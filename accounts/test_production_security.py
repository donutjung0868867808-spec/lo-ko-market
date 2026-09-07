import os
import re
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .models import Community, EmailDelivery, FarmerProfile, User
from .services import client_ip


class AdminMfaTests(TestCase):
    @override_settings(
        ADMIN_MFA_REQUIRED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_owner_must_confirm_email_code_before_admin(self):
        owner = User.objects.create_user(
            username="mfa-owner",
            password="AdminPass123!",
            email="owner@example.com",
            role=User.Roles.OWNER,
            is_staff=True,
            is_superuser=True,
        )
        self.client.post(
            reverse("admin:login"),
            {
                "username": owner.username,
                "password": "AdminPass123!",
                "next": reverse("admin:index"),
            },
        )

        response = self.client.get(reverse("admin:index"))
        self.assertRedirects(
            response,
            reverse("admin_mfa"),
            fetch_redirect_response=False,
        )
        response = self.client.get(reverse("admin_mfa"))
        self.assertEqual(response.status_code, 200)

        delivery = EmailDelivery.objects.get(user=owner)
        code = re.search(r"\b(\d{6})\b", delivery.body).group(1)
        response = self.client.post(reverse("admin_mfa"), {"code": code})
        self.assertRedirects(
            response,
            reverse("admin:index"),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)


class PrivateDocumentAccessTests(TestCase):
    def setUp(self):
        self.community = Community.objects.create(
            name="Private community",
            slug="private-community",
            province="Nan",
        )
        self.farmer = User.objects.create_user(
            username="private-farmer",
            password="pass12345",
            role=User.Roles.FARMER,
        )
        self.profile = FarmerProfile.objects.create(
            user=self.farmer,
            community=self.community,
            farm_name="Private farm",
            verification_document=SimpleUploadedFile(
                "farmer-proof.pdf",
                b"%PDF-1.4\nprivate test document\n%%EOF",
                content_type="application/pdf",
            ),
        )
        self.outsider = User.objects.create_user(
            username="private-outsider",
            password="pass12345",
            role=User.Roles.CONSUMER,
        )
        self.owner = User.objects.create_user(
            username="private-owner",
            password="pass12345",
            role=User.Roles.OWNER,
        )

    def tearDown(self):
        self.profile.verification_document.delete(save=False)

    def test_private_farmer_document_requires_scope(self):
        url = reverse("accounts:farmer_document", args=[self.profile.pk])
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.owner)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertTrue(b"private test document" in b"".join(response.streaming_content))
        response.close()


class ProxyIpTests(TestCase):
    def test_forwarded_ip_is_used_only_when_proxy_is_trusted(self):
        class Request:
            META = {
                "REMOTE_ADDR": "127.0.0.1",
                "HTTP_X_FORWARDED_FOR": "203.0.113.10, 10.0.0.1",
            }

        with override_settings(TRUST_X_FORWARDED_FOR=False):
            self.assertEqual(client_ip(Request()), "127.0.0.1")
        with override_settings(TRUST_X_FORWARDED_FOR=True):
            self.assertEqual(client_ip(Request()), "203.0.113.10")
class ProductionReadinessCommandTests(SimpleTestCase):
    @override_settings(
        DEBUG=False,
        SECRET_KEY="production-secret-key-with-enough-random-characters-test-only",
        REQUIRE_EMAIL_VERIFICATION=True,
        ADMIN_MFA_REQUIRED=True,
        TRUST_X_FORWARDED_FOR=True,
        SECURE_SSL_REDIRECT=True,
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        STRIPE_CONNECT_TRANSFERS_ENABLED=False,
        TERMS_VERSION="2026-08",
        PRIVACY_VERSION="2026-08",
        PLATFORM_FEE_PERCENT="5.00",
        ALLOWED_HOSTS=["market.example.com"],
        SITE_URL="https://market.example.com",
        REDIS_URL="redis://localhost:6379/0",
        CSRF_TRUSTED_ORIGINS=["https://market.example.com"],
        SETTLEMENT_HOLD_DAYS=2,
    )
    @patch.dict(
        os.environ,
        {
            "DATABASE_URL": "postgresql://example",
            "CLOUDINARY_URL": "cloudinary://example",
            "STRIPE_SECRET_KEY": "sk_test_example",
            "STRIPE_PUBLISHABLE_KEY": "pk_test_example",
            "STRIPE_WEBHOOK_SECRET": "whsec_example",
            "EMAIL_HOST": "smtp.example.com",
            "EMAIL_HOST_USER": "smtp-user",
            "EMAIL_HOST_PASSWORD": "smtp-password",
            "DEFAULT_FROM_EMAIL": "noreply@example.com",
            "CONTACT_EMAIL": "support@example.com",
            "CSRF_TRUSTED_ORIGINS": "https://market.example.com",
            "SITE_URL": "https://market.example.com",
            "REDIS_URL": "redis://localhost:6379/0",
        },
        clear=True,
    )
    def test_optional_monitoring_and_connect_do_not_block_deploy(self):
        stdout = StringIO()
        fake_connection = SimpleNamespace(vendor="postgresql")

        with patch(
            "accounts.management.commands.check_production.connection",
            fake_connection,
        ):
            call_command("check_production", stdout=stdout)

        output = stdout.getvalue()
        self.assertIn("STRIPE_CONNECT_TRANSFERS_ENABLED", output)
        self.assertIn("SENTRY_DSN", output)
        self.assertIn("การตั้งค่า Production พร้อมใช้งาน", output)
