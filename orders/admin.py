from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from accounts.admin_permissions import CsvExportAdminMixin, OwnerOnlyAdminMixin, RoleScopedAdminMixin

from .models import Order, OrderItem, OrderStatusHistory, Shipment, ShipmentEvent, ShippingRate
from .services import ALLOWED_STATUS_TRANSITIONS, change_order_status


@admin.register(ShippingRate)
class ShippingRateAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "province_label",
        "base_fee",
        "fee_per_kg",
        "free_shipping_threshold",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active",)
    search_fields = ("province",)

    @admin.display(description="จังหวัด", ordering="province")
    def province_label(self, obj):
        return obj.province or "ทุกจังหวัดที่ไม่มีกฎเฉพาะ"


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = (
        "product_thumbnail",
        "product",
        "product_name",
        "unit",
        "quantity",
        "unit_price",
    )

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_owner or request.user.is_cooperative_staff)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="รูปสินค้า")
    def product_thumbnail(self, item):
        if not item.product or not item.product.image:
            return "ไม่มีรูป"
        return format_html(
            '<img src="{}" alt="" style="height: 40px; width: 40px; border: 1px solid #d1d5db; border-radius: 6px; object-fit: cover;" loading="lazy">',
            item.product.image.url,
        )


class OrderStatusHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    can_delete = False
    readonly_fields = ("status", "note", "changed_by", "created_at")

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_owner or request.user.is_cooperative_staff)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ShipmentEventInline(admin.TabularInline):
    model = ShipmentEvent
    extra = 0
    can_delete = False
    readonly_fields = ("event_id", "received_at")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Shipment)
class ShipmentAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "order_reference",
        "buyer",
        "seller",
        "tracking_number",
        "status_label",
        "carrier_slug",
        "attempts",
        "next_sync_at",
        "provider_updated_at",
        "updated_at",
    )
    list_filter = ("status", "carrier_slug", "updated_at")
    search_fields = (
        "order__reference",
        "order__buyer__username",
        "order__seller__username",
        "tracking_number",
        "provider_id",
    )
    list_select_related = ("order", "order__buyer", "order__seller")
    readonly_fields = (
        "order",
        "tracking_number",
        "carrier_slug",
        "provider_id",
        "status",
        "status_label",
        "checkpoint_timeline",
        "attempts",
        "last_error",
        "next_sync_at",
        "provider_updated_at",
        "updated_at",
    )
    fieldsets = (
        ("คำสั่งซื้อ", {"fields": ("order",)}),
        ("ข้อมูลพัสดุ", {"fields": ("tracking_number", "carrier_slug", "provider_id", "status", "status_label")} ),
        ("จุดติดตาม", {"fields": ("checkpoint_timeline",)}),
        ("การเชื่อมต่อ AfterShip", {"fields": ("attempts", "last_error", "next_sync_at")}),
        ("วันเวลา", {"fields": ("provider_updated_at", "updated_at")} ),
    )
    inlines = [ShipmentEventInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="เลขคำสั่งซื้อ", ordering="order__reference")
    def order_reference(self, shipment):
        return shipment.order.reference

    @admin.display(description="ผู้ซื้อ", ordering="order__buyer__username")
    def buyer(self, shipment):
        return shipment.order.buyer

    @admin.display(description="ผู้ขาย", ordering="order__seller__username")
    def seller(self, shipment):
        return shipment.order.seller

    @admin.display(description="สถานะขนส่ง", ordering="status")
    def status_label(self, shipment):
        return shipment.status_label

    @admin.display(description="จุดติดตามล่าสุด")
    def checkpoint_timeline(self, shipment):
        if not shipment.checkpoints:
            return "ยังไม่มีข้อมูลติดตามจากผู้ให้บริการ"
        return format_html_join(
            "<br>",
            "<strong>{}</strong> {} <span style=\color:#64748b\>{}</span>",
            (
                (point.get("time", ""), point.get("message", ""), point.get("location", ""))
                for point in reversed(shipment.checkpoints)
            ),
        )


class OrderAdminForm(forms.ModelForm):
    status_note = forms.CharField(
        label="บันทึกการเปลี่ยนสถานะ",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="ข้อความนี้จะถูกเก็บในประวัติคำสั่งซื้อและใช้ประกอบการแจ้งเตือน",
    )

    class Meta:
        model = Order
        fields = ("status", "shipping_carrier", "tracking_number")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            return
        allowed = set(ALLOWED_STATUS_TRANSITIONS.get(self.instance.status, set()))
        if self.instance.payment_status == Order.PaymentStatus.PAID:
            allowed.discard(Order.Status.CANCELLED)
        visible_statuses = {self.instance.status, *allowed}
        self.fields["status"].choices = [
            choice for choice in Order.Status.choices if choice[0] in visible_statuses
        ]

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk:
            return cleaned

        new_status = cleaned.get("status")
        current_status = self.instance.status
        carrier = (cleaned.get("shipping_carrier") or "").strip()
        tracking = (cleaned.get("tracking_number") or "").strip()
        if new_status != current_status:
            allowed = ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
            if new_status not in allowed:
                self.add_error("status", "ไม่สามารถเปลี่ยนไปยังสถานะที่เลือกได้")
            if (
                new_status == Order.Status.CANCELLED
                and self.instance.payment_status == Order.PaymentStatus.PAID
            ):
                self.add_error("status", "คำสั่งซื้อที่ชำระแล้วต้องคืนเงินก่อนยกเลิก")
            if new_status == Order.Status.SHIPPED:
                if not carrier:
                    self.add_error("shipping_carrier", "กรุณาระบุบริษัทขนส่ง")
                if not tracking:
                    self.add_error("tracking_number", "กรุณาระบุหมายเลขติดตามพัสดุ")
        elif {"shipping_carrier", "tracking_number"}.intersection(self.changed_data):
            if current_status != Order.Status.SHIPPED:
                self.add_error(
                    "shipping_carrier",
                    "แก้ไขข้อมูลขนส่งได้เมื่อคำสั่งซื้ออยู่ในสถานะจัดส่งแล้ว",
                )
        return cleaned


@admin.register(Order)
class OrderAdmin(CsvExportAdminMixin, RoleScopedAdminMixin, admin.ModelAdmin):
    staff_access = True
    community_filter = "community"
    form = OrderAdminForm

    list_display = (
        "reference",
        "buyer",
        "seller",
        "community",
        "status",
        "payment_status",
        "shipment_status",
        "total_amount",
        "created_at",
    )
    list_filter = ("status", "payment_status", "community")
    search_fields = (
        "reference",
        "buyer__username",
        "seller__username",
        "shipping_name",
        "shipping_phone",
        "tracking_number",
        "shipment_status",
    )
    list_select_related = ("buyer", "seller", "community")
    inlines = [OrderItemInline, OrderStatusHistoryInline]
    csv_filename = "orders.csv"
    csv_export_fields = (
        ("reference", "เลขคำสั่งซื้อ"),
        ("buyer__username", "ผู้ซื้อ"),
        ("seller__username", "ผู้ขาย"),
        ("community__name", "ชุมชน/สหกรณ์"),
        ("status", "สถานะคำสั่งซื้อ"),
        ("payment_status", "สถานะชำระเงิน"),
        ("subtotal", "ยอดสินค้า"),
        ("shipping_fee", "ค่าจัดส่ง"),
        ("discount_amount", "ส่วนลด"),
        ("total_amount", "ยอดรวม"),
        ("shipping_carrier", "บริษัทขนส่ง"),
        ("tracking_number", "เลขพัสดุ"),
        ("shipping_province", "จังหวัดจัดส่ง"),
        ("shipping_postal_code", "รหัสไปรษณีย์"),
        ("created_at", "วันที่สั่งซื้อ"),
    )
    readonly_fields = (
        "reference",
        "buyer",
        "seller",
        "community",
        "payment_status",
        "subtotal",
        "shipping_fee",
        "discount_amount",
        "total_amount",
        "shipping_name",
        "shipping_phone",
        "shipping_address",
        "shipping_province",
        "shipping_postal_code",
        "note",
        "expires_at",
        "stock_reserved",
        "stock_released_at",
        "shipped_at",
        "delivered_at",
        "cancelled_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "ข้อมูลคำสั่งซื้อ",
            {"fields": ("reference", "buyer", "seller", "community")},
        ),
        (
            "จัดการสถานะ",
            {
                "fields": (
                    "status",
                    "payment_status",
                    "status_note",
                    "shipping_carrier",
                    "tracking_number",
                    "shipment_status",
                ),
                "description": "เปลี่ยนสถานะตามลำดับงานจริง ระบบจะบันทึกประวัติและแจ้งผู้ซื้อให้อัตโนมัติ",
            },
        ),
        (
            "ยอดเงิน",
            {"fields": ("subtotal", "shipping_fee", "discount_amount", "total_amount")},
        ),
        (
            "ข้อมูลจัดส่งจากผู้ซื้อ",
            {
                "fields": (
                    "shipping_name",
                    "shipping_phone",
                    "shipping_address",
                    "shipping_province",
                    "shipping_postal_code",
                    "note",
                )
            },
        ),
        (
            "ลำดับเวลาคำสั่งซื้อ",
            {"fields": ("expires_at", "shipped_at", "delivered_at", "cancelled_at")},
        ),
        (
            "ข้อมูลระบบและสต็อก",
            {
                "fields": ("stock_reserved", "stock_released_at", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("shipment")

    @admin.display(description="ติดตามพัสดุ", ordering="shipment__status")
    def shipment_status(self, order):
        try:
            shipment = order.shipment
        except Shipment.DoesNotExist:
            return "ยังไม่มีข้อมูลจากผู้ให้บริการ"
        url = reverse("admin:orders_shipment_change", args=[shipment.pk])
        return format_html('<a href="{}">{}</a>', url, shipment.status_label)

    def save_model(self, request, obj, form, change):
        original = Order.objects.get(pk=obj.pk)
        new_status = form.cleaned_data["status"]
        carrier = (form.cleaned_data.get("shipping_carrier") or "").strip()
        tracking = (form.cleaned_data.get("tracking_number") or "").strip()
        if new_status != original.status:
            saved = change_order_status(
                original,
                new_status,
                request.user,
                note=(form.cleaned_data.get("status_note") or "").strip(),
                carrier=carrier,
                tracking_number=tracking,
            )
        else:
            original.shipping_carrier = carrier
            original.tracking_number = tracking
            original.save(update_fields=["shipping_carrier", "tracking_number", "updated_at"])
            saved = original
        obj.__dict__.update(saved.__dict__)
