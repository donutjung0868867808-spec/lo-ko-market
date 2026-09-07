import uuid

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.sessions.models import Session
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from agri_market.asgi import application
from .models import ChatBlock, Community, Conversation, SupportMessage, SupportTicket, User


@override_settings(
    ALLOWED_HOSTS=["testserver"], ADMIN_MFA_REQUIRED=True,
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class RealtimeTests(TransactionTestCase):
    def setUp(self):
        self.seller = User.objects.create_user(username="socket-seller", role=User.Roles.FARMER)
        self.buyer = User.objects.create_user(username="socket-buyer")
        self.outsider = User.objects.create_user(username="socket-outsider")
        self.owner = User.objects.create_user(username="socket-owner", role=User.Roles.OWNER, is_staff=True)
        self.community = Community.objects.create(name="Realtime", slug="realtime", province="Nan")
        self.ticket = SupportTicket.objects.create(seller=self.seller, community=self.community, subject="Help")
        self.room = Conversation.objects.create(buyer=self.buyer, seller=self.seller)
        self.seller_cookie, self.seller_key = self.cookie(self.seller)
        self.buyer_cookie, _ = self.cookie(self.buyer)
        self.outsider_cookie, _ = self.cookie(self.outsider)
        self.owner_cookie, _ = self.cookie(self.owner, admin=True, mfa=True)
        self.unverified_cookie, _ = self.cookie(self.owner, admin=True)

    def cookie(self, user, admin=False, mfa=False):
        client = Client()
        client.force_login(user)
        session = client.session
        session["admin_mfa_verified"] = mfa
        session.save()
        name = settings.ADMIN_SESSION_COOKIE_NAME if admin else settings.SESSION_COOKIE_NAME
        return f"{name}={session.session_key}".encode(), session.session_key

    def socket(self, path, cookie=b"", origin=b"http://testserver"):
        return WebsocketCommunicator(application, path, headers=[(b"cookie", cookie), (b"origin", origin)])

    async def event(self, socket, kind):
        for _ in range(12):
            result = await socket.receive_json_from(timeout=5)
            if result["type"] == kind:
                return result
        self.fail(f"Missing event: {kind}")

    def test_support_two_way_chat_notifies_admin_and_survives_reconnect(self):
        async def scenario():
            seller = self.socket(f"/ws/chat/support/{self.ticket.pk}/", self.seller_cookie)
            admin = self.socket(f"/ws/admin/chat/support/{self.ticket.pk}/", self.owner_cookie)
            alerts = self.socket("/ws/admin/events/", self.owner_cookie)
            for socket in [seller, admin, alerts]:
                self.assertTrue((await socket.connect())[0])
            await self.event(seller, "ready")
            await self.event(admin, "ready")
            self.assertEqual((await self.event(alerts, "notifications"))["admin_support_chat_count"], 0)
            message = {"type": "send", "body": "Seller question", "client_id": str(uuid.uuid4())}
            await seller.send_json_to(message)
            sent = (await self.event(seller, "ack"))["message"]
            self.assertEqual((await self.event(admin, "message"))["message"]["id"], sent["id"])
            self.assertEqual((await self.event(alerts, "notifications"))["admin_support_chat_count"], 1)
            await seller.send_json_to(message)
            self.assertEqual((await self.event(seller, "ack"))["message"]["id"], sent["id"])
            await admin.send_json_to({"type": "read", "through": sent["id"]})
            await self.event(seller, "read")
            self.assertEqual((await self.event(alerts, "notifications"))["admin_support_chat_count"], 0)
            await admin.send_json_to({"type": "send", "body": "Admin answer", "client_id": str(uuid.uuid4())})
            answer = (await self.event(admin, "ack"))["message"]
            self.assertEqual((await self.event(seller, "message"))["message"]["id"], answer["id"])
            await seller.disconnect()
            seller = self.socket(f"/ws/chat/support/{self.ticket.pk}/", self.seller_cookie)
            self.assertTrue((await seller.connect())[0])
            await self.event(seller, "ready")
            await seller.send_json_to({"type": "history"})
            history = await self.event(seller, "history")
            self.assertEqual(len(history["messages"]), 2)
            self.assertIsNotNone(history["messages"][0]["read_at"])
            await seller.disconnect()
            await admin.disconnect()
            await alerts.disconnect()
        async_to_sync(scenario)()
        self.assertEqual(SupportMessage.objects.count(), 2)

    def test_rejects_outsiders_missing_mfa_and_wrong_origin(self):
        async def scenario():
            cases = [
                self.socket(f"/ws/chat/support/{self.ticket.pk}/"),
                self.socket(f"/ws/chat/support/{self.ticket.pk}/", self.outsider_cookie),
                self.socket(f"/ws/chat/direct/{self.room.pk}/", self.outsider_cookie),
                self.socket("/ws/admin/events/", self.unverified_cookie),
                self.socket("/ws/admin/events/", self.seller_cookie),
                self.socket("/ws/events/", self.seller_cookie, b"https://attacker.example"),
            ]
            for socket in cases:
                self.assertFalse((await socket.connect())[0])
                await socket.disconnect()
        async_to_sync(scenario)()

    def test_logout_revokes_existing_socket(self):
        async def scenario():
            socket = self.socket("/ws/events/", self.seller_cookie)
            self.assertTrue((await socket.connect())[0])
            await self.event(socket, "notifications")
            await database_sync_to_async(Session.objects.filter(session_key=self.seller_key).delete)()
            await socket.send_json_to({"type": "ping"})
            self.assertEqual((await socket.receive_output(timeout=5))["code"], 4403)
            await socket.disconnect()
        async_to_sync(scenario)()

    def test_owner_http_route_cannot_bypass_admin_mfa(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("accounts:support_ticket_detail", args=[self.ticket.pk]),
                                    {"body": "Must not be sent"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("admin:accounts_supportticket_changelist")))
        self.assertFalse(self.ticket.messages.exists())

    def test_blocked_direct_chat_cannot_send_and_typing_is_live(self):
        async def scenario():
            seller = self.socket(f"/ws/chat/direct/{self.room.pk}/", self.seller_cookie)
            buyer = self.socket(f"/ws/chat/direct/{self.room.pk}/", self.buyer_cookie)
            for socket in [seller, buyer]:
                self.assertTrue((await socket.connect())[0])
                await self.event(socket, "ready")
            await buyer.send_json_to({"type": "typing"})
            self.assertEqual((await self.event(seller, "typing"))["sender_id"], self.buyer.pk)
            await database_sync_to_async(ChatBlock.objects.create)(blocker=self.seller, blocked=self.buyer)
            await buyer.send_json_to({"type": "send", "body": "Blocked", "client_id": str(uuid.uuid4())})
            await self.event(buyer, "error")
            await seller.disconnect()
            await buyer.disconnect()
        async_to_sync(scenario)()
