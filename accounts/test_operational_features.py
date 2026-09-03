import re

from django.contrib import admin
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from agri_market.admin_localization import apply_admin_thai_labels

from .models import EmailDelivery, Notification, User


class OperationalFeatureTests(TestCase):
    password = "AdminPass123!"

    def setUp(self):
        self.owner = User.objects.create_user(
            username="operations-owner",
            password=self.password,
            email="owner@example.com",
            role=User.Roles.OWNER,
        )
        self.member = User.objects.create_user(
            username="operations-member",
            password=self.password,
            email="member@example.com",
            role=User.Roles.CONSUMER,
        )

    def login_admin(self):
        response = self.client.post(
            reverse("admin:login"),
            {
                "username": self.owner.username,
                "password": self.password,
                "next": reverse("admin:index"),
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_owner_can_export_selected_members_as_csv(self):
        self.login_admin()

        response = self.client.post(
            reverse("admin:accounts_user_changelist"),
            {
                "action": "export_as_csv",
                "_selected_action": [self.member.pk],
                "index": "0",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertTrue(response.content.startswith("\ufeff".encode("utf-8")))
        self.assertIn(self.member.username, response.content.decode("utf-8-sig"))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_owner_can_retry_a_pending_email_from_admin(self):
        delivery = EmailDelivery.objects.create(
            user=self.member,
            to_email=self.member.email,
            subject="ทดสอบส่งอีกครั้ง",
            body="ข้อความทดสอบ",
        )
        self.login_admin()

        response = self.client.post(
            reverse("admin:accounts_emaildelivery_changelist"),
            {
                "action": "retry_selected_emails",
                "_selected_action": [delivery.pk],
                "index": "0",
            },
        )

        self.assertEqual(response.status_code, 302)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)
        self.assertEqual(delivery.attempts, 1)

    def test_contact_members_creates_notification_and_email_queue(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("accounts:send_notification"),
            {
                "recipients": [self.member.pk],
                "title": "แจ้งเตือนการจัดส่ง",
                "message": "สินค้ากำลังจัดส่ง",
                "link": "/orders/",
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:dashboard"),
            fetch_redirect_response=False,
        )
        self.assertTrue(Notification.objects.filter(user=self.member).exists())
        queued = EmailDelivery.objects.get(user=self.member)
        self.assertEqual(queued.status, EmailDelivery.Status.PENDING)
        self.assertEqual(queued.attempts, 0)
        self.assertIn("/orders/", queued.body)

    @override_settings(DEBUG=False)
    def test_unknown_page_uses_thai_404_page(self):
        response = self.client.get("/missing-page-for-test/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "ไม่พบหน้าที่ต้องการ", status_code=404)

    @override_settings(DEBUG=False)
    def test_csrf_failure_uses_thai_error_page(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post(reverse("login"), {"username": "x", "password": "x"})

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "แบบฟอร์มหมดอายุ", status_code=403)

    def test_custom_admin_fields_have_thai_labels(self):
        apply_admin_thai_labels()
        app_labels = {"accounts", "catalog", "orders", "payments"}
        untranslated = [
            f"{model._meta.label}.{field.name}: {field.verbose_name}"
            for model in admin.site._registry
            if model._meta.app_label in app_labels
            for field in model._meta.fields
            if re.fullmatch(r"[A-Za-z0-9 _-]+", str(field.verbose_name))
        ]

        self.assertEqual(untranslated, [])

    def test_admin_changelist_uses_thai_interface_text(self):
        self.login_admin()

        response = self.client.get(reverse("admin:accounts_user_changelist"))

        self.assertContains(response, "ดำเนินการ")
        self.assertContains(response, "แสดงจำนวน")
        self.assertContains(response, "เลือก 0 จาก")
        self.assertContains(response, "ข้ามไปยังเนื้อหาหลัก")
        self.assertNotContains(response, ">Run<")
        self.assertNotContains(response, ">Show counts<")
        self.assertNotContains(response, " selected</span>")
        javascript_catalog = self.client.get(reverse("admin:jsi18n"))
        self.assertContains(
            javascript_catalog,
            "เลือก %(sel)s จาก %(cnt)s รายการ".encode("unicode_escape").decode("ascii"),
        )
