from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from .models import AVATAR_MAX_SIZE, Community, DeliveryAddress, DirectMessage, FarmerProfile, NewsPost, Report, ReportMessage, User


def validate_upload(upload):
    if upload and upload.size > settings.MAX_UPLOAD_SIZE:
        raise forms.ValidationError("ไฟล์มีขนาดใหญ่เกินกำหนด")
    return upload


class StyledFormMixin:
    input_class = (
        "w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm "
        "text-slate-900 shadow-sm outline-none transition focus:border-emerald-600 "
        "focus:ring-2 focus:ring-emerald-100"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            "username": "ตัวอย่าง: farmer123",
            "display_name": "ชื่อที่จะแสดงบนโปรไฟล์",
            "email": "example@email.com",
            "phone": "0812345678",
            "password1": "รหัสผ่านอย่างน้อย 8 ตัว",
            "password2": "ยืนยันรหัสผ่าน",
        }
        help_texts = {
            "username": "ใช้ตัวอักษร a-z, A-Z, ตัวเลข และ _ . @ +/- ไม่มีช่องว่าง",
            "email": "ใส่อีเมลที่ใช้งานได้จริงเพื่อรับการแจ้งเตือน",
            "phone": "ใส่เบอร์โทรศัพท์ที่ติดต่อได้",
            "password1": "รหัสผ่านต้องมีอย่างน้อย 8 ตัวอักษร และควรประกอบด้วยตัวอักษรใหญ่-เล็กและตัวเลข",
            "password2": "กรอกให้ตรงกับรหัสผ่านด้านบน",
        }
        for name, field in self.fields.items():
            css_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css_class} {self.input_class}".strip()
            if name in placeholders:
                field.widget.attrs["placeholder"] = placeholders[name]
            if name in help_texts:
                field.help_text = help_texts[name]
            if name in {"display_name", "email", "phone"}:
                field.required = True


class BaseSignupForm(StyledFormMixin, UserCreationForm):
    accept_terms = forms.BooleanField(initial=True, widget=forms.HiddenInput())
    accept_privacy = forms.BooleanField(initial=True, widget=forms.HiddenInput())

    class Meta:
        model = User
        fields = [
            "username",
            "display_name",
            "email",
            "phone",
            "password1",
            "password2",
        ]
        labels = {
            "username": "ชื่อผู้ใช้",
            "display_name": "ชื่อที่แสดง",
            "email": "อีเมล",
            "phone": "เบอร์โทรศัพท์",
        }

    def clean_gender(self):
        return self.cleaned_data.get("gender") or getattr(
            self.instance,
            "gender",
            User.Gender.UNSPECIFIED,
        ) or User.Gender.UNSPECIFIED

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("อีเมลนี้ถูกใช้งานแล้ว โปรดลองใช้อีเมลอื่น")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        accepted_at = timezone.now()
        user.terms_accepted_at = accepted_at
        user.privacy_accepted_at = accepted_at
        user.terms_version = settings.TERMS_VERSION
        user.privacy_version = settings.PRIVACY_VERSION
        if commit:
            user.save()
        return user


class ConsumerSignupForm(BaseSignupForm):
    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Roles.CONSUMER
        if commit:
            user.save()
        return user


class FarmerSignupForm(BaseSignupForm):
    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Roles.FARMER
        if commit:
            user.save()
        return user


class FarmerProfileForm(StyledFormMixin, forms.ModelForm):
    community = forms.ModelChoiceField(
        queryset=Community.objects.filter(is_active=True).order_by("name"),
        empty_label="เลือกชุมชน/สหกรณ์",
        label="ชุมชน/สหกรณ์",
        required=True,
    )

    class Meta:
        model = FarmerProfile
        fields = [
            "farm_name",
            "community",
            "province",
            "district",
            "address",
            "bio",
            "document_type",
            "verification_document",
        ]
        labels = {
            "farm_name": "ชื่อสวน/ฟาร์ม",
            "province": "จังหวัด",
            "district": "อำเภอ",
            "address": "ที่อยู่",
            "document_type": "ประเภทเอกสารยืนยัน",
            "verification_document": "เอกสารยืนยันเกษตรกร",
            "bio": "ข้อมูลฟาร์ม",
        }
        widgets = {
            "farm_name": forms.TextInput(),
            "province": forms.TextInput(),
            "district": forms.TextInput(),
            "address": forms.Textarea(attrs={"rows": 3}),
            "bio": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_verification_document(self):
        return validate_upload(self.cleaned_data.get("verification_document"))

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("community"):
            self.add_error("community", "กรุณาเลือกชุมชนหรือสหกรณ์")
        return cleaned_data


class UserProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["avatar", "display_name", "email", "phone", "first_name", "last_name", "gender", "birth_date"]
        labels = {
            "display_name": "ชื่อที่แสดง",
            "email": "อีเมล",
            "phone": "เบอร์โทรศัพท์",
            "first_name": "ชื่อ",
            "last_name": "นามสกุล",
            "avatar": "รูปโปรไฟล์",
            "gender": "เพศ",
            "birth_date": "วันเกิด",
        }
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date"}),
            "gender": forms.RadioSelect(),
            "avatar": forms.FileInput(attrs={"accept": ".jpg,.jpeg,.png,image/jpeg,image/png"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["display_name", "email", "phone"]:
            self.fields[name].required = True
        self.fields["gender"].required = False

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if avatar and avatar.size > AVATAR_MAX_SIZE:
            raise forms.ValidationError("รูปโปรไฟล์ต้องมีขนาดไม่เกิน 1 MB")
        return avatar
    def clean_gender(self):
        return self.cleaned_data.get("gender") or getattr(
            self.instance,
            "gender",
            User.Gender.UNSPECIFIED,
        ) or User.Gender.UNSPECIFIED

    def clean_email(self):
        email = self.cleaned_data.get("email")
        qs = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if email and qs.exists():
            raise forms.ValidationError("อีเมลนี้ถูกใช้งานแล้ว โปรดลองใช้อีเมลอื่น")
        return email


class StaffSellerAccountForm(UserProfileForm):
    class Meta(UserProfileForm.Meta):
        fields = UserProfileForm.Meta.fields + ["is_active"]
        labels = {
            **UserProfileForm.Meta.labels,
            "is_active": "เปิดใช้งานบัญชี",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["is_active"].widget.attrs["class"] = (
            "h-5 w-5 rounded border-slate-300 text-emerald-700 "
            "focus:ring-emerald-200"
        )


class StaffFarmerProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FarmerProfile
        fields = [
            "farm_name",
            "province",
            "district",
            "address",
            "bio",
            "document_type",
            "verification_status",
            "rejection_reason",
        ]
        labels = {
            "farm_name": "ชื่อสวน/ฟาร์ม",
            "province": "จังหวัด",
            "district": "อำเภอ",
            "address": "ที่อยู่",
            "bio": "ข้อมูลฟาร์ม",
            "document_type": "ประเภทเอกสารยืนยัน",
            "verification_status": "สถานะการตรวจสอบ",
            "rejection_reason": "เหตุผลที่ไม่ผ่าน",
        }
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
            "bio": forms.Textarea(attrs={"rows": 3}),
            "rejection_reason": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("verification_status")
            == FarmerProfile.VerificationStatus.REJECTED
            and not cleaned_data.get("rejection_reason", "").strip()
        ):
            self.add_error("rejection_reason", "กรุณาระบุเหตุผลที่ไม่ผ่านการตรวจสอบ")
        return cleaned_data

class NotificationForm(StyledFormMixin, forms.Form):
    recipients = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        label="ผู้รับ",
        widget=forms.SelectMultiple(attrs={"size": 8}),
    )
    title = forms.CharField(label="หัวข้อ", max_length=200)
    message = forms.CharField(
        label="ข้อความ",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    link = forms.CharField(label="ลิงก์", required=False, max_length=500)

    def __init__(self, *args, recipients=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["recipients"].queryset = recipients or User.objects.none()


class NewsPostForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = NewsPost
        fields = ["title", "slug", "summary", "body", "audience", "is_published", "published_at"]
        labels = {
            "title": "หัวข้อข่าว",
            "slug": "Slug",
            "summary": "สรุปข่าว",
            "body": "เนื้อหา",
            "audience": "กลุ่มผู้อ่าน",
            "is_published": "เผยแพร่",
            "published_at": "วันที่เผยแพร่",
        }
        widgets = {
            "summary": forms.Textarea(attrs={"rows": 3}),
            "body": forms.Textarea(attrs={"rows": 8}),
            "published_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["published_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"]
        if self.instance and self.instance.pk and self.instance.published_at:
            self.initial["published_at"] = self.instance.published_at.strftime("%Y-%m-%dT%H:%M")


class ReportForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Report
        fields = ["reason", "details", "evidence"]
        labels = {
            "reason": "เหตุผล",
            "evidence": "หลักฐานประกอบ",
            "details": "รายละเอียด",
        }
        widgets = {
            "details": forms.Textarea(attrs={"rows": 5}),
        }

    def clean_evidence(self):
        return validate_upload(self.cleaned_data.get("evidence"))


class ReportMessageForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ReportMessage
        fields = ["message", "attachment"]
        labels = {"message": "ข้อความ", "attachment": "ไฟล์แนบ"}
        widgets = {"message": forms.Textarea(attrs={"rows": 3})}

    def clean_attachment(self):
        return validate_upload(self.cleaned_data.get("attachment"))


class ReportResolutionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Report
        fields = ["status", "resolution_note"]
        labels = {
            "status": "สถานะ",
            "resolution_note": "บันทึกการดำเนินการ",
        }
        widgets = {
            "resolution_note": forms.Textarea(attrs={"rows": 4}),
        }
class DirectMessageForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = DirectMessage
        fields = ["body"]
        labels = {"body": "ข้อความ"}
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 3,
                    "maxlength": 2000,
                    "placeholder": "พิมพ์ข้อความถึงผู้ขาย",
                }
            )
        }

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("กรุณาพิมพ์ข้อความ")
        return body
class DeliveryAddressForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = DeliveryAddress
        fields = [
            "label",
            "recipient_name",
            "phone",
            "province",
            "district",
            "subdistrict",
            "postal_code",
            "address_line",
            "is_default",
        ]
        widgets = {
            "address_line": forms.Textarea(attrs={"rows": 3}),
            "postal_code": forms.TextInput(attrs={"inputmode": "numeric", "maxlength": 5}),
        }

    def clean_postal_code(self):
        postal_code = self.cleaned_data["postal_code"].strip()
        if len(postal_code) != 5 or not postal_code.isdigit():
            raise forms.ValidationError("กรุณากรอกรหัสไปรษณีย์ 5 หลัก")
        return postal_code