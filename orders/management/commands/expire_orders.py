from django.core.management.base import BaseCommand

from orders.services import expire_stale_orders


class Command(BaseCommand):
    help = "Cancel expired unpaid orders and release stock"

    def handle(self, *args, **options):
        count = expire_stale_orders()
        self.stdout.write(self.style.SUCCESS(f"Expired orders processed: {count}"))