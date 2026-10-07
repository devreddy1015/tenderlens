# TenderLens: things to be able to explain

Short answers to the questions the build plan says interviewers will ask, plus the
non-obvious things that came up while building it. Every claim here is backed by a test
or by a command you can run live.

## "Walk me through the upsert."

```sql
INSERT INTO tender (...) VALUES (...)
ON CONFLICT (source, source_tender_id) DO UPDATE SET ...
WHERE tender.content_hash <> EXCLUDED.content_hash
  AND tender.fetched_at  <= EXCLUDED.fetched_at
RETURNING id, (xmax = 0) AS inserted;
```

* `ON CONFLICT` on the natural key: re-crawling can never create a second row.
* `WHERE content_hash <>`: unchanged data writes nothing (no dead tuples, no needless
  re-index). If no row comes back, a second statement only bumps `last_seen`.
* `fetched_at <=`: replaying an *older* stored page (a backfill) can't overwrite newer data.
* `xmax = 0`: true only for a row this statement inserted, so one round-trip tells
  new from updated.
* **Why not hash the HTML?** Every GePNIC page has a visitor counter and session tokens, so
  the HTML differs on every fetch. The hash covers the validated business fields.
* Tests: `tests/test_loader.py` (twice → same rows; older page doesn't win; first_seen kept).

## "Why store raw pages before parsing?"

Parsing bugs and new fields are inevitable. With raw HTML stored, `manage.py backfill FROM
TO` re-parses without touching the portal. `test_backfill_after_parser_fix_updates_rows`
shows it: a parser bug writes a bad value, the parser is fixed, backfill corrects it,
and no HTTP request is made. Storage is the cost: lz4 TOAST compression stores HTML at
about a third of its size (see the README numbers), and listing pages are pruned after 7 days.

## "What happens when a crawl fails halfway?"

Three layers, from the inside out:

1. **Fetcher**: 429/5xx/timeouts are retried with exponential backoff + jitter, honouring
   `Retry-After`.
2. **Celery**: `fetch_detail` has `autoretry_for` with backoff, max 5 retries, then a
   `dead_letter` row and the tender is marked `failed`. The run still finishes and is
   flagged `mismatch`.
3. **Worker death**: `acks_late` + `reject_on_worker_lost`, so an in-flight task is
   redelivered. Every step is idempotent, so running it twice is harmless.

**What actually happened when I SIGKILLed the worker mid-crawl** (MP portal, 137 tenders):
42 loaded at the kill and 95 pending. After restart the queue drained: 135 rows,
135 distinct, 0 duplicates. 2 tasks had been in flight. Redis only redelivers an
unacknowledged message after `visibility_timeout`, and those 2 never came back. The
next incremental crawl fetched exactly those 2 (`new=2`, `skipped=134`). The killed run was
closed as `incomplete: 2 tenders never finished`.

The lesson to say out loud: **correctness came from idempotency and from reconciling
against the source on every crawl, not from the broker's delivery guarantee.** I also
lowered `visibility_timeout` from 1 h to 15 min after this: it must be longer than the
longest task (about 8 min), and a task that outlives it runs twice, which is safe here.

**Why counters come from `crawl_item`, not `+= 1`:** a redelivered task would increment
twice. One row per (run, tender) with the final outcome can't double-count.

## "How do you know a crawl was complete?"

Reconciliation. The organisation index says how many tenders each organisation has. The
run compares that claim to the listing rows it parsed, and those to what it accounted for
(new + updated + unchanged + skipped + quarantined + failed). Any gap marks the run
`mismatch` and shows up in `/health`.

## "Tell me about a data-quality problem you found."

Tenders `2026_RMLH_926750_1` (RML Hospital) and `2026_THDC_925930_1` (THDC): the portal's
own detail page says *Published 18-Oct-2026 02:24 AM* / *12-Oct-2026 02:47 AM*, but bid
submission closes on *03-Oct-2026*. The listing says the real dates were 18-Sep and
12-Sep. The pattern: the right day, one month late, stamped with the server's current
time (the pages were fetched at 02:24 and 02:47). That looks like a portal rendering bug,
affecting 2 of 2,549 tenders. **And it was transient:** an hour later the portal served
the right dates. Because quarantined tenders are not in the table, the next incremental
crawl fetched them again, and both loaded without anyone touching anything. Validation (`closes_at ≥ published_at`) quarantined it
with a readable error instead of loading an impossible row. The page is saved as a test
fixture (`fixtures/broken/real_published_after_closing.html`). I did not auto-"fix" it
from the listing date. Silent repair hides source problems; quarantine keeps them visible.

## "Entity resolution: how good is it?"

* Normalise → block (same state, same first token) → RapidFuzz `token_set_ratio`; ≥ 90
  merge, 80–90 review list.
* **What I found:** on real GePNIC names, plain `token_set_ratio` merges *siblings*. It
  scores the shared tokens and ignores what differs, so "DDA ‖ CE-Dwarka Zone" and
  "DDA ‖ CE-North Zone" look like the same buyer. Before the guards, the live database had
  merged six different DDA zones into one entity (visible in the UI's buyer panel).
* **Fix:** (1) score organisation and department separately and take the minimum;
  (2) a token on one side only, with no close misspelling on the other side, caps the
  score in the review band. "Merrut"/"Meerut" still merges; "Dwarka"/"North" doesn't.
* **Measured:** on 120 hand-labelled real pairs (every one a pair of distinct buyers),
  plain `token_set_ratio` made 40 false merges; with the guards, 0. On 60 synthetic
  variants of real names (abbreviations, punctuation, upper case, "Office of the",
  typos), recall is 95%. The 3 misses are typos in the *first* word, which blocking never
  compares. That's the trade-off of first-token blocking, and it's worth saying so.
* On the live data, the unguarded scorer had made 150 merges during the first crawl. After
  `resolve_buyers --rebuild` with the guards there are 0, and 112 near-pairs sit in the
  review list.
* Run `make er-eval` to reproduce it live.

## "How does search work without Elasticsearch?"

v1 ran Elasticsearch next to Postgres; v2 dropped it (one database, no second index to keep
in sync, ~1 GB less RAM on the VPS). Everything is in `tenders/search.py`:

* `tender.search_vector` is a STORED generated `tsvector` with a GIN index: title at
  weight A (stemmed *and* as written, so exact words still count), tender ID / reference
  number A, buyer C, location and organisation chain D. Every write path keeps it current
  because the database computes it.
* The query is `websearch_to_tsquery` syntax with every word turned into a prefix
  (`constr:*` finds "construction"), ranked with `ts_rank_cd`; an exact tender ID or
  reference number ranks first.
* Typos: when nothing matches, unknown words are corrected against the data's own
  vocabulary with `pg_trgm` + Levenshtein ("toliet" -> "toilet"), returned as `corrected`.
* **Ranking bug I fixed (still covered by a test):** "rod maintenence" first returned a
  classroom repair, because its *buyer* is an "Estate Maintenance Section" and a rare
  word in a boosted buyer field beat every title. Title weight A vs buyer C fixes it; if
  no tender matches every word, the API retries with any word and returns
  `relaxed: true`, and the UI says it is showing partial matches.
* Copilot passages use the same idea plus pgvector: Postgres full-text top 50 and HNSW
  cosine top 50, fused with reciprocal rank fusion (k = 60). Global recall@5 on the
  439-question eval is 92.9% (`manage.py copilot_eval`).
* Alerts reuse the same search, so an alert keyword matches exactly what the search box
  would find.

## "Anything break in deployment?"

(v1, before Caddy replaced nginx in v2; the lessons still apply to any reverse proxy.)
nginx resolves upstream hostnames once, at startup. After `docker compose up` recreated
the web container, it had a new IP and nginx kept sending traffic to the old one: 502s.
Fix: Docker's DNS resolver plus `server web:8000 resolve` in a shared-memory upstream zone
(nginx ≥ 1.27.3). Verified by force-recreating web while nginx kept running.

Second one, found by the end-to-end browser test: nginx forwarded `Host: localhost` without
the port, so Django's CSRF origin check compared `http://localhost:8080` (the browser's
`Origin`) with `http://localhost` and refused every sign-in POST. Unit tests can't see this;
they don't go through nginx. Fix: `proxy_set_header Host $http_host`.

## "How did you use AI tools, and how did you verify the output?"

Answer this honestly in your own words. Things you can point to: every behaviour above
has a test; the crawler ran against the live portal; the crash was a real SIGKILL; the
search and entity-resolution fixes came from looking at real outputs, not from assumptions.
Read the code until you can explain every file without notes.
