from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from .models import CustomerPaymentProfile, SavedPaymentMethod


class SavedPaymentMethodTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="card-owner",
            password="pass12345",
            email="card-owner@example.com",
            role=User.Roles.CONSUMER,
        )
        self.other_user = User.objects.create_user(
            username="other-card-owner",
            password="pass12345",
            email="other-card@example.com",
            role=User.Roles.CONSUMER,
        )
        self.client.force_login(self.user)

    @staticmethod
    def stripe_mock():
        stripe = MagicMock()
        stripe.Customer.create.return_value = SimpleNamespace(id="cus_test_owner")
        stripe.checkout.Session.create.return_value = SimpleNamespace(
            id="cs_setup_test",
            url="https://checkout.stripe.test/setup",
        )
        return stripe

    def test_setup_creates_customer_profile_and_redirects_to_stripe(self):
        stripe = self.stripe_mock()

        with patch("payments.views.stripe_client", return_value=stripe):
            response = self.client.post(reverse("payments:create_payment_method_setup"))

        self.assertRedirects(
            response,
            "https://checkout.stripe.test/setup",
            fetch_redirect_response=False,
        )
        profile = CustomerPaymentProfile.objects.get(user=self.user)
        self.assertEqual(profile.stripe_customer_id, "cus_test_owner")
        stripe.checkout.Session.create.assert_called_once()
        self.assertEqual(
            stripe.checkout.Session.create.call_args.kwargs["mode"],
            "setup",
        )

    def test_success_stores_only_masked_card_metadata(self):
        profile = CustomerPaymentProfile.objects.create(
            user=self.user,
            stripe_customer_id="cus_test_owner",
        )
        stripe = self.stripe_mock()
        stripe.checkout.Session.retrieve.return_value = {
            "customer": profile.stripe_customer_id,
            "setup_intent": {
                "status": "succeeded",
                "payment_method": {
                    "id": "pm_test_4242",
                    "type": "card",
                    "card": {
                        "brand": "visa",
                        "last4": "4242",
                        "exp_month": 12,
                        "exp_year": 2030,
                    },
                },
            },
        }

        with patch("payments.views.stripe_client", return_value=stripe):
            response = self.client.get(
                reverse("payments:payment_method_setup_success"),
                {"session_id": "cs_setup_test"},
            )

        self.assertRedirects(response, reverse("accounts:payment_settings"))
        method = SavedPaymentMethod.objects.get(profile=profile)
        self.assertEqual(method.stripe_payment_method_id, "pm_test_4242")
        self.assertEqual(method.last4, "4242")
        self.assertEqual(method.brand, "visa")
        self.assertTrue(method.is_default)
        self.assertFalse(hasattr(method, "card_number"))
        self.assertFalse(hasattr(method, "cvc"))

    def test_user_cannot_delete_another_users_payment_method(self):
        profile = CustomerPaymentProfile.objects.create(
            user=self.other_user,
            stripe_customer_id="cus_other",
        )
        method = SavedPaymentMethod.objects.create(
            profile=profile,
            stripe_payment_method_id="pm_other",
            brand="mastercard",
            last4="4444",
            is_default=True,
        )

        response = self.client.post(
            reverse("payments:payment_method_delete", args=[method.pk])
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(SavedPaymentMethod.objects.filter(pk=method.pk).exists())