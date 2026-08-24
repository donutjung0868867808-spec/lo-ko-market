from decimal import Decimal

from django import forms
from django.core.validators import FileExtensionValidator

from accounts.models import validate_file_size
from accounts.validators import validate_private_document

from catalog.forms import StyledFormMixin


class RefundRequestForm(StyledFormMixin, forms.Form):
    amount = forms.DecimalField(
        label="จำนวนเงินที่ขอคืน",
        min_value=Decimal("0.01"),
        max_digits=12,
        decimal_places=2,
    )
    reason = forms.CharField(
        label="เหตุผลที่ขอคืนเงิน",
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    evidence = forms.FileField(
        label="หลักฐานประกอบ (ถ้ามี)",
        required=False,
        validators=[
            FileExtensionValidator(["pdf", "jpg", "jpeg", "png", "webp"]),
            validate_file_size,
            validate_private_document,
        ],
    )

    def __init__(self, *args, payment=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.payment = payment
        if payment:
            remaining = payment.amount - payment.refunded_amount
            self.fields["amount"].max_value = remaining
            self.fields["amount"].initial = remaining

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if self.payment and amount > self.payment.amount - self.payment.refunded_amount:
            raise forms.ValidationError("จำนวนเงินเกินยอดที่สามารถคืนได้")
        return amount

class RefundDecisionForm(StyledFormMixin, forms.Form):
    resolution_note = forms.CharField(
        label="เหตุผลที่ไม่อนุมัติ",
        min_length=5,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 4}),
    )