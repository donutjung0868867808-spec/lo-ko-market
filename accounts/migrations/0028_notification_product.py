import re

import django.db.models.deletion
from django.db import migrations, models


ORDER_LINK_PATTERN = re.compile(r"/orders/(\d+)(?:/|$)")


def backfill_notification_products(apps, schema_editor):
    Notification = apps.get_model("accounts", "Notification")
    OrderItem = apps.get_model("orders", "OrderItem")
    notifications = list(
        Notification.objects.filter(product__isnull=True)
        .exclude(link="")
        .only("id", "link")
    )
    order_ids = {
        int(match.group(1))
        for notification in notifications
        if (match := ORDER_LINK_PATTERN.search(notification.link))
    }
    first_product_by_order = {}
    for item in OrderItem.objects.filter(order_id__in=order_ids).order_by("order_id", "pk"):
        first_product_by_order.setdefault(item.order_id, item.product_id)
    for notification in notifications:
        match = ORDER_LINK_PATTERN.search(notification.link)
        if match and (product_id := first_product_by_order.get(int(match.group(1)))):
            Notification.objects.filter(pk=notification.pk).update(product_id=product_id)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0027_preserve_cloudinary_file_extensions"),
        ("catalog", "0022_productreview_order_item"),
        ("orders", "0020_order_received_confirmed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="product",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="notifications",
                to="catalog.product",
            ),
        ),
        migrations.RunPython(backfill_notification_products, migrations.RunPython.noop),
    ]