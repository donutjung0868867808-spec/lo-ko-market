from django.core.management.base import BaseCommand

from catalog.services import notify_low_stock_for_all


class Command(BaseCommand):
    help = "แจ้งผู้ขายเมื่อสินค้าใกล้หมด"

    def handle(self, *args, **options):
        count = notify_low_stock_for_all()
        self.stdout.write(self.style.SUCCESS(f"Low-stock notifications sent: {count}"))