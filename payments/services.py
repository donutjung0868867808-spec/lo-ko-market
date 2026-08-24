import logging
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Payment, SellerPaymentAccount, SellerSettlement


logger = logging.getLogger(__name__)
CENT = Decimal("0.01")
REFUND_REVIEW_HOLD_REASON = "พักยอดระหว่างตรวจสอบคำขอคืนเงิน"


def _money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def settlement_values(payment):
    gross = _money(payment.amount - payment.refunded_amount)
    fee_rate = Decimal(str(settings.PLATFORM_FEE_PERCENT))
    platform_fee = _money(gross * fee_rate / Decimal("100"))
    return gross, fee_rate, platform_fee, _money(gross - platform_fee)


@transaction.atomic
def sync_settlement_for_payment(payment):
    payment = Payment.objects.select_for_update().select_related("order__seller").get(pk=payment.pk)
    if payment.status not in {Payment.Status.PAID, Payment.Status.REFUNDED}:
        return None

    settlement = SellerSettlement.objects.select_for_update().filter(payment=payment).first()
    if payment.refunded_amount >= payment.amount:
        if settlement:
            settlement.status = (
                SellerSettlement.Status.HELD
                if settlement.status == SellerSettlement.Status.TRANSFERRED
                else SellerSettlement.Status.REVERSED
            )
            settlement.failure_reason = (
                "มีการคืนเงินหลังโอนเงินให้ผู้ขายแล้ว ต้องตรวจสอบและเรียกคืนเงิน"
                if settlement.status == SellerSettlement.Status.HELD
                else "คืนเงินเต็มจำนวนแล้ว"
            )
            settlement.save(update_fields=["status", "failure_reason", "updated_at"])
        return settlement

    gross, fee_rate, platform_fee, net = settlement_values(payment)
    available_at = payment.updated_at + timedelta(days=settings.SETTLEMENT_HOLD_DAYS)
    desired_status = SellerSettlement.Status.PENDING
    if payment.order.status == payment.order.Status.COMPLETED and available_at <= timezone.now():
        desired_status = SellerSettlement.Status.READY

    if settlement is None:
        return SellerSettlement.objects.create(
            payment=payment,
            seller=payment.order.seller,
            gross_amount=gross,
            fee_rate=fee_rate,
            platform_fee=platform_fee,
            net_amount=net,
            currency=payment.currency,
            status=desired_status,
            available_at=available_at,
        )

    if settlement.status == SellerSettlement.Status.TRANSFERRED:
        if settlement.gross_amount != gross:
            settlement.status = SellerSettlement.Status.HELD
            settlement.failure_reason = "ยอดคืนเงินเปลี่ยนหลังโอนเงินแล้ว ต้องตรวจสอบยอดกับผู้ขาย"
            settlement.save(update_fields=["status", "failure_reason", "updated_at"])
        return settlement

    settlement.seller = payment.order.seller
    settlement.gross_amount = gross
    settlement.fee_rate = fee_rate
    settlement.platform_fee = platform_fee
    settlement.net_amount = net
    settlement.currency = payment.currency
    settlement.available_at = available_at
    if settlement.status not in {SellerSettlement.Status.PROCESSING, SellerSettlement.Status.HELD}:
        settlement.status = desired_status
        settlement.failure_reason = ""
    settlement.save(
        update_fields=[
            "seller",
            "gross_amount",
            "fee_rate",
            "platform_fee",
            "net_amount",
            "currency",
            "available_at",
            "status",
            "failure_reason",
            "updated_at",
        ]
    )
    return settlement


@transaction.atomic
def hold_settlement_for_refund(payment):
    settlement = sync_settlement_for_payment(payment)
    if settlement is None:
        return None
    settlement = SellerSettlement.objects.select_for_update().get(pk=settlement.pk)
    settlement.status = SellerSettlement.Status.HELD
    settlement.failure_reason = REFUND_REVIEW_HOLD_REASON
    settlement.save(update_fields=["status", "failure_reason", "updated_at"])
    return settlement


@transaction.atomic
def release_refund_hold(payment):
    settlement = SellerSettlement.objects.select_for_update().filter(payment=payment).first()
    if not settlement or settlement.failure_reason != REFUND_REVIEW_HOLD_REASON:
        return settlement
    settlement.status = (
        SellerSettlement.Status.TRANSFERRED
        if settlement.stripe_transfer_id
        else SellerSettlement.Status.PENDING
    )
    settlement.failure_reason = ""
    settlement.save(update_fields=["status", "failure_reason", "updated_at"])
    return sync_settlement_for_payment(payment)

@transaction.atomic
def mark_order_settlement_ready(order):
    payment = Payment.objects.select_for_update().filter(order=order).first()
    if not payment:
        return None
    return sync_settlement_for_payment(payment)


def _stripe_client():
    if not settings.STRIPE_SECRET_KEY:
        return None
    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def process_seller_settlement(settlement):
    if not settings.STRIPE_CONNECT_TRANSFERS_ENABLED:
        raise ValidationError("ยังไม่ได้เปิดใช้งานการโอนเงิน Stripe Connect")
    stripe = _stripe_client()
    if stripe is None:
        raise ValidationError("ยังไม่ได้ตั้งค่า Stripe")

    with transaction.atomic():
        settlement = SellerSettlement.objects.select_for_update().select_related(
            "payment__order", "seller"
        ).get(pk=settlement.pk)
        if settlement.status == SellerSettlement.Status.TRANSFERRED:
            return settlement
        if settlement.status not in {SellerSettlement.Status.READY, SellerSettlement.Status.FAILED}:
            raise ValidationError("ยอดนี้ยังไม่พร้อมโอนเงิน")

        account = SellerPaymentAccount.objects.filter(seller=settlement.seller).first()
        if not account or not account.stripe_account_id or not account.payouts_enabled:
            settlement.status = SellerSettlement.Status.HELD
            settlement.failure_reason = "บัญชีผู้ขายยังไม่พร้อมรับเงิน"
            settlement.save(update_fields=["status", "failure_reason", "updated_at"])
            return settlement

        settlement.status = SellerSettlement.Status.PROCESSING
        settlement.failure_reason = ""
        settlement.save(update_fields=["status", "failure_reason", "updated_at"])

        payment_intent_id = settlement.payment.payment_intent_id
        net_amount = settlement.net_amount
        currency = settlement.currency
        destination = account.stripe_account_id
        order_reference = settlement.payment.order.reference
        order_id = settlement.payment.order_id
        settlement_id = settlement.pk

    try:
        intent = stripe.PaymentIntent.retrieve(
            payment_intent_id,
            expand=["latest_charge"],
        )
        latest_charge = intent.get("latest_charge")
        charge_id = latest_charge.get("id") if hasattr(latest_charge, "get") else latest_charge
        if not charge_id:
            raise ValidationError("ไม่พบรายการเรียกเก็บเงินต้นทางจาก Stripe")
        transfer = stripe.Transfer.create(
            amount=int(net_amount * Decimal("100")),
            currency=currency,
            destination=destination,
            source_transaction=charge_id,
            transfer_group=order_reference,
            metadata={
                "settlement_id": str(settlement_id),
                "order_id": str(order_id),
            },
            idempotency_key=f"seller-settlement-{settlement_id}",
        )
    except Exception as exc:
        with transaction.atomic():
            failed = SellerSettlement.objects.select_for_update().get(pk=settlement_id)
            if failed.status != SellerSettlement.Status.TRANSFERRED:
                failed.status = SellerSettlement.Status.FAILED
                failed.failure_reason = str(exc)[:2000]
                failed.save(update_fields=["status", "failure_reason", "updated_at"])
        logger.exception("Seller settlement %s failed", settlement_id)
        raise

    with transaction.atomic():
        completed = SellerSettlement.objects.select_for_update().get(pk=settlement_id)
        completed.status = SellerSettlement.Status.TRANSFERRED
        completed.stripe_transfer_id = transfer.get("id", "")
        completed.transferred_at = timezone.now()
        completed.failure_reason = ""
        completed.save(
            update_fields=[
                "status",
                "stripe_transfer_id",
                "transferred_at",
                "failure_reason",
                "updated_at",
            ]
        )
    return completed