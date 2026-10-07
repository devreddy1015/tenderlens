"""Gunicorn settings for the `web` container (deploy/entrypoint.sh web).

gthread workers: a Copilot answer streams for ~60-80 s while the self-hosted LLM writes it,
and that must hold one thread, not a whole process. Each worker process loads the embedding
model (~0.5 GB) on its first question, so scale with threads before workers.
"""

import os

bind = "0.0.0.0:8000"
worker_class = "gthread"
workers = int(os.environ.get("GUNICORN_WORKERS") or 2)
threads = int(os.environ.get("GUNICORN_THREADS") or 8)
# Above LLM_TIMEOUT_SECONDS so a slow answer is ended by the LLM client (which then falls back
# to an extractive answer), never by gunicorn killing the worker mid-stream.
timeout = int(
    os.environ.get("GUNICORN_TIMEOUT") or float(os.environ.get("LLM_TIMEOUT_SECONDS") or 120) + 60
)
graceful_timeout = 30
keepalive = 5
# Recycle workers now and then to bound slow memory growth (torch, PyMuPDF).
max_requests = 2000
max_requests_jitter = 200
# Only Caddy reaches this port (it is not published), so trust its X-Forwarded-* headers.
forwarded_allow_ips = "*"
accesslog = "-"
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms "%(a)s"'
