"""Run explicitly with --settings=agri_market.browser_test_settings."""
import os
import asyncio
import re
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
            self.owner = User.objects.create_user(
                username="browser-owner",
                password="browser-owner-pass",
                role=User.Roles.OWNER,
                is_staff=True,
            )
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
                expect(seller.locator(".support-ticket-chat__composer")).to_be_visible()
                seller_frame = seller.locator(".support-chat-main")
                self.assertLessEqual(
                    seller_frame.evaluate("element => Math.ceil(element.getBoundingClientRect().bottom)"),
                    844,
                )
                self.assertEqual(
                    seller.locator(".live-chat-list").evaluate("element => getComputedStyle(element).overflowY"),
                    "auto",
                )
                self.assertLessEqual(
                    seller.evaluate("document.documentElement.scrollHeight"),
                    seller.evaluate("innerHeight") + 1,
                )
                seller_input = seller.locator('[name="body"]')
                seller_input.focus()
                seller.set_viewport_size({"width": 390, "height": 500})
                expect(seller.locator(".support-chat-main")).to_have_class(
                    re.compile(r"\bis-keyboard-open\b")
                )
                expect(seller.locator(".support-ticket-chat__composer")).to_be_visible()
                self.assertLessEqual(
                    seller.locator(".support-ticket-chat__composer").evaluate(
                        "element => Math.ceil(element.getBoundingClientRect().bottom)"
                    ),
                    500,
                )
                expect(seller.locator(".support-ticket-chat__header")).to_be_hidden()
                seller.set_viewport_size({"width": 390, "height": 844})
                seller_input.blur()
                seller.locator('[name="body"]').fill("ข้อความจากผู้ขายทดสอบ")
                seller.locator('[name="body"]').press("Enter")
                expect(admin.locator(".live-chat-bubble")).to_contain_text("ข้อความจากผู้ขายทดสอบ")
                admin.set_viewport_size({"width": 390, "height": 844})
                expect(admin.locator(".support-inbox__composer")).to_be_visible()
                expect(admin.locator(".support-inbox__send")).to_be_visible()
                send_right = admin.locator(".support-inbox__send").evaluate("element => Math.ceil(element.getBoundingClientRect().right)")
                self.assertLessEqual(send_right, 390)
                expect(admin.locator(".owner-mobile-actions")).to_be_hidden()
                chat_frame = admin.locator(".support-inbox--selected")
                self.assertLessEqual(
                    chat_frame.evaluate("element => Math.ceil(element.getBoundingClientRect().bottom)"),
                    844,
                )
                self.assertEqual(
                    admin.locator(".live-chat-list").evaluate("element => getComputedStyle(element).overflowY"),
                    "auto",
                )
                self.assertTrue(admin.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
                admin.locator('[name="body"]').fill("ผู้ดูแลตอบกลับแล้ว")
                admin.locator(".support-inbox__send").click()
                expect(seller.locator(".live-chat-bubble").last).to_contain_text("ผู้ดูแลตอบกลับแล้ว")
                admin_layout = admin.evaluate(
                    """() => {
                        const selectors = {
                            inbox: ".support-inbox--selected",
                            conversation: ".support-inbox__conversation",
                            list: ".live-chat-list",
                            row: ".live-chat-row.is-own",
                            bubble: ".live-chat-row.is-own .live-chat-bubble",
                        };
                        const result = {innerWidth};
                        for (const [name, selector] of Object.entries(selectors)) {
                            const element = document.querySelector(selector);
                            const rect = element.getBoundingClientRect();
                            const style = getComputedStyle(element);
                            result[name] = {
                                left: Math.ceil(rect.left),
                                right: Math.ceil(rect.right),
                                width: Math.ceil(rect.width),
                                boxSizing: style.boxSizing,
                                paddingLeft: style.paddingLeft,
                                paddingRight: style.paddingRight,
                            };
                        }
                        return result;
                    }"""
                )
                self.assertLessEqual(admin_layout["bubble"]["right"], 390, admin_layout)
                expect(seller.locator("[data-live-chat-status]")).to_contain_text("กำลังดำเนินการ")
                expect(seller.locator(".live-chat-bubble").first).to_contain_text("อ่านแล้ว")
                for page, name in [(seller, "seller-mobile"), (admin, "admin-desktop")]:
                    self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
                    page.evaluate("window.scrollTo(0, 0)")
                    page.screenshot(path=str(artifacts / f"chat-{name}.png"), full_page=True)
                admin.screenshot(path=str(artifacts / "chat-admin-mobile.png"), full_page=True)
                seller.reload()
                expect(seller.locator(".live-chat-bar")).to_contain_text("เชื่อมต่อแล้ว")
                expect(seller.locator(".live-chat-bubble")).to_have_count(2)
                self.assertEqual(errors, [])
                browser.close()

        def test_mobile_auth_pages_and_admin_table_remain_usable(self):
            artifacts = Path(settings.BASE_DIR) / ".artifacts"
            artifacts.mkdir(exist_ok=True)
            admin_cookie = self.cookie(self.owner, admin=True)
            if sys.platform == "win32":
                previous_policy = asyncio.get_event_loop_policy()
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                self.addCleanup(asyncio.set_event_loop_policy, previous_policy)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                public_context = browser.new_context(viewport={"width": 390, "height": 844})
                public = public_context.new_page()
                for url, card in [
                    (reverse("login"), ".market-login section > div:last-child"),
                    (reverse("accounts:signup"), ".market-signup section > div:last-child"),
                ]:
                    public.goto(self.live_server_url + url)
                    expect(public.locator(card)).to_be_visible()
                    self.assertTrue(public.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
                    self.assertLessEqual(public.locator(card).evaluate("element => element.getBoundingClientRect().width"), 390)
                public.screenshot(path=str(artifacts / "auth-mobile.png"), full_page=True)

                admin_context = browser.new_context(viewport={"width": 390, "height": 844})
                admin_context.add_cookies([admin_cookie])
                admin = admin_context.new_page()
                admin.goto(self.live_server_url + reverse("admin:accounts_user_changelist"))
                for selector in [
                    ".owner-mobile-actions a[href='/admin/']",
                    ".owner-mobile-actions a[href='/admin/site-preview/']",
                    ".owner-mobile-actions a[href='/admin/password_change/']",
                    ".owner-mobile-actions button[type='submit']",
                ]:
                    expect(admin.locator(selector)).to_be_visible()
                header_bottom = admin.locator("#header").evaluate("element => element.getBoundingClientRect().bottom")
                actions_top = admin.locator(".owner-mobile-actions").evaluate("element => element.getBoundingClientRect().top")
                self.assertLessEqual(header_bottom, actions_top + 1)
                results = admin.locator("#changelist .results")
                expect(results).to_be_visible()
                self.assertGreater(results.evaluate("element => element.scrollWidth"), results.evaluate("element => element.clientWidth"))
                expect(admin.locator(".change-list .admin-support-rail")).not_to_be_visible()
                admin.screenshot(path=str(artifacts / "admin-table-mobile.png"), full_page=True)
                admin.locator(".owner-back-button").click()
                expect(admin).to_have_url(self.live_server_url + reverse("admin:index"))
                expect(admin.locator(".console-dashboard")).to_be_visible()
                expect(admin.locator(".owner-mobile-actions a[href='/admin/password_change/']")).to_be_visible()
                expect(admin.locator(".owner-mobile-actions button[type='submit']")).to_be_visible()
                browser.close()
