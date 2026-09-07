"""Receive signed tracking updates. No customer data is sent to a provider."""

import base64
import hashlib
import hmac
import json
import uuid

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.services import notify_user
from .models import Order, Shipment, ShipmentEvent


@transaction.atomic
def apply_tracking_event(event):
    event_id = str(uuid.UUID(event["event_id"]))
    payload = event["msg"]
    number = payload.get("tracking_number")
    provider_id = str(payload.get("id") or "")
    if not number or not provider_id or len(provider_id) > 128:
        raise ValueError("Tracking identity is required")
    updated = parse_datetime(payload.get("updated_at") or "")
    if not updated or timezone.is_naive(updated):
        raise ValueError("Tracking timestamp must include a timezone")
    if ShipmentEvent.objects.filter(event_id=event_id).exists():
        return
    shipments = Shipment.objects.filter(provider_id=provider_id).exclude(provider_id="")
    shipment = shipments.first()
    if shipment:
        order = Order.objects.select_for_update().select_related("buyer").get(pk=shipment.order_id)
    else:
        # Require an explicit matching order reference; tracking numbers can be reused.
        order = Order.objects.select_for_update().select_related("buyer").filter(
            reference=payload.get("order_id", ""), tracking_number=number,
            status__in=[Order.Status.SHIPPED, Order.Status.COMPLETED],
        ).first()
        if not order:
            return
        shipment, _ = Shipment.objects.get_or_create(order=order, defaults={
            "tracking_number": number, "provider_id": provider_id,
        })
    if shipment.tracking_number != order.tracking_number and number == order.tracking_number:
        shipment.tracking_number = number
        shipment.provider_id = provider_id
        shipment.provider_updated_at = None
        shipment.status = "Pending"
        shipment.checkpoints = []
    if order.tracking_number != number or shipment.tracking_number != number:
        raise ValueError("Tracking number does not match")
    if shipment.provider_id and shipment.provider_id != provider_id:
        raise ValueError("Tracking provider ID does not match")
    if ShipmentEvent.objects.filter(event_id=event_id).exists():
        return
    ShipmentEvent.objects.create(shipment=shipment, event_id=event_id)
    if shipment.provider_updated_at and updated <= shipment.provider_updated_at:
        return
    points = payload.get("checkpoints") or []
    if not isinstance(points, list):
        raise ValueError("Invalid checkpoints")
    previous = shipment.status
    shipment.provider_id = provider_id
    shipment.status = str(payload.get("tag") or "Pending")[:40]
    shipment.carrier_slug = str(payload.get("slug") or "")[:120]
    shipment.checkpoints = [{
        "time": str(point.get("checkpoint_time") or "")[:80],
        "message": str(point.get("message") or "")[:1000],
        "location": str(point.get("location") or point.get("city") or "")[:255],
    } for point in points[-100:] if isinstance(point, dict)]
    shipment.provider_updated_at = updated
    shipment.save()
    if previous != shipment.status:
        # Delivery by the carrier does not replace buyer acceptance or release funds.
        notify_user(order.buyer, f"พัสดุ {order.reference}", shipment.status_label,
                    order.get_absolute_url(), send_email_message=False)


@csrf_exempt
@require_POST
def aftership_webhook(request):
    secret = settings.AFTERSHIP_WEBHOOK_SECRET
    if not secret or len(request.body) > 256000:
        return HttpResponse(status=400)
    digest = base64.b64encode(hmac.new(secret.encode(), request.body, hashlib.sha256).digest()).decode()
    signature = request.headers.get("aftership-hmac-sha256", "")
    if not signature.isascii() or not hmac.compare_digest(digest, signature):
        return HttpResponse(status=400)
    try:
        event = json.loads(request.body)
        if event.get("event") == "tracking_update":
            apply_tracking_event(event)
    except (ValueError, KeyError, TypeError, AttributeError):
        return HttpResponse(status=400)
    return JsonResponse({"received": True})
