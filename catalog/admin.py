from django.contrib import admin
from django.utils import timezone

from accounts.admin_permissions import CsvExportAdminMixin, OwnerOnlyAdminMixin, RoleScopedAdminMixin

from .models import (
    Category,
    Product,
    ProductFavorite,
    ProductImage,
    ProductReview,
    SellerFavorite,
    StockMovement,
)


@admin.register(Category)
class CategoryAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_owner or request.user.is_cooperative_staff)

    def has_add_permission(self, request, obj=None):
        return request.user.is_owner

    def has_change_permission(self, request, obj=None):
        return request.user.is_owner

    def has_delete_permission(self, request, obj=None):
        return request.user.is_owner


class StockMovementInline(admin.TabularInline):
    model = StockMovement
    extra = 0
    can_delete = False
    readonly_fields = (
        "movement_type",
        "quantity_change",
        "balance_after",
        "order",
        "note",
        "created_at",
    )

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_owner or request.user.is_cooperative_staff)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Product)
class ProductAdmin(CsvExportAdminMixin, RoleScopedAdminMixin, admin.ModelAdmin):
    staff_access = True
    staff_can_change = True
    community_filter = "community"

    list_display = (
        "name",
        "seller",
        "community",
        "price",
        "stock_quantity",
        "status",
    )
    list_filter = ("status", "community", "category")
    search_fields = ("name", "sku", "seller__username", "community__name")
    autocomplete_fields = ("seller", "community", "category", "approved_by")
    csv_filename = "products.csv"
    csv_export_fields = (
        ("sku", "รหัสสินค้า"),
        ("name", "ชื่อสินค้า"),
        ("seller__username", "ผู้ขาย"),
        ("community__name", "ชุมชน/สหกรณ์"),
        ("category__name", "หมวดสินค้า"),
        ("price", "ราคา"),
        ("stock_quantity", "จำนวนคงเหลือ"),
        ("unit", "หน่วย"),
        ("status", "สถานะ"),
        ("created_at", "วันที่เพิ่มสินค้า"),
    )
    readonly_fields = (
        "sku",
        "approved_by",
        "approved_at",
        "created_at",
        "updated_at",
        "last_low_stock_notified_at",
    )
    fieldsets = (
        (
            "ข้อมูลสินค้า",
            {"fields": ("name", "sku", "seller", "community", "category", "description", "image")},
        ),
        (
            "ราคาและสต็อก",
            {"fields": ("unit", "price", "stock_quantity", "minimum_order_quantity", "low_stock_threshold", "weight_grams", "last_low_stock_notified_at")},
        ),
        ("วันที่สำคัญของสินค้า", {"fields": ("harvest_date", "expiry_date")}),
        (
            "การตรวจสอบและการขาย",
            {"fields": ("status", "rejection_reason", "approved_by", "approved_at")},
        ),
        ("ข้อมูลระบบ", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    inlines = [ProductImageInline, StockMovementInline]
    actions = ("approve_selected", "block_selected", "unblock_selected", "export_as_csv")

    def get_readonly_fields(self, request, obj=None):
        if self._is_owner(request.user):
            fields = list(self.readonly_fields)
            if obj:
                fields.extend(("seller", "community"))
            return tuple(fields)
        editable = {"status", "rejection_reason"}
        return tuple(
            field.name
            for field in self.model._meta.fields
            if field.name not in editable
        )

    def get_autocomplete_fields(self, request):
        if not self._is_owner(request.user):
            return ()
        return super().get_autocomplete_fields(request)

    def get_inlines(self, request, obj):
        if not self._is_owner(request.user):
            return [StockMovementInline]
        return super().get_inlines(request, obj)

    def save_model(self, request, obj, form, change):
        if "status" in form.changed_data:
            obj.approved_by = request.user
            obj.approved_at = timezone.now()
            if obj.status == Product.Status.ACTIVE:
                obj.rejection_reason = ""
        super().save_model(request, obj, form, change)

    @admin.action(description="อนุมัติสินค้าที่เลือก")
    def approve_selected(self, request, queryset):
        count = 0
        for product in queryset:
            product.approve(request.user)
            count += 1
        self.message_user(request, f"อนุมัติสินค้าแล้ว {count} รายการ")

    @admin.action(description="บล็อกสินค้าที่เลือก")
    def block_selected(self, request, queryset):
        count = 0
        for product in queryset:
            product.block(request.user, "บล็อกโดยเจ้าหน้าที่ผ่านระบบจัดการ")
            count += 1
        self.message_user(request, f"บล็อกสินค้าแล้ว {count} รายการ")

    @admin.action(description="ปลดบล็อกสินค้าที่เลือก")
    def unblock_selected(self, request, queryset):
        count = 0
        for product in queryset:
            product.unblock(request.user)
            count += 1
        self.message_user(request, f"ปลดบล็อกสินค้าแล้ว {count} รายการ")


@admin.register(ProductReview)
class ProductReviewAdmin(RoleScopedAdminMixin, admin.ModelAdmin):
    staff_access = True
    community_filter = "product__community"

    list_display = ("product", "user", "rating", "created_at")
    list_filter = ("rating", "created_at")
    search_fields = ("product__name", "user__username", "comment")
    readonly_fields = ("product", "user", "rating", "comment", "created_at")
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ProductFavorite)
class ProductFavoriteAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("user", "product", "created_at")
    search_fields = ("user__username", "product__name")
    readonly_fields = ("user", "product", "created_at")
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SellerFavorite)
class SellerFavoriteAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("user", "seller", "created_at")
    search_fields = (
        "user__username",
        "seller__username",
        "seller__display_name",
    )
    readonly_fields = ("user", "seller", "created_at")
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
