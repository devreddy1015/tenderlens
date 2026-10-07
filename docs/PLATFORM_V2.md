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
| Fine-tuning kit lives in `llm/` (own `pyproject.toml`, not installed in the web image; since 2026-10-08 kept off GitHub, on the founder's disk as `../tenderlens-llm`): dataset builder → QLoRA (fits an 8 GB RTX 4060) → GGUF export → eval. | Keeps torch-CUDA out of the server image; training runs on the founder's laptop. |
| Multi-tenant SaaS: `workspaces` (organisation, members, company profile, bid pipeline, API keys) and `billing` (plans, quotas, Razorpay subscriptions). | "Provide everything to the client". |
| Production = one VPS with docker compose + Caddy (auto-HTTPS) + nightly `pg_dump` off-site. Until that server exists, the free Vercel + Neon deployment stays live (`vercel.json`, `.github/workflows/crawl.yml`, `docs/DEPLOY.md` "Free hosting on Vercel"): search, alerts, workspaces and billing work there; the Copilot answers extractively (no LLM) and cannot process uploads (no worker). | A proper database without free-tier size hacks, without taking the public site down meanwhile. |

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
| `llm/` (standalone, not on GitHub) | fine-tuning kit, serving config, LLM eval | not a Django app; a link to `../tenderlens-llm` |
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

## 5. Beating the incumbents (added 2026-10-06)

The founder named the competitors to beat: **TenderDetail** (tenderdetail.com) and **TenderKart** (tenderkart.in).
TenderDetail, read on 2026-10-06, claims 2,03,426+ live Indian tenders, 96,56,053+ tender results,
12,120+ authorities and 1,00,000+ businesses. It sells three tiers (Standard, Premium, Enterprise)
with **no published prices** (sales-led, phone and WhatsApp), and keeps every AI feature (short summary,
competitive bid analysis, bid predictor, probable bidders, missing opportunities) for the top tiers.
It also sells bid consultancy, digital signatures and MSME loans. It shows no API, no data-freshness
information and no source citations. TenderKart blocks automated reading; its offer is not yet known.

We do not out-claim their volume on day one. We win on what they cannot easily copy:

| They do | We do |
|---|---|
| Prices hidden behind a sales call | Published INR prices, self-serve checkout, a useful free plan forever |
| AI only on the top tiers | Bid Brief, cited Q&A and Eligibility on **every** plan (quota-limited on free) |
| "AI summary" with no evidence | Every extracted fact carries a page citation and a link to the source portal; ungrounded answers are refused |
| Eligibility assessed by a consultant | Automatic eligibility verdict against the company profile, in seconds |
| Unknown freshness | `/coverage` shows every source with its last successful crawl |
| Due-date calendar inside their app | Pipeline deadlines as an **iCal feed** the team subscribes to in Google Calendar / Outlook |
| "Missing opportunities" (top tier) | **Recommended for you** on every plan, from the company profile |
| Tender results and bidder insights (their strongest asset) | Award data from public GePNIC result pages where reachable without a CAPTCHA, linked to the tender (OCDS awards) |
| No API | REST API keys and OCDS exports |

### Contract additions

- `GET /api/recommendations?page=` (login; owner **saas**) → paginated tenders like `/api/tenders`, each with
  `reasons: [str]` (e.g. "Sector: Roads", "State: Chhattisgarh", "Within your turnover limit"). Open tenders only;
  matches the active organisation's `states`, `sectors` and, when the tender's estimated value is known,
  excludes tenders whose value exceeds what the company's turnover plausibly qualifies for
  (default rule: value ≤ 3 × annual_turnover_inr; document it). Excludes tenders already in the pipeline.
  Empty profile → `{"results": [], "profile_incomplete": true}`.
- `GET /api/pipeline/calendar.ics?token=<token>` (owner **saas**): an iCal feed of the organisation's tracked,
  not-yet-submitted tenders (bid submission end and pre-bid meeting as events, with the tender link).
  Authenticated by an unguessable per-organisation token, not the session, so calendar apps can poll it.
  `GET /api/workspace` gains `calendar_url`; `POST /api/workspace/calendar-token` rotates it (owner/admin).
- Awards (owner **sources**, only if the data is publicly reachable without a CAPTCHA; otherwise document why):
  `Award` (tender FK, bidder name, normalised bidder key, amount_inr, award_date, source_url) and
  `GET /api/tenders/{id}` gains `awards: [{bidder, amount_inr, award_date}]`; `GET /api/bidders?q=` and
  `GET /api/bidders/{key}` → `{name, wins, total_value_inr, buyers: [...], sectors: [...], recent: [...]}`.
  The OCDS export includes `awards` when present.
- Frontend (owner of the next frontend pass): a "Recommended for you" section on Home/Explore for signed-in
  users, the calendar subscribe link on Pipeline and Workspace, awards and bidder pages when the API has them,
  and an installable PWA (manifest + icons) so phones can add TenderLens to the home screen.

## 6. Status (2026-10-06)

Every stage of this spec is built and verified; nothing is committed yet (the commit plan
groups the work into reviewable commits).

| Stage | Done | Measured |
|---|---|---|
| Foundation | Postgres search replaces Elasticsearch (`tenders/search.py`, generated `tsvector` + GIN, `pg_trgm` typo correction); `workspaces`, `billing` (plans, `Usage`, entitlements) scaffolding | search tests green; ES containers no longer needed |
| LLM kit (`llm/`) | Model choice, llama.cpp serving, prompt, dataset builder, QLoRA + GGUF export scripts, LLM eval | Qwen3.5-4B GGUF serving on CPU at ~37–80 s per answer |
| Sources | 35 GePNIC portals behind an adapter interface, per-portal staggered beat schedule, `/api/sources` with `last_success` | integration run: 35/35 portals succeeded, 548 listing + 478 detail pages, 472 new + 6 updated tenders, 0 quarantined, 0 dead letters, 0 organisation count mismatches |
| Copilot | Upload, OCR, chunking with tender context, e5 embeddings, hybrid retrieval (RRF), streaming LLM answers with grounding, extractive fallback, Bid Brief, eligibility | recall@5 93.8% scoped / 92.9% global (439 questions); brief 309/330 fields; live answer 37 s, cited and grounded; LLM down → extractive |
| SaaS | Workspaces, roles, invites, seats, pipeline + reminders, iCal feed (with pre-bid meetings), recommendations, API keys, CSV, OCDS 1.1, Razorpay subscriptions + webhook | recommendations 53 ms over HTTP on 3,158 tenders; every quota answers 402 |
| Deploy | Caddy + gunicorn (gthread) prod compose, one-shot migrate with `check --deploy` (fails on any warning), backups + restore drill, CI | image 3.42 GB; full prod stack healthy in 60 s; est. ₹775/month (₹1,275 with the CPU LLM) |
| Frontend | All of the above in the UI, §5 features, PWA, 375 px layouts | 68 Vitest tests, 106 kB (33 kB gzip) main bundle |
| Follow-ups | Global Copilot recall 41% → 93%, `Tender.prebid_meeting` (1,132 tenders have one), Razorpay supersede-cancel, alerts on Postgres search | |
| Integration | Schema warnings fixed, prebid backfill, live bounded crawl of all portals, HTTP smoke on real data, headless screenshots at 375 px and 1280 px, docs | 437 backend + 68 frontend tests green; 4 mobile layout bugs and 1 API bug (alert creation 500 when SMTP is down) fixed |

**Known gaps**

* **Award and bidder data**: every public results page (GePNIC "Results of Tenders",
  "Tenders Status", CPPP results) is CAPTCHA-gated, and we never bypass a CAPTCHA. Next
  step: a data-sharing request to NIC and GeM (template and precedents in
  `docs/SOURCE_NOTES.md`). Until then there is no `Award` model and no `/api/bidders`.
* **GeM and CPPP** are not crawled for the same reason; same route.
* **Fine-tuning has not been run**: the host's NVIDIA driver is broken, so the QLoRA kit is
  untested on a GPU and the default model is the stock Qwen3.5-4B.
* **No full crawl of the 30 new portals yet**: the integration run was deliberately bounded
  (25 organisations and 15 detail pages per portal). The first full crawls (≈ 45,000 detail
  pages) should run on the VPS with the `crawl` worker's thread pool. The `central` index
  page is slow (it timed out 4 × 30 s once, then loaded); watch it and raise
  `CRAWLER_TIMEOUT` if it keeps failing.
* **Dev containers still run the pre-v2 images** (nginx, Elasticsearch, old web image).
  Rebuild with `make up` (or the `docker:27-cli compose` workaround in the README) and then
  remove the Elasticsearch container and volume.
* Cross-portal duplicates: 0 found on 3,158 tenders from 34 portals, so the
  link-without-merge rule in `SOURCE_NOTES.md` stays planned, not built. Re-run the query
  after the first full crawls.
* Live restore into a production stack (`restore.sh live`) and a real LLM answer through the
  production compose were not exercised; do both on the VPS before launch.

**Next steps (in order)**: rebuild the dev stack on the v2 images; provision the VPS and run
the first full crawls; register an OCDS prefix and the Razorpay plans and webhook; send the
NIC/GeM data-sharing requests; fix the GPU driver and run the fine-tuning kit against
the kit's eval_llm.py; then launch the free plan publicly.
