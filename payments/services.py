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
    secret_key = settings.STRIPE_SECRET_KEY
    if not secret_key:
        return None
    if settings.PAYMENT_MODE == "test" and secret_key.startswith("sk_live_"):
        logger.error("Blocked a live Stripe key because PAYMENT_MODE is test.")
        return None
    import stripe

    stripe.api_key = secret_key
    return stripe


def process_seller_settlement(settlement):
    if not settings.STRIPE_CONNECT_TRANSFERS_ENABLED:
        raise ValidationError("ยังไม่ได้เปิดใช้งานการโอนเงิน Stripe Connect")
    stripe = _stripe_client()
    if stripe is None:
        raise ValidationError("ยังไม่ได้ตั้งค่า Stripe")
    failure = None
    # Use the same lock order as refunds; keep it until Stripe has answered.
    with transaction.atomic():
        payment = Payment.objects.select_for_update().select_related("order").get(pk=settlement.payment_id)
        settlement = SellerSettlement.objects.select_for_update().get(pk=settlement.pk)
        if settlement.stripe_transfer_id:
            return settlement
        if settlement.status not in {SellerSettlement.Status.READY, SellerSettlement.Status.FAILED}:
            raise ValidationError("ยอดนี้ยังไม่พร้อมโอนเงิน")
        if (payment.order.status != payment.order.Status.COMPLETED
                or payment.status != Payment.Status.PAID
                or settlement.available_at is None or settlement.available_at > timezone.now()
                or payment.refunds.filter(status__in=["requested", "processing", "failed"]).exists()):
            raise ValidationError("คำสั่งซื้อยังไม่เข้าเงื่อนไขการโอนเงิน")
        if settlement.attempts >= settings.SETTLEMENT_MAX_ATTEMPTS:
            raise ValidationError("รายการนี้ต้องให้ผู้ดูแลตรวจสอบก่อนลองโอนอีกครั้ง")
        if (settlement.net_amount <= 0 or settlement.gross_amount != payment.amount - payment.refunded_amount
                or settlement.seller_id != payment.order.seller_id or settlement.currency != payment.currency
                or settlement.platform_fee + settlement.net_amount != settlement.gross_amount):
            raise ValidationError("ยอดเงินเปลี่ยนแปลง ต้องตรวจสอบก่อนโอน")
        account = SellerPaymentAccount.objects.filter(seller=settlement.seller).first()
        if not account or not account.stripe_account_id or not account.payouts_enabled:
            settlement.status = SellerSettlement.Status.HELD
            settlement.failure_reason = "บัญชีผู้ขายยังไม่พร้อมรับเงิน"
            settlement.save(update_fields=["status", "failure_reason", "updated_at"])
            return settlement
        settlement.status = SellerSettlement.Status.PROCESSING
        settlement.attempts += 1
        settlement.save(update_fields=["status", "attempts", "updated_at"])
        try:
            # Reconcile first: Stripe idempotency keys expire, so a retry alone is insufficient.
            transfers = stripe.Transfer.list(transfer_group=payment.order.reference, limit=100)
            transfer = next((item for item in transfers.auto_paging_iter()
                             if item.get("metadata", {}).get("settlement_id") == str(settlement.pk)), None)
            if transfer is None:
                intent = stripe.PaymentIntent.retrieve(payment.payment_intent_id, expand=["latest_charge"])
                charge = intent.get("latest_charge")
                charge_id = charge.get("id") if hasattr(charge, "get") else charge
                if not charge_id:
                    raise ValidationError("ไม่พบรายการเรียกเก็บเงินต้นทางจาก Stripe")
                transfer = stripe.Transfer.create(
                    amount=int(settlement.net_amount * Decimal("100")),
                    currency=settlement.currency, destination=account.stripe_account_id,
                    source_transaction=charge_id, transfer_group=payment.order.reference,
                    metadata={"settlement_id": str(settlement.pk), "order_id": str(payment.order_id)},
                    idempotency_key=f"seller-settlement-{settlement.pk}",
                )
            transfer_id = transfer.get("id", "")
            if not transfer_id:
                raise ValidationError("Stripe ไม่ส่งรหัสรายการโอนกลับมา")
            settlement.stripe_transfer_id = transfer_id
            settlement.transferred_at = timezone.now()
            matches = (transfer.get("amount") == int(settlement.net_amount * Decimal("100"))
                       and transfer.get("currency") == settlement.currency
                       and transfer.get("destination") == account.stripe_account_id
                       and not transfer.get("reversed"))
            settlement.status = SellerSettlement.Status.TRANSFERRED if matches else SellerSettlement.Status.HELD
            settlement.failure_reason = "" if matches else "พบยอดโอนเดิม ต้องตรวจสอบรายละเอียดกับ Stripe"
        except Exception as exc:
            failure = exc
            settlement.status = SellerSettlement.Status.FAILED
            settlement.failure_reason = str(exc)[:2000]
            settlement.next_attempt_at = timezone.now() + timedelta(minutes=min(2 ** settlement.attempts, 60))
        settlement.save()
    if failure:
        raise failure
    return settlement


def retry_due_settlements(limit=50):
    if not settings.STRIPE_CONNECT_TRANSFERS_ENABLED:
        return 0
    # Only release holds caused by missing payout onboarding, never refund or manual holds.
    for settlement in SellerSettlement.objects.filter(
        status=SellerSettlement.Status.HELD, failure_reason="บัญชีผู้ขายยังไม่พร้อมรับเงิน",
        seller__payment_account__payouts_enabled=True,
    )[:limit]:
        with transaction.atomic():
            Payment.objects.select_for_update().get(pk=settlement.payment_id)
            current = SellerSettlement.objects.select_for_update().get(pk=settlement.pk)
            if current.status == SellerSettlement.Status.HELD and current.failure_reason == "บัญชีผู้ขายยังไม่พร้อมรับเงิน":
                current.status = SellerSettlement.Status.PENDING
                current.failure_reason = ""
                current.save(update_fields=["status", "failure_reason", "updated_at"])
                sync_settlement_for_payment(current.payment)
    due = SellerSettlement.objects.filter(
        status__in=[SellerSettlement.Status.READY, SellerSettlement.Status.FAILED],
        next_attempt_at__lte=timezone.now(), attempts__lt=settings.SETTLEMENT_MAX_ATTEMPTS,
        payment__order__status="completed", available_at__lte=timezone.now(),
    ).order_by("next_attempt_at")
    transferred = 0
    for settlement in due[:limit]:
        try:
            result = process_seller_settlement(settlement)
            transferred += result.status == SellerSettlement.Status.TRANSFERRED
        except Exception:
            logger.exception("Unable to settle payment %s", settlement.payment_id)
    return transferred
