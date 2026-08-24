from django.test import TestCase
from django.urls import reverse

from catalog.models import Product
from orders.models import Order

from .models import Community, FarmerProfile, User


class FarmerShopCenterTests(TestCase):
    def setUp(self):
        self.community = Community.objects.create(name="ชุมชนทดสอบ", slug="shop-center-community")
        self.farmer = User.objects.create_user(username="shop-farmer", password="pass12345", role=User.Roles.FARMER)
        FarmerProfile.objects.create(user=self.farmer, community=self.community, farm_name="สวนทดสอบ", verification_status=FarmerProfile.VerificationStatus.VERIFIED)
        self.buyer = User.objects.create_user(username="shop-buyer", password="pass12345", role=User.Roles.CONSUMER)
        self.product = Product.objects.create(
            seller=self.farmer, community=self.community, name="ผักทดสอบ", description="สินค้า", price="35.00",
            stock_quantity="3.00", low_stock_threshold="5.00", status=Product.Status.PENDING,
        )
        Order.objects.create(
            buyer=self.buyer, seller=self.farmer, community=self.community, status=Order.Status.PREPARING,
            payment_status=Order.PaymentStatus.PAID, total_amount="120.00", shipping_name="ผู้รับ",
            shipping_phone="0812345678", shipping_address="ที่อยู่ทดสอบ",
        )

    def test_farmer_can_view_own_shop_center_with_live_data(self):
        self.client.force_login(self.farmer)
        response = self.client.get(reverse("accounts:farmer_shop_center"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ศูนย์จัดการร้านค้า")
        self.assertContains(response, "120.00")

        orders_response = self.client.get(reverse("accounts:farmer_shop_center") + "?section=orders")
        self.assertEqual(orders_response.status_code, 200)
        self.assertContains(orders_response, "คำสั่งซื้อสินค้า")

    def test_verified_farmer_can_add_product_within_shop_center(self):
        self.client.force_login(self.farmer)
        response = self.client.post(
            reverse("accounts:farmer_shop_center") + "?section=products&mode=create",
            {
                "shop_action": "create_product",
                "name": "ผักเพิ่มใหม่",
                "description": "สินค้าจากศูนย์จัดการร้านค้า",
                "unit": Product.Unit.KG,
                "price": "45.00",
                "stock_quantity": "5.00",
                "minimum_order_quantity": "0.50",
                "low_stock_threshold": "1.00",
            },
        )
        self.assertRedirects(response, reverse("accounts:farmer_shop_center"), fetch_redirect_response=False)
        product = Product.objects.get(name="ผักเพิ่มใหม่")
        self.assertEqual(product.seller, self.farmer)
        self.assertEqual(product.status, Product.Status.PENDING)
    def test_consumer_cannot_view_farmer_shop_center(self):
        self.client.force_login(self.buyer)
        response = self.client.get(reverse("accounts:farmer_shop_center"))
        self.assertRedirects(response, reverse("accounts:dashboard"), fetch_redirect_response=False)
