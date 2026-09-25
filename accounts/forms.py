from django import forms
from datetime import timedelta
from urllib.parse import urlsplit
from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm, UserCreationForm
from django.core.validators import FileExtensionValidator
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone
from django.template.loader import render_to_string

from .models import AVATAR_MAX_SIZE, Community, DeliveryAddress, DirectMessage, FarmerProfile, NewsPost, Report, ReportMessage, SupportMessage, SupportTicket, User, validate_store_image_size


def split_display_name(display_name):
    parts = display_name.strip().split(maxsplit=1)
    first_name = parts[0] if parts else ""
    last_name = parts[1] if len(parts) > 1 else ""
    return first_name, last_name


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
            "first_name": "กรอกชื่อ",
            "last_name": "กรอกนามสกุล",
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
            if name in {"first_name", "last_name", "birth_date", "email", "phone"}:
                field.required = True


class MultipleFileInput(forms.FileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        if not data:
            return []
        if not isinstance(data, (list, tuple)):
            data = [data]
        clean_file = super().clean
        return [clean_file(file, initial) for file in data]


class PasswordResetRequestForm(PasswordResetForm):
    """Password reset request form styled for the public marketplace pages."""

    def save(self, **kwargs):
        if settings.SITE_URL:
            site = urlsplit(settings.SITE_URL)
            kwargs.update(domain_override=site.netloc, use_https=site.scheme == "https")
        return super().save(**kwargs)

    def send_mail(self, subject_template_name, email_template_name, context,
                  from_email, to_email, html_email_template_name=None):
        from .services import queue_email

        subject = "".join(render_to_string(subject_template_name, context).splitlines())
        queue_email(
            to_email, subject, render_to_string(email_template_name, context),
            user=context["user"],
            html_body=render_to_string(html_email_template_name, context) if html_email_template_name else "",
            expires_at=timezone.now() + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT),
        )

    email = forms.EmailField(
        label="อีเมล",
        widget=forms.EmailInput(
            attrs={
                "placeholder": "อีเมลที่ใช้สมัครสมาชิก",
                "autocomplete": "email",
                "inputmode": "email",
            }
        ),
    )


class BaseSignupForm(StyledFormMixin, UserCreationForm):
    accept_terms = forms.BooleanField(initial=True, widget=forms.HiddenInput())
    accept_privacy = forms.BooleanField(initial=True, widget=forms.HiddenInput())

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "birth_date",
            "username",
            "email",
            "phone",
            "password1",
            "password2",
        ]
        labels = {
            "first_name": "ชื่อ",
            "last_name": "นามสกุล",
            "birth_date": "วันเกิด",
            "username": "ชื่อผู้ใช้",
            "email": "อีเมล",
            "phone": "เบอร์โทรศัพท์",
        }
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date"}),
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

    def clean_birth_date(self):
        birth_date = self.cleaned_data["birth_date"]
        if birth_date > timezone.localdate():
            raise forms.ValidationError("วันเกิดต้องไม่เป็นวันในอนาคต")
        return birth_date

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        user.birth_date = self.cleaned_data["birth_date"]
        user.display_name = " ".join(part for part in [user.first_name, user.last_name] if part)
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
        document = self.cleaned_data.get("verification_document")
        return validate_upload(document) if isinstance(document, UploadedFile) else document

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("community"):
            self.add_error("community", "กรุณาเลือกชุมชนหรือสหกรณ์")
        return cleaned_data


class SellerStoreDetailsForm(StyledFormMixin, forms.ModelForm):
    """Store text fields saved independently from optional cover media."""

    class Meta:
        model = FarmerProfile
        fields = ["farm_name", "province", "district", "address", "bio"]
        labels = {
            "farm_name": "ชื่อร้าน/ฟาร์ม",
            "province": "จังหวัด",
            "district": "อำเภอ/เขต",
            "address": "ที่อยู่ร้าน",
            "bio": "คำอธิบายหน้าร้าน",
        }
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
            "bio": forms.Textarea(attrs={"rows": 4, "placeholder": "แนะนำร้านค้า จุดเด่น หรือวิธีดูแลสินค้า"}),
        }


class SellerStoreProfileForm(SellerStoreDetailsForm):
    """Store details together with optional cover media for the settings UI."""

    store_cover_slides = MultipleFileField(
        label="เพิ่มรูปสไลด์หน้าร้าน",
        required=False,
        validators=[
            FileExtensionValidator(["jpg", "jpeg", "png", "webp"]),
            validate_store_image_size,
        ],
        widget=MultipleFileInput(
            attrs={
                "accept": "image/jpeg,image/png,image/webp",
                "data-store-cover-slides-input": "",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields([
            "farm_name",
            "province",
            "district",
            "address",
            "bio",
            "store_cover",
            "store_cover_slides",
        ])

    class Meta(SellerStoreDetailsForm.Meta):
        fields = [*SellerStoreDetailsForm.Meta.fields, "store_cover"]
        labels = {
            **SellerStoreDetailsForm.Meta.labels,
            "store_cover": "รูปปกหน้าร้าน",
        }
        widgets = {
            **SellerStoreDetailsForm.Meta.widgets,
            "store_cover": forms.FileInput(
                attrs={
                    "accept": "image/jpeg,image/png,image/webp",
                    "data-store-cover-input": "",
                }
            ),
        }


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
        for name in ["email", "phone"]:
            self.fields[name].required = True
        for name in ["first_name", "last_name", "gender", "birth_date"]:
            self.fields[name].required = False

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if avatar and avatar.size > AVATAR_MAX_SIZE:
            raise forms.ValidationError("รูปโปรไฟล์ต้องมีขนาดไม่เกิน 5 MB")
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
    class RecipientScope:
        ALL = "all"
        CONSUMERS = "consumers"
        FARMERS = "farmers"
        STAFF = "staff"
        SELECTED = "selected"

    recipient_scope = forms.ChoiceField(
        label="กลุ่มผู้รับ",
        choices=[
            (RecipientScope.ALL, "สมาชิกทั้งหมด"),
            (RecipientScope.CONSUMERS, "ผู้บริโภค"),
            (RecipientScope.FARMERS, "เกษตรกร"),
            (RecipientScope.STAFF, "เจ้าหน้าที่"),
            (RecipientScope.SELECTED, "เลือกเป็นรายคน"),
        ],
        initial=RecipientScope.ALL,
        widget=forms.RadioSelect,
    )
    recipients = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        label="ผู้รับ",
        required=False,
        widget=forms.SelectMultiple(attrs={"size": 8}),
    )
    title = forms.CharField(label="หัวข้อ", max_length=200)
    message = forms.CharField(
        label="ข้อความ",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    link = forms.CharField(label="ลิงก์", required=False, max_length=500)
    send_email = forms.BooleanField(
        label="ส่งอีเมลด้วย",
        required=False,
        help_text="ใช้สำหรับประกาศสำคัญเท่านั้น",
    )

    def __init__(self, *args, recipients=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["recipients"].queryset = recipients or User.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("recipient_scope") == self.RecipientScope.SELECTED
            and not cleaned_data.get("recipients")
        ):
            self.add_error("recipients", "กรุณาเลือกผู้รับอย่างน้อย 1 คน")
        return cleaned_data

    def selected_recipients(self):
        recipients = self.fields["recipients"].queryset
        scope = self.cleaned_data["recipient_scope"]
        if scope == self.RecipientScope.SELECTED:
            return self.cleaned_data["recipients"]
        if scope == self.RecipientScope.CONSUMERS:
            return recipients.filter(role=User.Roles.CONSUMER)
        if scope == self.RecipientScope.FARMERS:
            return recipients.filter(role=User.Roles.FARMER)
        if scope == self.RecipientScope.STAFF:
            return recipients.filter(role=User.Roles.COOPERATIVE_STAFF)
        return recipients


class NewsPostForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = NewsPost
        fields = [
            "title",
            "slug",
            "summary",
            "body",
            "audience",
            "is_published",
            "is_important",
            "published_at",
        ]
        labels = {
            "title": "หัวข้อข่าว",
            "slug": "Slug",
            "summary": "สรุปข่าว",
            "body": "เนื้อหา",
            "audience": "กลุ่มผู้อ่าน",
            "is_published": "เผยแพร่",
            "is_important": "ข่าวสำคัญ (ส่งอีเมล)",
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
class SupportTicketCreateForm(StyledFormMixin, forms.Form):
    category = forms.ChoiceField(label="หัวข้อที่ต้องการสอบถาม", choices=SupportTicket.Category.choices)
    subject = forms.CharField(label="เรื่องที่ต้องการสอบถาม", max_length=200)
    message = forms.CharField(
        label="รายละเอียด",
        max_length=3000,
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": "อธิบายปัญหาหรือสิ่งที่ต้องการให้ผู้ดูแลช่วย"}),
    )

    def clean_message(self):
        message = self.cleaned_data["message"].strip()
        if not message:
            raise forms.ValidationError("กรุณาระบุรายละเอียด")
        return message


class SupportMessageForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SupportMessage
        fields = ["body"]
        labels = {"body": "ข้อความ"}
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 1,
                    "maxlength": 3000,
                    "placeholder": "พิมพ์ข้อความ",
                    "enterkeyhint": "send",
                }
            )
        }

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("กรุณาพิมพ์ข้อความ")
        return body

class DirectMessageForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = DirectMessage
        fields = ["body", "attachment"]
        labels = {"body": "ข้อความ", "attachment": "รูปภาพหรือวิดีโอ"}
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 1,
                    "maxlength": 2000,
                    "placeholder": "พิมพ์ข้อความถึงผู้ขาย",
                }
            ),
            "attachment": forms.FileInput(
                attrs={"accept": "image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm"}
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        body = (cleaned_data.get("body") or "").strip()
        attachment = cleaned_data.get("attachment")
        if not body and not attachment:
            raise forms.ValidationError("กรุณาพิมพ์ข้อความหรือแนบรูปภาพหรือวิดีโอ")
        cleaned_data["body"] = body
        return cleaned_data
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
