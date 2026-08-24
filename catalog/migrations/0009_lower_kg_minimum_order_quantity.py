from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models


def lower_default_kg_minimum(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    Product.objects.filter(
        unit="kg",
        minimum_order_quantity=Decimal("1.00"),
    ).update(minimum_order_quantity=Decimal("0.50"))


class Migration(migrations.Migration):
    dependencies = [("catalog", "0008_alter_product_low_stock_threshold_and_more")]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="minimum_order_quantity",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.50"),
                max_digits=10,
                validators=[MinValueValidator(Decimal("0.50"))],
            ),
        ),
        migrations.RunPython(lower_default_kg_minimum, migrations.RunPython.noop),
    ]