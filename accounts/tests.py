from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.test import override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.test import Client, TestCase
from django.urls import reverse

from catalog.models import Product, StockMovement
from orders.models import Order

from .models import Community, CommunityStaffProfile, Conversation, DirectMessage, FarmerProfile, LoginAttempt, User


class LoginSeparationTests(TestCase):
    def test_admin_dashboard_hides_add_link_for_system_email_log(self):
        owner = User.objects.create_user(
            username="email-log-owner",
            password="pass12345",
            is_staff=True,
            is_superuser=True,
            role=User.Roles.OWNER,
        )
        login_response = self.client.post(
            reverse("admin:login"),
            {
                "username": owner.username,
                "password": "pass12345",
                "next": reverse("admin:index"),
            },
        )
        self.assertEqual(login_response.status_code, 302)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("admin:accounts_emaildelivery_changelist"))
        self.assertNotContains(response, reverse("admin:accounts_emaildelivery_add"))
        self.assertEqual(
            self.client.get(reverse("admin:accounts_emaildelivery_add")).status_code,
            403,
        )
    def test_admin_login_shortcut_goes_to_django_admin_login(self):
        response = self.client.get(reverse("admin_login"))

        self.assertRedirects(
            response,
            f"{reverse('admin:login')}?next={reverse('admin:index')}",
            fetch_redirect_response=False,
        )

    def test_public_login_does_not_logout_authenticated_consumer(self):
        consumer = User.objects.create_user(
            username="consumer-login",
            password="pass12345",
            role=User.Roles.CONSUMER,
        )
        self.client.force_login(consumer)

        response = self.client.get(reverse("login"))

        self.assertRedirects(response, reverse("catalog:product_list"), fetch_redirect_response=False)
        self.assertEqual(str(self.client.session.get("_auth_user_id")), str(consumer.pk))

    @override_settings(REQUIRE_EMAIL_VERIFICATION=False)
    def test_public_login_redirects_new_session_to_homepage(self):
        consumer = User.objects.create_user(
            username="consumer-home-login",
            password="pass12345",
            role=User.Roles.CONSUMER,
        )

        response = self.client.post(
            reverse("login"),
            {"username": consumer.username, "password": "pass12345"},
        )

        self.assertRedirects(response, reverse("catalog:product_list"), fetch_redirect_response=False)

    @override_settings(REQUIRE_EMAIL_VERIFICATION=False)
    def test_public_login_keeps_safe_next_destination(self):
        consumer = User.objects.create_user(
            username="consumer-next-login",
            password="pass12345",
            role=User.Roles.CONSUMER,
        )

        response = self.client.post(
            reverse("login"),
            {
                "username": consumer.username,
                "password": "pass12345",
                "next": reverse("orders:cart"),
            },
        )

        self.assertRedirects(response, reverse("orders:cart"), fetch_redirect_response=False)

    def test_public_login_does_not_logout_authenticated_admin(self):
        admin_user = User.objects.create_user(
            username="admin-login",
            password="pass12345",
            is_staff=True,
            is_superuser=True,
            role=User.Roles.OWNER,
        )
        self.client.force_login(admin_user)

        response = self.client.get(reverse("login"))

        self.assertRedirects(response, reverse("admin:index"), fetch_redirect_response=False)
        self.assertEqual(str(self.client.session.get("_auth_user_id")), str(admin_user.pk))

    def test_staff_account_is_not_logged_into_public_site(self):
        admin_user = User.objects.create_user(
            username="staff-only",
            password="pass12345",
            is_staff=True,
            role=User.Roles.OWNER,
        )

        response = self.client.post(
            reverse("login"),
            {"username": admin_user.username, "password": "pass12345"},
        )

        self.assertRedirects(response, reverse("admin_login"), fetch_redirect_response=False)
        self.assertIsNone(self.client.session.get("_auth_user_id"))

    def test_admin_login_uses_separate_session_cookie_from_public_site(self):
        consumer = User.objects.create_user(
            username="consumer-same-browser",
            password="pass12345",
            role=User.Roles.CONSUMER,
        )
        admin_user = User.objects.create_user(
            username="admin-same-browser",
            password="pass12345",
            is_staff=True,
            is_superuser=True,
            role=User.Roles.OWNER,
        )
        self.client.force_login(consumer)
        public_session_key = self.client.cookies[settings.SESSION_COOKIE_NAME].value

        response = self.client.post(
            reverse("admin:login"),
            {
                "username": admin_user.username,
                "password": "pass12345",
                "next": reverse("admin:index"),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(settings.SESSION_COOKIE_NAME, self.client.cookies)
        self.assertIn(settings.ADMIN_SESSION_COOKIE_NAME, self.client.cookies)
        self.assertEqual(self.client.cookies[settings.SESSION_COOKIE_NAME].value, public_session_key)
        self.assertNotEqual(
            self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            self.client.cookies[settings.ADMIN_SESSION_COOKIE_NAME].value,
        )

        public_response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(public_response, str(consumer))

        admin_response = self.client.get(reverse("admin:index"))
        self.assertEqual(admin_response.status_code, 200)

    def test_admin_and_public_login_pages_use_different_csrf_cookies(self):
        client = Client(enforce_csrf_checks=True)

        client.get(reverse("login"))
        client.get(reverse("admin:login"))

        self.assertIn(settings.CSRF_COOKIE_NAME, client.cookies)
        self.assertIn(settings.ADMIN_CSRF_COOKIE_NAME, client.cookies)
        self.assertNotEqual(
            client.cookies[settings.CSRF_COOKIE_NAME].value,
            client.cookies[settings.ADMIN_CSRF_COOKIE_NAME].value,
        )

class AccountSecurityTests(TestCase):
    @override_settings(REQUIRE_EMAIL_VERIFICATION=True)
    def test_unverified_user_cannot_log_in_until_email_is_verified(self):
        user = User.objects.create_user(
            username="verify-user",
            password="pass12345",
            email="verify@example.com",
            role=User.Roles.CONSUMER,
        )

        response = self.client.post(
            reverse("login"),
            {"username": user.username, "password": "pass12345"},
        )
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
        self.assertIsNone(self.client.session.get("_auth_user_id"))

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        response = self.client.get(reverse("accounts:verify_email", args=[uid, token]))
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)

        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)

    @override_settings(LOGIN_MAX_ATTEMPTS=3, LOGIN_LOCKOUT_MINUTES=15)
    def test_repeated_failed_logins_temporarily_block_source(self):
        user = User.objects.create_user(
            username="locked-user",
            password="pass12345",
            role=User.Roles.CONSUMER,
        )
        for _ in range(3):
            self.client.post(reverse("login"), {"username": user.username, "password": "wrong-password"})

        response = self.client.post(
            reverse("login"),
            {"username": user.username, "password": "pass12345"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.session.get("_auth_user_id"))
        self.assertEqual(LoginAttempt.objects.get().failed_attempts, 3)


class StaffPortalSeparationTests(TestCase):
    password = "AdminPass123!"

    def setUp(self):
        self.community = Community.objects.create(
            name="วิสาหกิจชุมชนหนึ่ง",
            slug="community-one",
            province="เชียงใหม่",
        )
        self.other_community = Community.objects.create(
            name="วิสาหกิจชุมชนสอง",
            slug="community-two",
            province="ลำพูน",
        )
        self.staff = User.objects.create_user(
            username="community-officer",
            password=self.password,
            role=User.Roles.COOPERATIVE_STAFF,
        )
        CommunityStaffProfile.objects.create(
            user=self.staff,
            community=self.community,
            title="เจ้าหน้าที่ตรวจสอบ",
        )
        self.farmer = User.objects.create_user(
            username="farmer-one",
            password=self.password,
            role=User.Roles.FARMER,
        )
        FarmerProfile.objects.create(
            user=self.farmer,
            community=self.community,
            farm_name="สวนชุมชนหนึ่ง",
        )
        self.other_farmer = User.objects.create_user(
            username="farmer-two",
            password=self.password,
            role=User.Roles.FARMER,
        )
        FarmerProfile.objects.create(
            user=self.other_farmer,
            community=self.other_community,
            farm_name="สวนชุมชนสอง",
        )
        self.product = Product.objects.create(
            seller=self.farmer,
            community=self.community,
            name="ผักชุมชนหนึ่ง",
            description="สินค้าสำหรับทดสอบ",
            price="40.00",
            stock_quantity="10.00",
        )
        self.other_product = Product.objects.create(
            seller=self.other_farmer,
            community=self.other_community,
            name="ผักชุมชนสอง",
            description="สินค้าต่างชุมชน",
            price="45.00",
            stock_quantity="8.00",
        )

    @override_settings(REQUIRE_EMAIL_VERIFICATION=False)
    def test_staff_logs_in_to_homepage_and_can_open_dedicated_portal(self):
        response = self.client.post(
            reverse("login"),
            {"username": self.staff.username, "password": self.password},
        )

        self.assertRedirects(
            response,
            reverse("catalog:product_list"),
            fetch_redirect_response=False,
        )
        response = self.client.get(reverse("accounts:staff_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ศูนย์เจ้าหน้าที่วิสาหกิจชุมชน")
        self.assertContains(response, self.community.name)
        self.assertContains(response, self.product.name)
        self.assertNotContains(response, self.other_product.name)

    def test_staff_role_never_receives_django_admin_access(self):
        owner = User.objects.create_user(
            username="system-owner",
            password=self.password,
            role=User.Roles.OWNER,
        )

        self.staff.refresh_from_db()
        owner.refresh_from_db()

        self.assertFalse(self.staff.is_staff)
        self.assertTrue(owner.is_staff)

        response = self.client.post(
            reverse("admin:login"),
            {
                "username": self.staff.username,
                "password": self.password,
                "next": reverse("admin:index"),
            },
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse("admin:index"))
        self.assertRedirects(
            response,
            f"{reverse('admin:login')}?next={reverse('admin:index')}",
            fetch_redirect_response=False,
        )

    def test_staff_dashboard_redirects_from_general_dashboard(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("accounts:dashboard"))

        self.assertRedirects(
            response,
            reverse("accounts:staff_dashboard"),
            fetch_redirect_response=False,
        )

    def test_consumer_cannot_open_staff_portal(self):
        consumer = User.objects.create_user(
            username="consumer-no-staff",
            password=self.password,
            role=User.Roles.CONSUMER,
        )
        self.client.force_login(consumer)

        response = self.client.get(reverse("accounts:staff_dashboard"))

        self.assertRedirects(
            response,
            reverse("accounts:dashboard"),
            fetch_redirect_response=False,
        )

    def test_owner_role_can_open_django_admin(self):
        owner = User.objects.create_user(
            username="system-owner-full",
            password=self.password,
            role=User.Roles.OWNER,
        )
        response = self.client.post(
            reverse("admin:login"),
            {
                "username": owner.username,
                "password": self.password,
                "next": reverse("admin:index"),
            },
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ศูนย์เจ้าของระบบ")
        self.assertContains(response, "การชำระเงิน")
    def test_staff_can_view_and_edit_seller_in_own_community(self):
        self.client.force_login(self.staff)

        response = self.client.get(
            reverse("accounts:staff_seller_detail", args=[self.farmer.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)
        self.assertNotContains(response, self.other_product.name)

        response = self.client.post(
            reverse("accounts:staff_seller_edit", args=[self.farmer.pk]),
            {
                "account-display_name": "ผู้ขายที่แก้ไขแล้ว",
                "account-email": "updated-farmer@example.com",
                "account-phone": "0891112222",
                "account-first_name": "สมชาย",
                "account-last_name": "ชาวสวน",
                "account-is_active": "on",
                "farm-farm_name": "สวนที่แก้ไขแล้ว",
                "farm-province": "เชียงใหม่",
                "farm-district": "เมือง",
                "farm-address": "ที่อยู่ใหม่",
                "farm-bio": "ข้อมูลฟาร์มใหม่",
                "farm-document_type": FarmerProfile.DocumentType.FARM_REGISTRATION,
                "farm-verification_status": FarmerProfile.VerificationStatus.VERIFIED,
                "farm-rejection_reason": "",
            },
        )
        self.assertRedirects(
            response,
            reverse("accounts:staff_seller_detail", args=[self.farmer.pk]),
            fetch_redirect_response=False,
        )

        self.farmer.refresh_from_db()
        profile = self.farmer.farmer_profile
        profile.refresh_from_db()
        self.assertEqual(self.farmer.display_name, "ผู้ขายที่แก้ไขแล้ว")
        self.assertEqual(profile.farm_name, "สวนที่แก้ไขแล้ว")
        self.assertEqual(
            profile.verification_status,
            FarmerProfile.VerificationStatus.VERIFIED,
        )
        self.assertEqual(profile.verified_by, self.staff)

    def test_staff_cannot_open_or_edit_seller_from_other_community(self):
        self.client.force_login(self.staff)

        response = self.client.get(
            reverse("accounts:staff_seller_detail", args=[self.other_farmer.pk])
        )
        self.assertEqual(response.status_code, 404)

        response = self.client.post(
            reverse("accounts:staff_seller_edit", args=[self.other_farmer.pk]),
            {
                "account-display_name": "ไม่ควรถูกแก้",
                "account-email": "blocked@example.com",
                "account-phone": "0800000000",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.other_farmer.refresh_from_db()
        self.assertNotEqual(self.other_farmer.display_name, "ไม่ควรถูกแก้")

    def test_staff_can_edit_product_and_stock_only_in_own_community(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("catalog:product_update", args=[self.product.pk]),
            {
                "category": "",
                "name": "ผักชุมชนหนึ่งแก้ไขแล้ว",
                "description": "แก้ไขโดยเจ้าหน้าที่",
                "unit": Product.Unit.KG,
                "price": "55.00",
                "stock_quantity": "15.00",
                "minimum_order_quantity": "1.00",
                "low_stock_threshold": "3.00",
                "weight_grams": "",
                "harvest_date": "",
                "expiry_date": "",
            },
        )
        self.assertRedirects(
            response,
            self.product.get_absolute_url(),
            fetch_redirect_response=False,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "ผักชุมชนหนึ่งแก้ไขแล้ว")
        self.assertEqual(str(self.product.stock_quantity), "15.00")
        movement = StockMovement.objects.get(product=self.product)
        self.assertEqual(str(movement.quantity_change), "5.00")

        original_name = self.other_product.name
        response = self.client.post(
            reverse("catalog:product_update", args=[self.other_product.pk]),
            {
                "name": "ไม่ควรถูกแก้",
                "description": "ต่างชุมชน",
                "unit": Product.Unit.KG,
                "price": "1.00",
                "stock_quantity": "1.00",
                "minimum_order_quantity": "1.00",
                "low_stock_threshold": "1.00",
            },
        )
        self.assertRedirects(
            response,
            reverse("accounts:staff_dashboard"),
            fetch_redirect_response=False,
        )
        self.other_product.refresh_from_db()
        self.assertEqual(self.other_product.name, original_name)
    def test_staff_can_manage_orders_only_for_sellers_in_own_community(self):
        buyer = User.objects.create_user(
            username="order-buyer",
            password=self.password,
            role=User.Roles.CONSUMER,
        )
        own_order = Order.objects.create(
            buyer=buyer,
            seller=self.farmer,
            community=self.community,
            status=Order.Status.PAID,
            payment_status=Order.PaymentStatus.PAID,
            shipping_name="ผู้รับหนึ่ง",
            shipping_phone="0811111111",
            shipping_address="เชียงใหม่",
        )
        other_order = Order.objects.create(
            buyer=buyer,
            seller=self.other_farmer,
            community=self.other_community,
            status=Order.Status.PAID,
            payment_status=Order.PaymentStatus.PAID,
            shipping_name="ผู้รับสอง",
            shipping_phone="0822222222",
            shipping_address="ลำพูน",
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("orders:order_update_status", args=[own_order.pk]),
            {
                "status": Order.Status.CONFIRMED,
                "shipping_carrier": "",
                "tracking_number": "",
                "status_note": "ตรวจสอบโดยเจ้าหน้าที่",
            },
        )
        self.assertRedirects(
            response,
            own_order.get_absolute_url(),
            fetch_redirect_response=False,
            msg_prefix=str(
                response.context["form"].errors
                if response.status_code == 200
                else ""
            ),
        )
        own_order.refresh_from_db()
        self.assertEqual(own_order.status, Order.Status.CONFIRMED)

        response = self.client.post(
            reverse("orders:order_update_status", args=[other_order.pk]),
            {
                "status": Order.Status.CONFIRMED,
                "status_note": "ไม่ควรถูกแก้",
            },
        )
        self.assertRedirects(
            response,
            other_order.get_absolute_url(),
            fetch_redirect_response=False,
        )
        other_order.refresh_from_db()
        self.assertEqual(other_order.status, Order.Status.PAID)

class BuyerSellerConversationTests(TestCase):
    def setUp(self):
        self.community = Community.objects.create(
            name="ชุมชนทดสอบแชท",
            slug="chat-community",
            province="เชียงใหม่",
        )
        self.buyer = User.objects.create_user(
            username="chat-buyer",
            password="pass12345",
            role=User.Roles.CONSUMER,
        )
        self.seller = User.objects.create_user(
            username="chat-seller",
            password="pass12345",
            role=User.Roles.FARMER,
        )
        FarmerProfile.objects.create(
            user=self.seller,
            community=self.community,
            farm_name="สวนแชท",
            verification_status=FarmerProfile.VerificationStatus.VERIFIED,
        )
        self.outsider = User.objects.create_user(
            username="chat-outsider",
            password="pass12345",
            role=User.Roles.CONSUMER,
        )
        self.product = Product.objects.create(
            seller=self.seller,
            community=self.community,
            name="ผักสดสำหรับแชท",
            description="สินค้าเกษตรชุมชน",
            price="35.00",
            stock_quantity="10.00",
            status=Product.Status.ACTIVE,
        )

    def test_buyer_can_start_conversation_and_send_message(self):
        self.client.force_login(self.buyer)
        response = self.client.post(
            reverse("accounts:conversation_start", args=[self.product.pk])
        )
        conversation = Conversation.objects.get(
            buyer=self.buyer,
            seller=self.seller,
            product=self.product,
        )
        self.assertRedirects(
            response,
            reverse("accounts:conversation_detail", args=[conversation.pk]),
        )

        response = self.client.post(
            reverse("accounts:conversation_detail", args=[conversation.pk]),
            {"body": "สินค้านี้เก็บเกี่ยววันนี้ไหม"},
        )

        self.assertRedirects(
            response,
            reverse("accounts:conversation_detail", args=[conversation.pk]),
        )
        self.assertTrue(
            DirectMessage.objects.filter(
                conversation=conversation,
                sender=self.buyer,
                body="สินค้านี้เก็บเกี่ยววันนี้ไหม",
            ).exists()
        )

    def test_third_party_cannot_open_conversation(self):
        conversation = Conversation.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            product=self.product,
        )
        self.client.force_login(self.outsider)

        response = self.client.get(
            reverse("accounts:conversation_detail", args=[conversation.pk])
        )

        self.assertEqual(response.status_code, 404)