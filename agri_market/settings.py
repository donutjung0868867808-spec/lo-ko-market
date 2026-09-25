import importlib.util
import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def load_local_env_file():
    """Load simple KEY=value values for local development only."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_local_env_file()


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def env_list(name, default=None):
    value = os.environ.get(name)
    if not value:
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]


def database_from_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must use postgres:// or postgresql://")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username or "",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
        "OPTIONS": dict(parse_qsl(parsed.query)),
    }


def cloudinary_storage_config(value):
    """Return a normalized Cloudinary URL and Django storage settings."""
    url = (value or "").strip()
    if url.startswith("CLOUDINARY_URL="):
        url = url.split("=", 1)[1].strip()
    parsed = urlparse(url)
    if not (
        parsed.scheme == "cloudinary"
        and parsed.hostname
        and parsed.username
        and parsed.password
    ):
        return url, {}
    return url, {
        "CLOUD_NAME": parsed.hostname,
        "API_KEY": unquote(parsed.username),
        "API_SECRET": unquote(parsed.password),
        "SECURE": True,
    }


def package_exists(package_name):
    return importlib.util.find_spec(package_name) is not None


SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-change-me-only-for-local-development",
)
DEBUG = env_bool("DEBUG", default=True)
IS_TESTING = "test" in sys.argv
CLOUDINARY_URL, CLOUDINARY_STORAGE = cloudinary_storage_config(
    os.environ.get("CLOUDINARY_URL")
)
if CLOUDINARY_URL:
    os.environ["CLOUDINARY_URL"] = CLOUDINARY_URL
ALLOWED_HOSTS = env_list(
    "ALLOWED_HOSTS",
    default=["127.0.0.1", "localhost", "172.29.71.169", ".onrender.com"],
)
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Allow Cloudflare Quick Tunnel only while developing locally.
if DEBUG:
    ALLOWED_HOSTS.append(".trycloudflare.com")
    CSRF_TRUSTED_ORIGINS.append("https://*.trycloudflare.com")

ENABLE_DEMO_DATA = env_bool("ENABLE_DEMO_DATA", default=False)
REQUIRE_EMAIL_VERIFICATION = env_bool("REQUIRE_EMAIL_VERIFICATION", default=not DEBUG and not IS_TESTING)
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_LOCKOUT_MINUTES = int(os.environ.get("LOGIN_LOCKOUT_MINUTES", "15"))
TRUST_X_FORWARDED_FOR = env_bool("TRUST_X_FORWARDED_FOR", default=not DEBUG and not IS_TESTING)
ORDER_RESERVATION_MINUTES = int(os.environ.get("ORDER_RESERVATION_MINUTES", "30"))
REFUND_REQUEST_DAYS = int(os.environ.get("REFUND_REQUEST_DAYS", "7"))
PAYMENT_MODE = os.environ.get("PAYMENT_MODE", "test").strip().lower()
if PAYMENT_MODE not in {"test", "live"}:
    raise ValueError("PAYMENT_MODE must be either 'test' or 'live'.")
FLAT_SHIPPING_FEE = os.environ.get("FLAT_SHIPPING_FEE", "50.00")
FREE_SHIPPING_THRESHOLD = os.environ.get("FREE_SHIPPING_THRESHOLD", "500.00")
MAX_UPLOAD_SIZE = int(os.environ.get("MAX_UPLOAD_SIZE", str(5 * 1024 * 1024)))
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "support@local.test")
TERMS_VERSION = os.environ.get("TERMS_VERSION", "2026-07")
PRIVACY_VERSION = os.environ.get("PRIVACY_VERSION", "2026-07")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=not DEBUG and not IS_TESTING)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", default=not DEBUG and not IS_TESTING)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", default=not DEBUG and not IS_TESTING)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_FAILURE_VIEW = "agri_market.views.csrf_failure"
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000" if not DEBUG and not IS_TESTING else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=not DEBUG and not IS_TESTING)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", default=not DEBUG and not IS_TESTING)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts",
    "catalog",
    "orders",
    "payments",
    "api",
]

if package_exists("cloudinary_storage") and CLOUDINARY_STORAGE:
    INSTALLED_APPS.insert(0, "cloudinary_storage")
    INSTALLED_APPS.insert(1, "cloudinary")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "agri_market.middleware.AdminCookieScopeMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "agri_market.middleware.OwnerMfaMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if package_exists("whitenoise"):
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "agri_market.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context_processors.notification_summary",
                "catalog.context_processors.search_provinces",
                "payments.context_processors.payment_mode",
            ],
        },
    },
]

WSGI_APPLICATION = "agri_market.wsgi.application"
ASGI_APPLICATION = "agri_market.asgi.application"
REDIS_URL = os.environ.get("REDIS_URL", "")
AFTERSHIP_API_KEY = os.environ.get("AFTERSHIP_API_KEY", "")
AFTERSHIP_REQUEST_TIMEOUT_SECONDS = int(os.environ.get("AFTERSHIP_REQUEST_TIMEOUT_SECONDS", "10"))
CHANNEL_LAYERS = {"default": (
    {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [REDIS_URL]}}
    if REDIS_URL and not IS_TESTING else {"BACKEND": "channels.layers.InMemoryChannelLayer"}
)}
SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")

database_url = os.environ.get("DATABASE_URL")
if database_url:
    DATABASES = {"default": database_from_url(database_url)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "th"
TIME_ZONE = "Asia/Bangkok"
USE_I18N = True
USE_TZ = True
LOCALE_PATHS = [BASE_DIR / "locale"]

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
PRIVATE_MEDIA_ROOT = BASE_DIR / "private_media"

static_backend = "django.contrib.staticfiles.storage.StaticFilesStorage"
# WhiteNoise middleware serves these files in deployment. Avoid manifest and
# compression storage here because Django admin's static assets can collide
# during parallel post-processing in clean deployment builds.

# django-cloudinary-storage still reads this legacy setting in its
# collectstatic command. Django 6 uses STORAGES above for actual resolution.
STATICFILES_STORAGE = static_backend

if package_exists("cloudinary_storage") and CLOUDINARY_STORAGE:
    default_storage = "agri_market.storage_backends.PublicCloudinaryStorage"
    private_storage_backend = "agri_market.storage_backends.PrivateCloudinaryStorage"
    private_storage_options = {}
else:
    default_storage = "django.core.files.storage.FileSystemStorage"
    private_storage_backend = "django.core.files.storage.FileSystemStorage"
    private_storage_options = {"location": PRIVATE_MEDIA_ROOT}

STORAGES = {
    "default": {"BACKEND": default_storage},
    "private": {"BACKEND": private_storage_backend, "OPTIONS": private_storage_options},
    "staticfiles": {"BACKEND": static_backend},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "catalog:product_list"
LOGOUT_REDIRECT_URL = "catalog:product_list"
PASSWORD_RESET_TIMEOUT = int(os.environ.get("PASSWORD_RESET_TIMEOUT", "3600"))
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_COOKIE_AGE", "1209600"))

ADMIN_SESSION_COOKIE_NAME = os.environ.get("ADMIN_SESSION_COOKIE_NAME", "admin_sessionid")
ADMIN_CSRF_COOKIE_NAME = os.environ.get("ADMIN_CSRF_COOKIE_NAME", "admin_csrftoken")
ADMIN_PREVIEW_COOKIE_NAME = os.environ.get("ADMIN_PREVIEW_COOKIE_NAME", "admin_site_preview")
ADMIN_PREVIEW_COOKIE_SALT = "agri-market-owner-site-preview"
ADMIN_MFA_REQUIRED = env_bool("ADMIN_MFA_REQUIRED", default=not DEBUG and not IS_TESTING)
ADMIN_MFA_CODE_MINUTES = int(os.environ.get("ADMIN_MFA_CODE_MINUTES", "10"))
ADMIN_SESSION_COOKIE_AGE = int(os.environ.get("ADMIN_SESSION_COOKIE_AGE", "28800"))

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"anon": "60/min", "user": "300/min"},
}

EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "15"))
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND") or (
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_HOST
    else "django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@local.test")
SERVER_EMAIL = os.environ.get("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
EMAIL_MAX_ATTEMPTS = int(os.environ.get("EMAIL_MAX_ATTEMPTS", "5"))

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_CONNECT_WEBHOOK_SECRET = os.environ.get("STRIPE_CONNECT_WEBHOOK_SECRET", "")
DEFAULT_CURRENCY = os.environ.get("DEFAULT_CURRENCY", "thb")
PLATFORM_FEE_PERCENT = os.environ.get("PLATFORM_FEE_PERCENT", "5.00")
SETTLEMENT_HOLD_DAYS = int(os.environ.get("SETTLEMENT_HOLD_DAYS", "2"))
STRIPE_CONNECT_TRANSFERS_ENABLED = env_bool("STRIPE_CONNECT_TRANSFERS_ENABLED", default=False)
SETTLEMENT_MAX_ATTEMPTS = int(os.environ.get("SETTLEMENT_MAX_ATTEMPTS", "5"))
AFTERSHIP_WEBHOOK_SECRET = os.environ.get("AFTERSHIP_WEBHOOK_SECRET", "")


SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
SENTRY_ENVIRONMENT = os.environ.get("SENTRY_ENVIRONMENT", "development" if DEBUG else "production")
SENTRY_TRACES_SAMPLE_RATE = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.05"))
if SENTRY_DSN and package_exists("sentry_sdk"):
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=SENTRY_ENVIRONMENT,
        release=os.environ.get("RENDER_GIT_COMMIT") or None,
        send_default_pii=False,
        traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
    )
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "payments": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
