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
                "first_name": "Seller",
                "last_name": "One",
                "birth_date": "1992-06-15",
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
        self.assertEqual(seller.first_name, "Seller")
        self.assertEqual(seller.last_name, "One")
        self.assertEqual(seller.display_name, "Seller One")
        self.assertEqual(seller.birth_date.isoformat(), "1992-06-15")
        self.assertEqual(seller.farmer_profile.farm_name, "Seller farm")
        self.assertNotIn("farmer_signup_account", self.client.session)

    def test_farmer_profile_step_requires_account_step(self):
        response = self.client.get(reverse("accounts:farmer_signup_profile"))

        self.assertRedirects(response, reverse("accounts:farmer_signup_create"))

    def test_consumer_can_upgrade_existing_account_to_seller(self):
        consumer = User.objects.create_user(
            username="existing-buyer",
            password="StrongPass123!",
            email="buyer@example.com",
            role=User.Roles.CONSUMER,
        )
        original_user_id = consumer.pk
        self.client.force_login(consumer)

        intro_response = self.client.get(reverse("accounts:farmer_signup"))
        self.assertContains(intro_response, "เปิดร้านค้าด้วยบัญชีนี้")

        profile_response = self.client.post(
            reverse("accounts:farmer_signup_profile"),
            {
                "farm_name": "Existing buyer shop",
                "community": self.community.pk,
                "province": "Chiang Mai",
                "district": "Mueang",
                "address": "Test address",
                "bio": "",
                "document_type": FarmerProfile.DocumentType.NATIONAL_ID,
            },
        )

        self.assertRedirects(profile_response, reverse("accounts:farmer_shop_center"))
        consumer.refresh_from_db()
        self.assertEqual(consumer.pk, original_user_id)
        self.assertEqual(User.objects.filter(username="existing-buyer").count(), 1)
        self.assertEqual(consumer.role, User.Roles.FARMER)
        self.assertTrue(consumer.can_buy)
        self.assertTrue(consumer.check_password("StrongPass123!"))
        self.assertEqual(consumer.farmer_profile.farm_name, "Existing buyer shop")
        self.assertEqual(
            consumer.farmer_profile.verification_status,
            FarmerProfile.VerificationStatus.PENDING,
        )

    def test_consumer_signup_saves_name_and_birth_date_to_profile(self):
        response = self.client.post(
            reverse("accounts:consumer_signup"),
            {
                "first_name": "Buyer",
                "last_name": "Example",
                "birth_date": "1995-04-12",
                "username": "buyer-example",
                "email": "buyer-example@example.com",
                "phone": "0812345678",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "accept_terms": "True",
                "accept_privacy": "True",
            },
        )

        self.assertRedirects(response, reverse("login"))
        buyer = User.objects.get(username="buyer-example")
        self.assertEqual(buyer.first_name, "Buyer")
        self.assertEqual(buyer.last_name, "Example")
        self.assertEqual(buyer.display_name, "Buyer Example")
        self.assertEqual(buyer.birth_date.isoformat(), "1995-04-12")
