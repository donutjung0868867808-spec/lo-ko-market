"""Receive signed tracking updates. No customer data is sent to a provider."""

import base64
import hashlib
import hmac
import json
import logging
import uuid
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.services import notify_user
from .models import Order, Shipment, ShipmentEvent


logger = logging.getLogger(__name__)
AFTERSHIP_TRACKINGS_URL = "https://api.aftership.com/tracking/2026-07/trackings"
AFTERSHIP_CARRIER_SLUGS = {
    "thailand post": "thailand-post",
    "ไปรษณีย์ไทย": "thailand-post",
    "j&t express": "jtexpress",
    "j and t express": "jtexpress",
    "kerry express": "kerry-logistics",
    "spx express": "spx-th",
    "shopee express": "spx-th",
}


def aftership_carrier_slug(carrier):
    normalized = " ".join((carrier or "").casefold().split())
    return AFTERSHIP_CARRIER_SLUGS.get(normalized, "")


def _record_registration_failure(shipment_id, error, retryable=True):
    with transaction.atomic():
        shipment = Shipment.objects.select_for_update().get(pk=shipment_id)
        if shipment.provider_id:
            return
        shipment.attempts += 1
        exhausted = not retryable or shipment.attempts >= settings.AFTERSHIP_MAX_ATTEMPTS
        shipment.status = "Exception" if exhausted else "Pending"
        shipment.last_error = str(error)[:255]
        shipment.next_sync_at = (
            None
            if exhausted
            else timezone.now()
            + timedelta(minutes=min(2 ** shipment.attempts, 360))
        )
        shipment.save(
            update_fields=[
                "attempts",
                "status",
                "last_error",
                "next_sync_at",
                "updated_at",
            ]
        )
    logger.warning("Unable to register AfterShip tracking for shipment %s: %s", shipment_id, error)


def register_aftership_tracking(order_id):
    """Register a shipped order when automatic AfterShip tracking is configured."""
    if not settings.AFTERSHIP_API_KEY:
        return False

    now = timezone.now()
    with transaction.atomic():
        order = (
            Order.objects.select_for_update()
            .filter(
                pk=order_id,
                status__in=[Order.Status.SHIPPED, Order.Status.COMPLETED],
            )
            .first()
        )
        if not order or not order.tracking_number:
            return False

        carrier_slug = aftership_carrier_slug(order.shipping_carrier)
        shipment, _ = Shipment.objects.select_for_update().get_or_create(
            order=order,
            defaults={
                "tracking_number": order.tracking_number,
                "carrier_slug": carrier_slug,
                "next_sync_at": now,
            },
        )
        if shipment.tracking_number != order.tracking_number:
            shipment.tracking_number = order.tracking_number
            shipment.carrier_slug = carrier_slug
            shipment.provider_id = ""
            shipment.status = "Pending"
            shipment.checkpoints = []
            shipment.provider_updated_at = None
            shipment.attempts = 0
            shipment.last_error = ""
        if shipment.provider_id:
            return True
        if shipment.next_sync_at and shipment.next_sync_at > now:
            return False
        shipment.carrier_slug = carrier_slug
        # A short lease prevents the cron job and the on-commit callback from
        # submitting the same tracking number concurrently.
        shipment.next_sync_at = now + timedelta(minutes=5)
        shipment.save(
            update_fields=[
                "tracking_number",
                "carrier_slug",
                "provider_id",
                "status",
                "checkpoints",
                "provider_updated_at",
                "attempts",
                "last_error",
                "next_sync_at",
                "updated_at",
            ]
        )

    payload_data = {
        "tracking_number": order.tracking_number,
        "title": order.reference,
        "order_id": order.reference,
        "order_number": order.reference,
        "shipment_direction": "forward",
    }
    if carrier_slug:
        payload_data["slug"] = carrier_slug
    payload = json.dumps(payload_data).encode("utf-8")
    request = Request(
        AFTERSHIP_TRACKINGS_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "as-api-key": settings.AFTERSHIP_API_KEY,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=settings.AFTERSHIP_REQUEST_TIMEOUT_SECONDS) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, ValueError) as exc:
        retryable = not isinstance(exc, HTTPError) or exc.code == 429 or exc.code >= 500
        _record_registration_failure(shipment.pk, exc, retryable=retryable)
        return False

    tracking = response_data.get("data", {}).get("tracking") or response_data.get("tracking") or response_data.get("data", {})
    provider_id = str(tracking.get("id") or "")[:128] if isinstance(tracking, dict) else ""
    carrier_slug = str(tracking.get("slug") or "")[:120] if isinstance(tracking, dict) else ""
    if not provider_id:
        _record_registration_failure(
            shipment.pk,
            "AfterShip did not return a tracking id",
            retryable=False,
        )
        return False

    with transaction.atomic():
        shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
        if shipment.tracking_number != order.tracking_number:
            return False
        shipment.provider_id = provider_id
        shipment.carrier_slug = carrier_slug
        shipment.status = str(tracking.get("tag") or "Pending")[:40]
        shipment.attempts = 0
        shipment.last_error = ""
        shipment.next_sync_at = None
        shipment.save(
            update_fields=[
                "provider_id",
                "carrier_slug",
                "status",
                "attempts",
                "last_error",
                "next_sync_at",
                "updated_at",
            ]
        )
    return True


def register_pending_aftership_trackings(batch_size=100):
    """Retry shipped orders that do not yet have an AfterShip tracking id."""
    if not settings.AFTERSHIP_API_KEY:
        return 0

    now = timezone.now()
    order_ids = Order.objects.filter(
        status__in=[Order.Status.SHIPPED, Order.Status.COMPLETED],
    ).exclude(tracking_number="").filter(
        Q(shipment__isnull=True)
        | (
            Q(shipment__provider_id="")
            & Q(shipment__status="Pending")
            & (Q(shipment__next_sync_at__isnull=True) | Q(shipment__next_sync_at__lte=now))
        )
    ).values_list("pk", flat=True)[:batch_size]
    registered = 0
    for order_id in order_ids:
        before = Shipment.objects.filter(order_id=order_id).values_list("provider_id", flat=True).first() or ""
        register_aftership_tracking(order_id)
        after = Shipment.objects.filter(order_id=order_id).values_list("provider_id", flat=True).first() or ""
        registered += int(not before and bool(after))
    return registered


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
        shipment.attempts = 0
        shipment.last_error = ""
        shipment.next_sync_at = timezone.now()
    if order.tracking_number != number or shipment.tracking_number != number:
        raise ValueError("Tracking number does not match")
    if shipment.provider_id and shipment.provider_id != provider_id:
        raise ValueError("Tracking provider ID does not match")
    _, created = ShipmentEvent.objects.get_or_create(
        event_id=event_id,
        defaults={"shipment": shipment},
    )
    if not created:
        return
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
    if shipment.status == "Delivered" and not order.delivered_at:
        order.delivered_at = updated
        order.save(update_fields=["delivered_at", "updated_at"])
    if previous != shipment.status:
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
