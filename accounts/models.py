from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from agri_market.storage import private_storage

from .validators import validate_private_document


def validate_file_size(upload):
    if upload and upload.size > settings.MAX_UPLOAD_SIZE:
        raise ValidationError("ไฟล์มีขนาดใหญ่เกินกำหนด")


AVATAR_MAX_SIZE = 1024 * 1024


def validate_avatar_size(upload):
    if upload and upload.size > AVATAR_MAX_SIZE:
        raise ValidationError("รูปโปรไฟล์ต้องมีขนาดไม่เกิน 1 MB")


class User(AbstractUser):
    class Roles(models.TextChoices):
        CONSUMER = "consumer", "ผู้บริโภคทั่วไป"
        FARMER = "farmer", "เกษตรกรชุมชน"
        COOPERATIVE_STAFF = "cooperative_staff", "เจ้าหน้าที่สหกรณ์/วิสาหกิจชุมชน"
        OWNER = "owner", "เจ้าของระบบ"

    class Gender(models.TextChoices):
        MALE = "male", "ชาย"
        FEMALE = "female", "หญิง"
        OTHER = "other", "อื่น ๆ"
        UNSPECIFIED = "unspecified", "ไม่ระบุ"

    avatar = models.FileField("รูปโปรไฟล์",
        upload_to="avatars/%Y/%m/",
        blank=True,
        validators=[
            FileExtensionValidator(["jpg", "jpeg", "png"]),
            validate_avatar_size,
        ],
    )
    birth_date = models.DateField("วันเกิด", null=True, blank=True)
    gender = models.CharField("เพศ",
        max_length=20,
        choices=Gender.choices,
        default=Gender.UNSPECIFIED,
    )
    role = models.CharField(
        max_length=32,
        choices=Roles.choices,
        default=Roles.CONSUMER,
    )
    display_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    privacy_accepted_at = models.DateTimeField(null=True, blank=True)
    terms_version = models.CharField(max_length=20, blank=True)
    privacy_version = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = "ผู้ใช้"
        verbose_name_plural = "ผู้ใช้"
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                condition=~models.Q(email=""),
                name="unique_nonblank_user_email_ci",
            ),
        ]

    def __str__(self):
        return self.display_name or self.get_full_name() or self.username

    def save(self, *args, **kwargs):
        admin_roles = {self.Roles.OWNER}
        if self.role in admin_roles:
            self.is_staff = True
        elif not self.is_superuser:
            self.is_staff = False
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and {"role", "is_superuser"}.intersection(update_fields):
            kwargs["update_fields"] = set(update_fields) | {"is_staff"}
        super().save(*args, **kwargs)

    @property
    def is_consumer(self):
        return self.role == self.Roles.CONSUMER

    @property
    def can_buy(self):
        return self.role in {self.Roles.CONSUMER, self.Roles.FARMER}

    @property
    def is_farmer(self):
        return self.role == self.Roles.FARMER

    @property
    def is_cooperative_staff(self):
        return self.role == self.Roles.COOPERATIVE_STAFF

    @property
    def is_owner(self):
        return self.role == self.Roles.OWNER or self.is_superuser

    @property
    def is_email_verified(self):
        return bool(self.email_verified_at)


class Community(models.Model):
    name = models.CharField("ชื่อชุมชน/สหกรณ์", max_length=180, unique=True)
    slug = models.SlugField("ชื่อย่อ URL", max_length=200, unique=True)
    province = models.CharField("จังหวัด", max_length=120)
    district = models.CharField("อำเภอ/เขต", max_length=120, blank=True)
    address = models.TextField("ที่อยู่", blank=True)
    description = models.TextField("รายละเอียด", blank=True)
    is_active = models.BooleanField("เปิดใช้งาน", default=True)
    created_at = models.DateTimeField("วันที่สร้าง", auto_now_add=True)
    updated_at = models.DateTimeField("วันที่แก้ไขล่าสุด", auto_now=True)

    class Meta:
        verbose_name = "ชุมชน/สหกรณ์"
        verbose_name_plural = "ชุมชน/สหกรณ์"
        ordering = ["name"]

    def __str__(self):
        return self.name


class FarmerProfile(models.Model):
    class DocumentType(models.TextChoices):
        NATIONAL_ID = "national_id", "บัตรประจำตัวประชาชน"
        FARM_REGISTRATION = "farm_registration", "ทะเบียนเกษตรกร"
        COMMUNITY_CERTIFICATE = "community_certificate", "หนังสือรับรองชุมชน"
        OTHER = "other", "เอกสารอื่น"

    class VerificationStatus(models.TextChoices):
        PENDING = "pending", "รอตรวจสอบ"
        VERIFIED = "verified", "ยืนยันแล้ว"
        REJECTED = "rejected", "ไม่ผ่านการตรวจสอบ"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="farmer_profile",
    )
    community = models.ForeignKey(
        Community,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="farmers",
    )
    farm_name = models.CharField(max_length=180)
    bio = models.TextField(blank=True)
    store_cover = models.FileField(
        "รูปปกหน้าร้าน",
        upload_to="store-covers/%Y/%m/",
        blank=True,
        validators=[
            FileExtensionValidator(["jpg", "jpeg", "png", "webp"]),
            validate_file_size,
        ],
    )
    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        default=DocumentType.FARM_REGISTRATION,
    )
    verification_document = models.FileField(
        upload_to="farmer-verification/%Y/%m/",
        storage=private_storage,
        blank=True,
        validators=[
            FileExtensionValidator(["pdf", "jpg", "jpeg", "png", "webp"]),
            validate_file_size,
            validate_private_document,
        ],
    )
    address = models.TextField("ที่อยู่", blank=True)
    province = models.CharField(max_length=120, blank=True)
    district = models.CharField("อำเภอ/เขต", max_length=120, blank=True)
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_farmers",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField("วันที่สร้าง", auto_now_add=True)
    updated_at = models.DateTimeField("วันที่แก้ไขล่าสุด", auto_now=True)

    class Meta:
        verbose_name = "ข้อมูลเกษตรกร"
        verbose_name_plural = "ข้อมูลเกษตรกร"
        ordering = ["farm_name"]

    def __str__(self):
        return self.farm_name

    @property
    def is_verified(self):
        return self.verification_status == self.VerificationStatus.VERIFIED

    def mark_verified(self, staff_user):
        self.verification_status = self.VerificationStatus.VERIFIED
        self.verified_by = staff_user
        self.verified_at = timezone.now()
        self.rejection_reason = ""
        self.save(update_fields=["verification_status", "verified_by", "verified_at", "rejection_reason"])


class StoreCoverSlide(models.Model):
    profile = models.ForeignKey(
        FarmerProfile,
        on_delete=models.CASCADE,
        related_name="store_cover_slides",
    )
    image = models.FileField(
        "รูปสไลด์หน้าร้าน",
        upload_to="store-cover-slides/%Y/%m/",
        validators=[
            FileExtensionValidator(["jpg", "jpeg", "png", "webp"]),
            validate_file_size,
        ],
    )
    sort_order = models.PositiveSmallIntegerField("ลำดับ", default=0)
    is_active = models.BooleanField("เปิดใช้งาน", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "รูปสไลด์หน้าร้าน"
        verbose_name_plural = "รูปสไลด์หน้าร้าน"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"รูปสไลด์ {self.profile.farm_name} #{self.pk}"


class DeliveryAddress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="delivery_addresses",
    )
    label = models.CharField("ชื่อที่อยู่", max_length=60, default="บ้าน")
    recipient_name = models.CharField("ชื่อผู้รับ", max_length=180)
    phone = models.CharField("เบอร์โทรศัพท์", max_length=30)
    address_line = models.CharField("บ้านเลขที่ ซอย ถนน", max_length=255)
    subdistrict = models.CharField("ตำบล/แขวง", max_length=120)
    district = models.CharField("อำเภอ/เขต", max_length=120)
    province = models.CharField("จังหวัด", max_length=120)
    postal_code = models.CharField("รหัสไปรษณีย์", max_length=5)
    is_default = models.BooleanField("ที่อยู่เริ่มต้น", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "ที่อยู่จัดส่ง"
        verbose_name_plural = "ที่อยู่จัดส่ง"
        ordering = ["-is_default", "-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_default=True),
                name="one_default_delivery_address_per_user",
            )
        ]
        indexes = [models.Index(fields=["user", "is_default"])]

    def __str__(self):
        return f"{self.label} - {self.recipient_name}"

    @property
    def full_address(self):
        return (
            f"{self.address_line} {self.subdistrict} {self.district} "
            f"{self.province} {self.postal_code}"
        )

class LoginAttempt(models.Model):
    identifier_hash = models.CharField(max_length=64)
    ip_hash = models.CharField(max_length=64)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    blocked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "การพยายามเข้าสู่ระบบ"
        verbose_name_plural = "การพยายามเข้าสู่ระบบ"
        constraints = [
            models.UniqueConstraint(
                fields=["identifier_hash", "ip_hash"],
                name="unique_login_attempt_source",
            )
        ]


class Notification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    link = models.CharField(max_length=500, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField("วันที่สร้าง", auto_now_add=True)

    class Meta:
        verbose_name = "การแจ้งเตือน"
        verbose_name_plural = "การแจ้งเตือน"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title



class NewsPost(models.Model):
    class Audience(models.TextChoices):
        ALL = "all", "ผู้ใช้ทั้งหมด"
        CONSUMERS = "consumers", "ผู้บริโภค"
        FARMERS = "farmers", "เกษตรกรชุมชน"
        STAFF = "staff", "เจ้าหน้าที่ชุมชน"

    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=240, unique=True)
    summary = models.TextField(blank=True)
    body = models.TextField()
    audience = models.CharField(
        max_length=20,
        choices=Audience.choices,
        default=Audience.ALL,
    )
    is_published = models.BooleanField(default=True)
    is_important = models.BooleanField(
        "ข่าวสำคัญ (ส่งอีเมล)",
        default=False,
        help_text="ส่งอีเมลถึงกลุ่มผู้อ่านเมื่อเผยแพร่ข่าวนี้",
    )
    published_at = models.DateTimeField(default=timezone.now)
    notified_at = models.DateTimeField(
        "แจ้งเตือนเมื่อ",
        null=True,
        blank=True,
        editable=False,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="news_posts",
    )
    created_at = models.DateTimeField("วันที่สร้าง", auto_now_add=True)
    updated_at = models.DateTimeField("วันที่แก้ไขล่าสุด", auto_now=True)

    class Meta:
        verbose_name = "ข่าวสาร"
        verbose_name_plural = "ข่าวสาร"
        ordering = ["-published_at", "-created_at"]
        indexes = [
            models.Index(fields=["is_published", "published_at"]),
            models.Index(fields=["audience", "is_published"]),
        ]

    def __str__(self):
        return self.title

    def is_visible_to(self, user):
        if not self.is_published:
            return bool(user.is_authenticated and user.is_owner)
        if self.audience == self.Audience.ALL:
            return True
        if not user.is_authenticated:
            return False
        return (
            (self.audience == self.Audience.CONSUMERS and user.is_consumer)
            or (self.audience == self.Audience.FARMERS and user.is_farmer)
            or (
                self.audience == self.Audience.STAFF
                and (user.is_cooperative_staff or user.is_owner)
            )
        )


class Report(models.Model):
    class TargetType(models.TextChoices):
        PRODUCT = "product", "สินค้า"
        SELLER = "seller", "ผู้ขาย"
        BUYER = "buyer", "ผู้ซื้อ"
        ORDER = "order", "คำสั่งซื้อ"
        CONVERSATION = "conversation", "บทสนทนา"

    class Reason(models.TextChoices):
        QUALITY = "quality", "ปัญหาคุณภาพสินค้า"
        FRAUD = "fraud", "น่าสงสัยหรือฉ้อโกง"
        ABUSE = "abuse", "พฤติกรรมไม่เหมาะสม"
        DELIVERY = "delivery", "ปัญหาการจัดส่ง"
        PAYMENT = "payment", "ปัญหาการชำระเงิน"
        OTHER = "other", "อื่น ๆ"

    class Status(models.TextChoices):
        OPEN = "open", "เปิดรายการ"
        REVIEWING = "reviewing", "กำลังตรวจสอบ"
        RESOLVED = "resolved", "จัดการแล้ว"
        DISMISSED = "dismissed", "ยกเลิกรายงาน"

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reports_submitted",
    )
    target_type = models.CharField(max_length=20, choices=TargetType.choices)
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
    )
    reported_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports_received",
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
    )
    conversation = models.ForeignKey(
        "Conversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
        verbose_name="บทสนทนาที่ถูกรายงาน",
    )
    community = models.ForeignKey(
        Community,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
    )
    reason = models.CharField(
        max_length=30,
        choices=Reason.choices,
        default=Reason.OTHER,
    )
    details = models.TextField()
    evidence = models.FileField(
        upload_to="report-evidence/%Y/%m/",
        storage=private_storage,
        blank=True,
        validators=[
            FileExtensionValidator(["pdf", "jpg", "jpeg", "png", "webp"]),
            validate_file_size,
            validate_private_document,
        ],
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports_handled",
    )
    handled_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)
    created_at = models.DateTimeField("วันที่สร้าง", auto_now_add=True)
    updated_at = models.DateTimeField("วันที่แก้ไขล่าสุด", auto_now=True)

    class Meta:
        verbose_name = "รายงานปัญหา"
        verbose_name_plural = "รายงานปัญหา"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["community", "status"]),
            models.Index(fields=["reporter", "created_at"]),
        ]

    def __str__(self):
        return f"รายงาน{self.get_target_type_display()} #{self.pk}"

    def infer_community(self):
        if self.product_id:
            return self.product.community
        if self.order_id:
            return self.order.community
        if self.reported_user_id:
            profile = getattr(self.reported_user, "farmer_profile", None)
            if profile and profile.community_id:
                return profile.community
        return None

    def save(self, *args, **kwargs):
        if not self.community_id:
            community = self.infer_community()
            if community:
                self.community = community
        super().save(*args, **kwargs)

    def resolve(self, staff_user, status=None, note=""):
        self.status = status or self.Status.RESOLVED
        self.handled_by = staff_user
        self.handled_at = timezone.now()
        self.resolution_note = note
        self.save(update_fields=["status", "handled_by", "handled_at", "resolution_note", "updated_at"])


class ReportMessage(models.Model):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="report_messages",
    )
    message = models.TextField()
    attachment = models.FileField(
        upload_to="report-messages/%Y/%m/",
        storage=private_storage,
        blank=True,
        validators=[
            FileExtensionValidator(["pdf", "jpg", "jpeg", "png", "webp"]),
            validate_file_size,
            validate_private_document,
        ],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ข้อความในรายงานปัญหา"
        verbose_name_plural = "ข้อความในรายงานปัญหา"
        ordering = ["created_at"]


class Conversation(models.Model):
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ผู้ซื้อ",
        on_delete=models.CASCADE,
        related_name="buyer_conversations",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ผู้ขาย",
        on_delete=models.CASCADE,
        related_name="seller_conversations",
    )
    product = models.ForeignKey(
        "catalog.Product",
        verbose_name="สินค้า",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="conversations",
    )
    order = models.ForeignKey(
        "orders.Order",
        verbose_name="คำสั่งซื้อที่เกี่ยวข้อง",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations",
    )
    created_at = models.DateTimeField("วันที่เริ่มสนทนา", auto_now_add=True)
    updated_at = models.DateTimeField("วันที่อัปเดตล่าสุด", auto_now=True)

    class Meta:
        verbose_name = "บทสนทนาผู้ซื้อและผู้ขาย"
        verbose_name_plural = "บทสนทนาผู้ซื้อและผู้ขาย"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["buyer", "seller", "product"],
                condition=models.Q(order__isnull=True),
                name="unique_general_buyer_seller_product_conversation",
            ),
            models.UniqueConstraint(
                fields=["buyer", "seller", "product", "order"],
                name="unique_order_buyer_seller_product_conversation",
            ),
            models.UniqueConstraint(
                fields=["buyer", "seller"],
                condition=models.Q(product__isnull=True, order__isnull=True),
                name="unique_general_buyer_seller_shop_conversation",
            ),
            models.CheckConstraint(
                condition=~models.Q(buyer=models.F("seller")),
                name="prevent_self_conversation",
            ),
        ]
        indexes = [
            models.Index(fields=["buyer", "updated_at"]),
            models.Index(fields=["seller", "updated_at"]),
        ]

    def __str__(self):
        subject = self.product or "สนทนาทั่วไปกับร้านค้า"
        return f"{self.buyer} - {self.seller}: {subject}"

    def other_participant(self, user):
        return self.seller if user.pk == self.buyer_id else self.buyer

    def clean(self):
        super().clean()
        if self.order_id:
            if self.order.buyer_id != self.buyer_id or self.order.seller_id != self.seller_id:
                raise ValidationError("คำสั่งซื้อนี้ไม่ตรงกับผู้เข้าร่วมบทสนทนา")
            if not self.order.items.filter(product_id=self.product_id).exists():
                raise ValidationError("สินค้าไม่อยู่ในคำสั่งซื้อที่เลือก")


class DirectMessage(models.Model):
    client_id = models.UUIDField(null=True, blank=True, editable=False)
    conversation = models.ForeignKey(
        Conversation,
        verbose_name="บทสนทนา",
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ผู้ส่ง",
        on_delete=models.CASCADE,
        related_name="direct_messages",
    )
    body = models.TextField("ข้อความ", max_length=2000)
    read_at = models.DateTimeField("วันที่อ่าน", null=True, blank=True)
    created_at = models.DateTimeField("วันที่ส่ง", auto_now_add=True)

    class Meta:
        verbose_name = "ข้อความระหว่างผู้ซื้อและผู้ขาย"
        verbose_name_plural = "ข้อความระหว่างผู้ซื้อและผู้ขาย"
        constraints = [models.UniqueConstraint(fields=["sender", "client_id"], name="direct_message_client_id")]
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["conversation", "read_at"]),
        ]

    def __str__(self):
        return f"ข้อความจาก {self.sender}"

    def clean(self):
        super().clean()
        if self.conversation_id and self.sender_id not in {
            self.conversation.buyer_id,
            self.conversation.seller_id,
        }:
            raise ValidationError("ผู้ส่งต้องเป็นผู้เข้าร่วมบทสนทนา")


class SupportTicket(models.Model):
    class Category(models.TextChoices):
        REFUND = "refund", "งานคืนเงิน/คืนสินค้า"
        ACCOUNT_SECURITY = "account_security", "บัญชีและความปลอดภัย"
        FINANCE_FEES = "finance_fees", "การเงิน/ค่าธรรมเนียม"
        GENERAL = "general", "คำถามทั่วไป"

    class Status(models.TextChoices):
        OPEN = "open", "รอผู้ดูแลตอบ"
        IN_PROGRESS = "in_progress", "กำลังดำเนินการ"
        RESOLVED = "resolved", "แก้ไขแล้ว"
        CLOSED = "closed", "ปิดคำขอ"

    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ผู้ขาย",
        on_delete=models.CASCADE,
        related_name="support_tickets",
    )
    community = models.ForeignKey(
        Community,
        verbose_name="ชุมชน/สหกรณ์",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_tickets",
    )
    category = models.CharField("หัวข้อ", max_length=30, choices=Category.choices)
    subject = models.CharField("เรื่องที่ต้องการสอบถาม", max_length=200)
    status = models.CharField("สถานะ", max_length=20, choices=Status.choices, default=Status.OPEN)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ผู้ดูแลที่รับเรื่อง",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_tickets_handled",
    )
    last_seller_message_at = models.DateTimeField(
        "ข้อความล่าสุดจากผู้ขาย",
        null=True,
        blank=True,
        editable=False,
    )
    last_admin_message_at = models.DateTimeField(
        "ข้อความล่าสุดจากผู้ดูแล",
        null=True,
        blank=True,
        editable=False,
    )
    admin_read_at = models.DateTimeField(
        "ผู้ดูแลอ่านล่าสุด",
        null=True,
        blank=True,
        editable=False,
    )
    seller_read_at = models.DateTimeField(
        "ผู้ขายอ่านล่าสุด",
        null=True,
        blank=True,
        editable=False,
    )
    created_at = models.DateTimeField("วันที่เปิดคำขอ", auto_now_add=True)
    updated_at = models.DateTimeField("อัปเดตล่าสุด", auto_now=True)

    class Meta:
        verbose_name = "คำขอถึงผู้ดูแล"
        verbose_name_plural = "คำขอถึงผู้ดูแล"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["seller", "status", "updated_at"]),
            models.Index(fields=["status", "updated_at"]),
            models.Index(fields=["status", "last_seller_message_at"]),
        ]

    def __str__(self):
        return f"#{self.pk} {self.subject}"

    @property
    def has_unread_for_admin(self):
        return bool(
            self.last_seller_message_at
            and (
                not self.admin_read_at
                or self.last_seller_message_at > self.admin_read_at
            )
        )

    @property
    def has_unread_for_seller(self):
        return bool(
            self.last_admin_message_at
            and (
                not self.seller_read_at
                or self.last_admin_message_at > self.seller_read_at
            )
        )


class SupportMessage(models.Model):
    client_id = models.UUIDField(null=True, blank=True, editable=False)
    ticket = models.ForeignKey(
        SupportTicket,
        verbose_name="คำขอ",
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ผู้ส่ง",
        on_delete=models.CASCADE,
        related_name="support_messages",
    )
    body = models.TextField("ข้อความ", max_length=3000)
    created_at = models.DateTimeField("วันที่ส่ง", auto_now_add=True)

    class Meta:
        verbose_name = "ข้อความถึงผู้ดูแล"
        verbose_name_plural = "ข้อความถึงผู้ดูแล"
        constraints = [models.UniqueConstraint(fields=["sender", "client_id"], name="support_message_client_id")]
        ordering = ["created_at"]
        indexes = [models.Index(fields=["ticket", "created_at"])]

    def clean(self):
        super().clean()
        if self.ticket_id and self.sender_id not in {self.ticket.seller_id, self.ticket.handled_by_id}:
            sender = self.sender
            if not sender.is_owner:
                raise ValidationError("ผู้ส่งไม่มีสิทธิ์ตอบคำขอนี้")

    def __str__(self):
        return f"ข้อความคำขอ #{self.ticket_id} จาก {self.sender}"

class ChatBlock(models.Model):
    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ผู้บล็อก",
        on_delete=models.CASCADE,
        related_name="chat_blocks_created",
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ผู้ถูกบล็อก",
        on_delete=models.CASCADE,
        related_name="chat_blocks_received",
    )
    created_at = models.DateTimeField("วันที่บล็อก", auto_now_add=True)

    class Meta:
        verbose_name = "การบล็อกบทสนทนา"
        verbose_name_plural = "การบล็อกบทสนทนา"
        constraints = [
            models.UniqueConstraint(fields=["blocker", "blocked"], name="unique_chat_block"),
            models.CheckConstraint(
                condition=~models.Q(blocker=models.F("blocked")),
                name="prevent_self_chat_block",
            ),
        ]
        indexes = [models.Index(fields=["blocker", "blocked"])]

    def __str__(self):
        return f"{self.blocker} บล็อก {self.blocked}"


class CommunityStaffProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="community_staff_profile",
    )
    community = models.ForeignKey(
        Community,
        on_delete=models.PROTECT,
        related_name="staff_members",
    )
    title = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField("วันที่สร้าง", auto_now_add=True)

    class Meta:
        verbose_name = "เจ้าหน้าที่ชุมชน"
        verbose_name_plural = "เจ้าหน้าที่ชุมชน"
        ordering = ["community__name", "user__username"]

    def __str__(self):
        return f"{self.user} - {self.community}"


class EmailDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "รอส่ง"
        SENT = "sent", "ส่งแล้ว"
        FAILED = "failed", "ส่งไม่สำเร็จ"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_deliveries",
    )
    to_email = models.EmailField()
    subject = models.CharField(max_length=255)
    body = models.TextField()
    html_body = models.TextField("เนื้อหาอีเมล HTML", blank=True)
    expires_at = models.DateTimeField("หมดอายุเมื่อ", null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "อีเมลที่ระบบส่ง"
        verbose_name_plural = "อีเมลที่ระบบส่ง"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "next_attempt_at"]),
            models.Index(fields=["to_email", "created_at"]),
        ]

    def __str__(self):
        return f"{self.subject} - {self.to_email}"


class AuditEvent(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", "สร้างข้อมูล"
        UPDATE = "update", "แก้ไขข้อมูล"
        APPROVE = "approve", "อนุมัติ"
        REJECT = "reject", "ปฏิเสธ"
        BLOCK = "block", "ระงับ"
        UNBLOCK = "unblock", "ปลดระงับ"
        STATUS = "status", "เปลี่ยนสถานะ"
        REFUND = "refund", "คืนเงิน"
        DOWNLOAD = "download", "ดาวน์โหลดเอกสาร"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    target_type = models.CharField(max_length=100)
    target_id = models.CharField(max_length=100, blank=True)
    description = models.CharField(max_length=255, blank=True)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    community = models.ForeignKey(
        Community,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "บันทึกการตรวจสอบ"
        verbose_name_plural = "บันทึกการตรวจสอบ"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["actor", "created_at"]),
            models.Index(fields=["community", "created_at"]),
        ]

    def __str__(self):
        return f"{self.get_action_display()} {self.target_type} {self.target_id}"
