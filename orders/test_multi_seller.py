from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import Community, User
from catalog.models import Product

from .models import Order


class MultiSellerCheckoutTests(TestCase):
    def test_multi_seller_checkout_does_not_apply_legacy_discount_codes(self):
        community = Community.objects.create(
            name="Multi-seller community",
            slug="multi-seller-community",
            province="Nan",
        )
        buyer = User.objects.create_user(
            username="multi-seller-buyer",
            password="pass12345",
            role=User.Roles.CONSUMER,
        )
        seller_one = User.objects.create_user(
            username="multi-seller-seller-one",
            password="pass12345",
            role=User.Roles.FARMER,
        )
        seller_two = User.objects.create_user(
            username="multi-seller-seller-two",
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
            Decimal("0.00"),
        )
