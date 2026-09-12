"""Shared authorization, persistence and events for WebSocket chat."""

import logging
from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace
from uuid import UUID

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth import get_user
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .models import ChatBlock, Conversation, DirectMessage, SupportMessage, SupportTicket, User
from .services import notify_user

logger = logging.getLogger(__name__)


def publish(group, event):
    try:
        async_to_sync(get_channel_layer().group_send)(group, event)
    except Exception:
        logger.exception("Realtime delivery unavailable for %s; messages remain in the database", group)


def socket_user(scope):
    # Reload on every operation, including delivery, to honor logout and revocation.
    session = import_module(settings.SESSION_ENGINE).SessionStore(scope.get("session_key"))
    user = get_user(SimpleNamespace(session=session))
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied
    if scope.get("admin_socket"):
        if not user.is_owner or (settings.ADMIN_MFA_REQUIRED and not session.get("admin_mfa_verified")):
            raise PermissionDenied
    return user


def room_for_user(user, kind, pk, lock=False):
    model = SupportTicket if kind == "support" else Conversation
    rooms = model.objects.select_for_update() if lock else model.objects.all()
    room = rooms.filter(pk=pk).first()
    if room is None:
        raise PermissionDenied
    if kind == "support":
        allowed = user.is_owner or room.seller_id == user.pk
    else:
        allowed = user.pk in {room.buyer_id, room.seller_id}
    if not allowed:
        raise PermissionDenied
    return room


def can_send(user, kind, room):
    if kind == "support":
        return room.status != SupportTicket.Status.CLOSED
    other = room.other_participant(user)
    return other.is_active and not ChatBlock.objects.filter(
        Q(blocker=user, blocked=other) | Q(blocker=other, blocked=user)
    ).exists()


def serialize_message(message, room=None):
    read_at = getattr(message, "read_at", None)
    if isinstance(message, SupportMessage) and room:
        read_at = room.admin_read_at if message.sender_id == room.seller_id else room.seller_read_at
        if read_at and read_at < message.created_at:
            read_at = None
    reader = None
    if read_at and isinstance(room, Conversation):
        reader = room.other_participant(message.sender)
    elif read_at and isinstance(room, SupportTicket):
        reader = room.handled_by if message.sender_id == room.seller_id else room.seller
    return {
        "id": message.pk, "sender_id": message.sender_id,
        "sender_name": message.sender.display_name or message.sender.username,
        "sender_avatar_url": message.sender.avatar.url if message.sender.avatar else None,
        "body": message.body, "created_at": message.created_at.isoformat(),
        "client_id": str(message.client_id) if message.client_id else None,
        "read_at": read_at.isoformat() if read_at else None,
        "reader_name": (reader.display_name or reader.username) if reader else None,
        "reader_avatar_url": reader.avatar.url if reader and reader.avatar else None,
    }


def history(user, kind, pk, before=None, after=None):
    room = room_for_user(user, kind, pk)
    queryset = room.messages.select_related("sender")
    if before:
        queryset = queryset.filter(pk__lt=before)
    if after:
        queryset = queryset.filter(pk__gt=after)
        rows = list(queryset.order_by("pk")[:51])
        more = len(rows) > 50
        rows = rows[:50]
    else:
        rows = list(queryset.order_by("-pk")[:51])
        more = len(rows) > 50
        rows = list(reversed(rows[:50]))
    return {"type": "history", "messages": [serialize_message(row, room) for row in rows],
            "more": more, "before": before, "after": after, "can_send": can_send(user, kind, room)}


@transaction.atomic
def send_message(user, kind, pk, body, client_id):
    room = room_for_user(user, kind, pk, lock=True)
    if not can_send(user, kind, room):
        raise ValidationError("ไม่สามารถส่งข้อความในบทสนทนานี้ได้")
    model = SupportMessage if kind == "support" else DirectMessage
    try:
        client_id = UUID(str(client_id))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("รหัสข้อความไม่ถูกต้อง")
    existing = model.objects.filter(sender=user, client_id=client_id).first()
    if existing:
        parent_id = existing.ticket_id if kind == "support" else existing.conversation_id
        if parent_id != pk:
            raise ValidationError("รหัสข้อความนี้ถูกใช้แล้ว")
        return serialize_message(existing, room)
    maximum = 3000 if kind == "support" else 2000
    if not isinstance(body, str) or not body.strip() or len(body) > maximum:
        raise ValidationError(f"กรุณาระบุข้อความไม่เกิน {maximum} ตัวอักษร")
    if room.messages.filter(sender=user, created_at__gte=timezone.now() - timedelta(minutes=1)).count() >= 12:
        raise ValidationError("ส่งข้อความเร็วเกินไป กรุณารอ 1 นาที")
    parent = {"ticket": room} if kind == "support" else {"conversation": room}
    message = model.objects.create(sender=user, body=body.strip(), client_id=client_id, **parent)
    if kind == "support":
        if user.is_owner:
            room.status = SupportTicket.Status.IN_PROGRESS
            room.handled_by = user
            room.last_admin_message_at = message.created_at
            recipients = [room.seller]
        else:
            room.status = SupportTicket.Status.OPEN
            room.last_seller_message_at = message.created_at
            recipients = User.objects.filter(Q(role=User.Roles.OWNER) | Q(is_superuser=True), is_active=True)
        room.save()
    else:
        Conversation.objects.filter(pk=pk).update(updated_at=message.created_at)
        recipients = [room.other_participant(user)]
    for recipient in recipients:
        if kind == "support" and recipient.is_owner:
            link = reverse("admin:accounts_supportticket_changelist") + f"?ticket={pk}"
        else:
            link = reverse("accounts:support_ticket_detail" if kind == "support" else "accounts:conversation_detail", args=[pk])
        notify_user(recipient, f"ข้อความใหม่จาก {user}", message.body[:120], link, send_email_message=False)
    return serialize_message(message, room)


@transaction.atomic
def mark_read(user, kind, pk, through):
    room = room_for_user(user, kind, pk, lock=True)
    last = room.messages.filter(pk=through).first()
    if not last:
        return
    now = timezone.now()
    if kind == "direct":
        changed = room.messages.filter(pk__lte=through, read_at__isnull=True).exclude(sender=user).update(read_at=now)
    else:
        field = "admin_read_at" if user.is_owner else "seller_read_at"
        previous = getattr(room, field)
        if previous is None or previous < last.created_at:
            setattr(room, field, last.created_at)
            fields = [field]
            if user.is_owner and room.handled_by_id != user.pk:
                room.handled_by = user
                fields.append("handled_by")
            room.save(update_fields=fields)
    transaction.on_commit(lambda: publish(f"chat.{kind}.{pk}", {
        "type": "chat.event", "payload": {
            "type": "read", "sender_id": user.pk, "through": through,
            "read_at": now.isoformat(),
            "reader_name": user.display_name or user.username,
            "reader_avatar_url": user.avatar.url if user.avatar else None,
        },
    }))
    transaction.on_commit(lambda: publish(f"user.{user.pk}", {"type": "notification.event"}))
