from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped(request, *args, **kwargs):
            if request.user.is_owner or request.user.role in roles:
                return view_func(request, *args, **kwargs)
            messages.error(request, "บัญชีนี้ไม่มีสิทธิ์เข้าถึงหน้านั้น")
            return redirect("accounts:dashboard")

        return wrapped

    return decorator


def user_community(user):
    if hasattr(user, "community_staff_profile"):
        return user.community_staff_profile.community
    if hasattr(user, "farmer_profile"):
        return user.farmer_profile.community
    return None
