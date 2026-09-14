from .base import *

SECRET_KEY = "test-only-secret-never-used-in-production-01234567890123456789"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
DISCORD_GUILD_ID = "100"
DISCORD_ADMIN_ROLE_ID = "200"
DISCORD_OVERLORD_ROLE_ID = "300"
DISCORD_PATRON_ROLE_ID = "400"
DISCORD_CLIENT_ID = "500"
DISCORD_CLIENT_SECRET = "test-only-client-secret"
DISCORD_BOT_TOKEN = "test-only-bot-token"
DISCORD_REDIRECT_URI = "https://testserver/auth/callback/"
COREPROTECT_DB_NAME = ""
