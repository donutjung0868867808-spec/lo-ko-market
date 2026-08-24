from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import Community, Report, User
from catalog.models import Product

from .models import Coupon, Order, OrderItem, OrderStatusHistory, ShippingRate


class OrderModelTests(TestCase):
    def test_refresh_total_sums_line_items(self):
        community = Community.objects.create(
            name="ชุมชนทดสอบ",
            slug="orders-community",
            province="น่าน",
        )
        buyer = User.objects.create_user(username="buyer", password="pass")
        seller = User.objects.create_user(
            username="seller",
            password="pass",
            role=User.Roles.FARMER,
        )
        product = Product.objects.create(
            seller=seller,
            community=community,
            name="กาแฟ",
            description="เมล็ดกาแฟ",
            price=Decimal("120.00"),
            stock_quantity=Decimal("5.00"),
            status=Product.Status.ACTIVE,
        )
        order = Order.objects.create(
            buyer=buyer,
            seller=seller,
            community=community,
            shipping_name="ผู้รับ",
            shipping_phone="0800000000",
            shipping_address="ที่อยู่",
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            unit=product.unit,
            quantity=Decimal("2.00"),
            unit_price=product.price,
        )

        order.refresh_total()

        self.assertEqual(order.total_amount, Decimal("240.00"))


class CartWorkflowTests(TestCase):
    def setUp(self):
        self.community = Community.objects.create(
            name="ชุมชนตะกร้า",
            slug="cart-community",
            province="เชียงราย",
        )
        self.buyer = User.objects.create_user(
            username="cart-buyer",
            password="pass",
            role=User.Roles.CONSUMER,
            display_name="ผู้ซื้อตะกร้า",
            phone="0811111111",
        )
        self.seller = User.objects.create_user(
            username="cart-seller",
            password="pass",
            role=User.Roles.FARMER,
        )
        self.product = Product.objects.create(
            seller=self.seller,
            community=self.community,
            name="ข้าวโพดหวาน",
            description="สดจากไร่",
            price=Decimal("25.00"),
            stock_quantity=Decimal("10.00"),
            status=Product.Status.ACTIVE,
        )

    def test_consumer_can_add_product_to_cart(self):
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse("orders:cart_add", args=[self.product.pk]),
            {"quantity": "2"},
        )

        self.assertRedirects(response, reverse("orders:cart"))
        self.assertEqual(self.client.session["cart"][str(self.product.pk)], "2.00")

    def test_cart_does_not_store_one_hundredth_quantity(self):
        self.client.force_login(self.buyer)

        self.client.post(
            reverse("orders:cart_add", args=[self.product.pk]),
            {"quantity": "1.01"},
        )

        self.assertEqual(self.client.session["cart"][str(self.product.pk)], "0.50")

    def test_piece_product_rounds_invalid_fraction_to_whole_unit(self):
        piece_product = Product.objects.create(
            seller=self.seller,
            community=self.community,
            name="Piece product",
            description="Sold by piece",
            price=Decimal("10.00"),
            stock_quantity=Decimal("10.00"),
            minimum_order_quantity=Decimal("1.00"),
            unit=Product.Unit.PIECE,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.buyer)

        self.client.post(
            reverse("orders:cart_add", args=[piece_product.pk]),
            {"quantity": "0.50"},
        )

        self.assertEqual(self.client.session["cart"][str(piece_product.pk)], "1.00")
    def test_direct_checkout_accepts_half_unit_quantity(self):
        self.client.force_login(self.buyer)

        response = self.client.get(
            reverse("orders:checkout", args=[self.product.pk]),
            {"quantity": "3.50"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial["quantity"], Decimal("3.50"))

    def test_cart_checkout_creates_order(self):
        self.client.force_login(self.buyer)
        self.client.post(reverse("orders:cart_add", args=[self.product.pk]), {"quantity": "3"})

        response = self.client.post(
            reverse("orders:cart_checkout"),
            {
                "shipping_name": "ผู้รับสินค้า",
                "shipping_phone": "0899999999",
                "shipping_address": "บ้านเลขที่ 9",
                "shipping_province": "เชียงใหม่",
                "shipping_postal_code": "50000",
                "note": "ส่งช่วงเช้า",
            },
        )

        order = Order.objects.get(buyer=self.buyer, seller=self.seller)
        self.assertRedirects(response, reverse("payments:create_checkout", args=[order.pk]), fetch_redirect_response=False)
        self.assertEqual(order.items.get().quantity, Decimal("3.00"))
        self.assertEqual(order.subtotal, Decimal("75.00"))
        self.assertEqual(order.shipping_fee, Decimal("50.00"))
        self.assertEqual(order.total_amount, Decimal("125.00"))
        self.assertTrue(order.stock_reserved)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("7.00"))
        self.assertEqual(self.client.session.get("cart"), {})

    def test_shipping_rate_uses_destination_and_product_weight(self):
        self.product.weight_grams = 2000
        self.product.save(update_fields=["weight_grams"])
        ShippingRate.objects.create(
            province="เชียงใหม่",
            base_fee=Decimal("30.00"),
            fee_per_kg=Decimal("10.00"),
        )
        self.client.force_login(self.buyer)
        self.client.post(reverse("orders:cart_add", args=[self.product.pk]), {"quantity": "3"})

        self.client.post(
            reverse("orders:cart_checkout"),
            {
                "shipping_name": "ผู้รับสินค้า",
                "shipping_phone": "0899999999",
                "shipping_address": "บ้านเลขที่ 9",
                "shipping_province": "เชียงใหม่",
                "shipping_postal_code": "50000",
                "note": "",
            },
        )

        order = Order.objects.get(buyer=self.buyer, seller=self.seller)
        self.assertEqual(order.shipping_fee, Decimal("90.00"))
        self.assertEqual(order.total_amount, Decimal("165.00"))

    def test_checkout_rejects_invalid_postal_code(self):
        self.client.force_login(self.buyer)
        self.client.post(reverse("orders:cart_add", args=[self.product.pk]), {"quantity": "1"})

        response = self.client.post(
            reverse("orders:cart_checkout"),
            {
                "shipping_name": "ผู้รับสินค้า",
                "shipping_phone": "0899999999",
                "shipping_address": "บ้านเลขที่ 9",
                "shipping_province": "เชียงใหม่",
                "shipping_postal_code": "50",
                "note": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "กรุณากรอกรหัสไปรษณีย์ 5 หลัก")
        self.assertFalse(Order.objects.filter(buyer=self.buyer).exists())


class BuyerReportTests(TestCase):
    def test_seller_can_report_buyer_from_order(self):
        community = Community.objects.create(
            name="ชุมชนรายงานผู้ซื้อ",
            slug="buyer-report-community",
            province="พะเยา",
        )
        buyer = User.objects.create_user(username="reported-buyer", password="pass", role=User.Roles.CONSUMER)
        seller = User.objects.create_user(username="reporting-seller", password="pass", role=User.Roles.FARMER)
        order = Order.objects.create(
            buyer=buyer,
            seller=seller,
            community=community,
            shipping_name="ผู้รับ",
            shipping_phone="0800000000",
            shipping_address="ที่อยู่",
        )
        self.client.force_login(seller)

        response = self.client.post(
            reverse("orders:report_buyer", args=[order.pk]),
            {"reason": Report.Reason.ABUSE, "details": "ติดต่อไม่ได้"},
        )

        self.assertRedirects(response, order.get_absolute_url())
        self.assertTrue(
            Report.objects.filter(
                reporter=seller,
                reported_user=buyer,
                target_type=Report.TargetType.BUYER,
                order=order,
            ).exists()
        )

class InventoryReservationTests(TestCase):
    def setUp(self):
        self.community = Community.objects.create(name="ชุมชนสต็อก", slug="stock-community", province="น่าน")
        self.buyer = User.objects.create_user(username="stock-buyer", password="pass", role=User.Roles.CONSUMER)
        self.seller = User.objects.create_user(username="stock-seller", password="pass", role=User.Roles.FARMER)
        self.product = Product.objects.create(
            seller=self.seller,
            community=self.community,
            name="ข้าวสาร",
            description="ข้าวชุมชน",
            price=Decimal("100.00"),
            stock_quantity=Decimal("5.00"),
            status=Product.Status.ACTIVE,
        )

    def test_buyer_cancel_restores_reserved_stock(self):
        self.client.force_login(self.buyer)
        self.client.post(reverse("orders:cart_add", args=[self.product.pk]), {"quantity": "2"})
        self.client.post(
            reverse("orders:cart_checkout"),
            {
                "shipping_name": "ผู้รับ",
                "shipping_phone": "0800000000",
                "shipping_address": "ที่อยู่",
                "shipping_province": "น่าน",
                "shipping_postal_code": "55000",
                "note": "",
            },
        )
        order = Order.objects.get(buyer=self.buyer)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("3.00"))

        self.client.post(reverse("orders:cancel_order", args=[order.pk]), {"reason": "เปลี่ยนแผนการสั่งซื้อ"})

        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertFalse(order.stock_reserved)
        self.assertEqual(self.product.stock_quantity, Decimal("5.00"))
        history = OrderStatusHistory.objects.filter(
            order=order,
            status=Order.Status.CANCELLED,
        ).latest("created_at")
        self.assertIn("เปลี่ยนแผนการสั่งซื้อ", history.note)

    def test_coupon_reduces_total_and_is_released_on_cancel(self):
        Coupon.objects.create(
            code="FARM50",
            discount_type=Coupon.DiscountType.FIXED,
            value=Decimal("50.00"),
            minimum_spend=Decimal("100.00"),
        )
        self.client.force_login(self.buyer)
        self.client.post(reverse("orders:cart_add", args=[self.product.pk]), {"quantity": "2"})
        self.client.post(
            reverse("orders:cart_checkout"),
            {
                "shipping_name": "ผู้รับ",
                "shipping_phone": "0800000000",
                "shipping_address": "ที่อยู่",
                "shipping_province": "น่าน",
                "shipping_postal_code": "55000",
                "note": "",
                "coupon_code": "FARM50",
            },
        )
        order = Order.objects.get(buyer=self.buyer)
        self.assertEqual(order.subtotal, Decimal("200.00"))
        self.assertEqual(order.shipping_fee, Decimal("50.00"))
        self.assertEqual(order.discount_amount, Decimal("50.00"))
        self.assertEqual(order.total_amount, Decimal("200.00"))
        self.assertTrue(order.coupon_redemption.active)

        self.client.post(reverse("orders:cancel_order", args=[order.pk]), {"reason": "เปลี่ยนแผนการสั่งซื้อ"})

        order.coupon_redemption.refresh_from_db()
        self.assertFalse(order.coupon_redemption.active)
