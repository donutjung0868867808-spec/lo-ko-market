from django.db import migrations
from django.utils import timezone


def verify_existing_users(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(email_verified_at__isnull=True).update(email_verified_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_farmerprofile_document_type_and_more")]

    operations = [migrations.RunPython(verify_existing_users, migrations.RunPython.noop)]