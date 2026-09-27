from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.utils.dateparse import parse_datetime

from accounts.decorators import user_community
from accounts.forms import ReportForm
from accounts.models import Report
from catalog.models import Product, ProductVariant

from .forms import CancelOrderForm, CartCheckoutForm, CheckoutForm, OrderStatusForm, SellerShipmentForm
from .models import Order, OrderItem, Shipment
from .services import (
    cancel_unpaid_order,
    change_order_status,
    expire_stale_orders,
    reserve_order_stock,
    ship_order,
    shipping_fee_for,
    shipping_fee_for_values,
)


CART_SESSION_KEY = "cart"
CHECKOUT_QUANTITY_SESSION_KEY = "checkout_quantities"


def parse_quantity(value, default=Decimal("1.00"), step=Decimal("0.50")):
    step = Decimal(str(step))
    fallback = Decimal(str(default))
    fallback = (fallback / step).to_integral_value(rounding=ROUND_CEILING) * step
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return fallback
    if quantity <= 0:
        return Decimal("0")
    if (quantity / step) != (quantity / step).to_integral_value():
        return fallback
    return quantity.quantize(Decimal("0.01"))


def available_quantity(product):
    """Return the largest orderable quantity that matches the product unit."""
    step = product.quantity_step
    return (product.orderable_quantity / step).to_integral_value(rounding=ROUND_FLOOR) * step


def cart_line_key(product_id, variant_id=None):
    return f"{product_id}:{variant_id}" if variant_id else str(product_id)


def parse_cart_line_key(value):
    product_id, separator, variant_id = str(value).partition(":")
    if not product_id.isdigit():
        return None
    if separator and not variant_id.isdigit():
        return None
    return int(product_id), int(variant_id) if separator else None


def active_variant_for_product(product, variant_id):
    variants = {variant.pk: variant for variant in product.variants.all()}
    if not variants:
        return None
    variant = variants.get(variant_id)
    return variant if variant and variant.is_active else None


def cart_items(request):
    cart = request.session.get(CART_SESSION_KEY, {})
    cart_lines = {
        key: parts
        for key, parts in (
            (key, parse_cart_line_key(key)) for key in cart
        )
        if parts
    }
    products = Product.objects.select_related("seller", "community", "category").prefetch_related(
        "variants"
    ).filter(
        pk__in={parts[0] for parts in cart_lines.values()},
        status=Product.Status.ACTIVE,
    )
    products_by_id = {product.pk: product for product in products}
    items = []
    normalized_cart = {}
    total = Decimal("0.00")

    for key, (product_id, variant_id) in cart_lines.items():
        product = products_by_id.get(product_id)
        if product is None:
            continue
        if request.user.is_authenticated and product.seller_id == request.user.id:
            continue
        variant = active_variant_for_product(product, variant_id)
        if product.variants.exists() and variant is None:
            continue
        quantity = parse_quantity(
            cart.get(key),
            default=product.minimum_order_quantity,
            step=product.quantity_step,
        )
        available = available_quantity(product)
        if available <= 0 or quantity <= 0:
            continue
        if quantity > available:
            quantity = available
        line_total = quantity * product.price
        total += line_total
        normalized_cart[key] = str(quantity)
        items.append(
            {
                "key": key,
                "product": product,
                "variant": variant,
                "quantity": quantity,
                "unit_price": product.price,
                "line_total": line_total,
            }
        )

    if normalized_cart != cart:
        request.session[CART_SESSION_KEY] = normalized_cart
        request.session.modified = True

    return items, total


def scoped_orders(user):
    orders = Order.objects.select_related("buyer", "seller", "community").prefetch_related("items")
    if user.is_owner:
        return orders
    if user.is_farmer:
        return orders.filter(seller=user)
    if user.is_cooperative_staff:
        community = user_community(user)
        return orders.filter(community=community) if community else orders.none()
    return orders.filter(buyer=user)


def can_view_order(user, order):
    if user.is_owner:
        return True
    if user.is_farmer and order.seller_id == user.id:
        return True
    if user.is_cooperative_staff and user_community(user) == order.community:
        return True
    return order.buyer_id == user.id


def tracking_events(order):
    """Normalize carrier checkpoints for a readable, newest-first delivery timeline."""
    try:
        shipment = order.shipment
    except Shipment.DoesNotExist:
        return []

    events = []
    for point in reversed(shipment.checkpoints):
        events.append(
            {
                "message": point.get("message") or "กำลังอัปเดตสถานะพัสดุ",
                "location": point.get("location", ""),
                "occurred_at": parse_datetime(point.get("time", "")),
                "time_label": point.get("time", ""),
            }
        )
    if not events:
        events.append(
            {
                "message": shipment.status_label,
                "location": "",
                "occurred_at": shipment.provider_updated_at,
                "time_label": "",
            }
        )
    return events


def can_manage_order(user, order):
    return user.is_owner or (user.is_farmer and order.seller_id == user.id) or (
        user.is_cooperative_staff and user_community(user) == order.community
    )


def buyer_initial(user):
    initial = {
        "shipping_name": user.display_name or user.get_full_name() or user.username,
        "shipping_phone": user.phone,
    }
    address = default_delivery_address(user)
    if address:
        initial.update(shipping_details_from_address(address))
    return initial


def default_delivery_address(user):
    return user.delivery_addresses.order_by("-is_default", "-updated_at").first()


def shipping_details_from_address(address):
    address_parts = [address.address_line]
    if address.subdistrict:
        address_parts.append(f"ตำบล/แขวง {address.subdistrict}")
    if address.district:
        address_parts.append(f"อำเภอ/เขต {address.district}")
    return {
        "shipping_name": address.recipient_name,
        "shipping_phone": address.phone,
        "shipping_address": " ".join(address_parts),
        "shipping_province": address.province,
        "shipping_postal_code": address.postal_code,
    }


def preview_shipping_fee(items, province):
    if not province:
        return Decimal("0.00")

    grouped_items = {}
    for item in items:
        product = item["product"]
        quantity = Decimal(item["quantity"])
        group = grouped_items.setdefault(
            (product.seller_id, product.community_id),
            {"subtotal": Decimal("0.00"), "weight_grams": Decimal("0.00")},
        )
        group["subtotal"] += product.price * quantity
        group["weight_grams"] += Decimal(product.weight_grams or 0) * quantity

    return sum(
        (
            shipping_fee_for_values(
                province,
                group["subtotal"],
                group["weight_grams"],
            )
            for group in grouped_items.values()
        ),
        Decimal("0.00"),
    )


def checkout_payment_redirect(order, payment_method):
    url = reverse("payments:create_checkout", args=[order.pk])
    if payment_method == "promptpay":
        url = f"{url}?payment_method=promptpay"
    return redirect(url)


def finalize_order(order):
    order.refresh_total()
    order.shipping_fee = shipping_fee_for(order)
    order.save(update_fields=["shipping_fee", "updated_at"])
    order.refresh_total()
    return reserve_order_stock(order)


@login_required
def cart_detail(request):
    items, total = cart_items(request)
    return render(
        request,
        "orders/cart.html",
        {
            "items": items,
            "total": total,
            "selected_item_keys": {item["key"] for item in items},
        },
    )


@login_required
def cart_add(request, product_id):
    product = get_object_or_404(
        Product.objects.prefetch_related("variants"),
        pk=product_id,
        status=Product.Status.ACTIVE,
    )
    if product.seller_id == request.user.id:
        messages.info(request, "ไม่สามารถซื้อสินค้าจากร้านค้าของตัวเองได้")
        return redirect(product)
    if not request.user.can_buy and not request.user.is_owner:
        messages.error(request, "ตะกร้าสินค้าเปิดให้ผู้บริโภคทั่วไป")
        return redirect(product)
    if request.method == "POST":
        variant_id = request.POST.get("variant_id", "").strip()
        variant = active_variant_for_product(
            product,
            int(variant_id) if variant_id.isdigit() else None,
        )
        if product.variants.exists() and variant is None:
            messages.warning(request, "กรุณาเลือกตัวเลือกสินค้าที่เปิดขายอยู่")
            return redirect(product)
        quantity = parse_quantity(request.POST.get("quantity"), default=product.minimum_order_quantity, step=product.quantity_step)
        if quantity <= 0:
            messages.warning(request, "กรุณาระบุจำนวนสินค้า")
            return redirect(product)
        cart = request.session.get(CART_SESSION_KEY, {})
        line_key = cart_line_key(product.pk, variant.pk if variant else None)
        current_quantity = parse_quantity(cart.get(line_key), default=Decimal("0.00"), step=product.quantity_step)
        next_quantity = current_quantity + quantity
        available = available_quantity(product)
        if next_quantity > available:
            next_quantity = available
            messages.info(request, "จำนวนสินค้าในตะกร้าถูกปรับตามสต็อกที่มี")
        cart[line_key] = str(next_quantity)
        request.session[CART_SESSION_KEY] = cart
        request.session.modified = True
        messages.success(request, "เพิ่มสินค้าในตะกร้าแล้ว")
        return redirect("orders:cart")
    return redirect(product)


@login_required
@require_POST
def order_reorder(request, pk):
    order = get_object_or_404(
        Order.objects.prefetch_related("items__product__variants"),
        pk=pk,
        buyer=request.user,
    )
    if not request.user.can_buy and not request.user.is_owner:
        messages.error(request, "บัญชีนี้ไม่สามารถสั่งซื้อสินค้าได้")
        return redirect("orders:order_list")

    cart = request.session.get(CART_SESSION_KEY, {})
    added_count = 0
    unavailable_count = 0

    for item in order.items.all():
        product = item.product
        variant = active_variant_for_product(product, item.variant_id)
        if (
            product.status != Product.Status.ACTIVE
            or product.seller_id == request.user.id
            or available_quantity(product) <= 0
            or (product.variants.exists() and variant is None)
        ):
            unavailable_count += 1
            continue

        quantity = parse_quantity(
            item.quantity,
            default=product.minimum_order_quantity,
            step=product.quantity_step,
        )
        quantity = max(quantity, product.minimum_order_quantity)
        line_key = cart_line_key(product.pk, variant.pk if variant else None)
        current_quantity = parse_quantity(
            cart.get(line_key),
            default=Decimal("0.00"),
            step=product.quantity_step,
        )
        next_quantity = min(current_quantity + quantity, available_quantity(product))
        if next_quantity <= current_quantity:
            unavailable_count += 1
            continue

        cart[line_key] = str(next_quantity)
        added_count += 1

    request.session[CART_SESSION_KEY] = cart
    request.session.modified = True

    if added_count:
        messages.success(request, f"เพิ่มสินค้า {added_count} รายการลงตะกร้าแล้ว")
    if unavailable_count:
        messages.warning(request, f"มีสินค้า {unavailable_count} รายการที่ไม่พร้อมสั่งซื้อ")
    return redirect("orders:cart")


@login_required
def cart_update(request, product_id):
    product = get_object_or_404(
        Product.objects.prefetch_related("variants"),
        pk=product_id,
        status=Product.Status.ACTIVE,
    )
    if request.method == "POST":
        variant_id = request.POST.get("variant_id", "").strip()
        variant = active_variant_for_product(
            product,
            int(variant_id) if variant_id.isdigit() else None,
        )
        if product.variants.exists() and variant is None:
            messages.warning(request, "ตัวเลือกสินค้านี้ไม่พร้อมจำหน่ายแล้ว")
            return redirect("orders:cart")
        line_key = cart_line_key(product.pk, variant.pk if variant else None)
        quantity = parse_quantity(request.POST.get("quantity"), default=Decimal("0.00"), step=product.quantity_step)
        cart = request.session.get(CART_SESSION_KEY, {})
        if quantity <= 0:
            cart.pop(line_key, None)
            messages.info(request, "นำสินค้าออกจากตะกร้าแล้ว")
        else:
            available = available_quantity(product)
            if quantity > available:
                quantity = available
                messages.info(request, "จำนวนสินค้าในตะกร้าถูกปรับตามสต็อกที่มี")
            cart[line_key] = str(quantity)
            messages.success(request, "อัปเดตตะกร้าแล้ว")
        request.session[CART_SESSION_KEY] = cart
        request.session.modified = True
    return redirect("orders:cart")


@login_required
def cart_remove(request, product_id):
    cart = request.session.get(CART_SESSION_KEY, {})
    variant_id = request.POST.get("variant_id", "").strip()
    line_key = cart_line_key(
        product_id,
        int(variant_id) if variant_id.isdigit() else None,
    )
    cart.pop(line_key, None)
    request.session[CART_SESSION_KEY] = cart
    request.session.modified = True
    messages.info(request, "นำสินค้าออกจากตะกร้าแล้ว")
    return redirect("orders:cart")


@login_required
def cart_checkout(request):
    if not request.user.can_buy and not request.user.is_owner:
        messages.error(request, "การสั่งซื้อเปิดให้ผู้บริโภคทั่วไป")
        return redirect("orders:cart")

    items, total = cart_items(request)
    if not items:
        messages.warning(request, "ยังไม่มีสินค้าในตะกร้า")
        return redirect("orders:cart")

    selection_data = request.POST if request.method == "POST" else request.GET
    selection_submitted = selection_data.get("cart_selection") == "1"
    if request.method == "GET" and selection_submitted:
        cart = request.session.get(CART_SESSION_KEY, {})
        cart_changed = False
        for item in items:
            product = item["product"]
            line_key = item["key"]
            requested_quantity = selection_data.get(f"cart_quantity_{line_key}")
            if requested_quantity is None:
                continue
            quantity = parse_quantity(
                requested_quantity,
                default=item["quantity"],
                step=product.quantity_step,
            )
            quantity = min(quantity, available_quantity(product))
            if quantity <= 0:
                cart.pop(line_key, None)
            else:
                cart[line_key] = str(quantity)
            cart_changed = True
        if cart_changed:
            request.session[CART_SESSION_KEY] = cart
            request.session.modified = True
            items, total = cart_items(request)

    selected_item_keys = set(selection_data.getlist("selected_items"))
    if selection_submitted:
        selected_items = [item for item in items if item["key"] in selected_item_keys]
        total = sum((item["line_total"] for item in selected_items), Decimal("0.00"))
    else:
        # Keep legacy checkout posts working while the cart UI submits an explicit selection.
        selected_items = items
        selected_item_keys = {item["key"] for item in items}

    delivery_address = default_delivery_address(request.user)
    form = CartCheckoutForm(request.POST or None, initial=buyer_initial(request.user))
    preview_shipping = preview_shipping_fee(
        selected_items,
        delivery_address.province if delivery_address else "",
    )
    preview_discount = Decimal("0.00")
    preview_grand_total = total + preview_shipping - preview_discount
    if request.method == "GET":
        if not selection_submitted or not selected_items:
            messages.warning(request, "กรุณาเลือกสินค้าอย่างน้อย 1 รายการ")
            return redirect("orders:cart")
        return render(
            request,
            "orders/cart_checkout.html",
            {
                "items": selected_items,
                "total": total,
                "form": form,
                "delivery_address": delivery_address,
                "preview_shipping": preview_shipping,
                "preview_discount": preview_discount,
                "preview_grand_total": preview_grand_total,
            },
        )

    if selection_submitted and not selected_items:
        form.add_error(None, "กรุณาเลือกสินค้าอย่างน้อย 1 รายการ")
    elif not delivery_address:
        form.add_error(None, "กรุณาเพิ่มที่อยู่จัดส่งก่อนยืนยันคำสั่งซื้อ")
    elif form.is_valid():
        shipping_details = shipping_details_from_address(delivery_address)
        cart = request.session.get(CART_SESSION_KEY, {})
        errors = []
        created_orders = []

        with transaction.atomic():
            products = Product.objects.select_for_update().select_related("seller", "community").prefetch_related(
                "variants"
            ).filter(
                pk__in={item["product"].pk for item in selected_items},
                status=Product.Status.ACTIVE,
            )
            products_by_id = {product.pk: product for product in products}
            locked_items = []
            for cart_item in selected_items:
                product = products_by_id.get(cart_item["product"].pk)
                if product is None:
                    errors.append("มีสินค้าในตะกร้าที่ไม่พร้อมจำหน่ายแล้ว")
                    continue
                variant_id = cart_item["variant"].pk if cart_item["variant"] else None
                variant = active_variant_for_product(product, variant_id)
                if product.variants.exists() and variant is None:
                    errors.append(f"ตัวเลือกของ {product.name} ไม่พร้อมจำหน่ายแล้ว")
                    continue
                quantity = parse_quantity(
                    cart.get(cart_item["key"]),
                    default=Decimal("0.00"),
                    step=product.quantity_step,
                )
                if quantity <= 0:
                    continue
                if quantity > available_quantity(product):
                    errors.append(f"{product.name} มีสินค้าไม่พอ")
                    continue
                if quantity < product.minimum_order_quantity:
                    errors.append(
                        f"{product.name} ต้องสั่งอย่างน้อย {product.minimum_order_quantity} {product.get_unit_display()}"
                    )
                    continue
                locked_items.append(
                    {
                        "key": cart_item["key"],
                        "product": product,
                        "variant": variant,
                        "quantity": quantity,
                    }
                )

            if not locked_items:
                errors.append("ไม่พบสินค้าที่พร้อมสั่งซื้อ")

            if not errors:
                grouped = {}
                for item in locked_items:
                    product = item["product"]
                    grouped.setdefault((product.seller_id, product.community_id), []).append(item)

                grouped_orders = sorted(
                    grouped.values(),
                    key=lambda values: sum(
                        (item["product"].price * item["quantity"] for item in values),
                        Decimal("0.00"),
                    ),
                    reverse=True,
                )
                for grouped_items in grouped_orders:
                    first_product = grouped_items[0]["product"]
                    order = Order.objects.create(
                        buyer=request.user,
                        seller=first_product.seller,
                        community=first_product.community,
                        **shipping_details,
                        note=form.cleaned_data["note"],
                    )
                    for item in grouped_items:
                        product = item["product"]
                        OrderItem.objects.create(
                            order=order,
                            product=product,
                            variant=item["variant"],
                            product_name=product.name,
                            variant_name=item["variant"].name if item["variant"] else "",
                            unit=product.unit,
                            quantity=item["quantity"],
                            unit_price=product.price,
                        )
                    try:
                        finalize_order(order)
                    except ValidationError as exc:
                        errors.append(exc.message)
                        transaction.set_rollback(True)
                        break
                    created_orders.append(order)

        if errors:
            for error in errors:
                form.add_error(None, error)
        else:
            for item in locked_items:
                cart.pop(item["key"], None)
            request.session[CART_SESSION_KEY] = cart
            request.session.modified = True
            if len(created_orders) == 1:
                return checkout_payment_redirect(
                    created_orders[0],
                    form.cleaned_data.get("payment_method") or "card",
                )
            messages.success(request, f"สร้างคำสั่งซื้อ {len(created_orders)} รายการแล้ว กรุณาชำระเงินแยกตามผู้ขาย")
            return redirect("orders:order_list")

    return render(
        request,
        "orders/cart_checkout.html",
        {
            "items": selected_items,
            "total": total,
            "form": form,
            "delivery_address": delivery_address,
            "preview_shipping": preview_shipping,
            "preview_discount": preview_discount,
            "preview_grand_total": preview_grand_total,
        },
    )


@login_required
def checkout(request, product_id):
    if not request.user.can_buy and not request.user.is_owner:
        messages.error(request, "การสั่งซื้อเปิดให้ผู้บริโภคทั่วไป")
        return redirect("catalog:product_detail", pk=product_id)

    product = get_object_or_404(
        Product.objects.select_related("seller", "community").prefetch_related("variants"),
        pk=product_id,
        status=Product.Status.ACTIVE,
    )
    if product.seller_id == request.user.id:
        messages.info(request, "ไม่สามารถซื้อสินค้าจากร้านค้าของตัวเองได้")
        return redirect(product)
    variant_id = (
        request.GET.get("variant", "").strip()
        if request.method == "GET"
        else request.POST.get("variant_id", "").strip()
    )
    variant = active_variant_for_product(
        product,
        int(variant_id) if variant_id.isdigit() else None,
    )
    if product.variants.exists() and variant is None:
        messages.warning(request, "กรุณาเลือกตัวเลือกสินค้าที่เปิดขายอยู่ก่อนทำการสั่งซื้อ")
        return redirect(product)

    checkout_quantities = request.session.get(CHECKOUT_QUANTITY_SESSION_KEY, {})
    checkout_key = cart_line_key(product.pk, variant.pk if variant else None)
    if request.method == "GET":
        selected_quantity = parse_quantity(
            request.GET.get("quantity"),
            default=product.minimum_order_quantity,
            step=product.quantity_step,
        )
        selected_quantity = min(selected_quantity, available_quantity(product))
        checkout_quantities[checkout_key] = str(selected_quantity)
        request.session[CHECKOUT_QUANTITY_SESSION_KEY] = checkout_quantities
        request.session.modified = True
    else:
        selected_quantity = parse_quantity(
            checkout_quantities.get(checkout_key),
            default=product.minimum_order_quantity,
            step=product.quantity_step,
        )

    delivery_address = default_delivery_address(request.user)
    initial = {"quantity": selected_quantity, **buyer_initial(request.user)}
    form_data = request.POST.copy() if request.method == "POST" else None
    if form_data is not None:
        # Keep the quantity chosen before checkout; never trust a browser-side edit here.
        form_data["quantity"] = str(selected_quantity)
    form = CheckoutForm(form_data, initial=initial, product=product)
    preview_total = product.price * selected_quantity
    preview_shipping = preview_shipping_fee(
        [{"product": product, "quantity": selected_quantity}],
        delivery_address.province if delivery_address else "",
    )
    preview_discount = Decimal("0.00")
    preview_grand_total = preview_total + preview_shipping - preview_discount

    if request.method == "POST" and not delivery_address:
        form.add_error(None, "กรุณาเพิ่มที่อยู่จัดส่งก่อนยืนยันคำสั่งซื้อ")
    elif request.method == "POST" and form.is_valid():
        quantity = form.cleaned_data["quantity"]
        shipping_details = shipping_details_from_address(delivery_address)
        with transaction.atomic():
            product = Product.objects.select_for_update().prefetch_related("variants").get(
                pk=product.pk
            )
            variant = active_variant_for_product(product, variant.pk if variant else None)
            if product.variants.exists() and variant is None:
                form.add_error(None, "ตัวเลือกสินค้านี้ไม่พร้อมจำหน่ายแล้ว")
            if quantity > available_quantity(product):
                form.add_error("quantity", "จำนวนสินค้าไม่พอ")
            elif not form.errors:
                order = Order.objects.create(
                    buyer=request.user,
                    seller=product.seller,
                    community=product.community,
                    **shipping_details,
                    note=form.cleaned_data["note"],
                )
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    variant=variant,
                    product_name=product.name,
                    variant_name=variant.name if variant else "",
                    unit=product.unit,
                    quantity=quantity,
                    unit_price=product.price,
                )
                try:
                    finalize_order(order)
                except ValidationError as exc:
                    form.add_error(None, exc.message)
                    transaction.set_rollback(True)
                else:
                    checkout_quantities.pop(checkout_key, None)
                    request.session[CHECKOUT_QUANTITY_SESSION_KEY] = checkout_quantities
                    request.session.modified = True
                    return checkout_payment_redirect(
                        order,
                        form.cleaned_data.get("payment_method") or "card",
                    )

    return render(
        request,
        "orders/checkout.html",
        {
            "form": form,
            "product": product,
            "variant": variant,
            "preview_quantity": selected_quantity,
            "preview_total": preview_total,
            "preview_shipping": preview_shipping,
            "preview_discount": preview_discount,
            "preview_grand_total": preview_grand_total,
            "delivery_address": delivery_address,
        },
    )


@login_required
def order_list(request):
    expire_stale_orders()
    if request.user.is_farmer:
        orders = Order.objects.filter(buyer=request.user).select_related("buyer", "seller", "community")
    else:
        orders = scoped_orders(request.user)
    orders = orders.select_related("seller__farmer_profile", "shipment").prefetch_related("items__product")
    status_filter = request.GET.get("status", "all")
    status_groups = {
        "pending_payment": [Order.Status.PENDING_PAYMENT],
        "preparing": [Order.Status.PAID, Order.Status.CONFIRMED, Order.Status.PREPARING],
        "shipping": [Order.Status.SHIPPED],
        "completed": [Order.Status.COMPLETED],
        "cancelled": [Order.Status.CANCELLED],
        "refunded": [Order.Status.REFUNDED],
    }
    if status_filter in status_groups:
        orders = orders.filter(status__in=status_groups[status_filter])
    else:
        status_filter = "all"

    query = request.GET.get("q", "").strip()
    search_by = request.GET.get("search_by", "reference")
    payment_filter = request.GET.get("payment", "all")
    if query:
        if search_by == "buyer" and request.user.is_farmer:
            orders = orders.filter(Q(buyer__display_name__icontains=query) | Q(buyer__username__icontains=query))
        else:
            orders = orders.filter(
                Q(reference__icontains=query)
                | Q(seller__display_name__icontains=query)
                | Q(seller__username__icontains=query)
                | Q(items__product_name__icontains=query)
            ).distinct()

    payment_groups = {
        "paid": Order.PaymentStatus.PAID,
        "unpaid": Order.PaymentStatus.UNPAID,
        "failed": Order.PaymentStatus.FAILED,
        "refunded": Order.PaymentStatus.REFUNDED,
    }
    if payment_filter in payment_groups:
        orders = orders.filter(payment_status=payment_groups[payment_filter])
    else:
        payment_filter = "all"

    return render(
        request,
        "orders/order_list.html",
        {
            "orders": orders,
            "account_section": "orders",
            "status_filter": status_filter,
            "order_query": query,
            "search_by": search_by,
            "payment_filter": payment_filter,
            "is_seller_order_view": False,
        },
    )


@login_required
def order_detail(request, pk):
    order = get_object_or_404(
        Order.objects.select_related("buyer", "seller", "community", "payment").prefetch_related(
            "items__product", "status_history__changed_by", "payment__refunds"
        ),
        pk=pk,
    )
    if not can_view_order(request.user, order):
        messages.error(request, "คุณไม่มีสิทธิ์ดูคำสั่งซื้อนี้")
        return redirect("orders:order_list")
    return render(request, "orders/order_detail.html", {"order": order})


@login_required
def order_tracking(request, pk):
    order = get_object_or_404(
        Order.objects.select_related("buyer", "seller", "seller__farmer_profile", "community", "shipment").prefetch_related(
            "items__product", "status_history__changed_by"
        ),
        pk=pk,
    )
    if not can_view_order(request.user, order):
        messages.error(request, "คุณไม่มีสิทธิ์ดูข้อมูลการติดตามพัสดุนี้")
        return redirect("orders:order_list")
    return render(
        request,
        "orders/order_tracking.html",
        {"order": order, "tracking_events": tracking_events(order)},
    )


@login_required
def order_receipt(request, pk):
    order = get_object_or_404(
        Order.objects.select_related("buyer", "seller", "community", "payment").prefetch_related("items"),
        pk=pk,
    )
    if not can_view_order(request.user, order):
        messages.error(request, "คุณไม่มีสิทธิ์ดูใบเสร็จของคำสั่งซื้อนี้")
        return redirect("orders:order_list")
    if order.payment_status != Order.PaymentStatus.PAID:
        messages.error(request, "ใบเสร็จจะออกให้หลังชำระเงินสำเร็จ")
        return redirect(order)
    return render(request, "orders/order_receipt.html", {"order": order})


@login_required
def order_update_status(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if not can_manage_order(request.user, order):
        messages.error(request, "คุณไม่มีสิทธิ์ปรับสถานะคำสั่งซื้อนี้")
        return redirect(order)
    is_community_staff = request.user.is_cooperative_staff and not request.user.is_owner
    if is_community_staff and order.status not in {
        Order.Status.PAID,
        Order.Status.CONFIRMED,
    }:
        messages.error(
            request,
            "เจ้าหน้าที่ชุมชนปรับได้เฉพาะขั้นตอนยืนยันและเตรียมสินค้า",
        )
        return redirect(order)

    seller_quick_ship = request.user == order.seller and order.can_seller_mark_shipped
    if seller_quick_ship:
        form = SellerShipmentForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            try:
                ship_order(
                    order,
                    request.user,
                    carrier=form.cleaned_data["shipping_carrier"],
                    tracking_number=form.cleaned_data["tracking_number"],
                )
            except ValidationError as exc:
                form.add_error(None, exc.message)
            else:
                messages.success(request, f"แจ้งจัดส่ง {order.reference} แล้ว ผู้ซื้อจะได้รับเลขพัสดุทันที")
                return redirect(order)
        return render(
            request,
            "orders/order_status_form.html",
            {"form": form, "order": order, "seller_quick_ship": True},
        )

    form = OrderStatusForm(request.POST or None, instance=order)
    if is_community_staff:
        allowed_statuses = {Order.Status.CONFIRMED, Order.Status.PREPARING}
        form.fields["status"].choices = [
            choice
            for choice in form.fields["status"].choices
            if choice[0] in allowed_statuses
        ]
    if request.method == "POST" and form.is_valid():
        order.refresh_from_db()
        try:
            change_order_status(
                order,
                form.cleaned_data["status"],
                request.user,
                note=form.cleaned_data["status_note"],
                carrier=form.cleaned_data.get("shipping_carrier", ""),
                tracking_number=form.cleaned_data.get("tracking_number", ""),
            )
        except ValidationError as exc:
            form.add_error(None, exc.message)
        else:
            messages.success(request, "อัปเดตสถานะคำสั่งซื้อแล้ว")
            return redirect(order)

    return render(request, "orders/order_status_form.html", {"form": form, "order": order})


@login_required
@require_POST
def seller_ship_order(request, pk):
    order = get_object_or_404(Order, pk=pk, seller=request.user)
    if not request.user.is_farmer:
        messages.error(request, "เฉพาะผู้ขายเท่านั้นที่สามารถแจ้งจัดส่งพัสดุได้")
        return redirect(order)

    form = SellerShipmentForm(request.POST)
    if form.is_valid():
        try:
            ship_order(
                order,
                request.user,
                carrier=form.cleaned_data["shipping_carrier"],
                tracking_number=form.cleaned_data["tracking_number"],
            )
        except ValidationError as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, f"แจ้งจัดส่ง {order.reference} แล้ว ผู้ซื้อจะได้รับเลขพัสดุทันที")
    else:
        messages.error(request, "กรุณาระบุบริษัทขนส่งและเลขติดตามพัสดุ")
    return redirect(f"{reverse('accounts:farmer_shop_center')}?section=orders&status=preparing")


@login_required
def cancel_order(request, pk):
    order = get_object_or_404(Order, pk=pk, buyer=request.user)
    form = CancelOrderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            cancel_unpaid_order(
                order,
                changed_by=request.user,
                note=f"ผู้ซื้อยกเลิก: {form.cleaned_data['reason']}",
            )
        except ValidationError as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, "ยกเลิกคำสั่งซื้อและคืนสต็อกแล้ว")
            return redirect(order)
    return render(request, "orders/order_cancel_form.html", {"form": form, "order": order})

@login_required
@require_POST
def confirm_received(request, pk):
    order = get_object_or_404(Order, pk=pk, buyer=request.user)
    if request.method == "POST":
        try:
            change_order_status(order, Order.Status.COMPLETED, request.user, note="ผู้ซื้อยืนยันว่าได้รับสินค้าแล้ว")
        except ValidationError as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, "ยืนยันการรับสินค้าแล้ว")
    return redirect(order)


@login_required
def report_buyer(request, pk):
    order = get_object_or_404(Order.objects.select_related("buyer", "seller", "community"), pk=pk)
    if not can_manage_order(request.user, order):
        messages.error(request, "รายงานผู้ซื้อได้เฉพาะผู้ขายของคำสั่งซื้อนี้")
        return redirect(order)

    form = ReportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        report = form.save(commit=False)
        report.reporter = request.user
        report.target_type = Report.TargetType.BUYER
        report.reported_user = order.buyer
        report.order = order
        report.community = order.community
        report.save()
        messages.success(request, "ส่งรายงานผู้ซื้อแล้ว")
        return redirect(order)
    return render(request, "orders/report_buyer.html", {"form": form, "order": order})
