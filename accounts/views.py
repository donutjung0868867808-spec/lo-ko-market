import logging
import mimetypes
from datetime import date, timedelta
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.hashers import make_password
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.db.models import Avg, Count, F, Max, OuterRef, Prefetch, Q, Subquery, Sum
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode
from django.views.decorators.http import require_POST

from catalog.forms import ProductForm
from catalog.models import Product, ProductClick, ProductDetailImage, ProductFavorite, ProductImage, ProductReview, SellerFavorite, SellerStoreVisit
from orders.models import Order
from payments.models import CustomerPaymentProfile, Refund, SavedPaymentMethod, SellerPaymentAccount, SellerSettlement

from .decorators import role_required, user_community
from .forms import (
    ConsumerSignupForm,
    DeliveryAddressForm,
    DirectMessageForm,
    FarmerProfileForm,
    FarmerSignupForm,
    NewsPostForm,
    NotificationForm,
    ReportForm,
    ReportMessageForm,
    ReportResolutionForm,
    StaffFarmerProfileForm,
    SellerStoreDetailsForm,
    SellerStoreProfileForm,
    SupportMessageForm,
    SupportTicketCreateForm,
    StaffSellerAccountForm,
    UserProfileForm,
    split_display_name,
)
from .models import AuditEvent, ChatBlock, Conversation, DeliveryAddress, DirectMessage, FarmerProfile, NewsPost, Notification, Report, ReportMessage, StoreCoverSlide, SupportMessage, SupportTicket, User, chat_media_type_for_upload
from .realtime import serialize_message
from .services import (
    clear_login_failures,
    is_login_blocked,
    notify_user,
    notify_news_post,
    queue_email,
    record_audit,
    record_login_failure,
    send_verification_email,
)


logger = logging.getLogger(__name__)


MEMBER_ROLE_OPTIONS = {
    "consumers": (User.Roles.CONSUMER, "ผู้บริโภค"),
    "farmers": (User.Roles.FARMER, "เกษตรกรชุมชน"),
    "staff": (User.Roles.COOPERATIVE_STAFF, "เจ้าหน้าที่สหกรณ์/วิสาหกิจชุมชน"),
}


def visible_news_queryset(user):
    news = NewsPost.objects.select_related("created_by")
    if user.is_authenticated and user.is_owner:
        return news
    news = news.filter(is_published=True)
    if not user.is_authenticated:
        return news.filter(audience=NewsPost.Audience.ALL)
    allowed = [NewsPost.Audience.ALL]
    if user.is_consumer:
        allowed.append(NewsPost.Audience.CONSUMERS)
    if user.is_farmer:
        allowed.append(NewsPost.Audience.FARMERS)
    if user.is_cooperative_staff or user.is_owner:
        allowed.append(NewsPost.Audience.STAFF)
    return news.filter(audience__in=allowed)


def scoped_reports(user):
    reports = Report.objects.select_related(
        "reporter",
        "reported_user",
        "product",
        "order",
        "community",
        "handled_by",
    )
    if user.is_owner:
        return reports
    if user.is_cooperative_staff:
        community = user_community(user)
        if not community:
            return reports.none()
        return reports.filter(
            Q(community=community)
            | Q(product__community=community)
            | Q(order__community=community)
            | Q(reported_user__farmer_profile__community=community)
        ).distinct()
    return reports.filter(reporter=user)


def managed_users_queryset(user):
    users = User.objects.select_related("farmer_profile__community", "community_staff_profile__community")
    if user.is_owner or user.is_superuser:
        return users
    if user.is_cooperative_staff:
        community = user_community(user)
        if community:
            return users.filter(role=User.Roles.FARMER, farmer_profile__community=community)
    return users.none()


def role_slug_for(user):
    if user.is_farmer:
        return "farmers"
    if user.is_cooperative_staff:
        return "staff"
    return "consumers"


def signup(request):
    return render(request, "accounts/signup_choice.html")


def admin_login(request):
    if request.user.is_authenticated and request.user.is_owner:
        return redirect("admin:index")
    return redirect(f"{reverse('admin:login')}?next={reverse('admin:index')}")


def public_login(request):
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if request.method == "POST":
        identifier = request.POST.get("username", "").strip()
        form = AuthenticationForm(request, data=request.POST)
        if is_login_blocked(request, identifier):
            form.add_error(None, "มีการเข้าสู่ระบบไม่สำเร็จหลายครั้ง กรุณารอแล้วลองใหม่")
        elif form.is_valid():
            user = form.get_user()
            clear_login_failures(request, identifier)
            if user.is_owner:
                messages.info(request, "บัญชีเจ้าของระบบ กรุณาเข้าสู่ระบบผ่านหน้า Admin")
                return redirect("admin_login")
            if settings.REQUIRE_EMAIL_VERIFICATION and not user.is_email_verified:
                messages.error(request, "กรุณายืนยันอีเมลก่อนเข้าสู่ระบบ")
                return redirect("login")
            login(request, user)
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect("catalog:product_list")
        elif identifier:
            record_login_failure(request, identifier)
    else:
        if request.user.is_authenticated:
            if request.user.is_owner:
                return redirect("admin:index")
            return redirect("catalog:product_list")
        form = AuthenticationForm()

    return render(request, "registration/login.html", {"form": form, "next": next_url})

def _send_signup_verification(request, user):
    try:
        send_verification_email(request, user)
    except Exception:
        logger.exception("Unable to send verification email for user %s", user.pk)
        messages.warning(request, "สร้างบัญชีแล้ว แต่ยังส่งอีเมลยืนยันไม่ได้ กรุณาลองส่งใหม่จากหน้าเข้าสู่ระบบ")


def consumer_signup(request):
    if request.method == "POST":
        form = ConsumerSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            _send_signup_verification(request, user)
            messages.success(request, "สมัครสมาชิกผู้บริโภคเรียบร้อย กรุณาเข้าสู่ระบบด้วยบัญชีของคุณ")
            return redirect("login")
    else:
        form = ConsumerSignupForm()

    return render(request, "accounts/signup_consumer.html", {"form": form})


def farmer_signup(request):
    if request.user.is_authenticated:
        if request.user.is_farmer:
            return redirect("accounts:farmer_shop_center")
        if not request.user.is_consumer:
            messages.error(request, "บัญชีนี้ไม่สามารถสมัครเป็นผู้ขายได้")
            return redirect("accounts:dashboard")
    return render(
        request,
        "accounts/signup_farmer_intro.html",
        {"upgrade_existing_account": request.user.is_authenticated},
    )


def farmer_signup_create(request):
    if request.user.is_authenticated:
        if request.user.is_farmer:
            return redirect("accounts:farmer_shop_center")
        if request.user.is_consumer:
            return redirect("accounts:farmer_signup_profile")
        messages.error(request, "บัญชีนี้ไม่สามารถสมัครเป็นผู้ขายได้")
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = FarmerSignupForm(request.POST)
        if form.is_valid():
            request.session["farmer_signup_account"] = {
                "username": form.cleaned_data["username"],
                "first_name": form.cleaned_data["first_name"],
                "last_name": form.cleaned_data["last_name"],
                "birth_date": form.cleaned_data["birth_date"].isoformat(),
                "email": form.cleaned_data["email"],
                "phone": form.cleaned_data["phone"],
                "password_hash": make_password(form.cleaned_data["password1"]),
            }
            request.session.modified = True
            return redirect("accounts:farmer_signup_profile")
    else:
        form = FarmerSignupForm()

    return render(request, "accounts/signup_farmer.html", {"form": form})


def farmer_signup_profile(request):
    upgrading_user = None
    if request.user.is_authenticated:
        if request.user.is_farmer:
            return redirect("accounts:farmer_shop_center")
        if not request.user.is_consumer:
            messages.error(request, "บัญชีนี้ไม่สามารถสมัครเป็นผู้ขายได้")
            return redirect("accounts:dashboard")
        upgrading_user = request.user

    account_data = request.session.get("farmer_signup_account") if not upgrading_user else None
    if not upgrading_user and not account_data:
        return redirect("accounts:farmer_signup_create")

    existing_profile = getattr(upgrading_user, "farmer_profile", None) if upgrading_user else None
    if request.method == "POST":
        profile_form = FarmerProfileForm(request.POST, request.FILES, instance=existing_profile)
        if profile_form.is_valid():
            if not upgrading_user and (
                User.objects.filter(username=account_data["username"]).exists()
                or User.objects.filter(email__iexact=account_data["email"]).exists()
            ):
                request.session.pop("farmer_signup_account", None)
                request.session.modified = True
                messages.error(request, "ชื่อผู้ใช้หรืออีเมลนี้ถูกใช้งานแล้ว กรุณาสมัครใหม่")
                return redirect("accounts:farmer_signup_create")

            with transaction.atomic():
                if upgrading_user:
                    user = upgrading_user
                    user.role = User.Roles.FARMER
                    user.save(update_fields=["role"])
                else:
                    accepted_at = timezone.now()
                    first_name = account_data.get("first_name", "")
                    last_name = account_data.get("last_name", "")
                    if not first_name and not last_name:
                        first_name, last_name = split_display_name(account_data.get("display_name", ""))
                    display_name = " ".join(part for part in [first_name, last_name] if part)
                    user = User(
                        username=account_data["username"],
                        display_name=display_name or account_data["username"],
                        first_name=first_name,
                        last_name=last_name,
                        birth_date=account_data.get("birth_date") or None,
                        email=account_data["email"],
                        phone=account_data["phone"],
                        password=account_data["password_hash"],
                        role=User.Roles.FARMER,
                        terms_accepted_at=accepted_at,
                        privacy_accepted_at=accepted_at,
                        terms_version=settings.TERMS_VERSION,
                        privacy_version=settings.PRIVACY_VERSION,
                    )
                    user.save()
                profile = profile_form.save(commit=False)
                profile.user = user
                profile.save()

            if upgrading_user:
                messages.success(request, "ส่งข้อมูลสมัครผู้ขายแล้ว บัญชีเดิมของคุณยังใช้ซื้อสินค้าได้ตามปกติ")
                return redirect("accounts:farmer_shop_center")

            request.session.pop("farmer_signup_account", None)
            request.session.modified = True
            _send_signup_verification(request, user)
            messages.success(request, "สมัครบัญชีเกษตรกรเรียบร้อย กรุณาเข้าสู่ระบบเพื่อรอการยืนยัน")
            return redirect("login")
    else:
        initial_name = upgrading_user.username if upgrading_user else account_data["username"]
        profile_form = FarmerProfileForm(instance=existing_profile, initial={"farm_name": initial_name})

    return render(
        request,
        "accounts/signup_farmer_profile.html",
        {"profile_form": profile_form, "upgrade_existing_account": bool(upgrading_user)},
    )

@login_required
def profile(request):
    return redirect("accounts:account_history")


@login_required
def account_history(request):
    user_form = UserProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    profile_form = None
    farmer_profile = getattr(request.user, "farmer_profile", None)

    if request.user.is_farmer:
        profile_form = FarmerProfileForm(request.POST or None, request.FILES or None, instance=farmer_profile)

    if request.method == "POST":
        forms_are_valid = user_form.is_valid() and (profile_form is None or profile_form.is_valid())
        if forms_are_valid:
            email_changed = "email" in user_form.changed_data
            user = user_form.save(commit=False)
            if email_changed:
                user.email_verified_at = None
            user.save()
            if email_changed:
                _send_signup_verification(request, user)
            if profile_form is not None:
                profile = profile_form.save(commit=False)
                profile.user = request.user
                if not farmer_profile or "community" in profile_form.changed_data:
                    profile.verification_status = FarmerProfile.VerificationStatus.PENDING
                    profile.verified_by = None
                    profile.verified_at = None
                profile.save()
            messages.success(request, "บันทึกข้อมูลส่วนตัวแล้ว")
            return redirect("accounts:account_history")

    return render(
        request,
        "accounts/account_history.html",
        {
            "user_form": user_form,
            "profile_form": profile_form,
            "farmer_profile": farmer_profile,
            "account_section": "history",
        },
    )

@role_required(User.Roles.FARMER)
def farmer_shop_center(request):
    products = (
        Product.objects.filter(seller=request.user)
        .select_related("category")
        .prefetch_related(
            Prefetch(
                "images",
                queryset=ProductImage.objects.only("id", "product_id", "image", "alt_text").order_by("sort_order", "id"),
                to_attr="gallery_images",
            )
        )
    )
    farmer_profile = getattr(request.user, "farmer_profile", None)
    store_form = SellerStoreProfileForm(
        request.POST or None,
        request.FILES or None,
        instance=farmer_profile,
    ) if farmer_profile else None
    store_details_form = SellerStoreDetailsForm(
        request.POST or None,
        instance=farmer_profile,
    ) if farmer_profile else None
    product_form = ProductForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and request.POST.get("shop_action") == "create_product":
        if not farmer_profile or not farmer_profile.community or not farmer_profile.is_verified:
            messages.warning(request, "บัญชีเกษตรกรต้องได้รับการยืนยันจากเจ้าหน้าที่ก่อนเพิ่มสินค้า")
        elif product_form.is_valid():
            product = product_form.save(commit=False)
            gallery_images = list(product_form.cleaned_data["image"])
            detail_images = product_form.cleaned_data["detail_images"]
            if not product.image and gallery_images:
                product.image = gallery_images.pop(0)
            product.seller = request.user
            product.community = farmer_profile.community
            product.status = Product.Status.PENDING
            product.save()
            for image in gallery_images:
                ProductImage.objects.create(product=product, image=image)
            for sort_order, image in enumerate(detail_images, start=1):
                ProductDetailImage.objects.create(product=product, image=image, sort_order=sort_order)
            messages.success(request, "ส่งสินค้าให้เจ้าหน้าที่ตรวจสอบแล้ว")
            return redirect(f"{reverse('accounts:farmer_shop_center')}?section=products")
    elif request.method == "POST" and request.POST.get("shop_action") == "update_store":
        if store_details_form and store_details_form.is_valid():
            store_profile = store_details_form.save(commit=False)
            if store_form and store_form.is_valid():
                previous_cover_name = store_profile.store_cover.name if store_profile.store_cover else ""
                remove_store_cover = request.POST.get("remove_store_cover") == "1"
                if remove_store_cover and not request.FILES.get("store_cover"):
                    store_profile.store_cover = ""
                store_profile.save()
                if remove_store_cover and previous_cover_name:
                    store_profile.store_cover.storage.delete(previous_cover_name)
                next_sort_order = (
                    store_profile.store_cover_slides.aggregate(last=Max("sort_order"))["last"] or 0
                )
                for image in store_form.cleaned_data["store_cover_slides"]:
                    next_sort_order += 1
                    StoreCoverSlide.objects.create(
                        profile=store_profile,
                        image=image,
                        sort_order=next_sort_order,
                    )
                messages.success(request, f"บันทึกข้อมูลหน้าร้านแล้ว ชื่อร้าน: {store_profile.farm_name}")
                return redirect(f"{reverse('accounts:farmer_shop_center')}?section=store&mode=settings")
            store_profile.save()
            media_errors = []
            for field_name in ("store_cover", "store_cover_slides"):
                media_errors.extend(store_form.errors.get(field_name, []))
            detail = f" สาเหตุ: {' '.join(media_errors)}" if media_errors else ""
            messages.warning(
                request,
                f"บันทึกชื่อและข้อมูลร้านแล้ว แต่รูปปกหรือรูปสไลด์ไม่ผ่านการตรวจสอบ{detail}",
            )
        elif store_form:
            messages.error(request, "บันทึกข้อมูลร้านค้าไม่สำเร็จ กรุณาตรวจสอบข้อมูลที่ทำเครื่องหมายไว้")
    sales = Order.objects.filter(seller=request.user).select_related("buyer").prefetch_related("items").order_by("-created_at")
    paid_sales = sales.filter(payment_status=Order.PaymentStatus.PAID)
    gross_sales = paid_sales.aggregate(total=Sum("total_amount"))["total"] or 0

    allowed_sections = {"overview", "orders", "products", "marketing", "service", "finance", "store"}
    shop_section = request.GET.get("section", "overview")
    if shop_section not in allowed_sections:
        shop_section = "overview"

    order_status = request.GET.get("status", "all")
    status_groups = {
        "pending_payment": [Order.Status.PENDING_PAYMENT],
        "preparing": [Order.Status.PAID, Order.Status.CONFIRMED, Order.Status.PREPARING],
        "shipping": [Order.Status.SHIPPED],
        "completed": [Order.Status.COMPLETED],
        "cancelled": [Order.Status.CANCELLED, Order.Status.REFUNDED],
    }
    filtered_sales = sales
    if order_status in status_groups:
        filtered_sales = filtered_sales.filter(status__in=status_groups[order_status])
    else:
        order_status = "all"

    order_menu = request.GET.get("order_menu", order_status)
    if order_menu not in {"all", "batch", "preparing", "cancelled"}:
        order_menu = order_status
    if order_status == "all":
        order_menu = "all"

    order_query = request.GET.get("q", "").strip()
    order_search_by = request.GET.get("search_by", "reference")
    if order_query:
        if order_search_by == "buyer":
            filtered_sales = filtered_sales.filter(
                Q(buyer__display_name__icontains=order_query) | Q(buyer__username__icontains=order_query)
            )
        else:
            filtered_sales = filtered_sales.filter(
                Q(reference__icontains=order_query) | Q(items__product_name__icontains=order_query)
            ).distinct()

    order_payment = request.GET.get("payment", "all")
    payment_groups = {
        "paid": Order.PaymentStatus.PAID,
        "unpaid": Order.PaymentStatus.UNPAID,
        "failed": Order.PaymentStatus.FAILED,
        "refunded": Order.PaymentStatus.REFUNDED,
    }
    if order_payment in payment_groups:
        filtered_sales = filtered_sales.filter(payment_status=payment_groups[order_payment])
    else:
        order_payment = "all"

    reviews = ProductReview.objects.filter(product__seller=request.user).select_related("product", "user")
    settlements = SellerSettlement.objects.filter(seller=request.user).select_related("payment__order")
    pending_settlement_statuses = [
        SellerSettlement.Status.PENDING,
        SellerSettlement.Status.READY,
        SellerSettlement.Status.PROCESSING,
        SellerSettlement.Status.HELD,
    ]
    settlement_totals = settlements.aggregate(
        pending=Sum(
            "net_amount",
            filter=Q(status__in=pending_settlement_statuses),
        ),
        transferred=Sum("net_amount", filter=Q(status=SellerSettlement.Status.TRANSFERRED)),
    )
    today = timezone.localdate()
    transferred_settlements = settlements.filter(status=SellerSettlement.Status.TRANSFERRED)
    transferred_this_week_total = transferred_settlements.filter(
        transferred_at__date__gte=today - timedelta(days=today.weekday())
    ).aggregate(total=Sum("net_amount"))["total"] or 0
    transferred_this_month_total = transferred_settlements.filter(
        transferred_at__date__gte=today.replace(day=1)
    ).aggregate(total=Sum("net_amount"))["total"] or 0

    income_status = request.GET.get("income_status", "transferred")
    if income_status == "transferred":
        income_settlements = transferred_settlements
        income_date_field = "transferred_at"
    else:
        income_status = "pending"
        income_settlements = settlements.filter(status__in=pending_settlement_statuses)
        income_date_field = "created_at"

    income_period = request.GET.get("income_period", "week")
    income_period_options = {
        "week": (today - timedelta(days=today.weekday()), today, "สัปดาห์นี้"),
        "month": (today.replace(day=1), today, "เดือนนี้"),
        "quarter": (today - timedelta(days=89), today, "3 เดือนล่าสุด"),
        "all": (None, None, "ทั้งหมด"),
    }
    income_start = None
    income_end = None
    if income_period == "custom":
        try:
            income_start = date.fromisoformat(request.GET.get("income_start", ""))
            income_end = date.fromisoformat(request.GET.get("income_end", ""))
        except ValueError:
            income_period = "week"
        else:
            if income_start > income_end:
                income_period = "week"
    if income_period == "custom":
        income_period_label = "เลือกวัน"
    else:
        if income_period not in income_period_options:
            income_period = "week"
        income_start, income_end, income_period_label = income_period_options[income_period]
    if income_start:
        income_settlements = income_settlements.filter(
            **{f"{income_date_field}__date__gte": income_start}
        )
    if income_end:
        income_settlements = income_settlements.filter(
            **{f"{income_date_field}__date__lte": income_end}
        )

    income_query = request.GET.get("income_q", "").strip()
    if income_query:
        income_settlements = income_settlements.filter(
            payment__order__reference__icontains=income_query
        )

    balance_activity_type = request.GET.get("balance_activity", "all")
    if balance_activity_type not in {"all", "incoming", "transferred"}:
        balance_activity_type = "all"
    balance_transactions = settlements
    if balance_activity_type == "incoming":
        balance_transactions = balance_transactions.filter(status__in=pending_settlement_statuses)
    elif balance_activity_type == "transferred":
        balance_transactions = balance_transactions.filter(
            status=SellerSettlement.Status.TRANSFERRED
        )

    balance_period = request.GET.get("balance_period", "week")
    balance_period_options = {
        "week": (
            today - timedelta(days=today.weekday()),
            today,
            "สัปดาห์นี้",
        ),
        "month": (today.replace(day=1), today, "เดือนนี้"),
        "quarter": (today - timedelta(days=89), today, "3 เดือนล่าสุด"),
        "all": (None, None, "ทั้งหมด"),
    }
    balance_start = None
    balance_end = None
    if balance_period == "custom":
        try:
            balance_start = date.fromisoformat(request.GET.get("balance_start", ""))
            balance_end = date.fromisoformat(request.GET.get("balance_end", ""))
        except ValueError:
            balance_period = "week"
        else:
            if balance_start > balance_end:
                balance_period = "week"
    if balance_period == "custom":
        balance_period_label = "เลือกวัน"
    else:
        if balance_period not in balance_period_options:
            balance_period = "week"
        balance_start, balance_end, balance_period_label = balance_period_options[balance_period]
    if balance_start:
        balance_transactions = balance_transactions.filter(created_at__date__gte=balance_start)
    if balance_end:
        balance_transactions = balance_transactions.filter(created_at__date__lte=balance_end)
    balance_transaction_total = balance_transactions.aggregate(total=Sum("net_amount"))["total"] or 0

    review_summary = reviews.aggregate(average=Avg("rating"), total=Count("id"))
    refund_or_cancel_total = (
        sales.filter(status__in=[Order.Status.CANCELLED, Order.Status.REFUNDED]).count()
        + Refund.objects.filter(
            payment__order__seller=request.user,
            status__in=[Refund.Status.REQUESTED, Refund.Status.PROCESSING],
        ).count()
    )
    policy_issue_total = products.filter(
        status__in=[Product.Status.REJECTED, Product.Status.BLOCKED]
    ).count()
    today_sales = paid_sales.filter(created_at__date=today)
    yesterday = today - timedelta(days=1)
    yesterday_sales = paid_sales.filter(created_at__date=yesterday)
    today_sales_total = today_sales.aggregate(total=Sum("total_amount"))["total"] or 0
    yesterday_sales_total = yesterday_sales.aggregate(total=Sum("total_amount"))["total"] or 0
    today_product_sales_total = today_sales.aggregate(
        total=Sum(F("total_amount") - F("shipping_fee"))
    )["total"] or 0
    today_order_total = today_sales.count()
    yesterday_order_total = yesterday_sales.count()
    today_total_orders = sales.filter(created_at__date=today).count()
    today_payment_success_rate = (
        today_order_total * 100 / today_total_orders if today_total_orders else 0
    )
    today_store_visitor_total = SellerStoreVisit.objects.filter(
        seller=request.user,
        visited_on=today,
    ).count()
    today_product_click_total = ProductClick.objects.filter(
        seller=request.user,
        created_at__date=today,
    ).count()

    def percent_change(current_value, previous_value):
        if not previous_value:
            return 0
        return (current_value - previous_value) * 100 / previous_value

    trend_start = today - timedelta(days=6)
    trend_totals = {
        row["created_at__date"]: row["total"]
        for row in paid_sales.filter(created_at__date__gte=trend_start)
        .values("created_at__date")
        .annotate(total=Sum("total_amount"))
    }
    daily_sales_trend = [
        {
            "label": (trend_start + timedelta(days=offset)).strftime("%d/%m"),
            "total": trend_totals.get(trend_start + timedelta(days=offset), 0),
        }
        for offset in range(7)
    ]
    trend_maximum = max((point["total"] for point in daily_sales_trend), default=0)
    for index, point in enumerate(daily_sales_trend):
        point["height"] = (
            max(8, round(point["total"] * 100 / trend_maximum))
            if trend_maximum
            else 0
        )
        point["chart_x"] = round(40 + index * (620 / 6), 2)
        point["chart_y"] = round(156 - point["height"] * 1.36, 2)
    weekly_sales_total = sum(point["total"] for point in daily_sales_trend)
    daily_sales_chart_points = " ".join(
        f'{point["chart_x"]},{point["chart_y"]}' for point in daily_sales_trend
    )

    context = {
        "farmer_profile": farmer_profile,
        "product_form": product_form,
        "store_form": store_form,
        "can_create_products": bool(farmer_profile and farmer_profile.community and farmer_profile.is_verified),
        "shop_products": products.order_by("-updated_at"),
        "shop_section": shop_section,
        "products": products.order_by("-updated_at")[:6],
        "recent_sales": sales[:6],
        "shop_orders": filtered_sales,
        "shop_order_count": filtered_sales.count(),
        "order_status": order_status,
        "order_menu": order_menu,
        "order_query": order_query,
        "order_search_by": order_search_by,
        "order_payment": order_payment,
        "product_total": products.count(),
        "active_product_total": products.filter(status=Product.Status.ACTIVE).count(),
        "pending_product_total": products.filter(status=Product.Status.PENDING).count(),
        "low_stock_total": products.filter(stock_quantity__lte=F("low_stock_threshold")).count(),
        "pending_payment_total": sales.filter(status=Order.Status.PENDING_PAYMENT).count(),
        "preparing_total": sales.filter(
            status__in=[Order.Status.PAID, Order.Status.CONFIRMED, Order.Status.PREPARING]
        ).count(),
        "shipped_total": sales.filter(status=Order.Status.SHIPPED).count(),
        "gross_sales": gross_sales,
        "refund_or_cancel_total": refund_or_cancel_total,
        "policy_issue_total": policy_issue_total,
        "today_sales_total": today_sales_total,
        "today_store_visitor_total": today_store_visitor_total,
        "today_product_click_total": today_product_click_total,
        "today_product_sales_total": today_product_sales_total,
        "today_order_total": today_order_total,
        "today_payment_success_rate": today_payment_success_rate,
        "today_sales_change": percent_change(today_sales_total, yesterday_sales_total),
        "today_order_change": percent_change(today_order_total, yesterday_order_total),
        "daily_sales_trend": daily_sales_trend,
        "daily_sales_trend_has_data": bool(trend_maximum),
        "daily_sales_chart_points": daily_sales_chart_points,
        "weekly_sales_total": weekly_sales_total,
        "support_open_count": SupportTicket.objects.filter(seller=request.user, status__in=[SupportTicket.Status.OPEN, SupportTicket.Status.IN_PROGRESS]).count(),
        "shop_reviews": reviews,
        "review_average": review_summary["average"] or 0,
        "review_total": review_summary["total"] or 0,
        "settlements": settlements,
        "income_settlements": income_settlements,
        "income_status": income_status,
        "income_period": income_period,
        "income_period_label": income_period_label,
        "income_start": income_start,
        "income_end": income_end,
        "income_query": income_query,
        "pending_settlement_total": settlement_totals["pending"] or 0,
        "transferred_settlement_total": settlement_totals["transferred"] or 0,
        "transferred_this_week_total": transferred_this_week_total,
        "transferred_this_month_total": transferred_this_month_total,
        "balance_activity_type": balance_activity_type,
        "balance_period": balance_period,
        "balance_period_label": balance_period_label,
        "balance_start": balance_start,
        "balance_end": balance_end,
        "balance_transactions": balance_transactions,
        "balance_transaction_total": balance_transaction_total,
        "seller_payment_account": SellerPaymentAccount.objects.filter(seller=request.user).first(),
    }
    return render(request, "accounts/farmer_shop_center.html", context)


@role_required(User.Roles.FARMER)
def income_statement(request):
    today = timezone.localdate()
    pending_statuses = [
        SellerSettlement.Status.PENDING,
        SellerSettlement.Status.READY,
        SellerSettlement.Status.PROCESSING,
        SellerSettlement.Status.HELD,
    ]
    income_status = request.GET.get("income_status", "transferred")
    settlements = SellerSettlement.objects.filter(seller=request.user).select_related(
        "payment__order"
    )
    if income_status == "transferred":
        income_settlements = settlements.filter(status=SellerSettlement.Status.TRANSFERRED)
        income_date_field = "transferred_at"
        status_label = "โอนเงินแล้ว"
    else:
        income_status = "pending"
        income_settlements = settlements.filter(status__in=pending_statuses)
        income_date_field = "created_at"
        status_label = "รอดำเนินการ"

    income_period = request.GET.get("income_period", "week")
    periods = {
        "week": (today - timedelta(days=today.weekday()), today, "สัปดาห์นี้"),
        "month": (today.replace(day=1), today, "เดือนนี้"),
        "quarter": (today - timedelta(days=89), today, "3 เดือนล่าสุด"),
        "all": (None, None, "ทั้งหมด"),
    }
    period_start = None
    period_end = None
    if income_period == "custom":
        try:
            period_start = date.fromisoformat(request.GET.get("income_start", ""))
            period_end = date.fromisoformat(request.GET.get("income_end", ""))
        except ValueError:
            income_period = "week"
        else:
            if period_start > period_end:
                income_period = "week"
    if income_period == "custom":
        period_label = "เลือกวัน"
    else:
        if income_period not in periods:
            income_period = "week"
        period_start, period_end, period_label = periods[income_period]
    if period_start:
        income_settlements = income_settlements.filter(
            **{f"{income_date_field}__date__gte": period_start}
        )
    if period_end:
        income_settlements = income_settlements.filter(
            **{f"{income_date_field}__date__lte": period_end}
        )

    income_query = request.GET.get("income_q", "").strip()
    if income_query:
        income_settlements = income_settlements.filter(
            payment__order__reference__icontains=income_query
        )
    statement_total = income_settlements.aggregate(total=Sum("net_amount"))["total"] or 0

    return render(
        request,
        "accounts/income_statement.html",
        {
            "farmer_profile": getattr(request.user, "farmer_profile", None),
            "income_settlements": income_settlements,
            "income_status": income_status,
            "income_query": income_query,
            "period_label": period_label,
            "period_start": period_start,
            "statement_total": statement_total,
            "statement_date": today,
            "status_label": status_label,
        },
    )

@login_required
@role_required(User.Roles.FARMER)
def support_chat(request):
    ticket = (
        SupportTicket.objects.filter(
            seller=request.user,
            status__in=[SupportTicket.Status.OPEN, SupportTicket.Status.IN_PROGRESS],
        )
        .order_by("-updated_at")
        .first()
    )
    if ticket is None:
        community = getattr(getattr(request.user, "farmer_profile", None), "community", None)
        ticket = SupportTicket.objects.create(
            seller=request.user,
            community=community,
            category=SupportTicket.Category.GENERAL,
            subject="แชทกับผู้ดูแลระบบ",
        )
        record_audit(
            request,
            AuditEvent.Action.CREATE,
            ticket,
            description="ผู้ขายเริ่มแชทกับผู้ดูแล",
            community=community,
        )
    return redirect("accounts:support_ticket_detail", pk=ticket.pk)


@login_required
@role_required(User.Roles.FARMER)
def support_ticket_list(request):
    tickets = SupportTicket.objects.filter(seller=request.user).prefetch_related("messages").select_related("handled_by")
    return render(request, "accounts/support_ticket_list.html", {"tickets": tickets})


@login_required
@role_required(User.Roles.FARMER)
def support_ticket_create(request):
    form = SupportTicketCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        community = getattr(getattr(request.user, "farmer_profile", None), "community", None)
        ticket = SupportTicket.objects.create(
            seller=request.user,
            community=community,
            category=form.cleaned_data["category"],
            subject=form.cleaned_data["subject"],
        )
        message = SupportMessage(ticket=ticket, sender=request.user, body=form.cleaned_data["message"])
        message.full_clean()
        message.save()
        ticket.last_seller_message_at = message.created_at
        ticket.admin_read_at = None
        ticket.save(update_fields=["last_seller_message_at", "admin_read_at", "updated_at"])
        record_audit(
            request,
            AuditEvent.Action.CREATE,
            ticket,
            description="ผู้ขายเปิดคำขอถึงผู้ดูแล",
            community=community,
        )
        owners = User.objects.filter(Q(role=User.Roles.OWNER) | Q(is_superuser=True), is_active=True)
        for owner in owners:
            notify_user(
                owner,
                title=f"คำขอใหม่จากผู้ขาย: {ticket.get_category_display()}",
                message=f"{request.user} · {ticket.subject}",
                link=reverse("admin:accounts_supportticket_reply", args=[ticket.pk]),
                send_email_message=False,
            )
        messages.success(request, "ส่งคำขอถึงผู้ดูแลแล้ว")
        return redirect("accounts:support_ticket_detail", pk=ticket.pk)
    return render(request, "accounts/support_ticket_form.html", {"form": form})


@login_required
def support_chat_unread(request):
    if not request.user.is_owner:
        raise PermissionDenied
    unread_tickets = SupportTicket.objects.exclude(status=SupportTicket.Status.CLOSED).filter(
        Q(admin_read_at__isnull=True, last_seller_message_at__isnull=False)
        | Q(last_seller_message_at__gt=F("admin_read_at"))
    )
    return JsonResponse({"count": unread_tickets.count()})




def _support_ticket_for_user(request, pk):
    tickets = SupportTicket.objects.select_related("seller", "community", "handled_by").prefetch_related("messages__sender")
    if request.user.is_owner:
        return get_object_or_404(tickets, pk=pk)
    return get_object_or_404(tickets, pk=pk, seller=request.user)


@login_required
def support_ticket_detail(request, pk):
    ticket = _support_ticket_for_user(request, pk)
    can_manage = request.user.is_owner
    if can_manage and settings.ADMIN_MFA_REQUIRED:
        return redirect(f"{reverse('admin:accounts_supportticket_changelist')}?ticket={ticket.pk}")
    if can_manage and ticket.has_unread_for_admin:
        ticket.admin_read_at = timezone.now()
        ticket.save(update_fields=["admin_read_at"])
    elif not can_manage and ticket.has_unread_for_seller:
        ticket.seller_read_at = timezone.now()
        ticket.save(update_fields=["seller_read_at"])
    form = SupportMessageForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        recent_messages = SupportMessage.objects.filter(
            ticket=ticket,
            sender=request.user,
            created_at__gte=timezone.now() - timedelta(minutes=1),
        ).count()
        if recent_messages >= 12:
            form.add_error(None, "คุณส่งข้อความเร็วเกินไป กรุณารอประมาณ 1 นาทีแล้วลองใหม่")
        else:
            message = form.save(commit=False)
            message.ticket = ticket
            message.sender = request.user
            message.full_clean()
            message.save()
            if can_manage:
                ticket.status = SupportTicket.Status.IN_PROGRESS
                ticket.handled_by = request.user
                ticket.last_admin_message_at = message.created_at
                ticket.seller_read_at = None
                recipients = [ticket.seller]
                title = "ผู้ดูแลตอบกลับแชทของคุณ"
                note = ticket.subject
                notification_link = reverse("accounts:support_ticket_detail", args=[ticket.pk])
            else:
                ticket.status = SupportTicket.Status.OPEN
                ticket.last_seller_message_at = message.created_at
                ticket.admin_read_at = None
                recipient = ticket.handled_by
                recipients = [recipient] if recipient else list(User.objects.filter(Q(role=User.Roles.OWNER) | Q(is_superuser=True), is_active=True))
                title = "ข้อความใหม่จากผู้ขาย"
                note = f"{ticket.seller} · {ticket.subject}"
                notification_link = reverse("admin:accounts_supportticket_reply", args=[ticket.pk])
            ticket.save(update_fields=[
                "status",
                "handled_by",
                "last_seller_message_at",
                "last_admin_message_at",
                "admin_read_at",
                "seller_read_at",
                "updated_at",
            ])
            for recipient in recipients:
                if not recipient:
                    continue
                notify_user(
                    recipient,
                    title=title,
                    message=note,
                    link=notification_link,
                    send_email_message=False,
                )
            messages.success(request, "ส่งข้อความแล้ว")
            return redirect("accounts:support_ticket_detail", pk=ticket.pk)
    return render(
        request,
        "accounts/support_ticket_detail.html",
        {"ticket": ticket, "form": form, "can_manage": can_manage},
    )


@role_required(User.Roles.FARMER)
@require_POST
def store_cover_slide_delete(request, slide_id):
    slide = get_object_or_404(
        StoreCoverSlide.objects.select_related("profile"),
        pk=slide_id,
        profile__user=request.user,
    )
    image_name = slide.image.name
    storage = slide.image.storage
    slide.delete()
    if image_name:
        storage.delete(image_name)
    messages.success(request, "ลบรูปสไลด์หน้าร้านแล้ว")
    return redirect(f"{reverse('accounts:farmer_shop_center')}?section=store&mode=settings")

@login_required
def addresses_list(request):
    return render(
        request,
        "accounts/addresses.html",
        {"account_section": "addresses", "addresses": request.user.delivery_addresses.all()},
    )


def _save_delivery_address(request, address, form):
    with transaction.atomic():
        if form.cleaned_data.get("is_default") or not request.user.delivery_addresses.exclude(pk=address.pk).exists():
            request.user.delivery_addresses.exclude(pk=address.pk).update(is_default=False)
            address.is_default = True
        address.user = request.user
        address.save()
    return address


@login_required
def address_create(request):
    address = DeliveryAddress(user=request.user)
    form = DeliveryAddressForm(request.POST or None, instance=address)
    if request.method == "POST" and form.is_valid():
        _save_delivery_address(request, address, form)
        messages.success(request, "เพิ่มที่อยู่ใหม่แล้ว")
        return redirect("accounts:addresses")
    return render(request, "accounts/address_form.html", {"account_section": "addresses", "form": form, "address": address})


@login_required
def address_edit(request, pk):
    address = get_object_or_404(DeliveryAddress, pk=pk, user=request.user)
    form = DeliveryAddressForm(request.POST or None, instance=address)
    if request.method == "POST" and form.is_valid():
        _save_delivery_address(request, address, form)
        messages.success(request, "บันทึกที่อยู่แล้ว")
        return redirect("accounts:addresses")
    return render(request, "accounts/address_form.html", {"account_section": "addresses", "form": form, "address": address})


@login_required
@require_POST
def address_set_default(request, pk):
    address = get_object_or_404(DeliveryAddress, pk=pk, user=request.user)
    with transaction.atomic():
        request.user.delivery_addresses.update(is_default=False)
        address.is_default = True
        address.save(update_fields=["is_default", "updated_at"])
    messages.success(request, "ตั้งเป็นที่อยู่เริ่มต้นแล้ว")
    return redirect("accounts:addresses")


@login_required
@require_POST
def address_delete(request, pk):
    address = get_object_or_404(DeliveryAddress, pk=pk, user=request.user)
    was_default = address.is_default
    address.delete()
    if was_default:
        replacement = request.user.delivery_addresses.first()
        if replacement:
            replacement.is_default = True
            replacement.save(update_fields=["is_default", "updated_at"])
    messages.success(request, "ลบที่อยู่แล้ว")
    return redirect("accounts:addresses")


@login_required
def payment_settings(request):
    customer_profile = CustomerPaymentProfile.objects.filter(user=request.user).prefetch_related("payment_methods").first()
    saved_methods = customer_profile.payment_methods.all() if customer_profile else SavedPaymentMethod.objects.none()
    return render(
        request,
        "accounts/payment_settings.html",
        {
            "account_section": "payments",
            "customer_payment_profile": customer_profile,
            "saved_methods": saved_methods,
            "seller_payment_account": SellerPaymentAccount.objects.filter(seller=request.user).first(),
        },
    )

@login_required
def notifications_list(request):
    notifications = request.user.notifications.all()
    return render(request, "accounts/notifications.html", {"notifications": notifications, "account_section": "notifications"})


@login_required
def mark_notification_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    notification.is_read = True
    notification.save(update_fields=["is_read"])
    if notification.link:
        return redirect(notification.link)
    return redirect("accounts:notifications")


@role_required(User.Roles.COOPERATIVE_STAFF)
def staff_dashboard(request):
    if request.user.is_owner:
        return redirect("accounts:dashboard")

    community = user_community(request.user)
    if community:
        farmers = FarmerProfile.objects.select_related("user", "community").filter(
            community=community
        )
        products = Product.objects.select_related("seller", "community", "category").filter(
            community=community
        )
        orders = Order.objects.select_related("buyer", "seller", "community").filter(
            community=community
        )
        reports = scoped_reports(request.user)
    else:
        farmers = FarmerProfile.objects.none()
        products = Product.objects.none()
        orders = Order.objects.none()
        reports = Report.objects.none()

    active_reports = reports.filter(
        status__in=[Report.Status.OPEN, Report.Status.REVIEWING]
    )
    context = {
        "community": community,
        "farmer_count": farmers.count(),
        "product_count": products.count(),
        "order_count": orders.count(),
        "open_report_count": active_reports.count(),
        "pending_farmers": farmers.filter(
            verification_status=FarmerProfile.VerificationStatus.PENDING
        )[:6],
        "pending_products": products.filter(status=Product.Status.PENDING)[:6],
        "recent_orders": orders[:6],
        "active_reports": active_reports[:6],
        "order_status_counts": orders.values("status").annotate(count=Count("id")),
    }
    return render(request, "accounts/staff_dashboard.html", context)


@login_required
def dashboard(request):
    user = request.user
    if user.is_cooperative_staff:
        return redirect("accounts:staff_dashboard")

    reviews = ProductReview.objects.filter(product__seller=request.user).select_related("product", "user")
    settlements = SellerSettlement.objects.filter(seller=request.user).select_related("payment__order")
    settlement_totals = settlements.aggregate(
        pending=Sum(
            "net_amount",
            filter=Q(
                status__in=[
                    SellerSettlement.Status.PENDING,
                    SellerSettlement.Status.READY,
                    SellerSettlement.Status.PROCESSING,
                    SellerSettlement.Status.HELD,
                ]
            ),
        ),
        transferred=Sum("net_amount", filter=Q(status=SellerSettlement.Status.TRANSFERRED)),
    )
    review_summary = reviews.aggregate(average=Avg("rating"), total=Count("id"))

    context = {
        "community": user_community(user),
        "open_report_count": scoped_reports(user).filter(
            status=Report.Status.OPEN
        ).count(),
    }

    if user.is_owner:
        context.update(
            {
                "user_count": User.objects.count(),
                "consumer_count": User.objects.filter(role=User.Roles.CONSUMER).count(),
                "farmer_count": User.objects.filter(role=User.Roles.FARMER).count(),
                "staff_count": User.objects.filter(role=User.Roles.COOPERATIVE_STAFF).count(),
                "product_count": Product.objects.count(),
                "order_count": Order.objects.count(),
                "sales_total": Order.objects.aggregate(total=Sum("total_amount"))["total"] or 0,
                "pending_products": Product.objects.filter(status=Product.Status.PENDING)[:8],
                "pending_farmers": FarmerProfile.objects.filter(
                    verification_status=FarmerProfile.VerificationStatus.PENDING
                )[:8],
            }
        )
    elif user.is_farmer:
        products = Product.objects.filter(seller=user)
        sales = Order.objects.filter(seller=user)
        context.update(
            {
                "farmer_profile": getattr(user, "farmer_profile", None),
                "products": products[:8],
                "product_count": products.count(),
                "sales_count": sales.count(),
                "sales_total": sales.aggregate(total=Sum("total_amount"))["total"] or 0,
                "recent_sales": sales[:8],
                "payment_account": SellerPaymentAccount.objects.filter(seller=user).first(),
                "pending_settlement_total": SellerSettlement.objects.filter(
                    seller=user,
                    status__in=[
                        SellerSettlement.Status.PENDING,
                        SellerSettlement.Status.READY,
                        SellerSettlement.Status.PROCESSING,
                    ],
                ).aggregate(total=Sum("net_amount"))["total"] or 0,
            }
        )
    else:
        context.update({"recent_orders": Order.objects.filter(buyer=user)[:8]})

    return render(request, "accounts/dashboard.html", context)


@login_required
@require_POST
def switch_market_mode(request, mode):
    if not request.user.is_farmer:
        raise PermissionDenied

    if mode == "buyer":
        request.session["active_market_mode"] = "buyer"
        messages.success(request, "สลับเป็นโหมดผู้ซื้อแล้ว")
        return redirect("catalog:product_list")

    if mode == "seller":
        request.session["active_market_mode"] = "seller"
        messages.success(request, "สลับเป็นโหมดผู้ขายแล้ว")
        return redirect("accounts:farmer_shop_center")

    raise Http404


@role_required(User.Roles.COOPERATIVE_STAFF)
def farmer_verification(request, profile_id, action):
    profile = get_object_or_404(FarmerProfile, pk=profile_id)
    community = user_community(request.user)
    if not request.user.is_owner and not community:
        messages.error(request, "บัญชีเจ้าหน้าที่ยังไม่ได้ผูกกับชุมชน")
        return redirect("accounts:staff_dashboard")
    if not request.user.is_owner and community and profile.community_id != community.id:
        messages.error(request, "ตรวจสอบได้เฉพาะเกษตรกรในชุมชนของคุณ")
        return redirect("accounts:staff_dashboard")

    if (
        request.user.is_cooperative_staff
        and profile.verification_status != FarmerProfile.VerificationStatus.PENDING
    ):
        messages.error(request, "ตรวจสอบได้เฉพาะบัญชีที่รอการตรวจสอบ")
        return redirect("accounts:staff_dashboard")

    if request.method == "POST":
        before_status = profile.verification_status
        if action == "approve":
            profile.mark_verified(request.user)
            Notification.objects.create(
                user=profile.user,
                title="บัญชีเกษตรกรได้รับการยืนยัน",
                message=f"บัญชีเกษตรกรของคุณ {profile.farm_name} ได้รับการยืนยันแล้ว",
                link="/accounts/dashboard/",
            )
            messages.success(request, f"ยืนยัน {profile.farm_name} แล้ว")
        elif action == "reject":
            rejection_reason = request.POST.get("rejection_reason", "").strip()
            if not rejection_reason:
                messages.error(request, "กรุณาระบุเหตุผลที่ไม่อนุมัติ")
                return redirect("accounts:staff_dashboard")
            profile.verification_status = FarmerProfile.VerificationStatus.REJECTED
            profile.verified_by = request.user
            profile.verified_at = timezone.now()
            profile.rejection_reason = rejection_reason
            profile.save(update_fields=["verification_status", "verified_by", "verified_at", "rejection_reason"])
            Notification.objects.create(
                user=profile.user,
                title="บัญชีเกษตรกรไม่ผ่านการตรวจสอบ",
                message=f"บัญชีเกษตรกรของคุณ {profile.farm_name} ไม่ผ่านการตรวจสอบ: {rejection_reason}",
                link="/accounts/dashboard/",
            )
            messages.warning(request, f"ปฏิเสธ {profile.farm_name} แล้ว")
        if action in {"approve", "reject"}:
            record_audit(
                request,
                AuditEvent.Action.APPROVE if action == "approve" else AuditEvent.Action.REJECT,
                profile,
                description="ตรวจสอบบัญชีเกษตรกร",
                before={"verification_status": before_status},
                after={
                    "verification_status": profile.verification_status,
                    "rejection_reason": profile.rejection_reason,
                },
                community=profile.community,
            )
    return redirect("accounts:staff_dashboard")


def verify_email(request, uidb64, token):
    try:
        user_id = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=user_id)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
    if user and default_token_generator.check_token(user, token):
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])
        messages.success(request, "ยืนยันอีเมลเรียบร้อยแล้ว สามารถเข้าสู่ระบบได้")
    else:
        messages.error(request, "ลิงก์ยืนยันอีเมลไม่ถูกต้องหรือหมดอายุ")
    return redirect("login")


def resend_verification(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        user = User.objects.filter(email__iexact=email).first()
        if user and not user.is_email_verified:
            try:
                send_verification_email(request, user)
            except Exception:
                logger.exception("Unable to resend verification email for user %s", user.pk)
        messages.success(request, "หากพบอีเมลนี้ในระบบ เราได้ส่งลิงก์ยืนยันให้แล้ว")
        return redirect("login")
    return render(request, "accounts/resend_verification.html")


@login_required
def report_detail(request, pk):
    report = get_object_or_404(scoped_reports(request.user).prefetch_related("messages__sender"), pk=pk)
    form = ReportMessageForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        message = form.save(commit=False)
        message.report = report
        message.sender = request.user
        message.save()
        if report.status == Report.Status.OPEN:
            report.status = Report.Status.REVIEWING
            report.save(update_fields=["status", "updated_at"])
        messages.success(request, "ส่งข้อความในรายงานแล้ว")
        return redirect("accounts:report_detail", pk=report.pk)
    return render(request, "accounts/report_detail.html", {"report": report, "form": form})


@login_required
def favorites_list(request):
    product_favorites = ProductFavorite.objects.filter(user=request.user).select_related(
        "product", "product__seller", "product__community", "product__category"
    )
    seller_favorites = SellerFavorite.objects.filter(user=request.user).select_related("seller")
    return render(
        request,
        "accounts/favorites.html",
        {"product_favorites": product_favorites, "seller_favorites": seller_favorites},
    )


def news_list(request):
    news_posts = visible_news_queryset(request.user)
    return render(request, "accounts/news_list.html", {"news_posts": news_posts})


def news_detail(request, slug):
    post = get_object_or_404(NewsPost, slug=slug)
    if not post.is_visible_to(request.user):
        messages.error(request, "คุณไม่มีสิทธิ์ดูข่าวนี้")
        return redirect("accounts:news_list")
    return render(request, "accounts/news_detail.html", {"post": post})


@role_required(User.Roles.OWNER)
def news_manage(request):
    news_posts = NewsPost.objects.select_related("created_by")
    return render(request, "accounts/news_manage.html", {"news_posts": news_posts})


@role_required(User.Roles.OWNER)
def news_create(request):
    form = NewsPostForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        post = form.save(commit=False)
        post.created_by = request.user
        post.save()
        notify_news_post(post)
        messages.success(request, "เพิ่มข่าวสารแล้ว")
        return redirect("accounts:news_manage")
    return render(request, "accounts/news_form.html", {"form": form, "title": "เพิ่มข่าวสาร"})


@role_required(User.Roles.OWNER)
def news_update(request, pk):
    post = get_object_or_404(NewsPost, pk=pk)
    form = NewsPostForm(request.POST or None, instance=post)
    if request.method == "POST" and form.is_valid():
        post = form.save()
        notify_news_post(post)
        messages.success(request, "บันทึกข่าวสารแล้ว")
        return redirect("accounts:news_manage")
    return render(request, "accounts/news_form.html", {"form": form, "title": "แก้ไขข่าวสาร"})


@role_required(User.Roles.OWNER)
def news_delete(request, pk):
    post = get_object_or_404(NewsPost, pk=pk)
    if request.method == "POST":
        post.delete()
        messages.success(request, "ลบข่าวสารแล้ว")
        return redirect("accounts:news_manage")
    return render(request, "accounts/news_confirm_delete.html", {"post": post})


@login_required
def reports_list(request):
    reports = scoped_reports(request.user)
    return render(request, "accounts/reports.html", {"reports": reports})


@login_required
def resolve_report(request, pk):
    report = get_object_or_404(Report, pk=pk)
    if not request.user.is_owner:
        community = user_community(request.user)
        if not request.user.is_cooperative_staff or not community or report.community_id != community.id:
            messages.error(request, "คุณไม่มีสิทธิ์จัดการรายงานนี้")
            return redirect("accounts:reports")

    form = ReportResolutionForm(request.POST or None, instance=report)
    if request.method == "POST" and form.is_valid():
        report = form.save(commit=False)
        report.handled_by = request.user
        report.handled_at = timezone.now()
        report.save(update_fields=["status", "resolution_note", "handled_by", "handled_at", "updated_at"])
        messages.success(request, "อัปเดตรายงานแล้ว")
        return redirect("accounts:reports")

    return render(request, "accounts/report_resolution.html", {"form": form, "report": report})


@login_required
def members_list(request, role):
    if role not in MEMBER_ROLE_OPTIONS:
        messages.error(request, "ไม่พบหน้าสมาชิกที่ต้องการ")
        return redirect("accounts:dashboard")
    if not request.user.is_owner and not request.user.is_cooperative_staff:
        messages.error(request, "บัญชีนี้ไม่มีสิทธิ์จัดการสมาชิก")
        return redirect("accounts:dashboard")
    if request.user.is_cooperative_staff and role != "farmers":
        messages.error(request, "เจ้าหน้าที่จัดการได้เฉพาะเกษตรกรในชุมชน")
        return redirect("accounts:members", role="farmers")

    role_value, title = MEMBER_ROLE_OPTIONS[role]
    members = managed_users_queryset(request.user).filter(role=role_value)
    q = request.GET.get("q", "").strip()
    if q:
        members = members.filter(
            Q(username__icontains=q)
            | Q(display_name__icontains=q)
            | Q(email__icontains=q)
            | Q(phone__icontains=q)
        )

    return render(request, "accounts/members.html", {"members": members, "role": role, "title": title, "q": q})


@role_required(User.Roles.COOPERATIVE_STAFF)
def staff_seller_detail(request, user_id):
    seller = get_object_or_404(
        managed_users_queryset(request.user),
        pk=user_id,
        role=User.Roles.FARMER,
    )
    profile = get_object_or_404(
        FarmerProfile.objects.select_related("community"),
        user=seller,
    )
    products = Product.objects.select_related("category").filter(
        seller=seller,
        community=profile.community,
    )
    orders = Order.objects.select_related("buyer", "community").filter(
        seller=seller,
        community=profile.community,
    )

    context = {
        "seller": seller,
        "profile": profile,
        "products": products,
        "orders": orders[:10],
        "product_count": products.count(),
        "order_count": orders.count(),
        "sales_total": orders.aggregate(total=Sum("total_amount"))["total"] or 0,
    }
    return render(request, "accounts/staff_seller_detail.html", context)


@role_required(User.Roles.COOPERATIVE_STAFF)
def staff_seller_edit(request, user_id):
    seller = get_object_or_404(
        managed_users_queryset(request.user),
        pk=user_id,
        role=User.Roles.FARMER,
    )
    profile = get_object_or_404(FarmerProfile, user=seller)
    seller_before = {
        "display_name": seller.display_name,
        "email": seller.email,
        "phone": seller.phone,
        "is_active": seller.is_active,
        "farm_name": profile.farm_name,
        "verification_status": profile.verification_status,
    }
    account_form = StaffSellerAccountForm(
        request.POST or None,
        request.FILES or None,
        instance=seller,
        prefix="account",
    )
    profile_form = StaffFarmerProfileForm(
        request.POST or None,
        instance=profile,
        prefix="farm",
    )

    if request.method == "POST" and account_form.is_valid() and profile_form.is_valid():
        with transaction.atomic():
            email_changed = "email" in account_form.changed_data
            seller = account_form.save(commit=False)
            if email_changed:
                seller.email_verified_at = None
            seller.save()

            profile = profile_form.save(commit=False)
            if "verification_document" in profile_form.changed_data:
                profile.verification_status = FarmerProfile.VerificationStatus.PENDING
                profile.verified_by = None
                profile.verified_at = None
                profile.rejection_reason = ""
            profile.save()
            record_audit(
                request,
                AuditEvent.Action.UPDATE,
                profile,
                description="เจ้าหน้าที่แก้ไขข้อมูลผู้ขาย",
                before=seller_before,
                after={
                    "display_name": seller.display_name,
                    "email": seller.email,
                    "phone": seller.phone,
                    "is_active": seller.is_active,
                    "farm_name": profile.farm_name,
                    "verification_status": profile.verification_status,
                },
                community=profile.community,
            )

            Notification.objects.create(
                user=seller,
                title="ข้อมูลผู้ขายได้รับการปรับปรุง",
                message="เจ้าหน้าที่ชุมชนได้ปรับปรุงข้อมูลบัญชีหรือข้อมูลฟาร์มของคุณ",
                link="/accounts/profile/",
            )
        messages.success(request, f"บันทึกข้อมูลผู้ขาย {seller} แล้ว")
        return redirect("accounts:staff_seller_detail", user_id=seller.pk)

    return render(
        request,
        "accounts/staff_seller_form.html",
        {
            "seller": seller,
            "profile": profile,
            "account_form": account_form,
            "profile_form": profile_form,
            "document_is_image": bool(
                profile.verification_document
                and profile.verification_document.name.lower().endswith(
                    (".jpg", ".jpeg", ".png", ".webp")
                )
            ),
        },
    )

@login_required
def toggle_member_active(request, user_id):
    target = get_object_or_404(managed_users_queryset(request.user), pk=user_id)
    if request.method == "POST":
        if target.pk == request.user.pk:
            messages.warning(request, "ไม่สามารถบล็อกบัญชีของตัวเองได้")
        else:
            target.is_active = not target.is_active
            target.save(update_fields=["is_active"])
            status = "ปลดบล็อก" if target.is_active else "บล็อก"
            Notification.objects.create(
                user=target,
                title=f"บัญชีของคุณถูก{status}",
                message=f"ผู้ดูแลระบบได้{status}บัญชีของคุณ",
                link="/accounts/dashboard/",
            )
            messages.success(request, f"{status}บัญชี {target} แล้ว")
    return redirect("accounts:members", role=role_slug_for(target))


@login_required
def send_notification(request, user_id=None):
    recipients = managed_users_queryset(request.user).exclude(pk=request.user.pk).order_by("role", "username")
    if (
        not recipients.exists()
        and not request.user.is_owner
        and not request.user.is_superuser
        and not request.user.is_cooperative_staff
    ):
        messages.error(request, "บัญชีนี้ไม่มีสิทธิ์แจ้งเตือนสมาชิก")
        return redirect("accounts:dashboard")

    initial = {}
    if user_id:
        target = get_object_or_404(recipients, pk=user_id)
        initial["recipients"] = [target.pk]
        initial["recipient_scope"] = NotificationForm.RecipientScope.SELECTED

    form = NotificationForm(request.POST or None, recipients=recipients, initial=initial)
    if request.method == "POST" and form.is_valid():
        selected = list(form.selected_recipients())
        send_email = form.cleaned_data["send_email"]
        for recipient in selected:
            notify_user(
                recipient,
                form.cleaned_data["title"],
                form.cleaned_data["message"],
                form.cleaned_data["link"],
                send_email_message=send_email,
            )
        message = f"ส่งแจ้งเตือนให้สมาชิก {len(selected)} คนแล้ว"
        queued_emails = sum(1 for recipient in selected if send_email and recipient.email)
        if queued_emails:
            message += f" และเข้าคิวอีเมล {queued_emails} ฉบับ"
        messages.success(request, message)
        return redirect("accounts:dashboard")

    recipient_counts = {
        "all": recipients.count(),
        "consumers": recipients.filter(role=User.Roles.CONSUMER).count(),
        "farmers": recipients.filter(role=User.Roles.FARMER).count(),
        "staff": recipients.filter(role=User.Roles.COOPERATIVE_STAFF).count(),
    }
    return render(
        request,
        "accounts/notification_form.html",
        {"form": form, "recipient_counts": recipient_counts},
    )


def _private_file_response(field_file, *, as_attachment=True):
    if not field_file or not field_file.name:
        raise Http404
    filename = Path(field_file.name).name
    content_type, _ = mimetypes.guess_type(filename)
    response = FileResponse(
        field_file.open("rb"),
        as_attachment=as_attachment,
        filename=filename,
        content_type=content_type or "application/octet-stream",
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def farmer_document_download(request, profile_id):
    profile = get_object_or_404(FarmerProfile.objects.select_related("user", "community"), pk=profile_id)
    community = user_community(request.user)
    allowed = (
        request.user.is_owner
        or request.user.pk == profile.user_id
        or (
            request.user.is_cooperative_staff
            and community is not None
            and profile.community_id == community.id
        )
    )
    if not allowed:
        raise Http404
    record_audit(request, AuditEvent.Action.DOWNLOAD, profile, description="ดาวน์โหลดเอกสารยืนยันเกษตรกร", community=profile.community)
    return _private_file_response(
        profile.verification_document,
        as_attachment=request.GET.get("inline") != "1",
    )


@login_required
def report_evidence_download(request, report_id):
    report = get_object_or_404(scoped_reports(request.user), pk=report_id)
    record_audit(request, AuditEvent.Action.DOWNLOAD, report, description="ดาวน์โหลดหลักฐานรายงาน", community=report.community)
    return _private_file_response(report.evidence)


@login_required
def report_attachment_download(request, message_id):
    message = get_object_or_404(ReportMessage.objects.select_related("report"), pk=message_id)
    get_object_or_404(scoped_reports(request.user), pk=message.report_id)
    record_audit(request, AuditEvent.Action.DOWNLOAD, message, description="ดาวน์โหลดไฟล์แนบรายงาน", community=message.report.community)
    return _private_file_response(message.attachment)

@login_required
def export_my_data(request):
    user = request.user
    profile = getattr(user, "farmer_profile", None)
    data = {
        "บัญชี": {
            "ชื่อผู้ใช้": user.username,
            "ชื่อที่แสดง": user.display_name,
            "อีเมล": user.email,
            "เบอร์โทรศัพท์": user.phone,
            "บทบาท": user.get_role_display(),
            "วันที่สมัคร": user.date_joined.isoformat(),
            "เวอร์ชันเงื่อนไข": user.terms_version,
            "เวอร์ชันนโยบายความเป็นส่วนตัว": user.privacy_version,
        },
        "ข้อมูลเกษตรกร": {
            "ชื่อฟาร์ม": profile.farm_name,
            "ชุมชน": profile.community.name if profile and profile.community else "",
            "ที่อยู่": profile.address,
            "จังหวัด": profile.province,
            "อำเภอ": profile.district,
            "สถานะการตรวจสอบ": profile.get_verification_status_display(),
        }
        if profile
        else None,
        "คำสั่งซื้อ": [
            {
                "เลขอ้างอิง": order.reference,
                "สถานะ": order.get_status_display(),
                "สถานะชำระเงิน": order.get_payment_status_display(),
                "ยอดรวม": str(order.total_amount),
                "วันที่": order.created_at.isoformat(),
            }
            for order in Order.objects.filter(Q(buyer=user) | Q(seller=user)).order_by("created_at")
        ],
        "รายงานที่ส่ง": [
            {
                "รหัส": report.pk,
                "ประเภท": report.get_target_type_display(),
                "เหตุผล": report.get_reason_display(),
                "สถานะ": report.get_status_display(),
                "วันที่": report.created_at.isoformat(),
            }
            for report in Report.objects.filter(reporter=user).order_by("created_at")
        ],
    }
    record_audit(request, AuditEvent.Action.DOWNLOAD, user, description="ส่งออกข้อมูลส่วนบุคคล")
    response = JsonResponse(data, json_dumps_params={"ensure_ascii": False, "indent": 2})
    response["Content-Disposition"] = 'attachment; filename="my-market-data.json"'
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def deactivate_my_account(request):
    if request.user.is_owner or request.user.is_cooperative_staff:
        messages.error(request, "บัญชีผู้ดูแลและเจ้าหน้าที่ต้องให้เจ้าของระบบดำเนินการ")
        return redirect("accounts:profile")
    if request.method != "POST":
        return render(request, "accounts/deactivate_account.html")
    if not request.user.check_password(request.POST.get("password", "")):
        messages.error(request, "รหัสผ่านไม่ถูกต้อง")
        return render(request, "accounts/deactivate_account.html")

    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        record_audit(request, AuditEvent.Action.UPDATE, user, description="ผู้ใช้ปิดบัญชีและขอลบข้อมูลส่วนบุคคล")
        profile = getattr(user, "farmer_profile", None)
        if profile:
            if profile.verification_document:
                profile.verification_document.delete(save=False)
            profile.farm_name = "บัญชีถูกปิด"
            profile.bio = ""
            profile.address = ""
            profile.province = ""
            profile.district = ""
            profile.verification_document = ""
            profile.save(
                update_fields=[
                    "farm_name",
                    "bio",
                    "address",
                    "province",
                    "district",
                    "verification_document",
                    "updated_at",
                ]
            )
            Product.objects.filter(seller=user).update(status=Product.Status.ARCHIVED)

        Notification.objects.filter(user=user).delete()
        user.username = f"deleted-{user.pk}-{uuid.uuid4().hex[:10]}"
        user.email = ""
        user.display_name = "บัญชีถูกปิด"
        user.phone = ""
        user.first_name = ""
        user.last_name = ""
        user.is_active = False
        user.set_unusable_password()
        user.save(
            update_fields=[
                "username",
                "email",
                "display_name",
                "phone",
                "first_name",
                "last_name",
                "is_active",
                "password",
            ]
        )
    logout(request)
    messages.success(request, "ปิดบัญชีและลบข้อมูลส่วนบุคคลที่ไม่จำเป็นแล้ว")
    return redirect("catalog:product_list")
@login_required
def conversations_list(request):
    latest_message = DirectMessage.objects.filter(conversation=OuterRef("pk")).order_by("-created_at")
    conversations = (
        Conversation.objects.filter(Q(buyer=request.user) | Q(seller=request.user))
        .select_related("buyer", "seller", "seller__farmer_profile__community", "product", "product__community", "order")
        .annotate(
            unread_count=Count(
                "messages",
                filter=Q(messages__read_at__isnull=True) & ~Q(messages__sender=request.user),
            ),
            last_message_body=Subquery(latest_message.values("body")[:1]),
            last_message_media_type=Subquery(latest_message.values("media_type")[:1]),
            last_message_at=Subquery(latest_message.values("created_at")[:1]),
        )
        .order_by("-updated_at")
    )
    return render(request, "accounts/conversations.html", {"conversations": conversations})


def _chat_is_blocked(first_user, second_user):
    return ChatBlock.objects.filter(
        Q(blocker=first_user, blocked=second_user)
        | Q(blocker=second_user, blocked=first_user)
    ).exists()


def _conversation_community(conversation):
    if conversation.product_id:
        return conversation.product.community
    seller_profile = getattr(conversation.seller, "farmer_profile", None)
    return getattr(seller_profile, "community", None)

def _conversation_for_user(request, pk):
    return get_object_or_404(
        Conversation.objects.select_related("buyer", "seller", "seller__farmer_profile__community", "product", "product__community", "order"),
        Q(buyer=request.user) | Q(seller=request.user),
        pk=pk,
    )


def _start_conversation(request, *, buyer, seller, product=None, order=None):
    if _chat_is_blocked(buyer, seller):
        messages.error(request, "ไม่สามารถเริ่มบทสนทนานี้ได้")
        return None
    conversation, _ = Conversation.objects.get_or_create(
        buyer=buyer,
        seller=seller,
        product=product,
        order=order,
    )
    return conversation


@login_required
@require_POST
def conversation_start(request, product_id):
    product = get_object_or_404(
        Product.objects.select_related("seller"),
        pk=product_id,
        status=Product.Status.ACTIVE,
    )
    if product.seller_id == request.user.id:
        messages.info(request, "นี่คือสินค้าของคุณ")
        return redirect(product)
    if not request.user.can_buy:
        messages.error(request, "การเริ่มแชทจากหน้าสินค้าเปิดให้บัญชีผู้บริโภค")
        return redirect(product)

    conversation = _start_conversation(
        request,
        buyer=request.user,
        seller=product.seller,
        product=product,
    )
    if not conversation:
        return redirect(product)
    return redirect("accounts:conversation_detail", pk=conversation.pk)


@login_required
@require_POST
def conversation_start_seller(request, seller_id):
    seller = get_object_or_404(
        User.objects.select_related("farmer_profile__community"),
        pk=seller_id,
        role=User.Roles.FARMER,
        is_active=True,
    )
    if seller.pk == request.user.pk:
        messages.info(request, "นี่คือร้านค้าของคุณ")
        return redirect("catalog:seller_store", seller_id=seller.pk)
    if not request.user.can_buy:
        messages.error(request, "การเริ่มแชทกับร้านค้าเปิดให้บัญชีผู้บริโภค")
        return redirect("catalog:seller_store", seller_id=seller.pk)

    conversation = _start_conversation(
        request,
        buyer=request.user,
        seller=seller,
    )
    if not conversation:
        return redirect("catalog:seller_store", seller_id=seller.pk)
    return redirect("accounts:conversation_detail", pk=conversation.pk)
@login_required
@require_POST
def conversation_start_order(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related("buyer", "seller").prefetch_related("items__product"),
        pk=order_id,
    )
    if request.user.pk not in {order.buyer_id, order.seller_id}:
        messages.error(request, "คุณไม่มีสิทธิ์เริ่มบทสนทนาสำหรับคำสั่งซื้อนี้")
        return redirect("orders:order_list")

    first_item = next(iter(order.items.all()), None)
    if not first_item:
        messages.error(request, "คำสั่งซื้อนี้ไม่มีรายการสินค้า")
        return redirect(order)

    conversation = _start_conversation(
        request,
        buyer=order.buyer,
        seller=order.seller,
        product=first_item.product,
        order=order,
    )
    if not conversation:
        return redirect(order)
    return redirect("accounts:conversation_detail", pk=conversation.pk)


@login_required
@require_POST
def conversation_block(request, pk):
    conversation = _conversation_for_user(request, pk)
    other_participant = conversation.other_participant(request.user)
    block, created = ChatBlock.objects.get_or_create(
        blocker=request.user,
        blocked=other_participant,
    )
    if created:
        record_audit(
            request,
            AuditEvent.Action.BLOCK,
            block,
            description="บล็อกผู้ใช้งานจากบทสนทนา",
            community=_conversation_community(conversation),
        )
        messages.success(request, f"บล็อก {other_participant} แล้ว คุณจะไม่สามารถส่งข้อความถึงกันได้")
    else:
        block.delete()
        messages.success(request, f"ปลดบล็อก {other_participant} แล้ว")
    return redirect("accounts:conversation_detail", pk=conversation.pk)


@login_required
def conversation_report(request, pk):
    conversation = _conversation_for_user(request, pk)
    other_participant = conversation.other_participant(request.user)
    form = ReportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        report = form.save(commit=False)
        report.reporter = request.user
        report.target_type = Report.TargetType.CONVERSATION
        report.conversation = conversation
        report.product = conversation.product
        report.order = conversation.order
        report.reported_user = other_participant
        report.community = _conversation_community(conversation)
        report.save()
        record_audit(
            request,
            AuditEvent.Action.CREATE,
            report,
            description="รายงานบทสนทนา",
            community=report.community,
        )
        messages.success(request, "ส่งรายงานบทสนทนาแล้ว เจ้าหน้าที่จะตรวจสอบโดยเร็ว")
        return redirect("accounts:conversation_detail", pk=conversation.pk)
    return render(
        request,
        "accounts/conversation_report.html",
        {"conversation": conversation, "other_participant": other_participant, "form": form},
    )


@login_required
def conversation_detail(request, pk):
    conversation = _conversation_for_user(request, pk)
    other_participant = conversation.other_participant(request.user)
    blocked_by_user = ChatBlock.objects.filter(
        blocker=request.user,
        blocked=other_participant,
    ).exists()
    blocked_by_other = ChatBlock.objects.filter(
        blocker=other_participant,
        blocked=request.user,
    ).exists()
    can_send = not blocked_by_user and not blocked_by_other

    DirectMessage.objects.filter(
        conversation=conversation,
        read_at__isnull=True,
    ).exclude(sender=request.user).update(read_at=timezone.now())

    form = DirectMessageForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if not can_send:
            messages.error(request, "ไม่สามารถส่งข้อความในบทสนทนานี้ได้")
        elif form.is_valid():
            one_minute_ago = timezone.now() - timedelta(minutes=1)
            sent_count = DirectMessage.objects.filter(
                conversation=conversation,
                sender=request.user,
                created_at__gte=one_minute_ago,
            ).count()
            if sent_count >= 12:
                form.add_error(None, "คุณส่งข้อความเร็วเกินไป กรุณารอประมาณ 1 นาทีแล้วลองใหม่")
            else:
                direct_message = form.save(commit=False)
                direct_message.conversation = conversation
                direct_message.sender = request.user
                if direct_message.attachment:
                    direct_message.media_type = chat_media_type_for_upload(direct_message.attachment)
                direct_message.full_clean()
                direct_message.save()
                Conversation.objects.filter(pk=conversation.pk).update(updated_at=timezone.now())
                notify_user(
                    other_participant,
                    title=f"ข้อความใหม่จาก {request.user}",
                    message=(f"เกี่ยวกับสินค้า {conversation.product.name}" if conversation.product_id else "เกี่ยวกับร้านค้าของคุณ"),
                    link=reverse("accounts:conversation_detail", args=[conversation.pk]),
                    send_email_message=False,
                )
                return redirect("accounts:conversation_detail", pk=conversation.pk)

    message_queryset = conversation.messages.select_related("sender").order_by("-created_at")
    conversation_messages = list(message_queryset[:100])
    conversation_messages.reverse()
    return render(
        request,
        "accounts/conversation_detail.html",
        {
            "conversation": conversation,
            "conversation_messages": conversation_messages,
            "has_older_messages": message_queryset.count() > len(conversation_messages),
            "other_participant": other_participant,
            "blocked_by_user": blocked_by_user,
            "blocked_by_other": blocked_by_other,
            "can_send": can_send,
            "form": form,
        },
    )


@login_required
@require_POST
@transaction.atomic
def conversation_media_upload(request, pk):
    """Upload one piece of chat media and publish it to the live conversation."""
    conversation = _conversation_for_user(request, pk)
    other_participant = conversation.other_participant(request.user)
    blocked = ChatBlock.objects.filter(
        Q(blocker=request.user, blocked=other_participant)
        | Q(blocker=other_participant, blocked=request.user)
    ).exists()
    if blocked:
        return JsonResponse({"error": "ไม่สามารถส่งข้อความในบทสนทนานี้ได้"}, status=403)

    attachment = request.FILES.get("attachment")
    body = (request.POST.get("body") or "").strip()
    if not attachment:
        return JsonResponse({"error": "กรุณาเลือกไฟล์รูปภาพหรือวิดีโอ"}, status=400)
    if len(body) > 2000:
        return JsonResponse({"error": "ข้อความต้องไม่เกิน 2,000 ตัวอักษร"}, status=400)

    try:
        client_id = uuid.UUID(request.POST.get("client_id", ""))
    except (ValueError, AttributeError):
        return JsonResponse({"error": "ไม่พบรหัสการส่งไฟล์ กรุณาลองใหม่"}, status=400)

    existing = DirectMessage.objects.filter(sender=request.user, client_id=client_id).first()
    if existing:
        if existing.conversation_id != conversation.pk:
            return JsonResponse({"error": "รหัสการส่งไฟล์นี้ถูกใช้งานแล้ว"}, status=409)
        return JsonResponse({"message": serialize_message(existing, conversation)})

    if DirectMessage.objects.filter(
        conversation=conversation,
        sender=request.user,
        created_at__gte=timezone.now() - timedelta(minutes=1),
    ).count() >= 12:
        return JsonResponse({"error": "คุณส่งข้อความเร็วเกินไป กรุณารอประมาณ 1 นาทีแล้วลองใหม่"}, status=429)

    try:
        media_type = chat_media_type_for_upload(attachment)
        message = DirectMessage(
            conversation=conversation,
            sender=request.user,
            client_id=client_id,
            body=body,
            attachment=attachment,
            media_type=media_type,
        )
        message.full_clean()
        message.save()
    except ValidationError as error:
        return JsonResponse({"error": error.messages[0]}, status=400)

    Conversation.objects.filter(pk=conversation.pk).update(updated_at=message.created_at)
    notify_user(
        other_participant,
        title=f"ข้อความใหม่จาก {request.user}",
        message=(f"เกี่ยวกับสินค้า {conversation.product.name}" if conversation.product_id else "เกี่ยวกับร้านค้าของคุณ"),
        link=reverse("accounts:conversation_detail", args=[conversation.pk]),
        send_email_message=False,
    )
    return JsonResponse({"message": serialize_message(message, conversation)}, status=201)


@login_required
def conversation_media(request, message_id):
    message = get_object_or_404(DirectMessage.objects.select_related("conversation"), pk=message_id)
    if request.user.pk not in {message.conversation.buyer_id, message.conversation.seller_id}:
        raise Http404
    return _private_file_response(message.attachment, as_attachment=False)
