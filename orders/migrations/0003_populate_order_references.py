from django.db import migrations


def populate_orders(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    for order in Order.objects.filter(reference__isnull=True).iterator():
        order.reference = f"AG-{order.created_at:%Y%m%d}-{order.pk:05d}"
        order.subtotal = order.total_amount
        order.save(update_fields=["reference", "subtotal"])


class Migration(migrations.Migration):
    dependencies = [("orders", "0002_order_cancelled_at_order_delivered_at_and_more")]

    operations = [migrations.RunPython(populate_orders, migrations.RunPython.noop)]