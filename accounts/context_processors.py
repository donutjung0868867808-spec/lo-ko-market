from django.db.models import F, Q


def notification_summary(request):
    user = getattr(request, "user", None)
    session = getattr(request, "session", {})
    if not getattr(user, "is_authenticated", False):
        return {
            "unread_notification_count": 0,
            "cart_item_count": 0,
            "admin_support_chat_count": 0,
            "seller_support_chat_count": 0,
            "active_market_mode": "seller",
        }

    context = {
        "unread_notification_count": user.notifications.filter(is_read=False).count(),
        "cart_item_count": len(session.get("cart", {})),
        "admin_support_chat_count": 0,
        "seller_support_chat_count": 0,
        "active_market_mode": (
            "buyer"
            if user.is_farmer
            and session.get("active_market_mode") == "buyer"
            else "seller"
        ),
    }
    from .models import SupportTicket

    if user.is_owner:
        context["admin_support_chat_count"] = SupportTicket.objects.exclude(
            status=SupportTicket.Status.CLOSED
        ).filter(
            Q(admin_read_at__isnull=True, last_seller_message_at__isnull=False)
            | Q(last_seller_message_at__gt=F("admin_read_at"))
        ).count()
    elif user.role == user.Roles.FARMER:
        context["seller_support_chat_count"] = SupportTicket.objects.filter(
            seller=user
        ).filter(
            Q(seller_read_at__isnull=True, last_admin_message_at__isnull=False)
            | Q(last_admin_message_at__gt=F("seller_read_at"))
        ).count()
    return context
