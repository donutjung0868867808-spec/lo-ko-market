from datetime import timedelta

from django.db import models
from django.utils import timezone

from accounts.services import notify_user

from .models import Product


def notify_low_stock(product_id):
    product = Product.objects.select_related("seller").filter(pk=product_id).first()
    if not product or product.stock_quantity > product.low_stock_threshold:
        return False
    if (
        product.last_low_stock_notified_at
        and product.last_low_stock_notified_at > timezone.now() - timedelta(hours=24)
    ):
        return False

    product.last_low_stock_notified_at = timezone.now()
    product.save(update_fields=["last_low_stock_notified_at", "updated_at"])
    notify_user(
        product.seller,
        f"สินค้าใกล้หมด: {product.name}",
        f"เหลือ {product.stock_quantity} {product.get_unit_display()}",
        product.get_absolute_url(),
    )
    return True

def notify_low_stock_for_all():
    count = 0
    product_ids = Product.objects.filter(
        status=Product.Status.ACTIVE,
        stock_quantity__lte=models.F("low_stock_threshold"),
    ).values_list("id", flat=True)
    for product_id in product_ids:
        count += int(notify_low_stock(product_id))
    return count