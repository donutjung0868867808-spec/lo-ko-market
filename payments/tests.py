import json
from types import SimpleNamespace
from unittest.mock import patch
from datetime import timedelta
from decimal import Decimal

from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Community, Notification, User
from catalog.models import Product
from orders.models import Order, OrderItem

from .models import Payment, PaymentBatch, Refund, SellerSettlement, StripeEvent
from .services import retry_due_settlements, sync_settlement_for_payment
from .views import mark_session_paid, truemoney_sandbox_checkout_url


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

    @override_settings(PAYMENT_MODE="test", STRIPE_SECRET_KEY="sk_test_batch")
    @patch("payments.views.stripe_client")
    def test_batch_checkout_redirects_to_one_stripe_session_and_webhook_pays_every_order(self, stripe_client_mock):
        second_seller = User.objects.create_user(
            username="batch-seller", password="pass12345", role=User.Roles.FARMER
        )
        second_product = Product.objects.create(
            seller=second_seller,
            community=self.community,
            name="Batch product",
            description="Second seller item",
            price=Decimal("30.00"),
            stock_quantity=Decimal("10.00"),
            status=Product.Status.ACTIVE,
        )
        second_order = Order.objects.create(
            buyer=self.buyer,
            seller=second_seller,
            community=self.community,
            shipping_name="Receiver",
            shipping_phone="0800000000",
            shipping_address="Address",
        )
        OrderItem.objects.create(
            order=second_order,
            product=second_product,
            product_name=second_product.name,
            unit=second_product.unit,
            quantity=Decimal("1.00"),
            unit_price=second_product.price,
        )
        second_order.refresh_total()
        batch = PaymentBatch.objects.create(
            buyer=self.buyer,
            amount=self.order.total_amount + second_order.total_amount,
            currency="thb",
        )
        batch.orders.set([self.order, second_order])
        stripe_client_mock.return_value = SimpleNamespace(
            checkout=SimpleNamespace(
                Session=SimpleNamespace(
                    create=lambda **kwargs: SimpleNamespace(id="cs_batch", url="https://checkout.stripe.test/cs_batch")
                )
            )
        )
        self.client.force_login(self.buyer)

        response = self.client.get(reverse("payments:batch_checkout", args=[batch.pk]))

        self.assertRedirects(response, "https://checkout.stripe.test/cs_batch", fetch_redirect_response=False)
        batch.refresh_from_db()
        self.assertEqual(batch.status, PaymentBatch.Status.PROCESSING)
        self.assertEqual(batch.checkout_session_id, "cs_batch")

        from .views import process_stripe_event
        process_stripe_event(
            {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": "cs_batch",
                        "amount_total": int(batch.amount * Decimal("100")),
                        "currency": "thb",
                        "payment_intent": "pi_batch",
                        "metadata": {"payment_batch_id": str(batch.pk), "transfer_group": f"batch-{batch.pk}"},
                    }
                },
            },
            {"provider": "stripe"},
        )
        batch.refresh_from_db()
        self.order.refresh_from_db()
        second_order.refresh_from_db()
        self.assertEqual(batch.status, PaymentBatch.Status.PAID)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(second_order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(Payment.objects.get(order=self.order).raw_payload["batch_payment_intent_id"], "pi_batch")
        self.assertEqual(
            Notification.objects.filter(
                user=self.buyer,
                title="ชำระเงินรวม 2 ร้านค้า สำเร็จ",
            ).count(),
            1,
        )
        self.assertEqual(
            Notification.objects.filter(
                user=self.seller,
                title=f"มีคำสั่งซื้อใหม่ {self.order.reference}",
            ).count(),
            1,
        )
        self.assertEqual(
            Notification.objects.filter(
                user=second_seller,
                title=f"มีคำสั่งซื้อใหม่ {second_order.reference}",
            ).count(),
            1,
        )
    @override_settings(DEBUG=True, PAYMENT_MODE="test", STRIPE_SECRET_KEY="")
    def test_batch_truemoney_uses_the_sandbox_qr_and_pays_every_order(self):
        second_order = Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            community=self.community,
            shipping_name="Second receiver",
            shipping_phone="0800000001",
            shipping_address="Second address",
        )
        OrderItem.objects.create(
            order=second_order,
            product=self.product,
            product_name=self.product.name,
            unit=self.product.unit,
            quantity=Decimal("1.00"),
            unit_price=self.product.price,
        )
        second_order.refresh_total()
        batch = PaymentBatch.objects.create(
            buyer=self.buyer,
            amount=self.order.total_amount + second_order.total_amount,
            currency="thb",
        )
        batch.orders.set([self.order, second_order])
        self.client.force_login(self.buyer)

        response = self.client.get(
            reverse("payments:batch_checkout", args=[batch.pk]),
            {"payment_method": "truemoney"},
        )

        self.assertRedirects(
            response,
            reverse("payments:batch_demo_checkout", args=[batch.pk]),
            fetch_redirect_response=False,
        )
        batch.refresh_from_db()
        self.assertEqual(batch.status, PaymentBatch.Status.PROCESSING)
        self.assertTrue(batch.checkout_session_id.startswith("demo-batch-"))
        response = self.client.get(reverse("payments:batch_demo_checkout", args=[batch.pk]))
        self.assertContains(response, "TrueMoney Wallet Sandbox")
        self.assertContains(response, 'src="data:image/png;base64,')

        scan_url = reverse("payments:batch_truemoney_sandbox_scan", args=[batch.checkout_attempt_id])
        scanner = Client()
        self.assertEqual(scanner.get(scan_url).status_code, 200)
        response = scanner.post(scan_url)
        self.assertRedirects(
            response,
            f"{reverse('payments:success')}?session_id={batch.checkout_session_id}",
            fetch_redirect_response=False,
        )
        batch.refresh_from_db()
        self.order.refresh_from_db()
        second_order.refresh_from_db()
        self.assertEqual(batch.status, PaymentBatch.Status.PAID)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(second_order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(batch.raw_payload["payment_method"], "truemoney")
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

    @override_settings(DEBUG=True, PAYMENT_MODE="test", STRIPE_SECRET_KEY="")
    def test_checkout_keeps_promptpay_selected_in_demo_payment(self):
        self.client.force_login(self.buyer)

        response = self.client.get(
            reverse("payments:create_checkout", args=[self.order.pk]),
            {"payment_method": "promptpay"},
        )

        self.assertRedirects(
            response,
            f"{reverse('payments:demo_checkout', args=[self.order.pk])}?payment_method=promptpay",
            fetch_redirect_response=False,
        )
        response = self.client.get(
            reverse("payments:demo_checkout", args=[self.order.pk]),
            {"payment_method": "promptpay"},
        )
        self.assertEqual(response.context["selected_payment_method"], "promptpay")

    @override_settings(PAYMENT_MODE="test", STRIPE_SECRET_KEY="sk_test_unused")
    def test_demo_success_does_not_verify_with_stripe(self):
        payment = Payment.objects.create(
            order=self.order,
            amount=self.order.total_amount,
            status=Payment.Status.PAID,
            checkout_session_id="demo-success-session",
        )

        with patch("payments.views.stripe_client") as stripe_client:
            response = self.client.get(
                f"{reverse('payments:success')}?session_id={payment.checkout_session_id}"
            )

        stripe_client.assert_not_called()
        self.assertNotContains(response, "ยังตรวจสอบสถานะชำระเงินจาก Stripe ไม่สำเร็จ")
    @override_settings(SITE_URL="https://market.example.com")
    def test_truemoney_qr_uses_the_canonical_public_url(self):
        payment = Payment.objects.create(
            order=self.order,
            amount=self.order.total_amount,
            status=Payment.Status.PROCESSING,
        )
        request = RequestFactory().get("/", HTTP_HOST="127.0.0.1:8000")

        self.assertEqual(
            truemoney_sandbox_checkout_url(request, payment),
            f"https://market.example.com{reverse('payments:truemoney_sandbox_scan', args=[payment.checkout_attempt_id])}",
        )

    @override_settings(DEBUG=True, PAYMENT_MODE="test", STRIPE_SECRET_KEY="")
    def test_scanning_truemoney_qr_requires_confirmation_before_payment(self):
        self.client.force_login(self.buyer)
        self.client.get(
            reverse("payments:create_checkout", args=[self.order.pk]),
            {"payment_method": "truemoney"},
        )
        payment = Payment.objects.get(order=self.order)
        scan_url = reverse("payments:truemoney_sandbox_scan", args=[payment.checkout_attempt_id])
        status_url = reverse("payments:demo_checkout_status", args=[self.order.pk])

        scanner = Client()
        response = scanner.get(scan_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "TrueMoney Wallet Sandbox")
        self.assertContains(response, "ยืนยันการชำระเงิน")
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PROCESSING)
        self.assertFalse(self.client.get(status_url).json()["paid"])

        response = scanner.post(scan_url)

        self.assertRedirects(
            response,
            f"{reverse('payments:success')}?session_id={payment.checkout_session_id}",
            fetch_redirect_response=False,
        )
        payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PAID)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(payment.raw_payload["confirmed_by"], "qr_confirmation")
        status_response = self.client.get(status_url)
        self.assertTrue(status_response.json()["paid"])
        self.assertEqual(
            status_response.json()["success_url"],
            f"{reverse('payments:success')}?session_id={payment.checkout_session_id}",
        )
    @override_settings(DEBUG=True, PAYMENT_MODE="test", STRIPE_SECRET_KEY="")
    def test_checkout_keeps_truemoney_selected_and_completes_in_demo_mode(self):
        self.client.force_login(self.buyer)

        response = self.client.get(
            reverse("payments:create_checkout", args=[self.order.pk]),
            {"payment_method": "truemoney"},
        )

        self.assertRedirects(
            response,
            f"{reverse('payments:demo_checkout', args=[self.order.pk])}?payment_method=truemoney",
            fetch_redirect_response=False,
        )
        response = self.client.get(
            reverse("payments:demo_checkout", args=[self.order.pk]),
            {"payment_method": "truemoney"},
        )
        self.assertEqual(response.context["selected_payment_method"], "truemoney")
        self.assertContains(response, "ชำระเงินด้วย TrueMoney Wallet")
        self.assertContains(response, "ยืนยันชำระด้วย TrueMoney Wallet")
        self.assertNotContains(response, "เลือกวิธีชำระเงิน")
        self.assertContains(response, "data-truemoney-fields")
        self.assertContains(response, 'src="data:image/png;base64,')
        self.assertContains(response, "'input[name=\"payment_method\"][value=\"' + method + '\"]'")

        payment = Payment.objects.get(order=self.order)
        response = self.client.post(
            reverse("payments:complete_demo_checkout", args=[self.order.pk]),
            {"payment_method": "truemoney"},
        )
        self.assertRedirects(
            response,
            f"{reverse('payments:success')}?session_id={payment.checkout_session_id}",
            fetch_redirect_response=False,
        )
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PAID)
        self.assertEqual(payment.raw_payload["payment_method"], "truemoney")
    @override_settings(DEBUG=True, PAYMENT_MODE="test", STRIPE_SECRET_KEY="")
    def test_truemoney_replaces_an_active_card_checkout_url(self):
        payment = Payment.objects.create(
            order=self.order,
            amount=self.order.total_amount,
            status=Payment.Status.PROCESSING,
            checkout_session_id="cs_card_active",
            checkout_url="https://checkout.stripe.test/card-session",
            checkout_expires_at=timezone.now() + timedelta(minutes=20),
        )
        self.order.payment_status = Order.PaymentStatus.PROCESSING
        self.order.save(update_fields=["payment_status", "updated_at"])
        self.client.force_login(self.buyer)

        response = self.client.get(
            reverse("payments:create_checkout", args=[self.order.pk]),
            {"payment_method": "truemoney"},
        )

        expected_url = f"{reverse('payments:demo_checkout', args=[self.order.pk])}?payment_method=truemoney"
        self.assertRedirects(response, expected_url, fetch_redirect_response=False)
        payment.refresh_from_db()
        self.assertIn("payment_method=truemoney", payment.checkout_url)
        self.assertTrue(payment.checkout_session_id.startswith("demo-"))
    @override_settings(SETTLEMENT_HOLD_DAYS=10)
    def test_buyer_confirmation_makes_seller_settlement_ready_immediately(self):
        confirmed_at = timezone.now()
        self.order.status = Order.Status.COMPLETED
        self.order.delivered_at = confirmed_at
        self.order.received_confirmed_at = confirmed_at
        self.order.save(update_fields=["status", "delivered_at", "received_confirmed_at", "updated_at"])
        payment = Payment.objects.create(
            order=self.order,
            amount=self.order.total_amount,
            status=Payment.Status.PAID,
        )

        settlement = sync_settlement_for_payment(payment)

        self.assertEqual(settlement.status, SellerSettlement.Status.READY)
        self.assertEqual(settlement.available_at, confirmed_at)

    @override_settings(SETTLEMENT_HOLD_DAYS=10)
    def test_seller_settlement_waits_ten_days_without_buyer_confirmation(self):
        self.order.status = Order.Status.COMPLETED
        self.order.delivered_at = timezone.now() - timedelta(days=9)
        self.order.save(update_fields=["status", "delivered_at", "updated_at"])
        payment = Payment.objects.create(
            order=self.order,
            amount=self.order.total_amount,
            status=Payment.Status.PAID,
        )

        settlement = sync_settlement_for_payment(payment)
        self.assertEqual(settlement.status, SellerSettlement.Status.PENDING)

        self.order.delivered_at = timezone.now() - timedelta(days=10, seconds=1)
        self.order.save(update_fields=["delivered_at", "updated_at"])
        settlement = sync_settlement_for_payment(payment)
        self.assertEqual(settlement.status, SellerSettlement.Status.READY)
        self.assertLessEqual(settlement.available_at, timezone.now())
    @override_settings(PAYMENT_MODE="test", DEMO_SETTLEMENTS_ENABLED=True, SETTLEMENT_HOLD_DAYS=10)
    def test_test_mode_records_simulated_seller_transfer_after_ten_days(self):
        self.order.status = Order.Status.COMPLETED
        self.order.delivered_at = timezone.now() - timedelta(days=10, seconds=1)
        self.order.save(update_fields=["status", "delivered_at", "updated_at"])
        payment = Payment.objects.create(
            order=self.order,
            amount=self.order.total_amount,
            status=Payment.Status.PAID,
        )
        settlement = sync_settlement_for_payment(payment)
        self.assertEqual(settlement.status, SellerSettlement.Status.READY)

        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(retry_due_settlements(), 1)

        settlement.refresh_from_db()
        self.assertEqual(settlement.status, SellerSettlement.Status.TRANSFERRED)
        self.assertEqual(settlement.stripe_transfer_id, f"demo-settlement-{settlement.pk}")
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
        self.assertTrue(
            Notification.objects.filter(
                user=self.seller,
                title=f"ผู้ซื้อขอคืนเงิน {self.order.reference}",
                link=self.order.get_absolute_url(),
            ).exists()
        )

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
