"""Django settings. Everything environment-specific comes from env vars (see .env.example)."""

import os
from pathlib import Path

from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).lower() in {"1", "true", "yes", "on"}


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,web").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "ingest",
    "tenders",
    "api",
    "accounts",
    "alerts",
    "feedback",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "tenderlens"),
        "USER": env("POSTGRES_USER", "tenderlens"),
        "PASSWORD": env("POSTGRES_PASSWORD", "tenderlens"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --- Sessions, CSRF, sign-in -----------------------------------------------------
# The React app and the API share one origin behind nginx, so plain session cookies
# work: SameSite=Lax blocks cross-site POSTs, and the CSRF token covers same-site ones.
SECURE_COOKIES = env_bool("SECURE_COOKIES", False)  # true in production (HTTPS)
SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_SECURE = SECURE_COOKIES
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Google sign-in: create an OAuth client ID ("Web application") in Google Cloud Console
# and add your site to "Authorized JavaScript origins". Empty disables the button.
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", "")
# Local development without Google: sign in with any email. Never true in production;
# it is ignored unless DEBUG is also true.
DEV_LOGIN_ENABLED = DEBUG and env_bool("DEV_LOGIN_ENABLED", False)

# --- Email (tender alerts, feedback notifications) -----------------------------------
# Development: Mailpit (in docker-compose) catches every email at http://localhost:8025.
# Production: any SMTP provider, e.g. Gmail with an App Password:
#   EMAIL_HOST=smtp.gmail.com EMAIL_PORT=587 EMAIL_USE_TLS=true
#   EMAIL_HOST_USER=you@gmail.com EMAIL_HOST_PASSWORD=<16-char app password>
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = int(env("EMAIL_PORT", "1025"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
EMAIL_TIMEOUT = 20
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "TenderLens <alerts@tenderlens.local>")
# Where feedback is forwarded (empty: stored in the database only).
FEEDBACK_NOTIFY_EMAIL = env("FEEDBACK_NOTIFY_EMAIL", "")
# Absolute URL of the site, used for links inside emails.
SITE_URL = env("SITE_URL", "http://localhost:8080").rstrip("/")
# The site's own origin is always trusted for CSRF (it matters behind TLS-terminating
# proxies, where the scheme Django sees can differ from the browser's).
if SITE_URL not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(SITE_URL)

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("API_RATE_LIMIT", "120/min"),
        "user": env("API_RATE_LIMIT_USER", "240/min"),
        "feedback": "10/hour",
        "auth": "30/hour",
        "alert_test": "10/hour",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "TenderLens API",
    "DESCRIPTION": "Search public Indian government tenders crawled from NIC GePNIC portals.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")

# Cache (API throttle counters) in its own Redis database, never the Celery broker's:
# a cache flush must not be able to delete queued tasks.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_CACHE_URL", REDIS_URL.rsplit("/", 1)[0] + "/1"),
    }
}

# --- Celery -----------------------------------------------------------------
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_EAGER_PROPAGATES = True
# A task is acknowledged only after it finishes, and a task whose worker died is
# redelivered. Together with idempotent upserts this is what makes "kill the
# worker mid-crawl" safe.
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
# With Redis as broker, a task held by a worker that died is redelivered once this many
# seconds pass. It must exceed the longest task (crawl_listing on the central portal is
# ~6-8 minutes at 1 req/s); a task that outlives it would run twice, which is wasteful but
# harmless because every step is idempotent.
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "visibility_timeout": int(env("CELERY_VISIBILITY_TIMEOUT", "900"))
}
CELERY_TASK_ROUTES = {
    "ingest.tasks.crawl_listing": {"queue": "crawl"},
    "ingest.tasks.fetch_detail": {"queue": "crawl"},
    "ingest.tasks.parse_and_load": {"queue": "default"},
    "tenders.tasks.*": {"queue": "default"},
}
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "hourly-incremental-crawl": {
        "task": "ingest.tasks.start_crawl",
        "schedule": crontab(minute=5),
        "kwargs": {"mode": "incremental"},
    },
    "nightly-full-crawl": {
        "task": "ingest.tasks.start_crawl",
        "schedule": crontab(minute=30, hour=2),
        "kwargs": {"mode": "full"},
    },
    "close-stale-runs": {
        "task": "ingest.tasks.close_stale_runs",
        "schedule": crontab(minute="*/15"),
    },
    # Alerts are also sent when each crawl run finishes; this catches anything missed.
    "send-tender-alerts": {
        "task": "alerts.tasks.send_alerts",
        "schedule": crontab(minute=50),
    },
    "prune-raw-listing-pages": {
        "task": "ingest.tasks.prune_raw_pages",
        "schedule": crontab(minute=0, hour=4),
    },
}

# --- Crawler ----------------------------------------------------------------
CRAWLER = {
    "USER_AGENT": env(
        "CRAWLER_USER_AGENT",
        "TenderLens/0.1 (+https://github.com/devreddy1015/tenderlens; polite crawler, 1 req/s)",
    ),
    "MIN_INTERVAL_SECONDS": float(env("CRAWLER_MIN_INTERVAL", "1.0")),
    "TIMEOUT_SECONDS": float(env("CRAWLER_TIMEOUT", "30")),
    "MAX_ATTEMPTS": int(env("CRAWLER_MAX_ATTEMPTS", "4")),
    # Comma-separated source keys from ingest/sources.py
    "SOURCES": env("CRAWLER_SOURCES", "central").split(","),
    # Listing/index pages are only needed for change detection; details are kept.
    "RAW_LISTING_RETENTION_DAYS": int(env("RAW_LISTING_RETENTION_DAYS", "7")),
}

# --- Elasticsearch ----------------------------------------------------------
ES_URL = env("ES_URL", "http://localhost:9200")
ES_INDEX = env("ES_INDEX", "tenders")
ES_ENABLED = env_bool("ES_ENABLED", True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "httpx": {"level": "WARNING"},
        "elastic_transport": {"level": "WARNING"},
    },
}
