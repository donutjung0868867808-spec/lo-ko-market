def notification_summary(request):
    if not request.user.is_authenticated:
        return {"unread_notification_count": 0, "admin_support_chat_count": 0}

    context = {
        "unread_notification_count": request.user.notifications.filter(is_read=False).count(),
        "admin_support_chat_count": 0,
    }
    if request.user.is_owner:
        from .models import SupportTicket

        context["admin_support_chat_count"] = SupportTicket.objects.filter(
            status=SupportTicket.Status.OPEN,
            handled_by__isnull=True,
        ).count()
    return context