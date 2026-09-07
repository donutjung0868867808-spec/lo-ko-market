from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import DirectMessage, Notification, SupportMessage, SupportTicket
from .realtime import publish, serialize_message


@receiver(post_save, sender=DirectMessage)
@receiver(post_save, sender=SupportMessage)
def message_created(sender, instance, created, **kwargs):
    if not created:
        return
    kind = "support" if sender is SupportMessage else "direct"
    pk = instance.ticket_id if kind == "support" else instance.conversation_id
    payload = {"type": "message", "message": serialize_message(instance)}
    transaction.on_commit(lambda: publish(f"chat.{kind}.{pk}", {"type": "chat.event", "payload": payload}))


@receiver(post_save, sender=Notification)
def notification_changed(sender, instance, **kwargs):
    transaction.on_commit(lambda: publish(f"user.{instance.user_id}", {"type": "notification.event"}))


@receiver(post_save, sender=SupportTicket)
def support_room_changed(sender, instance, update_fields=None, **kwargs):
    if update_fields and not {"status", "handled_by"}.intersection(update_fields):
        return
    payload = {"type": "room", "status": instance.status, "label": instance.get_status_display(),
               "can_send": instance.status != SupportTicket.Status.CLOSED}
    transaction.on_commit(lambda: publish(f"chat.support.{instance.pk}", {"type": "chat.event", "payload": payload}))
