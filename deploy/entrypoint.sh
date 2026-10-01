#!/bin/sh
set -e
if [ "$1" = "web" ]; then
  python manage.py migrate --noinput
  python manage.py es_setup || echo "elasticsearch not ready; search falls back to Postgres"
  exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers "${GUNICORN_WORKERS:-3}" \
       --timeout 60 --access-logfile - --forwarded-allow-ips="*"
fi
exec "$@"
