import os
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from .models import User


class BootstrapOwnerCommandTests(TestCase):
    def test_command_creates_owner_only_once(self):
        environment = {
            "INITIAL_OWNER_USERNAME": "first-owner",
            "INITIAL_OWNER_EMAIL": "first-owner@example.com",
            "INITIAL_OWNER_PASSWORD": "StrongOwnerPass123!",
        }
        with patch.dict(os.environ, environment, clear=False):
            call_command("bootstrap_owner")
            call_command("bootstrap_owner")

        owner = User.objects.get(username="first-owner")
        self.assertEqual(User.objects.filter(role=User.Roles.OWNER).count(), 1)
        self.assertTrue(owner.is_owner)
        self.assertTrue(owner.is_staff)
        self.assertTrue(owner.is_superuser)
        self.assertTrue(owner.is_email_verified)
        self.assertTrue(owner.check_password("StrongOwnerPass123!"))

    def test_command_without_environment_is_a_safe_noop(self):
        environment = {
            "INITIAL_OWNER_USERNAME": "",
            "INITIAL_OWNER_EMAIL": "",
            "INITIAL_OWNER_PASSWORD": "",
        }
        with patch.dict(os.environ, environment, clear=False):
            call_command("bootstrap_owner")

        self.assertFalse(User.objects.filter(role=User.Roles.OWNER).exists())