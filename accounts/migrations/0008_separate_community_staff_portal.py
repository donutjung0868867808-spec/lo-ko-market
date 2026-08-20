from django.db import migrations


def separate_staff_from_admin(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(
        role="cooperative_staff",
        is_superuser=False,
    ).update(is_staff=False)
    User.objects.filter(role="owner").update(is_staff=True)


def restore_staff_admin_access(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="cooperative_staff").update(is_staff=True)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_enable_role_based_admin_access"),
    ]

    operations = [
        migrations.RunPython(
            separate_staff_from_admin,
            restore_staff_admin_access,
        ),
    ]