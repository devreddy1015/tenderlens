# Deploying TenderLens on an Ubuntu server

The same `docker-compose.yml` runs in production. Every service has
`restart: unless-stopped`, so the stack comes back by itself after a reboot as long as
the Docker daemon is enabled.

## 1. One-time server setup

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
sudo systemctl enable --now docker            # Docker (and so the stack) starts on boot
sudo usermod -aG docker $USER && newgrp docker
# Elasticsearch needs this kernel setting, persisted across reboots:
echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-elasticsearch.conf && sudo sysctl --system
```

## 2. Get the code and configure

```bash
sudo mkdir -p /opt/tenderlens && sudo chown $USER /opt/tenderlens
git clone https://github.com/devreddy1015/tenderlens /opt/tenderlens && cd /opt/tenderlens
cp .env.example .env
python3 -c "import secrets; print('DJANGO_SECRET_KEY=' + secrets.token_urlsafe(50))" >> .env
# then edit .env:
#   DJANGO_ALLOWED_HOSTS=tenderlens.example.in,localhost,web
#   DJANGO_CSRF_TRUSTED_ORIGINS=https://tenderlens.example.in
#   POSTGRES_PASSWORD=<something long>
#   HTTP_PORT=80            # or keep 8080 behind an existing reverse proxy
```

### Google sign-in (for email alerts)

1. Open https://console.cloud.google.com/apis/credentials and create a project.
2. **OAuth consent screen**: External, app name "TenderLens", your email; scopes
   `openid`, `email`, `profile` only. Publish it.
3. **Create credentials → OAuth client ID → Web application.** Under *Authorized
   JavaScript origins*, add `https://tenderlens.example.in` (and `http://localhost:8080`
   for local testing). No redirect URI is needed; the button uses a popup.
4. Put the client ID (`…apps.googleusercontent.com`) in `.env` as `GOOGLE_CLIENT_ID`.
   It is public by design; there is no client secret to keep.

### Email (alerts and feedback)

Any SMTP provider works. With a Gmail account, turn on 2-Step Verification, create an
**App Password** at https://myaccount.google.com/apppasswords, then in `.env`:

```
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=you@gmail.com
EMAIL_HOST_PASSWORD=<the 16-character app password>
DEFAULT_FROM_EMAIL=TenderLens <you@gmail.com>
FEEDBACK_NOTIFY_EMAIL=you@gmail.com
SITE_URL=https://tenderlens.example.in
SECURE_COOKIES=true
```

Gmail allows roughly 500 messages a day. For more, use a transactional provider (Brevo,
Amazon SES, Postmark) and add SPF/DKIM records for your domain so alerts aren't marked
as spam. Leave `DJANGO_DEBUG` and `DEV_LOGIN_ENABLED` unset in production.

## 3. Start

```bash
make up                      # builds images, waits until every health check passes
curl -s localhost:${HTTP_PORT:-8080}/health | python3 -m json.tool
make crawl MODE=full         # first full crawl; afterwards Celery Beat runs hourly + nightly
make admin                   # admin user for /admin/ (feedback, alerts, crawl runs)
```

HTTPS: put the server behind Cloudflare, or add certbot on the host and proxy to the
nginx container. The container's nginx config is in `deploy/nginx.conf`.

## 4. Backups (nightly pg_dump)

```bash
crontab -e
# 15 3 * * *  cd /opt/tenderlens && ./deploy/backup.sh >> backups/backup.log 2>&1
```

`backup.sh` writes a custom-format dump, verifies it with `pg_restore --list`, and
keeps 14 days. Restore:

```bash
docker compose exec -T postgres pg_restore -U tenderlens -d tenderlens --clean --if-exists < backups/tenderlens-YYYYMMDD-HHMMSS.dump
```

Copy `backups/` off the machine (rsync, rclone to cloud storage). A backup kept on the
same disk is not a backup.

## 5. Monitoring

`GET /health` returns:

* `checks`: database, redis, elasticsearch (`503` only when the database is down)
* `crawl.runs_24h`: crawl runs by status (`succeeded`, `mismatch`, `failed`, `incomplete`)
* `crawl.last_success_at`, `crawl.open_dead_letters`, `crawl.quarantined_24h`

Point any uptime checker (UptimeRobot, Better Stack, a cron + curl) at `/health`, and
alert when `last_success_at` is more than ~3 hours old or `runs_24h.failed` > 0.

## 6. Verify reboot survival

```bash
sudo reboot
# after it comes back:
docker compose ps            # all services "running (healthy)"
curl -s localhost:${HTTP_PORT:-8080}/health
```

## Operations cheat-sheet

| Task | Command |
|---|---|
| Logs | `make logs` |
| Queue a crawl | `make crawl SOURCE=central MODE=incremental` |
| Re-parse stored pages | `make backfill FROM=2026-10-01 TO=2026-10-02` |
| Rebuild search index | `make reindex` |
| Re-run buyer resolution | `docker compose exec web python manage.py resolve_buyers --rebuild` |
| Review the 80–90 band | `docker compose exec web python manage.py er_review` |
| Dead letters | `docker compose exec postgres psql -U tenderlens -c "select * from dead_letter where not resolved"` |
