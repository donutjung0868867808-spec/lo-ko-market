import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import User


class Command(BaseCommand):
    help = "Create the initial system owner from environment variables"

    @transaction.atomic
    def handle(self, *args, **options):
        username = os.environ.get("INITIAL_OWNER_USERNAME", "").strip()
        email = os.environ.get("INITIAL_OWNER_EMAIL", "").strip().lower()
        password = os.environ.get("INITIAL_OWNER_PASSWORD", "")

        supplied = [bool(username), bool(email), bool(password)]
        if not any(supplied):
            self.stdout.write("Initial owner variables are not set; skipping")
            return
        if not all(supplied):
            raise CommandError(
                "Set INITIAL_OWNER_USERNAME, INITIAL_OWNER_EMAIL "
                "and INITIAL_OWNER_PASSWORD together"
            )

        existing_owner = User.objects.filter(
            Q(role=User.Roles.OWNER) | Q(is_superuser=True)
        ).first()
        if existing_owner:
            self.stdout.write(
                self.style.WARNING(
                    f"An owner already exists ({existing_owner.username}); skipping"
                )
            )
            return

        if User.objects.filter(Q(username__iexact=username) | Q(email__iexact=email)).exists():
            raise CommandError("The initial owner username or email is already in use")

        try:
            validate_email(email)
            candidate = User(
                username=username,
                email=email,
                role=User.Roles.OWNER,
                is_staff=True,
                is_superuser=True,
                email_verified_at=timezone.now(),
            )
            validate_password(password, user=candidate)
        except ValidationError as exc:
            raise CommandError("Invalid initial owner: " + " ".join(exc.messages))

        candidate.set_password(password)
        candidate.save()
        self.stdout.write(
            self.style.SUCCESS(f"Created initial owner {candidate.username}")
        )