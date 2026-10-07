#!/bin/sh
# One image, several roles; the first argument picks one. Anything else runs as given
# (e.g. `python manage.py shell`).
#
#   migrate       apply migrations once (production: the one-shot `migrate` service; with
#                 DJANGO_PRODUCTION=true it also fails on any `check --deploy` warning)
#   web           gunicorn (deploy/gunicorn.conf.py); migrates first unless MIGRATE_ON_START=false
#   worker-crawl  Celery, `crawl` queue: thread pool, I/O-bound, ~1 req/s per portal host
#   worker        Celery, `default` queue: parsing, Copilot OCR/embeddings, alerts, emails
#   beat          Celery beat with its schedule on a volume (/var/lib/celery)
set -e
cd /app

case "$1" in
  migrate)
    python manage.py migrate --noinput
    if [ "${DJANGO_PRODUCTION:-false}" = true ]; then
      # Any warning blocks the deploy: security settings and the drf-spectacular schema lint.
      python manage.py check --deploy --fail-level WARNING
    fi
    ;;
  web)
    if [ "${MIGRATE_ON_START:-true}" = true ]; then
      python manage.py migrate --noinput
    fi
    exec gunicorn -c deploy/gunicorn.conf.py config.wsgi:application
    ;;
  worker-crawl)
    # 35 portals, each throttled to CRAWLER_MIN_INTERVAL seconds by a Redis lock shared by all
    # threads: ~24 threads keep every host busy while most threads wait on the network.
    exec celery -A config worker -Q crawl -P threads -c "${CRAWL_CONCURRENCY:-24}" \
      -n "crawl@%h" -l "${LOG_LEVEL:-INFO}" --without-gossip --without-mingle
    ;;
  worker)
    # Prefork: OCR and embeddings are CPU-bound. Recycle children to bound memory growth.
    exec celery -A config worker -Q default -c "${WORKER_CONCURRENCY:-2}" \
      --max-tasks-per-child 200 -n "default@%h" -l "${LOG_LEVEL:-INFO}" \
      --without-gossip --without-mingle
    ;;
  beat)
    exec celery -A config beat -l "${LOG_LEVEL:-INFO}" \
      --schedule "${BEAT_SCHEDULE_FILE:-/var/lib/celery/celerybeat-schedule}" --pidfile=
    ;;
  *)
    exec "$@"
    ;;
esac
