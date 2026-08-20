from decimal import Decimal

from django import forms
from django.conf import settings

from .models import Product, ProductImage


class StyledFormMixin:
    input_class = (
        "w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm "
        "text-slate-900 shadow-sm outline-none focus:border-emerald-600 focus:ring-2 "
        "focus:ring-emerald-100"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css_class} {self.input_class}".strip()


class ProductForm(StyledFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        unit = self.initial.get("unit") or self.instance.unit
        step = Product.quantity_step_for_unit(unit)
        for name in ("stock_quantity", "minimum_order_quantity"):
            self.fields[name].widget.attrs["step"] = str(step)
        if not self.instance.pk and unit == Product.Unit.KG:
            self.initial["minimum_order_quantity"] = Decimal("0.50")

    class Meta:
        model = Product
        fields = [
            "category",
            "name",
            "description",
            "unit",
            "price",
            "stock_quantity",
            "minimum_order_quantity",
            "low_stock_threshold",
            "weight_grams",
            "image",
            "harvest_date",
            "expiry_date",
        ]
        labels = {
            "category": "หมวดสินค้า",
            "name": "ชื่อสินค้า",
            "description": "รายละเอียด",
            "unit": "หน่วยขาย",
            "price": "ราคา",
            "stock_quantity": "จำนวนคงเหลือ",
            "minimum_order_quantity": "จำนวนสั่งซื้อขั้นต่ำ",
            "low_stock_threshold": "แจ้งเตือนเมื่อเหลือน้อยกว่า",
            "weight_grams": "น้ำหนักต่อหน่วย (กรัม)",
            "expiry_date": "วันที่ควรบริโภคก่อน",
            "image": "รูปสินค้า",
            "harvest_date": "วันที่เก็บเกี่ยว",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "harvest_date": forms.DateInput(attrs={"type": "date"}),
            "expiry_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image and image.size > settings.MAX_UPLOAD_SIZE:
            raise forms.ValidationError("รูปภาพมีขนาดใหญ่เกินกำหนด")
        return image

    def clean(self):
        cleaned = super().clean()
        harvest_date = cleaned.get("harvest_date")
        expiry_date = cleaned.get("expiry_date")
        if harvest_date and expiry_date and expiry_date < harvest_date:
            self.add_error("expiry_date", "วันที่ควรบริโภคก่อนต้องไม่น้อยกว่าวันเก็บเกี่ยว")
        unit = cleaned.get("unit")
        step = Product.quantity_step_for_unit(unit)
        for field_name in ("stock_quantity", "minimum_order_quantity"):
            value = cleaned.get(field_name)
            if value is None:
                continue
            if value < step or (value / step) != (value / step).to_integral_value():
                self.add_error(field_name, f"กรุณากรอกเป็นช่วงละ {step}")
        return cleaned


class ProductImageForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = ["image", "alt_text"]
        labels = {"image": "รูปภาพเพิ่มเติม", "alt_text": "คำอธิบายรูป"}

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image and image.size > settings.MAX_UPLOAD_SIZE:
            raise forms.ValidationError("รูปภาพมีขนาดใหญ่เกินกำหนด")
        return image


class ProductReviewForm(StyledFormMixin, forms.Form):
    decision = forms.ChoiceField(
        choices=[("approve", "อนุมัติ"), ("reject", "ไม่อนุมัติ")],
        label="ผลการตรวจสอบ",
    )
    rejection_reason = forms.CharField(
        label="เหตุผล",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
