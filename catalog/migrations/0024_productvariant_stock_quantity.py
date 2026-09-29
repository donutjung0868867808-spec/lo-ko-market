from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0023_allow_half_star_reviews"),
    ]

    operations = [
        migrations.AddField(
            model_name="productvariant",
            name="stock_quantity",
            field=models.DecimalField(
                decimal_places=2,
                help_text="ระบุจำนวนแยกสำหรับตัวเลือกนี้",
                max_digits=10,
                null=True,
                blank=True,
                validators=[MinValueValidator(0)],
                verbose_name="จำนวนคงเหลือของตัวเลือก",
            ),
        ),
    ]