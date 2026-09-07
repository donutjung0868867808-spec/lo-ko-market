"""Isolated file database for optional Playwright/Channels browser tests."""
from .settings import *  # noqa: F403

DEBUG = True
SECRET_KEY = "browser-tests-only-never-production"
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
CSRF_TRUSTED_ORIGINS = []
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
ADMIN_MFA_REQUIRED = True
REQUIRE_EMAIL_VERIFICATION = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
STRIPE_SECRET_KEY = ""
STRIPE_CONNECT_TRANSFERS_ENABLED = False
SITE_URL = ""
REDIS_URL = ""
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": str(BASE_DIR / ".browser-test.sqlite3"),
    "TEST": {"NAME": str(BASE_DIR / ".browser-test.sqlite3")},
}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES = {
    "private": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
