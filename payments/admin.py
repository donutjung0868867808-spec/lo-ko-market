from django.contrib import admin, messages

from accounts.admin_permissions import CsvExportAdminMixin, OwnerOnlyAdminMixin

from .models import (
    CustomerPaymentProfile,
    Payment,
    Refund,
    SavedPaymentMethod,
    SellerPaymentAccount,
    SellerSettlement,
    StripeEvent,
)
from .services import process_seller_settlement


class ReadOnlyOwnerAdminMixin(OwnerOnlyAdminMixin):
    """แสดงข้อมูลที่ระบบภายนอกสร้าง โดยไม่ให้แก้ค่าด้วยมือ"""

    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class RefundInline(admin.TabularInline):
    model = Refund
    extra = 0
    can_delete = False
    readonly_fields = (
        "requested_by",
        "amount",
        "reason",
        "status",
        "stripe_refund_id",
        "created_at",
    )

    def has_view_permission(self, request, obj=None):
        return request.user.is_owner

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(CsvExportAdminMixin, ReadOnlyOwnerAdminMixin, admin.ModelAdmin):
    list_display = (
        "order",
        "provider_thai",
        "status",
        "amount",
        "refunded_amount",
        "currency_thai",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "order__reference",
        "order__id",
        "checkout_session_id",
        "payment_intent_id",
    )
    list_select_related = ("order",)
    readonly_fields = (
        "order",
        "provider_thai",
        "status",
        "amount",
        "currency_thai",
        "checkout_session_id",
        "checkout_attempt_id",
        "checkout_url",
        "checkout_expires_at",
        "payment_intent_id",
        "raw_payload",
        "refunded_amount",
        "created_at",
        "updated_at",
    )
    inlines = [RefundInline]
    fieldsets = (
        (
            "ข้อมูลการชำระเงิน",
            {"fields": ("order", "provider_thai", "status", "amount", "currency_thai", "refunded_amount")},
        ),
        (
            "รหัสอ้างอิงจากผู้ให้บริการ",
            {
                "fields": (
                    "checkout_session_id",
                    "checkout_attempt_id",
                    "checkout_url",
                    "checkout_expires_at",
                    "payment_intent_id",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "ข้อมูลระบบ",
            {"fields": ("raw_payload", "created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
    csv_filename = "payments.csv"
    csv_export_fields = (
        ("order__reference", "เลขคำสั่งซื้อ"),
        ("status", "สถานะ"),
        ("amount", "จำนวนเงิน"),
        ("refunded_amount", "ยอดคืนเงิน"),
        ("currency", "สกุลเงิน"),
        ("payment_intent_id", "รหัสการชำระเงิน"),
        ("created_at", "วันที่สร้าง"),
    )

    @admin.display(description="ช่องทางชำระเงิน", ordering="provider")
    def provider_thai(self, obj):
        return "ชำระเงินออนไลน์"

    @admin.display(description="สกุลเงิน", ordering="currency")
    def currency_thai(self, obj):
        return "บาทไทย" if obj.currency.lower() == "thb" else "สกุลเงินอื่น"


@admin.register(Refund)
class RefundAdmin(CsvExportAdminMixin, ReadOnlyOwnerAdminMixin, admin.ModelAdmin):
    list_display = ("payment", "amount", "status", "requested_by", "handled_by", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("payment__order__reference", "reason", "stripe_refund_id")
    readonly_fields = (
        "payment",
        "requested_by",
        "amount",
        "reason",
        "evidence",
        "status",
        "resolution_note",
        "handled_by",
        "handled_at",
        "stripe_refund_id",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("คำขอคืนเงิน", {"fields": ("payment", "requested_by", "amount", "reason", "evidence", "status")}),
        ("ผลการพิจารณา", {"fields": ("resolution_note", "handled_by", "handled_at")}),
        (
            "ข้อมูลจากผู้ให้บริการ",
            {"fields": ("stripe_refund_id", "created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
    csv_filename = "refunds.csv"
    csv_export_fields = (
        ("payment__order__reference", "เลขคำสั่งซื้อ"),
        ("requested_by__username", "ผู้ขอคืนเงิน"),
        ("amount", "จำนวนเงิน"),
        ("status", "สถานะ"),
        ("reason", "เหตุผล"),
        ("resolution_note", "ผลการพิจารณา"),
        ("handled_by__username", "ผู้พิจารณา"),
        ("handled_at", "วันที่พิจารณา"),
        ("created_at", "วันที่ยื่นคำขอ"),
    )


@admin.register(CustomerPaymentProfile)
class CustomerPaymentProfileAdmin(ReadOnlyOwnerAdminMixin, admin.ModelAdmin):
    list_display = ("user", "saved_method_count", "created_at", "updated_at")
    search_fields = ("user__username", "user__display_name", "user__email")
    readonly_fields = ("user", "stripe_customer_id", "created_at", "updated_at")
    fieldsets = (
        ("เจ้าของบัญชีชำระเงิน", {"fields": ("user",)}),
        (
            "ข้อมูลระบบชำระเงิน",
            {"fields": ("stripe_customer_id", "created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    @admin.display(description="จำนวนบัตรที่บันทึกไว้")
    def saved_method_count(self, obj):
        return obj.payment_methods.count()


@admin.register(SavedPaymentMethod)
class SavedPaymentMethodAdmin(ReadOnlyOwnerAdminMixin, admin.ModelAdmin):
    list_display = ("owner", "brand", "last4", "expiry", "is_default", "created_at")
    list_filter = ("brand", "is_default")
    search_fields = (
        "profile__user__username",
        "profile__user__display_name",
        "last4",
    )
    readonly_fields = (
        "profile",
        "method_type",
        "brand",
        "last4",
        "exp_month",
        "exp_year",
        "is_default",
        "stripe_payment_method_id",
        "created_at",
    )
    fieldsets = (
        (
            "ข้อมูลบัตรที่แสดงได้",
            {"fields": ("profile", "brand", "last4", "exp_month", "exp_year", "is_default")},
        ),
        (
            "ข้อมูลระบบชำระเงิน",
            {"fields": ("method_type", "stripe_payment_method_id", "created_at"), "classes": ("collapse",)},
        ),
    )

    @admin.display(description="ผู้ใช้", ordering="profile__user__username")
    def owner(self, obj):
        return obj.profile.user

    @admin.display(description="วันหมดอายุ")
    def expiry(self, obj):
        if not obj.exp_month or not obj.exp_year:
            return "ไม่มีข้อมูล"
        return f"{obj.exp_month:02d}/{str(obj.exp_year)[-2:]}"


@admin.register(StripeEvent)
class StripeEventAdmin(ReadOnlyOwnerAdminMixin, admin.ModelAdmin):
    list_display = ("event_id", "event_type_thai", "processed", "received_at", "processed_at")
    list_filter = ("processed", "received_at")
    search_fields = ("event_id", "event_type", "error_message")
    readonly_fields = (
        "event_id",
        "event_type",
        "event_type_thai",
        "payload",
        "processed",
        "error_message",
        "received_at",
        "processed_at",
    )
    fieldsets = (
        (
            "ข้อมูลเหตุการณ์จากระบบชำระเงิน",
            {"fields": ("event_id", "event_type_thai", "processed", "error_message")},
        ),
        (
            "ข้อมูลทางเทคนิค",
            {"fields": ("event_type", "payload", "received_at", "processed_at"), "classes": ("collapse",)},
        ),
    )

    @admin.display(description="ประเภทเหตุการณ์", ordering="event_type")
    def event_type_thai(self, obj):
        labels = {
            "checkout.session.completed": "ชำระเงินสำเร็จ",
            "checkout.session.expired": "หมดเวลาชำระเงิน",
            "payment_intent.succeeded": "ยืนยันการชำระเงินสำเร็จ",
            "payment_intent.payment_failed": "การชำระเงินไม่สำเร็จ",
            "charge.refunded": "คืนเงินแล้ว",
            "refund.updated": "อัปเดตสถานะคืนเงิน",
        }
        return labels.get(obj.event_type, "เหตุการณ์อื่นจากระบบชำระเงิน")


@admin.register(SellerPaymentAccount)
class SellerPaymentAccountAdmin(ReadOnlyOwnerAdminMixin, admin.ModelAdmin):
    list_display = (
        "seller",
        "status",
        "details_submitted",
        "charges_enabled",
        "payouts_enabled",
        "updated_at",
    )
    list_filter = ("status", "details_submitted", "payouts_enabled")
    search_fields = ("seller__username", "seller__email", "stripe_account_id")
    readonly_fields = (
        "seller",
        "country",
        "status",
        "stripe_account_id",
        "details_submitted",
        "charges_enabled",
        "payouts_enabled",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("ผู้ขาย", {"fields": ("seller", "country", "status")}),
        (
            "บัญชีรับเงินออนไลน์",
            {"fields": ("stripe_account_id", "details_submitted", "charges_enabled", "payouts_enabled")},
        ),
        (
            "ข้อมูลระบบ",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )


@admin.register(SellerSettlement)
class SellerSettlementAdmin(CsvExportAdminMixin, OwnerOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "payment",
        "seller",
        "gross_amount",
        "platform_fee",
        "net_amount",
        "status",
        "available_at",
    )
    list_filter = ("status", "currency", "created_at")
    search_fields = ("payment__order__reference", "seller__username", "stripe_transfer_id")
    readonly_fields = (
        "payment",
        "seller",
        "gross_amount",
        "fee_rate",
        "platform_fee",
        "net_amount",
        "currency",
        "status",
        "stripe_transfer_id",
        "available_at",
        "transferred_at",
        "failure_reason",
        "created_at",
        "updated_at",
    )
    csv_filename = "seller-settlements.csv"
    csv_export_fields = (
        ("payment__order__reference", "เลขคำสั่งซื้อ"),
        ("seller__username", "ผู้ขาย"),
        ("gross_amount", "ยอดขาย"),
        ("platform_fee", "ค่าธรรมเนียมระบบ"),
        ("net_amount", "ยอดสุทธิผู้ขาย"),
        ("status", "สถานะ"),
        ("available_at", "วันที่พร้อมโอน"),
        ("transferred_at", "วันที่โอน"),
    )
    actions = ("transfer_selected_settlements", "export_as_csv")

    @admin.action(description="โอนยอดที่เลือกให้ผู้ขาย")
    def transfer_selected_settlements(self, request, queryset):
        completed = 0
        for settlement in queryset:
            try:
                result = process_seller_settlement(settlement)
            except Exception as exc:
                self.message_user(
                    request,
                    f"ยอด {settlement.pk} ไม่สำเร็จ: {exc}",
                    level=messages.ERROR,
                )
            else:
                if result.status == SellerSettlement.Status.TRANSFERRED:
                    completed += 1
                else:
                    self.message_user(request, result.failure_reason, level=messages.WARNING)
        if completed:
            self.message_user(request, f"โอนเงินสำเร็จ {completed} รายการ", level=messages.SUCCESS)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
