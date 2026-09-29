"""Run explicitly with --settings=agri_market.browser_test_settings."""
import asyncio
import os
import sys
from urllib.parse import urlencode

from django.urls import reverse


if os.environ.get("DJANGO_SETTINGS_MODULE") == "agri_market.browser_test_settings":
    from django.contrib.staticfiles.testing import StaticLiveServerTestCase
    from playwright.sync_api import expect, sync_playwright

    class ProvinceAutocompleteBrowserTests(StaticLiveServerTestCase):
        def test_province_suggestions_open_and_filter(self):
            if sys.platform == "win32":
                previous_policy = asyncio.get_event_loop_policy()
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                self.addCleanup(asyncio.set_event_loop_policy, previous_policy)

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + reverse("catalog:product_list"))

                input_element = page.locator("#province-search")
                suggestions = page.locator("#province-suggestions")
                input_element.click()
                expect(suggestions).to_be_visible()
                expect(suggestions.locator("[data-province-option]")).to_have_count(77)

                input_element.fill("\u0e01\u0e23\u0e38\u0e07")
                option = suggestions.locator(
                    '[data-province-value="\u0e01\u0e23\u0e38\u0e07\u0e40\u0e17\u0e1e\u0e21\u0e2b\u0e32\u0e19\u0e04\u0e23"]'
                )
                expect(option).to_be_visible()
                option.click()
                expected_url = self.live_server_url + reverse("catalog:product_list") + "?" + urlencode(
                    {"province": "\u0e01\u0e23\u0e38\u0e07\u0e40\u0e17\u0e1e\u0e21\u0e2b\u0e32\u0e19\u0e04\u0e23", "q": ""}
                )
                expect(page).to_have_url(expected_url)
                self.assertEqual(errors, [])
                browser.close()