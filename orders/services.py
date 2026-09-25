from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import AuditEvent
from accounts.services import notify_user
from catalog.models import Product, StockMovement
from catalog.services import notify_low_stock

from .models import CouponRedemption, Order, OrderStatusHistory, ShippingRate


ALLOWED_STATUS_TRANSITIONS = {
    Order.Status.PENDING_PAYMENT: {Order.Status.CANCELLED},
    Order.Status.PAID: {Order.Status.CONFIRMED},
    Order.Status.CONFIRMED: {Order.Status.PREPARING, Order.Status.CANCELLED},
    Order.Status.PREPARING: {Order.Status.SHIPPED, Order.Status.CANCELLED},
    Order.Status.SHIPPED: {Order.Status.COMPLETED},
    Order.Status.COMPLETED: set(),
    Order.Status.CANCELLED: set(),
    Order.Status.REFUNDED: set(),
}


def shipping_fee_for(order):
    subtotal = Decimal(order.subtotal)
    rule = ShippingRate.objects.filter(
        province__iexact=order.shipping_province.strip(),
        is_active=True,
    ).first()
    if rule is None:
        rule = ShippingRate.objects.filter(province="", is_active=True).first()

    if rule is None:
        threshold = Decimal(settings.FREE_SHIPPING_THRESHOLD)
        return Decimal("0.00") if subtotal >= threshold else Decimal(settings.FLAT_SHIPPING_FEE)
    if rule.free_shipping_threshold is not None and subtotal >= rule.free_shipping_threshold:
        return Decimal("0.00")

    weight_grams = sum(
        (
            Decimal(item.product.weight_grams or 0) * item.quantity
            for item in order.items.select_related("product")
        ),
        Decimal("0"),
    )
    weight_kg = weight_grams / Decimal("1000")
    return (rule.base_fee + (rule.fee_per_kg * weight_kg)).quantize(Decimal("0.01"))

@transaction.atomic
def release_coupon(order):
    redemption = CouponRedemption.objects.select_for_update().filter(order=order, active=True).first()
    if redemption:
        redemption.active = False
        redemption.released_at = timezone.now()
        redemption.save(update_fields=["active", "released_at"])
    return redemption


@transaction.atomic
def reserve_order_stock(order):
    order = Order.objects.select_for_update().prefetch_related("items").get(pk=order.pk)
    if order.stock_reserved:
        return order
    if order.payment_status == Order.PaymentStatus.PAID:
        raise ValidationError("คำสั่งซื้อนี้ชำระเงินแล้ว")

    locked_products = {}
    for item in order.items.all():
        product = locked_products.get(item.product_id)
        if product is None:
            product = Product.objects.select_for_update().get(pk=item.product_id)
            locked_products[item.product_id] = product
        if product.status != Product.Status.ACTIVE or product.stock_quantity < item.quantity:
            raise ValidationError(f"สินค้า {product.name} มีจำนวนไม่เพียงพอ")
        if item.quantity < product.minimum_order_quantity:
            raise ValidationError(
                f"สินค้า {product.name} ต้องสั่งอย่างน้อย {product.minimum_order_quantity} {product.get_unit_display()}"
            )

    for item in order.items.all():
        product = locked_products[item.product_id]
        product.stock_quantity -= item.quantity
        product.save(update_fields=["stock_quantity", "updated_at"])
        transaction.on_commit(lambda product_id=product.pk: notify_low_stock(product_id))
        StockMovement.objects.create(
            product=product,
            order=order,
            movement_type=StockMovement.MovementType.RESERVE,
            quantity_change=-item.quantity,
            balance_after=product.stock_quantity,
            note="จองสินค้าเพื่อรอชำระเงิน",
        )

    order.stock_reserved = True
    order.stock_released_at = None
    order.save(update_fields=["stock_reserved", "stock_released_at", "updated_at"])
    OrderStatusHistory.objects.get_or_create(
        order=order,
        status=order.status,
        defaults={"note": "สร้างคำสั่งซื้อและจองสินค้า"},
    )
    return order


@transaction.atomic
def release_order_stock(order, note="คืนสต็อกจากคำสั่งซื้อ"):
    order = Order.objects.select_for_update().prefetch_related("items").get(pk=order.pk)
    if not order.stock_reserved or order.stock_released_at:
        return order
    if order.payment_status == Order.PaymentStatus.PAID:
        raise ValidationError("ต้องคืนเงินก่อนคืนสต็อกของคำสั่งซื้อที่ชำระแล้ว")

    for item in order.items.all():
        product = Product.objects.select_for_update().get(pk=item.product_id)
        product.stock_quantity += item.quantity
        product.save(update_fields=["stock_quantity", "updated_at"])
        transaction.on_commit(lambda product_id=product.pk: notify_low_stock(product_id))
        StockMovement.objects.create(
            product=product,
            order=order,
            movement_type=StockMovement.MovementType.RELEASE,
            quantity_change=item.quantity,
            balance_after=product.stock_quantity,
            note=note,
        )

    order.stock_reserved = False
    order.stock_released_at = timezone.now()
    order.save(update_fields=["stock_reserved", "stock_released_at", "updated_at"])
    return order


@transaction.atomic
def restock_refunded_order(order, changed_by=None):
    order = Order.objects.select_for_update().prefetch_related("items").get(pk=order.pk)
    if order.stock_reserved and not order.stock_released_at:
        for item in order.items.all():
            product = Product.objects.select_for_update().get(pk=item.product_id)
            product.stock_quantity += item.quantity
            product.save(update_fields=["stock_quantity", "updated_at"])
            StockMovement.objects.create(
                product=product,
                order=order,
                movement_type=StockMovement.MovementType.RELEASE,
                quantity_change=item.quantity,
                balance_after=product.stock_quantity,
                note="คืนสต็อกจากการคืนเงินเต็มจำนวน",
            )
        order.stock_reserved = False
        order.stock_released_at = timezone.now()

    order.status = Order.Status.REFUNDED
    order.payment_status = Order.PaymentStatus.REFUNDED
    order.save(
        update_fields=[
            "stock_reserved",
            "stock_released_at",
            "status",
            "payment_status",
            "updated_at",
        ]
    )
    OrderStatusHistory.objects.create(
        order=order,
        status=Order.Status.REFUNDED,
        note="คืนเงินเต็มจำนวนแล้ว",
        changed_by=changed_by,
    )
    return order


@transaction.atomic
def cancel_unpaid_order(order, changed_by=None, note="ยกเลิกคำสั่งซื้อ"):
    from payments.models import Payment

    payment = Payment.objects.select_for_update().filter(order_id=order.pk).first()
    order = Order.objects.select_for_update().select_related("seller").get(pk=order.pk)
    if order.status == Order.Status.CANCELLED:
        return order
    before_status = order.status
    if order.payment_status == Order.PaymentStatus.PAID or (
        payment and payment.status == Payment.Status.PAID
    ):
        raise ValidationError("คำสั่งซื้อที่ชำระแล้วต้องดำเนินการคืนเงิน")

    release_order_stock(order, note)
    release_coupon(order)
    order.status = Order.Status.CANCELLED
    order.cancelled_at = timezone.now()
    order.save(update_fields=["status", "cancelled_at", "updated_at"])
    OrderStatusHistory.objects.create(
        order=order,
        status=Order.Status.CANCELLED,
        note=note,
        changed_by=changed_by,
    )
    AuditEvent.objects.create(
        actor=changed_by,
        action=AuditEvent.Action.STATUS,
        target_type=order._meta.label,
        target_id=str(order.pk),
        description=note,
        before={"status": before_status},
        after={"status": order.status},
        community=order.community,
    )
    transaction.on_commit(
        lambda: notify_user(
            order.seller,
            f"คำสั่งซื้อ {order.reference} ถูกยกเลิก",
            note,
            order.get_absolute_url(),
        )
    )
    return order


def expire_stale_orders():
    stale = Order.objects.filter(
        status=Order.Status.PENDING_PAYMENT,
        payment_status__in=[Order.PaymentStatus.UNPAID, Order.PaymentStatus.PROCESSING, Order.PaymentStatus.FAILED],
        expires_at__lte=timezone.now(),
        stock_reserved=True,
    )
    count = 0
    for order in stale.iterator():
        try:
            cancel_unpaid_order(order, note="หมดเวลาชำระเงิน")
        except ValidationError:
            continue
        count += 1
    return count


@transaction.atomic
def change_order_status(order, new_status, changed_by, note="", carrier="", tracking_number=""):
    from payments.models import Payment

    Payment.objects.select_for_update().filter(order_id=order.pk).first()
    order = Order.objects.select_for_update().select_related("buyer").get(pk=order.pk)
    before_status = order.status
    allowed = ALLOWED_STATUS_TRANSITIONS.get(order.status, set())
    if new_status not in allowed:
        raise ValidationError("ไม่สามารถเปลี่ยนไปยังสถานะที่เลือกได้")

    if new_status == Order.Status.SHIPPED:
        if not carrier or not tracking_number:
            raise ValidationError("กรุณาระบุบริษัทขนส่งและเลขติดตามพัสดุ")
        order.shipping_carrier = carrier
        order.tracking_number = tracking_number
        order.shipped_at = timezone.now()
    elif new_status == Order.Status.COMPLETED:
        order.delivered_at = timezone.now()
    elif new_status == Order.Status.CANCELLED:
        if order.payment_status == Order.PaymentStatus.PAID:
            raise ValidationError("กรุณาคืนเงินก่อนยกเลิกคำสั่งซื้อ")
        return cancel_unpaid_order(order, changed_by=changed_by, note=note or "ยกเลิกคำสั่งซื้อ")

    order.status = new_status
    order.save(
        update_fields=[
            "status",
            "shipping_carrier",
            "tracking_number",
            "shipped_at",
            "delivered_at",
            "updated_at",
        ]
    )
    OrderStatusHistory.objects.create(
        order=order,
        status=new_status,
        note=note,
        changed_by=changed_by,
    )
    AuditEvent.objects.create(
        actor=changed_by,
        action=AuditEvent.Action.STATUS,
        target_type=order._meta.label,
        target_id=str(order.pk),
        description=note,
        before={"status": before_status},
        after={
            "status": order.status,
            "shipping_carrier": order.shipping_carrier,
            "tracking_number": order.tracking_number,
        },
        community=order.community,
    )
    if new_status == Order.Status.COMPLETED:
        from payments.services import mark_order_settlement_ready

        mark_order_settlement_ready(order)
    notification_title = f"อัปเดตคำสั่งซื้อ {order.reference}"
    notification_message = f"สถานะใหม่: {order.get_status_display()}" + (
        f"\nเลขติดตาม: {tracking_number}" if tracking_number else ""
    )
    notification_link = order.get_absolute_url()
    transaction.on_commit(
        lambda: notify_user(
            order.buyer,
            notification_title,
            notification_message,
            notification_link,
        )
    )
    if new_status == Order.Status.SHIPPED:
        from .tracking import register_aftership_tracking

        transaction.on_commit(lambda order_id=order.pk: register_aftership_tracking(order_id))
    return order


@transaction.atomic
def ship_order(order, changed_by, carrier, tracking_number):
    """Advance a paid order to shipped in one seller action, retaining its audit trail."""

    order.refresh_from_db()
    automatic_steps = {
        Order.Status.PAID: (Order.Status.CONFIRMED, "ผู้ขายยืนยันคำสั่งซื้อเพื่อจัดส่ง"),
        Order.Status.CONFIRMED: (Order.Status.PREPARING, "ผู้ขายเตรียมสินค้าเพื่อจัดส่ง"),
    }
    while order.status in automatic_steps:
        next_status, note = automatic_steps[order.status]
        order = change_order_status(order, next_status, changed_by, note=note)

    return change_order_status(
        order,
        Order.Status.SHIPPED,
        changed_by,
        note="ผู้ขายนำส่งพัสดุแล้ว",
        carrier=carrier,
        tracking_number=tracking_number,
    )
