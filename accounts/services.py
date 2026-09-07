from datetime import timedelta

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import AuditEvent, EmailDelivery, LoginAttempt, Notification


def deliver_email(delivery, raise_on_failure=False, retry_failed=False):
    failure = None
    with transaction.atomic():
        delivery = EmailDelivery.objects.select_for_update().get(pk=delivery.pk)
        if delivery.status == EmailDelivery.Status.FAILED and retry_failed:
            delivery.status = EmailDelivery.Status.PENDING
        if delivery.status != EmailDelivery.Status.PENDING:
            return delivery
        if delivery.expires_at and delivery.expires_at <= timezone.now():
            delivery.status = EmailDelivery.Status.FAILED
            delivery.last_error = "อีเมลหมดอายุก่อนส่ง"
            delivery.save(update_fields=["status", "last_error", "updated_at"])
            return delivery
        delivery.attempts += 1
        try:
            send_mail(
                delivery.subject,
                delivery.body,
                settings.DEFAULT_FROM_EMAIL,
                [delivery.to_email],
                fail_silently=False,
                html_message=delivery.html_body or None,
            )
        except Exception as exc:
            failure = exc
            delivery.last_error = str(exc)
            delivery.status = (
                EmailDelivery.Status.FAILED
                if delivery.attempts >= settings.EMAIL_MAX_ATTEMPTS
                else EmailDelivery.Status.PENDING
            )
            delay_minutes = min(2 ** delivery.attempts, 60)
            delivery.next_attempt_at = timezone.now() + timedelta(minutes=delay_minutes)
            delivery.save(
                update_fields=[
                    "attempts",
                    "last_error",
                    "status",
                    "next_attempt_at",
                    "updated_at",
                ]
            )
        else:
            delivery.status = EmailDelivery.Status.SENT
            delivery.sent_at = timezone.now()
            delivery.last_error = ""
            delivery.save(
                update_fields=["attempts", "status", "sent_at", "last_error", "updated_at"]
            )
    if failure and raise_on_failure:
        raise failure
    return delivery


def queue_email(to_email, subject, body, user=None, send_now=True, raise_on_failure=False,
                html_body="", expires_at=None):
    delivery = EmailDelivery.objects.create(
        user=user,
        to_email=to_email,
        subject=subject,
        body=body,
        html_body=html_body,
        expires_at=expires_at,
    )
    if send_now:
        return deliver_email(delivery, raise_on_failure=raise_on_failure)
    return delivery


def notify_user(user, title, message="", link="", send_email_message=True):
    notification = Notification.objects.create(
        user=user,
        title=title,
        message=message,
        link=link,
    )
    if send_email_message and user.email:
        body = message
        if link:
            body = f"{body}\n\n{link}" if body else link
        queue_email(user.email, title, body, user=user, send_now=False)
    return notification


def send_verification_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    path = reverse("accounts:verify_email", args=[uid, token])
    url = f"{settings.SITE_URL}{path}" if settings.SITE_URL else request.build_absolute_uri(path)
    queue_email(
        user.email,
        "ยืนยันอีเมลตลาดเกษตรชุมชน",
        f"กรุณายืนยันอีเมลของคุณโดยเปิดลิงก์นี้ภายในระยะเวลาที่กำหนด:\n\n{url}",
        user=user,
        send_now=True,
        raise_on_failure=True,
        expires_at=timezone.now() + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT),
    )


def _dimension_hash(value):
    return salted_hmac("login-throttle", (value or "").strip().lower()).hexdigest()


def client_ip(request):
    if settings.TRUST_X_FORWARDED_FOR:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def login_attempt_for(request, identifier):
    return LoginAttempt.objects.filter(
        identifier_hash=_dimension_hash(identifier),
        ip_hash=_dimension_hash(client_ip(request)),
    ).first()


def is_login_blocked(request, identifier):
    attempt = login_attempt_for(request, identifier)
    return bool(attempt and attempt.blocked_until and attempt.blocked_until > timezone.now())


@transaction.atomic
def record_login_failure(request, identifier):
    attempt, _ = LoginAttempt.objects.get_or_create(
        identifier_hash=_dimension_hash(identifier),
        ip_hash=_dimension_hash(client_ip(request)),
    )
    attempt = LoginAttempt.objects.select_for_update().get(pk=attempt.pk)
    if attempt.blocked_until and attempt.blocked_until <= timezone.now():
        attempt.failed_attempts = 0
        attempt.blocked_until = None
    attempt.failed_attempts += 1
    if attempt.failed_attempts >= settings.LOGIN_MAX_ATTEMPTS:
        attempt.blocked_until = timezone.now() + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
    attempt.save(update_fields=["failed_attempts", "blocked_until", "updated_at"])
    return attempt


def clear_login_failures(request, identifier):
    LoginAttempt.objects.filter(
        identifier_hash=_dimension_hash(identifier),
        ip_hash=_dimension_hash(client_ip(request)),
    ).delete()

def record_audit(request, action, target, description="", before=None, after=None, community=None):
    actor = request.user if request and request.user.is_authenticated else None
    if community is None:
        community = getattr(target, "community", None)
    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        target_type=target._meta.label,
        target_id=str(target.pk or ""),
        description=description,
        before=before or {},
        after=after or {},
        community=community,
        ip_address=client_ip(request) or None if request else None,
    )
