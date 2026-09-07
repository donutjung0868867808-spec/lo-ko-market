from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import get_connection, send_mail
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email


class Command(BaseCommand):
    help = "ตรวจการเชื่อมต่อ SMTP; ส่งอีเมลทดสอบเฉพาะเมื่อระบุ --to"

    def add_arguments(self, parser):
        parser.add_argument("--to", help="อีเมลของคุณสำหรับรับข้อความทดสอบ")

    def handle(self, *args, **options):
        if settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend":
            raise CommandError("ยังไม่ได้เปิด SMTP backend จึงยังส่งอีเมลจริงไม่ได้")
        recipient = options.get("to")
        if recipient:
            try:
                validate_email(recipient)
            except ValidationError as exc:
                raise CommandError("รูปแบบอีเมลไม่ถูกต้อง") from exc
        try:
            with get_connection() as connection:
                if recipient:
                    send_mail(
                        "ทดสอบระบบอีเมลตลาดเกษตรชุมชน",
                        "ระบบเชื่อมต่อบริการส่งอีเมลสำเร็จ",
                        settings.DEFAULT_FROM_EMAIL, [recipient], connection=connection,
                    )
        except Exception as exc:
            raise CommandError(
                "เชื่อมต่อ SMTP ไม่สำเร็จ ตรวจ host, port, TLS และข้อมูลเข้าสู่ระบบ"
            ) from exc
        self.stdout.write(self.style.SUCCESS(
            "ส่งอีเมลทดสอบแล้ว กรุณาตรวจกล่องจดหมายและสแปม" if recipient
            else "เชื่อมต่อและยืนยันตัวตน SMTP สำเร็จ (ยังไม่ได้ส่งอีเมล)"
        ))
