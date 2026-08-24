from django.core.files.storage import default_storage, storages
from django.core.management.base import BaseCommand

from accounts.models import FarmerProfile, Report, ReportMessage


PRIVATE_FIELDS = (
    (FarmerProfile, "verification_document"),
    (Report, "evidence"),
    (ReportMessage, "attachment"),
)


class Command(BaseCommand):
    help = "คัดลอกเอกสารเดิมจากพื้นที่สาธารณะไป Private Storage"

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete-public",
            action="store_true",
            help="ลบไฟล์สาธารณะหลังคัดลอกสำเร็จ",
        )

    def handle(self, *args, **options):
        private = storages["private"]
        copied = 0
        missing = 0
        for model, field_name in PRIVATE_FIELDS:
            for obj in model.objects.exclude(**{field_name: ""}).iterator():
                field = getattr(obj, field_name)
                name = field.name
                if private.exists(name):
                    continue
                if not default_storage.exists(name):
                    missing += 1
                    self.stderr.write(f"ไม่พบไฟล์เดิม: {model._meta.label} {obj.pk} {name}")
                    continue
                with default_storage.open(name, "rb") as source:
                    saved_name = private.save(name, source)
                if saved_name != name:
                    setattr(obj, field_name, saved_name)
                    obj.save(update_fields=[field_name])
                if options["delete_public"]:
                    default_storage.delete(name)
                copied += 1

        self.stdout.write(self.style.SUCCESS(f"คัดลอก {copied} ไฟล์, ไม่พบ {missing} ไฟล์"))