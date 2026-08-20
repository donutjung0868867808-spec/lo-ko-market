from django.conf import settings
from django.core import signing
from django.http import HttpResponse
from django.shortcuts import redirect

from accounts.services import clear_login_failures, is_login_blocked, record_login_failure


class AdminCookieScopeMiddleware:
    """Keep public, admin, and admin-preview sessions isolated."""

    admin_path_prefixes = ("/admin/", "/admin-login/", "/admin-mfa/")
    admin_exact_paths = ("/admin", "/admin-login", "/admin-mfa")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        admin_path = self.is_admin_path(request.path_info)
        preview_scope = self.is_preview_request(request)
        request.admin_preview = preview_scope

        if not admin_path and not preview_scope:
            return self.get_response(request)

        session_cookie_name = settings.SESSION_COOKIE_NAME
        csrf_cookie_name = settings.CSRF_COOKIE_NAME
        admin_session_cookie_name = settings.ADMIN_SESSION_COOKIE_NAME
        admin_csrf_cookie_name = settings.ADMIN_CSRF_COOKIE_NAME

        self._use_admin_request_cookie(request, session_cookie_name, admin_session_cookie_name)
        self._use_admin_request_cookie(request, csrf_cookie_name, admin_csrf_cookie_name)

        is_login_post = request.method == "POST" and request.path_info.rstrip("/") == "/admin/login"
        identifier = request.POST.get("username", "").strip() if is_login_post else ""
        if is_login_post and identifier and is_login_blocked(request, identifier):
            return HttpResponse(
                "มีการเข้าสู่ระบบไม่สำเร็จหลายครั้ง กรุณารอแล้วลองใหม่",
                status=429,
                content_type="text/plain; charset=utf-8",
            )

        response = self.get_response(request)
        if is_login_post and identifier:
            if 300 <= response.status_code < 400:
                clear_login_failures(request, identifier)
            else:
                record_login_failure(request, identifier)

        self._rename_response_cookie(response, session_cookie_name, admin_session_cookie_name)
        self._rename_response_cookie(response, csrf_cookie_name, admin_csrf_cookie_name)

        if request.path_info.rstrip("/") == "/admin/logout":
            response.delete_cookie(
                settings.ADMIN_PREVIEW_COOKIE_NAME,
                path="/",
                samesite=settings.SESSION_COOKIE_SAMESITE,
            )
        return response

    def is_admin_path(self, path):
        return path in self.admin_exact_paths or path.startswith(self.admin_path_prefixes)

    def is_preview_request(self, request):
        value = request.COOKIES.get(settings.ADMIN_PREVIEW_COOKIE_NAME)
        if not value:
            return False
        try:
            payload = signing.loads(
                value,
                salt=settings.ADMIN_PREVIEW_COOKIE_SALT,
                max_age=settings.ADMIN_SESSION_COOKIE_AGE,
            )
        except signing.BadSignature:
            return False
        return payload == "owner-site-preview"

    def _use_admin_request_cookie(self, request, public_name, admin_name):
        cookies = request.COOKIES.copy()
        admin_value = cookies.get(admin_name)
        cookies.pop(public_name, None)
        if admin_value is not None:
            cookies[public_name] = admin_value
        request.COOKIES = cookies

    def _rename_response_cookie(self, response, public_name, admin_name):
        if public_name not in response.cookies:
            return

        source = response.cookies[public_name]
        response.cookies[admin_name] = source.value
        target = response.cookies[admin_name]
        for key, value in source.items():
            if value:
                target[key] = value
        del response.cookies[public_name]


class OwnerMfaMiddleware:
    """Require a second factor before an owner can use Django Admin."""

    exempt_paths = {"/admin/login/", "/admin/logout/", "/admin-mfa/"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.ADMIN_MFA_REQUIRED:
            return self.get_response(request)
        path = request.path_info
        is_admin = path == "/admin" or path.startswith("/admin/")
        if (
            is_admin
            and path not in self.exempt_paths
            and request.user.is_authenticated
            and request.user.is_owner
            and not request.session.get("admin_mfa_verified")
        ):
            return redirect("admin_mfa")
        return self.get_response(request)