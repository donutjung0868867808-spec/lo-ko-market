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

    def test_new_seller_message_updates_admin_unread_chat_notification(self):
        self.client.force_login(self.seller)
        response = self.client.post(
            reverse("accounts:support_ticket_create"),
            {
                "category": SupportTicket.Category.GENERAL,
                "subject": "ขอความช่วยเหลือ",
                "message": "ผู้ขายมีคำถามใหม่",
            },
        )
        ticket = SupportTicket.objects.get(subject="ขอความช่วยเหลือ")
        self.assertRedirects(response, reverse("accounts:support_ticket_detail", args=[ticket.pk]))
        self.assertIsNotNone(ticket.last_seller_message_at)
        notification = Notification.objects.get(user=self.owner)
        self.assertEqual(
            notification.link,
            reverse("admin:accounts_supportticket_reply", args=[ticket.pk]),
        )

        self.client.force_login(self.owner)
        unread_response = self.client.get(reverse("accounts:support_chat_unread"))
        self.assertEqual(unread_response.json(), {"count": 1})

        self.client.get(reverse("accounts:support_ticket_detail", args=[ticket.pk]))
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.admin_read_at)
        self.assertEqual(
            self.client.get(reverse("accounts:support_chat_unread")).json(),
            {"count": 0},
        )

        self.client.post(
            reverse("accounts:support_ticket_detail", args=[ticket.pk]),
            {"body": "ผู้ดูแลกำลังช่วยตรวจสอบให้"},
        )
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.last_admin_message_at)
        self.assertIsNone(ticket.seller_read_at)

        self.client.force_login(self.seller)
        self.client.get(reverse("accounts:support_ticket_detail", args=[ticket.pk]))
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.seller_read_at)

    def test_seller_cannot_view_another_sellers_ticket(self):
        ticket = SupportTicket.objects.create(seller=self.seller, community=self.community, category=SupportTicket.Category.GENERAL, subject="คำถาม")
        other_seller = User.objects.create_user(username="other-support-seller", password="pass12345", role=User.Roles.FARMER)
        self.client.force_login(other_seller)

        response = self.client.get(reverse("accounts:support_ticket_detail", args=[ticket.pk]))

        self.assertEqual(response.status_code, 404)

    @override_settings(ADMIN_MFA_REQUIRED=False)
    def test_admin_inbox_selects_and_replies_in_one_view(self):
        ticket = SupportTicket.objects.create(
            seller=self.seller,
            community=self.community,
            category=SupportTicket.Category.GENERAL,
            subject="สอบถามค่าธรรมเนียม",
        )
        seller_message = SupportMessage.objects.create(
            ticket=ticket,
            sender=self.seller,
            body="ต้องการสอบถามรายละเอียดค่าธรรมเนียม",
        )
        ticket.last_seller_message_at = seller_message.created_at
        ticket.save(update_fields=["last_seller_message_at"])
        inbox_url = reverse("admin:accounts_supportticket_changelist")
        login_response = self.client.post(
            reverse("admin:login"),
            {"username": self.owner.username, "password": "pass12345", "next": inbox_url},
        )
        self.assertEqual(login_response.status_code, 302)
        response = self.client.get(f"{inbox_url}?ticket={ticket.pk}")

        self.assertTemplateUsed(response, "admin/accounts/support_ticket_inbox.html")
        self.assertContains(response, "สอบถามค่าธรรมเนียม")
        self.assertContains(response, "ต้องการสอบถามรายละเอียดค่าธรรมเนียม")
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.admin_read_at)

        response = self.client.post(
            inbox_url,
            {"ticket_id": ticket.pk, "body": "ผู้ดูแลจะตรวจสอบและแจ้งผลให้ทราบ"},
        )

        self.assertRedirects(response, f"{inbox_url}?ticket={ticket.pk}")
        self.assertTrue(
            SupportMessage.objects.filter(
                ticket=ticket,
                sender=self.owner,
                body="ผู้ดูแลจะตรวจสอบและแจ้งผลให้ทราบ",
            ).exists()
        )

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