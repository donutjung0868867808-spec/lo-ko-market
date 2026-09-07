from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import EmailDelivery, User
from .services import deliver_email, queue_email, send_verification_email


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ReliableEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mail-user", password="ExamplePass123!", email="mail@example.com")

    def test_failure_survives_raise_and_retry_delivers_once(self):
        delivery = queue_email(self.user.email, "test", "body", send_now=False)
        with patch("accounts.services.send_mail", side_effect=OSError("SMTP unavailable")):
            with self.assertRaises(OSError):
                deliver_email(delivery, raise_on_failure=True)
        delivery.refresh_from_db()
        self.assertEqual(delivery.attempts, 1)
        self.assertEqual(delivery.status, EmailDelivery.Status.PENDING)
        self.assertGreater(delivery.next_attempt_at, timezone.now())
        deliver_email(delivery)
        deliver_email(delivery)
        self.assertEqual(len(mail.outbox), 1)

    def test_expired_auth_email_is_not_sent(self):
        delivery = queue_email(self.user.email, "code", "expired", send_now=False,
                               expires_at=timezone.now() - timedelta(seconds=1))
        with patch("accounts.services.send_mail") as send:
            result = deliver_email(delivery)
        send.assert_not_called()
        self.assertEqual(result.status, EmailDelivery.Status.FAILED)

    def test_admin_can_explicitly_retry_failed_but_not_expired_email(self):
        delivery = queue_email(self.user.email, "test", "body", send_now=False)
        delivery.status = EmailDelivery.Status.FAILED
        delivery.save()
        with patch("accounts.services.send_mail") as send:
            deliver_email(delivery)
            send.assert_not_called()
        result = deliver_email(delivery, retry_failed=True)
        self.assertEqual(result.status, EmailDelivery.Status.SENT)

    @override_settings(SITE_URL="https://market.example.com")
    def test_reset_and_verification_links_use_canonical_domain(self):
        send_verification_email(RequestFactory().get("/", HTTP_HOST="testserver"), self.user)
        self.client.post(reverse("password_reset"), {"email": self.user.email})
        self.assertEqual(len(mail.outbox), 2)
        for message in mail.outbox:
            self.assertIn("https://market.example.com/", message.body)
            self.assertNotIn("testserver", message.body)
        self.assertEqual(len(mail.outbox[1].alternatives), 1)

    def test_reset_failure_is_queued_without_disclosing_account(self):
        with patch("accounts.services.send_mail", side_effect=OSError("SMTP unavailable")):
            response = self.client.post(reverse("password_reset"), {"email": self.user.email})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(EmailDelivery.objects.get().status, EmailDelivery.Status.PENDING)
        self.assertEqual(EmailDelivery.objects.get().attempts, 1)
