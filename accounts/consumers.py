import json
import time
from http.cookies import SimpleCookie
from importlib import import_module

from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError

from .context_processors import notification_summary
from .realtime import can_send, history, mark_read, room_for_user, send_message, socket_user
from types import SimpleNamespace


class AuthenticatedConsumer(JsonWebsocketConsumer):
    def connect(self):
        self.window_started = time.monotonic()
        self.received_count = 0
        cookies = SimpleCookie()
        try:
            cookies.load(dict(self.scope["headers"]).get(b"cookie", b"").decode("latin1"))
            self.scope["admin_socket"] = self.scope["path"].startswith("/ws/admin/")
            name = settings.ADMIN_SESSION_COOKIE_NAME if self.scope["admin_socket"] else settings.SESSION_COOKIE_NAME
            self.scope["session_key"] = cookies[name].value if name in cookies else None
            self.user = socket_user(self.scope)
            self.subscribe()
        except (PermissionDenied, ValueError):
            self.close(code=4403)
            return
        self.accept()
        self.initial()

    def subscribe(self):
        self.group = f"user.{self.user.pk}"
        async_to_sync(self.channel_layer.group_add)(self.group, self.channel_name)

    def initial(self):
        self.notification_event({})

    def disconnect(self, code):
        if getattr(self, "group", None):
            async_to_sync(self.channel_layer.group_discard)(self.group, self.channel_name)

    def receive(self, text_data=None, bytes_data=None, **kwargs):
        if time.monotonic() - self.window_started > 10:
            self.window_started, self.received_count = time.monotonic(), 0
        self.received_count += 1
        if self.received_count > 120:
            self.close(code=4429)
            return
        if not text_data or len(text_data) > 20000:
            self.close(code=4400)
            return
        try:
            content = json.loads(text_data)
            if not isinstance(content, dict):
                raise ValueError
            self.user = socket_user(self.scope)
            self.receive_json(content)
        except PermissionDenied:
            self.close(code=4403)
        except (ValueError, TypeError, ValidationError) as exc:
            error = " ".join(exc.messages) if isinstance(exc, ValidationError) else "คำขอไม่ถูกต้อง"
            self.send_json({"type": "error", "message": error})

    def receive_json(self, content, **kwargs):
        if content.get("type") == "ping":
            async_to_sync(self.channel_layer.group_add)(self.group, self.channel_name)
            self.send_json({"type": "pong"})

    def notification_event(self, event):
        try:
            self.user = socket_user(self.scope)
        except PermissionDenied:
            self.close(code=4403)
            return
        session = import_module(settings.SESSION_ENGINE).SessionStore(self.scope.get("session_key"))
        counts = notification_summary(SimpleNamespace(user=self.user, session=session))
        self.send_json({"type": "notifications", **counts})


class ChatConsumer(AuthenticatedConsumer):
    def subscribe(self):
        self.kind = self.scope["url_route"]["kwargs"]["kind"]
        self.pk = int(self.scope["url_route"]["kwargs"]["pk"])
        if self.user.is_owner and settings.ADMIN_MFA_REQUIRED and not self.scope.get("admin_socket"):
            raise PermissionDenied
        room_for_user(self.user, self.kind, self.pk)
        self.group = f"chat.{self.kind}.{self.pk}"
        self.last_typing = 0
        async_to_sync(self.channel_layer.group_add)(self.group, self.channel_name)

    def initial(self):
        self.send_json({"type": "ready", "user_id": self.user.pk})

    def receive_json(self, content, **kwargs):
        room = room_for_user(self.user, self.kind, self.pk)
        action = content.get("type")
        if action == "history":
            before = max(0, int(content.get("before") or 0))
            after = max(0, int(content.get("after") or 0))
            self.send_json(history(self.user, self.kind, self.pk, before=before, after=after))
        elif action == "send":
            message = send_message(self.user, self.kind, self.pk, content.get("body"), content.get("client_id"))
            self.send_json({"type": "ack", "message": message})
        elif action == "read":
            mark_read(self.user, self.kind, self.pk, max(0, int(content.get("through") or 0)))
        elif action == "typing" and can_send(self.user, self.kind, room) and time.monotonic() - self.last_typing > 1:
            self.last_typing = time.monotonic()
            async_to_sync(self.channel_layer.group_send)(self.group, {
                "type": "chat.event", "payload": {"type": "typing", "sender_id": self.user.pk},
            })
        else:
            super().receive_json(content)

    def chat_event(self, event):
        try:
            self.user = socket_user(self.scope)
            room_for_user(self.user, self.kind, self.pk)
        except PermissionDenied:
            self.close(code=4403)
            return
        self.send_json(event["payload"])
