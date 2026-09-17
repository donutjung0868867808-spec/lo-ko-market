from django.db.models import F, Q


def notification_summary(request):
    if not request.user.is_authenticated:
        return {
            "unread_notification_count": 0,
            "admin_support_chat_count": 0,
            "seller_support_chat_count": 0,
            "active_market_mode": "seller",
        }

    context = {
        "unread_notification_count": request.user.notifications.filter(is_read=False).count(),
        "admin_support_chat_count": 0,
        "seller_support_chat_count": 0,
        "active_market_mode": (
            "buyer"
            if request.user.is_farmer
            and request.session.get("active_market_mode") == "buyer"
            else "seller"
        ),
    }
    from .models import SupportTicket

    if request.user.is_owner:
        context["admin_support_chat_count"] = SupportTicket.objects.exclude(
            status=SupportTicket.Status.CLOSED
        ).filter(
            Q(admin_read_at__isnull=True, last_seller_message_at__isnull=False)
            | Q(last_seller_message_at__gt=F("admin_read_at"))
        ).count()
    elif request.user.role == request.user.Roles.FARMER:
        context["seller_support_chat_count"] = SupportTicket.objects.filter(
            seller=request.user
        ).filter(
            Q(seller_read_at__isnull=True, last_admin_message_at__isnull=False)
            | Q(last_admin_message_at__gt=F("seller_read_at"))
        ).count()
    return context
