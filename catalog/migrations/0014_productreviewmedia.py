from django.db import migrations, models
import django.db.models.deletion
import catalog.models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0013_homeslide"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProductReviewMedia",
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
                    "file",
                    models.FileField(
                        upload_to="reviews/%Y/%m/",
                        validators=[catalog.models.validate_review_media_file],
                        verbose_name="ไฟล์สื่อ",
                    ),
                ),
                (
                    "media_type",
                    models.CharField(
                        choices=[("image", "รูปภาพ"), ("video", "วิดีโอ")],
                        max_length=10,
                        verbose_name="ประเภทสื่อ",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "review",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="media",
                        to="catalog.productreview",
                    ),
                ),
            ],
            options={
                "verbose_name": "สื่อประกอบรีวิว",
                "verbose_name_plural": "สื่อประกอบรีวิว",
                "ordering": ["id"],
            },
        ),
    ]
