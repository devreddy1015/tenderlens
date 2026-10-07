# TenderLens Bid Advisor + Market Intelligence: build spec

Branch `platform-v2`. This file is the contract every builder of this stage follows, like
`docs/PLATFORM_V2.md`, whose house rules (section 4) still apply: read before you change,
match the style, ruff, tests in `tests/`, `uv run --frozen`, your own `TEST_DB_NAME` /
`REDIS_URL` db number, never commit, never bypass a CAPTCHA, honour robots.txt.

Goal: for any tender, tell a contractor **what amount to quote**, how likely that amount is
to win, and why, backed by historical award data from 2000 to today, with receipts
(comparable past contracts and their sources) for every number.

## 1. Decisions (developer + CFO)

| Decision | Why |
|---|---|
| The **price model is gradient-boosted quantile regression (LightGBM), not an LLM**. Target `r = ln(winning price / estimate)`. The LLM (local Qwen) only *explains* numbers the model produced, and a numeric check rejects any sentence whose numbers are not in the model output. | LLMs are poor numeric regressors and give no calibrated uncertainty (the 4B model even expanded "EMD" wrongly without documents). Boosted trees train on this laptop's CPU in minutes, give quantiles, and can be backtested. |
| **Ratio space.** `award / estimate` has no currency and no inflation, so contracts from 2000 and from other countries are comparable. Absolute size enters only as `ln(estimate in 2026 rupees)`. | Makes a 2000-2026 dataset usable honestly. |
| Real rupees = convert to USD at that year's rate, to INR at that year's rate, inflate with India's CPI (World Bank WDI). `intel/prices.py`, done. | One free series for every country; only the size feature depends on it. |
| **Win probability** from the predicted distribution of the lowest competing price: `P(win | b) = sum_k p(k others) * P(L1 of k bids > b)`. With the bidder's cost `c`, recommend `argmax_b (b - c) * P(win | b)`; without it, the bid at a target win probability (default 0.5). | Friedman (1956) / Gates (1967) competitive bidding, with an ML-estimated L1 distribution. |
| **Bidder count** is the strongest driver and unknown at bid time: it is a *target* of its own (Poisson LightGBM), never an input from the future. The ratio model takes `num_bidders` as a feature; the advisor mixes over the predicted count (or the user's guess). | No leakage; "what if 12 bidders turn up" is a slider. |
| **Calibration**: conformalised quantile regression on a time-ordered calibration split, holdout = the most recent period. Baseline B0 (hierarchical empirical-Bayes cell quantiles) ships too; the model card reports both and the better one is activated. | An "80% range" must cover ~80% on data the model never saw. |
| **Receipts**: every advice lists the nearest comparable awards (country, sector, state, size, recency) with links. | Same trust rule as the Copilot: no number without evidence. |
| **Outcome capture is the moat.** Marking a pipeline tender won/lost asks for the L1 amount, the winner and the bidder count; those rows train the next model. `Organization.contribute_outcomes` (default on, clear notice, can be switched off); pooled training only uses ratios, never names, and only after award. | Indian award pages are CAPTCHA-gated; our users see the results. Every customer improves the advice for every customer. |
| Never advise one customer with another customer's *private* data on the same live tender; user rows enter the pooled model only after the tender's closing date. | Competition Act 2002 s.3(3)(d) exposure and customer trust. |
| One new Django app **`intel`**. Model artefacts are files under `data/intel/models/<version>/` with a `ModelVersion` row; rollback = activate an older row. Raw downloads under `data/intel/raw/<source>/` (gitignored) with sha256 + licence per `DatasetImport`. | Same monolith and deploy; auditable, re-runnable imports. |

## 2. Data sources (verified 2026-10-07; details in `docs/SOURCE_NOTES.md` section "Award data")

| Key | Source | Rows / years | Gives | Licence |
|---|---|---|---|---|
| `worldbank_in` | World Bank, India: **STEP procurement plans** (documents API, `docty_exact=Procurement Plan&count_exact=India`, 9,321 docs; each activity has reference no., method, market approach, **Estimated Amount (US$)**, **Actual Amount (US$)**, status, dates) + **contract award notices** (`search.worldbank.org/api/v2/procnotices?notice_type_exact=Contract Award&project_ctry_name=India`, 37,480 notices, 2014-2026: awarded bidder, **every evaluated bidder's opening/evaluated price in INR**, signed price) + **Finances One contract awards** (`DS00005`, 34,973 India rows FY2001+, USD amount, supplier, method, category). Joined on the normalised reference number (`IN-ICAR-18247-GO-RFQ`). | ~20-35k contracts | India-specific estimate, award, all bids, winner, method | World Bank terms of use / CC BY 4.0 (datasets), CC BY 3.0 IGO (documents); attribution |
| `pmgsy` | India Data Portal (ISB) "PMGSY Financial and Physical Report" CSV (127 MB) | ~407k road works, sanctioned 2000-01 onwards | contractor, award date, sanctioned cost (lakh), expenditure, district | ODC-BY (mirror it; host is a dev CKAN) |
| `ted` | EU TED contract award notices CSV 2006-2023 (`data.europa.eu`, `ted-contract-award-notices-<year>.zip`) | millions of lots; estimate filled ~39% | estimate (`AWARD_EST_VALUE_EURO`), award (`AWARD_VALUE_EURO`), `NUMBER_OFFERS`, CPV, winner | CC BY 4.0 / EC reuse notice |
| `peru` | Peru OECE OCDS bulk (OCP registry publication 135, `…/download?name=<year>.jsonl.gz`) | 2003-2026; value 93%, tenderers 92%, awards 79% | estimate, award, number of tenderers | CC BY 4.0 |
| `tenderlens` | Our users' recorded outcomes (pipeline) | grows daily | Indian L1, winner, bidders | ours, per ToS |

**Not used, and why** (do not build adapters for these in this stage):
GeM BidPlus results (public, no CAPTCHA, 3.38M bids with every seller's price since 2018, but
GeM's copyright policy requires written permission for reuse: the founder sends the request in
`docs/DATA_REQUESTS.md` first); CPPP / GePNIC AOC and result pages (CAPTCHA-gated); the Hugging
Face `tenders_aoc` corpus and the CivicDataLab Assam / Himachal OCDS sets (built by solving
CAPTCHAs); GTI GPPD and Opentender (non-commercial licences); Prozorro, ChileCompra, SECOP II
(licence or volume questions; phase 2); `mahatenders.gov.in` (robots.txt disallows all; its
crawler source is now disabled).

## 3. Data model (`intel/models.py`, built)

`DatasetImport`, `HistoricalAward`, `PriceIndex`, `ModelVersion` as in the code. Key points:
`HistoricalAward` is unique on `(source, source_id)`; `ratio` is `award / estimate` only when
both are known and `0.2 <= ratio <= 3`; `bids` is the sorted list of every bid amount (same
currency as the row); `organization` + `shared` mark user-contributed outcomes.

Adapters (`intel/sources/<name>.py`, discovered automatically) subclass `intel.sources.base.Source`,
set `key, name, url, license, kind ("outcomes"|"history"), min_interval_seconds`, decorate with
`@register`, and implement `rows(ctx) -> Iterator[AwardRow]`. They use `ctx.get()` /
`ctx.download()` (rate-limited, retried, cached under `data/intel/raw/<key>/`, sha256 recorded),
`ctx.limit`, `ctx.since`, `ctx.file`. `base.upsert` derives year, ratio, sector (`tenders.sectors.classify`
for English titles; adapters for non-English sources set `sector` themselves, e.g. via
`base.cpv_sector`), buyer/winner keys and real-rupee amounts. Helpers: `parse_amount`, `cpv_sector`.
Commands: `manage.py intel_import <key> [--limit --since --file --refresh]`, `intel_import --list`,
`manage.py intel_prices`.

`workspaces.BidTrack` gains `l1_amount_inr` (Decimal null), `winner_name` (Text blank),
`num_bidders` (PositiveSmallInteger null), `our_rank` (PositiveSmallInteger null).
`workspaces.Organization` gains `contribute_outcomes` (Boolean, default True).

## 4. Model contract (`intel/model.py`, `intel/train.py`)

```python
QUANTILES: tuple[float, ...]   # 0.05, 0.10, ..., 0.95 (19)
MAX_BIDDERS = 30

@dataclass(frozen=True)
class Features:
    estimated_inr_real: float          # > 0
    country: str = "IN"
    state: str = ""
    sector: str = ""
    category: str = ""                 # works | goods | services | consultancy | ""
    method: str = ""
    year: int = <current year>
    buyer_key: str = ""

class Predictor:                       # LightGBM model or the B0 baseline, same interface
    version: str
    card: dict                         # ModelVersion.metrics + data summary
    def ratio_quantiles(self, f: Features, num_bidders: int) -> np.ndarray   # shape (19,), sorted,
                                       # conformal-adjusted quantiles of r = ln(L1 / estimate) for an
                                       # auction with num_bidders bids
    def bidders_pmf(self, f: Features) -> np.ndarray                         # shape (MAX_BIDDERS + 1,),
                                       # P(total bidders = n), n = 0..MAX_BIDDERS, sums to 1, p[0] = 0
def load_active() -> Predictor | None  # cached per process; reloads when the active version changes
```

Training (`manage.py intel_train [--holdout-months 18] [--activate] [--min-rows 200]`): rows with
`ratio` (and `shared=True`, user rows only after the tender closed); time-ordered split train /
calibration / holdout; LightGBM quantile models per tau (sorted to remove crossing), Poisson
LightGBM for bidder count on rows with `num_bidders`; CQR; B0 baseline; metrics on the holdout,
overall and for `country=IN`: pinball loss, MAE of the median in percentage points, 80% coverage
and width, bidder-count MAE; the better of LightGBM vs B0 (by India holdout pinball when India
has >= 200 holdout rows, else overall) is saved and, with `--activate`, activated.
Dependencies to add: `lightgbm` (MIT) to the main dependencies (needs `libgomp1` in the image).

## 5. API contract

JSON, same auth and error shapes as PLATFORM_V2 section 3. New quota key
`bid_advice_per_month` (free 5, pro 100, team 500, enterprise unlimited); repeated what-ifs on
the same tender in the same month count once.

- `GET /api/tenders/{id}/bid-advice?cost_inr=&bidders=&target=0.5` and
  `POST /api/intel/advice {estimated_value_inr, sector, category?, state?, method?, buyer?, bidders?, cost_inr?, target?}`
  (login) → `Advice`:

```json
{
  "tender": {"id": 1, "title": "", "value_inr": 0, "sector": "", "state": "", "category": ""},
  "inputs": {"estimated_value_inr": 0, "sector": "", "category": "", "state": "", "method": "",
             "buyer": "", "bidders": 6, "bidders_source": "user|model", "cost_inr": null, "target": 0.5},
  "model": {"version": "", "kind": "lightgbm|baseline", "trained_at": "", "rows": 0,
            "holdout": {"rows": 0, "mae_pct": 0.0, "coverage_80": 0.0}},
  "prediction": {
    "winning_ratio": {"p10": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0},
    "winning_amount_inr": {"p10": 0, "p25": 0, "p50": 0, "p75": 0, "p90": 0},
    "bidders": {"p10": 0, "p50": 0, "p90": 0}
  },
  "curve": [{"ratio": 0.0, "amount_inr": 0, "p_win": 0.0, "expected_profit_inr": null}],
  "recommendation": {"amount_inr": 0, "ratio": 0.0, "p_win": 0.0, "expected_profit_inr": null,
                     "strategy": "max_expected_profit|target_win_probability", "target_p_win": 0.5},
  "rules": [{"key": "", "severity": "info|warn", "message": "", "source": ""}],
  "comparables": [{"source": "", "title": "", "buyer": "", "state": "", "country": "", "year": 0,
                   "estimated_inr_real": 0, "award_inr_real": 0, "ratio": 0.0, "num_bidders": 0,
                   "winner": "", "url": ""}],
  "confidence": "high|medium|low", "confidence_reasons": [""],
  "disclaimer": ""
}
```

  `ratio` values are `winning price / estimate` (not logs). `curve` spans 41 points over the
  model's 1st-99th percentile range. Never recommend below `cost_inr`. The rules engine
  (`intel/rules.py`, versioned by date and state) adds: MoRTH NH APS tiers (bids >10% below
  estimate, from 2025-04-30), Odisha 15% floor (until 2026-01-03, abolished by Works Dept OM 173),
  abnormally-low-bid scrutiny (DoE OM F.9/4/2020-PPD), MSE L1+15% matching and Make in India 20%
  margin (goods/services), GeM reverse auction above Rs 10 lakh (advice becomes a walk-away floor),
  QCBS for consultancy (L1 logic does not apply: warn). Tender without a known estimate → 422
  `{"code": "no_estimate"}`; no active model → 503 `{"code": "model_unavailable"}`.
- `GET /api/tenders/{id}/bid-advice/explanation?<same params>` → `{"text", "mode": "llm|template", "model", "latency_ms"}`;
  cached per (tender, params, model version); no extra quota.
- `GET /api/intel/comparables?tender=<id>` or `?sector=&state=&country=IN&value_inr=` → `[Comparable]` (login).
- `GET /api/intel/market?sector=&state=&country=IN&category=` (public) →
  `{"rows", "by_year": [{"year", "awards", "median_ratio", "p25_ratio", "p75_ratio", "median_bidders"}], "top_winners": [{"winner", "key", "wins", "total_inr_real", "median_ratio"}]}`.
- `GET /api/intel/coverage` (public) → `{"sources": [{"key", "name", "license", "url", "kind", "rows", "rows_with_ratio", "years": [min, max], "countries": [..], "last_import": {"status", "finished_at", "rows_seen"} | null}], "model": {"version", "kind", "trained_at", "metrics"} | null}`.
- `GET /api/intel/bidders?q=` and `GET /api/intel/bidders/{key}` (login) →
  `{"name", "key", "wins", "bids", "total_inr_real", "median_ratio", "sectors": [..], "states": [..], "buyers": [..], "recent": [Comparable]}`.
- `PATCH /api/pipeline/{id}` also accepts `l1_amount_inr, winner_name, num_bidders, our_rank`, and
  `BidTrack` JSON returns them. Marking `won`/`lost` with `l1_amount_inr` and a known tender value
  upserts `HistoricalAward(source="tenderlens", source_id="<org>:<tender>", organization, shared=org.contribute_outcomes)`.
  `GET/PATCH /api/workspace` gains `contribute_outcomes`.

## 6. Stages

A. Data (parallel): `worldbank_in`; `ted` + `peru`; `pmgsy` + outcome capture + crawler robots.txt gate + `docs/DATA_REQUESTS.md`.
B. Model + advisor + API (parallel): `intel/model.py` + `intel/train.py` + `intel_train`; `intel/advisor.py` + `intel/rules.py` + views + LLM explanation + quota.
C. Frontend: Bid Advisor panel on the tender page (curve + bid slider + cost input + rules + comparables + explain), `/intel` Market Intelligence page (trend by year, top winners, coverage + model card), bidder pages, pipeline outcome dialog, workspace toggle.
D. Integration: full imports and training on this machine, live smoke, adversarial review, docs.
