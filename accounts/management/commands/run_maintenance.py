from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from accounts.models import EmailDelivery, LoginAttempt
from accounts.services import deliver_email
from catalog.services import notify_low_stock_for_all
from orders.services import expire_stale_orders
from payments.models import SellerSettlement, StripeEvent
from payments.services import process_seller_settlement, sync_settlement_for_payment


class Command(BaseCommand):
    help = "ทำงานประจำ: หมดอายุคำสั่งซื้อ แจ้งสต็อก ส่งอีเมล และเตรียมยอดผู้ขาย"

    def handle(self, *args, **options):
        expired = expire_stale_orders()
        low_stock = notify_low_stock_for_all()

        sent = 0
        pending_email_ids = list(
            EmailDelivery.objects.filter(
                status=EmailDelivery.Status.PENDING,
                next_attempt_at__lte=timezone.now(),
            ).values_list("pk", flat=True)[:100]
        )
        for delivery_id in pending_email_ids:
            delivery = deliver_email(EmailDelivery.objects.get(pk=delivery_id))
            if delivery.status == EmailDelivery.Status.SENT:
                sent += 1

        stale_processing = timezone.now() - timedelta(minutes=15)
        SellerSettlement.objects.filter(
            status=SellerSettlement.Status.PROCESSING,
            updated_at__lt=stale_processing,
        ).update(
            status=SellerSettlement.Status.READY,
            failure_reason="กู้คืนรายการที่ค้างหลังงานโอนเงินหยุดทำงาน",
        )
        for settlement in SellerSettlement.objects.filter(
            status=SellerSettlement.Status.PENDING,
            available_at__lte=timezone.now(),
            payment__order__status="completed",
        ).select_related("payment"):
            sync_settlement_for_payment(settlement.payment)

        transferred = 0
        if settings.STRIPE_CONNECT_TRANSFERS_ENABLED:
            settlement_ids = list(
                SellerSettlement.objects.filter(status=SellerSettlement.Status.READY)
                .values_list("pk", flat=True)[:50]
            )
            for settlement_id in settlement_ids:
                try:
                    result = process_seller_settlement(SellerSettlement.objects.get(pk=settlement_id))
                except Exception as exc:
                    self.stderr.write(f"Settlement {settlement_id}: {exc}")
                else:
                    if result.status == SellerSettlement.Status.TRANSFERRED:
                        transferred += 1
                    elif result.failure_reason:
                        self.stderr.write(f"Settlement {settlement_id}: {result.failure_reason}")

        now = timezone.now()
        LoginAttempt.objects.filter(updated_at__lt=now - timedelta(days=30)).delete()
        EmailDelivery.objects.filter(
            Q(status=EmailDelivery.Status.SENT, sent_at__lt=now - timedelta(days=30))
            | Q(status=EmailDelivery.Status.FAILED, updated_at__lt=now - timedelta(days=90))
        ).delete()
        StripeEvent.objects.filter(processed=True, processed_at__lt=now - timedelta(days=90)).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Expired {expired}, low stock {low_stock}, emails {sent}, settlements {transferred}"
            )
        )