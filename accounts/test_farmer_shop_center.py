from decimal import Decimal
from datetime import timedelta

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalog.models import Category, Product, ProductImage, ProductReview
from orders.models import Order
from payments.models import Payment, SellerSettlement

from .models import Community, FarmerProfile, StoreCoverSlide, User


class FarmerShopCenterTests(TestCase):
    def setUp(self):
        self.community = Community.objects.create(
            name="ชุมชนร้านค้าทดสอบ",
            slug="seller-center-test",
            province="สกลนคร",
        )
        self.seller = User.objects.create_user(
            username="seller-center",
            password="pass12345",
            role=User.Roles.FARMER,
        )
        self.profile = FarmerProfile.objects.create(
            user=self.seller,
            community=self.community,
            farm_name="ฟาร์มเดิม",
            verification_status=FarmerProfile.VerificationStatus.VERIFIED,
        )
        category = Category.objects.create(name="ผัก", slug="vegetables-seller-center")
        self.product = Product.objects.create(
            seller=self.seller,
            community=self.community,
            category=category,
            name="ผักทดสอบ",
            description="ผักสำหรับทดสอบหน้าร้าน",
            price=Decimal("35.00"),
            stock_quantity=Decimal("10.00"),
            status=Product.Status.ACTIVE,
        )
        self.reviewer = User.objects.create_user(
            username="shop-reviewer",
            password="pass12345",
            role=User.Roles.CONSUMER,
        )
        self.reviewer.avatar = "avatars/shop-reviewer.jpg"
        self.reviewer.save(update_fields=["avatar"])
        self.product.image = "products/review-product.jpg"
        self.product.save(update_fields=["image"])
        ProductReview.objects.create(
            product=self.product,
            user=self.reviewer,
            rating=5,
            comment="ผักสดมาก",
        )
        self.client.force_login(self.seller)

    def test_seller_center_service_finance_and_store_views_are_available(self):
        center_url = reverse("accounts:farmer_shop_center")

        reviews = self.client.get(f"{center_url}?section=service&mode=reviews")
        self.assertContains(reviews, "ผักสดมาก")
        self.assertContains(reviews, reverse("accounts:conversations"))
        self.assertContains(reviews, self.reviewer.avatar.url)
        self.assertContains(reviews, self.product.image.url)

        finance = self.client.get(f"{center_url}?section=finance&mode=bank")
        self.assertContains(finance, "Stripe Connect")
        self.assertContains(finance, reverse("payments:connect_account"))

        balance = self.client.get(f"{center_url}?section=finance&mode=balance")
        self.assertContains(balance, "ภาพรวมยอดเงิน")
        self.assertContains(balance, "ธุรกรรมที่ผ่านมา")
        self.assertContains(balance, "โอนเงินแล้ว")
        self.assertContains(balance, "เลือกช่วงวันที่")

        store = self.client.get(f"{center_url}?section=store")
        self.assertContains(store, "ฟาร์มเดิม")
        self.assertContains(store, reverse("catalog:seller_store", args=[self.seller.pk]))

        marketing = self.client.get(f"{center_url}?section=marketing&mode=store")
        self.assertContains(marketing, "การประชาสัมพันธ์ร้าน")
        self.assertContains(marketing, reverse("catalog:seller_store", args=[self.seller.pk]))

    def test_seller_dashboard_shows_key_metrics_without_duplicate_work_queue(self):
        response = self.client.get(reverse("accounts:farmer_shop_center"))

        self.assertContains(response, "ตัวชี้วัดหลัก")
        self.assertContains(response, reverse("accounts:farmer_shop_center"))
        self.assertContains(response, "ยอดขายไม่รวมค่าจัดส่ง")
        self.assertContains(response, "จำนวนผู้เยี่ยมชม")
        self.assertContains(response, "จำนวนการคลิกสินค้า")
        self.assertNotContains(response, "กราฟแสดงยอดขายที่ชำระสำเร็จในแต่ละวัน")
        self.assertContains(response, "ภาพรวมร้านค้า")
        self.assertContains(response, "คะแนนรีวิว")
        self.assertContains(response, "ที่ต้องจัดส่ง")
        self.assertContains(response, "คำขอคืนเงิน / คืนสินค้า / ยกเลิก")
        self.assertContains(response, "สินค้าที่ละเมิดนโยบาย")
        self.assertEqual(response.context["policy_issue_total"], 0)
        self.assertEqual(len(response.context["daily_sales_trend"]), 7)
        self.assertFalse(response.context["daily_sales_trend_has_data"])

        analytics = self.client.get(f"{reverse('accounts:farmer_shop_center')}?section=marketing")
        self.assertContains(analytics, "แนวโน้มยอดขาย 7 วันล่าสุด")
        self.assertContains(analytics, "ยังไม่มียอดขายที่ชำระสำเร็จในช่วง 7 วันที่ผ่านมา")

    def test_finance_income_tabs_and_transferred_period_totals(self):
        buyer = User.objects.create_user(
            username="finance-buyer",
            password="pass12345",
            role=User.Roles.CONSUMER,
        )
        order = Order.objects.create(
            buyer=buyer,
            seller=self.seller,
            community=self.community,
            reference="FINANCE-TRANSFERRED",
            subtotal=Decimal("120.00"),
            total_amount=Decimal("120.00"),
            shipping_name="Finance buyer",
            shipping_phone="0812345678",
            shipping_address="Bangkok",
            payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.COMPLETED,
        )
        payment = Payment.objects.create(
            order=order,
            amount=Decimal("120.00"),
            status=Payment.Status.PAID,
            provider=Payment.Provider.STRIPE,
        )
        SellerSettlement.objects.create(
            payment=payment,
            seller=self.seller,
            gross_amount=Decimal("120.00"),
            net_amount=Decimal("100.00"),
            status=SellerSettlement.Status.TRANSFERRED,
            transferred_at=timezone.now() - timedelta(days=1),
        )

        response = self.client.get(f"{reverse('accounts:farmer_shop_center')}?section=finance")

        self.assertEqual(response.context["income_status"], "transferred")
        self.assertEqual(response.context["income_period"], "week")
        self.assertContains(response, "รอดำเนินการ")
        self.assertContains(response, "ยอดขายที่ชำระแล้ว")
        self.assertContains(response, "สัปดาห์นี้")
        self.assertContains(response, "เดือนนี้")
        self.assertContains(response, "FINANCE-TRANSFERRED")
        self.assertContains(response, "ช่องทางการรับเงิน")
        self.assertContains(response, "เลือกช่วงวันที่")
        self.assertEqual(response.context["transferred_this_week_total"], Decimal("100.00"))
        self.assertEqual(response.context["transferred_this_month_total"], Decimal("100.00"))

        selected_income_date = timezone.localdate() - timedelta(days=1)
        custom_income = self.client.get(
            f"{reverse('accounts:farmer_shop_center')}?section=finance"
            f"&income_status=transferred&income_period=custom"
            f"&income_start={selected_income_date.isoformat()}"
            f"&income_end={selected_income_date.isoformat()}"
        )
        self.assertEqual(custom_income.context["income_period"], "custom")
        self.assertEqual(custom_income.context["income_start"], selected_income_date)
        self.assertEqual(custom_income.context["income_end"], selected_income_date)
        self.assertContains(custom_income, "เลือกช่วงวันที่")
        self.assertContains(custom_income, "FINANCE-TRANSFERRED")

        selected_date = timezone.localdate()
        custom_balance = self.client.get(
            f"{reverse('accounts:farmer_shop_center')}?section=finance&mode=balance"
            f"&balance_period=custom&balance_start={selected_date.isoformat()}"
            f"&balance_end={selected_date.isoformat()}&balance_activity=transferred"
        )
        self.assertEqual(custom_balance.context["balance_period"], "custom")
        self.assertEqual(custom_balance.context["balance_start"], selected_date)
        self.assertEqual(custom_balance.context["balance_end"], selected_date)
        self.assertContains(custom_balance, "เลือกช่วงวันที่")

        pending = self.client.get(
            f"{reverse('accounts:farmer_shop_center')}?section=finance&income_status=pending"
        )
        self.assertNotContains(pending, "FINANCE-TRANSFERRED")
        self.assertContains(pending, "เริ่มดำเนินการเมื่อ")

        statement = self.client.get(
            f"{reverse('accounts:income_statement')}?income_status=transferred&income_period=week"
        )
        self.assertContains(statement, "ใบสรุปรายรับเพื่อประกอบการยื่นภาษี")
        self.assertContains(statement, "FINANCE-TRANSFERRED")

    def test_store_details_displays_the_seller_avatar(self):
        self.seller.avatar = "avatars/store-details.jpg"
        self.seller.save(update_fields=["avatar"])

        response = self.client.get(f"{reverse('accounts:farmer_shop_center')}?section=store")

        self.assertContains(response, self.seller.avatar.url)

    def test_selected_menu_group_stays_open_after_navigation(self):
        center_url = reverse("accounts:farmer_shop_center")

        for section in ("orders", "products", "marketing", "service", "finance", "store"):
            response = self.client.get(f"{center_url}?section={section}")
            self.assertContains(response, f'<details data-shop-menu="{section}" open>')
            self.assertContains(response, f'data-shop-menu="{section}"')

        self.assertContains(response, "seller-shop-open-menu-groups")

    def test_order_submenu_uses_the_selected_order_menu(self):
        response = self.client.get(
            f"{reverse('accounts:farmer_shop_center')}?section=orders&status=cancelled&order_menu=cancelled"
        )

        self.assertEqual(response.context["order_menu"], "cancelled")
        self.assertContains(
            response,
            'href="?section=orders&status=cancelled&order_menu=cancelled" class="block px-6 py-2 bg-emerald-50 font-semibold text-leaf"',
        )
        self.assertContains(
            response,
            'href="?section=orders" class="block px-6 py-2 text-slate-700 hover:bg-emerald-50 hover:text-leaf"',
        )

    def test_product_submenu_uses_the_selected_mode(self):
        response = self.client.get(
            f"{reverse('accounts:farmer_shop_center')}?section=products&mode=status"
        )

        self.assertContains(
            response,
            'href="?section=products&mode=status" class="block px-6 py-2 bg-emerald-50 font-semibold text-leaf"',
        )
        self.assertContains(
            response,
            'href="?section=products" class="block px-6 py-2 text-slate-700 hover:bg-emerald-50 hover:text-leaf"',
        )
        self.assertContains(
            response,
            'href="?section=orders" class="block px-6 py-2 text-slate-700 hover:bg-emerald-50 hover:text-leaf"',
        )

    def test_product_list_shows_product_thumbnail(self):
        self.product.image = "products/seller-center-product.jpg"
        self.product.save(update_fields=["image"])

        response = self.client.get(f"{reverse('accounts:farmer_shop_center')}?section=products")

        self.assertContains(response, "data-product-thumbnail")
        self.assertContains(response, self.product.image.url)

        self.product.image = ""
        self.product.save(update_fields=["image"])
        gallery_image = ProductImage.objects.create(
            product=self.product,
            image="products/gallery/seller-center-gallery-product.jpg",
            alt_text="รูปอัลบั้มสินค้า",
        )

        response = self.client.get(f"{reverse('accounts:farmer_shop_center')}?section=products")

        self.assertContains(response, gallery_image.image.url)

    def test_seller_can_remove_the_main_product_image(self):
        self.product.image.save("remove-this-product-image.jpg", ContentFile(b"product image"), save=True)

        response = self.client.post(
            reverse("catalog:product_update", args=[self.product.pk]),
            {
                "category": self.product.category_id,
                "name": self.product.name,
                "description": self.product.description,
                "unit": self.product.unit,
                "price": self.product.price,
                "stock_quantity": self.product.stock_quantity,
                "minimum_order_quantity": self.product.minimum_order_quantity,
                "low_stock_threshold": self.product.low_stock_threshold,
                "weight_grams": "",
                "harvest_date": "",
                "expiry_date": "",
                "remove_image": "1",
            },
        )

        self.assertRedirects(response, self.product.get_absolute_url(), fetch_redirect_response=False)
        self.product.refresh_from_db()
        self.assertFalse(self.product.image)

    def test_seller_can_update_storefront_details(self):
        response = self.client.post(
            reverse("accounts:farmer_shop_center"),
            {
                "shop_action": "update_store",
                "farm_name": "ฟาร์มใหม่",
                "province": "สกลนคร",
                "district": "เมือง",
                "address": "99 หมู่ 1",
                "bio": "ผักปลูกสดจากสวน",
            },
        )

        self.assertRedirects(response, f"{reverse('accounts:farmer_shop_center')}?section=store&mode=settings")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.farm_name, "ฟาร์มใหม่")
        self.assertEqual(self.profile.bio, "ผักปลูกสดจากสวน")

    def test_store_name_update_is_reflected_on_public_store_with_existing_slides(self):
        slide = StoreCoverSlide.objects.create(
            profile=self.profile,
            image="store-cover-slides/existing-slide.jpg",
        )
        response = self.client.post(
            reverse("accounts:farmer_shop_center"),
            {
                "shop_action": "update_store",
                "farm_name": "ชื่อร้านใหม่",
                "province": self.profile.province,
                "district": self.profile.district,
                "address": self.profile.address,
                "bio": self.profile.bio,
            },
        )

        self.assertRedirects(response, f"{reverse('accounts:farmer_shop_center')}?section=store&mode=settings")
        public_store = self.client.get(reverse("catalog:seller_store", args=[self.seller.pk]))
        self.assertContains(public_store, "ชื่อร้านใหม่")
        self.assertIn("no-store", public_store.headers["Cache-Control"])
        settings_page = self.client.get(f"{reverse('accounts:farmer_shop_center')}?section=store&mode=settings")
        self.assertContains(settings_page, f'form="store-cover-slide-delete-{slide.pk}"')

    def test_store_settings_shows_cover_image_requirements_and_preview(self):
        self.profile.store_cover = "store-covers/current-cover.jpg"
        self.profile.save(update_fields=["store_cover"])

        response = self.client.get(
            f"{reverse('accounts:farmer_shop_center')}?section=store&mode=settings"
        )

        self.assertContains(response, 'data-store-cover-input')
        self.assertContains(response, 'data-store-cover-preview')
        self.assertContains(response, 'data-store-cover-cropper')
        self.assertContains(response, 'data-store-cover-clear')
        self.assertContains(response, 'data-store-cover-remove')
        self.assertNotContains(response, 'type="checkbox" name="store_cover-clear"')
        self.assertContains(response, 'z-[70] hidden place-items-center')
        self.assertContains(response, "1600 x 500")
        self.assertContains(response, "ไฟล์ต้นฉบับไม่เกิน 50 MB")
        self.assertContains(response, "ภาพแบนเนอร์ขนาดไม่เกิน 5 MB")
        self.assertContains(response, "MAX_SOURCE_IMAGE_SIZE")
        self.assertContains(response, "กดบันทึกข้อมูลร้านเพื่อเพิ่มสไลด์")

    def test_store_name_is_saved_when_cover_file_is_invalid(self):
        invalid_cover = SimpleUploadedFile(
            "cover.txt",
            b"not an image",
            content_type="text/plain",
        )

        response = self.client.post(
            reverse("accounts:farmer_shop_center"),
            {
                "shop_action": "update_store",
                "farm_name": "ชื่อร้านที่บันทึกได้",
                "province": self.profile.province,
                "district": self.profile.district,
                "address": self.profile.address,
                "bio": self.profile.bio,
                "store_cover": invalid_cover,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.farm_name, "ชื่อร้านที่บันทึกได้")
        self.assertContains(response, "บันทึกชื่อและข้อมูลร้านแล้ว")

    def test_store_design_displays_the_saved_cover_image(self):
        self.profile.store_cover = "store-covers/design-preview.jpg"
        self.profile.save(update_fields=["store_cover"])

        response = self.client.get(
            f"{reverse('accounts:farmer_shop_center')}?section=store&mode=design"
        )

        self.assertContains(response, self.profile.store_cover.url)

    def test_seller_can_remove_the_store_cover_with_the_remove_button(self):
        self.profile.store_cover.save("remove-me.jpg", ContentFile(b"store cover"), save=True)

        response = self.client.post(
            reverse("accounts:farmer_shop_center"),
            {
                "shop_action": "update_store",
                "farm_name": self.profile.farm_name,
                "province": self.profile.province,
                "district": self.profile.district,
                "address": self.profile.address,
                "bio": self.profile.bio,
                "remove_store_cover": "1",
            },
        )

        self.assertRedirects(response, f"{reverse('accounts:farmer_shop_center')}?section=store&mode=settings")
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.store_cover)

    def test_seller_can_add_and_remove_store_cover_slides(self):
        first_upload = SimpleUploadedFile("slide-one.jpg", b"slide image", content_type="image/jpeg")
        second_upload = SimpleUploadedFile("slide-two.jpg", b"second slide image", content_type="image/jpeg")
        response = self.client.post(
            reverse("accounts:farmer_shop_center"),
            {
                "shop_action": "update_store",
                "farm_name": self.profile.farm_name,
                "province": self.profile.province,
                "district": self.profile.district,
                "address": self.profile.address,
                "bio": self.profile.bio,
                "store_cover_slides": [first_upload, second_upload],
            },
        )

        self.assertRedirects(response, f"{reverse('accounts:farmer_shop_center')}?section=store&mode=settings")
        slides = list(StoreCoverSlide.objects.filter(profile=self.profile).order_by("sort_order"))
        self.assertEqual(len(slides), 2)
        self.assertLess(slides[0].sort_order, slides[1].sort_order)

        response = self.client.post(reverse("accounts:store_cover_slide_delete", args=[slides[0].pk]))

        self.assertRedirects(response, f"{reverse('accounts:farmer_shop_center')}?section=store&mode=settings")
        self.assertFalse(StoreCoverSlide.objects.filter(pk=slides[0].pk).exists())
        self.assertTrue(StoreCoverSlide.objects.filter(pk=slides[1].pk).exists())
