from django.db import migrations, models

import catalog.models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0011_category_image_label"),
    ]

    operations = [
        migrations.AlterField(
            model_name="category",
            name="image",
            field=models.FileField(
                blank=True,
                upload_to="categories/",
                validators=[catalog.models.validate_image_file, catalog.models.validate_image_size],
                verbose_name="รูปหมวดหมู่",
            ),
        ),
        migrations.AlterField(
            model_name="product",
            name="image",
            field=models.FileField(
                blank=True,
                help_text="เลือกรูป JPG, PNG หรือ WEBP ได้ แม้ชื่อไฟล์ไม่มีนามสกุล",
                upload_to="products/",
                validators=[catalog.models.validate_image_file, catalog.models.validate_image_size],
                verbose_name="รูปภาพหลัก",
            ),
        ),
        migrations.AlterField(
            model_name="productimage",
            name="image",
            field=models.FileField(
                upload_to="products/gallery/%Y/%m/",
                validators=[catalog.models.validate_image_file, catalog.models.validate_image_size],
                verbose_name="รูปสินค้าเพิ่มเติม",
            ),
        ),
    ]
