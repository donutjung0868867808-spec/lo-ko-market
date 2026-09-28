from decimal import Decimal

from django import forms
from django.conf import settings
from django.forms import inlineformset_factory

from .models import Product, ProductDetailImage, ProductImage, ProductSizeChartRow, ProductVariant


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


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.FileField):
    widget = MultipleImageInput

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        return [super().clean(file, initial=None) for file in files]


class ProductForm(StyledFormMixin, forms.ModelForm):
    detail_image_size = forms.ChoiceField(
        label="ขนาดรูปประกอบรายละเอียด",
        choices=ProductDetailImage.DisplaySize.choices,
        initial=ProductDetailImage.DisplaySize.STANDARD,
        help_text="ใช้กับรูปประกอบรายละเอียดที่เลือกในครั้งนี้",
    )

    detail_images = MultipleImageField(
        label="รูปประกอบรายละเอียดสินค้า",
        required=False,
        help_text="เพิ่มรูปที่ต้องการให้แสดงภายในส่วนรายละเอียดสินค้าได้หลายรูป",
        validators=ProductDetailImage._meta.get_field("image").validators,
        widget=MultipleImageInput(
            attrs={
                "accept": "image/jpeg,image/png,image/webp",
                "data-product-gallery-input": "true",
                "data-product-detail-image-input": "true",
                "data-product-gallery-title": "เลือกรูปประกอบรายละเอียด",
                "data-product-gallery-hint": "รูปเหล่านี้จะแสดงในส่วนรายละเอียดสินค้า",
                "multiple": True,
            }
        ),
    )

    image = MultipleImageField(
        label="รูปสินค้า",
        required=False,
        help_text="กดเลือกหรือลากรูปมาวางได้หลายรูป รูปแรกจะใช้เป็นรูปหลัก",
        validators=ProductImage._meta.get_field("image").validators,
        widget=MultipleImageInput(
            attrs={
                "accept": "image/jpeg,image/png,image/webp",
                "data-product-gallery-input": "true",
                "multiple": True,
            }
        ),
    )

    field_order = [
        "category",
        "name",
        "description",
        "detail_image_size",
        "detail_images",
        "unit",
        "price",
        "stock_quantity",
        "minimum_order_quantity",
        "maximum_order_quantity",
        "low_stock_threshold",
        "weight_grams",
        "package_length_cm",
        "package_width_cm",
        "package_height_cm",
        "preparation_days",
        "gtin",
        "image",
        "size_chart_image",
        "harvest_date",
        "expiry_date",
    ]

    def __init__(self, *args, require_shipping_weight=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.require_shipping_weight = require_shipping_weight
        unit = self.initial.get("unit") or self.instance.unit
        step = Product.quantity_step_for_unit(unit)
        for name in ("stock_quantity", "minimum_order_quantity", "maximum_order_quantity"):
            self.fields[name].widget.attrs["step"] = str(step)
        if not self.instance.pk and unit == Product.Unit.KG:
            self.initial["minimum_order_quantity"] = Decimal("0.50")
        self.fields["preparation_days"].required = False
        self.fields["preparation_days"].initial = self.instance.preparation_days or 1
        self.fields["maximum_order_quantity"].help_text = "เว้นว่างหากไม่จำกัดจำนวนต่อคำสั่งซื้อ"
        self.fields["gtin"].help_text = "เว้นว่างได้หากสินค้าไม่มีรหัสบาร์โค้ด"
        self.fields["package_height_cm"].help_text = "ระบุให้ครบทั้งยาว x กว้าง x สูง หากใช้"
        self.fields["preparation_days"].help_text = "จำนวนวันก่อนพร้อมส่งสินค้า"
        if require_shipping_weight:
            self.fields["weight_grams"].required = True
            self.fields["weight_grams"].widget.attrs.update({"min": "1", "inputmode": "numeric"})
            self.fields["weight_grams"].help_text = "ระบุน้ำหนักต่อหน่วยเพื่อคำนวณค่าจัดส่ง"

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
            "maximum_order_quantity",
            "low_stock_threshold",
            "weight_grams",
            "package_length_cm",
            "package_width_cm",
            "package_height_cm",
            "preparation_days",
            "gtin",
            "size_chart_image",
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
            "maximum_order_quantity": "จำนวนสั่งซื้อสูงสุดต่อคำสั่งซื้อ",
            "low_stock_threshold": "แจ้งเตือนเมื่อเหลือน้อยกว่า",
            "weight_grams": "น้ำหนักต่อหน่วย (กรัม)",
            "gtin": "รหัส GTIN (ถ้ามี)",
            "package_length_cm": "ความยาวพัสดุ (ซม.)",
            "package_width_cm": "ความกว้างพัสดุ (ซม.)",
            "package_height_cm": "ความสูงพัสดุ (ซม.)",
            "preparation_days": "ระยะเวลาเตรียมสินค้า (วัน)",
            "expiry_date": "วันที่ควรบริโภคก่อน",
            "size_chart_image": "รูปตารางขนาดสินค้า (ถ้ามี)",
            "harvest_date": "วันที่เก็บเกี่ยว",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "maximum_order_quantity": forms.NumberInput(
                attrs={"min": "0.50", "step": "0.50", "inputmode": "decimal"}
            ),
            "package_length_cm": forms.NumberInput(attrs={"min": "1", "inputmode": "numeric"}),
            "package_width_cm": forms.NumberInput(attrs={"min": "1", "inputmode": "numeric"}),
            "package_height_cm": forms.NumberInput(attrs={"min": "1", "inputmode": "numeric"}),
            "preparation_days": forms.NumberInput(attrs={"min": "0", "max": "14", "inputmode": "numeric"}),
            "gtin": forms.TextInput(attrs={"inputmode": "numeric", "maxlength": "14"}),
            "harvest_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "expiry_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def clean_image(self):
        return self.cleaned_data.get("image", [])

    def clean_detail_images(self):
        return self.cleaned_data.get("detail_images", [])

    def clean_weight_grams(self):
        weight_grams = self.cleaned_data.get("weight_grams")
        if self.require_shipping_weight and (weight_grams is None or weight_grams <= 0):
            raise forms.ValidationError("กรุณาระบุน้ำหนักต่อหน่วยอย่างน้อย 1 กรัม")
        return weight_grams

    def clean_gtin(self):
        gtin = (self.cleaned_data.get("gtin") or "").strip()
        if not gtin:
            return None
        if not gtin.isascii() or not gtin.isdigit() or len(gtin) not in {8, 12, 13, 14}:
            raise forms.ValidationError("GTIN ต้องเป็นตัวเลข 8, 12, 13 หรือ 14 หลัก")
        return gtin

    def clean_preparation_days(self):
        return self.cleaned_data.get("preparation_days") or 1

    def clean(self):
        cleaned = super().clean()
        harvest_date = cleaned.get("harvest_date")
        expiry_date = cleaned.get("expiry_date")
        if harvest_date and expiry_date and expiry_date < harvest_date:
            self.add_error("expiry_date", "วันที่ควรบริโภคก่อนต้องไม่น้อยกว่าวันเก็บเกี่ยว")
        unit = cleaned.get("unit")
        step = Product.quantity_step_for_unit(unit)
        for field_name in ("stock_quantity", "minimum_order_quantity", "maximum_order_quantity"):
            value = cleaned.get(field_name)
            if value is None:
                continue
            if value < step or (value / step) != (value / step).to_integral_value():
                self.add_error(field_name, f"กรุณากรอกเป็นช่วงละ {step}")
        minimum_order_quantity = cleaned.get("minimum_order_quantity")
        maximum_order_quantity = cleaned.get("maximum_order_quantity")
        if (
            minimum_order_quantity is not None
            and maximum_order_quantity is not None
            and maximum_order_quantity < minimum_order_quantity
        ):
            self.add_error(
                "maximum_order_quantity",
                "จำนวนสูงสุดต้องไม่น้อยกว่าจำนวนสั่งซื้อขั้นต่ำ",
            )
        package_dimensions = [
            cleaned.get("package_length_cm"),
            cleaned.get("package_width_cm"),
            cleaned.get("package_height_cm"),
        ]
        if any(package_dimensions) and not all(package_dimensions):
            for field_name in (
                "package_length_cm",
                "package_width_cm",
                "package_height_cm",
            ):
                if cleaned.get(field_name) is None:
                    self.add_error(field_name, "กรุณาระบุขนาดพัสดุให้ครบทั้ง 3 ด้าน")
        return cleaned


class ProductImageForm(StyledFormMixin, forms.Form):
    image = MultipleImageField(
        label="รูปสินค้า",
        help_text="กดเลือกหรือลากรูปมาวางได้หลายรูป",
        validators=ProductImage._meta.get_field("image").validators,
        widget=MultipleImageInput(
            attrs={
                "accept": "image/jpeg,image/png,image/webp",
                "data-product-gallery-input": "true",
                "multiple": True,
            }
        ),
    )


class ProductVariantForm(StyledFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["is_active"].widget.attrs["class"] = (
            "h-4 w-4 rounded border-stone-300 text-leaf focus:ring-leaf"
        )
        self.fields["sort_order"].required = False

    def clean_sort_order(self):
        return self.cleaned_data.get("sort_order") or 0

    class Meta:
        model = ProductVariant
        fields = ["name", "image", "is_active", "sort_order"]
        labels = {
            "name": "ชื่อตัวเลือก",
            "image": "รูปกำกับ",
            "is_active": "เปิดให้เลือก",
            "sort_order": "ลำดับ",
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "เช่น สีเหลือง"}),
            "image": forms.ClearableFileInput(
                attrs={"accept": "image/jpeg,image/png,image/webp"}
            ),
            "sort_order": forms.NumberInput(attrs={"min": "0"}),
        }


ProductVariantFormSet = inlineformset_factory(
    Product,
    ProductVariant,
    form=ProductVariantForm,
    extra=0,
    max_num=1000,
    can_delete=True,
)


class ProductSizeChartRowForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ProductSizeChartRow
        fields = ["label", "length_cm", "width_cm", "height_cm", "weight_grams", "note", "sort_order"]
        widgets = {
            "label": forms.TextInput(attrs={"placeholder": "เช่น S, M, L"}),
            "length_cm": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
            "width_cm": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
            "height_cm": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
            "weight_grams": forms.NumberInput(attrs={"min": "0"}),
            "note": forms.TextInput(attrs={"placeholder": "หมายเหตุ (ถ้ามี)"}),
            "sort_order": forms.NumberInput(attrs={"min": "0"}),
        }


ProductSizeChartRowFormSet = inlineformset_factory(
    Product,
    ProductSizeChartRow,
    form=ProductSizeChartRowForm,
    extra=0,
    max_num=1000,
    can_delete=True,
)


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
