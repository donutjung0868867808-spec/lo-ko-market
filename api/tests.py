from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import Community, FarmerProfile, User
from catalog.models import Product


class ProductApiTests(TestCase):
    def setUp(self):
        self.community = Community.objects.create(
            name="ชุมชน API",
            slug="api-community",
            province="ลำพูน",
        )
        self.farmer = User.objects.create_user(
            username="api-farmer",
            password="pass",
            role=User.Roles.FARMER,
        )
        FarmerProfile.objects.create(
            user=self.farmer,
            community=self.community,
            farm_name="สวน API",
            verification_status=FarmerProfile.VerificationStatus.VERIFIED,
        )

    def test_public_product_api_returns_only_active_products(self):
        Product.objects.create(
            seller=self.farmer,
            community=self.community,
            name="ผักเปิดขาย",
            description="พร้อมขาย",
            price=Decimal("35.00"),
            stock_quantity=Decimal("10.00"),
            status=Product.Status.ACTIVE,
        )
        Product.objects.create(
            seller=self.farmer,
            community=self.community,
            name="ผักรออนุมัติ",
            description="รอตรวจ",
            price=Decimal("30.00"),
            stock_quantity=Decimal("10.00"),
            status=Product.Status.PENDING,
        )

        response = self.client.get(reverse("product-list"))

        names = [item["name"] for item in response.json()["results"]]
        self.assertIn("ผักเปิดขาย", names)
        self.assertNotIn("ผักรออนุมัติ", names)
