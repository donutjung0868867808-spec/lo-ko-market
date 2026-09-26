from django.db import migrations, models
import catalog.models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0012_image_content_validation"),
    ]

    operations = [
        migrations.CreateModel(
            name="HomeSlide",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.FileField(upload_to="home-slides/", validators=[catalog.models.validate_image_file, catalog.models.validate_image_size], verbose_name="ภาพสไลด์")),
                ("alt_text", models.CharField(blank=True, max_length=180, verbose_name="คำอธิบายภาพ")),
                ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="ลำดับ")),
                ("is_active", models.BooleanField(default=True, verbose_name="เปิดใช้งาน")),
            ],
            options={
                "verbose_name": "ภาพสไลด์หน้าแรก",
                "verbose_name_plural": "ภาพสไลด์หน้าแรก",
                "ordering": ["sort_order", "id"],
            },
        ),
    ]
