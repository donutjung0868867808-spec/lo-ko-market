from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Community, User
from orders.models import Order
from .models import Payment, Refund, SellerPaymentAccount, SellerSettlement
from .services import process_seller_settlement, retry_due_settlements


@override_settings(STRIPE_CONNECT_TRANSFERS_ENABLED=True, SETTLEMENT_MAX_ATTEMPTS=5)
class AutomaticSettlementTests(TestCase):
    def setUp(self):
        buyer = User.objects.create_user(username="auto-buyer")
        seller = User.objects.create_user(username="auto-seller", role=User.Roles.FARMER)
        community = Community.objects.create(name="Payouts", slug="payouts", province="Nan")
        self.order = Order.objects.create(
            buyer=buyer, seller=seller, community=community, status=Order.Status.COMPLETED,
            total_amount=Decimal("100"), shipping_name="Buyer", shipping_phone="0800000000",
            shipping_address="Test",
        )
        self.payment = Payment.objects.create(order=self.order, amount=Decimal("100"),
                                              status=Payment.Status.PAID, payment_intent_id="pi_test")
        self.account = SellerPaymentAccount.objects.create(
            seller=seller, stripe_account_id="acct_test", payouts_enabled=True,
        )
        self.settlement = SellerSettlement.objects.create(
            payment=self.payment, seller=seller, gross_amount=Decimal("100"),
            fee_rate=Decimal("5"), platform_fee=Decimal("5"), net_amount=Decimal("95"),
            available_at=timezone.now() - timedelta(days=1), status=SellerSettlement.Status.READY,
        )
        self.transfer = {"id": "tr_test", "amount": 9500, "currency": "thb", "destination": "acct_test",
                         "reversed": False, "metadata": {"settlement_id": str(self.settlement.pk)}}
        self.stripe = SimpleNamespace(
            Transfer=Mock(), PaymentIntent=Mock(),
        )
        self.stripe.Transfer.list.return_value = SimpleNamespace(auto_paging_iter=lambda: iter([]))
        self.stripe.Transfer.create.return_value = self.transfer
        self.stripe.PaymentIntent.retrieve.return_value = {"latest_charge": {"id": "ch_test"}}
        self.mock = patch("payments.services._stripe_client", return_value=self.stripe)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_due_job_transfers_once_with_source_and_idempotency(self):
        self.assertEqual(retry_due_settlements(), 1)
        self.assertEqual(retry_due_settlements(), 0)
        self.stripe.Transfer.create.assert_called_once()
        args = self.stripe.Transfer.create.call_args.kwargs
        self.assertEqual(args["source_transaction"], "ch_test")
        self.assertEqual(args["idempotency_key"], f"seller-settlement-{self.settlement.pk}")
        self.assertEqual(args["amount"], 9500)

    def test_reconciles_transfer_after_lost_response_without_creating_again(self):
        self.stripe.Transfer.list.return_value = SimpleNamespace(auto_paging_iter=lambda: iter([self.transfer]))
        result = process_seller_settlement(self.settlement)
        self.assertEqual(result.status, SellerSettlement.Status.TRANSFERRED)
        self.stripe.Transfer.create.assert_not_called()
        self.stripe.PaymentIntent.retrieve.assert_not_called()

    def test_network_error_is_persisted_and_backoff_is_respected(self):
        self.stripe.Transfer.create.side_effect = OSError("connection lost")
        with self.assertRaises(OSError):
            process_seller_settlement(self.settlement)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, SellerSettlement.Status.FAILED)
        self.assertEqual(self.settlement.attempts, 1)
        self.assertGreater(self.settlement.next_attempt_at, timezone.now())
        self.assertEqual(retry_due_settlements(), 0)
        self.stripe.Transfer.create.assert_called_once()

    def test_incomplete_order_or_hold_period_blocks_transfer(self):
        self.order.status = Order.Status.SHIPPED
        self.order.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            process_seller_settlement(self.settlement)
        self.order.status = Order.Status.COMPLETED
        self.order.save(update_fields=["status"])
        self.settlement.available_at = timezone.now() + timedelta(days=1)
        self.settlement.save(update_fields=["available_at"])
        with self.assertRaises(ValidationError):
            process_seller_settlement(self.settlement)
        self.stripe.Transfer.create.assert_not_called()

    def test_pending_refund_blocks_transfer(self):
        Refund.objects.create(payment=self.payment, requested_by=self.order.buyer,
                              amount=Decimal("50"), reason="Return")
        with self.assertRaises(ValidationError):
            process_seller_settlement(self.settlement)
        self.stripe.Transfer.create.assert_not_called()

    def test_manual_hold_and_attempt_limit_are_not_released_by_job(self):
        self.settlement.status = SellerSettlement.Status.HELD
        self.settlement.failure_reason = "Manual review"
        self.settlement.save()
        self.assertEqual(retry_due_settlements(), 0)
        self.settlement.status = SellerSettlement.Status.FAILED
        self.settlement.attempts = 5
        self.settlement.save()
        self.assertEqual(retry_due_settlements(), 0)
        self.stripe.Transfer.create.assert_not_called()

    def test_reconciled_mismatched_transfer_is_held_for_review(self):
        self.transfer["amount"] = 123
        self.stripe.Transfer.list.return_value = SimpleNamespace(auto_paging_iter=lambda: iter([self.transfer]))
        result = process_seller_settlement(self.settlement)
        self.assertEqual(result.status, SellerSettlement.Status.HELD)
        self.assertEqual(result.stripe_transfer_id, "tr_test")
        self.stripe.Transfer.create.assert_not_called()
