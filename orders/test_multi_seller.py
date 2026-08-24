from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import Community, User
from catalog.models import Product

from .models import Coupon, CouponRedemption, Order


class MultiSellerCouponTests(TestCase):
    def test_coupon_is_redeemed_only_once_for_multi_seller_cart(self):
        community = Community.objects.create(
            name="Coupon community",
            slug="coupon-community",
            province="Nan",
        )
        buyer = User.objects.create_user(
            username="coupon-buyer",
            password="pass12345",
            role=User.Roles.CONSUMER,
        )
        seller_one = User.objects.create_user(
            username="coupon-seller-one",
            password="pass12345",
            role=User.Roles.FARMER,
        )
        seller_two = User.objects.create_user(
            username="coupon-seller-two",
            password="pass12345",
            role=User.Roles.FARMER,
        )
        product_one = Product.objects.create(
            seller=seller_one,
            community=community,
            name="Large basket product",
            description="Test",
            price=Decimal("200.00"),
            stock_quantity=Decimal("5.00"),
            status=Product.Status.ACTIVE,
        )
        product_two = Product.objects.create(
            seller=seller_two,
            community=community,
            name="Small basket product",
            description="Test",
            price=Decimal("100.00"),
            stock_quantity=Decimal("5.00"),
            status=Product.Status.ACTIVE,
        )
        Coupon.objects.create(
            code="ONCE50",
            discount_type=Coupon.DiscountType.FIXED,
            value=Decimal("50.00"),
        )
        self.client.force_login(buyer)
        self.client.post(reverse("orders:cart_add", args=[product_one.pk]), {"quantity": "1"})
        self.client.post(reverse("orders:cart_add", args=[product_two.pk]), {"quantity": "1"})

        response = self.client.post(
            reverse("orders:cart_checkout"),
            {
                "shipping_name": "Buyer",
                "shipping_phone": "0800000000",
                "shipping_address": "Nan",
                "shipping_province": "น่าน",
                "shipping_postal_code": "55000",
                "note": "",
                "coupon_code": "ONCE50",
            },
        )

        self.assertRedirects(
            response,
            reverse("orders:order_list"),
            fetch_redirect_response=False,
        )
        orders = Order.objects.filter(buyer=buyer)
        self.assertEqual(orders.count(), 2)
        self.assertEqual(
            sum((order.discount_amount for order in orders), Decimal("0.00")),
            Decimal("50.00"),
        )
        self.assertEqual(CouponRedemption.objects.filter(active=True).count(), 1)
        discounted = orders.get(discount_amount=Decimal("50.00"))
        self.assertEqual(discounted.seller, seller_one)