import json
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Community, Notification, User
from catalog.models import Product
from orders.models import Order, OrderItem

from .models import Payment, Refund, SellerSettlement, StripeEvent
from .views import mark_session_paid


class PaymentWorkflowTests(TestCase):
    def setUp(self):
        self.community = Community.objects.create(
            name="ชุมชนชำระเงิน",
            slug="payment-community",
            province="เชียงใหม่",
        )
        self.buyer = User.objects.create_user(
            username="payment-buyer",
            password="pass12345",
            role=User.Roles.CONSUMER,
        )
        self.seller = User.objects.create_user(
            username="payment-seller",
            password="pass12345",
            role=User.Roles.FARMER,
        )
        self.product = Product.objects.create(
            seller=self.seller,
            community=self.community,
            name="ผักบุ้ง",
            description="สดจากสวน",
            price=Decimal("20.00"),
            stock_quantity=Decimal("10.00"),
            status=Product.Status.ACTIVE,
        )
        self.order = Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            community=self.community,
            shipping_name="ผู้รับสินค้า",
            shipping_phone="0800000000",
            shipping_address="ที่อยู่จัดส่ง",
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            product_name=self.product.name,
            unit=self.product.unit,
            quantity=Decimal("2.00"),
            unit_price=self.product.price,
        )
        self.order.refresh_total()

    @override_settings(DEBUG=True, PAYMENT_MODE="test", STRIPE_SECRET_KEY="")
    def test_checkout_uses_interactive_demo_payment_in_test_mode(self):
        self.client.force_login(self.buyer)

        response = self.client.get(reverse("payments:create_checkout", args=[self.order.pk]))

        self.assertRedirects(
            response,
            reverse("payments:demo_checkout", args=[self.order.pk]),
            fetch_redirect_response=False,
        )
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        payment = Payment.objects.get(order=self.order)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PROCESSING)
        self.assertEqual(payment.status, Payment.Status.PROCESSING)
        self.assertEqual(self.product.stock_quantity, Decimal("8.00"))

        response = self.client.get(reverse("payments:demo_checkout", args=[self.order.pk]))
        self.assertContains(response, "โหมดทดลอง ไม่มีการตัดเงินจริง")

        response = self.client.post(
            reverse("payments:complete_demo_checkout", args=[self.order.pk]),
            {"payment_method": "promptpay"},
        )
        self.assertRedirects(
            response,
            f"{reverse('payments:success')}?session_id={payment.checkout_session_id}",
            fetch_redirect_response=False,
        )
        self.order.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(payment.status, Payment.Status.PAID)
        self.assertEqual(payment.raw_payload["payment_method"], "promptpay")

    @override_settings(DEBUG=False, PAYMENT_MODE="live", STRIPE_SECRET_KEY="", SECURE_SSL_REDIRECT=False)
    def test_checkout_without_provider_in_live_mode_fails_safely(self):
        self.client.force_login(self.buyer)

        response = self.client.get(reverse("payments:create_checkout", args=[self.order.pk]))

        self.assertRedirects(response, self.order.get_absolute_url(), fetch_redirect_response=False)
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        payment = Payment.objects.get(order=self.order)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.FAILED)
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.assertEqual(self.product.stock_quantity, Decimal("10.00"))

    @override_settings(
        DEBUG=False,
        PAYMENT_MODE="test",
        STRIPE_SECRET_KEY="sk_live_should_not_be_used",
        SECURE_SSL_REDIRECT=False,
    )
    def test_test_mode_blocks_a_live_stripe_key(self):
        self.client.force_login(self.buyer)

        response = self.client.get(reverse("payments:create_checkout", args=[self.order.pk]))

        self.assertRedirects(
            response,
            reverse("payments:demo_checkout", args=[self.order.pk]),
            fetch_redirect_response=False,
        )
        self.order.refresh_from_db()
        payment = Payment.objects.get(order=self.order)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PROCESSING)
        self.assertEqual(payment.status, Payment.Status.PROCESSING)

    @override_settings(DEBUG=False, STRIPE_SECRET_KEY="", STRIPE_WEBHOOK_SECRET="whsec_test", SECURE_SSL_REDIRECT=False)
    def test_webhook_rejects_unsigned_payload_in_production(self):
        payload = {
            "type": "checkout.session.completed",
            "data": {"object": {"id": "sess_unsigned", "metadata": {"order_id": str(self.order.pk)}}},
        }

        response = self.client.post(
            reverse("payments:stripe_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.UNPAID)

    def test_mark_session_paid_is_idempotent_for_stock(self):
        payment = Payment.objects.create(
            order=self.order,
            amount=self.order.total_amount,
            currency="thb",
            checkout_session_id="sess_paid_once",
        )
        session = {
            "id": payment.checkout_session_id,
            "payment_intent": "pi_paid_once",
            "metadata": {"order_id": str(self.order.pk)},
        }

        mark_session_paid(session, {"event": "first"})
        mark_session_paid(session, {"event": "duplicate"})

        self.order.refresh_from_db()
        self.product.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(payment.status, Payment.Status.PAID)
        self.assertEqual(self.product.stock_quantity, Decimal("8.00"))
        self.assertEqual(payment.raw_payload, {"event": "duplicate"})

    @override_settings(DEBUG=True, STRIPE_SECRET_KEY="")
    def test_full_refund_restores_stock_and_marks_order_refunded(self):
        payment = Payment.objects.create(
            order=self.order,
            amount=self.order.total_amount,
            currency="thb",
            checkout_session_id="sess_refund",
        )
        mark_session_paid({"id": "sess_refund", "payment_intent": "pi_refund"})
        owner = User.objects.create_user(
            username="refund-owner",
            password="pass12345",
            role=User.Roles.OWNER,
        )
        refund = Refund.objects.create(
            payment=payment,
            amount=payment.amount,
            reason="สินค้าเสียหาย",
            requested_by=self.buyer,
        )
        self.client.force_login(owner)

        self.client.post(reverse("payments:process_refund", args=[refund.pk]))

        refund.refresh_from_db()
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.SUCCEEDED)
        self.assertEqual(self.order.status, Order.Status.REFUNDED)
        self.assertEqual(self.product.stock_quantity, Decimal("10.00"))

    @override_settings(DEBUG=True, STRIPE_SECRET_KEY="")
    def test_duplicate_webhook_event_is_processed_once(self):
        payment = Payment.objects.create(
            order=self.order,
            amount=self.order.total_amount,
            currency="thb",
            checkout_session_id="sess_duplicate",
        )
        payload = {
            "id": "evt_duplicate",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "sess_duplicate",
                    "payment_intent": "pi_duplicate",
                    "metadata": {"order_id": str(self.order.pk)},
                }
            },
        }
        url = reverse("payments:stripe_webhook")
        first = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        second = self.client.post(url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(StripeEvent.objects.filter(event_id="evt_duplicate").count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("8.00"))
    @override_settings(DEBUG=True, STRIPE_SECRET_KEY="")
    def test_refund_request_holds_settlement_and_rejection_releases_it(self):
        payment = Payment.objects.create(
            order=self.order,
            amount=self.order.total_amount,
            currency="thb",
            checkout_session_id="sess_refund_review",
        )
        mark_session_paid(
            {
                "id": "sess_refund_review",
                "payment_intent": "pi_refund_review",
                "metadata": {"order_id": str(self.order.pk)},
            }
        )
        owner = User.objects.create_user(
            username="refund-review-owner",
            password="pass12345",
            role=User.Roles.OWNER,
        )
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse("payments:request_refund", args=[self.order.pk]),
            {"amount": "20.00", "reason": "สินค้าที่ได้รับไม่ตรงกับรายการ"},
        )

        self.assertRedirects(response, self.order.get_absolute_url())
        refund = Refund.objects.get(payment=payment)
        settlement = SellerSettlement.objects.get(payment=payment)
        self.assertEqual(refund.status, Refund.Status.REQUESTED)
        self.assertEqual(settlement.status, SellerSettlement.Status.HELD)

        self.client.force_login(owner)
        response = self.client.post(
            reverse("payments:reject_refund", args=[refund.pk]),
            {"resolution_note": "ตรวจสอบหลักฐานแล้วพบว่าสินค้าตรงกับรายการ"},
        )

        self.assertRedirects(response, self.order.get_absolute_url())
        refund.refresh_from_db()
        settlement.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.REJECTED)
        self.assertEqual(refund.handled_by, owner)
        self.assertIsNotNone(refund.handled_at)
        self.assertEqual(settlement.status, SellerSettlement.Status.PENDING)
        self.assertTrue(
            Notification.objects.filter(
                user=self.buyer,
                title__contains="ไม่ได้รับการอนุมัติ",
            ).exists()
        )

    @override_settings(DEBUG=True, STRIPE_SECRET_KEY="")
    def test_rejected_refund_cannot_be_processed(self):
        payment = Payment.objects.create(
            order=self.order,
            amount=self.order.total_amount,
            currency="thb",
            status=Payment.Status.PAID,
        )
        refund = Refund.objects.create(
            payment=payment,
            amount=Decimal("10.00"),
            reason="ทดสอบสถานะ",
            requested_by=self.buyer,
            status=Refund.Status.REJECTED,
        )
        owner = User.objects.create_user(
            username="refund-state-owner",
            password="pass12345",
            role=User.Roles.OWNER,
        )
        self.client.force_login(owner)

        response = self.client.post(reverse("payments:process_refund", args=[refund.pk]))

        self.assertEqual(response.status_code, 404)
        refund.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.REJECTED)
