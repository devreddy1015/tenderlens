"""Django settings. Everything environment-specific comes from env vars (see .env.example)."""

import os
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

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
    "copilot",
    "workspaces",
    "billing",
    "intel",  # bid advisor stage: historical awards, price model (docs/BID_ADVISOR.md)
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

# A managed Postgres usually provides a single DATABASE_URL; docker-compose and local runs
# use the POSTGRES_* variables.
if env("DATABASE_URL"):
    _db_url = urlsplit(env("DATABASE_URL"))
    _db = {
        "NAME": unquote(_db_url.path.lstrip("/")),
        "USER": unquote(_db_url.username or ""),
        "PASSWORD": unquote(_db_url.password or ""),
        "HOST": _db_url.hostname or "",
        "PORT": str(_db_url.port or 5432),
        "OPTIONS": dict(parse_qsl(_db_url.query)),  # e.g. sslmode=require
    }
else:
    _db = {
        "NAME": env("POSTGRES_DB", "tenderlens"),
        "USER": env("POSTGRES_USER", "tenderlens"),
        "PASSWORD": env("POSTGRES_PASSWORD", "tenderlens"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "OPTIONS": {},
    }
# Fail fast when the database is unreachable instead of waiting ~2 min for TCP.
_db["OPTIONS"].setdefault("connect_timeout", 10)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        **_db,
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        # PgBouncer in transaction mode (a "-pooler" host) cannot keep server-side cursors.
        "DISABLE_SERVER_SIDE_CURSORS": "-pooler" in _db["HOST"],
        # Parallel test runs (CI shards, several builders on one machine) each need their own
        # test database: TEST_DB_NAME=test_<name> uv run pytest.
        "TEST": {"NAME": env("TEST_DB_NAME")},
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
    # Two "role" and several "status" choice sets share a field name; name them explicitly so
    # the schema (and `check --deploy`, which the production entrypoint gates on) stays clean.
    "ENUM_NAME_OVERRIDES": {
        "MembershipRoleEnum": "workspaces.models.Membership.Role",
        "BidTrackStatusEnum": "workspaces.models.BidTrack.Status",
    },
}

REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
# Vercel runs no broker (crawls and beat jobs run in .github/workflows/crawl.yml): there,
# without a REDIS_URL, /health reports Redis as not used instead of down.
REDIS_EXPECTED = bool(env("REDIS_URL")) or not env("VERCEL")

# Cache (API throttle counters) in its own Redis database, never the Celery broker's:
# a cache flush must not be able to delete queued tasks. Hosted Redis URLs often have no
# "/<db>" path, so the database is set on the parsed URL rather than by string splitting.
# With no Redis configured at all (e.g. a serverless deploy), throttle counters fall back to
# per-process memory instead of turning every API request into a connection error.
_cache_url = env("REDIS_CACHE_URL") or (
    urlunsplit(urlsplit(env("REDIS_URL"))._replace(path="/1")) if env("REDIS_URL") else ""
)
CACHES = {
    "default": (
        {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _cache_url,
            "OPTIONS": {"socket_connect_timeout": 2, "socket_timeout": 2},
        }
        if _cache_url
        else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    )
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
    # Per-source crawl entries are added below the CRAWLER section (ingest/schedule.py).
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
    "prune-crawl-items": {  # no-op unless CRAWL_ITEM_RETENTION_DAYS is set
        "task": "ingest.tasks.prune_crawl_items",
        "schedule": crontab(minute=10, hour=4),
    },
    "refresh-search-words": {  # typo-correction word list, after the hourly crawl
        "task": "tenders.tasks.refresh_search_words",
        "schedule": crontab(minute=40),
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
    # Comma-separated source keys from ingest/sources.py; "all" = every enabled source.
    "SOURCES": env("CRAWLER_SOURCES", "all").split(","),
    # Listing/index pages are only needed for change detection; details are kept.
    "RAW_LISTING_RETENTION_DAYS": int(env("RAW_LISTING_RETENTION_DAYS", "7")),
    # Unset: keep every detail page. Set (small hosted databases): after this many days,
    # delete detail pages that no tender or quarantine row points at. 0 also drops an
    # unchanged re-fetch as soon as it is loaded (see pipeline.record_loaded).
    "RAW_DETAIL_RETENTION_DAYS": (
        int(env("RAW_DETAIL_RETENTION_DAYS")) if env("RAW_DETAIL_RETENTION_DAYS") else None
    ),
    # Unset: keep per-tender crawl outcomes forever. Set: delete those of finished runs older
    # than this; the run's totals stay on CrawlRun.
    "CRAWL_ITEM_RETENTION_DAYS": (
        int(env("CRAWL_ITEM_RETENTION_DAYS")) if env("CRAWL_ITEM_RETENTION_DAYS") else None
    ),
}
# --- Sources stage: per-source crawls (hourly incremental, nightly full), staggered. An
# unknown key in CRAWLER_SOURCES fails here, at startup, rather than in the 3 a.m. crawl.
from ingest.schedule import crawl_beat_schedule  # noqa: E402

CELERY_BEAT_SCHEDULE.update(crawl_beat_schedule(CRAWLER["SOURCES"]))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "httpx": {"level": "WARNING"},
    },
}

# --- Copilot ----------------------------------------------------------------
# Empty values in .env count as unset ("or" defaults), so .env.example can list every key.
# Any OpenAI-compatible server: llama.cpp (default, `llm/`), Ollama, vLLM. Swapping the model
# (CPU <-> GPU <-> fine-tuned) means changing LLM_BASE_URL / LLM_MODEL only.
LLM_BASE_URL = (env("LLM_BASE_URL") or "http://localhost:8081/v1").rstrip("/")
LLM_MODEL = env("LLM_MODEL") or "tenderlens-qwen3.5-4b"
LLM_API_KEY = env("LLM_API_KEY") or ""  # llama.cpp ignores it unless started with --api-key
LLM_TIMEOUT_SECONDS = float(env("LLM_TIMEOUT_SECONDS") or "120")
LLM_MAX_TOKENS = int(env("LLM_MAX_TOKENS") or "700")
# Multilingual (Hindi + English tender documents), 384 dimensions, runs on CPU.
EMBEDDING_MODEL = env("EMBEDDING_MODEL") or "intfloat/multilingual-e5-small"
# A sentence-transformers cross-encoder, e.g. BAAI/bge-reranker-base; empty = no reranking.
RERANKER_MODEL = env("RERANKER_MODEL") or ""
# Uploaded tender documents. In production a mounted volume, backed up with the database.
# Vercel (which sets VERCEL=1) can only write to /tmp and runs no worker, so an upload there
# is kept briefly and marked "processing queue unavailable" instead of failing with a 500.
MEDIA_ROOT = Path(env("MEDIA_ROOT") or ("/tmp/media" if env("VERCEL") else BASE_DIR / "media"))
MEDIA_URL = "/media/"
COPILOT_MAX_UPLOAD_MB = int(env("COPILOT_MAX_UPLOAD_MB") or "25")
# Uploads above 2.5 MB stream to a temp file instead of memory; the request body may be the
# largest allowed PDF plus the multipart overhead.
FILE_UPLOAD_MAX_MEMORY_SIZE = 2_621_440
DATA_UPLOAD_MAX_MEMORY_SIZE = (COPILOT_MAX_UPLOAD_MB + 1) * 1024 * 1024

# --- Workspaces -------------------------------------------------------------
# OCDS ids (ocid) are "<prefix>-<source>-<native tender ID>". Register a prefix with the Open
# Contracting Partnership before publishing; the default is for development.
OCDS_PREFIX = env("OCDS_PREFIX") or "ocds-tenderlens"
INVITE_MAX_AGE_DAYS = int(env("INVITE_MAX_AGE_DAYS") or "7")
# REST API keys (`Authorization: Api-Key tl_...`, plan feature "api"): tried before the
# session so a key request never needs a CSRF token, and rate-limited per key.
REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] = [
    "workspaces.auth.ApiKeyAuthentication",
    *REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"],
]
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"].append("workspaces.auth.ApiKeyRateThrottle")
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["api_key"] = env("API_KEY_RATE_LIMIT") or "600/min"
# Daily email about tracked tenders closing within 3 days that are not submitted yet.
CELERY_BEAT_SCHEDULE["pipeline-reminders"] = {
    "task": "workspaces.tasks.send_pipeline_reminders",
    "schedule": crontab(minute=0, hour=8),  # 08:00 IST
}

# --- Billing ----------------------------------------------------------------
# fake: checkout activates the plan immediately (development, tests). razorpay: real
# subscriptions through Razorpay Checkout and its signed webhook.
# Unset, it is "fake" only with DEBUG on: a production server without the variable must
# never hand out paid plans for free.
BILLING_PROVIDER = env("BILLING_PROVIDER") or ("fake" if DEBUG else "razorpay")
RAZORPAY_KEY_ID = env("RAZORPAY_KEY_ID") or ""
RAZORPAY_KEY_SECRET = env("RAZORPAY_KEY_SECRET") or ""
RAZORPAY_WEBHOOK_SECRET = env("RAZORPAY_WEBHOOK_SECRET") or ""
# Razorpay plan ids (Dashboard > Subscriptions > Plans), one per paid plan and interval:
# RAZORPAY_PLAN_PRO_MONTH, RAZORPAY_PLAN_PRO_YEAR, RAZORPAY_PLAN_TEAM_MONTH, ...
RAZORPAY_PLAN_IDS = {
    f"{code}_{interval}": env(f"RAZORPAY_PLAN_{code}_{interval}") or ""
    for code in ("PRO", "TEAM")
    for interval in ("MONTH", "YEAR")
}

# --- Production security ----------------------------------------------------
# DJANGO_PRODUCTION=true (set by deploy/compose.prod.yml) switches on the HTTPS-only settings
# and refuses to start with a development configuration, so a typo in .env fails the deploy
# instead of quietly serving free paid plans or session cookies over plain HTTP. Caddy
# terminates TLS and sends X-Forwarded-Proto (SECURE_PROXY_SSL_HEADER above).
PRODUCTION = env_bool("DJANGO_PRODUCTION", False)
if PRODUCTION:
    from django.core.exceptions import ImproperlyConfigured

    _problems = [
        msg
        for bad, msg in (
            (DEBUG, "DJANGO_DEBUG must be false"),
            (
                SECRET_KEY in {"dev-only-insecure-key", "change-me"} or len(SECRET_KEY) < 50,
                "DJANGO_SECRET_KEY must be a random string of 50+ characters",
            ),
            (not SITE_URL.startswith("https://"), "SITE_URL must start with https://"),
            (BILLING_PROVIDER != "razorpay", "BILLING_PROVIDER must be razorpay"),
            (
                not (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET and RAZORPAY_WEBHOOK_SECRET),
                "RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET and RAZORPAY_WEBHOOK_SECRET are required",
            ),
        )
        if bad
    ]
    if _problems:
        raise ImproperlyConfigured("Production settings: " + "; ".join(_problems))
    # The public host always works, even if DJANGO_ALLOWED_HOSTS forgets it; localhost is for
    # the container healthchecks (gunicorn is not published, and Caddy only routes SITE_ADDRESS).
    _site_host = urlsplit(SITE_URL).hostname or ""
    ALLOWED_HOSTS = [h for h in dict.fromkeys([*ALLOWED_HOSTS, _site_host, "localhost"]) if h]
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    # Container healthchecks call gunicorn directly over plain HTTP.
    SECURE_REDIRECT_EXEMPT = [r"^health$"]
    SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS") or 31_536_000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
    # Google sign-in's popup must be able to message the opener.
    SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin-allow-popups"
    # HSTS preload is a months-long commitment made by submitting the domain to
    # hstspreload.org; leave it to the founder rather than send the directive by default.
    SILENCED_SYSTEM_CHECKS = ["security.W021"]
