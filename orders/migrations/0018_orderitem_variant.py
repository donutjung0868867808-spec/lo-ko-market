from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0018_productvariant"),
        ("orders", "0017_shipment_registration_retry_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderitem",
            name="variant",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="order_items",
                to="catalog.productvariant",
            ),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="variant_name",
            field=models.CharField(blank=True, max_length=80),
        ),
    ]
