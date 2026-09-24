import hashlib
import hmac
import json
import time

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from .models import SellerPaymentAccount, StripeEvent


@override_settings(
    DEBUG=False, SECURE_SSL_REDIRECT=False, STRIPE_SECRET_KEY="sk_test_fixture",
    STRIPE_WEBHOOK_SECRET="whsec_platform_fixture",
    STRIPE_CONNECT_WEBHOOK_SECRET="whsec_connect_fixture",
)
class ConnectWebhookTests(TestCase):
    def setUp(self):
        seller = User.objects.create_user(username="connect-webhook-seller", role=User.Roles.FARMER)
        self.account = SellerPaymentAccount.objects.create(seller=seller, stripe_account_id="acct_fixture")
        self.payload = {
            "id": "evt_connect_fixture", "object": "event", "type": "account.updated",
            "account": "acct_fixture", "data": {"object": {
                "id": "acct_fixture", "payouts_enabled": True, "charges_enabled": True, "details_submitted": True,
            }},
        }

    def post_event(self, secret="whsec_connect_fixture"):
        body = json.dumps(self.payload).encode()
        timestamp = str(int(time.time()))
        digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        return self.client.post(reverse("payments:stripe_connect_webhook"), body,
                                content_type="application/json", HTTP_STRIPE_SIGNATURE=f"t={timestamp},v1={digest}")

    def test_connect_signature_updates_seller_and_deduplicates(self):
        self.assertEqual(self.post_event().status_code, 200)
        self.assertEqual(self.post_event().status_code, 200)
        self.account.refresh_from_db()
        self.assertTrue(self.account.payouts_enabled)
        self.assertEqual(StripeEvent.objects.count(), 1)

    def test_platform_secret_is_not_valid_for_connect_endpoint(self):
        self.assertEqual(self.post_event("whsec_platform_fixture").status_code, 400)
        self.account.refresh_from_db()
        self.assertFalse(self.account.payouts_enabled)
        self.assertFalse(StripeEvent.objects.exists())

    def test_connect_endpoint_cannot_process_platform_checkout(self):
        self.payload["type"] = "checkout.session.completed"
        self.assertEqual(self.post_event().status_code, 400)
        self.assertFalse(StripeEvent.objects.exists())

    @override_settings(STRIPE_SECRET_KEY="sk_live_fixture", PAYMENT_MODE="live")
    def test_test_events_cannot_change_live_account_readiness(self):
        self.payload["livemode"] = False
        response = self.post_event()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ignored"], "different_mode")
        self.account.refresh_from_db()
        self.assertFalse(self.account.payouts_enabled)
