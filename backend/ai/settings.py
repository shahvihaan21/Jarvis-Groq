"""
Django settings for the Jarvis AI project — 100% stateless & database-free.

- Serverless-ready for Vercel, Render, and Railway.
- No database, no ORM models, no migrations, no auth/admin/sessions.
- Static files served by Whitenoise + Vercel static routing.
- Configuration loaded from environment variables and local .env.
"""

import os
from pathlib import Path

import dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load local .env if present
dotenv.load_dotenv(BASE_DIR.parent / ".env")

# ---------------------------------------------------------------------------
# Core security & hosts
# ---------------------------------------------------------------------------

SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-jarvis-ai-stateless-prod-key-change-me")
DEBUG = os.environ.get("DEBUG", "False").lower() in ("1", "true", "yes")

# Default ALLOWED_HOSTS allows all subdomains on Vercel and local dev
raw_allowed_hosts = os.environ.get("ALLOWED_HOSTS", "*")
ALLOWED_HOSTS = [h.strip() for h in raw_allowed_hosts.split(",") if h.strip()]
if "*" not in ALLOWED_HOSTS and ".vercel.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.extend([".vercel.app", "localhost", "127.0.0.1"])

# CSRF trusted origins for Vercel preview deployments and custom domains
raw_csrf = os.environ.get("CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = [o.strip() for o in raw_csrf.split(",") if o.strip()]
if "https://*.vercel.app" not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.extend(["https://*.vercel.app", "https://*.onrender.com", "https://*.up.railway.app"])

# ---------------------------------------------------------------------------
# Application definition — minimal, database-free
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "corsheaders",
    "todo",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ai.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR.parent / "frontend" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "ai.wsgi.application"

# ---------------------------------------------------------------------------
# Database — intentionally disabled. Application is 100% stateless.
# ---------------------------------------------------------------------------

DATABASES = {}

# ---------------------------------------------------------------------------
# Cache — In-memory local cache for rate limiting and request idempotency
# ---------------------------------------------------------------------------

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "jarvis-stateless-cache",
    }
}

# ---------------------------------------------------------------------------
# Static files (Whitenoise + Vercel static)
# ---------------------------------------------------------------------------

STATIC_URL = "/static/"
STATICFILES_DIRS = [
    BASE_DIR.parent / "frontend" / "static",
]
STATIC_ROOT = BASE_DIR / "staticfiles"

# CompressedStaticFilesStorage prevents crashes if collectstatic was omitted in serverless
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
WHITENOISE_MAX_AGE = 3600
WHITENOISE_MANIFEST_STRICT = False
# Serve directly from STATICFILES_DIRS so the app works without running
# collectstatic first (covers local dev and bare serverless cold starts).
WHITENOISE_USE_FINDERS = True
if DEBUG:
    WHITENOISE_AUTOREFRESH = True

# Empty by default keeps cross-origin access disabled until explicitly configured.
CORS_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "pythonjsonlogger.json.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "loggers": {"todo": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}

# ---------------------------------------------------------------------------
# Production security headers
# ---------------------------------------------------------------------------

if not DEBUG:
    SECURE_SSL_REDIRECT = False  # TLS is terminated at Vercel/Render proxy
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    CSRF_COOKIE_SECURE = True

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
