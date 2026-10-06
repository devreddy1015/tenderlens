# TenderLens Platform v2: build spec

Branch `platform-v2`. This file is the contract every builder follows. It turns TenderLens
from a one-portal crawler demo into a product a paying contractor can use end to end:
**find** every relevant Indian public tender, **understand** its documents in minutes, and
**manage** the bid with a team. DocIntel is folded in as the "Copilot", running on our own
self-hosted LLM: no paid LLM API anywhere in the request path.

## 1. Decisions (developer + CFO)

| Decision | Why |
|---|---|
| One Django monolith (DRF), one Postgres. DocIntel's FastAPI service is ported into a Django app `copilot`. | One deploy, one auth/session, one admin, one backup. |
| **Drop Elasticsearch.** Tender search = Postgres full-text (`tsvector` generated column + GIN, `websearch_to_tsquery`, prefix `:*`) + `pg_trgm` for typos; doc chunks = Postgres FTS + pgvector HNSW, fused with RRF. | ES needs ≥1 GB RAM per node and a second index to keep in sync. Postgres already answers the fallback path; at our scale (≤ millions of rows) it is enough. Saves a server tier. |
| Keep Celery + Redis. | Crawl pipeline, crash-safety story and tests already rely on it; Redis is ~50 MB. |
| LLM = any **OpenAI-compatible** endpoint (`LLM_BASE_URL`), default a llama.cpp server running an Apache-2.0 open-weight model (Qwen3 family) as GGUF. Ollama and vLLM work unchanged. | Zero per-token cost; swap CPU ↔ GPU ↔ fine-tuned model by changing two env vars. |
| Answers are grounded or refused: retrieval → LLM with numbered passages → post-check that every number/date appears in the cited passage (DocIntel's `grounding.py`) → otherwise refusal. When the LLM is down, fall back to **extractive** answers (best passage sentences) rather than failing. | Trust is the product; a wrong EMD amount costs a customer a bid. |
| **Bid Brief** = deterministic rule-based extraction (EMD, fee, dates, turnover, experience, penalties, documents required…) with page citations; no LLM needed. | Cheapest possible feature with the most value; works on CPU in milliseconds. |
| Fine-tuning kit lives in `llm/` (own `pyproject.toml`, not installed in the web image): dataset builder → QLoRA (fits an 8 GB RTX 4060) → GGUF export → eval. | Keeps torch-CUDA out of the server image; training runs on the founder's laptop. |
| Multi-tenant SaaS: `workspaces` (organisation, members, company profile, bid pipeline, API keys) and `billing` (plans, quotas, Razorpay subscriptions). | "Provide everything to the client". |
| Production = one VPS with docker compose + Caddy (auto-HTTPS) + nightly `pg_dump` off-site. Vercel/Neon free-tier workarounds are removed. | A proper database without free-tier size hacks. |

## 2. Apps and ownership

| App / dir | Owns | Notes |
|---|---|---|
| `ingest/` | crawling, source adapters, pipeline, loader, validation | Adapter interface so non-GePNIC sources (GeM, CPPP e-publish) fit. |
| `tenders/` | Tender, buyers, entity resolution, sectors, **Postgres search** (`tenders/search.py`) | |
| `api/` | public tender endpoints, `/health`, `/api/config`, URL root `api/urls.py` | |
| `accounts/` | Google sign-in, sessions | unchanged |
| `alerts/` | email digests | |
| `feedback/` | feedback form | the "private tenders waitlist" goes away |
| `copilot/` (new) | documents, chunks, embeddings, hybrid retrieval, LLM client, grounding, bid brief, eligibility | port of `../docintel` |
| `workspaces/` (new) | Organization, Membership, Invite, BidTrack (pipeline), ApiKey, exports (CSV, OCDS) | |
| `billing/` (new) | plans, Usage, Subscription, Razorpay checkout + webhook, entitlements | |
| `llm/` (new, standalone) | fine-tuning kit, serving config, LLM eval | not a Django app |
| `frontend/` | React 19 + TS + Tailwind 4 + TanStack Query | |
| `deploy/` | Dockerfile, compose (dev + prod), Caddy, backups | |

### Shared interfaces (created in the foundation stage; other stages build on them)

```python
# workspaces/models.py
class Organization(models.Model):
    name, slug (unique)
    plan_code = CharField(default="free")          # key into billing.plans.PLANS
    # company profile, used by eligibility checks and alert defaults
    annual_turnover_inr = Decimal(null)             # average of last 3 financial years
    largest_similar_work_inr = Decimal(null)
    years_in_business = PositiveSmallInteger(null)
    states = JSONField(list)                        # where they work
    sectors = JSONField(list)                       # tenders.sectors slugs
    certifications = JSONField(list)                # "MSE", "Startup (DPIIT)", "ISO 9001", "Class-A contractor", ...
    gstin = CharField(blank)
    created_at
class Membership(models.Model):  user FK, organization FK, role in {owner, admin, member}; unique(user, organization)

# workspaces/services.py
def get_active_org(user) -> Organization       # creates a personal org (owner) on first use
def require_role(user, org, *roles) -> Membership   # raises PermissionDenied

# billing/plans.py
PLANS: dict[str, Plan]   # frozen dataclass: code, name, price_inr_month, price_inr_year, limits: dict, features: list[str]
LIMIT_KEYS = ("alerts", "questions_per_month", "documents_per_month", "seats", "export", "api")
# limit value: int, None = unlimited, 0/False = not included

# billing/models.py
class Usage(models.Model): organization FK, key, period (CharField "YYYY-MM"), count; unique(organization, key, period)

# billing/entitlements.py
class QuotaExceeded(APIException): status_code = 402; default_code = "quota_exceeded"
def get_plan(org) -> Plan
def limit(org, key)                      # int | None | bool
def used(org, key) -> int                # this month
def consume(org, key, n=1) -> None       # atomic (select_for_update or UPDATE ... RETURNING); raises QuotaExceeded
def require_feature(org, key) -> None    # for boolean limits (export, api); raises QuotaExceeded
```

## 3. API contract (frontend and backend both follow this exactly)

All JSON. Session auth (+ CSRF) for the browser; `Authorization: Api-Key <key>` for API
customers (plan feature `api`). Errors: DRF default shape; quota errors are HTTP 402
`{"detail": "...", "code": "quota_exceeded", "limit": <key>}`.

### Tenders (existing, unchanged shapes)
`GET /api/tenders` (+ `search_backend` is always `"postgres"`), `GET /api/tenders/{id}`,
`GET /api/tenders/{id}/similar`, `GET /api/buyers/{id}`, `GET /api/stats`, `GET /api/sectors`,
`GET /api/map`, `GET /api/config`.

New: `GET /api/sources` → `[{key, name, kind: "gepnic"|"gem"|"cppp", state|null, url, open_tenders, last_run: {status, finished, new, updated}|null, enabled}]`.

### Copilot `/api/copilot/` (login required)
- `POST documents` multipart `file` (PDF ≤ 25 MB), optional `tender` (Tender pk) → 201 `Document`.
  Counts `documents_per_month`. Processing runs in Celery (eager in tests).
- `GET documents?tender=<pk>` → `[Document]` (only the caller's organisation's documents).
- `GET documents/{id}`, `DELETE documents/{id}`.
- `Document` = `{id, filename, pages, chunks, status: "processing"|"ready"|"failed", error, ocr_pages, tender: {id, title, source_tender_id}|null, created_at}`.
- `GET documents/{id}/brief` and `GET brief?tender=<pk>` (all ready docs of that tender) →
  `{fields: [{key, label, value, page, quote, document_id, filename}], missing: [key], generated_at}`.
  Keys: `emd`, `tender_fee`, `estimated_value`, `bid_submission_end`, `bid_opening`, `prebid_meeting`,
  `completion_period`, `bid_validity`, `min_turnover`, `similar_work`, `performance_security`,
  `liquidated_damages`, `mse_exemption`, `documents_required` (value = list of strings).
- `POST ask` `{question, tender?, document_ids?}` → **SSE** (`text/event-stream`, each event one line
  `data: <json>` + blank line):
  `{"type":"retrieval","passages":[{n, document_id, filename, page, text}]}`,
  `{"type":"delta","text":"..."}` (draft, may be replaced),
  `{"type":"final","status":"answered"|"abstained"|"rejected"|"no_context"|"error","answer","citations":[{n, document_id, filename, page, quote}],"grounding":{"unsupported":[...]}|null,"model","mode":"llm"|"extractive","latency_ms"}`.
  `?stream=false` returns the final object as JSON. Counts `questions_per_month`.
- `GET eligibility?tender=<pk>` (or `?document=<id>`) → `{verdict: "eligible"|"not_eligible"|"unknown", checks: [{key, requirement, required, yours, status: "pass"|"fail"|"unknown", source: {document_id, filename, page}|null}]}` comparing the brief against the active organisation's profile.
- `GET status` → `{llm: {available, model}, embedding_model, documents}`.

### Workspace `/api/workspace` (login required)
- `GET /api/workspace` → `{id, name, slug, role, plan: Plan, usage: {key: used}, profile: {annual_turnover_inr, largest_similar_work_inr, years_in_business, states, sectors, certifications, gstin}}`.
- `PATCH /api/workspace` `{name?, profile fields?}` (owner/admin).
- `GET /api/workspace/members` → `[{id, email, name, role, joined_at}]`; `DELETE /api/workspace/members/{id}`.
- `POST /api/workspace/invites` `{email, role}` (seats limit) → emails a link `SITE_URL/invite/<token>`; `POST /api/workspace/invites/{token}/accept`.
- `GET|POST|DELETE /api/workspace/api-keys` (feature `api`); the key is shown once on create.

### Pipeline `/api/pipeline` (login required, scoped to active org)
- `GET /api/pipeline?status=` → `[BidTrack]`; `POST /api/pipeline` `{tender, status?}` (idempotent per org+tender);
  `PATCH /api/pipeline/{id}` `{status?, notes?, bid_amount_inr?, owner?}`; `DELETE /api/pipeline/{id}`.
- `BidTrack` = `{id, tender: Tender, status: "watching"|"preparing"|"submitted"|"won"|"lost"|"dropped", notes, bid_amount_inr, owner: {id, email}|null, created_at, updated_at}`.
- `GET /api/pipeline/summary` → `{by_status: {status: count}, closing_soon: [BidTrack], value_inr_in_play}`.
- Daily Celery job emails owners about tracked tenders closing within 3 days (not yet submitted).

### Exports
- `GET /api/export/tenders.csv?<tender search filters>` (feature `export`, max 10,000 rows).
- `GET /api/ocds/releases?<tender search filters>&page=` → OCDS 1.1 release package (public, paginated), so the data is interoperable with international tooling (UK Contracts Finder, EU TED, Open Contracting).

### Billing `/api/billing/`
- `GET plans` → `[Plan]` with `{code, name, price_inr_month, price_inr_year, limits, features}` (public).
- `GET subscription` → `{plan, status, interval, current_period_end, provider}` (login).
- `POST checkout` `{plan, interval: "month"|"year"}` → Razorpay: `{provider: "razorpay", key_id, subscription_id}` (the browser opens Razorpay Checkout); with `BILLING_PROVIDER=fake` (dev/tests) the plan is activated immediately: `{provider: "fake", activated: true}`.
- `POST webhook` → verifies `X-Razorpay-Signature` (HMAC-SHA256 of the raw body with `RAZORPAY_WEBHOOK_SECRET`), idempotent per event id; `subscription.activated|charged` → plan active, `subscription.cancelled|halted|completed` → back to free.
- `POST cancel`.

## 4. House rules for every builder

- Read the code you change first and match its style: short docstrings that explain *why*, ruff
  (`line-length 100`), type hints, tests next to the existing ones in `tests/` (one file per area,
  e.g. `tests/test_copilot.py`). Every endpoint gets tests (happy path, auth, quota/permission, bad input).
- **Do not edit `pyproject.toml` or `uv.lock`** after the foundation stage. Need a package? Say so in
  your final report. (`llm/` has its own pyproject; that one is yours if you own `llm/`.)
- Shared files (`config/settings.py`, `api/urls.py`, `docker-compose.yml`, `frontend/src/main.tsx`):
  only small `Edit`s inside your own marked section; never rewrite the whole file.
- Run Python with `uv run --frozen ...`. Tests need Postgres (pgvector) and Redis from
  `docker compose up -d postgres redis`. Use your **own test database**: prefix commands with
  `TEST_DB_NAME=test_<your-stage> REDIS_URL=redis://localhost:6379/<n>` so parallel builders never
  collide. Run `uv run --frozen ruff check <your files>` and `ruff format <your files>` only.
- Frontend: host `node` is broken (missing `libada.so.3`); run npm in Docker:
  `docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v "$PWD/frontend":/app -w /app node:22-bookworm-slim npm run build`.
- Never commit, push, or touch the `main` branch or the `../docintel` repo (read it, copy from it).
- Network etiquette for crawlers: ≤ 1 request/second per host, honest User-Agent, public pages only,
  never touch or bypass a CAPTCHA.
- Finish with a report: what you built, files touched, test results (exact counts), anything left
  undone or that another stage must wire up.
