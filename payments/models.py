import uuid

from django.conf import settings
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models

from agri_market.storage import private_storage
from accounts.models import validate_file_size
from accounts.validators import validate_private_document


class Payment(models.Model):
    class Provider(models.TextChoices):
        STRIPE = "stripe", "Stripe"

    class Status(models.TextChoices):
        CREATED = "created", "สร้างรายการแล้ว"
        PROCESSING = "processing", "กำลังดำเนินการ"
        PAID = "paid", "ชำระแล้ว"
        FAILED = "failed", "ไม่สำเร็จ"
        REFUNDED = "refunded", "คืนเงินแล้ว"

    order = models.OneToOneField(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="payment",
    )
    provider = models.CharField(
        max_length=20,
        choices=Provider.choices,
        default=Provider.STRIPE,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CREATED,
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0.01)])
    currency = models.CharField(max_length=10, default="thb")
    checkout_session_id = models.CharField(max_length=255, blank=True, db_index=True)
    checkout_attempt_id = models.UUIDField(default=uuid.uuid4, editable=False)
    checkout_url = models.URLField(max_length=1000, blank=True)
    checkout_expires_at = models.DateTimeField(null=True, blank=True)
    payment_intent_id = models.CharField(max_length=255, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    refunded_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "การชำระเงิน"
        verbose_name_plural = "การชำระเงิน"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payment_amount_positive"),
            models.CheckConstraint(condition=models.Q(refunded_amount__gte=0), name="payment_refunded_nonnegative"),
            models.CheckConstraint(condition=models.Q(refunded_amount__lte=models.F("amount")), name="payment_refunded_not_over_amount"),
            models.UniqueConstraint(
                fields=["checkout_session_id"],
                condition=~models.Q(checkout_session_id=""),
                name="unique_nonblank_checkout_session",
            ),
            models.UniqueConstraint(
                fields=["payment_intent_id"],
                condition=~models.Q(payment_intent_id=""),
                name="unique_nonblank_payment_intent",
            ),
        ]

    def __str__(self):
        return f"การชำระเงินคำสั่งซื้อ #{self.order_id} - {self.get_status_display()}"

class StripeEvent(models.Model):
    event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    processed = models.BooleanField(default=False)
    error_message = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "เหตุการณ์จาก Stripe"
        verbose_name_plural = "เหตุการณ์จาก Stripe"
        ordering = ["-received_at"]


class Refund(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "รอดำเนินการ"
        PROCESSING = "processing", "กำลังคืนเงิน"
        SUCCEEDED = "succeeded", "คืนเงินสำเร็จ"
        FAILED = "failed", "คืนเงินไม่สำเร็จ"
        REJECTED = "rejected", "ไม่อนุมัติคำขอ"

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0.01)])
    reason = models.TextField()
    evidence = models.FileField(
        upload_to="refund-evidence/%Y/%m/",
        storage=private_storage,
        blank=True,
        validators=[
            FileExtensionValidator(["pdf", "jpg", "jpeg", "png", "webp"]),
            validate_file_size,
            validate_private_document,
        ],
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    stripe_refund_id = models.CharField(max_length=255, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="refund_requests",
    )
    resolution_note = models.TextField("เหตุผลการตัดสิน", blank=True, default="")
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handled_refunds",
    )
    handled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "รายการคืนเงิน"
        verbose_name_plural = "รายการคืนเงิน"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="refund_amount_positive"),
            models.UniqueConstraint(
                fields=["payment"],
                condition=models.Q(status__in=["requested", "processing", "failed"]),
                name="one_active_refund_per_payment",
            ),
        ]


class CustomerPaymentProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_payment_profile",
    )
    stripe_customer_id = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "ข้อมูลลูกค้า Stripe"
        verbose_name_plural = "ข้อมูลลูกค้า Stripe"

    def __str__(self):
        return f"ข้อมูลชำระเงินของ {self.user}"


class SavedPaymentMethod(models.Model):
    profile = models.ForeignKey(
        CustomerPaymentProfile,
        on_delete=models.CASCADE,
        related_name="payment_methods",
    )
    stripe_payment_method_id = models.CharField(max_length=255, unique=True)
    method_type = models.CharField(max_length=30, default="card")
    brand = models.CharField(max_length=40, blank=True)
    last4 = models.CharField(max_length=4)
    exp_month = models.PositiveSmallIntegerField(null=True, blank=True)
    exp_year = models.PositiveSmallIntegerField(null=True, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "บัตรที่บันทึกไว้"
        verbose_name_plural = "บัตรที่บันทึกไว้"
        ordering = ["-is_default", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile"],
                condition=models.Q(is_default=True),
                name="one_default_payment_method_per_profile",
            )
        ]

    def __str__(self):
        return f"{self.brand} ลงท้าย {self.last4}"

class SellerPaymentAccount(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "ยังไม่ได้เริ่มตั้งค่า"
        PENDING = "pending", "รอตรวจสอบข้อมูล"
        ACTIVE = "active", "พร้อมรับเงิน"
        RESTRICTED = "restricted", "ถูกจำกัดการใช้งาน"

    seller = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payment_account",
    )
    stripe_account_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_STARTED)
    country = models.CharField(max_length=2, default="TH")
    details_submitted = models.BooleanField(default=False)
    charges_enabled = models.BooleanField(default=False)
    payouts_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "บัญชีรับเงินของผู้ขาย"
        verbose_name_plural = "บัญชีรับเงินของผู้ขาย"
        constraints = [
            models.UniqueConstraint(
                fields=["stripe_account_id"],
                condition=~models.Q(stripe_account_id=""),
                name="unique_nonblank_stripe_account",
            ),
        ]

    def __str__(self):
        return f"บัญชีรับเงินของ {self.seller}"


class SellerSettlement(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "รอคำสั่งซื้อสำเร็จ"
        READY = "ready", "พร้อมโอนเงิน"
        PROCESSING = "processing", "กำลังโอนเงิน"
        TRANSFERRED = "transferred", "โอนเงินแล้ว"
        HELD = "held", "ระงับไว้ตรวจสอบ"
        FAILED = "failed", "โอนเงินไม่สำเร็จ"
        REVERSED = "reversed", "ยกเลิกรายการแล้ว"

    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="settlement")
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="settlements",
    )
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    fee_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    platform_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="thb")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    stripe_transfer_id = models.CharField(max_length=255, blank=True)
    available_at = models.DateTimeField(null=True, blank=True)
    transferred_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "ยอดเงินที่ต้องจ่ายผู้ขาย"
        verbose_name_plural = "ยอดเงินที่ต้องจ่ายผู้ขาย"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(gross_amount__gt=0), name="settlement_gross_positive"),
            models.CheckConstraint(condition=models.Q(fee_rate__gte=0, fee_rate__lte=100), name="settlement_fee_rate_valid"),
            models.CheckConstraint(condition=models.Q(platform_fee__gte=0), name="settlement_fee_nonnegative"),
            models.CheckConstraint(condition=models.Q(net_amount__gte=0), name="settlement_net_nonnegative"),
            models.CheckConstraint(condition=models.Q(platform_fee__lte=models.F("gross_amount")), name="settlement_fee_not_over_gross"),
            models.CheckConstraint(condition=models.Q(net_amount__lte=models.F("gross_amount")), name="settlement_net_not_over_gross"),
            models.UniqueConstraint(
                fields=["stripe_transfer_id"],
                condition=~models.Q(stripe_transfer_id=""),
                name="unique_nonblank_stripe_transfer",
            ),
        ]

    def __str__(self):
        return f"ยอดจ่าย {self.payment.order.reference} - {self.get_status_display()}"