from decimal import Decimal
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse


from accounts.models import Community, FarmerProfile, Notification, User

from orders.models import Order, OrderItem

from .models import Category, Product, ProductReview


class ProductCatalogTests(TestCase):
    def test_product_list_does_not_seed_demo_data_by_default(self):
        Product.objects.all().delete()

        self.client.get(reverse("catalog:product_list"))

        self.assertEqual(Product.objects.filter(status=Product.Status.ACTIVE).count(), 0)

    @override_settings(ENABLE_DEMO_DATA=True)
    def test_product_list_can_seed_demo_data_when_enabled(self):
        Product.objects.all().delete()

        self.client.get(reverse("catalog:product_list"))

        self.assertEqual(Product.objects.filter(status=Product.Status.ACTIVE).count(), 20)

    def setUp(self):
        self.community = Community.objects.create(
            name="ชุมชนทดสอบ",
            slug="test-community",
            province="เชียงใหม่",
        )
        self.farmer = User.objects.create_user(
            username="farmer",
            password="pass",
            role=User.Roles.FARMER,
        )
        FarmerProfile.objects.create(
            user=self.farmer,
            community=self.community,
            farm_name="สวนทดสอบ",
            verification_status=FarmerProfile.VerificationStatus.VERIFIED,
        )

    def test_active_product_appears_on_marketplace(self):
        Product.objects.create(
            seller=self.farmer,
            community=self.community,
            name="ข้าวอินทรีย์",
            description="ปลูกแบบอินทรีย์",
            price=Decimal("80.00"),
            stock_quantity=Decimal("20.00"),
            status=Product.Status.ACTIVE,
        )

        response = self.client.get(reverse("catalog:product_list"))

        self.assertContains(response, "ข้าวอินทรีย์")

    def test_farmer_can_add_multiple_gallery_images_when_creating_a_product(self):
        self.client.force_login(self.farmer)
        files = [
            SimpleUploadedFile("vegetable-one.jpg", b"first image", content_type="image/jpeg"),
            SimpleUploadedFile("vegetable-two.webp", b"second image", content_type="image/webp"),
        ]

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            with patch("catalog.views.ProductImage.objects.create") as create_image:
                response = self.client.post(
                    reverse("catalog:product_create"),
                    {
                        "name": "ผักพร้อมรูปหลายรูป",
                        "description": "สินค้าทดสอบอัลบั้มรูป",
                        "unit": Product.Unit.KG,
                        "price": "35.00",
                        "stock_quantity": "10.00",
                        "minimum_order_quantity": "0.50",
                        "low_stock_threshold": "5.00",
                        "image": files,
                    },
                )

        product = Product.objects.get(name="ผักพร้อมรูปหลายรูป")
        self.assertRedirects(response, product.get_absolute_url(), fetch_redirect_response=False)
        self.assertTrue(product.image)
        self.assertEqual(create_image.call_count, 1)

    def test_farmer_can_add_multiple_images_from_product_management(self):
        product = Product.objects.create(
            seller=self.farmer,
            community=self.community,
            name="สินค้าสำหรับเพิ่มรูป",
            description="ทดสอบเพิ่มรูปจากหน้ารายละเอียด",
            price=Decimal("35.00"),
            stock_quantity=Decimal("10.00"),
        )
        self.client.force_login(self.farmer)
        files = [
            SimpleUploadedFile("management-one.jpg", b"first image", content_type="image/jpeg"),
            SimpleUploadedFile("management-two.png", b"second image", content_type="image/png"),
        ]

        with patch("catalog.views.ProductImage.objects.create") as create_image:
            response = self.client.post(
                reverse("catalog:product_image_upload", args=[product.pk]),
                {"image": files},
            )

        self.assertRedirects(response, product.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(create_image.call_count, 2)

    def test_pending_product_is_hidden_from_public(self):
        Product.objects.create(
            seller=self.farmer,
            community=self.community,
            name="มะม่วงรอตรวจ",
            description="ยังไม่อนุมัติ",
            price=Decimal("50.00"),
            stock_quantity=Decimal("10.00"),
            status=Product.Status.PENDING,
        )

        response = self.client.get(reverse("catalog:product_list"))

        self.assertNotContains(response, "มะม่วงรอตรวจ")


    def test_products_can_be_filtered_by_province(self):
        northern_product = Product.objects.create(
            seller=self.farmer,
            community=self.community,
            name="กาแฟเชียงใหม่",
            description="กาแฟชุมชน",
            price=Decimal("120.00"),
            stock_quantity=Decimal("10.00"),
            status=Product.Status.ACTIVE,
        )
        other_community = Community.objects.create(
            name="ชุมชนต่างจังหวัด",
            slug="other-province-community",
            province="ตรัง",
        )
        other_farmer = User.objects.create_user(
            username="other-province-farmer",
            password="pass",
            role=User.Roles.FARMER,
        )
        FarmerProfile.objects.create(
            user=other_farmer,
            community=other_community,
            farm_name="สวนต่างจังหวัด",
            verification_status=FarmerProfile.VerificationStatus.VERIFIED,
        )
        Product.objects.create(
            seller=other_farmer,
            community=other_community,
            name="กาแฟตรัง",
            description="กาแฟอีกจังหวัด",
            price=Decimal("110.00"),
            stock_quantity=Decimal("8.00"),
            status=Product.Status.ACTIVE,
        )

        response = self.client.get(
            reverse("catalog:product_list"),
            {"province": "เชียงใหม่"},
        )

        self.assertContains(response, northern_product.name)
        self.assertNotContains(response, "กาแฟตรัง")
        self.assertContains(response, "จังหวัด เชียงใหม่")
class ProductReviewTests(TestCase):
    def setUp(self):
        self.community = Community.objects.create(
            name="ชุมชนรีวิว",
            slug="review-community",
            province="เชียงใหม่",
        )
        self.buyer = User.objects.create_user(
            username="reviewbuyer",
            password="pass",
            role=User.Roles.CONSUMER,
        )
        self.farmer = User.objects.create_user(
            username="reviewfarmer",
            password="pass",
            role=User.Roles.FARMER,
        )
        FarmerProfile.objects.create(
            user=self.farmer,
            community=self.community,
            farm_name="สวนรีวิว",
            verification_status=FarmerProfile.VerificationStatus.VERIFIED,
        )
        self.product = Product.objects.create(
            seller=self.farmer,
            community=self.community,
            name="แตงโม",
            description="หวานอร่อย",
            price=Decimal("120.00"),
            stock_quantity=Decimal("10.00"),
            status=Product.Status.ACTIVE,
        )

    def test_buyer_can_submit_review_after_purchase(self):
        order = Order.objects.create(
            buyer=self.buyer,
            seller=self.farmer,
            community=self.community,
            shipping_name="ผู้ซื้อ",
            shipping_phone="0812345678",
            shipping_address="บ้านเลขที่ 1",
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name=self.product.name,
            unit=self.product.unit,
            quantity=Decimal("1"),
            unit_price=self.product.price,
        )
        order.payment_status = Order.PaymentStatus.PAID
        order.status = Order.Status.PAID
        order.save(update_fields=["payment_status", "status", "updated_at"])

        self.client.force_login(self.buyer)
        response = self.client.post(
            reverse("catalog:submit_review", args=[self.product.pk]),
            {"rating": 5, "comment": "อร่อยมาก"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(ProductReview.objects.filter(product=self.product, user=self.buyer).exists())
        self.assertEqual(self.product.average_rating, 5)


class ProductDetailInteractionTests(TestCase):
    def setUp(self):
        self.community = Community.objects.create(
            name="ชุมชนหน้าสินค้า",
            slug="detail-community",
            province="สุโขทัย",
        )
        self.buyer = User.objects.create_user(
            username="detailbuyer",
            password="pass",
            role=User.Roles.CONSUMER,
        )
        self.farmer = User.objects.create_user(
            username="detailfarmer",
            password="pass",
            role=User.Roles.FARMER,
        )
        FarmerProfile.objects.create(
            user=self.farmer,
            community=self.community,
            farm_name="สวนหน้าสินค้า",
            verification_status=FarmerProfile.VerificationStatus.VERIFIED,
        )
        self.product = Product.objects.create(
            seller=self.farmer,
            community=self.community,
            name="ฟักทอง",
            description="เนื้อแน่น",
            price=Decimal("45.00"),
            stock_quantity=Decimal("15.00"),
            status=Product.Status.ACTIVE,
        )

    def test_consumer_sees_cart_favorite_and_report_actions(self):
        self.client.force_login(self.buyer)

        response = self.client.get(reverse("catalog:product_detail", args=[self.product.pk]))

        self.assertContains(response, "เพิ่มลงตะกร้า")
        self.assertContains(response, reverse("orders:cart_add", args=[self.product.pk]))
        self.assertContains(response, reverse("catalog:toggle_product_favorite", args=[self.product.pk]))
        self.assertContains(response, reverse("catalog:report_product", args=[self.product.pk]))
        self.assertContains(response, reverse("catalog:seller_store", args=[self.farmer.pk]))
        self.assertContains(response, reverse("accounts:conversation_start", args=[self.product.pk]))

    def test_seller_store_filters_category_and_sorts_by_price(self):
        vegetables = Category.objects.create(name="ผักทดสอบ", slug="store-vegetables")
        fruit = Category.objects.create(name="ผลไม้ทดสอบ", slug="store-fruit")
        self.product.category = vegetables
        self.product.save(update_fields=["category"])
        expensive = Product.objects.create(
            seller=self.farmer,
            community=self.community,
            category=vegetables,
            name="ผักราคาสูง",
            description="สินค้าในหมวดเดียวกัน",
            price=Decimal("90.00"),
            stock_quantity=Decimal("5.00"),
            status=Product.Status.ACTIVE,
        )
        Product.objects.create(
            seller=self.farmer,
            community=self.community,
            category=fruit,
            name="ผลไม้คนละหมวด",
            description="ไม่ควรอยู่ในผลการกรอง",
            price=Decimal("120.00"),
            stock_quantity=Decimal("5.00"),
            status=Product.Status.ACTIVE,
        )

        response = self.client.get(
            reverse("catalog:seller_store", args=[self.farmer.pk]),
            {"category": vegetables.pk, "sort": "price_desc"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["products"]), [expensive, self.product])
        self.assertEqual(response.context["current_sort"], "price_desc")
    def test_product_detail_recommends_other_active_products(self):
        recommended = Product.objects.create(
            seller=self.farmer,
            community=self.community,
            name="สินค้าแนะนำจากชุมชน",
            description="สินค้าอีกชนิด",
            price=Decimal("25.00"),
            stock_quantity=Decimal("8.00"),
            status=Product.Status.ACTIVE,
        )

        response = self.client.get(reverse("catalog:product_detail", args=[self.product.pk]))

        self.assertContains(response, "สินค้าแนะนำ")
        self.assertContains(response, recommended.name)
        self.assertNotContains(response, f'href="{self.product.get_absolute_url()}" class="group')
class LowStockNotificationTests(TestCase):
    def test_low_stock_command_notifies_seller_once(self):
        community = Community.objects.create(name="ชุมชนแจ้งสต็อก", slug="low-stock-community", province="แพร่")
        seller = User.objects.create_user(username="low-stock-seller", password="pass", role=User.Roles.FARMER)
        product = Product.objects.create(
            seller=seller,
            community=community,
            name="ผักสด",
            description="ผักชุมชน",
            price=Decimal("30.00"),
            stock_quantity=Decimal("2.00"),
            low_stock_threshold=Decimal("5.00"),
            status=Product.Status.ACTIVE,
        )

        call_command("notify_low_stock")
        call_command("notify_low_stock")

        self.assertEqual(
            Notification.objects.filter(user=seller, title__contains=product.name).count(),
            1,
        )
