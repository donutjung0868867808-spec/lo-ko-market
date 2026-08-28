from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import User


class PasswordResetEmailTests(TestCase):
    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_password_reset_request_sends_reset_link_by_email(self):
        user = User.objects.create_user(
            username="reset-member",
            email="member@example.com",
            password="StrongPass123!",
            role=User.Roles.CONSUMER,
        )

        response = self.client.post(
            reverse("password_reset"),
            {"email": user.email},
        )

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [user.email])
        self.assertIn("ตั้งรหัสผ่านใหม่", message.subject)
        self.assertIn("http://testserver/reset/", message.body)
        self.assertEqual(message.alternatives[0][1], "text/html")
        self.assertIn("ตั้งรหัสผ่านใหม่", message.alternatives[0][0])