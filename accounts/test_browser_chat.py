"""Run explicitly with --settings=agri_market.browser_test_settings."""
import os
import asyncio
import sys
from pathlib import Path

from django.conf import settings
from django.test import Client
from django.urls import reverse

if os.environ.get("DJANGO_SETTINGS_MODULE") == "agri_market.browser_test_settings":
    from channels.testing import ChannelsLiveServerTestCase
    from playwright.sync_api import sync_playwright, expect
    from .models import Community, FarmerProfile, SupportTicket, User

    class ChatBrowserTests(ChannelsLiveServerTestCase):
        def setUp(self):
            self.seller = User.objects.create_user(username="browser-seller", role=User.Roles.FARMER)
            self.owner = User.objects.create_user(username="browser-owner", role=User.Roles.OWNER, is_staff=True)
            community = Community.objects.create(name="Browser community", slug="browser-community", province="Nan")
            FarmerProfile.objects.create(user=self.seller, community=community, farm_name="Browser farm")
            self.ticket = SupportTicket.objects.create(seller=self.seller, community=community, subject="Browser chat")

        def cookie(self, user, admin=False):
            client = Client()
            client.force_login(user)
            session = client.session
            session["admin_mfa_verified"] = True
            session.save()
            return {
                "name": settings.ADMIN_SESSION_COOKIE_NAME if admin else settings.SESSION_COOKIE_NAME,
                "value": session.session_key, "url": self.live_server_url, "httpOnly": True,
            }

        def test_desktop_and_mobile_two_way_chat(self):
            artifacts = Path(settings.BASE_DIR) / ".artifacts"
            artifacts.mkdir(exist_ok=True)
            seller_cookie = self.cookie(self.seller)
            admin_cookie = self.cookie(self.owner, admin=True)
            if sys.platform == "win32":
                previous_policy = asyncio.get_event_loop_policy()
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                self.addCleanup(asyncio.set_event_loop_policy, previous_policy)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                seller_context = browser.new_context(viewport={"width": 390, "height": 844})
                admin_context = browser.new_context(viewport={"width": 1440, "height": 900})
                seller_context.add_cookies([seller_cookie])
                admin_context.add_cookies([admin_cookie])
                seller, admin = seller_context.new_page(), admin_context.new_page()
                errors = []
                for page in [seller, admin]:
                    page.on("pageerror", lambda error: errors.append(str(error)))
                seller.goto(self.live_server_url + reverse("accounts:support_ticket_detail", args=[self.ticket.pk]))
                admin.goto(self.live_server_url + reverse("admin:accounts_supportticket_changelist") + f"?ticket={self.ticket.pk}")
                expect(seller.locator(".live-chat-bar")).to_contain_text("เชื่อมต่อแล้ว")
                expect(admin.locator(".live-chat-bar")).to_contain_text("เชื่อมต่อแล้ว")
                seller.locator('[name="body"]').fill("ข้อความจากผู้ขายทดสอบ")
                seller.locator('form:has([name="body"]) button[type="submit"]').click()
                expect(admin.locator(".live-chat-bubble")).to_contain_text("ข้อความจากผู้ขายทดสอบ")
                admin.locator('[name="body"]').fill("ผู้ดูแลตอบกลับแล้ว")
                admin.locator(".support-inbox__send").click()
                expect(seller.locator(".live-chat-bubble").last).to_contain_text("ผู้ดูแลตอบกลับแล้ว")
                expect(seller.locator("[data-live-chat-status]")).to_contain_text("กำลังดำเนินการ")
                expect(seller.locator(".live-chat-bubble").first).to_contain_text("อ่านแล้ว")
                for page, name in [(seller, "seller-mobile"), (admin, "admin-desktop")]:
                    self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
                    page.evaluate("window.scrollTo(0, 0)")
                    page.screenshot(path=str(artifacts / f"chat-{name}.png"), full_page=True)
                admin.set_viewport_size({"width": 390, "height": 844})
                self.assertTrue(admin.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
                admin.screenshot(path=str(artifacts / "chat-admin-mobile.png"), full_page=True)
                seller.reload()
                expect(seller.locator(".live-chat-bar")).to_contain_text("เชื่อมต่อแล้ว")
                expect(seller.locator(".live-chat-bubble")).to_have_count(2)
                self.assertEqual(errors, [])
                browser.close()
