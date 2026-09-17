from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from orders.views import buyer_initial

from .models import DeliveryAddress, Notification, User


class AccountCenterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="account-owner",
            password="pass12345",
            email="owner@example.com",
            display_name="ผู้ซื้อทดสอบ",
            phone="0812345678",
            role=User.Roles.CONSUMER,
        )
        self.other_user = User.objects.create_user(
            username="other-owner",
            password="pass12345",
            email="other@example.com",
            role=User.Roles.CONSUMER,
        )
        self.client.force_login(self.user)

    def test_account_center_pages_render(self):
        page_names = [

            "accounts:account_history",
            "accounts:addresses",
            "accounts:payment_settings",
            "accounts:notifications",
            "orders:order_list",
        ]

        profile_response = self.client.get(reverse("accounts:profile"))
        self.assertRedirects(profile_response, reverse("accounts:account_history"))

        for page_name in page_names:
            with self.subTest(page_name=page_name):
                response = self.client.get(reverse(page_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "บัญชีของฉัน")
                self.assertContains(response, "การสั่งซื้อของฉัน")

    def test_inner_pages_have_shared_back_button(self):
        inner_page = self.client.get(reverse("accounts:account_history"))
        self.assertContains(inner_page, "data-site-back")
        self.assertContains(inner_page, "ย้อนกลับ")

        homepage = self.client.get(reverse("catalog:product_list"))
        self.assertNotContains(homepage, "data-site-back")

    def test_header_notification_badge_counts_only_unread_items(self):
        Notification.objects.create(user=self.user, title="แจ้งเตือนที่หนึ่ง")
        Notification.objects.create(user=self.user, title="แจ้งเตือนที่สอง")
        Notification.objects.create(user=self.user, title="อ่านแล้ว", is_read=True)
        Notification.objects.create(user=self.other_user, title="ของผู้ใช้อื่น")

        response = self.client.get(reverse("catalog:product_list"))

        self.assertEqual(response.context["unread_notification_count"], 2)
        self.assertContains(response, "data-notification-bell")
        self.assertContains(response, 'data-notification-count="2"')
        self.assertContains(response, reverse("accounts:notifications"))

    def test_seller_menu_is_visible_only_to_farmers(self):
        consumer_page = self.client.get(reverse("catalog:product_list"))
        self.assertNotContains(consumer_page, "หน้าร้านค้าของฉัน")
        self.assertNotContains(consumer_page, "เพิ่มสินค้า")

        farmer = User.objects.create_user(
            username="seller-menu",
            password="pass12345",
            role=User.Roles.FARMER,
        )
        self.client.force_login(farmer)
        farmer_page = self.client.get(reverse("catalog:product_list"))
        self.assertContains(farmer_page, "หน้าร้านค้าของฉัน")
        self.assertContains(farmer_page, reverse("catalog:seller_store", args=[farmer.pk]))
        self.assertContains(farmer_page, "ร้านค้าของฉัน")
        self.assertContains(farmer_page, reverse("accounts:farmer_shop_center"))
        self.assertContains(farmer_page, "เพิ่มสินค้า")
        self.assertContains(farmer_page, reverse("catalog:product_create"))
        self.assertContains(farmer_page, "สลับเป็นผู้ซื้อ")

    def test_farmer_can_switch_between_buyer_and_seller_modes(self):
        farmer = User.objects.create_user(
            username="mode-switcher",
            password="pass12345",
            role=User.Roles.FARMER,
        )
        self.client.force_login(farmer)

        buyer_response = self.client.post(
            reverse("accounts:switch_market_mode", args=["buyer"])
        )
        self.assertRedirects(buyer_response, reverse("catalog:product_list"))

        buyer_page = self.client.get(reverse("catalog:product_list"))
        self.assertContains(buyer_page, "โหมดผู้ซื้อ")
        self.assertContains(buyer_page, "สลับเป็นผู้ขาย")
        self.assertNotContains(buyer_page, "หน้าร้านค้าของฉัน")
        self.assertNotContains(buyer_page, "เพิ่มสินค้า")

        seller_response = self.client.post(
            reverse("accounts:switch_market_mode", args=["seller"])
        )
        self.assertRedirects(seller_response, reverse("accounts:farmer_shop_center"))

        seller_page = self.client.get(reverse("catalog:product_list"))
        self.assertContains(seller_page, "สลับเป็นผู้ซื้อ")
        self.assertContains(seller_page, "หน้าร้านค้าของฉัน")
        self.assertContains(seller_page, "เพิ่มสินค้า")

    def test_account_sidebar_links_consumer_to_seller_signup_and_farmer_to_shop(self):
        consumer_page = self.client.get(reverse("accounts:account_history"))
        self.assertContains(consumer_page, "สมัครเป็นผู้ขาย")
        self.assertContains(consumer_page, reverse("accounts:farmer_signup"))

        farmer = User.objects.create_user(
            username="account-shop-shortcut",
            password="pass12345",
            role=User.Roles.FARMER,
        )
        self.client.force_login(farmer)

        farmer_page = self.client.get(reverse("accounts:account_history"))
        self.assertContains(farmer_page, "ร้านค้าของฉัน")
        self.assertContains(farmer_page, reverse("accounts:farmer_shop_center"))
        self.assertContains(farmer_page, "สลับเป็นผู้ซื้อ")
        self.assertContains(farmer_page, reverse("catalog:product_list"))
        self.assertContains(farmer_page, 'data-lucide="shopping-bag"')

    def test_staff_center_menu_is_visible_only_to_community_staff(self):
        consumer_page = self.client.get(reverse("catalog:product_list"))
        self.assertNotContains(consumer_page, "ศูนย์เจ้าหน้าที่วิสาหกิจชุมชน")

        owner = User.objects.create_user(
            username="owner-menu",
            password="pass12345",
            role=User.Roles.OWNER,
        )
        self.client.force_login(owner)
        owner_page = self.client.get(reverse("catalog:product_list"))
        self.assertNotContains(owner_page, "ศูนย์เจ้าหน้าที่วิสาหกิจชุมชน")

        community_staff = User.objects.create_user(
            username="community-staff-menu",
            password="pass12345",
            role=User.Roles.COOPERATIVE_STAFF,
        )
        self.client.force_login(community_staff)
        staff_page = self.client.get(reverse("catalog:product_list"))
        self.assertContains(staff_page, "ศูนย์เจ้าหน้าที่วิสาหกิจชุมชน")
        self.assertContains(staff_page, reverse("accounts:staff_dashboard"))

    def test_profile_saves_new_personal_fields(self):
        original_display_name = self.user.display_name
        response = self.client.post(
            reverse("accounts:account_history"),
            {
                "display_name": "สมใจ ใจดี",
                "email": "new-owner@example.com",
                "phone": "0899999999",
                "first_name": "สมใจ",
                "last_name": "ใจดี",
                "gender": User.Gender.FEMALE,
                "birth_date": "1995-04-12",
            },
        )

        self.assertRedirects(response, reverse("accounts:account_history"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.display_name, original_display_name)
        self.assertEqual(self.user.gender, User.Gender.FEMALE)
        self.assertEqual(self.user.birth_date.isoformat(), "1995-04-12")

    def test_avatar_picker_is_rendered_and_rejects_files_over_one_mb(self):
        page = self.client.get(reverse("accounts:account_history"))
        self.assertContains(page, "data-avatar-trigger")
        self.assertContains(page, "เลือก รูป".replace(" ", ""))
        self.assertContains(page, "สูงสุด 1 MB")

        oversized_avatar = SimpleUploadedFile(
            "avatar.jpg",
            b"x" * (1024 * 1024 + 1),
            content_type="image/jpeg",
        )
        response = self.client.post(
            reverse("accounts:account_history"),
            {
                "avatar": oversized_avatar,
                "display_name": self.user.display_name,
                "email": self.user.email,
                "phone": self.user.phone,
                "first_name": "",
                "last_name": "",
                "gender": User.Gender.UNSPECIFIED,
                "birth_date": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "รูปโปรไฟล์ต้องมีขนาดไม่เกิน 1 MB")
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar)
    def test_address_crud_keeps_one_default_and_prefills_checkout(self):
        first_response = self.client.post(
            reverse("accounts:address_create"),
            {
                "label": "บ้าน",
                "recipient_name": "ผู้ซื้อทดสอบ",
                "phone": "0812345678",
                "province": "นครราชสีมา",
                "district": "เมืองนครราชสีมา",
                "subdistrict": "ในเมือง",
                "postal_code": "30000",
                "address_line": "99 ถนนชุมชน",
            },
        )
        self.assertRedirects(first_response, reverse("accounts:addresses"))
        first = DeliveryAddress.objects.get(user=self.user)
        self.assertTrue(first.is_default)

        self.client.post(
            reverse("accounts:address_create"),
            {
                "label": "ที่ทำงาน",
                "recipient_name": "สมใจ ใจดี",
                "phone": "0899999999",
                "province": "ขอนแก่น",
                "district": "เมืองขอนแก่น",
                "subdistrict": "ในเมือง",
                "postal_code": "40000",
                "address_line": "88 ถนนกลางเมือง",
            },
        )
        second = DeliveryAddress.objects.get(user=self.user, label="ที่ทำงาน")
        self.assertFalse(second.is_default)

        self.client.post(reverse("accounts:address_set_default", args=[second.pk]))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)
        self.assertEqual(self.user.delivery_addresses.filter(is_default=True).count(), 1)

        initial = buyer_initial(self.user)
        self.assertEqual(initial["shipping_name"], second.recipient_name)
        self.assertEqual(initial["shipping_province"], "ขอนแก่น")
        self.assertEqual(initial["shipping_postal_code"], "40000")
        self.assertIn("88 ถนนกลางเมือง", initial["shipping_address"])

        self.client.post(reverse("accounts:address_delete", args=[second.pk]))
        first.refresh_from_db()
        self.assertTrue(first.is_default)

    def test_user_cannot_edit_another_users_address(self):
        address = DeliveryAddress.objects.create(
            user=self.other_user,
            label="บ้าน",
            recipient_name="ผู้ใช้อื่น",
            phone="0800000000",
            address_line="1 ถนนอื่น",
            subdistrict="ในเมือง",
            district="เมือง",
            province="เชียงใหม่",
            postal_code="50000",
            is_default=True,
        )

        response = self.client.get(reverse("accounts:address_edit", args=[address.pk]))

        self.assertEqual(response.status_code, 404)
