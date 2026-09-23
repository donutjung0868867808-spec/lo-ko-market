from decimal import Decimal
from io import BytesIO
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image


from accounts.models import Community, FarmerProfile, Notification, StoreCoverSlide, User

from orders.models import Order, OrderItem

from .forms import ProductForm
from .models import Category, HomeSlide, Product, ProductReview, ProductReviewMedia


def test_image_bytes():
    buffer = BytesIO()
    Image.new("RGB", (1, 1), color="green").save(buffer, format="PNG")
    return buffer.getvalue()


TEST_IMAGE_BYTES = test_image_bytes()


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

    def test_category_uses_its_cover_image_on_marketplace(self):
        category = Category.objects.create(
            name="category cover",
            slug="category-cover",
            image="categories/category-cover.jpg",
        )
        Product.objects.create(
            seller=self.farmer,
            community=self.community,
            category=category,
            name="test product",
            description="test product for category cover",
            price=Decimal("40.00"),
            stock_quantity=Decimal("10.00"),
            status=Product.Status.ACTIVE,
        )

        response = self.client.get(reverse("catalog:product_list"))

        self.assertContains(response, "/media/categories/category-cover.jpg")

    def test_category_accepts_an_image_without_a_filename_extension(self):
        category = Category(
            name="extensionless category",
            slug="extensionless-category",
            image=SimpleUploadedFile("download", TEST_IMAGE_BYTES),
        )

        category.full_clean()

    def test_active_home_slides_are_rendered_on_the_marketplace(self):
        HomeSlide.objects.create(
            image="home-slides/first-slide.jpg",
            alt_text="First slide",
            sort_order=2,
        )
        HomeSlide.objects.create(
            image="home-slides/hidden-slide.jpg",
            alt_text="Hidden slide",
            is_active=False,
        )

        response = self.client.get(reverse("catalog:product_list"))

        self.assertContains(response, "/media/home-slides/first-slide.jpg")
        self.assertNotContains(response, "/media/home-slides/hidden-slide.jpg")
        self.assertContains(response, "data-hero-carousel")

    def test_farmer_can_add_multiple_gallery_images_when_creating_a_product(self):
        self.client.force_login(self.farmer)
        files = [
            SimpleUploadedFile("download", TEST_IMAGE_BYTES, content_type="image/png"),
            SimpleUploadedFile("vegetable-two.webp", TEST_IMAGE_BYTES, content_type="image/webp"),
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

    def test_product_form_explains_multiple_image_uploads(self):
        self.client.force_login(self.farmer)

        response = self.client.get(reverse("catalog:product_create"))

        self.assertContains(response, "ลากรูปมาวางได้หลายรูป")
        self.assertContains(response, 'data-product-gallery-input="true"')

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
            SimpleUploadedFile("management-one.jpg", TEST_IMAGE_BYTES, content_type="image/jpeg"),
            SimpleUploadedFile("management-two.png", TEST_IMAGE_BYTES, content_type="image/png"),
        ]

        with patch("catalog.views.ProductImage.objects.create") as create_image:
            response = self.client.post(
                reverse("catalog:product_image_upload", args=[product.pk]),
                {"image": files},
            )

        self.assertRedirects(response, product.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(create_image.call_count, 2)

    def test_existing_product_image_without_extension_can_be_saved(self):
        product = Product.objects.create(
            seller=self.farmer,
            community=self.community,
            name="product with extensionless image",
            description="Existing image should not block changes.",
            price=Decimal("35.00"),
            stock_quantity=Decimal("10.00"),
            image="products/download_qp0Inf",
        )

        form = ProductForm(
            {
                "name": product.name,
                "description": product.description,
                "unit": product.unit,
                "price": product.price,
                "stock_quantity": product.stock_quantity,
                "minimum_order_quantity": product.minimum_order_quantity,
                "low_stock_threshold": product.low_stock_threshold,
            },
            instance=product,
        )

        self.assertTrue(form.is_valid(), form.errors)

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

    def test_province_search_suggestions_include_active_community_provinces(self):
        response = self.client.get(reverse("catalog:product_list"))

        self.assertContains(response, 'data-province-autocomplete')
        self.assertContains(response, 'data-province-value="เชียงใหม่"')
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

    def test_buyer_can_attach_an_image_and_video_to_a_review(self):
        order = Order.objects.create(
            buyer=self.buyer,
            seller=self.farmer,
            community=self.community,
            shipping_name="ผู้ซื้อ",
            shipping_phone="0812345678",
            shipping_address="บ้านเลขที่ 1",
            payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.PAID,
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name=self.product.name,
            unit=self.product.unit,
            quantity=Decimal("1"),
            unit_price=self.product.price,
        )
        self.client.force_login(self.buyer)
        media = [
            SimpleUploadedFile("review-photo.jpg", TEST_IMAGE_BYTES, content_type="image/jpeg"),
            SimpleUploadedFile("review-video.mp4", b"test video", content_type="video/mp4"),
        ]

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse("catalog:submit_review", args=[self.product.pk]),
                {"rating": 5, "comment": "มีทั้งรูปและวิดีโอ", "media": media},
            )

        review = ProductReview.objects.get(product=self.product, user=self.buyer)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(review.media.count(), 2)
        self.assertSetEqual(
            set(review.media.values_list("media_type", flat=True)),
            {ProductReviewMedia.MediaType.IMAGE, ProductReviewMedia.MediaType.VIDEO},
        )

    def test_seller_store_displays_the_seller_avatar(self):
        self.farmer.avatar = "avatars/store-owner.jpg"
        self.farmer.save(update_fields=["avatar"])
        self.farmer.farmer_profile.store_cover = "store-covers/store-owner.jpg"
        self.farmer.farmer_profile.save(update_fields=["store_cover"])

        response = self.client.get(reverse("catalog:seller_store", args=[self.farmer.pk]))

        self.assertContains(response, "/media/avatars/store-owner.jpg")
        self.assertContains(response, "/media/store-covers/store-owner.jpg")

    def test_seller_store_displays_cover_slides(self):
        StoreCoverSlide.objects.create(
            profile=self.farmer.farmer_profile,
            image="store-cover-slides/store-owner-slide.jpg",
        )

        response = self.client.get(reverse("catalog:seller_store", args=[self.farmer.pk]))

        self.assertContains(response, "/media/store-cover-slides/store-owner-slide.jpg")
        self.assertContains(response, "data-store-cover-carousel")


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

    def test_product_detail_displays_the_seller_avatar(self):
        self.farmer.avatar = "avatars/detail-seller.jpg"
        self.farmer.save(update_fields=["avatar"])

        response = self.client.get(reverse("catalog:product_detail", args=[self.product.pk]))

        self.assertContains(response, "/media/avatars/detail-seller.jpg")

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
