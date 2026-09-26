import hashlib
import json
import logging
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import AuditEvent, User
from accounts.services import notify_user
from catalog.models import Product, StockMovement
from catalog.services import notify_low_stock
from orders.models import Order, OrderStatusHistory
from orders.services import (
    cancel_unpaid_order,
    release_order_stock,
    reserve_order_stock,
    restock_refunded_order,
)

from .forms import RefundDecisionForm, RefundRequestForm
from .models import CustomerPaymentProfile, Payment, Refund, SavedPaymentMethod, SellerPaymentAccount, StripeEvent
from .services import hold_settlement_for_refund, release_refund_hold, sync_settlement_for_payment


logger = logging.getLogger(__name__)


@transaction.atomic
def mark_payment_failed(payment, order):
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    order = Order.objects.select_for_update().get(pk=order.pk)
    if payment.status in {Payment.Status.PAID, Payment.Status.REFUNDED}:
        return payment
    payment.status = Payment.Status.FAILED
    payment.save(update_fields=["status", "updated_at"])
    order.payment_status = Order.PaymentStatus.FAILED
    order.save(update_fields=["payment_status", "updated_at"])
    return payment


def start_demo_checkout(order, payment, request):
    """Prepare an in-app sandbox checkout without handling real payment details."""
    if not order.stock_reserved:
        order = reserve_order_stock(order)

    now = timezone.now()
    checkout_expires_at = max(
        order.expires_at or now,
        now + timedelta(minutes=30),
    )
    if order.expires_at != checkout_expires_at:
        order.expires_at = checkout_expires_at
        order.save(update_fields=["expires_at", "updated_at"])

    payment.status = Payment.Status.PROCESSING
    payment.checkout_session_id = f"demo-{payment.checkout_attempt_id.hex}"
    payment.checkout_url = request.build_absolute_uri(
        reverse("payments:demo_checkout", args=[order.pk])
    )
    payment.checkout_expires_at = checkout_expires_at
    payment.save(
        update_fields=[
            "status",
            "checkout_session_id",
            "checkout_url",
            "checkout_expires_at",
            "updated_at",
        ]
    )
    order.payment_status = Order.PaymentStatus.PROCESSING
    order.save(update_fields=["payment_status", "updated_at"])
    return redirect("payments:demo_checkout", order_id=order.pk)


def stripe_client():
    secret_key = settings.STRIPE_SECRET_KEY
    if not secret_key:
        return None
    if settings.PAYMENT_MODE == "test" and secret_key.startswith("sk_live_"):
        logger.error("Blocked a live Stripe key because PAYMENT_MODE is test.")
        return None
    try:
        import stripe
    except ImportError:
        return None
    stripe.api_key = secret_key
    return stripe


def validate_checkout_amount(session, payment):
    amount_total = session.get("amount_total")
    currency = session.get("currency")
    expected = int(payment.amount * Decimal("100"))
    if amount_total is not None and int(amount_total) != expected:
        raise ValidationError("ยอดเงินจาก Stripe ไม่ตรงกับคำสั่งซื้อ")
    if currency and currency.lower() != payment.currency.lower():
        raise ValidationError("สกุลเงินจาก Stripe ไม่ตรงกับคำสั่งซื้อ")


def mark_session_paid(session, payload=None):
    session_id = session.get("id")
    payment = Payment.objects.select_related("order").filter(checkout_session_id=session_id).first()
    if not payment:
        order_id = session.get("metadata", {}).get("order_id")
        if order_id:
            order = Order.objects.filter(pk=order_id).first()
            if order:
                payment, _ = Payment.objects.get_or_create(
                    order=order,
                    defaults={
                        "amount": order.total_amount,
                        "currency": settings.DEFAULT_CURRENCY,
                        "checkout_session_id": session_id or "",
                    },
                )
    if not payment:
        return None

    should_notify = False
    with transaction.atomic():
        payment = Payment.objects.select_for_update().select_related("order").get(pk=payment.pk)
        validate_checkout_amount(session, payment)
        order = Order.objects.select_for_update().get(pk=payment.order_id)

        if payment.status != Payment.Status.PAID:
            should_notify = True
            if not order.stock_reserved:
                for item in order.items.select_related("product").select_for_update():
                    product = Product.objects.select_for_update().get(pk=item.product_id)
                    if product.stock_quantity < item.quantity:
                        raise ValidationError(f"สินค้า {product.name} มีจำนวนไม่เพียงพอ")
                    product.stock_quantity -= item.quantity
                    product.save(update_fields=["stock_quantity", "updated_at"])
                    transaction.on_commit(lambda product_id=product.pk: notify_low_stock(product_id))
                    StockMovement.objects.create(
                        product=product,
                        order=order,
                        movement_type=StockMovement.MovementType.SALE,
                        quantity_change=-item.quantity,
                        balance_after=product.stock_quantity,
                        note="ตัดสต็อกเมื่อชำระเงิน",
                    )
                order.stock_reserved = True
                order.save(update_fields=["stock_reserved", "updated_at"])
            else:
                for item in order.items.select_related("product"):
                    StockMovement.objects.create(
                        product=item.product,
                        order=order,
                        movement_type=StockMovement.MovementType.SALE,
                        quantity_change=Decimal("0.00"),
                        balance_after=item.product.stock_quantity,
                        note="ยืนยันการขายจากสต็อกที่จองไว้",
                    )

        payment.status = Payment.Status.PAID
        payment.checkout_session_id = session_id or payment.checkout_session_id
        payment.payment_intent_id = session.get("payment_intent") or payment.payment_intent_id
        if payload is not None:
            payment.raw_payload = payload
        payment.save(
            update_fields=[
                "status",
                "checkout_session_id",
                "payment_intent_id",
                "raw_payload",
                "updated_at",
            ]
        )
        order.mark_paid()
        OrderStatusHistory.objects.get_or_create(
            order=order,
            status=Order.Status.PAID,
            defaults={"note": "ยืนยันการชำระเงินแล้ว"},
        )

        sync_settlement_for_payment(payment)

    if should_notify:
        notify_user(
            payment.order.buyer,
            f"ชำระเงินคำสั่งซื้อ {payment.order.reference} สำเร็จ",
            f"ยอดชำระ {payment.amount:.2f} บาท",
            payment.order.get_absolute_url(),
        )
        notify_user(
            payment.order.seller,
            f"มีคำสั่งซื้อใหม่ {payment.order.reference}",
            "ผู้ซื้อชำระเงินแล้ว กรุณายืนยันและเตรียมสินค้า",
            payment.order.get_absolute_url(),
        )
    return payment


@login_required
def create_checkout_session(request, order_id):
    accessible_order = get_object_or_404(Order, pk=order_id, buyer=request.user)

    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(order_id=accessible_order.pk).first()
        order = get_object_or_404(
            Order.objects.select_for_update().prefetch_related("items"),
            pk=accessible_order.pk,
            buyer=request.user,
        )
        if order.payment_status == Order.PaymentStatus.PAID:
            return redirect(order)
        if order.is_expired:
            cancel_unpaid_order(order, changed_by=request.user, note="หมดเวลาชำระเงิน")
            messages.error(request, "คำสั่งซื้อหมดเวลาชำระเงินแล้ว")
            return redirect(order)
        if order.total_amount <= 0:
            messages.error(request, "ไม่สามารถชำระเงินคำสั่งซื้อที่ยอดรวมเป็นศูนย์ได้")
            return redirect(order)

        if payment is None:
            payment = Payment.objects.create(
                order=order,
                amount=order.total_amount,
                currency=settings.DEFAULT_CURRENCY,
            )

        now = timezone.now()
        if (
            payment.status == Payment.Status.PROCESSING
            and payment.checkout_url
            and payment.checkout_expires_at
            and payment.checkout_expires_at > now
        ):
            return redirect(payment.checkout_url)

        if payment.checkout_session_id and payment.checkout_expires_at and payment.checkout_expires_at <= now:
            payment.checkout_attempt_id = uuid.uuid4()
            payment.checkout_session_id = ""
            payment.checkout_url = ""

        payment.amount = order.total_amount
        payment.currency = settings.DEFAULT_CURRENCY
        payment.save(
            update_fields=[
                "amount",
                "currency",
                "checkout_attempt_id",
                "checkout_session_id",
                "checkout_url",
                "updated_at",
            ]
        )

        stripe = stripe_client()
        if stripe is None:
            if settings.PAYMENT_MODE == "test":
                try:
                    return start_demo_checkout(order, payment, request)
                except ValidationError as exc:
                    messages.error(request, exc.message)
                    return redirect(order)
            mark_payment_failed(payment, order)
            if order.stock_reserved:
                release_order_stock(order, "คืนสต็อกเนื่องจากระบบชำระเงินไม่พร้อม")
            messages.error(request, "ระบบชำระเงินยังไม่พร้อมใช้งาน กรุณาติดต่อผู้ดูแลระบบ")
            return redirect(order)

        if not order.stock_reserved:
            try:
                order = reserve_order_stock(order)
            except ValidationError as exc:
                messages.error(request, exc.message)
                return redirect(order)

        checkout_expires_at = max(
            order.expires_at or now,
            now + timedelta(minutes=30),
        )
        if order.expires_at != checkout_expires_at:
            order.expires_at = checkout_expires_at
            order.save(update_fields=["expires_at", "updated_at"])

        customer_profile = CustomerPaymentProfile.objects.filter(user=request.user).first()
        customer_arguments = (
            {"customer": customer_profile.stripe_customer_id}
            if customer_profile
            else {"customer_email": request.user.email or None}
        )
        success_url = request.build_absolute_uri(reverse("payments:success"))
        cancel_url = request.build_absolute_uri(reverse("payments:cancel", args=[order.pk]))
        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                line_items=[
                    {
                        "price_data": {
                            "currency": payment.currency,
                            "product_data": {"name": f"คำสั่งซื้อ {order.reference}"},
                            "unit_amount": int(order.total_amount * Decimal("100")),
                        },
                        "quantity": 1,
                    }
                ],
                success_url=f"{success_url}?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=cancel_url,
                metadata={"order_id": str(order.pk), "reference": order.reference},
                payment_intent_data={"transfer_group": order.reference},
                client_reference_id=order.reference,
                **customer_arguments,
                expires_at=int(checkout_expires_at.timestamp()),
                idempotency_key=f"checkout-{order.pk}-{payment.checkout_attempt_id}",
            )
        except Exception:
            logger.exception("Unable to create Stripe checkout for order %s", order.pk)
            if settings.PAYMENT_MODE == "test":
                try:
                    return start_demo_checkout(order, payment, request)
                except ValidationError as exc:
                    messages.error(request, exc.message)
                    return redirect(order)
            mark_payment_failed(payment, order)
            release_order_stock(order, "คืนสต็อกเนื่องจากสร้างหน้าชำระเงินไม่สำเร็จ")
            messages.error(request, "ไม่สามารถเชื่อมต่อระบบชำระเงินได้ กรุณาลองใหม่")
            return redirect(order)

        payment.status = Payment.Status.PROCESSING
        payment.checkout_session_id = session.id
        payment.checkout_url = session.url
        payment.checkout_expires_at = checkout_expires_at
        payment.save(
            update_fields=[
                "status",
                "checkout_session_id",
                "checkout_url",
                "checkout_expires_at",
                "updated_at",
            ]
        )
        order.payment_status = Order.PaymentStatus.PROCESSING
        order.save(update_fields=["payment_status", "updated_at"])
        return redirect(session.url)


@login_required
def demo_checkout(request, order_id):
    if settings.PAYMENT_MODE != "test":
        messages.error(request, "หน้าชำระเงินจำลองใช้ได้เฉพาะโหมดทดลอง")
        return redirect("orders:order_detail", pk=order_id)

    order = get_object_or_404(Order, pk=order_id, buyer=request.user)
    payment = get_object_or_404(Payment, order=order)
    if payment.status == Payment.Status.PAID:
        return redirect(f"{reverse('payments:success')}?session_id={payment.checkout_session_id}")
    if payment.status != Payment.Status.PROCESSING or not payment.checkout_session_id:
        return redirect("payments:create_checkout", order_id=order.pk)
    if order.is_expired:
        cancel_unpaid_order(order, changed_by=request.user, note="หมดเวลาชำระเงินทดลอง")
        messages.error(request, "รายการชำระเงินหมดเวลาแล้ว")
        return redirect(order)
    return render(request, "payments/demo_checkout.html", {"order": order, "payment": payment})


@login_required
@require_POST
def complete_demo_checkout(request, order_id):
    if settings.PAYMENT_MODE != "test":
        messages.error(request, "หน้าชำระเงินจำลองใช้ได้เฉพาะโหมดทดลอง")
        return redirect("orders:order_detail", pk=order_id)

    order = get_object_or_404(Order, pk=order_id, buyer=request.user)
    payment = get_object_or_404(Payment, order=order)
    if payment.status == Payment.Status.PAID:
        return redirect(f"{reverse('payments:success')}?session_id={payment.checkout_session_id}")
    if payment.status != Payment.Status.PROCESSING or not payment.checkout_session_id:
        return redirect("payments:create_checkout", order_id=order.pk)
    if order.is_expired:
        cancel_unpaid_order(order, changed_by=request.user, note="หมดเวลาชำระเงินทดลอง")
        messages.error(request, "รายการชำระเงินหมดเวลาแล้ว")
        return redirect(order)

    method = request.POST.get("payment_method", "card")
    if method not in {"card", "promptpay"}:
        messages.error(request, "กรุณาเลือกวิธีชำระเงิน")
        return redirect("payments:demo_checkout", order_id=order.pk)

    mark_session_paid(
        {
            "id": payment.checkout_session_id,
            "payment_intent": f"demo-intent-{payment.checkout_attempt_id.hex}",
        },
        {"provider": "demo", "payment_method": method, "order_id": order.pk},
    )
    return redirect(f"{reverse('payments:success')}?session_id={payment.checkout_session_id}")


def success(request):
    session_id = request.GET.get("session_id")
    payment = None
    if session_id:
        stripe = stripe_client()
        payment = Payment.objects.filter(checkout_session_id=session_id).select_related("order").first()
        if stripe is not None:
            try:
                session = stripe.checkout.Session.retrieve(session_id)
                if session.get("payment_status") == "paid":
                    payment = mark_session_paid(session)
            except Exception:
                logger.exception("Unable to verify Stripe checkout session %s", session_id)
                messages.warning(request, "ยังตรวจสอบสถานะชำระเงินจาก Stripe ไม่สำเร็จ")
    return render(request, "payments/success.html", {"payment": payment})


@login_required
def cancel(request, order_id):
    order = get_object_or_404(Order, pk=order_id, buyer=request.user)
    return render(request, "payments/cancel.html", {"order": order})


@login_required
@transaction.atomic
def request_refund(request, order_id):
    order = get_object_or_404(Order.objects.select_related("payment"), pk=order_id, buyer=request.user)
    payment = getattr(order, "payment", None)
    if not payment or payment.status not in {Payment.Status.PAID, Payment.Status.REFUNDED}:
        messages.error(request, "คำสั่งซื้อนี้ยังไม่สามารถขอคืนเงินได้")
        return redirect(order)

    refund_start = order.delivered_at or payment.updated_at
    if timezone.now() > refund_start + timedelta(days=settings.REFUND_REQUEST_DAYS):
        messages.error(request, f"คำสั่งซื้อนี้พ้นระยะขอคืนเงิน {settings.REFUND_REQUEST_DAYS} วันแล้ว")
        return redirect(order)

    if payment.refunded_amount >= payment.amount:
        messages.info(request, "คำสั่งซื้อนี้คืนเงินครบแล้ว")
        return redirect(order)

    if payment.refunds.filter(
        status__in=[Refund.Status.REQUESTED, Refund.Status.PROCESSING, Refund.Status.FAILED]
    ).exists():
        messages.warning(request, "มีคำขอคืนเงินที่ยังต้องตรวจสอบหรือดำเนินการซ้ำ")
        return redirect(order)

    form = RefundRequestForm(request.POST or None, request.FILES or None, payment=payment)
    if request.method == "POST" and form.is_valid():
        Refund.objects.create(
            payment=payment,
            amount=form.cleaned_data["amount"],
            reason=form.cleaned_data["reason"],
            requested_by=request.user,
            evidence=form.cleaned_data["evidence"],
        )
        hold_settlement_for_refund(payment)
        owners = User.objects.filter(role=User.Roles.OWNER, is_active=True)
        for owner in owners:
            notify_user(
                owner,
                f"คำขอคืนเงิน {order.reference}",
                form.cleaned_data["reason"],
                order.get_absolute_url(),
            )
        messages.success(request, "ส่งคำขอคืนเงินแล้ว ผู้ดูแลระบบจะตรวจสอบ")
        return redirect(order)
    return render(request, "payments/refund_form.html", {"form": form, "order": order, "payment": payment})


@transaction.atomic
def complete_refund(refund, changed_by=None):
    refund = Refund.objects.select_for_update().select_related("payment__order").get(pk=refund.pk)
    if refund.status == Refund.Status.SUCCEEDED:
        return refund
    before_status = refund.status

    payment = Payment.objects.select_for_update().get(pk=refund.payment_id)
    remaining = payment.amount - payment.refunded_amount
    if refund.amount > remaining:
        raise ValidationError("จำนวนเงินคืนเกินยอดคงเหลือ")

    refund.status = Refund.Status.SUCCEEDED
    refund.handled_by = changed_by
    refund.handled_at = timezone.now()
    refund.save(update_fields=["status", "handled_by", "handled_at", "updated_at"])
    payment.refunded_amount += refund.amount
    if payment.refunded_amount >= payment.amount:
        payment.status = Payment.Status.REFUNDED
    payment.save(update_fields=["refunded_amount", "status", "updated_at"])
    release_refund_hold(payment)
    AuditEvent.objects.create(
        actor=changed_by,
        action=AuditEvent.Action.REFUND,
        target_type=refund._meta.label,
        target_id=str(refund.pk),
        description="ดำเนินการคืนเงิน",
        before={"status": before_status},
        after={"status": refund.status, "amount": str(refund.amount)},
        community=payment.order.community,
    )
    if payment.refunded_amount >= payment.amount:
        restock_refunded_order(payment.order, changed_by=changed_by)
    return refund


@login_required
@transaction.atomic
def reject_refund(request, refund_id):
    if not request.user.is_owner:
        messages.error(request, "เฉพาะเจ้าของระบบเท่านั้นที่พิจารณาคำขอคืนเงินได้")
        return redirect("accounts:dashboard")

    refund = get_object_or_404(
        Refund.objects.select_related("payment__order", "requested_by"),
        pk=refund_id,
        status__in=[Refund.Status.REQUESTED, Refund.Status.FAILED],
    )
    form = RefundDecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        refund.status = Refund.Status.REJECTED
        refund.resolution_note = form.cleaned_data["resolution_note"]
        refund.handled_by = request.user
        refund.handled_at = timezone.now()
        refund.save(
            update_fields=[
                "status",
                "resolution_note",
                "handled_by",
                "handled_at",
                "updated_at",
            ]
        )
        release_refund_hold(refund.payment)
        AuditEvent.objects.create(
            actor=request.user,
            action=AuditEvent.Action.REJECT,
            target_type=refund._meta.label,
            target_id=str(refund.pk),
            description="ไม่อนุมัติคำขอคืนเงิน",
            after={
                "status": refund.status,
                "resolution_note": refund.resolution_note,
            },
            community=refund.payment.order.community,
        )
        notify_user(
            refund.requested_by,
            f"คำขอคืนเงิน {refund.payment.order.reference} ไม่ได้รับการอนุมัติ",
            refund.resolution_note,
            refund.payment.order.get_absolute_url(),
        )
        messages.success(request, "บันทึกผลการพิจารณาและปล่อยยอดผู้ขายแล้ว")
        return redirect(refund.payment.order)

    return render(
        request,
        "payments/refund_decision_form.html",
        {"form": form, "refund": refund, "order": refund.payment.order},
    )

@login_required
def process_refund(request, refund_id):
    if not request.user.is_owner:
        messages.error(request, "เฉพาะเจ้าของระบบเท่านั้นที่ดำเนินการคืนเงินได้")
        return redirect("accounts:dashboard")

    refund = get_object_or_404(
        Refund.objects.select_related("payment__order"),
        pk=refund_id,
        status__in=[Refund.Status.REQUESTED, Refund.Status.FAILED],
    )
    if request.method != "POST" or refund.status == Refund.Status.SUCCEEDED:
        return redirect(refund.payment.order)

    payment = refund.payment
    payment.refresh_from_db()
    if refund.amount > payment.amount - payment.refunded_amount:
        refund.status = Refund.Status.FAILED
        refund.save(update_fields=["status", "updated_at"])
        messages.error(request, "ยอดคืนเงินเกินยอดคงเหลือ")
        return redirect(payment.order)

    refund.status = Refund.Status.PROCESSING
    refund.save(update_fields=["status", "updated_at"])
    stripe = stripe_client()
    try:
        if stripe is None:
            if not settings.DEBUG:
                raise ValidationError("ยังไม่ได้ตั้งค่า Stripe")
            result = {"id": f"mock-refund-{refund.pk}", "status": "succeeded"}
        else:
            result = stripe.Refund.create(
                payment_intent=payment.payment_intent_id,
                amount=int(refund.amount * Decimal("100")),
                metadata={"refund_id": str(refund.pk), "order_id": str(payment.order_id)},
                idempotency_key=f"refund-{refund.pk}",
            )
        refund.stripe_refund_id = result.get("id", "")
        refund.save(update_fields=["stripe_refund_id", "updated_at"])
        if result.get("status") == "succeeded":
            refund = complete_refund(refund, changed_by=request.user)
            notify_user(
                payment.order.buyer,
                f"คืนเงินคำสั่งซื้อ {payment.order.reference} แล้ว",
                f"จำนวน {refund.amount:.2f} บาท",
                payment.order.get_absolute_url(),
            )
            messages.success(request, "ดำเนินการคืนเงินสำเร็จ")
    except Exception as exc:
        logger.exception("Refund failed for refund %s", refund.pk)
        refund.status = Refund.Status.FAILED
        refund.save(update_fields=["status", "updated_at"])
        messages.error(request, f"คืนเงินไม่สำเร็จ: {exc}")
    return redirect(payment.order)


def _event_identifier(payload, raw_payload):
    return payload.get("id") or "local-" + hashlib.sha256(raw_payload).hexdigest()


def process_stripe_event(event, payload_json):
    event_type = event.get("type", "")
    event_object = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        mark_session_paid(event_object, payload_json)
    elif event_type == "checkout.session.expired":
        payment = Payment.objects.select_related("order").filter(
            checkout_session_id=event_object.get("id", "")
        ).first()
        if payment and payment.order.payment_status != Order.PaymentStatus.PAID:
            mark_payment_failed(payment, payment.order)
            cancel_unpaid_order(payment.order, note="หน้าชำระเงินหมดอายุ")
    elif event_type in {"refund.created", "refund.updated"}:
        refund = Refund.objects.select_related("payment__order").filter(
            stripe_refund_id=event_object.get("id", "")
        ).first()
        if refund and event_object.get("status") == "succeeded":
            was_succeeded = refund.status == Refund.Status.SUCCEEDED
            refund = complete_refund(refund)
            if not was_succeeded:
                notify_user(
                    refund.payment.order.buyer,
                    f"คืนเงินคำสั่งซื้อ {refund.payment.order.reference} แล้ว",
                    f"จำนวน {refund.amount:.2f} บาท",
                    refund.payment.order.get_absolute_url(),
                )
    elif event_type == "account.updated":
        account = SellerPaymentAccount.objects.filter(
            stripe_account_id=event_object.get("id", "")
        ).first()
        if account:
            account.details_submitted = bool(event_object.get("details_submitted"))
            account.charges_enabled = bool(event_object.get("charges_enabled"))
            account.payouts_enabled = bool(event_object.get("payouts_enabled"))
            account.status = (
                SellerPaymentAccount.Status.ACTIVE
                if account.details_submitted and account.payouts_enabled
                else SellerPaymentAccount.Status.RESTRICTED
                if event_object.get("requirements", {}).get("disabled_reason")
                else SellerPaymentAccount.Status.PENDING
            )
            account.save(
                update_fields=[
                    "details_submitted",
                    "charges_enabled",
                    "payouts_enabled",
                    "status",
                    "updated_at",
                ]
            )
    elif event_type == "payment_intent.payment_failed":
        payment = Payment.objects.select_related("order").filter(
            payment_intent_id=event_object.get("id", "")
        ).first()
        if payment:
            mark_payment_failed(payment, payment.order)


@login_required
def connect_account(request):
    if not request.user.is_farmer:
        messages.error(request, "เฉพาะบัญชีเกษตรกรเท่านั้นที่ตั้งค่าบัญชีรับเงินได้")
        return redirect("accounts:dashboard")
    stripe = stripe_client()
    if stripe is None:
        messages.error(request, "ยังไม่ได้ตั้งค่า Stripe สำหรับระบบรับเงิน")
        return redirect("accounts:dashboard")

    account, _ = SellerPaymentAccount.objects.get_or_create(seller=request.user)
    try:
        if not account.stripe_account_id:
            stripe_account = stripe.Account.create(
                type="express",
                country=account.country,
                email=request.user.email or None,
                capabilities={"transfers": {"requested": True}},
                metadata={"seller_id": str(request.user.pk)},
                idempotency_key=f"connect-account-{request.user.pk}",
            )
            account.stripe_account_id = stripe_account.id
            account.status = SellerPaymentAccount.Status.PENDING
            account.save(update_fields=["stripe_account_id", "status", "updated_at"])

        account_link = stripe.AccountLink.create(
            account=account.stripe_account_id,
            refresh_url=request.build_absolute_uri(reverse("payments:connect_account")),
            return_url=request.build_absolute_uri(reverse("payments:connect_return")),
            type="account_onboarding",
        )
    except Exception:
        logger.exception("Unable to create Stripe Connect onboarding for seller %s", request.user.pk)
        messages.error(request, "ไม่สามารถเปิดหน้าตั้งค่าบัญชีรับเงินได้ กรุณาลองใหม่")
        return redirect("accounts:dashboard")
    return redirect(account_link.url)


@login_required
def connect_return(request):
    if not request.user.is_farmer:
        return redirect("accounts:dashboard")
    account = SellerPaymentAccount.objects.filter(seller=request.user).first()
    stripe = stripe_client()
    if not account or not account.stripe_account_id or stripe is None:
        messages.error(request, "ไม่พบบัญชีรับเงินที่ต้องตรวจสอบ")
        return redirect("accounts:dashboard")
    try:
        stripe_account = stripe.Account.retrieve(account.stripe_account_id)
        account.details_submitted = bool(stripe_account.get("details_submitted"))
        account.charges_enabled = bool(stripe_account.get("charges_enabled"))
        account.payouts_enabled = bool(stripe_account.get("payouts_enabled"))
        if account.details_submitted and account.payouts_enabled:
            account.status = SellerPaymentAccount.Status.ACTIVE
        elif stripe_account.get("requirements", {}).get("disabled_reason"):
            account.status = SellerPaymentAccount.Status.RESTRICTED
        else:
            account.status = SellerPaymentAccount.Status.PENDING
        account.save(
            update_fields=[
                "details_submitted",
                "charges_enabled",
                "payouts_enabled",
                "status",
                "updated_at",
            ]
        )
    except Exception:
        logger.exception("Unable to refresh Stripe Connect account %s", account.pk)
        messages.warning(request, "ยังตรวจสอบสถานะบัญชีรับเงินไม่สำเร็จ")
    else:
        messages.success(request, "อัปเดตสถานะบัญชีรับเงินแล้ว")
    return redirect("accounts:dashboard")

@csrf_exempt
def stripe_webhook(request, connect=False):
    if request.method != "POST":
        return HttpResponse(status=405)

    stripe = stripe_client()
    payload = request.body
    signature = request.META.get("HTTP_STRIPE_SIGNATURE")
    secret = settings.STRIPE_CONNECT_WEBHOOK_SECRET if connect else settings.STRIPE_WEBHOOK_SECRET
    try:
        payload_json = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponse(status=400)

    if stripe and secret and signature:
        try:
            event = stripe.Webhook.construct_event(payload, signature, secret)
        except Exception:
            return HttpResponse(status=400)
    elif settings.DEBUG and not connect:
        event = payload_json
    else:
        return HttpResponse(status=400)

    if connect and event.get("type") != "account.updated":
        return HttpResponse(status=400)
    if connect and bool(event.get("livemode")) != settings.STRIPE_SECRET_KEY.startswith("sk_live_"):
        return JsonResponse({"ok": True, "ignored": "different_mode"})
    event_id = _event_identifier(event, payload)
    with transaction.atomic():
        event_record, _ = StripeEvent.objects.get_or_create(
            event_id=event_id,
            defaults={
                "event_type": event.get("type", ""),
                "payload": payload_json,
            },
        )
        event_record = StripeEvent.objects.select_for_update().get(pk=event_record.pk)
        if event_record.processed:
            return JsonResponse({"ok": True, "duplicate": True})

        try:
            with transaction.atomic():
                process_stripe_event(event, payload_json)
        except Exception as exc:
            logger.exception("Stripe webhook processing failed for %s", event_record.event_id)
            event_record.error_message = str(exc)
            event_record.save(update_fields=["error_message"])
            return HttpResponse(status=500)

        event_record.processed = True
        event_record.processed_at = timezone.now()
        event_record.error_message = ""
        event_record.save(update_fields=["processed", "processed_at", "error_message"])
    return JsonResponse({"ok": True})
@login_required
@require_POST
def create_payment_method_setup(request):
    stripe = stripe_client()
    if stripe is None:
        messages.error(request, "ยังไม่ได้ตั้งค่า Stripe จึงไม่สามารถเพิ่มบัตรได้")
        return redirect("accounts:payment_settings")

    profile = CustomerPaymentProfile.objects.filter(user=request.user).first()
    try:
        if profile is None:
            customer = stripe.Customer.create(
                email=request.user.email or None,
                name=str(request.user),
                metadata={"user_id": str(request.user.pk)},
            )
            profile = CustomerPaymentProfile.objects.create(
                user=request.user,
                stripe_customer_id=customer.id,
            )
        success_url = request.build_absolute_uri(reverse("payments:payment_method_setup_success"))
        cancel_url = request.build_absolute_uri(reverse("accounts:payment_settings"))
        session = stripe.checkout.Session.create(
            mode="setup",
            payment_method_types=["card"],
            customer=profile.stripe_customer_id,
            success_url=f"{success_url}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=cancel_url,
            metadata={"user_id": str(request.user.pk)},
            idempotency_key=f"card-setup-{request.user.pk}-{uuid.uuid4()}",
        )
    except Exception:
        logger.exception("Unable to create card setup session for user %s", request.user.pk)
        messages.error(request, "ไม่สามารถเปิดหน้าบันทึกบัตรได้ กรุณาลองใหม่")
        return redirect("accounts:payment_settings")
    return redirect(session.url)


@login_required
def payment_method_setup_success(request):
    session_id = request.GET.get("session_id", "")
    profile = CustomerPaymentProfile.objects.filter(user=request.user).first()
    stripe = stripe_client()
    if not session_id or profile is None or stripe is None:
        messages.error(request, "ไม่พบข้อมูลการบันทึกบัตร")
        return redirect("accounts:payment_settings")
    try:
        session = stripe.checkout.Session.retrieve(
            session_id,
            expand=["setup_intent.payment_method"],
        )
        if session.get("customer") != profile.stripe_customer_id:
            raise ValidationError("ข้อมูลลูกค้า Stripe ไม่ตรงกับบัญชีผู้ใช้")
        setup_intent = session.get("setup_intent")
        if isinstance(setup_intent, str):
            setup_intent = stripe.SetupIntent.retrieve(
                setup_intent,
                expand=["payment_method"],
            )
        if not setup_intent or setup_intent.get("status") != "succeeded":
            raise ValidationError("การยืนยันบัตรยังไม่สำเร็จ")
        payment_method = setup_intent.get("payment_method")
        if isinstance(payment_method, str):
            payment_method = stripe.PaymentMethod.retrieve(payment_method)
        card = payment_method.get("card") or {}
        if payment_method.get("type") != "card" or not card.get("last4"):
            raise ValidationError("ไม่พบข้อมูลบัตรที่รองรับ")
        is_first = not profile.payment_methods.exists()
        SavedPaymentMethod.objects.update_or_create(
            stripe_payment_method_id=payment_method.get("id"),
            defaults={
                "profile": profile,
                "method_type": payment_method.get("type", "card"),
                "brand": card.get("brand", ""),
                "last4": card.get("last4", ""),
                "exp_month": card.get("exp_month"),
                "exp_year": card.get("exp_year"),
                "is_default": is_first,
            },
        )
    except Exception:
        logger.exception("Unable to verify saved payment method for user %s", request.user.pk)
        messages.error(request, "ตรวจสอบบัตรกับ Stripe ไม่สำเร็จ")
        return redirect("accounts:payment_settings")
    messages.success(request, "บันทึกบัตรเรียบร้อยแล้ว")
    return redirect("accounts:payment_settings")


@login_required
@require_POST
def payment_method_set_default(request, pk):
    method = get_object_or_404(
        SavedPaymentMethod.objects.select_related("profile"),
        pk=pk,
        profile__user=request.user,
    )
    with transaction.atomic():
        method.profile.payment_methods.update(is_default=False)
        method.is_default = True
        method.save(update_fields=["is_default"])
    stripe = stripe_client()
    if stripe is not None:
        try:
            stripe.Customer.modify(
                method.profile.stripe_customer_id,
                invoice_settings={"default_payment_method": method.stripe_payment_method_id},
            )
        except Exception:
            logger.exception("Unable to set Stripe default payment method %s", method.pk)
    messages.success(request, "ตั้งบัตรเริ่มต้นแล้ว")
    return redirect("accounts:payment_settings")


@login_required
@require_POST
def payment_method_delete(request, pk):
    method = get_object_or_404(
        SavedPaymentMethod.objects.select_related("profile"),
        pk=pk,
        profile__user=request.user,
    )
    stripe = stripe_client()
    if stripe is not None:
        try:
            stripe.PaymentMethod.detach(method.stripe_payment_method_id)
        except Exception:
            logger.exception("Unable to detach Stripe payment method %s", method.pk)
            messages.error(request, "ไม่สามารถลบบัตรจาก Stripe ได้ กรุณาลองใหม่")
            return redirect("accounts:payment_settings")
    was_default = method.is_default
    profile = method.profile
    method.delete()
    if was_default:
        replacement = profile.payment_methods.first()
        if replacement:
            replacement.is_default = True
            replacement.save(update_fields=["is_default"])
    messages.success(request, "ลบบัตรแล้ว")
    return redirect("accounts:payment_settings")
