from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from django.contrib.admin.sites import NotRegistered
from django.utils import timezone

from .admin_permissions import (
    CsvExportAdminMixin,
    OwnerOnlyAdminMixin,
    RoleScopedAdminMixin,
    staff_community,
)
from .services import deliver_email

from .models import (
    AuditEvent,
    Community,
    CommunityStaffProfile,
    DeliveryAddress,
    EmailDelivery,
    FarmerProfile,
    LoginAttempt,
    NewsPost,
    Notification,
    Report,
    ReportMessage,
    User,
)


try:
    admin.site.unregister(Group)
except NotRegistered:
    pass


@admin.register(User)
class CustomUserAdmin(CsvExportAdminMixin, RoleScopedAdminMixin, UserAdmin):
    staff_access = True
    staff_can_change = True
    community_filter = "farmer_profile__community"

    fieldsets = (
        ("ข้อมูลเข้าสู่ระบบ", {"fields": ("username", "password")}),
        (
            "ข้อมูลส่วนตัว",
            {
                "fields": (
                    "avatar",
                    "display_name",
                    "first_name",
                    "last_name",
                    "email",
                    "phone",
                    "gender",
                    "birth_date",
                )
            },
        ),
        ("สิทธิ์และสถานะบัญชี", {"fields": ("role", "is_active")}),
        (
            "การยืนยันและการยอมรับเงื่อนไข",
            {
                "fields": (
                    "email_verified_at",
                    "terms_accepted_at",
                    "privacy_accepted_at",
                    "terms_version",
                    "privacy_version",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "ประวัติบัญชี",
            {"fields": ("last_login", "date_joined"), "classes": ("collapse",)},
        ),
    )
    add_fieldsets = (
        (
            "สร้างบัญชีผู้ใช้",
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "password1",
                    "password2",
                    "role",
                    "display_name",
                    "email",
                    "phone",
                    "is_active",
                ),
            },
        ),
    )
    list_display = ("username", "display_name", "email", "role", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("username", "display_name", "email", "phone")
    ordering = ("-date_joined",)
    readonly_fields = (
        "last_login",
        "date_joined",
        "email_verified_at",
        "terms_accepted_at",
        "privacy_accepted_at",
        "terms_version",
        "privacy_version",
    )
    csv_filename = "members.csv"
    csv_export_fields = (
        ("username", "ชื่อผู้ใช้"),
        ("display_name", "ชื่อที่แสดง"),
        ("email", "อีเมล"),
        ("phone", "เบอร์โทรศัพท์"),
        ("role", "บทบาท"),
        ("is_active", "เปิดใช้งาน"),
        ("date_joined", "วันที่สมัคร"),
    )

    def get_fieldsets(self, request, obj=None):
        if not self._is_owner(request.user):
            return (
                (
                    "บัญชีเกษตรกรในชุมชน",
                    {
                        "fields": (
                            "username",
                            "avatar",
                            "display_name",
                            "first_name",
                            "last_name",
                            "email",
                            "phone",
                            "gender",
                            "birth_date",
                            "is_active",
                        )
                    },
                ),
            )
        return super().get_fieldsets(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if not self._is_owner(request.user):
            return ("username",)
        fields = list(super().get_readonly_fields(request, obj))
        if obj:
            fields.append("username")
        return tuple(dict.fromkeys(fields))


@admin.register(DeliveryAddress)
class DeliveryAddressAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "label",
        "recipient_name",
        "user",
        "province",
        "phone",
        "is_default",
        "updated_at",
    )
    list_filter = ("is_default", "province")
    search_fields = (
        "label",
        "recipient_name",
        "phone",
        "user__username",
        "user__display_name",
        "province",
        "postal_code",
    )
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("เจ้าของที่อยู่", {"fields": ("user", "label", "is_default")}),
        ("ข้อมูลผู้รับ", {"fields": ("recipient_name", "phone")}),
        (
            "ที่อยู่จัดส่ง",
            {
                "fields": (
                    "address_line",
                    "subdistrict",
                    "district",
                    "province",
                    "postal_code",
                )
            },
        ),
        (
            "ข้อมูลระบบ",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    def save_model(self, request, obj, form, change):
        if obj.is_default and obj.user_id:
            DeliveryAddress.objects.filter(
                user_id=obj.user_id,
                is_default=True,
            ).exclude(pk=obj.pk).update(is_default=False)
        super().save_model(request, obj, form, change)

@admin.register(Community)
class CommunityAdmin(RoleScopedAdminMixin, admin.ModelAdmin):
    staff_access = True
    community_filter = "pk"

    list_display = ("name", "province", "district", "is_active")
    list_filter = ("is_active", "province")
    search_fields = ("name", "province", "district")
    prepopulated_fields = {"slug": ("name",)}

    def get_readonly_fields(self, request, obj=None):
        if not self._is_owner(request.user):
            return tuple(field.name for field in self.model._meta.fields)
        return ("created_at", "updated_at")


@admin.register(FarmerProfile)
class FarmerProfileAdmin(CsvExportAdminMixin, RoleScopedAdminMixin, admin.ModelAdmin):
    staff_access = True
    staff_can_change = True
    community_filter = "community"

    list_display = ("farm_name", "user", "community", "verification_status")
    list_filter = ("verification_status", "community")
    search_fields = ("farm_name", "user__username", "user__email")
    csv_filename = "farmers.csv"
    csv_export_fields = (
        ("farm_name", "ชื่อฟาร์ม/ร้านค้า"),
        ("user__username", "ชื่อผู้ใช้"),
        ("community__name", "ชุมชน/สหกรณ์"),
        ("province", "จังหวัด"),
        ("district", "อำเภอ/เขต"),
        ("verification_status", "สถานะตรวจสอบ"),
        ("created_at", "วันที่สมัคร"),
    )
    readonly_fields = ("created_at", "updated_at", "verified_by", "verified_at")
    fieldsets = (
        ("ข้อมูลบัญชีและชุมชน", {"fields": ("user", "community")}),
        (
            "ข้อมูลฟาร์ม/ร้านค้า",
            {"fields": ("farm_name", "bio", "address", "province", "district")},
        ),
        (
            "เอกสารและผลการตรวจสอบ",
            {"fields": ("document_type", "verification_document", "verification_status", "rejection_reason", "verified_by", "verified_at")},
        ),
        ("ข้อมูลระบบ", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_readonly_fields(self, request, obj=None):
        if self._is_owner(request.user):
            return self.readonly_fields
        editable = {"verification_status", "rejection_reason"}
        return tuple(
            field.name
            for field in self.model._meta.fields
            if field.name not in editable
        )

    def save_model(self, request, obj, form, change):
        if "verification_status" in form.changed_data:
            obj.verified_by = request.user
            obj.verified_at = timezone.now()
            if obj.verification_status == FarmerProfile.VerificationStatus.VERIFIED:
                obj.rejection_reason = ""
        super().save_model(request, obj, form, change)


@admin.register(CommunityStaffProfile)
class CommunityStaffProfileAdmin(RoleScopedAdminMixin, admin.ModelAdmin):
    staff_access = True
    community_filter = "community"

    list_display = ("user", "community", "title")
    list_filter = ("community",)
    search_fields = ("user__username", "community__name")

    def get_readonly_fields(self, request, obj=None):
        if not self._is_owner(request.user):
            return ("user", "community", "title", "created_at")
        return ("created_at",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.user.role != User.Roles.COOPERATIVE_STAFF or obj.user.is_staff:
            obj.user.role = User.Roles.COOPERATIVE_STAFF
            obj.user.is_staff = False
            obj.user.save(update_fields=["role", "is_staff"])


@admin.register(Notification)
class NotificationAdmin(RoleScopedAdminMixin, admin.ModelAdmin):
    staff_access = True
    staff_can_add = True
    community_filter = "user__farmer_profile__community"

    list_display = ("title", "user", "is_read", "created_at")
    list_filter = ("is_read", "created_at")
    search_fields = ("title", "message", "user__username", "user__email")
    readonly_fields = ("created_at",)
    fieldsets = (
        ("ผู้รับการแจ้งเตือน", {"fields": ("user",)}),
        ("ข้อความแจ้งเตือน", {"fields": ("title", "message", "link")}),
        ("สถานะ", {"fields": ("is_read", "created_at")}),
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user" and not self._is_owner(request.user):
            community = staff_community(request.user)
            kwargs["queryset"] = User.objects.filter(
                role=User.Roles.FARMER,
                farmer_profile__community=community,
                is_active=True,
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(NewsPost)
class NewsPostAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("title", "audience", "is_published", "published_at", "created_by")
    list_filter = ("audience", "is_published", "published_at")
    search_fields = ("title", "summary", "body")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("เนื้อหาข่าว", {"fields": ("title", "slug", "summary", "body")}),
        ("การเผยแพร่", {"fields": ("audience", "is_published", "published_at")}),
        ("ข้อมูลระบบ", {"fields": ("created_by", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class ReportMessageInline(admin.TabularInline):
    model = ReportMessage
    extra = 0
    can_delete = False
    readonly_fields = ("sender", "message", "attachment", "created_at")

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_owner or request.user.is_cooperative_staff)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Report)
class ReportAdmin(CsvExportAdminMixin, RoleScopedAdminMixin, admin.ModelAdmin):
    staff_access = True
    staff_can_change = True
    community_filter = "community"

    list_display = (
        "id",
        "target_type",
        "reporter",
        "reported_user",
        "product",
        "status",
        "community",
        "created_at",
    )
    list_filter = ("target_type", "reason", "status", "community", "created_at")
    search_fields = (
        "reporter__username",
        "reported_user__username",
        "product__name",
        "details",
        "resolution_note",
    )
    readonly_fields = ("created_at", "updated_at", "handled_at")
    autocomplete_fields = (
        "reporter",
        "reported_user",
        "product",
        "order",
        "community",
        "handled_by",
    )
    inlines = [ReportMessageInline]
    csv_filename = "reports.csv"
    csv_export_fields = (
        ("id", "เลขรายงาน"),
        ("target_type", "ประเภทรายงาน"),
        ("reason", "เหตุผล"),
        ("reporter__username", "ผู้รายงาน"),
        ("reported_user__username", "สมาชิกที่ถูกรายงาน"),
        ("product__name", "สินค้า"),
        ("community__name", "ชุมชน/สหกรณ์"),
        ("status", "สถานะ"),
        ("created_at", "วันที่รายงาน"),
    )
    fieldsets = (
        ("ข้อมูลรายงาน", {"fields": ("reporter", "target_type", "reason", "details", "evidence")}),
        ("รายการที่เกี่ยวข้อง", {"fields": ("product", "reported_user", "order", "community")}),
        ("ผลการดำเนินการ", {"fields": ("status", "resolution_note", "handled_by", "handled_at")}),
        ("ข้อมูลระบบ", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_readonly_fields(self, request, obj=None):
        editable = {"status", "resolution_note"}
        return tuple(
            field.name
            for field in self.model._meta.fields
            if field.name not in editable
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_autocomplete_fields(self, request):
        if not self._is_owner(request.user):
            return ()
        return super().get_autocomplete_fields(request)

    def save_model(self, request, obj, form, change):
        if {"status", "resolution_note"}.intersection(form.changed_data):
            obj.handled_by = request.user
            obj.handled_at = timezone.now()
        super().save_model(request, obj, form, change)


@admin.register(LoginAttempt)
class LoginAttemptAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "identifier_hash",
        "failed_attempts",
        "blocked_until",
        "updated_at",
    )
    readonly_fields = (
        "identifier_hash",
        "ip_hash",
        "failed_attempts",
        "blocked_until",
        "updated_at",
    )
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "target_type", "target_id", "community")
    list_filter = ("action", "target_type", "community", "created_at")
    search_fields = ("actor__username", "target_type", "target_id", "description")
    readonly_fields = (
        "actor",
        "action",
        "target_type",
        "target_id",
        "description",
        "before",
        "after",
        "community",
        "ip_address",
        "created_at",
    )
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EmailDelivery)
class EmailDeliveryAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("subject", "to_email", "status", "attempts", "sent_at", "created_at")
    list_filter = ("status", "created_at", "sent_at")
    search_fields = ("subject", "to_email", "last_error")
    readonly_fields = (
        "user",
        "to_email",
        "subject",
        "body",
        "status",
        "attempts",
        "last_error",
        "next_attempt_at",
        "sent_at",
        "created_at",
        "updated_at",
    )
    actions = ("retry_selected_emails",)

    @admin.action(permissions=["view"], description="ส่งอีเมลที่เลือกอีกครั้ง")
    def retry_selected_emails(self, request, queryset):
        sent = 0
        failed = 0
        for delivery in queryset.exclude(status=EmailDelivery.Status.SENT):
            result = deliver_email(delivery)
            if result.status == EmailDelivery.Status.SENT:
                sent += 1
            else:
                failed += 1
        if sent:
            self.message_user(request, f"ส่งอีเมลสำเร็จ {sent} รายการ", messages.SUCCESS)
        if failed:
            self.message_user(
                request,
                f"ยังส่งอีเมลไม่สำเร็จ {failed} รายการ กรุณาตรวจรายละเอียดข้อผิดพลาด",
                messages.ERROR,
            )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False