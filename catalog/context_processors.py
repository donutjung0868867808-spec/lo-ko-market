from accounts.models import Community


def search_provinces(request):
    return {
        "search_provinces": Community.objects.filter(
            is_active=True
        ).exclude(
            province=""
        ).values_list(
            "province", flat=True
        ).distinct().order_by("province"),
    }
