COMPOSE ?= docker compose
SOURCE ?= central
MODE ?= incremental
MANAGE = $(COMPOSE) exec web python manage.py

.PHONY: up down logs ps test lint fmt crawl crawl-sync backfill migrate er-eval reindex frontend backup

up:            ## build and start the whole stack (postgres, redis, elasticsearch, web, worker, beat, nginx)
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100 web worker beat

ps:
	$(COMPOSE) ps

test:          ## run the test suite against the compose postgres/redis (start them with `make up`)
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

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

reindex:
	$(MANAGE) es_setup --recreate --reindex

backup:
	./deploy/backup.sh
