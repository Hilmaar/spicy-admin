import os
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in {"true", "1", "yes"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG")
TESTING = os.environ.get("DJANGO_SETTINGS_MODULE") == "config.settings.test"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not TESTING and (len(SECRET_KEY) < 50 or SECRET_KEY.startswith("replace-")):
    raise ImproperlyConfigured(
        "Set DJANGO_SECRET_KEY to a random secret of at least 50 characters."
    )
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
if not DEBUG and not TESTING and (not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS):
    raise ImproperlyConfigured("Set explicit DJANGO_ALLOWED_HOSTS in production.")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "accounts",
    "portal",
    "documentation",
    "coreprotect",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "portal.middleware.PrivateResponseMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "portal.context_processors.navigation",
            ]
        },
    }
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.environ.get("POSTGRES_HOST", "postgres"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "NAME": os.environ.get("POSTGRES_DB", "spicy_admin"),
        "USER": os.environ.get("POSTGRES_USER", "spicy_admin"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"connect_timeout": 5},
    }
}
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["accounts.backends.DiscordSessionBackend"]
LOGIN_URL = "/auth/login/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 12
SECURE_SSL_REDIRECT = not DEBUG
# Only trust this header because host Nginx overwrites it and web binds to loopback.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID", "")
DISCORD_ADMIN_ROLE_ID = os.environ.get("DISCORD_ADMIN_ROLE_ID", "")
DISCORD_OVERLORD_ROLE_ID = os.environ.get("DISCORD_OVERLORD_ROLE_ID", "")
DISCORD_PATRON_ROLE_ID = os.environ.get("DISCORD_PATRON_ROLE_ID", "")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "")
DISCORD_ROLE_CACHE_SECONDS = int(os.environ.get("DISCORD_ROLE_CACHE_SECONDS", "45"))
if not 30 <= DISCORD_ROLE_CACHE_SECONDS <= 60:
    raise ImproperlyConfigured("DISCORD_ROLE_CACHE_SECONDS must be between 30 and 60.")
if DISCORD_REDIRECT_URI and not DEBUG and urlsplit(DISCORD_REDIRECT_URI).scheme != "https":
    raise ImproperlyConfigured("Production Discord callback must use HTTPS.")

COREPROTECT_DB_HOST = os.environ.get("COREPROTECT_DB_HOST", "host.docker.internal")
COREPROTECT_DB_PORT = int(os.environ.get("COREPROTECT_DB_PORT", "3306"))
COREPROTECT_DB_NAME = os.environ.get("COREPROTECT_DB_NAME", "")
COREPROTECT_DB_USER = os.environ.get("COREPROTECT_DB_USER", "")
COREPROTECT_DB_PASSWORD = os.environ.get("COREPROTECT_DB_PASSWORD", "")
COREPROTECT_TABLE_PREFIX = os.environ.get("COREPROTECT_TABLE_PREFIX", "co_")
COREPROTECT_TIMEOUT_SECONDS = int(os.environ.get("COREPROTECT_TIMEOUT_SECONDS", "3"))
if not 1 <= COREPROTECT_TIMEOUT_SECONDS <= 10:
    raise ImproperlyConfigured("COREPROTECT_TIMEOUT_SECONDS must be between 1 and 10.")

# Do not log URLs/query strings, OAuth codes, API payloads, or exception locals.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django.server": {"handlers": ["console"], "level": "CRITICAL", "propagate": False},
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
    },
}
