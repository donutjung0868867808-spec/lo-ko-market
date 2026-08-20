import secrets
import time

from django.conf import settings
from django.core import signing
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.services import queue_email


def health(request):
    return JsonResponse({"status": "ok"})


def readiness(request):
    try:
        connection.ensure_connection()
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except Exception:
        return JsonResponse({"status": "not_ready", "database": "unavailable"}, status=503)
    if pending:
        return JsonResponse(
            {"status": "not_ready", "database": "ok", "migrations": "pending"},
            status=503,
        )
    return JsonResponse({"status": "ready", "database": "ok", "migrations": "ok"})

@login_required
def admin_site_preview(request):
    if not request.user.is_owner:
        return redirect("catalog:product_list")
    response = redirect("catalog:product_list")
    response.set_cookie(
        settings.ADMIN_PREVIEW_COOKIE_NAME,
        signing.dumps(
            "owner-site-preview",
            salt=settings.ADMIN_PREVIEW_COOKIE_SALT,
        ),
        max_age=settings.ADMIN_SESSION_COOKIE_AGE,
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=True,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        path="/",
    )
    return response


@login_required
@require_POST
def exit_admin_site_preview(request):
    response = redirect("catalog:product_list")
    response.delete_cookie(
        settings.ADMIN_PREVIEW_COOKIE_NAME,
        path="/",
        samesite=settings.SESSION_COOKIE_SAMESITE,
    )
    return response


@login_required
def admin_mfa(request):
    if not request.user.is_owner:
        return redirect("catalog:product_list")
    if request.session.get("admin_mfa_verified"):
        return redirect("admin:index")

    now = int(time.time())
    expires_at = int(request.session.get("admin_mfa_expires_at", 0))
    sent_at = int(request.session.get("admin_mfa_sent_at", 0))

    def send_code():
        if not request.user.email:
            messages.error(request, "บัญชีเจ้าของระบบยังไม่มีอีเมลสำหรับรับรหัสยืนยัน")
            return False
        code = f"{secrets.randbelow(1_000_000):06d}"
        request.session["admin_mfa_code_hash"] = make_password(code)
        request.session["admin_mfa_sent_at"] = now
        request.session["admin_mfa_expires_at"] = now + settings.ADMIN_MFA_CODE_MINUTES * 60
        request.session["admin_mfa_attempts"] = 0
        try:
            queue_email(
                request.user.email,
                "รหัสยืนยันการเข้าสู่ระบบผู้ดูแล",
                f"รหัสยืนยันของคุณคือ {code}\nรหัสมีอายุ {settings.ADMIN_MFA_CODE_MINUTES} นาที",
                user=request.user,
                send_now=True,
                raise_on_failure=True,
            )
        except Exception:
            messages.error(request, "ส่งรหัสยืนยันไม่สำเร็จ กรุณาตรวจสอบระบบอีเมล")
            return False
        return True

    if request.method == "POST" and request.POST.get("action") == "resend":
        if now - sent_at < 60:
            messages.warning(request, "กรุณารออย่างน้อย 1 นาทีก่อนขอรหัสใหม่")
        elif send_code():
            messages.success(request, "ส่งรหัสยืนยันใหม่แล้ว")
        return redirect("admin_mfa")

    if request.method == "POST":
        code_hash = request.session.get("admin_mfa_code_hash", "")
        attempts = int(request.session.get("admin_mfa_attempts", 0)) + 1
        request.session["admin_mfa_attempts"] = attempts
        code = request.POST.get("code", "").strip()
        if expires_at <= now:
            messages.error(request, "รหัสหมดอายุแล้ว กรุณาขอรหัสใหม่")
        elif len(code) == 6 and code.isdigit() and check_password(code, code_hash):
            for key in (
                "admin_mfa_code_hash",
                "admin_mfa_sent_at",
                "admin_mfa_expires_at",
                "admin_mfa_attempts",
            ):
                request.session.pop(key, None)
            request.session["admin_mfa_verified"] = True
            request.session.set_expiry(settings.ADMIN_SESSION_COOKIE_AGE)
            return redirect("admin:index")
        else:
            messages.error(request, "รหัสยืนยันไม่ถูกต้อง")

        if attempts >= 5:
            logout(request)
            messages.error(request, "กรอกรหัสผิดเกินกำหนด กรุณาเข้าสู่ระบบใหม่")
            return redirect("admin_login")

    if not request.session.get("admin_mfa_code_hash") or expires_at <= now:
        send_code()
    return render(request, "admin/mfa.html", {"email": request.user.email})

def _error_response(request, status, title, message, action_label="กลับหน้าหลัก", action_url="/"):
    response = render(
        request,
        "errors/error.html",
        {
            "status_code": status,
            "error_title": title,
            "error_message": message,
            "action_label": action_label,
            "action_url": action_url,
        },
        status=status,
    )
    response["Cache-Control"] = "no-store"
    return response


def bad_request(request, exception=None):
    return _error_response(
        request,
        400,
        "ข้อมูลคำขอไม่ถูกต้อง",
        "กรุณาตรวจสอบข้อมูลแล้วลองใหม่อีกครั้ง",
    )


def permission_denied(request, exception=None):
    return _error_response(
        request,
        403,
        "ไม่มีสิทธิ์เข้าถึงหน้านี้",
        "บัญชีของคุณไม่มีสิทธิ์ดำเนินการนี้ หรือการเข้าสู่ระบบอาจหมดอายุ",
        "เข้าสู่ระบบ",
        "/login/",
    )


def page_not_found(request, exception=None):
    return _error_response(
        request,
        404,
        "ไม่พบหน้าที่ต้องการ",
        "ลิงก์อาจไม่ถูกต้อง หรือข้อมูลนี้ถูกย้ายหรือลบแล้ว",
    )


def server_error(request):
    return _error_response(
        request,
        500,
        "ระบบขัดข้องชั่วคราว",
        "ระบบบันทึกเหตุการณ์นี้แล้ว กรุณาลองใหม่อีกครั้งในภายหลัง",
    )


def csrf_failure(request, reason=""):
    return _error_response(
        request,
        403,
        "แบบฟอร์มหมดอายุ",
        "กรุณาโหลดหน้าใหม่ แล้วส่งข้อมูลอีกครั้ง หากยังไม่สำเร็จให้เข้าสู่ระบบใหม่",
        "โหลดหน้าใหม่",
        request.path,
    )