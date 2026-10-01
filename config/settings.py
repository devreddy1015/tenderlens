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
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "ingest",
    "tenders",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
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

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": env("API_RATE_LIMIT", "120/min")},
}

SPECTACULAR_SETTINGS = {
    "TITLE": "TenderLens API",
    "DESCRIPTION": "Search public Indian government tenders crawled from NIC GePNIC portals.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
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
