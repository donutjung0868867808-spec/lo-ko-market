from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import user_community
from accounts.forms import ReportForm
from accounts.models import Report
from catalog.models import Product

from .forms import CancelOrderForm, CartCheckoutForm, CheckoutForm, OrderStatusForm
from .models import Order, OrderItem
from .services import (
    apply_coupon,
    cancel_unpaid_order,
    change_order_status,
    expire_stale_orders,
    reserve_order_stock,
    shipping_fee_for,
)


CART_SESSION_KEY = "cart"


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
    return (product.stock_quantity / step).to_integral_value(rounding=ROUND_FLOOR) * step


def cart_items(request):
    cart = request.session.get(CART_SESSION_KEY, {})
    products = Product.objects.select_related("seller", "community", "category").filter(
        pk__in=cart.keys(),
        status=Product.Status.ACTIVE,
    )
    items = []
    normalized_cart = {}
    total = Decimal("0.00")

    for product in products:
        if request.user.is_authenticated and product.seller_id == request.user.id:
            continue
        quantity = parse_quantity(cart.get(str(product.pk)), default=product.minimum_order_quantity, step=product.quantity_step)
        available = available_quantity(product)
        if available <= 0 or quantity <= 0:
            continue
        if quantity > available:
            quantity = available
        line_total = quantity * product.price
        total += line_total
        normalized_cart[str(product.pk)] = str(quantity)
        items.append({"product": product, "quantity": quantity, "line_total": line_total})

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


def can_manage_order(user, order):
    return user.is_owner or (user.is_farmer and order.seller_id == user.id) or (
        user.is_cooperative_staff and user_community(user) == order.community
    )


def buyer_initial(user):
    initial = {
        "shipping_name": user.display_name or user.get_full_name() or user.username,
        "shipping_phone": user.phone,
    }
    address = user.delivery_addresses.filter(is_default=True).first()
    if address:
        address_parts = [address.address_line]
        if address.subdistrict:
            address_parts.append(f"ตำบล/แขวง {address.subdistrict}")
        if address.district:
            address_parts.append(f"อำเภอ/เขต {address.district}")
        initial.update(
            {
                "shipping_name": address.recipient_name,
                "shipping_phone": address.phone,
                "shipping_address": " ".join(address_parts),
                "shipping_province": address.province,
                "shipping_postal_code": address.postal_code,
            }
        )
    return initial


def finalize_order(order, coupon_code=""):
    order.refresh_total()
    order.shipping_fee = shipping_fee_for(order)
    order.save(update_fields=["shipping_fee", "updated_at"])
    order.refresh_total()
    apply_coupon(order, coupon_code)
    return reserve_order_stock(order)


@login_required
def cart_detail(request):
    items, total = cart_items(request)
    form = CartCheckoutForm(initial=buyer_initial(request.user))
    return render(request, "orders/cart.html", {"items": items, "total": total, "form": form})


@login_required
def cart_add(request, product_id):
    product = get_object_or_404(Product, pk=product_id, status=Product.Status.ACTIVE)
    if product.seller_id == request.user.id:
        messages.info(request, "ไม่สามารถซื้อสินค้าจากร้านค้าของตัวเองได้")
        return redirect(product)
    if not request.user.can_buy and not request.user.is_owner:
        messages.error(request, "ตะกร้าสินค้าเปิดให้ผู้บริโภคทั่วไป")
        return redirect(product)
    if request.method == "POST":
        quantity = parse_quantity(request.POST.get("quantity"), default=product.minimum_order_quantity, step=product.quantity_step)
        if quantity <= 0:
            messages.warning(request, "กรุณาระบุจำนวนสินค้า")
            return redirect(product)
        cart = request.session.get(CART_SESSION_KEY, {})
        current_quantity = parse_quantity(cart.get(str(product.pk)), default=Decimal("0.00"), step=product.quantity_step)
        next_quantity = current_quantity + quantity
        available = available_quantity(product)
        if next_quantity > available:
            next_quantity = available
            messages.info(request, "จำนวนสินค้าในตะกร้าถูกปรับตามสต็อกที่มี")
        cart[str(product.pk)] = str(next_quantity)
        request.session[CART_SESSION_KEY] = cart
        request.session.modified = True
        messages.success(request, "เพิ่มสินค้าในตะกร้าแล้ว")
        return redirect("orders:cart")
    return redirect(product)


@login_required
def cart_update(request, product_id):
    product = get_object_or_404(Product, pk=product_id, status=Product.Status.ACTIVE)
    if request.method == "POST":
        quantity = parse_quantity(request.POST.get("quantity"), default=Decimal("0.00"), step=product.quantity_step)
        cart = request.session.get(CART_SESSION_KEY, {})
        if quantity <= 0:
            cart.pop(str(product.pk), None)
            messages.info(request, "นำสินค้าออกจากตะกร้าแล้ว")
        else:
            available = available_quantity(product)
            if quantity > available:
                quantity = available
                messages.info(request, "จำนวนสินค้าในตะกร้าถูกปรับตามสต็อกที่มี")
            cart[str(product.pk)] = str(quantity)
            messages.success(request, "อัปเดตตะกร้าแล้ว")
        request.session[CART_SESSION_KEY] = cart
        request.session.modified = True
    return redirect("orders:cart")


@login_required
def cart_remove(request, product_id):
    cart = request.session.get(CART_SESSION_KEY, {})
    cart.pop(str(product_id), None)
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

    form = CartCheckoutForm(request.POST or None, initial=buyer_initial(request.user))
    if request.method == "POST" and form.is_valid():
        cart = request.session.get(CART_SESSION_KEY, {})
        errors = []
        created_orders = []

        with transaction.atomic():
            products = Product.objects.select_for_update().select_related("seller", "community").filter(
                pk__in=cart.keys(),
                status=Product.Status.ACTIVE,
            )
            locked_items = []
            for product in products:
                quantity = parse_quantity(cart.get(str(product.pk)), default=Decimal("0.00"), step=product.quantity_step)
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
                locked_items.append({"product": product, "quantity": quantity})

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
                for group_index, grouped_items in enumerate(grouped_orders):
                    first_product = grouped_items[0]["product"]
                    order = Order.objects.create(
                        buyer=request.user,
                        seller=first_product.seller,
                        community=first_product.community,
                        shipping_name=form.cleaned_data["shipping_name"],
                        shipping_phone=form.cleaned_data["shipping_phone"],
                        shipping_address=form.cleaned_data["shipping_address"],
                        shipping_province=form.cleaned_data["shipping_province"],
                        shipping_postal_code=form.cleaned_data["shipping_postal_code"],
                        note=form.cleaned_data["note"],
                    )
                    for item in grouped_items:
                        product = item["product"]
                        OrderItem.objects.create(
                            order=order,
                            product=product,
                            product_name=product.name,
                            unit=product.unit,
                            quantity=item["quantity"],
                            unit_price=product.price,
                        )
                    try:
                        coupon_code = form.cleaned_data["coupon_code"] if group_index == 0 else ""
                        finalize_order(order, coupon_code)
                    except ValidationError as exc:
                        errors.append(exc.message)
                        transaction.set_rollback(True)
                        break
                    created_orders.append(order)

        if errors:
            for error in errors:
                form.add_error(None, error)
        else:
            request.session[CART_SESSION_KEY] = {}
            request.session.modified = True
            if len(created_orders) == 1:
                return redirect("payments:create_checkout", order_id=created_orders[0].pk)
            messages.success(request, f"สร้างคำสั่งซื้อ {len(created_orders)} รายการแล้ว กรุณาชำระเงินแยกตามผู้ขาย")
            return redirect("orders:order_list")

    items, total = cart_items(request)
    return render(request, "orders/cart.html", {"items": items, "total": total, "form": form})


@login_required
def checkout(request, product_id):
    if not request.user.can_buy and not request.user.is_owner:
        messages.error(request, "การสั่งซื้อเปิดให้ผู้บริโภคทั่วไป")
        return redirect("catalog:product_detail", pk=product_id)

    product = get_object_or_404(
        Product.objects.select_related("seller", "community"),
        pk=product_id,
        status=Product.Status.ACTIVE,
    )
    if product.seller_id == request.user.id:
        messages.info(request, "ไม่สามารถซื้อสินค้าจากร้านค้าของตัวเองได้")
        return redirect(product)
    requested_quantity = parse_quantity(
        request.GET.get("quantity"),
        default=product.minimum_order_quantity,
        step=product.quantity_step,
    )
    initial = {"quantity": requested_quantity, **buyer_initial(request.user)}
    form = CheckoutForm(request.POST or None, initial=initial, product=product)

    if request.method == "POST" and form.is_valid():
        quantity = form.cleaned_data["quantity"]
        with transaction.atomic():
            product = Product.objects.select_for_update().get(pk=product.pk)
            if quantity > available_quantity(product):
                form.add_error("quantity", "จำนวนสินค้าไม่พอ")
            else:
                order = Order.objects.create(
                    buyer=request.user,
                    seller=product.seller,
                    community=product.community,
                    shipping_name=form.cleaned_data["shipping_name"],
                    shipping_phone=form.cleaned_data["shipping_phone"],
                    shipping_address=form.cleaned_data["shipping_address"],
                    shipping_province=form.cleaned_data["shipping_province"],
                    shipping_postal_code=form.cleaned_data["shipping_postal_code"],
                    note=form.cleaned_data["note"],
                )
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    product_name=product.name,
                    unit=product.unit,
                    quantity=quantity,
                    unit_price=product.price,
                )
                try:
                    finalize_order(order, form.cleaned_data["coupon_code"])
                except ValidationError as exc:
                    form.add_error("coupon_code", exc.message)
                    transaction.set_rollback(True)
                else:
                    return redirect("payments:create_checkout", order_id=order.pk)

    return render(request, "orders/checkout.html", {"form": form, "product": product})


@login_required
def order_list(request):
    expire_stale_orders()
    if request.user.is_farmer:
        orders = Order.objects.filter(buyer=request.user).select_related("buyer", "seller", "community")
    else:
        orders = scoped_orders(request.user)
    orders = orders.prefetch_related("items__product")
    status_filter = request.GET.get("status", "all")
    status_groups = {
        "pending_payment": [Order.Status.PENDING_PAYMENT],
        "preparing": [Order.Status.PAID, Order.Status.CONFIRMED, Order.Status.PREPARING],
        "shipping": [Order.Status.SHIPPED],
        "completed": [Order.Status.COMPLETED],
        "cancelled": [Order.Status.CANCELLED, Order.Status.REFUNDED],
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
            "items", "status_history__changed_by", "payment__refunds"
        ),
        pk=pk,
    )
    if not can_view_order(request.user, order):
        messages.error(request, "คุณไม่มีสิทธิ์ดูคำสั่งซื้อนี้")
        return redirect("orders:order_list")
    return render(request, "orders/order_detail.html", {"order": order})


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

    form = OrderStatusForm(request.POST or None, instance=order)
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
