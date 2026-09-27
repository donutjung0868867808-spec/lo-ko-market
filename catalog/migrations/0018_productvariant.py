from django.db import migrations, models
import django.db.models.deletion
import catalog.models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0017_product_fulfillment_details"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProductVariant",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        help_text="เช่น สีเหลือง, สีม่วง หรือ ขนาดใหญ่",
                        max_length=80,
                        verbose_name="ชื่อตัวเลือก",
                    ),
                ),
                (
                    "image",
                    models.FileField(
                        blank=True,
                        upload_to="products/variants/%Y/%m/",
                        validators=[
                            catalog.models.validate_image_file,
                            catalog.models.validate_image_size,
                        ],
                        verbose_name="รูปของตัวเลือก",
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="เปิดให้เลือก")),
                ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="ลำดับ")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="variants",
                        to="catalog.product",
                    ),
                ),
            ],
            options={
                "verbose_name": "ตัวเลือกสินค้า",
                "verbose_name_plural": "ตัวเลือกสินค้า",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="productvariant",
            constraint=models.UniqueConstraint(
                fields=("product", "name"),
                name="unique_product_variant_name",
            ),
        ),
    ]
