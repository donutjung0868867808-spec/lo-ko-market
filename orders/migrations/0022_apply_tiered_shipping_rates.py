from decimal import Decimal

from django.db import migrations


def update_shipping_rates(apps, schema_editor):
    ShippingRate = apps.get_model("orders", "ShippingRate")
    ShippingRate.objects.update(base_fee=Decimal("39.00"), fee_per_kg=Decimal("10.00"))


class Migration(migrations.Migration):
    dependencies = [("orders", "0021_standardize_weight_shipping_rates")]

    operations = [migrations.RunPython(update_shipping_rates, migrations.RunPython.noop)]