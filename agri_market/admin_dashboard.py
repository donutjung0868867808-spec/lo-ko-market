from django.urls import reverse

from accounts.models import EmailDelivery, FarmerProfile, Report, User
from catalog.models import Product
from orders.models import Order
from payments.models import Payment


def build_admin_dashboard_context():
    active_order_statuses = (
        Order.Status.PENDING_PAYMENT,
        Order.Status.PAID,
        Order.Status.CONFIRMED,
        Order.Status.PREPARING,
        Order.Status.SHIPPED,
    )
    pending_farmers = FarmerProfile.objects.filter(
        verification_status=FarmerProfile.VerificationStatus.PENDING
    ).count()
    pending_products = Product.objects.filter(status=Product.Status.PENDING).count()
    active_orders = Order.objects.filter(status__in=active_order_statuses).count()
    open_reports = Report.objects.filter(
        status__in=(Report.Status.OPEN, Report.Status.REVIEWING)
    ).count()
    failed_payments = Payment.objects.filter(status=Payment.Status.FAILED).count()
    failed_emails = EmailDelivery.objects.filter(status=EmailDelivery.Status.FAILED).count()

    return {
        "admin_stats": (
            {
                "label": "สมาชิกที่ใช้งานอยู่",
                "value": User.objects.filter(is_active=True).count(),
                "detail": "บัญชีผู้ซื้อ ผู้ขาย และเจ้าหน้าที่",
                "url": reverse("admin:accounts_user_changelist"),
                "icon": "users",
            },
            {
                "label": "ผู้ขายรอตรวจสอบ",
                "value": pending_farmers,
                "detail": "เอกสารเกษตรกรที่ต้องพิจารณา",
                "url": reverse("admin:accounts_farmerprofile_changelist")
                + "?verification_status__exact=pending",
                "icon": "user-check",
            },
            {
                "label": "สินค้ารอตรวจสอบ",
                "value": pending_products,
                "detail": "รายการที่ยังไม่เปิดขาย",
                "url": reverse("admin:catalog_product_changelist")
                + "?status__exact=pending",
                "icon": "package-check",
            },
            {
                "label": "คำสั่งซื้อกำลังดำเนินการ",
                "value": active_orders,
                "detail": "รายการที่ยังไม่จบกระบวนการ",
                "url": reverse("admin:orders_order_changelist"),
                "icon": "clipboard-list",
            },
        ),
        "admin_attention": (
            {
                "label": "รายงานปัญหาที่ยังเปิดอยู่",
                "value": open_reports,
                "url": reverse("admin:accounts_report_changelist"),
            },
            {
                "label": "การชำระเงินไม่สำเร็จ",
                "value": failed_payments,
                "url": reverse("admin:payments_payment_changelist")
                + "?status__exact=failed",
            },
            {
                "label": "อีเมลที่ส่งไม่สำเร็จ",
                "value": failed_emails,
                "url": reverse("admin:accounts_emaildelivery_changelist")
                + "?status__exact=failed",
            },
        ),
    }
