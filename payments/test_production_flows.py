from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Community, User
from catalog.models import Product
from orders.models import Order, OrderItem

from .models import Payment, SellerPaymentAccount, SellerSettlement
from .services import process_seller_settlement
from .views import mark_payment_failed


class ProductionPaymentTests(TestCase):
    def setUp(self):
        self.community = Community.objects.create(
            name="Payment community",
            slug="production-payment-community",
            province="Bangkok",
        )
        self.buyer = User.objects.create_user(
            username="production-buyer",
            password="pass12345",
            role=User.Roles.CONSUMER,
            email="buyer@example.com",
        )
        self.seller = User.objects.create_user(
            username="production-seller",
            password="pass12345",
            role=User.Roles.FARMER,
        )
        self.product = Product.objects.create(
            seller=self.seller,
            community=self.community,
            name="Organic rice",
            description="Fresh",
            price=Decimal("100.00"),
            stock_quantity=Decimal("10.00"),
            status=Product.Status.ACTIVE,
        )
        self.order = Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            community=self.community,
            shipping_name="Buyer",
            shipping_phone="0800000000",
            shipping_address="Bangkok",
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            product_name=self.product.name,
            unit=self.product.unit,
            quantity=Decimal("1.00"),
            unit_price=self.product.price,
        )
        self.order.refresh_total()

    @override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False)
    def test_active_checkout_session_is_reused(self):
        calls = []

        class FakeSession:
            @staticmethod
            def create(**kwargs):
                calls.append(kwargs)
                return SimpleNamespace(
                    id="cs_test_reused",
                    url="https://checkout.stripe.test/reused",
                )

        fake_stripe = SimpleNamespace(
            checkout=SimpleNamespace(Session=FakeSession)
        )
        self.client.force_login(self.buyer)

        with patch("payments.views.stripe_client", return_value=fake_stripe):
            first = self.client.get(
                reverse("payments:create_checkout", args=[self.order.pk])
            )
            second = self.client.get(
                reverse("payments:create_checkout", args=[self.order.pk])
            )

        self.assertEqual(first.url, "https://checkout.stripe.test/reused")
        self.assertEqual(second.url, "https://checkout.stripe.test/reused")
        self.assertEqual(len(calls), 1)
        self.assertIn("idempotency_key", calls[0])
        self.assertEqual(
            calls[0]["payment_intent_data"]["transfer_group"],
            self.order.reference,
        )

    @override_settings(STRIPE_CONNECT_TRANSFERS_ENABLED=True)
    def test_failed_settlement_status_is_persisted(self):
        self.order.status = Order.Status.COMPLETED
        self.order.save(update_fields=["status"])
        payment = Payment.objects.create(
            order=self.order,
            amount=self.order.total_amount,
            status=Payment.Status.PAID,
            payment_intent_id="pi_failure",
        )
        account = SellerPaymentAccount.objects.create(
            seller=self.seller,
            stripe_account_id="acct_failure",
            payouts_enabled=True,
        )
        settlement = SellerSettlement.objects.create(
            payment=payment,
            seller=self.seller,
            gross_amount=Decimal("100.00"),
            fee_rate=Decimal("5.00"),
            platform_fee=Decimal("5.00"),
            net_amount=Decimal("95.00"),
            status=SellerSettlement.Status.READY,
            available_at=timezone.now(),
        )

        class FailingPaymentIntent:
            @staticmethod
            def retrieve(*args, **kwargs):
                raise RuntimeError("Stripe transfer unavailable")

        fake_stripe = SimpleNamespace(
            PaymentIntent=FailingPaymentIntent,
            Transfer=SimpleNamespace(list=lambda **kwargs: SimpleNamespace(auto_paging_iter=lambda: iter([]))),
        )
        with patch("payments.services._stripe_client", return_value=fake_stripe):
            with self.assertRaises(RuntimeError):
                process_seller_settlement(settlement)

        account.refresh_from_db()
        settlement.refresh_from_db()
        self.assertTrue(account.payouts_enabled)
        self.assertEqual(settlement.status, SellerSettlement.Status.FAILED)
        self.assertIn("Stripe transfer unavailable", settlement.failure_reason)

    def test_paid_payment_is_not_downgraded_to_failed(self):
        payment = Payment.objects.create(
            order=self.order,
            amount=self.order.total_amount,
            status=Payment.Status.PAID,
        )
        self.order.payment_status = Order.PaymentStatus.PAID
        self.order.save(update_fields=["payment_status", "updated_at"])

        mark_payment_failed(payment, self.order)

        payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PAID)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
