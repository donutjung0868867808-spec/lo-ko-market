import os
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "ตรวจสอบค่าที่จำเป็นก่อนเปิดระบบจริง"

    def handle(self, *args, **options):
        errors = []
        warnings = []
        required_env = [
            "DATABASE_URL",
            "CLOUDINARY_URL",
            "STRIPE_SECRET_KEY",
            "STRIPE_PUBLISHABLE_KEY",
            "STRIPE_WEBHOOK_SECRET",
            "EMAIL_HOST",
            "EMAIL_HOST_USER",
            "EMAIL_HOST_PASSWORD",
            "DEFAULT_FROM_EMAIL",
            "CONTACT_EMAIL",
            "CSRF_TRUSTED_ORIGINS",
            "SENTRY_DSN",
        ]
        for name in required_env:
            if not os.environ.get(name):
                errors.append(f"ยังไม่ได้กำหนด {name}")

        if settings.DEBUG:
            errors.append("DEBUG ต้องเป็น False")
        if settings.SECRET_KEY.startswith("django-insecure") or settings.SECRET_KEY == "change-me":
            errors.append("ต้องเปลี่ยน SECRET_KEY เป็นค่าสุ่มที่ปลอดภัย")
        if connection.vendor != "postgresql":
            errors.append("ฐานข้อมูล Production ต้องเป็น PostgreSQL")
        if not settings.REQUIRE_EMAIL_VERIFICATION:
            errors.append("ต้องเปิด REQUIRE_EMAIL_VERIFICATION")
        if not settings.ADMIN_MFA_REQUIRED:
            errors.append("ต้องเปิด ADMIN_MFA_REQUIRED")
        if not settings.TRUST_X_FORWARDED_FOR:
            errors.append("บน Render ต้องเปิด TRUST_X_FORWARDED_FOR")
        if not settings.SECURE_SSL_REDIRECT:
            errors.append("ต้องเปิด SECURE_SSL_REDIRECT")
        if settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend":
            errors.append("Production ต้องใช้ SMTP email backend")
        if not settings.STRIPE_CONNECT_TRANSFERS_ENABLED:
            errors.append("ยังไม่ได้เปิด STRIPE_CONNECT_TRANSFERS_ENABLED สำหรับโอนเงินให้ผู้ขาย")
        if not settings.TERMS_VERSION or not settings.PRIVACY_VERSION:
            errors.append("ต้องกำหนดเวอร์ชันเงื่อนไขการใช้งานและนโยบายความเป็นส่วนตัว")

        try:
            fee = Decimal(str(settings.PLATFORM_FEE_PERCENT))
            if fee < 0 or fee >= 100:
                errors.append("PLATFORM_FEE_PERCENT ต้องอยู่ระหว่าง 0 ถึงน้อยกว่า 100")
        except (InvalidOperation, TypeError):
            errors.append("PLATFORM_FEE_PERCENT ต้องเป็นตัวเลข")

        if settings.ALLOWED_HOSTS == [".onrender.com"]:
            warnings.append("ควรเพิ่มโดเมนจริงใน ALLOWED_HOSTS ก่อนเปิดให้ลูกค้า")
        if settings.SETTLEMENT_HOLD_DAYS < 1:
            warnings.append("ควรพักยอดผู้ขายอย่างน้อย 1 วันเพื่อรองรับการคืนเงิน")

        for warning in warnings:
            self.stdout.write(self.style.WARNING(f"- {warning}"))
        if errors:
            raise CommandError("\n".join(f"- {item}" for item in errors))
        self.stdout.write(self.style.SUCCESS("การตั้งค่า Production พร้อมใช้งาน"))