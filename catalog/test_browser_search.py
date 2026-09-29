"""Run explicitly with --settings=agri_market.browser_test_settings."""
import asyncio
import os
import sys
from decimal import Decimal
from urllib.parse import urlencode

from django.urls import reverse


if os.environ.get("DJANGO_SETTINGS_MODULE") == "agri_market.browser_test_settings":
    from accounts.models import Community, User
    from catalog.models import Product
    from django.contrib.staticfiles.testing import StaticLiveServerTestCase
    from playwright.sync_api import expect, sync_playwright

    class SearchAutocompleteBrowserTests(StaticLiveServerTestCase):
        def setUp(self):
            super().setUp()
            if sys.platform == "win32":
                previous_policy = asyncio.get_event_loop_policy()
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                self.addCleanup(asyncio.set_event_loop_policy, previous_policy)

            self.community = Community.objects.create(
                name="Browser test community",
                slug="browser-test-community",
                province="Chiang Mai",
            )
            self.seller = User.objects.create_user(
                username="browser-test-seller",
                password="pass",
                role=User.Roles.FARMER,
            )
            Product.objects.create(
                seller=self.seller,
                community=self.community,
                name="Fresh Mango",
                description="Sweet mango",
                price=Decimal("50.00"),
                stock_quantity=Decimal("10.00"),
                status=Product.Status.ACTIVE,
            )
            Product.objects.create(
                seller=self.seller,
                community=self.community,
                name="Fresh Banana",
                description="Sweet banana",
                price=Decimal("40.00"),
                stock_quantity=Decimal("10.00"),
                status=Product.Status.ACTIVE,
            )
            Product.objects.create(
                seller=self.seller,
                community=self.community,
                name="Hidden Mango",
                description="Not public",
                price=Decimal("45.00"),
                stock_quantity=Decimal("10.00"),
                status=Product.Status.PENDING,
            )
        def test_province_suggestions_open_filter_and_select(self):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 390, "height": 844})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + reverse("catalog:product_list"))

                input_element = page.locator("#province-search")
                suggestions = page.locator("#province-suggestions")
                input_element.click()
                expect(suggestions).to_be_visible()
                input_box = input_element.bounding_box()
                suggestions_box = suggestions.bounding_box()
                self.assertIsNotNone(input_box)
                self.assertIsNotNone(suggestions_box)
                self.assertAlmostEqual(suggestions_box["x"], input_box["x"], delta=1)
                self.assertAlmostEqual(suggestions_box["width"], input_box["width"], delta=1)
                expect(suggestions.locator("[data-province-option]")).to_have_count(77)

                input_element.fill("\u0e2a\u0e01\u0e25\u0e19")
                option = suggestions.locator(
                    '[data-province-value="\u0e2a\u0e01\u0e25\u0e19\u0e04\u0e23"]'
                )
                expect(option).to_be_visible()
                expect(
                    suggestions.locator(
                        '[data-province-value="\u0e01\u0e23\u0e38\u0e07\u0e40\u0e17\u0e1e\u0e21\u0e2b\u0e32\u0e19\u0e04\u0e23"]'
                    )
                ).to_be_hidden()
                expect(suggestions.locator("[data-province-option]:visible")).to_have_count(1)
                option.click()
                expected_url = self.live_server_url + reverse("catalog:product_list") + "?" + urlencode(
                    {"province": "\u0e2a\u0e01\u0e25\u0e19\u0e04\u0e23", "q": ""}
                )
                expect(page).to_have_url(expected_url)
                self.assertEqual(errors, [])
                browser.close()

        def test_product_suggestions_open_filter_and_select(self):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 390, "height": 844})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + reverse("catalog:product_list"))

                input_element = page.locator("#global-product-search")
                suggestions = page.locator("#product-suggestions")
                input_element.click()
                expect(suggestions).to_be_hidden()

                input_element.fill("Mango")
                expect(suggestions).to_be_visible()
                expect(suggestions.locator("[data-product-option]")).to_have_count(2)
                option = suggestions.locator('[data-product-value="Fresh Mango"]')
                expect(option).to_be_visible()
                expect(suggestions.locator('[data-product-value="Fresh Banana"]')).to_be_hidden()
                expect(suggestions.locator("[data-product-option]:visible")).to_have_count(1)
                option.click()
                expected_url = self.live_server_url + reverse("catalog:product_list") + "?" + urlencode(
                    {"province": "", "q": "Fresh Mango"}
                )
                expect(page).to_have_url(expected_url)
                self.assertEqual(errors, [])
                browser.close()