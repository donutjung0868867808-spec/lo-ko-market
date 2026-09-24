from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import Community, FarmerProfile, Report, User
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

        cart_response = self.client.get(reverse("orders:cart"))
        self.assertContains(cart_response, 'data-cart-count="1"', html=False)

    def test_seller_can_buy_from_another_store_with_the_same_account(self):
        seller_buyer = User.objects.create_user(
            username="seller-who-buys",
            password="pass",
            role=User.Roles.FARMER,
        )
        self.client.force_login(seller_buyer)

        response = self.client.post(
            reverse("orders:cart_add", args=[self.product.pk]),
            {"quantity": "2"},
        )

        self.assertRedirects(response, reverse("orders:cart"))
        self.assertEqual(self.client.session["cart"][str(self.product.pk)], "2.00")

    def test_seller_cannot_add_own_product_to_cart(self):
        self.client.force_login(self.seller)

        response = self.client.post(
            reverse("orders:cart_add", args=[self.product.pk]),
            {"quantity": "2"},
        )

        self.assertRedirects(response, self.product.get_absolute_url())
        self.assertNotIn(str(self.product.pk), self.client.session.get("cart", {}))

    def test_seller_order_history_shows_purchases_instead_of_store_sales(self):
        seller_buyer = User.objects.create_user(
            username="seller-order-history",
            password="pass",
            role=User.Roles.FARMER,
        )
        purchase = Order.objects.create(
            reference="PURCHASE-AS-BUYER",
            buyer=seller_buyer,
            seller=self.seller,
            community=self.community,
            shipping_name="Buyer",
            shipping_phone="0800000000",
            shipping_address="Buyer address",
        )
        OrderItem.objects.create(
            order=purchase,
            product=self.product,
            product_name=self.product.name,
            unit=self.product.unit,
            quantity=Decimal("1.00"),
            unit_price=self.product.price,
        )
        store_sale = Order.objects.create(
            reference="SALE-AS-SELLER",
            buyer=self.buyer,
            seller=seller_buyer,
            community=self.community,
            shipping_name="Another buyer",
            shipping_phone="0800000001",
            shipping_address="Another address",
        )
        OrderItem.objects.create(
            order=store_sale,
            product=self.product,
            product_name="Store product",
            unit=Product.Unit.KG,
            quantity=Decimal("1.00"),
            unit_price=Decimal("20.00"),
        )
        self.client.force_login(seller_buyer)

        response = self.client.get(reverse("orders:order_list"))

        self.assertContains(response, "PURCHASE-AS-BUYER")
        self.assertNotContains(response, "SALE-AS-SELLER")
        self.assertContains(response, "การซื้อของฉัน")

    def test_buyer_order_history_shows_product_image(self):
        self.product.image = "products/order-history-image.jpg"
        self.product.save(update_fields=["image"])
        order = Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            community=self.community,
            shipping_name="Buyer",
            shipping_phone="0800000000",
            shipping_address="Buyer address",
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name=self.product.name,
            unit=self.product.unit,
            quantity=Decimal("1.00"),
            unit_price=self.product.price,
        )
        self.client.force_login(self.buyer)

        response = self.client.get(reverse("orders:order_list"))

        self.assertContains(response, self.product.image.url)
        self.assertContains(response, self.product.name)
        self.assertContains(
            response,
            self.seller.display_name or self.seller.username,
        )
        self.assertContains(response, order.reference)

        detail_response = self.client.get(order.get_absolute_url())
        self.assertContains(detail_response, self.product.image.url)

    def test_buyer_order_history_shows_linked_store_profile(self):
        self.seller.avatar = "avatars/order-history-store.jpg"
        self.seller.save(update_fields=["avatar"])
        FarmerProfile.objects.create(
            user=self.seller,
            community=self.community,
            farm_name="สวนข้าวโพดทดสอบ",
        )
        order = Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            community=self.community,
            shipping_name="Buyer",
            shipping_phone="0800000000",
            shipping_address="Buyer address",
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name=self.product.name,
            unit=self.product.unit,
            quantity=Decimal("1.00"),
            unit_price=self.product.price,
        )
        self.client.force_login(self.buyer)

        response = self.client.get(reverse("orders:order_list"))

        self.assertContains(response, "สวนข้าวโพดทดสอบ")
        self.assertContains(response, self.seller.avatar.url)
        self.assertContains(response, reverse("catalog:seller_store", args=[self.seller.pk]))

    def test_buyer_order_history_can_expand_additional_products(self):
        additional_product = Product.objects.create(
            seller=self.seller,
            community=self.community,
            name="Additional product",
            description="Second product in an order.",
            price=Decimal("20.00"),
            stock_quantity=Decimal("10.00"),
            status=Product.Status.ACTIVE,
        )
        order = Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            community=self.community,
            shipping_name="Buyer",
            shipping_phone="0800000000",
            shipping_address="Buyer address",
        )
        for product in (self.product, additional_product):
            OrderItem.objects.create(
                order=order,
                product=product,
                product_name=product.name,
                unit=product.unit,
                quantity=Decimal("1.00"),
                unit_price=product.price,
            )
        self.client.force_login(self.buyer)

        response = self.client.get(reverse("orders:order_list"))

        self.assertContains(response, "ดูเพิ่มเติม")
        self.assertContains(response, "สินค้ารวม 2 รายการ")
        self.assertContains(response, additional_product.name)

    def test_buyer_can_add_an_order_to_cart_again(self):
        order = Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            community=self.community,
            shipping_name="Buyer",
            shipping_phone="0800000000",
            shipping_address="Buyer address",
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name=self.product.name,
            unit=self.product.unit,
            quantity=Decimal("2.00"),
            unit_price=self.product.price,
        )
        self.client.force_login(self.buyer)

        response = self.client.post(reverse("orders:order_reorder", args=[order.pk]))

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

    def test_cart_checkout_only_orders_selected_products(self):
        other_product = Product.objects.create(
            seller=self.seller,
            community=self.community,
            name="Selected later",
            description="Kept in cart",
            price=Decimal("40.00"),
            stock_quantity=Decimal("10.00"),
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.buyer)
        self.client.post(reverse("orders:cart_add", args=[self.product.pk]), {"quantity": "2"})
        self.client.post(reverse("orders:cart_add", args=[other_product.pk]), {"quantity": "1"})

        response = self.client.post(
            reverse("orders:cart_checkout"),
            {
                "cart_selection": "1",
                "selected_items": str(self.product.pk),
                "shipping_name": "Cart buyer",
                "shipping_phone": "0899999999",
                "shipping_address": "9 Market Road",
                "shipping_province": "Chiang Mai",
                "shipping_postal_code": "50000",
                "note": "",
            },
        )

        order = Order.objects.get(buyer=self.buyer, seller=self.seller)
        self.assertRedirects(response, reverse("payments:create_checkout", args=[order.pk]), fetch_redirect_response=False)
        self.assertEqual(list(order.items.values_list("product_id", flat=True)), [self.product.pk])
        self.assertEqual(order.subtotal, Decimal("50.00"))
        self.assertEqual(
            self.client.session.get("cart"),
            {str(other_product.pk): "1.00"},
        )

    def test_cart_checkout_shows_shipping_details_after_selecting_products(self):
        self.client.force_login(self.buyer)
        self.client.post(reverse("orders:cart_add", args=[self.product.pk]), {"quantity": "1"})

        cart_response = self.client.get(reverse("orders:cart"))
        self.assertNotContains(cart_response, "ที่อยู่จัดส่ง")

        response = self.client.get(
            reverse("orders:cart_checkout"),
            {"cart_selection": "1", "selected_items": str(self.product.pk)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "orders/cart_checkout.html")
        self.assertContains(response, "ที่อยู่จัดส่ง")
        self.assertContains(response, self.product.name)

    def test_cart_update_recalculates_item_and_cart_total(self):
        self.client.force_login(self.buyer)
        self.client.post(reverse("orders:cart_add", args=[self.product.pk]), {"quantity": "1"})

        response = self.client.post(
            reverse("orders:cart_update", args=[self.product.pk]),
            {"quantity": "2"},
        )

        self.assertRedirects(response, reverse("orders:cart"))
        cart_response = self.client.get(reverse("orders:cart"))
        self.assertEqual(cart_response.context["items"][0]["line_total"], Decimal("50.00"))
        self.assertEqual(cart_response.context["total"], Decimal("50.00"))
        self.assertNotContains(cart_response, ">อัปเดต<")

    def test_cart_checkout_keeps_the_quantity_shown_in_the_cart(self):
        self.client.force_login(self.buyer)
        self.client.post(reverse("orders:cart_add", args=[self.product.pk]), {"quantity": "1"})

        response = self.client.get(
            reverse("orders:cart_checkout"),
            {
                "cart_selection": "1",
                "selected_items": str(self.product.pk),
                f"cart_quantity_{self.product.pk}": "2",
            },
        )

        self.assertEqual(response.context["items"][0]["quantity"], Decimal("2.00"))
        self.assertEqual(response.context["total"], Decimal("50.00"))
        self.assertEqual(self.client.session["cart"][str(self.product.pk)], "2.00")

    def test_cart_checkout_requires_a_selected_product(self):
        self.client.force_login(self.buyer)
        self.client.post(reverse("orders:cart_add", args=[self.product.pk]), {"quantity": "1"})

        response = self.client.post(
            reverse("orders:cart_checkout"),
            {
                "cart_selection": "1",
                "shipping_name": "Cart buyer",
                "shipping_phone": "0899999999",
                "shipping_address": "9 Market Road",
                "shipping_province": "Chiang Mai",
                "shipping_postal_code": "50000",
                "note": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "กรุณาเลือกสินค้าอย่างน้อย 1 รายการ")
        self.assertFalse(Order.objects.filter(buyer=self.buyer).exists())

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
