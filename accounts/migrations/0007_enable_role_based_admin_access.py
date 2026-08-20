from django.db import migrations


def enable_admin_roles(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(
        role__in=["cooperative_staff", "owner"],
    ).update(is_staff=True)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_alter_farmerprofile_verification_document_and_more"),
    ]

    operations = [
        migrations.RunPython(enable_admin_roles, migrations.RunPython.noop),
    ]