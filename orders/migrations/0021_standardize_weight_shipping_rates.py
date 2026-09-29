from decimal import Decimal

from django.db import migrations


def standardize_shipping_rates(apps, schema_editor):
    ShippingRate = apps.get_model("orders", "ShippingRate")
    ShippingRate.objects.update(base_fee=Decimal("50.00"), fee_per_kg=Decimal("15.00"))


class Migration(migrations.Migration):
    dependencies = [("orders", "0020_order_received_confirmed_at")]

    operations = [migrations.RunPython(standardize_shipping_rates, migrations.RunPython.noop)]