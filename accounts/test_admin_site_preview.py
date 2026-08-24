from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from .models import User


class AdminSitePreviewTests(TestCase):
    def test_owner_can_preview_site_without_replacing_public_login(self):
        consumer = User.objects.create_user(
            username="preview-consumer",
            password="pass12345",
            role=User.Roles.CONSUMER,
        )
        owner = User.objects.create_user(
            username="preview-owner",
            password="AdminPass123!",
            role=User.Roles.OWNER,
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(consumer)
        public_session = self.client.cookies[settings.SESSION_COOKIE_NAME].value

        login_response = self.client.post(
            reverse("admin:login"),
            {
                "username": owner.username,
                "password": "AdminPass123!",
                "next": reverse("admin:index"),
            },
        )
        self.assertEqual(login_response.status_code, 302)
        admin_session = self.client.cookies[settings.ADMIN_SESSION_COOKIE_NAME].value

        admin_response = self.client.get(reverse("admin:index"))
        self.assertEqual(admin_response.status_code, 200)
        self.assertContains(admin_response, reverse("admin_site_preview"))

        enable_response = self.client.get(reverse("admin_site_preview"))
        self.assertRedirects(
            enable_response,
            reverse("catalog:product_list"),
            fetch_redirect_response=False,
        )
        self.assertIn(settings.ADMIN_PREVIEW_COOKIE_NAME, self.client.cookies)

        preview_response = self.client.get(reverse("catalog:product_list"))
        self.assertEqual(preview_response.wsgi_request.user.pk, owner.pk)
        self.assertTrue(preview_response.wsgi_request.admin_preview)
        self.assertContains(preview_response, "โหมดผู้ดูแลระบบ")
        self.assertEqual(
            self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            public_session,
        )

        exit_response = self.client.post(reverse("exit_admin_site_preview"))
        self.assertRedirects(
            exit_response,
            reverse("catalog:product_list"),
            fetch_redirect_response=False,
        )
        public_response = self.client.get(reverse("catalog:product_list"))
        self.assertEqual(public_response.wsgi_request.user.pk, consumer.pk)
        self.assertFalse(public_response.wsgi_request.admin_preview)
        self.assertEqual(
            self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            public_session,
        )
        self.assertEqual(
            self.client.cookies[settings.ADMIN_SESSION_COOKIE_NAME].value,
            admin_session,
        )
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_invalid_preview_cookie_does_not_switch_public_session(self):
        consumer = User.objects.create_user(
            username="invalid-preview-consumer",
            password="pass12345",
            role=User.Roles.CONSUMER,
        )
        self.client.force_login(consumer)
        self.client.cookies[settings.ADMIN_PREVIEW_COOKIE_NAME] = "invalid"

        response = self.client.get(reverse("catalog:product_list"))

        self.assertEqual(response.wsgi_request.user.pk, consumer.pk)
        self.assertFalse(response.wsgi_request.admin_preview)