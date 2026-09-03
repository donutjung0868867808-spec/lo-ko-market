from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Community, FarmerProfile, Notification, SupportMessage, SupportTicket, User


class SupportTicketTests(TestCase):
    def setUp(self):
        self.community = Community.objects.create(name="ชุมชนทดสอบ", slug="support-test", province="สกลนคร")
        self.seller = User.objects.create_user(username="support-seller", password="pass12345", role=User.Roles.FARMER)
        FarmerProfile.objects.create(user=self.seller, community=self.community, farm_name="ฟาร์มทดสอบ")
        self.owner = User.objects.create_user(
            username="support-owner",
            password="pass12345",
            role=User.Roles.OWNER,
            is_staff=True,
            is_superuser=True,
        )

    def test_seller_can_open_ticket_and_owner_can_reply(self):
        self.client.force_login(self.seller)
        response = self.client.post(
            reverse("accounts:support_ticket_create"),
            {"category": SupportTicket.Category.REFUND, "subject": "ขอสอบถามการคืนเงิน", "message": "ต้องการทราบสถานะการคืนเงิน"},
        )
        ticket = SupportTicket.objects.get()
        self.assertRedirects(response, reverse("accounts:support_ticket_detail", args=[ticket.pk]))
        self.assertEqual(ticket.community, self.community)
        self.assertEqual(ticket.messages.count(), 1)
        self.assertTrue(Notification.objects.filter(user=self.owner).exists())

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("accounts:support_ticket_detail", args=[ticket.pk]),
            {"body": "ผู้ดูแลกำลังตรวจสอบให้"},
        )
        ticket.refresh_from_db()
        self.assertRedirects(response, reverse("accounts:support_ticket_detail", args=[ticket.pk]))
        self.assertEqual(ticket.status, SupportTicket.Status.IN_PROGRESS)
        self.assertEqual(ticket.handled_by, self.owner)
        self.assertEqual(SupportMessage.objects.filter(ticket=ticket).count(), 2)
        self.assertTrue(Notification.objects.filter(user=self.seller).exists())

    def test_seller_cannot_view_another_sellers_ticket(self):
        ticket = SupportTicket.objects.create(seller=self.seller, community=self.community, category=SupportTicket.Category.GENERAL, subject="คำถาม")
        other_seller = User.objects.create_user(username="other-support-seller", password="pass12345", role=User.Roles.FARMER)
        self.client.force_login(other_seller)

        response = self.client.get(reverse("accounts:support_ticket_detail", args=[ticket.pk]))

        self.assertEqual(response.status_code, 404)

    @override_settings(ADMIN_MFA_REQUIRED=False)
    def test_admin_chat_view_sends_reply(self):
        ticket = SupportTicket.objects.create(
            seller=self.seller,
            community=self.community,
            category=SupportTicket.Category.GENERAL,
            subject="แชทกับผู้ดูแลระบบ",
        )
        SupportMessage.objects.create(ticket=ticket, sender=self.seller, body="ขอความช่วยเหลือ")
        login_response = self.client.post(
            reverse("admin:login"),
            {"username": self.owner.username, "password": "pass12345", "next": reverse("admin:index")},
        )
        self.assertEqual(login_response.status_code, 302)

        response = self.client.post(
            reverse("admin:accounts_supportticket_reply", args=[ticket.pk]),
            {"body": "ผู้ดูแลตอบกลับแล้ว"},
        )

        ticket.refresh_from_db()
        self.assertRedirects(
            response,
            reverse("admin:accounts_supportticket_reply", args=[ticket.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(ticket.handled_by, self.owner)
        self.assertTrue(
            SupportMessage.objects.filter(ticket=ticket, sender=self.owner).exists()
        )