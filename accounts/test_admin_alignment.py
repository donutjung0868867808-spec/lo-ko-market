from django.contrib import admin
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase
from django.urls import reverse

from catalog.models import ProductFavorite, ProductReview, SellerFavorite
from orders.admin import OrderAdminForm
from orders.models import Coupon, CouponRedemption, Order, OrderStatusHistory
from payments.models import (
    CustomerPaymentProfile,
    Payment,
    Refund,
    SavedPaymentMethod,
    SellerPaymentAccount,
    StripeEvent,
)

from .models import Community, DeliveryAddress, User


class AdminAlignmentTests(TestCase):
    password = "AdminPass123!"

    def setUp(self):
        self.owner = User.objects.create_user(
            username="alignment-owner",
            password=self.password,
            email="alignment-owner@example.com",
            role=User.Roles.OWNER,
        )
        self.request = RequestFactory().get("/admin/")
        self.request.user = self.owner

    def test_admin_uses_main_system_models_without_django_groups(self):
        self.assertNotIn(Group, admin.site._registry)
        self.assertIn(DeliveryAddress, admin.site._registry)
        self.assertIn(CustomerPaymentProfile, admin.site._registry)
        self.assertIn(SavedPaymentMethod, admin.site._registry)
        self.assertNotIn(Coupon, admin.site._registry)
        self.assertNotIn(CouponRedemption, admin.site._registry)

    def test_user_admin_matches_main_profile_fields(self):
        user_admin = admin.site._registry[User]
        fieldsets = user_admin.get_fieldsets(self.request, self.owner)
        fields = {
            field
            for _, options in fieldsets
            for field in options.get("fields", ())
        }

        self.assertTrue(
            {
                "avatar",
                "display_name",
                "first_name",
                "last_name",
                "email",
                "phone",
                "gender",
                "birth_date",
                "role",
                "is_active",
            }.issubset(fields)
        )
        self.assertTrue(
            {"groups", "user_permissions", "is_staff", "is_superuser"}.isdisjoint(fields)
        )

    def test_system_generated_records_cannot_be_added_or_edited_manually(self):
        generated_models = (
            ProductReview,
            ProductFavorite,
            SellerFavorite,
            Payment,
            Refund,
            CustomerPaymentProfile,
            SavedPaymentMethod,
            StripeEvent,
            SellerPaymentAccount,
        )
        for model in generated_models:
            with self.subTest(model=model._meta.label):
                model_admin = admin.site._registry[model]
                self.assertFalse(model_admin.has_add_permission(self.request))
                self.assertFalse(model_admin.has_change_permission(self.request))

    def test_setting_default_address_from_admin_keeps_only_one_default(self):
        first = DeliveryAddress.objects.create(
            user=self.owner,
            label="บ้าน",
            recipient_name="ผู้รับคนแรก",
            phone="0811111111",
            address_line="1 ถนนหลัก",
            subdistrict="ในเมือง",
            district="เมือง",
            province="ขอนแก่น",
            postal_code="40000",
            is_default=True,
        )
        second = DeliveryAddress(
            user=self.owner,
            label="ที่ทำงาน",
            recipient_name="ผู้รับคนที่สอง",
            phone="0822222222",
            address_line="2 ถนนรอง",
            subdistrict="ในเมือง",
            district="เมือง",
            province="ขอนแก่น",
            postal_code="40000",
            is_default=True,
        )

        address_admin = admin.site._registry[DeliveryAddress]
        address_admin.save_model(self.request, second, form=None, change=False)

        first.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)

    def test_order_admin_changes_status_through_main_service(self):
        buyer = User.objects.create_user(
            username="alignment-buyer",
            password=self.password,
            role=User.Roles.CONSUMER,
        )
        seller = User.objects.create_user(
            username="alignment-seller",
            password=self.password,
            role=User.Roles.FARMER,
        )
        community = Community.objects.create(
            name="ชุมชนทดสอบ Admin",
            slug="admin-alignment-community",
            province="ขอนแก่น",
        )
        order = Order.objects.create(
            buyer=buyer,
            seller=seller,
            community=community,
            status=Order.Status.PAID,
            payment_status=Order.PaymentStatus.PAID,
            shipping_name="ผู้ซื้อ",
            shipping_phone="0800000000",
            shipping_address="ขอนแก่น",
        )
        form = OrderAdminForm(
            data={
                "status": Order.Status.CONFIRMED,
                "status_note": "ตรวจสอบจากศูนย์เจ้าของระบบ",
                "shipping_carrier": "",
                "tracking_number": "",
            },
            instance=order,
        )
        self.assertTrue(form.is_valid(), form.errors)

        order_admin = admin.site._registry[Order]
        order_admin.save_model(self.request, form.save(commit=False), form, change=True)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CONFIRMED)
        self.assertTrue(
            OrderStatusHistory.objects.filter(
                order=order,
                status=Order.Status.CONFIRMED,
                changed_by=self.owner,
            ).exists()
        )

    def test_admin_dashboard_explains_workflows_in_thai(self):
        response = self.client.post(
            reverse("admin:login"),
            {
                "username": self.owner.username,
                "password": self.password,
                "next": reverse("admin:index"),
            },
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, "ข้อมูลส่วนตัว บทบาท และสถานะสมาชิก")
        self.assertContains(response, "ที่อยู่จัดส่งที่สมาชิกบันทึกไว้")
        self.assertContains(response, "ดูอย่างเดียว")
        self.assertContains(response, "รายการที่ควรรู้วันนี้")
        self.assertNotContains(response, "รหัสส่วนลด")
        self.assertNotContains(response, ">กลุ่ม<")

        list_response = self.client.get(reverse("admin:accounts_user_changelist"))
        self.assertContains(list_response, "owner-back-button")
