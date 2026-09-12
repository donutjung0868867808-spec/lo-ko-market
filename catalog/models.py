from decimal import Decimal

from django.conf import settings
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone


def validate_image_size(upload):
    if upload and upload.size > settings.MAX_UPLOAD_SIZE:
        from django.core.exceptions import ValidationError
        raise ValidationError("รูปภาพมีขนาดใหญ่เกินกำหนด")


class ProductReview(models.Model):
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="product_reviews",
    )
    rating = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "รีวิวสินค้า"
        verbose_name_plural = "รีวิวสินค้า"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5),
                name="product_review_rating_between_1_and_5",
            ),
        ]

    def __str__(self):
        return f"รีวิวของ {self.user} ต่อ {self.product} ({self.rating})"


class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True)
    image = models.FileField(
        "รูปหมวดหมู่",
        upload_to="categories/",
        blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"]), validate_image_size],
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "หมวดสินค้า"
        verbose_name_plural = "หมวดสินค้า"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    class Unit(models.TextChoices):
        KG = "kg", "กิโลกรัม"
        PACK = "pack", "แพ็ก"
        BUNDLE = "bundle", "มัด"
        PIECE = "piece", "ชิ้น"
        BOX = "box", "กล่อง"

    class Status(models.TextChoices):
        DRAFT = "draft", "ฉบับร่าง"
        PENDING = "pending", "รออนุมัติ"
        ACTIVE = "active", "เปิดขาย"
        REJECTED = "rejected", "ไม่อนุมัติ"
        BLOCKED = "blocked", "ถูกบล็อก"
        ARCHIVED = "archived", "หยุดขาย"

    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="products",
    )
    community = models.ForeignKey(
        "accounts.Community",
        on_delete=models.PROTECT,
        related_name="products",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    name = models.CharField(max_length=180)
    sku = models.CharField(max_length=40, unique=True, null=True, blank=True)
    description = models.TextField()
    unit = models.CharField(max_length=20, choices=Unit.choices, default=Unit.KG)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    stock_quantity = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    minimum_order_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.50"),
        validators=[MinValueValidator(Decimal("0.50"))],
    )
    low_stock_threshold = models.DecimalField(
        max_digits=10, decimal_places=2, default=5, validators=[MinValueValidator(0)]
    )
    last_low_stock_notified_at = models.DateTimeField(null=True, blank=True)
    weight_grams = models.PositiveIntegerField(null=True, blank=True)
    image = models.FileField(
        upload_to="products/",
        blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"]), validate_image_size],
    )
    harvest_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    rejection_reason = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_products",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "สินค้าเกษตร"
        verbose_name_plural = "สินค้าเกษตร"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["community", "status"]),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(price__gt=0), name="product_price_positive"),
            models.CheckConstraint(condition=models.Q(stock_quantity__gte=0), name="product_stock_nonnegative"),
            models.CheckConstraint(condition=models.Q(minimum_order_quantity__gt=0), name="product_minimum_order_positive"),
            models.CheckConstraint(condition=models.Q(low_stock_threshold__gte=0), name="product_low_stock_nonnegative"),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)
        if creating and not self.sku:
            self.sku = f"AGP-{self.pk:07d}"
            super().save(update_fields=["sku"])

    def get_absolute_url(self):
        return reverse("catalog:product_detail", args=[self.pk])

    @property
    def average_rating(self):
        reviews = self.reviews.all()
        if not reviews.exists():
            return 0
        return round(sum(review.rating for review in reviews) / reviews.count(), 1)

    @classmethod
    def quantity_step_for_unit(cls, unit):
        return Decimal("0.50") if unit == cls.Unit.KG else Decimal("1.00")

    @property
    def quantity_step(self):
        return self.quantity_step_for_unit(self.unit)

    @property
    def is_available(self):
        return self.status == self.Status.ACTIVE and self.stock_quantity >= self.quantity_step

    def approve(self, staff_user):
        self.status = self.Status.ACTIVE
        self.approved_by = staff_user
        self.approved_at = timezone.now()
        self.rejection_reason = ""
        self.save(update_fields=["status", "approved_by", "approved_at", "rejection_reason"])

    def reject(self, staff_user, reason=""):
        self.status = self.Status.REJECTED
        self.approved_by = staff_user
        self.approved_at = timezone.now()
        self.rejection_reason = reason
        self.save(update_fields=["status", "approved_by", "approved_at", "rejection_reason"])

    def block(self, staff_user, reason=""):
        self.status = self.Status.BLOCKED
        self.approved_by = staff_user
        self.approved_at = timezone.now()
        self.rejection_reason = reason
        self.save(update_fields=["status", "approved_by", "approved_at", "rejection_reason"])

    def unblock(self, staff_user):
        self.status = self.Status.ACTIVE
        self.approved_by = staff_user
        self.approved_at = timezone.now()
        self.rejection_reason = ""
        self.save(update_fields=["status", "approved_by", "approved_at", "rejection_reason"])


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.FileField(
        upload_to="products/gallery/%Y/%m/",
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"]), validate_image_size],
    )
    alt_text = models.CharField(max_length=180, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "รูปภาพสินค้า"
        verbose_name_plural = "รูปภาพสินค้า"
        ordering = ["sort_order", "id"]


class StockMovement(models.Model):
    class MovementType(models.TextChoices):
        MANUAL = "manual", "ปรับสต็อก"
        RESERVE = "reserve", "จองสำหรับคำสั่งซื้อ"
        RELEASE = "release", "คืนสต็อก"
        SALE = "sale", "ขายสำเร็จ"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock_movements")
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )
    movement_type = models.CharField(max_length=20, choices=MovementType.choices)
    quantity_change = models.DecimalField(max_digits=10, decimal_places=2)
    balance_after = models.DecimalField(max_digits=10, decimal_places=2)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ประวัติสต็อก"
        verbose_name_plural = "ประวัติสต็อก"
        ordering = ["-created_at"]


class ProductFavorite(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorite_products",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="favorites",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "รายการสินค้าที่ถูกใจ"
        verbose_name_plural = "รายการสินค้าที่ถูกใจ"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "product"], name="unique_product_favorite"),
        ]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["product", "created_at"]),
        ]

    def __str__(self):
        return f"{self.user} ถูกใจ {self.product}"


class SellerFavorite(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorite_sellers",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="seller_favorited_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ร้านค้าที่ถูกใจ"
        verbose_name_plural = "ร้านค้าที่ถูกใจ"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "seller"], name="unique_seller_favorite"),
            models.CheckConstraint(condition=~models.Q(user=models.F("seller")), name="prevent_self_seller_favorite"),
        ]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["seller", "created_at"]),
        ]

    def __str__(self):
        return f"{self.user} ถูกใจร้าน {self.seller}"
