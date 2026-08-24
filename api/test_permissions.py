from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import Community, CommunityStaffProfile, FarmerProfile, User
from catalog.models import Product


class ProductApiPermissionTests(TestCase):
    def setUp(self):
        self.community = Community.objects.create(
            name="API community one",
            slug="api-permission-one",
            province="Nan",
        )
        self.other_community = Community.objects.create(
            name="API community two",
            slug="api-permission-two",
            province="Phrae",
        )
        self.farmer = User.objects.create_user(
            username="api-permission-farmer",
            password="pass12345",
            role=User.Roles.FARMER,
        )
        FarmerProfile.objects.create(
            user=self.farmer,
            community=self.community,
            farm_name="API farm",
            verification_status=FarmerProfile.VerificationStatus.VERIFIED,
        )
        self.other_farmer = User.objects.create_user(
            username="api-permission-other",
            password="pass12345",
            role=User.Roles.FARMER,
        )
        FarmerProfile.objects.create(
            user=self.other_farmer,
            community=self.other_community,
            farm_name="Other API farm",
            verification_status=FarmerProfile.VerificationStatus.VERIFIED,
        )

    def test_product_create_ignores_submitted_owner_community_and_status(self):
        self.client.force_login(self.farmer)
        response = self.client.post(
            reverse("product-list"),
            {
                "seller": self.other_farmer.pk,
                "community": self.other_community.pk,
                "name": "Secure API product",
                "description": "Test",
                "unit": Product.Unit.KG,
                "price": "120.00",
                "stock_quantity": "5.00",
                "minimum_order_quantity": "1.00",
                "status": Product.Status.ACTIVE,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        product = Product.objects.get(name="Secure API product")
        self.assertEqual(product.seller, self.farmer)
        self.assertEqual(product.community, self.community)
        self.assertEqual(product.status, Product.Status.PENDING)

    def test_staff_can_edit_only_products_in_own_community(self):
        staff = User.objects.create_user(
            username="api-community-staff",
            password="pass12345",
            role=User.Roles.COOPERATIVE_STAFF,
        )
        CommunityStaffProfile.objects.create(user=staff, community=self.community)
        own_product = Product.objects.create(
            seller=self.farmer,
            community=self.community,
            name="Own community product",
            description="Test",
            price=Decimal("80.00"),
            stock_quantity=Decimal("5.00"),
            status=Product.Status.ACTIVE,
        )
        other_product = Product.objects.create(
            seller=self.other_farmer,
            community=self.other_community,
            name="Other community product",
            description="Test",
            price=Decimal("90.00"),
            stock_quantity=Decimal("5.00"),
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(staff)

        own_response = self.client.patch(
            reverse("product-detail", args=[own_product.pk]),
            {"name": "Edited by community staff"},
            content_type="application/json",
        )
        other_response = self.client.patch(
            reverse("product-detail", args=[other_product.pk]),
            {"name": "Must not change"},
            content_type="application/json",
        )

        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(other_response.status_code, 403)
        own_product.refresh_from_db()
        other_product.refresh_from_db()
        self.assertEqual(own_product.name, "Edited by community staff")
        self.assertEqual(other_product.name, "Other community product")