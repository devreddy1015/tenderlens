COMPOSE ?= docker compose
SOURCE ?= central
MODE ?= incremental
MANAGE = $(COMPOSE) exec web python manage.py

.PHONY: up down logs ps test lint fmt crawl crawl-sync backfill migrate er-eval frontend admin

up:            ## build and start the dev stack (postgres, redis, web, workers, beat, caddy proxy)
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100 web worker beat

ps:
	$(COMPOSE) ps

test:          ## run the test suite against the compose postgres/redis (`docker compose up -d postgres redis`)
	uv run --frozen pytest

lint:
	uv run --frozen ruff check .
	uv run --frozen ruff format --check .
	uv run --frozen python manage.py makemigrations --check --dry-run

fmt:
	uv run ruff check --fix .
	uv run ruff format .

crawl:         ## queue a crawl on the Celery workers: make crawl SOURCE=central MODE=full
	$(MANAGE) crawl --source $(SOURCE) --mode $(MODE)

crawl-sync:    ## crawl in the foreground, no Celery
	$(MANAGE) crawl --source $(SOURCE) --mode $(MODE) --sync

backfill:      ## re-parse stored pages: make backfill FROM=2026-10-01 TO=2026-10-02
	$(MANAGE) backfill $(FROM) $(TO)

migrate:
	$(MANAGE) migrate

er-eval:       ## entity-resolution precision on the hand-labelled pairs
	$(MANAGE) er_eval data/er_labels.csv data/er_synthetic.csv

admin:         ## create a Django admin user
	$(MANAGE) createsuperuser

# --- Production (one VPS; runbook: docs/DEPLOY.md) -----------------------------------------
PROD = docker compose -f deploy/compose.prod.yml --env-file .env
PROD_APP = web worker worker-crawl beat

.PHONY: prod-config prod-check prod-build prod-up prod-deploy prod-ps prod-logs prod-shell \
	prod-backup restore-check prod-rollback

prod-config:   ## print the resolved production compose file (catches .env typos)
	$(PROD) config

prod-check:    ## Django's production checks against .env, inside the app image
	$(PROD) run --rm --no-deps -e MIGRATE_ON_START=false web python manage.py check --deploy

prod-build:    ## build the app and proxy images, tagged with the git commit too
	$(PROD) build
	docker tag tenderlens:latest tenderlens:$$(git rev-parse --short HEAD)
	docker tag tenderlens-proxy:latest tenderlens-proxy:$$(git rev-parse --short HEAD)

prod-up:       ## start or update the stack; migrations run once, then the rest waits healthy
	$(PROD) up -d --wait

prod-deploy:   ## pull the code, back up, rebuild, roll out (docs/DEPLOY.md "Upgrades")
	git pull --ff-only
	./deploy/backup.sh
	$(MAKE) prod-build prod-up

prod-rollback: ## run an earlier build: make prod-rollback TAG=<git short sha>
	APP_IMAGE=tenderlens:$(TAG) PROXY_IMAGE=tenderlens-proxy:$(TAG) $(PROD) up -d --no-build --wait

prod-ps:
	$(PROD) ps

prod-logs:     ## make prod-logs S="web worker"
	$(PROD) logs -f --tail=200 $(S)

prod-shell:    ## Django shell in the running web container
	$(PROD) exec web python manage.py shell

prod-backup:   ## dump + media archive, verified, copied off-site (deploy/backup.sh)
	./deploy/backup.sh

restore-check: ## restore drill: newest local dump into a scratch database, then drop it
	./deploy/restore.sh check $$(ls -t $${BACKUP_DIR:-backups}/tenderlens-*.dump | head -1)
