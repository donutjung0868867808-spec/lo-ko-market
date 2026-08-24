from django.test import TestCase
from django.urls import reverse

from .models import Community, FarmerProfile, User


class FarmerSignupFlowTests(TestCase):
    def setUp(self):
        self.community = Community.objects.create(
            name="Test community",
            slug="test-community",
            province="Chiang Mai",
        )

    def test_farmer_signup_creates_account_after_profile_step(self):
        account_response = self.client.post(
            reverse("accounts:farmer_signup_create"),
            {
                "display_name": "Seller One",
                "username": "seller-one",
                "email": "seller-one@example.com",
                "phone": "0812345678",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "accept_terms": "True",
                "accept_privacy": "True",
            },
        )

        self.assertRedirects(account_response, reverse("accounts:farmer_signup_profile"))
        self.assertFalse(User.objects.filter(username="seller-one").exists())
        self.assertNotEqual(
            self.client.session["farmer_signup_account"]["password_hash"],
            "StrongPass123!",
        )

        profile_response = self.client.post(
            reverse("accounts:farmer_signup_profile"),
            {
                "farm_name": "Seller farm",
                "community": self.community.pk,
                "province": "Chiang Mai",
                "district": "Mueang",
                "address": "Test address",
                "bio": "",
                "document_type": FarmerProfile.DocumentType.NATIONAL_ID,
            },
        )

        self.assertRedirects(profile_response, reverse("login"))
        seller = User.objects.get(username="seller-one")
        self.assertEqual(seller.role, User.Roles.FARMER)
        self.assertTrue(seller.check_password("StrongPass123!"))
        self.assertEqual(seller.farmer_profile.farm_name, "Seller farm")
        self.assertNotIn("farmer_signup_account", self.client.session)

    def test_farmer_profile_step_requires_account_step(self):
        response = self.client.get(reverse("accounts:farmer_signup_profile"))

        self.assertRedirects(response, reverse("accounts:farmer_signup_create"))