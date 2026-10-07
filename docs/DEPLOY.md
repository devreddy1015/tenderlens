# Deploying TenderLens (production runbook)

One VPS, Docker Compose, Caddy with automatic HTTPS, and a nightly off-site backup. These
steps are written for a solo founder. Every command runs from the repository root on the
server (`/opt/tenderlens`) unless it says otherwise.

```
Internet ──443──► caddy (proxy image: React build + Caddyfile, Let's Encrypt)
                   │  /api /admin /static /health ──► web (gunicorn gthread, :8000)
                   │  /api/copilot/ask: SSE, flushed immediately, never compressed
                   ▼
   web ─┬─ postgres (pgvector/pgvector:pg16)    media volume (uploaded PDFs)
        ├─ redis (Celery broker + throttle locks)
        └─ llm (llama.cpp, optional, profile "llm")
   worker-crawl (Celery `crawl` queue, 24 threads, ≤ 1 req/s per portal host)
   worker       (Celery `default` queue: Copilot OCR + embeddings, alerts, email)
   beat         (schedule file on a volume)      migrate (one-shot, runs before all of them)
```

Files: `Dockerfile` (targets `app` and `proxy`), `deploy/compose.prod.yml`,
`deploy/caddy/Caddyfile` (+ `csp.mjs`, which builds the Content-Security-Policy),
`deploy/gunicorn.conf.py`, `deploy/entrypoint.sh`, `deploy/backup.sh`, `deploy/restore.sh`.

## 1. Choose the server

| Profile | What runs | Minimum | Recommended |
|---|---|---|---|
| **No LLM** | Everything except `llm`. Copilot answers are extractive (best passage sentences, still cited); Bid Brief and Eligibility are rule-based and need no LLM. | 4 vCPU, 8 GB RAM, 80 GB disk | Hetzner CX33 (4 vCPU / 8 GB / 80 GB) |
| **CPU LLM** | Everything plus llama.cpp running Qwen3.5-4B Q4_K_M (about 3.3 GB resident). One answer at a time, about 55–80 s each. | 8 vCPU, 16 GB RAM, 160 GB disk | Hetzner CX43 (8 vCPU / 16 GB / 160 GB). For faster answers, use dedicated vCPUs (CCX line). |
| **GPU** | The app on a small VPS as in "No LLM", and the LLM on a GPU box (`llama.cpp:server-cuda`, `-ngl 99 -np 4`). Point `LLM_BASE_URL` at it over a private network or WireGuard. | Any NVIDIA card with 8 GB or more (the 4B model plus KV cache fits in 6 GB) | Rent a GPU only once answer volume justifies it. |

The memory limits in `deploy/compose.prod.yml` add up to about 12.5 GB with the LLM: web 2 GB,
default worker 2 GB, crawl worker 1 GB, beat 384 MB, Postgres 2 GB, Redis 300 MB, Caddy
256 MB and LLM 5 GB. They fit 16 GB with page cache to spare. On an 8 GB box without the LLM,
keep the defaults. Each limit is a `*_MEM` variable in `.env`. Measured use is in §10.

Pick a location close to your users. Hetzner has no Indian region; its Singapore location
gives about 60–90 ms from Indian ISPs (assumption, not measured). An Indian provider works the
same way, since everything is plain Docker.

## 2. One-time server setup

```bash
# Ubuntu 24.04
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git make
sudo systemctl enable --now docker            # the stack restarts itself after a reboot
sudo usermod -aG docker $USER && newgrp docker
sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw allow 443/udp && sudo ufw enable
# The CPU-LLM box: add 4 GB of swap as a safety net for model loading
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile \
  && sudo swapon /swapfile && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Only Caddy publishes ports. Postgres, Redis, gunicorn and the LLM are reachable only on the
internal compose network. Note that Docker bypasses ufw for published ports, which is why
nothing else is published.

## 3. DNS

At your registrar, create an `A` record (and an `AAAA` record if the VPS has IPv6) for
`tenders.example.in` pointing at the server's IP. Wait until `dig +short tenders.example.in`
returns the IP. Caddy requests the Let's Encrypt certificate on first start, and it can only
do so once DNS resolves and port 80 is reachable.

For email, add your SMTP provider's SPF and DKIM records (and a `_dmarc` TXT record) so
alert emails do not land in spam.

## 4. Configure

```bash
sudo mkdir -p /opt/tenderlens && sudo chown $USER /opt/tenderlens
git clone https://github.com/devreddy1015/tenderlens /opt/tenderlens && cd /opt/tenderlens
git checkout platform-v2          # or main once merged
cp .env.example .env && chmod 600 .env
```

Edit `.env` and fill in the **Production** block at the bottom of `.env.example`. Every
starred value is mandatory. The stack runs with `DJANGO_PRODUCTION=true`, so Django refuses to
start (and `migrate` fails, which stops the deploy) if any of these is wrong: `DJANGO_DEBUG` is
true, the secret key is short, `SITE_URL` is not `https://`, `BILLING_PROVIDER` is not
`razorpay`, or the Razorpay keys are missing. Also delete the development lines at the top that
the production block replaces: `DJANGO_DEBUG`, `SITE_URL`, `SECURE_COOKIES`, `BILLING_PROVIDER`
and `POSTGRES_PASSWORD`. The last line wins in `.env`, but having only one copy is clearer.

**Google sign-in.** In https://console.cloud.google.com/apis/credentials, create a project.
Set up the OAuth consent screen (External; scopes `openid`, `email`, `profile`; then publish
it). Under **Create credentials → OAuth client ID → Web application**, add
`https://tenders.example.in` to *Authorized JavaScript origins*. Put the client ID in
`GOOGLE_CLIENT_ID`. It has no secret.

**Email.** Any SMTP relay works (Brevo, Amazon SES, Postmark, or Gmail with an App Password
for about 500 messages a day). Set `EMAIL_HOST`, `EMAIL_PORT=587`, `EMAIL_USE_TLS=true`,
`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and `DEFAULT_FROM_EMAIL`.

**Razorpay** (Dashboard, Live mode):
1. API keys (*Account & Settings → API Keys*): `RAZORPAY_KEY_ID` (`rzp_live_…`) and
   `RAZORPAY_KEY_SECRET`.
2. Plans (*Subscriptions → Plans*): one per paid plan and interval, at the prices in
   `billing/plans.py`. Their ids go in `RAZORPAY_PLAN_PRO_MONTH`, `RAZORPAY_PLAN_PRO_YEAR`,
   `RAZORPAY_PLAN_TEAM_MONTH` and `RAZORPAY_PLAN_TEAM_YEAR`.
3. Webhook (*Account & Settings → Webhooks*): the URL is
   **`https://tenders.example.in/api/billing/webhook`**. Choose a strong secret and put the
   same value in `RAZORPAY_WEBHOOK_SECRET`. Enable the events `subscription.activated`,
   `subscription.charged`, `subscription.cancelled`, `subscription.halted` and
   `subscription.completed`. The handler verifies `X-Razorpay-Signature` and is idempotent
   per event id, so Razorpay's retries are harmless.
4. Test end to end once in Test mode first, using test keys on a staging subdomain.

**OCDS prefix.** `/api/ocds/releases` publishes OCDS 1.1 releases whose ids are
`<OCDS_PREFIX>-<source>-<tender id>`. To get a globally unique prefix (`ocds-xxxxxx`), email the
Open Contracting Partnership's helpdesk (data@open-contracting.org; see
https://standard.open-contracting.org/latest/en/guidance/build/#register-an-ocid-prefix).
Registration is free. Until it arrives, keep the placeholder and do not advertise the feed.
Changing the prefix later changes every ocid.

**Copilot LLM.** Choose one:
- *CPU on the same box:* download the GGUF into `llm/models/` (llm/README.md), then set
  `COMPOSE_PROFILES=llm` and `LLM_BASE_URL=http://llm:8080/v1`.
- *Remote GPU:* set `LLM_BASE_URL=http://<gpu-host>:8080/v1` and leave the profile off. The GPU
  variant of the service is at the bottom of `deploy/llm/compose.llm.yml`.
- *None:* leave the profile off. Answers fall back to extractive mode automatically.

Pin the llama.cpp image after the first deploy:
`LLM_IMAGE=ghcr.io/ggml-org/llama.cpp@sha256:…` (from `docker image inspect`). That way an
upstream chat-template change cannot silently change answers.

## 5. First deploy

```bash
make prod-config        # resolved compose file; fails on a missing mandatory variable
make prod-build         # app + proxy images, also tagged with the git commit (for rollbacks)
make prod-check         # manage.py check --deploy with your .env, inside the image
make prod-up            # migrate (once) → web, workers, beat → caddy; waits for healthchecks
make prod-ps
curl -fsS https://tenders.example.in/health
docker compose -f deploy/compose.prod.yml --env-file .env exec web python manage.py createsuperuser
```

Next, load data. The real tenders are already in your dev database, so restore a dev dump
(§7, "Live restore"), or let beat crawl. Beat runs hourly incremental crawls and nightly full
crawls for all 35 portals. To start right away:

```bash
docker compose -f deploy/compose.prod.yml --env-file .env exec web python manage.py crawl --source all --mode full
```

What the images do:
- **Embedding model baked in, not a cache volume.** `intfloat/multilingual-e5-small` (about
  470 MB of safetensors) is downloaded at build time into `/opt/hf`, and `HF_HUB_OFFLINE=1`
  is set. Web and the default worker both load it. Baking it means a restart or a new
  replica never depends on huggingface.co being up or rate-limiting, and the image is
  reproducible. A volume would save one image layer per rebuild, but Docker caches that
  layer anyway until `EMBEDDING_MODEL` changes. Changing the model means
  `docker compose build --build-arg EMBEDDING_MODEL=…`, or mounting a local directory and
  setting `EMBEDDING_MODEL=/models/x`.
- **OCR:** ocrmypdf, Tesseract (English and Hindi) and Ghostscript come from Debian. Scanned
  pages in uploaded tender PDFs are read automatically.
- **Non-root:** the app runs as uid 1001. The code is read-only to it, and only `/app/media`
  and `/var/lib/celery` are writable (both are volumes). Build tools (uv, node, the model
  download) live in throwaway stages.
- **Migrations run once:** the one-shot `migrate` service applies them and runs
  `check --deploy`. Every app container waits for it to finish
  (`service_completed_successfully`), so replicas never race. In development, `web` migrates
  on start instead (`MIGRATE_ON_START`).
- **gunicorn:** gthread, `GUNICORN_WORKERS=2` × `GUNICORN_THREADS=8`. The timeout is
  `LLM_TIMEOUT_SECONDS + 60`, so a slow answer is ended by the LLM client, which then falls
  back to an extractive answer, and never by gunicorn killing the worker. Each open answer
  stream holds one thread for about 80 s, so raise threads before workers. Each worker
  process holds its own copy of the embedding model.
- **Caddy:** hashed `/assets/*` get `Cache-Control: immutable` for a year, `index.html` gets
  `no-cache`, and unknown paths fall back to the SPA. Responses are compressed with zstd or
  gzip, except the SSE answer stream, which is proxied with `flush_interval -1`. Security
  headers: HSTS (1 year), `nosniff`, `X-Frame-Options`, `Referrer-Policy`, COOP
  `same-origin-allow-popups` (for the Google popup), `Permissions-Policy`, and a CSP generated
  at build time. The CSP hashes the inline theme script and allows only Google sign-in,
  Google Fonts, Google profile pictures and Razorpay Checkout (`deploy/caddy/csp.mjs` lists
  why). If the frontend adds another external origin, add it there. Uploaded PDFs are never
  served by Caddy.

## 6. Upgrades and rollbacks

```bash
make prod-deploy        # git pull --ff-only → backup → build (tagged with the commit) → up --wait
```

`up --wait` replaces containers one service at a time. `web` is down for a few seconds while
its replacement starts. Answers that are streaming at that moment end early (gunicorn's
graceful timeout is 30 s).

**Rollback:** `make prod-rollback TAG=<previous short sha>`. `docker images tenderlens` lists
the tags. This rolls back code, not the database. Our migrations are additive, so the
previous build runs fine on the newer schema. If a release ever contains a destructive
migration, say so in its notes and roll back with a restore (§7) instead.

Clean up old images monthly: `docker image prune -a --filter "until=720h"`. This keeps the last
30 days of tags.

## 7. Backups and restore

`deploy/backup.sh` (also `make prod-backup`) does the following:
1. `pg_dump -Fc` of the whole database: tenders, users, workspaces, billing, Copilot chunks
   and vectors.
2. `tar.gz` of the media volume (uploaded PDFs).
3. Verification: `pg_restore --list` must read the dump and find data for `tender`,
   `auth_user`, `organization` and `django_migrations`; `tar -t` must read the archive; SHA-256
   sums are written alongside.
4. Off-site copy with the `rclone/rclone` container (nothing to install on the host), followed
   by `rclone check`, which reads the copy back.
5. Retention: `KEEP_DAYS` (7) locally and `REMOTE_KEEP_DAYS` (30) off-site.
6. A ping to `BACKUP_PING_URL` on success, or to `…/fail` on failure.

Off-site storage is any S3-compatible bucket, configured purely through `RCLONE_CONFIG_*`
variables in `.env` (the example uses Cloudflare R2). Create the bucket, plus an API token
limited to that bucket with read and write access, then:

```bash
sudo mkdir -p /var/backups/tenderlens && sudo chown $USER /var/backups/tenderlens
crontab -e
# 03:30 IST nightly, after the 01:00–03:16 full crawls
30 3 * * * cd /opt/tenderlens && ./deploy/backup.sh >> /var/log/tenderlens-backup.log 2>&1
```

For a healthchecks.io check (free), use a 1-day period and 2 hours of grace. If a night is
missed, it emails you.

**Restore drill: monthly, and after any change to backups.**

```bash
make restore-check      # newest local dump → scratch DB restore_check_<stamp> → row counts → DROP
# or a specific (e.g. off-site) copy:
docker run --rm -v "$PWD/backups:/backups" --env-file <(grep ^RCLONE_ .env) \
  rclone/rclone:1.71 copy offsite:tenderlens-backups/<stamp> /backups
./deploy/restore.sh check backups/tenderlens-<stamp>.dump
```

The procedure was tested on 2026-10-06 against the dev Postgres (2,686 tenders, 58 MB dump).
`backup.sh` dumped, verified and pushed the dump to an rclone remote, with `rclone check`
reporting 0 differences. `restore.sh check` then verified the checksums, restored the copy
fetched from the remote into a scratch database (tenders 2686, migrations 33) and dropped it.
The whole run took about 9 s.

Two details of the restore matter. The materialized views are restored without data and then
refreshed, because `pg_restore` runs with an empty `search_path` and cannot refresh them
itself. And `--no-owner` is used, so the objects belong to the connecting role.

**Live restore (disaster recovery).**
`./deploy/restore.sh live backups/tenderlens-<stamp>.dump backups/media-<stamp>.tar.gz --yes`
stops the app containers, restores into a new database and swaps it in by renaming. The old
database is kept as `tenderlens_before_<stamp>`. It then unpacks the media and starts
everything again. On a brand-new server, first run `make prod-up` (which creates an empty
database), then run the live restore.

## 8. Monitoring and logs

- **Uptime:** an external monitor (UptimeRobot or healthchecks.io, both free) on
  `https://<domain>/health` every 5 minutes. `/health` checks the database.
- **Container health:** every service has a healthcheck (`make prod-ps` shows them).
  `restart: unless-stopped` restarts crashed processes, but not merely unhealthy ones, so
  watch `docker ps --filter health=unhealthy`.
- **Logs:** `make prod-logs S="web worker"`. Caddy writes JSON access logs, gunicorn writes
  access lines with durations, and Postgres logs statements slower than 2 s. Logs rotate at
  5 × 20 MB per container.
- **Crawl freshness:** `/coverage` in the app, and `/admin/` → crawl runs.
- **Resources:** `docker stats --no-stream`, and `df -h` (the Postgres volume and `backups/`
  are what grow).
- **Certificates:** Caddy renews them by itself. Let's Encrypt emails `ACME_EMAIL` if renewal
  keeps failing. Keep the `caddy_data` volume, or you will hit Let's Encrypt's rate limits on
  re-issue.

## 9. Monthly cost (INR)

Exchange rates are assumptions: ₹105/€ and ₹88/$. "Verified" means the figure was read on the
linked page on 2026-10-06.

| Item | No LLM | CPU LLM | Basis |
|---|---|---|---|
| VPS | Hetzner CX33, about €6 → **≈ ₹650** | Hetzner CX43, about €11 → **≈ ₹1,150** | Specs **verified** (CX33 4 vCPU/8 GB/80 GB, CX43 8 vCPU/16 GB/160 GB) at https://www.hetzner.com/cloud/cost-optimized/. The euro prices are an **assumption**, because the page renders them client-side; check them in the Hetzner console. |
| Public IPv4 | ≈ ₹55 | ≈ ₹55 | **Assumption** (about €0.50/month at Hetzner) |
| Off-site backups (R2) | **₹0** | **₹0** | **Verified:** $0.015/GB-month with 10 GB-month free and free egress (https://developers.cloudflare.com/r2/pricing/). 30 nightly dumps of about 60 MB plus media come to roughly 2–5 GB. |
| Domain (.in) | ≈ ₹70 | ≈ ₹70 | **Assumption:** about ₹800/year at Indian registrars |
| Transactional email | ₹0 | ₹0 | **Assumption:** Brevo's free tier, 300 emails/day |
| Monitoring | ₹0 | ₹0 | **Assumption:** the free tiers of healthchecks.io and UptimeRobot |
| **Fixed total** | **≈ ₹775/month** | **≈ ₹1,275/month** | |
| Razorpay | 2% + 18% GST on the fee (= 2.36%) per payment, plus 0.9% on card recurring (Subscriptions) | same | **Verified** at https://razorpay.com/pricing/: no setup fee and no annual fee. For example, a ₹2,000 payment costs about ₹47 in fees, or about ₹65 if it is a card subscription. |
| GPU option | A separate GPU server (e.g. a Hetzner GEX44 with an RTX 4000 Ada) for **≈ ₹20,000/month** plus a setup fee | | **Assumption.** Worth it only once CPU answer latency costs you customers. |

## 10. Measured on the dev host (2026-10-06)

Smoke test: `deploy/compose.prod.yml` was brought up as a separate project
(`-p tlprod`, with its own volumes and Caddy on `127.0.0.1:18443`) using `SITE_ADDRESS=localhost`.
That address makes Caddy issue the certificate from its internal CA.

- **Images:** `tenderlens` (app) is 3.42 GB: the venv is 1.64 GB, of which torch CPU is
  0.77 GB; the e5 model is 0.49 GB; OCR packages are 0.27 GB. `tenderlens-proxy` is 84 MB.
  The first build took about 15 minutes on a slow link. Rebuilds after a code change take
  about 30 s, because the dependency, model and apt layers are cached.
- **Start-up:** `up --wait` brought everything up healthy in 60 s: migrate ran once, then
  web, both workers, beat and Caddy started. `check --deploy` ran with the production
  settings. The security checks were clean; the three drf-spectacular schema-naming warnings
  seen then were fixed in the integration stage, and `migrate` now fails on any warning.
- **Requests through Caddy:** `/health`, `/`, `/pricing` (SPA fallback), `/api/tenders`,
  `/api/sources`, `/api/billing/plans` and `/api/config` all returned 200.
  - `/` returned `Cache-Control: no-cache` and every security header.
  - `/assets/*.js` returned `immutable` and was compressed with zstd.
  - HTTP was redirected to HTTPS with a 308.
- **Copilot end to end:** a PDF upload was processed by the `default` worker in about 5 s,
  with the baked embedding model and no network. `POST /api/copilot/ask` streamed
  `text/event-stream` over HTTP/2 with no `Content-Encoding` and `X-Accel-Buffering: no`,
  and returned a cited answer. The answer was extractive: the dev host's llama.cpp listens on
  127.0.0.1 only, so the test stack could not reach it through `host-gateway`, and the
  fallback did its job. Anonymous requests got 403.
- **Memory** (`docker stats`, after one upload and one question):

| Service | Memory | Limit |
|---|---|---|
| web (2 gunicorn workers, one with the model loaded) | 900 MiB | 2 GiB |
| worker (default, model loaded) | 880 MiB | 2 GiB |
| worker-crawl (24 threads, crawling) | 180 MiB | 1 GiB |
| beat | 120 MiB | 384 MiB |
| postgres (empty DB) | 100 MiB | 2 GiB |
| caddy | 60 MiB | 256 MiB |
| redis | 10 MiB | 300 MiB |

  That is about 2.3 GB at idle. With both gunicorn workers warm, it is about 2.8 GB, before
  the Postgres page cache. Add about 3.3 GB for the CPU LLM.
