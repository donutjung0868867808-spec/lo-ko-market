from django.core.validators import FileExtensionValidator
from django.db import migrations, models
import django.db.models.deletion
import accounts.models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0023_farmerprofile_store_cover"),
    ]

    operations = [
        migrations.CreateModel(
            name="StoreCoverSlide",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "image",
                    models.FileField(
                        upload_to="store-cover-slides/%Y/%m/",
                        validators=[
                            FileExtensionValidator(["jpg", "jpeg", "png", "webp"]),
                            accounts.models.validate_file_size,
                        ],
                        verbose_name="รูปสไลด์หน้าร้าน",
                    ),
                ),
                ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="ลำดับ")),
                ("is_active", models.BooleanField(default=True, verbose_name="เปิดใช้งาน")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="store_cover_slides",
                        to="accounts.farmerprofile",
                    ),
                ),
            ],
            options={
                "verbose_name": "รูปสไลด์หน้าร้าน",
                "verbose_name_plural": "รูปสไลด์หน้าร้าน",
                "ordering": ["sort_order", "id"],
            },
        ),
    ]
