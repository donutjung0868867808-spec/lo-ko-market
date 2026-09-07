import os
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

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
            "REDIS_URL",
            "SITE_URL",
        ]
        for name in required_env:
            if not os.environ.get(name):
                errors.append(f"ยังไม่ได้กำหนด {name}")

        if settings.DEBUG:
            errors.append("DEBUG ต้องเป็น False")
        site = urlsplit(settings.SITE_URL)
        if (site.scheme != "https" or not site.hostname or site.path
                or site.query or site.fragment or site.username or site.password):
            errors.append("SITE_URL ต้องเป็น https://โดเมน โดยไม่มี path หรือข้อมูลเข้าสู่ระบบ")
        if site.hostname not in settings.ALLOWED_HOSTS:
            errors.append("ต้องเพิ่มโดเมน SITE_URL ใน ALLOWED_HOSTS")
        if settings.SITE_URL not in settings.CSRF_TRUSTED_ORIGINS:
            errors.append("ต้องเพิ่ม SITE_URL ใน CSRF_TRUSTED_ORIGINS")
        if any(host == "*" or host.startswith(".") for host in settings.ALLOWED_HOSTS):
            errors.append("ALLOWED_HOSTS ต้องระบุโดเมนจริง ห้ามใช้ wildcard ใน Production")
        if not settings.REDIS_URL or urlsplit(settings.REDIS_URL).scheme not in {"redis", "rediss"}:
            errors.append("REDIS_URL ต้องเป็น redis:// หรือ rediss://")
        if settings.EMAIL_USE_TLS == settings.EMAIL_USE_SSL:
            errors.append("ต้องเปิด TLS หรือ SSL สำหรับ SMTP เพียงอย่างเดียว")
        if (settings.SECRET_KEY.startswith("django-insecure") or len(settings.SECRET_KEY) < 50
                or len(set(settings.SECRET_KEY)) < 5):
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
            warnings.append(
                "ยังไม่ได้เปิด STRIPE_CONNECT_TRANSFERS_ENABLED "
                "ระบบจะพักยอดผู้ขายไว้และยังไม่โอนอัตโนมัติ"
            )
        elif not settings.STRIPE_CONNECT_WEBHOOK_SECRET:
            errors.append("ต้องกำหนด STRIPE_CONNECT_WEBHOOK_SECRET ก่อนเปิดการโอนอัตโนมัติ")
        if not settings.AFTERSHIP_WEBHOOK_SECRET:
            warnings.append("ยังไม่ได้เชื่อม webhook ติดตามพัสดุ")
        if settings.STRIPE_SECRET_KEY.startswith("sk_test_"):
            warnings.append("Stripe ยังอยู่ใน Test mode ไม่รับหรือโอนเงินจริง")
        if not settings.TERMS_VERSION or not settings.PRIVACY_VERSION:
            errors.append("ต้องกำหนดเวอร์ชันเงื่อนไขการใช้งานและนโยบายความเป็นส่วนตัว")

        try:
            fee = Decimal(str(settings.PLATFORM_FEE_PERCENT))
            if fee < 0 or fee >= 100:
                errors.append("PLATFORM_FEE_PERCENT ต้องอยู่ระหว่าง 0 ถึงน้อยกว่า 100")
        except (InvalidOperation, TypeError):
            errors.append("PLATFORM_FEE_PERCENT ต้องเป็นตัวเลข")

        if not os.environ.get("SENTRY_DSN"):
            warnings.append("ยังไม่ได้กำหนด SENTRY_DSN จึงยังไม่มีระบบติดตามข้อผิดพลาดภายนอก")
        if settings.ALLOWED_HOSTS == [".onrender.com"]:
            warnings.append("ควรเพิ่มโดเมนจริงใน ALLOWED_HOSTS ก่อนเปิดให้ลูกค้า")
        if settings.SETTLEMENT_HOLD_DAYS < 1:
            warnings.append("ควรพักยอดผู้ขายอย่างน้อย 1 วันเพื่อรองรับการคืนเงิน")

        for warning in warnings:
            self.stdout.write(self.style.WARNING(f"- {warning}"))
        if errors:
            raise CommandError("\n".join(f"- {item}" for item in errors))
        self.stdout.write(self.style.SUCCESS("การตั้งค่า Production พร้อมใช้งาน"))
