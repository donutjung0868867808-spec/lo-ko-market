import base64
import hashlib
import hmac
import json
import uuid

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Community, Notification, User
from .models import Order, Shipment, ShipmentEvent


@override_settings(AFTERSHIP_WEBHOOK_SECRET="test-only-tracking-secret")
class TrackingWebhookTests(TestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(username="tracking-buyer")
        self.seller = User.objects.create_user(username="tracking-seller", role=User.Roles.FARMER)
        community = Community.objects.create(name="Tracking", slug="tracking", province="Nan")
        self.order = Order.objects.create(
            buyer=self.buyer, seller=self.seller, community=community,
            status=Order.Status.SHIPPED, tracking_number="TH123", shipping_carrier="Thailand Post",
            shipping_name="Buyer", shipping_phone="0800000000", shipping_address="Test address",
        )

    def event(self, tag="InTransit", updated="2026-09-06T12:00:00Z"):
        return {"event": "tracking_update", "event_id": str(uuid.uuid4()), "msg": {
            "id": "test-shipment-id", "order_id": self.order.reference,
            "tracking_number": "TH123", "updated_at": updated, "tag": tag, "slug": "thailand-post",
            "checkpoints": [{"checkpoint_time": updated, "message": "Test checkpoint", "location": "Nan"}],
        }}

    def post(self, event, signed=True):
        body = json.dumps(event).encode()
        signature = base64.b64encode(hmac.new(b"test-only-tracking-secret", body, hashlib.sha256).digest()).decode()
        return self.client.post(reverse("orders:aftership_webhook"), body, content_type="application/json",
                                HTTP_AFTERSHIP_HMAC_SHA256=signature if signed else "invalid")

    def test_delivery_updates_tracking_without_releasing_order_or_money(self):
        event = self.event("Delivered")
        self.assertEqual(self.post(event).status_code, 200)
        self.assertEqual(self.post(event).status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.SHIPPED)
        self.assertEqual(Shipment.objects.get().status, "Delivered")
        self.assertEqual(ShipmentEvent.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.buyer).count(), 1)
        self.client.force_login(self.buyer)
        self.assertContains(self.client.get(self.order.get_absolute_url()), "Test checkpoint")

    def test_older_event_cannot_rewind_delivery(self):
        self.post(self.event("Delivered"))
        self.post(self.event("InTransit", "2026-09-05T12:00:00Z"))
        self.assertEqual(Shipment.objects.get().status, "Delivered")
        self.assertEqual(ShipmentEvent.objects.count(), 2)

    def test_bad_signature_and_unmatched_order_do_not_create_shipment(self):
        self.assertEqual(self.post(self.event(), signed=False).status_code, 400)
        event = self.event()
        event["msg"]["order_id"] = "another-order"
        self.assertEqual(self.post(event).status_code, 200)
        self.assertFalse(Shipment.objects.exists())

    def test_changed_tracking_number_rejects_old_callback(self):
        self.post(self.event())
        self.order.tracking_number = "TH999"
        self.order.save(update_fields=["tracking_number"])
        self.assertEqual(self.post(self.event("Delivered")).status_code, 400)
        self.assertEqual(Shipment.objects.get().status, "InTransit")
        corrected = self.event("Delivered")
        corrected["msg"].update(tracking_number="TH999", id="corrected-shipment")
        self.assertEqual(self.post(corrected).status_code, 200)
        self.assertEqual(Shipment.objects.get().tracking_number, "TH999")
        self.assertEqual(Shipment.objects.get().status, "Delivered")
