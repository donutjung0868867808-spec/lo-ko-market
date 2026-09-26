from types import SimpleNamespace

from django.test import SimpleTestCase

from .context_processors import notification_summary


class NotificationSummaryTests(SimpleTestCase):
    def test_request_without_user_returns_default_counts(self):
        self.assertEqual(
            notification_summary(SimpleNamespace()),
            {
                "unread_notification_count": 0,
                "cart_item_count": 0,
                "admin_support_chat_count": 0,
                "seller_support_chat_count": 0,
                "active_market_mode": "seller",
            },
        )
