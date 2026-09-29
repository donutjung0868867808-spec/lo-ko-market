from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.fields.files import FieldFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image, UnidentifiedImageError


def validate_image_size(upload):
    if upload and upload.size > settings.MAX_UPLOAD_SIZE:
        raise ValidationError("รูปภาพมีขนาดใหญ่เกินกำหนด")


def validate_image_file(upload):
    """Allow supported image bytes even when the browser provides no extension."""
    if not upload or isinstance(upload, FieldFile):
        return

    position = upload.tell() if hasattr(upload, "tell") else 0
    try:
        upload.seek(0)
        image = Image.open(upload)
        image.verify()
        if image.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValidationError("รองรับเฉพาะรูป JPG, PNG และ WEBP")
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValidationError("ไฟล์ที่เลือกไม่ใช่รูปภาพที่ใช้งานได้") from exc
    finally:
        if hasattr(upload, "seek"):
            upload.seek(position)


REVIEW_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}
REVIEW_VIDEO_MAX_SIZE = 25 * 1024 * 1024


def validate_half_star_rating(value):
    try:
        rating = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValidationError("คะแนนรีวิวไม่ถูกต้อง") from error
    if rating < Decimal("0.5") or rating > Decimal("5.0") or (rating * 2) != (rating * 2).to_integral_value():
        raise ValidationError("คะแนนรีวิวต้องอยู่ระหว่าง 0.5 ถึง 5.0 และเพิ่มครั้งละ 0.5")


def review_media_type_for_upload(upload):
    """Return the supported media type without relying solely on a filename."""
    try:
        validate_image_file(upload)
        return "image"
    except ValidationError:
        pass

    filename = (getattr(upload, "name", "") or "").lower()
    content_type = (getattr(upload, "content_type", "") or "").lower()
    if (
        any(filename.endswith(extension) for extension in REVIEW_VIDEO_EXTENSIONS)
        and (not content_type or content_type.startswith("video/"))
    ):
        return "video"
    raise ValidationError("รองรับเฉพาะรูป JPG, PNG, WEBP และวิดีโอ MP4, MOV, WEBM")


def validate_review_media_file(upload):
    media_type = review_media_type_for_upload(upload)
    if media_type == "image":
        validate_image_size(upload)
    elif upload and upload.size > REVIEW_VIDEO_MAX_SIZE:
        raise ValidationError("วิดีโอมีขนาดใหญ่เกิน 25 MB")


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
    order_item = models.ForeignKey(
        "orders.OrderItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews",
    )
    rating = models.DecimalField(
        max_digits=2,
        decimal_places=1,
        default=Decimal("5.0"),
        validators=[MinValueValidator(Decimal("0.5")), MaxValueValidator(Decimal("5.0")), validate_half_star_rating],
    )
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "รีวิวสินค้า"
        verbose_name_plural = "รีวิวสินค้า"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=Decimal("0.5"), rating__lte=Decimal("5.0")),
                name="product_review_rating_between_1_and_5",
            ),
        ]

    def __str__(self):
        return f"รีวิวของ {self.user} ต่อ {self.product} ({self.rating})"


class ProductReviewMedia(models.Model):
    class MediaType(models.TextChoices):
        IMAGE = "image", "รูปภาพ"
        VIDEO = "video", "วิดีโอ"

    review = models.ForeignKey(
        ProductReview,
        on_delete=models.CASCADE,
        related_name="media",
    )
    file = models.FileField(
        "ไฟล์สื่อ",
        upload_to="reviews/%Y/%m/",
        validators=[validate_review_media_file],
    )
    media_type = models.CharField(
        "ประเภทสื่อ",
        max_length=10,
        choices=MediaType.choices,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "สื่อประกอบรีวิว"
        verbose_name_plural = "สื่อประกอบรีวิว"
        ordering = ["id"]


class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True)
    image = models.FileField(
        "รูปหมวดหมู่",
        upload_to="categories/",
        blank=True,
        validators=[validate_image_file, validate_image_size],
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "หมวดสินค้า"
        verbose_name_plural = "หมวดสินค้า"
        ordering = ["name"]

    def __str__(self):
        return self.name


class HomeSlide(models.Model):
    image = models.FileField(
        "ภาพสไลด์",
        upload_to="home-slides/",
        validators=[validate_image_file, validate_image_size],
    )
    alt_text = models.CharField("คำอธิบายภาพ", max_length=180, blank=True)
    sort_order = models.PositiveSmallIntegerField("ลำดับ", default=0)
    is_active = models.BooleanField("เปิดใช้งาน", default=True)

    class Meta:
        verbose_name = "ภาพสไลด์หน้าแรก"
        verbose_name_plural = "ภาพสไลด์หน้าแรก"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.alt_text or f"ภาพสไลด์ #{self.pk}"


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
    maximum_order_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.50"))],
        verbose_name="จำนวนสั่งซื้อสูงสุดต่อคำสั่งซื้อ",
    )
    low_stock_threshold = models.DecimalField(
        max_digits=10, decimal_places=2, default=5, validators=[MinValueValidator(0)]
    )
    last_low_stock_notified_at = models.DateTimeField(null=True, blank=True)
    weight_grams = models.PositiveIntegerField(null=True, blank=True)
    gtin = models.CharField(max_length=14, null=True, blank=True, verbose_name="รหัส GTIN")
    package_length_cm = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        verbose_name="ความยาวพัสดุ (ซม.)",
    )
    package_width_cm = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        verbose_name="ความกว้างพัสดุ (ซม.)",
    )
    package_height_cm = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        verbose_name="ความสูงพัสดุ (ซม.)",
    )
    preparation_days = models.PositiveSmallIntegerField(
        default=1,
        validators=[MaxValueValidator(14)],
        verbose_name="ระยะเวลาเตรียมสินค้า (วัน)",
    )
    image = models.FileField(
        "รูปภาพหลัก",
        upload_to="products/",
        blank=True,
        validators=[validate_image_file, validate_image_size],
        help_text="เลือกรูป JPG, PNG หรือ WEBP ได้ แม้ชื่อไฟล์ไม่มีนามสกุล",
    )
    size_chart_image = models.FileField(
        "รูปตารางขนาดสินค้า",
        upload_to="products/size-charts/%Y/%m/",
        blank=True,
        validators=[validate_image_file, validate_image_size],
        help_text="อัปโหลดรูปตารางขนาด (ถ้ามี)",
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
    def orderable_quantity(self):
        if self.maximum_order_quantity is None:
            return self.stock_quantity
        return min(self.stock_quantity, self.maximum_order_quantity)

    @property
    def is_available(self):
        return self.status == self.Status.ACTIVE and self.orderable_quantity >= self.quantity_step

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


class ProductSizeChartRow(models.Model):
    """A flexible measurement row shown to shoppers beside an optional chart image."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="size_chart_rows",
    )
    label = models.CharField("ขนาด/ตัวเลือก", max_length=60, help_text="เช่น S, M, L หรือ 500 กรัม")
    length_cm = models.DecimalField("ความยาว (ซม.)", max_digits=7, decimal_places=2, null=True, blank=True)
    width_cm = models.DecimalField("ความกว้าง (ซม.)", max_digits=7, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField("ความสูง (ซม.)", max_digits=7, decimal_places=2, null=True, blank=True)
    weight_grams = models.PositiveIntegerField("น้ำหนัก (กรัม)", null=True, blank=True)
    note = models.CharField("หมายเหตุ", max_length=160, blank=True)
    sort_order = models.PositiveSmallIntegerField("ลำดับ", default=0)

    class Meta:
        verbose_name = "แถวตารางขนาดสินค้า"
        verbose_name_plural = "ตารางขนาดสินค้า"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.product} - {self.label}"


class ProductVariant(models.Model):
    """A selectable product option, such as a colour, with its own display image."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="variants",
    )
    name = models.CharField(
        "ชื่อตัวเลือก",
        max_length=80,
        help_text="เช่น สีเหลือง, สีม่วง หรือ ขนาดใหญ่",
    )
    image = models.FileField(
        "รูปของตัวเลือก",
        upload_to="products/variants/%Y/%m/",
        blank=True,
        validators=[validate_image_file, validate_image_size],
    )
    stock_quantity = models.DecimalField(
        "จำนวนคงเหลือของตัวเลือก",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
                validators=[MinValueValidator(0)],
        help_text="ระบุจำนวนแยกสำหรับตัวเลือกนี้",
    )
    is_active = models.BooleanField("เปิดให้เลือก", default=True)
    sort_order = models.PositiveSmallIntegerField("ลำดับ", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "ตัวเลือกสินค้า"
        verbose_name_plural = "ตัวเลือกสินค้า"
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "name"],
                name="unique_product_variant_name",
            )
        ]

    def __str__(self):
        return f"{self.product.name} - {self.name}"


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.FileField(
        "รูปสินค้าเพิ่มเติม",
        upload_to="products/gallery/%Y/%m/",
        validators=[validate_image_file, validate_image_size],
    )
    alt_text = models.CharField(max_length=180, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "รูปภาพสินค้า"
        verbose_name_plural = "รูปภาพสินค้า"
        ordering = ["sort_order", "id"]


class ProductDetailImage(models.Model):
    class DisplaySize(models.TextChoices):
        SMALL = "small", "เล็ก"
        STANDARD = "standard", "มาตรฐาน"
        WIDE = "wide", "เต็มความกว้าง"
        FULL = "full", "เต็ม"

    """Images that illustrate the written product description, not the product gallery."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="detail_images")
    image = models.FileField(
        "รูปประกอบรายละเอียดสินค้า",
        upload_to="products/details/%Y/%m/",
        validators=[validate_image_file, validate_image_size],
    )
    display_size = models.CharField(max_length=12, choices=DisplaySize.choices, default=DisplaySize.STANDARD)
    alt_text = models.CharField(max_length=180, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "รูปประกอบรายละเอียดสินค้า"
        verbose_name_plural = "รูปประกอบรายละเอียดสินค้า"
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


class SellerStoreVisit(models.Model):
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="store_visits",
    )
    session_key = models.CharField(max_length=40)
    visited_on = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "สถิติผู้เยี่ยมชมร้าน"
        verbose_name_plural = "สถิติผู้เยี่ยมชมร้าน"
        constraints = [
            models.UniqueConstraint(
                fields=["seller", "session_key", "visited_on"],
                name="unique_daily_seller_store_visit",
            ),
        ]
        indexes = [
            models.Index(fields=["seller", "visited_on"]),
        ]


class ProductClick(models.Model):
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="product_clicks",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="clicks",
    )
    session_key = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "สถิติการเปิดดูสินค้า"
        verbose_name_plural = "สถิติการเปิดดูสินค้า"
        indexes = [
            models.Index(fields=["seller", "created_at"]),
            models.Index(fields=["product", "created_at"]),
        ]
