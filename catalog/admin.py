from django.contrib import admin
from django import forms
from django.db.models import Prefetch
from django.utils.html import format_html
from django.utils import timezone

from accounts.admin_permissions import CsvExportAdminMixin, OwnerOnlyAdminMixin, RoleScopedAdminMixin

from .models import (
    Category,
    HomeSlide,
    Product,
    ProductFavorite,
    ProductImage,
    ProductReview,
    SellerFavorite,
    StockMovement,
)


class CategoryAdminForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = "__all__"
        widgets = {
            "image": forms.ClearableFileInput(
                attrs={
                    "data-admin-image-input": "true",
                    "data-image-picker-title": "เลือกรูปหมวดสินค้า",
                }
            ),
        }

    class Media:
        css = {"all": ("admin/category-image-upload.css",)}
        js = ("admin/category-image-upload.js",)


@admin.register(Category)
class CategoryAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    form = CategoryAdminForm
    list_display = ("category_thumbnail", "name", "slug", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(description="รูปปก")
    def category_thumbnail(self, category):
        if not category.image:
            return "ไม่มีรูป"
        return format_html(
            '<img src="{}" alt="" style="width:48px;height:48px;object-fit:cover;border-radius:6px;">',
            category.image.url,
        )


class HomeSlideAdminForm(forms.ModelForm):
    class Meta:
        model = HomeSlide
        fields = "__all__"
        widgets = {
            "image": forms.ClearableFileInput(
                attrs={
                    "data-admin-image-input": "true",
                    "data-image-picker-title": "เลือกรูปสไลด์หน้าแรก",
                    "data-image-crop-aspect": "3.25",
                }
            ),
        }

    class Media:
        css = {"all": ("admin/category-image-upload.css",)}
        js = ("admin/category-image-upload.js",)


@admin.register(HomeSlide)
class HomeSlideAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    form = HomeSlideAdminForm
    list_display = ("slide_thumbnail", "alt_text", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("alt_text",)

    @admin.display(description="ตัวอย่างภาพ")
    def slide_thumbnail(self, slide):
        return format_html(
            '<img src="{}" alt="" style="width:96px;height:56px;object-fit:cover;border-radius:6px;">',
            slide.image.url,
        )


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
        "product_thumbnail",
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
        "product_image_preview",
        "approved_by",
        "approved_at",
        "created_at",
        "updated_at",
        "last_low_stock_notified_at",
    )
    fieldsets = (
        (
            "ข้อมูลสินค้า",
            {"fields": ("name", "sku", "seller", "community", "category", "description", "product_image_preview", "image")},
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

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related(
            Prefetch(
                "images",
                queryset=ProductImage.objects.only("id", "product_id", "image").order_by("sort_order", "id"),
                to_attr="admin_gallery_images",
            )
        )

    @admin.display(description="รูปสินค้า")
    def product_thumbnail(self, product):
        if product.image:
            image_url = product.image.url
        elif product.admin_gallery_images:
            image_url = product.admin_gallery_images[0].image.url
        else:
            return "ไม่มีรูป"
        return format_html(
            '<img src="{}" alt="" style="height: 48px; width: 48px; border: 1px solid #d1d5db; border-radius: 6px; object-fit: cover;" loading="lazy">',
            image_url,
        )

    @admin.display(description="ตัวอย่างรูปสินค้า")
    def product_image_preview(self, product):
        if not product:
            return "บันทึกสินค้าแล้วจึงเพิ่มรูปได้"
        if product.image:
            image_url = product.image.url
        elif getattr(product, "admin_gallery_images", []):
            image_url = product.admin_gallery_images[0].image.url
        else:
            return "ยังไม่มีรูปสินค้า"
        return format_html(
            '<img src="{}" alt="รูปสินค้า {}" style="max-height:180px;max-width:280px;border:1px solid #d1d5db;border-radius:6px;object-fit:cover;" loading="lazy">',
            image_url,
            product.name,
        )

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
        ) + ("product_image_preview",)

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

    list_display = ("user_avatar", "product_thumbnail", "product", "user", "rating", "created_at")
    list_filter = ("rating", "created_at")
    search_fields = ("product__name", "user__username", "comment")
    readonly_fields = ("product", "user", "rating", "comment", "created_at")
    actions = None

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("product", "user").prefetch_related(
            Prefetch(
                "product__images",
                queryset=ProductImage.objects.only("id", "product_id", "image").order_by("sort_order", "id"),
                to_attr="review_gallery_images",
            )
        )

    @admin.display(description="รูปสินค้า")
    def product_thumbnail(self, review):
        product = review.product
        if product.image:
            image_url = product.image.url
        elif product.review_gallery_images:
            image_url = product.review_gallery_images[0].image.url
        else:
            return "ไม่มีรูป"
        return format_html(
            '<img src="{}" alt="" style="height:48px;width:48px;border:1px solid #d1d5db;border-radius:6px;object-fit:cover;" loading="lazy">',
            image_url,
        )

    @admin.display(description="รูปโปรไฟล์")
    def user_avatar(self, review):
        user = review.user
        if user.avatar:
            return format_html(
                '<img src="{}" alt="" style="height:40px;width:40px;border:1px solid #d1d5db;border-radius:9999px;object-fit:cover;" loading="lazy">',
                user.avatar.url,
            )
        return format_html(
            '<span style="display:grid;height:40px;width:40px;place-items:center;border-radius:9999px;background:#e8f3e9;color:#276f20;font-weight:800;">{}</span>',
            (user.get_username()[:1] or "?").upper(),
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ProductFavorite)
class ProductFavoriteAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("user_avatar", "user", "product_thumbnail", "product", "created_at")
    search_fields = ("user__username", "product__name")
    readonly_fields = ("user", "product", "created_at")
    actions = None

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "product").prefetch_related(
            Prefetch(
                "product__images",
                queryset=ProductImage.objects.only("id", "product_id", "image").order_by("sort_order", "id"),
                to_attr="favorite_gallery_images",
            )
        )

    @admin.display(description="รูปสินค้า")
    def product_thumbnail(self, favorite):
        product = favorite.product
        if product.image:
            image_url = product.image.url
        elif product.favorite_gallery_images:
            image_url = product.favorite_gallery_images[0].image.url
        else:
            return "ไม่มีรูป"
        return format_html(
            '<img src="{}" alt="" style="height:48px;width:48px;border:1px solid #d1d5db;border-radius:6px;object-fit:cover;" loading="lazy">',
            image_url,
        )

    @admin.display(description="รูปโปรไฟล์")
    def user_avatar(self, favorite):
        user = favorite.user
        if user.avatar:
            return format_html(
                '<img src="{}" alt="" style="height:40px;width:40px;border:1px solid #d1d5db;border-radius:9999px;object-fit:cover;" loading="lazy">',
                user.avatar.url,
            )
        return format_html(
            '<span style="display:grid;height:40px;width:40px;place-items:center;border-radius:9999px;background:#e8f3e9;color:#276f20;font-weight:800;">{}</span>',
            (user.get_username()[:1] or "?").upper(),
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SellerFavorite)
class SellerFavoriteAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("user_avatar", "user", "seller_avatar", "seller", "created_at")
    list_select_related = ("user", "seller")
    search_fields = (
        "user__username",
        "seller__username",
        "seller__display_name",
    )
    readonly_fields = ("user", "seller", "created_at")
    actions = None

    @admin.display(description="รูปผู้ใช้")
    def user_avatar(self, favorite):
        return self._avatar(favorite.user)

    @admin.display(description="รูปผู้ขาย")
    def seller_avatar(self, favorite):
        return self._avatar(favorite.seller)

    @staticmethod
    def _avatar(user):
        if user.avatar:
            return format_html(
                '<img src="{}" alt="" style="height:40px;width:40px;border:1px solid #d1d5db;border-radius:9999px;object-fit:cover;" loading="lazy">',
                user.avatar.url,
            )
        return format_html(
            '<span style="display:grid;height:40px;width:40px;place-items:center;border-radius:9999px;background:#e8f3e9;color:#276f20;font-weight:800;">{}</span>',
            (user.get_username()[:1] or "?").upper(),
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
