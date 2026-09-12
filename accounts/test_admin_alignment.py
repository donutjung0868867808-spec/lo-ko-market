from decimal import Decimal

from django.contrib import admin
from django.contrib.auth.models import Group
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from catalog.models import ProductFavorite, ProductReview, SellerFavorite
from orders.admin import OrderAdminForm
from orders.models import Coupon, CouponRedemption, Order, OrderStatusHistory, Shipment
from payments.models import (
    CustomerPaymentProfile,
    Payment,
    Refund,
    SavedPaymentMethod,
    SellerPaymentAccount,
    StripeEvent,
)

from .models import AuditEvent, Community, Conversation, DeliveryAddress, Notification, User


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
        self.assertIn(Shipment, admin.site._registry)
        self.assertNotIn(Coupon, admin.site._registry)
        self.assertNotIn(CouponRedemption, admin.site._registry)

    def test_shipments_are_available_to_owner_as_read_only_records(self):
        shipment_admin = admin.site._registry[Shipment]

        self.assertTrue(shipment_admin.has_view_permission(self.request))
        self.assertFalse(shipment_admin.has_add_permission(self.request))
        self.assertFalse(shipment_admin.has_change_permission(self.request))
        self.assertFalse(shipment_admin.has_delete_permission(self.request))

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

    def _request_with_messages(self, data):
        request = RequestFactory().post("/admin/accounts/user/", data)
        request.user = self.owner
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_owner_can_suspend_and_restore_member_with_audit_trail(self):
        member = User.objects.create_user(
            username="moderated-member",
            password=self.password,
            email="moderated@example.com",
            role=User.Roles.CONSUMER,
        )
        user_admin = admin.site._registry[User]

        suspend_request = self._request_with_messages(
            {"suspension_reason": "ตรวจพบการใช้งานผิดเงื่อนไข"}
        )
        user_admin.suspend_selected_users(
            suspend_request,
            User.objects.filter(pk=member.pk),
        )

        member.refresh_from_db()
        self.assertFalse(member.is_active)
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.owner,
                action=AuditEvent.Action.BLOCK,
                target_id=str(member.pk),
                description="ตรวจพบการใช้งานผิดเงื่อนไข",
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=member,
                title="บัญชีถูกระงับการใช้งาน",
            ).exists()
        )

        restore_request = self._request_with_messages(
            {"suspension_reason": "ตรวจสอบข้อมูลเรียบร้อยแล้ว"}
        )
        user_admin.restore_selected_users(
            restore_request,
            User.objects.filter(pk=member.pk),
        )

        member.refresh_from_db()
        self.assertTrue(member.is_active)
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.owner,
                action=AuditEvent.Action.UNBLOCK,
                target_id=str(member.pk),
            ).exists()
        )

    def test_owner_can_toggle_a_member_status_from_the_change_form(self):
        member = User.objects.create_user(
            username="toggle-member",
            password=self.password,
            role=User.Roles.CONSUMER,
        )
        user_admin = admin.site._registry[User]

        self.assertNotIn("is_active", user_admin.get_readonly_fields(self.request, member))
        self.assertIn("is_active", user_admin.get_readonly_fields(self.request, self.owner))
        form = user_admin.get_form(self.request, member)(instance=member)
        self.assertEqual(form.fields["is_active"].label, "เปิดใช้งานบัญชี")

        member.is_active = False
        user_admin.save_model(
            self.request,
            member,
            type("StatusChangeForm", (), {"changed_data": ("is_active",)})(),
            change=True,
        )

        member.refresh_from_db()
        self.assertFalse(member.is_active)
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.owner,
                action=AuditEvent.Action.BLOCK,
                target_id=str(member.pk),
                description="ระงับบัญชีจากหน้าข้อมูลผู้ใช้",
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=member,
                title="บัญชีถูกระงับการใช้งาน",
            ).exists()
        )
    def test_conversations_are_available_to_owner_as_read_only_records(self):
        self.assertIn(Conversation, admin.site._registry)
        conversation_admin = admin.site._registry[Conversation]
        self.assertTrue(conversation_admin.has_view_permission(self.request))
        self.assertFalse(conversation_admin.has_add_permission(self.request))
        self.assertFalse(conversation_admin.has_change_permission(self.request))
        self.assertFalse(conversation_admin.has_delete_permission(self.request))
        self.assertEqual(len(conversation_admin.get_inline_instances(self.request)), 1)

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
        self.assertContains(response, "คำขอคืนเงินรอดำเนินการ")
        self.assertContains(response, "ยอดผู้ขายพร้อมโอน")
        self.assertContains(response, "เหตุการณ์ Stripe รอประมวลผล")

        list_response = self.client.get(reverse("admin:accounts_user_changelist"))
        self.assertContains(list_response, "owner-back-button")

    @override_settings(
        DEBUG=True,
        STRIPE_SECRET_KEY="",
        ADMIN_MFA_REQUIRED=False,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_refund_can_be_processed_from_admin(self):
        buyer = User.objects.create_user(
            username="admin-refund-buyer",
            password=self.password,
            role=User.Roles.CONSUMER,
        )
        seller = User.objects.create_user(
            username="admin-refund-seller",
            password=self.password,
            role=User.Roles.FARMER,
        )
        community = Community.objects.create(
            name="ชุมชนคืนเงินผ่าน Admin",
            slug="admin-refund-community",
            province="สกลนคร",
        )
        order = Order.objects.create(
            buyer=buyer,
            seller=seller,
            community=community,
            status=Order.Status.PAID,
            payment_status=Order.PaymentStatus.PAID,
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            shipping_name="ผู้ซื้อทดสอบ",
            shipping_phone="0800000000",
            shipping_address="สกลนคร",
        )
        payment = Payment.objects.create(
            order=order,
            status=Payment.Status.PAID,
            amount=Decimal("100.00"),
            currency="thb",
            payment_intent_id="pi_admin_refund",
        )
        refund = Refund.objects.create(
            payment=payment,
            amount=Decimal("100.00"),
            reason="สินค้าเสียหาย",
            requested_by=buyer,
        )
        self.client.post(
            reverse("admin:login"),
            {
                "username": self.owner.username,
                "password": self.password,
                "next": reverse("admin:index"),
            },
        )

        change_response = self.client.get(
            reverse("admin:payments_refund_change", args=[refund.pk])
        )
        self.assertContains(change_response, "อนุมัติและคืนเงิน")
        self.assertContains(change_response, "ปฏิเสธคำขอ")

        response = self.client.post(
            reverse("admin:payments_refund_process", args=[refund.pk])
        )
        self.assertRedirects(
            response,
            reverse("admin:payments_refund_change", args=[refund.pk]),
        )
        refund.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.SUCCEEDED)
        self.assertEqual(refund.handled_by, self.owner)

    @override_settings(ADMIN_MFA_REQUIRED=False)
    def test_refund_can_be_rejected_from_admin_with_reason(self):
        buyer = User.objects.create_user(
            username="admin-reject-buyer",
            password=self.password,
            role=User.Roles.CONSUMER,
        )
        seller = User.objects.create_user(
            username="admin-reject-seller",
            password=self.password,
            role=User.Roles.FARMER,
        )
        community = Community.objects.create(
            name="ชุมชนปฏิเสธคืนเงินผ่าน Admin",
            slug="admin-reject-refund-community",
            province="นครพนม",
        )
        order = Order.objects.create(
            buyer=buyer,
            seller=seller,
            community=community,
            status=Order.Status.PAID,
            payment_status=Order.PaymentStatus.PAID,
            subtotal=Decimal("80.00"),
            total_amount=Decimal("80.00"),
            shipping_name="ผู้ซื้อทดสอบ",
            shipping_phone="0800000001",
            shipping_address="นครพนม",
        )
        payment = Payment.objects.create(
            order=order,
            status=Payment.Status.PAID,
            amount=Decimal("80.00"),
            currency="thb",
            payment_intent_id="pi_admin_reject_refund",
        )
        refund = Refund.objects.create(
            payment=payment,
            amount=Decimal("80.00"),
            reason="สินค้ามาถึงช้า",
            requested_by=buyer,
        )
        self.client.post(
            reverse("admin:login"),
            {
                "username": self.owner.username,
                "password": self.password,
                "next": reverse("admin:index"),
            },
        )
        reject_url = reverse("admin:payments_refund_reject", args=[refund.pk])

        self.assertContains(self.client.get(reject_url), "เหตุผลที่ไม่อนุมัติ")
        response = self.client.post(
            reject_url,
            {"resolution_note": "หลักฐานไม่เพียงพอสำหรับการคืนเงิน"},
        )
        self.assertRedirects(
            response,
            reverse("admin:payments_refund_change", args=[refund.pk]),
        )
        refund.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.REJECTED)
        self.assertEqual(refund.handled_by, self.owner)
        self.assertEqual(
            refund.resolution_note,
            "หลักฐานไม่เพียงพอสำหรับการคืนเงิน",
        )
