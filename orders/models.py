from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Coupon(models.Model):
    class DiscountType(models.TextChoices):
        FIXED = "fixed", "ลดเป็นจำนวนเงิน"
        PERCENT = "percent", "ลดเป็นเปอร์เซ็นต์"

    code = models.CharField("รหัสส่วนลด", max_length=40, unique=True)
    discount_type = models.CharField(
        "รูปแบบส่วนลด",
        max_length=20,
        choices=DiscountType.choices,
        default=DiscountType.FIXED,
    )
    value = models.DecimalField(
        "มูลค่าส่วนลด", max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    minimum_spend = models.DecimalField(
        "ยอดซื้อขั้นต่ำ", max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    starts_at = models.DateTimeField("เริ่มใช้", null=True, blank=True)
    expires_at = models.DateTimeField("หมดอายุ", null=True, blank=True)
    max_uses = models.PositiveIntegerField("จำนวนสิทธิ์สูงสุด", null=True, blank=True)
    is_active = models.BooleanField("เปิดใช้งาน", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "รหัสส่วนลด"
        verbose_name_plural = "รหัสส่วนลด"
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(condition=models.Q(value__gt=0), name="coupon_value_positive"),
            models.CheckConstraint(condition=models.Q(minimum_spend__gte=0), name="coupon_minimum_spend_nonnegative"),
            models.CheckConstraint(
                condition=~models.Q(discount_type="percent") | models.Q(value__lte=100),
                name="coupon_percent_at_most_100",
            ),
            models.CheckConstraint(
                condition=models.Q(max_uses__isnull=True) | models.Q(max_uses__gt=0),
                name="coupon_max_uses_positive",
            ),
        ]

    def __str__(self):
        return self.code

    def clean(self):
        super().clean()
        if self.discount_type == self.DiscountType.PERCENT and self.value > 100:
            raise ValidationError({"value": "ส่วนลดแบบเปอร์เซ็นต์ต้องไม่เกิน 100"})
        if self.starts_at and self.expires_at and self.expires_at <= self.starts_at:
            raise ValidationError({"expires_at": "วันหมดอายุต้องอยู่หลังวันเริ่มใช้"})

    def discount_for(self, subtotal):
        if self.discount_type == self.DiscountType.PERCENT:
            return min(subtotal * self.value / Decimal("100"), subtotal)
        return min(self.value, subtotal)


class Shipment(models.Model):
    order = models.OneToOneField("Order", on_delete=models.CASCADE, related_name="shipment")
    tracking_number = models.CharField(max_length=120)
    carrier_slug = models.CharField(max_length=120, blank=True)
    provider_id = models.CharField(max_length=128, blank=True, db_index=True)
    status = models.CharField(max_length=40, default="Pending")
    checkpoints = models.JSONField(default=list, blank=True)
    provider_updated_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def status_label(self):
        return {
            "Pending": "รอข้อมูลจากขนส่ง", "InfoReceived": "ขนส่งได้รับข้อมูลแล้ว",
            "InTransit": "อยู่ระหว่างขนส่ง", "OutForDelivery": "กำลังนำจ่าย",
            "AvailableForPickup": "รอรับที่จุดบริการ", "Delivered": "ขนส่งนำจ่ายแล้ว",
            "AttemptFail": "นำจ่ายไม่สำเร็จ", "Exception": "มีปัญหาในการจัดส่ง",
            "Expired": "ข้อมูลติดตามหมดอายุ",
        }.get(self.status, "กำลังตรวจสอบสถานะ")

    class Meta:
        verbose_name = "การติดตามพัสดุ"
        verbose_name_plural = "การติดตามพัสดุ"


class ShipmentEvent(models.Model):
    event_id = models.CharField(max_length=128, unique=True)
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name="events")
    received_at = models.DateTimeField(auto_now_add=True)


class ShippingRate(models.Model):
    province = models.CharField(
        "จังหวัด",
        max_length=120,
        unique=True,
        blank=True,
        help_text="เว้นว่างเพื่อใช้เป็นอัตราเริ่มต้นสำหรับจังหวัดที่ไม่มีกฎเฉพาะ",
    )
    base_fee = models.DecimalField(
        "ค่าจัดส่งเริ่มต้น",
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    fee_per_kg = models.DecimalField(
        "ค่าจัดส่งต่อกิโลกรัม",
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    free_shipping_threshold = models.DecimalField(
        "ยอดซื้อขั้นต่ำที่จัดส่งฟรี",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    is_active = models.BooleanField("เปิดใช้งาน", default=True)
    updated_at = models.DateTimeField("แก้ไขล่าสุด", auto_now=True)

    class Meta:
        verbose_name = "อัตราค่าจัดส่ง"
        verbose_name_plural = "อัตราค่าจัดส่ง"
        ordering = ["province"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(base_fee__gte=0),
                name="shipping_rate_base_fee_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(fee_per_kg__gte=0),
                name="shipping_rate_per_kg_nonnegative",
            ),
        ]

    def __str__(self):
        return self.province or "อัตราเริ่มต้น"

class Order(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "รอชำระเงิน"
        PAID = "paid", "ชำระเงินแล้ว"
        CONFIRMED = "confirmed", "ยืนยันคำสั่งซื้อ"
        PREPARING = "preparing", "กำลังเตรียมสินค้า"
        SHIPPED = "shipped", "จัดส่งแล้ว"
        COMPLETED = "completed", "สำเร็จ"
        CANCELLED = "cancelled", "ยกเลิก"
        REFUNDED = "refunded", "คืนเงินแล้ว"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "ยังไม่ชำระ"
        PROCESSING = "processing", "กำลังชำระ"
        PAID = "paid", "ชำระแล้ว"
        FAILED = "failed", "ชำระไม่สำเร็จ"
        REFUNDED = "refunded", "คืนเงินแล้ว"

    reference = models.CharField(max_length=24, unique=True, null=True, blank=True)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sales",
    )
    community = models.ForeignKey(
        "accounts.Community",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    coupon = models.ForeignKey(
        Coupon,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    coupon_code = models.CharField(max_length=40, blank=True)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING_PAYMENT,
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
    )
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    shipping_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    shipping_name = models.CharField(max_length=180)
    shipping_phone = models.CharField(max_length=30)
    shipping_address = models.TextField()
    shipping_province = models.CharField("จังหวัดจัดส่ง", max_length=120, blank=True, default="")
    shipping_postal_code = models.CharField("รหัสไปรษณีย์", max_length=10, blank=True, default="")
    note = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    stock_reserved = models.BooleanField(default=False)
    stock_released_at = models.DateTimeField(null=True, blank=True)
    shipping_carrier = models.CharField(max_length=120, blank=True)
    tracking_number = models.CharField(max_length=120, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "คำสั่งซื้อ"
        verbose_name_plural = "คำสั่งซื้อ"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["buyer", "created_at"]),
            models.Index(fields=["seller", "created_at"]),
            models.Index(fields=["community", "status"]),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(subtotal__gte=0), name="order_subtotal_nonnegative"),
            models.CheckConstraint(condition=models.Q(shipping_fee__gte=0), name="order_shipping_fee_nonnegative"),
            models.CheckConstraint(condition=models.Q(discount_amount__gte=0), name="order_discount_nonnegative"),
            models.CheckConstraint(condition=models.Q(total_amount__gte=0), name="order_total_nonnegative"),
        ]

    def __str__(self):
        return self.reference or f"คำสั่งซื้อ #{self.pk}"

    def save(self, *args, **kwargs):
        creating = self.pk is None
        if creating and not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=settings.ORDER_RESERVATION_MINUTES)
        super().save(*args, **kwargs)
        if creating and not self.reference:
            self.reference = f"AG-{self.created_at:%Y%m%d}-{self.pk:05d}"
            super().save(update_fields=["reference"])

    def legacy_label(self):
        return f"คำสั่งซื้อ #{self.pk}"

    def get_absolute_url(self):
        return reverse("orders:order_detail", args=[self.pk])

    def refresh_total(self):
        subtotal = sum((item.line_total for item in self.items.all()), Decimal("0.00"))
        self.subtotal = subtotal
        self.total_amount = max(subtotal + self.shipping_fee - self.discount_amount, Decimal("0.00"))
        self.save(update_fields=["subtotal", "total_amount", "updated_at"])

    def mark_paid(self):
        self.payment_status = self.PaymentStatus.PAID
        self.status = self.Status.PAID
        self.save(update_fields=["payment_status", "status", "updated_at"])

    @property
    def is_expired(self):
        return bool(
            self.expires_at
            and self.expires_at <= timezone.now()
            and self.payment_status != self.PaymentStatus.PAID
        )


class CouponRedemption(models.Model):
    coupon = models.ForeignKey(Coupon, on_delete=models.PROTECT, related_name="redemptions")
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="coupon_redemption")
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "การใช้รหัสส่วนลด"
        verbose_name_plural = "การใช้รหัสส่วนลด"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(discount_amount__gte=0),
                name="coupon_redemption_discount_nonnegative",
            ),
        ]


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    product_name = models.CharField(max_length=180)
    unit = models.CharField(max_length=20)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        verbose_name = "รายการสินค้าในคำสั่งซื้อ"
        verbose_name_plural = "รายการสินค้าในคำสั่งซื้อ"
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="order_item_quantity_positive"),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0), name="order_item_price_nonnegative"),
        ]

    def __str__(self):
        return f"{self.product_name} จำนวน {self.quantity}"

    @property
    def line_total(self):
        return self.quantity * self.unit_price


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_history")
    status = models.CharField(max_length=32, choices=Order.Status.choices)
    note = models.CharField(max_length=255, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_status_changes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ประวัติสถานะคำสั่งซื้อ"
        verbose_name_plural = "ประวัติสถานะคำสั่งซื้อ"
        ordering = ["created_at"]
