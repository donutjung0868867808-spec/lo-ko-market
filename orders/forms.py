from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from django import forms
from django.core.exceptions import ValidationError

from catalog.forms import StyledFormMixin

from .models import Order


class CheckoutForm(StyledFormMixin, forms.Form):
    coupon_code = forms.CharField(label="รหัสส่วนลด", required=False, max_length=40)
    def __init__(self, *args, product=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.product = product
        if product is not None:
            step = product.quantity_step
            minimum = (product.minimum_order_quantity / step).to_integral_value(rounding=ROUND_CEILING) * step
            maximum = (product.stock_quantity / step).to_integral_value(rounding=ROUND_FLOOR) * step
            self.fields["quantity"].min_value = minimum
            self.fields["quantity"].max_value = maximum
            self.fields["quantity"].widget.attrs["step"] = str(step)
            self.fields["quantity"].widget.attrs["inputmode"] = "decimal" if step < 1 else "numeric"
            self.fields["quantity"].help_text = f"สั่งขั้นต่ำ {minimum} {product.get_unit_display()}"

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if self.product is not None:
            step = self.product.quantity_step
            if (quantity / step) != (quantity / step).to_integral_value():
                raise ValidationError(f"กรุณาระบุจำนวนเป็นช่วงละ {step}")
        return quantity
    quantity = forms.DecimalField(
        label="จำนวน",
        min_value=Decimal("0.50"),
        decimal_places=2,
        max_digits=10,
        step_size=Decimal("0.50"),
    )
    shipping_name = forms.CharField(label="ชื่อผู้รับ", max_length=180)
    shipping_phone = forms.CharField(label="เบอร์โทรศัพท์", max_length=30)
    shipping_address = forms.CharField(
        label="ที่อยู่จัดส่ง",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    shipping_province = forms.CharField(label="จังหวัด", max_length=120)
    shipping_postal_code = forms.RegexField(
        label="รหัสไปรษณีย์",
        regex=r"^\d{5}$",
        error_messages={"invalid": "กรุณากรอกรหัสไปรษณีย์ 5 หลัก"},
    )
    note = forms.CharField(
        label="หมายเหตุ",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class CartCheckoutForm(StyledFormMixin, forms.Form):
    coupon_code = forms.CharField(label="รหัสส่วนลด", required=False, max_length=40)
    shipping_name = forms.CharField(label="ชื่อผู้รับ", max_length=180)
    shipping_phone = forms.CharField(label="เบอร์โทรศัพท์", max_length=30)
    shipping_address = forms.CharField(
        label="ที่อยู่จัดส่ง",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    shipping_province = forms.CharField(label="จังหวัด", max_length=120)
    shipping_postal_code = forms.RegexField(
        label="รหัสไปรษณีย์",
        regex=r"^\d{5}$",
        error_messages={"invalid": "กรุณากรอกรหัสไปรษณีย์ 5 หลัก"},
    )
    note = forms.CharField(
        label="หมายเหตุ",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class CancelOrderForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(
        label="เหตุผลที่ยกเลิก",
        min_length=5,
        max_length=255,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

class OrderStatusForm(StyledFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .services import ALLOWED_STATUS_TRANSITIONS

        allowed = ALLOWED_STATUS_TRANSITIONS.get(self.instance.status, set()) if self.instance.pk else set()
        self.fields["status"].choices = [
            choice for choice in Order.Status.choices if choice[0] in allowed
        ]

    status_note = forms.CharField(
        label="หมายเหตุ",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta:
        model = Order
        fields = ["status", "shipping_carrier", "tracking_number"]
        labels = {
            "status": "สถานะคำสั่งซื้อ",
            "shipping_carrier": "บริษัทขนส่ง",
            "tracking_number": "เลขติดตามพัสดุ",
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("status") == Order.Status.CANCELLED and not cleaned.get(
            "status_note", ""
        ).strip():
            self.add_error("status_note", "กรุณาระบุเหตุผลที่ยกเลิกคำสั่งซื้อ")
        if cleaned.get("status") == Order.Status.SHIPPED:
            if not cleaned.get("shipping_carrier"):
                self.add_error("shipping_carrier", "กรุณาระบุบริษัทขนส่ง")
            if not cleaned.get("tracking_number"):
                self.add_error("tracking_number", "กรุณาระบุเลขติดตามพัสดุ")
        return cleaned