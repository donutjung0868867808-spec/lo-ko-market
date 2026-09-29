from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0028_notification_product"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="sender",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="notification_sender_records",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]