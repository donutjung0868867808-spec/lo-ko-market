from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from accounts.views import admin_login, public_login
from agri_market.admin_dashboard import build_admin_dashboard_context
from agri_market.admin_localization import apply_admin_thai_labels
from agri_market.views import (
    admin_mfa,
    admin_site_preview,
    exit_admin_site_preview,
    health,
    readiness,
)

apply_admin_thai_labels()
handler400 = "agri_market.views.bad_request"
handler403 = "agri_market.views.permission_denied"
handler404 = "agri_market.views.page_not_found"
handler500 = "agri_market.views.server_error"

admin.site.site_header = "ศูนย์จัดการตลาดเกษตรชุมชน"
admin.site.site_title = "ศูนย์จัดการตลาดเกษตรชุมชน"
admin.site.index_title = "จัดการข้อมูลระบบ"
admin.site.site_url = "/admin/site-preview/"


def owner_admin_permission(request):
    user = request.user
    return bool(user.is_active and user.is_staff and user.is_owner)


admin.site.has_permission = owner_admin_permission

_default_admin_index = admin.site.index


def owner_admin_index(request, extra_context=None):
    context = build_admin_dashboard_context()
    context.update(extra_context or {})
    return _default_admin_index(request, context)


admin.site.index = owner_admin_index

urlpatterns = [
    path("health/", health, name="health"),
    path("ready/", readiness, name="readiness"),
    path("admin-mfa/", admin_mfa, name="admin_mfa"),
    path("admin/site-preview/", admin_site_preview, name="admin_site_preview"),
    path("admin-preview/exit/", exit_admin_site_preview, name="exit_admin_site_preview"),
    path("", include("catalog.urls")),
    path("accounts/", include("accounts.urls")),
    path("orders/", include("orders.urls")),
    path("payments/", include("payments.urls")),
    path("api/", include("api.urls")),
    path("login/", public_login, name="login"),
    path("admin-login/", admin_login, name="admin_login"),
    path(
        "logout/",
        auth_views.LogoutView.as_view(next_page="catalog:product_list"),
        name="logout",
    ),
    path(
        "password_reset/",
        auth_views.PasswordResetView.as_view(
            template_name="registration/password_reset.html",
            email_template_name="registration/password_reset_email.html",
            success_url="/password_reset/done/",
        ),
        name="password_reset",
    ),
    path(
        "password_reset/done/",
        auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(template_name="registration/password_reset_confirm.html"),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"),
        name="password_reset_complete",
    ),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)