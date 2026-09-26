from django.urls import reverse
from django.db.models import Count, Q

from accounts.models import EmailDelivery, FarmerProfile, Report, User
from catalog.models import Product
from orders.models import Order, Shipment
from payments.models import Payment, Refund, SellerSettlement, StripeEvent

ADMIN_WORKFLOWS = (
    {
        "key": "members",
        "name": "สมาชิกและชุมชน",
        "description": "ดูแลบัญชีผู้ใช้ ผู้ขาย เจ้าหน้าที่ และพื้นที่ชุมชน",
        "icon": "users",
        "models": (
            "accounts.user",
            "accounts.farmerprofile",
            "accounts.communitystaffprofile",
            "accounts.community",
            "accounts.deliveryaddress",
        ),
    },
    {
        "key": "catalog",
        "name": "สินค้าและร้านค้า",
        "description": "ตรวจสอบสินค้า หมวดสินค้า รีวิว และรายการที่สมาชิกสนใจ",
        "icon": "package-search",
        "models": (
            "catalog.product",
            "catalog.category",
            "catalog.homeslide",
            "catalog.productreview",
            "catalog.productfavorite",
            "catalog.sellerfavorite",
        ),
    },
    {
        "key": "orders",
        "name": "คำสั่งซื้อและการจัดส่ง",
        "description": "ติดตามคำสั่งซื้อ สถานะพัสดุ และค่าจัดส่ง",
        "icon": "clipboard-list",
        "models": ("orders.order", "orders.shipment", "orders.shippingrate"),
    },
    {
        "key": "payments",
        "name": "การเงินและการชำระเงิน",
        "description": "ตรวจสอบการชำระเงิน คืนเงิน และยอดที่ต้องจ่ายผู้ขาย",
        "icon": "wallet-cards",
        "models": (
            "payments.payment",
            "payments.refund",
            "payments.sellersettlement",
            "payments.sellerpaymentaccount",
            "payments.customerpaymentprofile",
            "payments.savedpaymentmethod",
        ),
    },
    {
        "key": "care",
        "name": "การดูแลสมาชิก",
        "description": "ตอบแชท จัดการรายงานปัญหา ข่าวสาร และการแจ้งเตือน",
        "icon": "messages-square",
        "models": (
            "accounts.supportticket",
            "accounts.report",
            "accounts.notification",
            "accounts.newspost",
            "accounts.conversation",
            "accounts.chatblock",
        ),
    },
    {
        "key": "system",
        "name": "ตรวจสอบการทำงานของระบบ",
        "description": "ข้อมูลบันทึกอัตโนมัติสำหรับตรวจสอบเมื่อเกิดปัญหา",
        "icon": "shield-check",
        "is_system": True,
        "models": (
            "accounts.auditevent",
            "accounts.loginattempt",
            "accounts.emaildelivery",
            "payments.stripeevent",
        ),
    },
)


ADMIN_MODEL_DESCRIPTIONS = {
    "accounts.user": "ข้อมูลส่วนตัว บทบาท และสถานะสมาชิก",
    "accounts.farmerprofile": "ข้อมูลร้านค้า เอกสาร และผลตรวจสอบผู้ขาย",
    "accounts.communitystaffprofile": "กำหนดเจ้าหน้าที่ประจำแต่ละชุมชน",
    "accounts.community": "ข้อมูลชุมชนและพื้นที่ให้บริการ",
    "accounts.deliveryaddress": "ที่อยู่จัดส่งที่สมาชิกบันทึกไว้",
    "catalog.product": "รายละเอียด ราคา สต็อก และสถานะการขาย",
    "catalog.category": "หมวดหมู่ที่ใช้ค้นหาและแสดงสินค้า",
    "catalog.homeslide": "ภาพหน้าปกหน้าแรกที่สลับแสดงอัตโนมัติ",
    "catalog.productreview": "ความคิดเห็นและคะแนนจากผู้ซื้อ",
    "catalog.productfavorite": "รายการสินค้าที่สมาชิกบันทึกไว้",
    "catalog.sellerfavorite": "ร้านค้าที่สมาชิกติดตาม",
    "orders.order": "ติดตามสถานะ การจัดส่ง และเลขพัสดุ",
    "orders.shipment": "ตรวจสอบสถานะพัสดุ จุดติดตาม และข้อมูลจากผู้ให้บริการขนส่ง",
    "orders.shippingrate": "กำหนดค่าจัดส่งตามพื้นที่และน้ำหนัก",
    "payments.payment": "ตรวจสอบผลการชำระเงินออนไลน์",
    "payments.refund": "พิจารณาคำขอและผลการคืนเงิน",
    "payments.sellersettlement": "ตรวจสอบและโอนยอดสุทธิให้ผู้ขาย",
    "payments.sellerpaymentaccount": "สถานะบัญชีรับเงินออนไลน์ของผู้ขาย",
    "payments.customerpaymentprofile": "บัญชีลูกค้าในระบบชำระเงิน",
    "payments.savedpaymentmethod": "ข้อมูลบัตรแบบปกปิดที่สมาชิกบันทึกไว้",
    "accounts.supportticket": "พูดคุยและตอบคำถามจากผู้ขาย",
    "accounts.report": "ตรวจสอบเรื่องร้องเรียนและบันทึกผลดำเนินการ",
    "accounts.notification": "ส่งและตรวจสอบการแจ้งเตือนสมาชิก",
    "accounts.newspost": "จัดการข่าวสารที่แสดงในเว็บไซต์",
    "accounts.conversation": "ตรวจสอบบทสนทนาเมื่อมีการรายงานปัญหา",
    "accounts.chatblock": "ตรวจสอบการบล็อกระหว่างสมาชิก",
    "accounts.auditevent": "ประวัติการเปลี่ยนแปลงข้อมูลสำคัญ",
    "accounts.loginattempt": "ประวัติการเข้าสู่ระบบที่ผิดปกติ",
    "accounts.emaildelivery": "สถานะอีเมลที่ระบบส่งให้สมาชิก",
    "payments.stripeevent": "เหตุการณ์จากระบบชำระเงินสำหรับตรวจสอบ",
}


def build_admin_navigation(app_list):
    """Turn Django's model-oriented app list into task-oriented workflows."""
    available_models = {}
    for app in app_list:
        for model in app.get("models", ()):
            model_class = model.get("model")
            if model_class is not None:
                available_models[model_class._meta.label_lower] = model

    navigation = []
    for workflow in ADMIN_WORKFLOWS:
        models = []
        for model_label in workflow["models"]:
            model = available_models.get(model_label)
            if model is None:
                continue
            item = dict(model)
            item["description"] = ADMIN_MODEL_DESCRIPTIONS.get(
                model_label, "จัดการข้อมูลที่เกี่ยวข้องกับระบบ"
            )
            item["model_label"] = model_label
            models.append(item)
        if not models:
            continue
        group = {key: value for key, value in workflow.items() if key != "models"}
        group["models"] = models
        group["app_label"] = f"workflow-{workflow['key']}"
        group["app_url"] = next(
            (model.get("admin_url") for model in models if model.get("admin_url")),
            "#",
        )
        navigation.append(group)
    return navigation


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
    pending_refunds = Refund.objects.filter(
        status__in=(Refund.Status.REQUESTED, Refund.Status.FAILED)
    ).count()
    ready_settlements = SellerSettlement.objects.filter(
        status=SellerSettlement.Status.READY
    ).count()
    failed_settlements = SellerSettlement.objects.filter(
        status=SellerSettlement.Status.FAILED
    ).count()
    pending_stripe_events = StripeEvent.objects.filter(processed=False).count()
    shipment_issues = Shipment.objects.filter(
        status__in=("AttemptFail", "Exception", "Expired")
    ).count()
    active_members = User.objects.filter(is_active=True).aggregate(
        consumers=Count("pk", filter=Q(role=User.Roles.CONSUMER)),
        farmers=Count("pk", filter=Q(role=User.Roles.FARMER)),
        staff=Count("pk", filter=Q(role=User.Roles.COOPERATIVE_STAFF)),
        owners=Count(
            "pk",
            filter=Q(role=User.Roles.OWNER) | Q(is_superuser=True),
        ),
    )

    return {
        "admin_stats": (
            {
                "label": "ผู้ดูแลระบบที่ใช้งานอยู่",
                "value": active_members["owners"],
                "detail": "บัญชี Admin และ Owner ที่เปิดใช้งาน",
                "url": reverse("admin:accounts_user_changelist")
                + "?role__exact=owner",
                "icon": "shield-check",
            },
            {
                "label": "ผู้ซื้อที่ใช้งานอยู่",
                "value": active_members["consumers"],
                "detail": "บัญชีผู้ซื้อที่เปิดใช้งาน",
                "url": reverse("admin:accounts_user_changelist")
                + "?role__exact=consumer",
                "icon": "shopping-bag",
            },
            {
                "label": "ผู้ขายที่ใช้งานอยู่",
                "value": active_members["farmers"],
                "detail": "บัญชีผู้ขายที่เปิดใช้งาน",
                "url": reverse("admin:accounts_user_changelist")
                + "?role__exact=farmer",
                "icon": "sprout",
            },
            {
                "label": "เจ้าหน้าที่ที่ใช้งานอยู่",
                "value": active_members["staff"],
                "detail": "บัญชีเจ้าหน้าที่ที่เปิดใช้งาน",
                "url": reverse("admin:accounts_user_changelist")
                + "?role__exact=cooperative_staff",
                "icon": "badge-check",
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
                "label": "คำขอคืนเงินรอดำเนินการ",
                "value": pending_refunds,
                "url": reverse("admin:payments_refund_changelist"),
            },
            {
                "label": "ยอดผู้ขายพร้อมโอน",
                "value": ready_settlements,
                "url": reverse("admin:payments_sellersettlement_changelist")
                + "?status__exact=ready",
            },
            {
                "label": "ยอดผู้ขายโอนไม่สำเร็จ",
                "value": failed_settlements,
                "url": reverse("admin:payments_sellersettlement_changelist")
                + "?status__exact=failed",
            },
            {
                "label": "เหตุการณ์ Stripe รอประมวลผล",
                "value": pending_stripe_events,
                "url": reverse("admin:payments_stripeevent_changelist")
                + "?processed__exact=0",
            },
            {
                "label": "อีเมลที่ส่งไม่สำเร็จ",
                "value": failed_emails,
                "url": reverse("admin:accounts_emaildelivery_changelist")
                + "?status__exact=failed",
            },
            {
                "label": "พัสดุที่ต้องติดตาม",
                "value": shipment_issues,
                "url": reverse("admin:orders_shipment_changelist")
                + "?status__in=AttemptFail,Exception,Expired",
            },
        ),
    }
