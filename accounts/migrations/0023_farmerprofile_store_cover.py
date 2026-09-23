from django.core.validators import FileExtensionValidator
from django.db import migrations, models
import accounts.models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0022_newspost_is_important_newspost_notified_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="farmerprofile",
            name="store_cover",
            field=models.FileField(
                blank=True,
                upload_to="store-covers/%Y/%m/",
                validators=[
                    FileExtensionValidator(["jpg", "jpeg", "png", "webp"]),
                    accounts.models.validate_file_size,
                ],
                verbose_name="รูปปกหน้าร้าน",
            ),
        ),
    ]
