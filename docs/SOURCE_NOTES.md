# Source study: what is public on CPPP / GePNIC, and what is not

Notes from studying the portals before writing the crawler (build plan step 2).
Checked on 2 October 2026.

## Which pages are usable

| Page | URL | CAPTCHA? | Used |
|---|---|---|---|
| CPPP "Latest Active Tenders" (Drupal) | `eprocure.gov.in/cppp/latestactivetendersnew/cpppdata` | listing visible; search form gated | no: detail links (`/cppp/tendersfullview/…`) are CAPTCHA-gated |
| GePNIC "Latest Active Tenders" | `eprocure.gov.in/epublish/app?page=FrontEndLatestActiveTenders` | **yes**, before any listing | no |
| GePNIC "Tenders by Organisation" index | `eprocure.gov.in/eprocure/app?page=FrontEndTendersByOrganisation&service=page` | no (only its optional search box has one) | **yes** |
| Organisation listing (DirectLink from the index) | `…/app?component=$DirectLink&page=FrontEndTendersByOrganisation&sp=…` | no | **yes** |
| Tender detail | `…/app?component=$DirectLink&page=FrontEndViewTender&sp=…` | no | **yes** |
| Tender documents (NIT PDF, BOQ, zip) | `…/app?component=docDownoad&page=FrontEndTenderDetails` | **yes** | no |

`robots.txt`: `eprocure.gov.in/robots.txt` and the state portals return 404 (no
restrictions). `eprocure.gov.in/cppp/robots.txt` only disallows Drupal admin paths.
Either way the crawler sends at most one request per second with an identifying
User-Agent.

The central GePNIC instance listed **2,549 active tenders from 252 organisations** that
day. The same GePNIC software (identical markup) runs the state portals: MP
`mptenders.gov.in/nicgep/app` (5,421 tenders, 96 organisations), Odisha, Kerala and
Rajasthan, so one parser covers them. Chhattisgarh's portal URL returned 404.

## Behaviour that shaped the design

* **Sessions.** Every `DirectLink` needs a live server session (`JSESSIONID`). Without
  one, the portal returns a "Stale Session / Your session has timed out" page with HTTP
  200, so a status-code check alone would accept it as success. The same link works in
  any *new* session, so recovery is "start a new session, retry the link". No re-walk of
  the listing is needed.
* **No pagination** on organisation listings: the largest (Ministry of Road Transport
  and Highways, 269 tenders) comes back on one page.
* **Volatile HTML.** Every page embeds a visitor counter and session tokens, so the raw
  body hash changes on every fetch. Change detection therefore hashes the parsed
  fields, not the HTML.
* **Tender ID is the stable key** (`2026_AMU_926330_3`); it is unique within a portal.
  URLs are not stable (session-bound `sp` tokens).
* **Indian number formatting**: `4,91,87,00,000`. Missing values are written `NA`, and
  `0.00` is common for "not disclosed".
* **Dates** are `07-Oct-2026 11:00 AM`, local time (IST).

## Fields

| Field | Where | Notes |
|---|---|---|
| Tender ID | listing + detail | primary key with `source` |
| Tender reference number | listing + detail | issuer's own number |
| Title | listing + detail ("Work Item Details → Title") | |
| Organisation chain | listing + detail | `Org‖Department‖Office‖…`; buyer = first two levels |
| e-Published date | listing + detail | |
| Bid submission end date (closing) | listing + detail | |
| Bid opening date | listing + detail | |
| Tender value in ₹ | detail | `NA` or `0.00` when undisclosed |
| EMD amount in ₹ | detail | |
| Tender fee in ₹ | detail | |
| Tender category | detail | Works / Goods / Services |
| Product category | detail | e.g. "Civil Works - Highways" |
| Tender type | detail | Open / Limited / … |
| Location, pincode | detail | state derived from pincode on the central portal |
| Tender inviting authority | detail | name and address |
| Pre-bid meeting date | detail ("Pre Bid Meeting Date") | `NA` on most; stored as `Tender.prebid_meeting` (IST), an unreadable value is treated as unknown, never quarantined |
| Document names | detail | names only; downloads are CAPTCHA-gated |

The saved pages in `tests/fixtures/` are real responses from that day: 1 organisation
index, 2 organisation listings, 18 detail pages from 5 organisations, 1 stale-session
page and 1 state-portal index. Three hand-broken copies are in `fixtures/broken/`.

## Coverage expansion: 35 GePNIC portals (6 October 2026)

Each candidate got **one** GET of its organisation index
(`<base>/app?page=FrontEndTendersByOrganisation&service=page`), sent one at a time with
more than 1 s between requests and the crawler's User-Agent. A portal was accepted only when
`ingest.parsers.gepnic.parse_org_index` read the page unchanged. The text "Provide Captcha
and click on Search" appears on every one of these pages, but it belongs to the optional
search box: the organisation table itself is public. Counts are the active tenders each
index listed on 6 October 2026. The five original portals (central, MP, Odisha, Kerala,
Rajasthan) were verified on 2 October; see above.

| Key | Host | State | Orgs | Active tenders |
|---|---|---|---|---|
| `etenders` | etenders.gov.in (`/eprocure/app`) | (pincode) | 82 | 2,049 |
| `defence` | defproc.gov.in | (pincode) | 11 | 4,632 |
| `mod-psu` | eprocuremdl.nic.in | (pincode) | 7 | 105 |
| `coalindia` | coalindiatenders.nic.in | (pincode) | 10 | 561 |
| `iocl` | iocletenders.nic.in | (pincode) | 1 | 217 |
| `ntpc` | eprocurentpc.nic.in | (pincode) | 5 | 414 |
| `bhel` | eprocurebhel.co.in | (pincode) | 1 | 467 |
| `haryana` | etenders.hry.nic.in | Haryana | 2 | 1,946 |
| `up` | etender.up.nic.in | Uttar Pradesh | 128 | 10,271 |
| `uttarakhand` | uktenders.gov.in | Uttarakhand | 73 | 673 |
| `hp` | hptenders.gov.in | Himachal Pradesh | 47 | 1,110 |
| `jk` | jktenders.gov.in | Jammu and Kashmir | 33 | 4,247 |
| `punjab` | eproc.punjab.gov.in | Punjab | 33 | 3,309 |
| `delhi` | govtprocurement.delhi.gov.in | Delhi | 17 | 593 |
| `chandigarh` | etenders.chd.nic.in | Chandigarh | 3 | 242 |
| `wb` | wbtenders.gov.in | West Bengal | 95 | 2,659 |
| `jharkhand` | jharkhandtenders.gov.in | Jharkhand | 41 | 658 |
| `assam` | assamtenders.gov.in | Assam | 45 | 471 |
| `arunachal` | arunachaltenders.gov.in | Arunachal Pradesh | 3 | 5 |
| `manipur` | manipurtenders.gov.in | Manipur | 14 | 47 |
| `meghalaya` | meghalayatenders.gov.in | Meghalaya | 6 | 20 |
| `mizoram` | mizoramtenders.gov.in | Mizoram | 0 | 0 (same layout, "No Active Tenders found") |
| `nagaland` | nagalandtenders.gov.in | Nagaland | 3 | 3 |
| `sikkim` | sikkimtender.gov.in | Sikkim | 4 | 5 |
| `tripura` | tripuratenders.gov.in | Tripura | 37 | 386 |
| `tn` | tntenders.gov.in | Tamil Nadu | 62 | 5,343 |
| `puducherry` | pudutenders.gov.in | Puducherry | 10 | 49 |
| `goa` | eprocure.goa.gov.in | Goa | 33 | 252 |
| `maharashtra` | mahatenders.gov.in | Maharashtra | 150 | 2,442 |
| `dnh` | dnhtenders.gov.in | Dadra and Nagar Haveli and Daman and Diu | 1 | 17 |

Together the 30 new portals list **43,193 active tenders**, on top of the original five.
"(pincode)" marks multi-state portals (central government, PSUs, defence): there each
tender's state is derived from its pincode, as on the central portal.

**Live smoke (15 requests):** dnhtenders, eprocurentpc and tntenders each got a session,
the index, the smallest organisation's listing and up to two detail pages. Listing counts
matched the index (17/17, 2/2, 1/1), and every detail page parsed with ID, title, dates,
value and pincode. The saved pages in `tests/fixtures/gepnic_portals/` are trimmed copies
(scripts and styles removed): the defence and Tamil Nadu indexes and the DNH listing and
detail page. `tests/test_sources.py` parses them and loads the DNH detail page.

**Rejected candidates**

| Candidate | Why |
|---|---|
| eprocure.andaman.gov.in | DNS does not resolve |
| tenders.ladakh.gov.in | TLS certificate is self-signed. We do not turn off certificate checks; try again later |
| eprocurebel.co.in, eprocuregrse.co.in | The same instance as eprocuremdl.nic.in ("eProcurement System for PSUs under MoD": BEML, BEL, GRSE, Goa Shipyard …, 7 orgs and 105 tenders on all three hosts). It is crawled once, as `mod-psu` |
| Chhattisgarh (2 Oct) | portal URL returned 404 |
| Karnataka, Andhra Pradesh, Telangana, Gujarat, Bihar | not probed: known to run non-GePNIC systems (their own or third-party e-procurement systems); each would need its own adapter and its own terms check |

**Overlap.** A tender ID is unique within one portal. Some central organisations may appear on
both `central` and `etenders` (not measured yet). Rows are keyed on (source, tender ID), so the same tender can
appear once for each portal. Cross-portal de-duplication, for example by reference number
plus buyer, is left for later.

**Load.** An hourly incremental crawl is roughly 1,300 requests (indexes plus organisation
listings) plus the changed detail pages. A nightly full crawl fetches about 50,000 detail
pages. The limit is 1 request per second per host and every portal is its own host, but a
worker waiting on a host's slot sleeps. With the compose default of 2 crawl workers the
whole fleet therefore gets about 2 requests per second, and the full crawl cannot finish
overnight. The deploy needs more crawl concurrency, for example `-P threads --concurrency
24` on the `crawl` queue, or less frequent full crawls for the largest portals (`up`, `tn`,
`defence`, `jk`).

## Award data (results of tenders): CAPTCHA-gated, not collected

Checked on 6 October 2026 with one GET per page:

| Page | URL | What it shows |
|---|---|---|
| GePNIC "Bid Awards" / Results of Tenders (central) | `eprocure.gov.in/eprocure/app?page=ResultOfTenders&service=page` | A search form (Tender ID, Keyword) with **Enter Captcha**. The result table (S.No, AOC Date, e-Published Date, Title and Ref.No./Tender ID, Organisation Chain, AOC) is empty: "No Results Of Tenders found" until a CAPTCHA-checked search is submitted |
| Same page on a state portal (MP) | `mptenders.gov.in/nicgep/app?page=ResultOfTenders&service=page` | Identical: CAPTCHA before any row |
| GePNIC "Tenders Status" | `…/app?page=WebTenderStatusLists&service=page` | Search by status (Technical/Financial Evaluation, **AOC**, Concluded …), with "Tender ID * / Enter Captcha *" required |
| GePNIC "Tenders in Archive" | `…/app?page=FrontEndTendersInArchive&service=page` | CAPTCHA search form, "No Archived Tenders found" |
| CPPP "Result of Tenders" | `eprocure.gov.in/cppp/resultoftendersnew/cpppdata` | Drupal form (organisation, keyword, AOC year, AOC status) with an image CAPTCHA ("What code is in the image?"); no result rows without it |
| GePNIC MIS Reports | `gepnicreports.gov.in/eprocreports/eproc/` | Redirects to an index page that needs JavaScript and a site code; aggregate reports, not bidder-level awards |

Without solving a CAPTCHA there is no public, machine-readable path to bidder names, award
amounts or AOC dates on GePNIC or CPPP, and we never touch a CAPTCHA. As spec §5 allows,
**no Award model, award parser or `/api/bidders` endpoints were built**. Detail pages of
active tenders, which are reachable, carry no award information.

What would unlock award data, in order of likelihood:

1. **A formal data-sharing request to NIC (eProcurement division) and the Department of
   Expenditure's Procurement Policy Division** for a bulk or API feed of AOC records
   (tender ID, bidder, contract value, AOC date). The GePNIC schema already holds these fields.
   The Public Procurement Order and GFR 2017 rule 159 already require award details to be
   *published* on CPPP. A feed only changes the format, not what is disclosed.
2. **GeM**: GeM publishes contract and order data in its own dashboards, but bidplus's data
   endpoint is protected by server-side controls, so we must not scrape it. Request access
   through GeM's data-sharing or API programme. An MoU with GeM SPV is the usual route for
   private platforms.
3. **Open-data precedents to cite in the request.** The EU publishes every award notice
   on TED as bulk XML/CSV under an open licence, and the UK publishes Find a Tender and
   Contracts Finder as OCDS with an API under the Open Government Licence. Both are
   OCDS-compatible, and our `/api/ocds/releases` export is already ready to carry `awards`.
4. Datasets on data.gov.in under the Government Open Data Licence – India. These are not
   verified here. Check the licence and coverage of each dataset before using it.

When a legitimate feed exists, the planned shape stays as in spec §5: `Award` (tender FK nullable,
source, source_tender_id, bidder, normalised bidder key, amount_inr, award_date, source_url,
raw), linked to `Tender` by (source, tender ID), `awards` on `GET /api/tenders/{id}`, and
`GET /api/bidders?q=` / `GET /api/bidders/{key}`.

## Award data for the Bid Advisor (7 October 2026)

What trains the bid price model (`docs/BID_ADVISOR.md` section 2; adapters in
`intel/sources/`, `manage.py intel_import <key>`). Every import records its files' sha256
and the licence in `DatasetImport`. The verification behind this list was done with live
requests on 7 October 2026.

**Used**

| Key | Source | Kind | Why it is usable |
|---|---|---|---|
| `worldbank_in` | World Bank procurement plans, contract award notices and Finances One contract awards for India | outcomes | Estimate, award, every evaluated bid. CC BY 4.0 (datasets), CC BY 3.0 IGO (documents), with attribution |
| `pmgsy` | India Data Portal (ISB) "PMGSY Financial and Physical Report", from OMMAS | history | Sanctioned cost (lakh), contractor, award date, district, 2000-2021. ODC-BY 1.0. Cost is the *sanction*, not the bid, so no ratio |
| `ted` | EU TED contract award notices CSV, 2006-2023 | outcomes | Estimate, award, number of offers, CPV. CC BY 4.0 / EC reuse notice |
| `peru` | Peru OECE OCDS bulk, 2003-2026 | outcomes | Estimate, award, number of tenderers. CC BY 4.0 |
| `tenderlens` | Our users' pipeline outcomes (L1, winner, bidders, rank) | outcomes | Ours under the ToS. `Organization.contribute_outcomes` decides `shared`; names never leave the organisation |

`pmgsy` notes: the CSV has one row per habitation and repeats a road for each contract, so
the adapter groups rows into one award per (state, package, road, award date): 407,633 rows
become 192,657 awards, of which 191,982 have a usable cost. It drops placeholder
"contractors" (Uttar Pradesh's "BMS"/"BMS EXPENDITURE" budget heads, "PROJECT AND
DESIGN"), costs below 1 lakh and dates before April 2000. Some West Bengal and Assam rows
appear to name consultants ("Consulting Engineering Services", "Infrastructure Consultant
Bureau") rather than the builder; they are kept as published. The host is a dev CKAN
(`ckandev.indiadataportal.com`), so keep the raw file.

**Not used, and why**

| Source | Why not | Route |
|---|---|---|
| GeM BidPlus "Bid/RA results" (3.38M awarded bids/RAs since 2018, every seller's price and rank; public, no CAPTCHA) | GeM Copyright Policy: no reproduction "without due permission in writing in advance from the GeM SPV" | Letter A in `docs/DATA_REQUESTS.md` |
| CPPP "Result of Tenders" and GePNIC Results / Tenders Status / Archive (AOC value, bids received, selected bidder) | CAPTCHA before any row. Replaying post-CAPTCHA pagination URLs would get around it. The CPPP policy also needs the owning department's permission | Letters B and C (MoU with DoE/NIC; RTI) |
| Hugging Face `tenders_aoc`; CivicDataLab Assam and Himachal OCDS | Built from CAPTCHA-gated CPPP result pages; the uploader's licence label cannot be relied on | None until B succeeds |
| Lehne, Shapiro & Vanden Eynde PMGSY bids; Lewis-Faupel et al. (openICPSR E114617V1) | Not public, or no licence that allows commercial use | Letter D |
| GTI GPPD, Opentender | Non-commercial licences | None |
| Prozorro, ChileCompra, SECOP II | Licence or volume questions | Phase 2 |
| `mahatenders.gov.in`, `ireps.gov.in` | robots.txt disallows all | None; the crawler's robots.txt gate (`ingest/robots.py`) enforces this on every run |

This supersedes the GeM remark in the section above: the all-bids list is a public JSON
call that uses the page's own CSRF token, with no login and no CAPTCHA. Permission is what
blocks reuse, not technical controls.

## GeM and CPPP e-publish adapters: not built

`Source.kind` accepts `"gem"` and `"cppp"`, and `ingest.pipeline.CRAWLERS` /
`ingest.parsers.DETAIL_PARSERS` are where an adapter would plug in. Neither is built:

* **GeM bidplus**: its data endpoint is protected by server-side controls. Working around
  them is off the table. Needed: the data-sharing route above.
* **CPPP e-publish "Latest Active Tenders"**: CAPTCHA-gated (GePNIC `epublish` asks for a
  CAPTCHA before any listing, and the CPPP Drupal detail links are gated). Tenders that
  organisations post on CPPP through their own GePNIC instance are already covered through
  that instance. Tenders posted only through e-publish need an NIC feed.

## Cross-portal duplicates: plan, no rule yet (6 October 2026)

Question: can the same tender appear on two portals (e.g. `central` and `etenders`), and
show twice in search, alerts and the calendar?

What the data says so far:

* Each GePNIC portal is its own installation with its own tender sequence. The ID
  `2026_ITBP_928174_1` is `year _ organisation code _ sequence _ cover/round`; the
  organisation code is defined per installation, and the sequence is the installation's
  own counter. An organisation creates a tender in one installation; CPPP lists tenders of
  all installations, but CPPP is not crawled. So a real duplicate needs an organisation to
  publish the same work twice, on two installations.
* The dev database (2,549 `central` + 137 `mp`, 6 October 2026) has **0** tender IDs and
  **0** (reference number, title) pairs shared by two sources. `etenders` and the 30 new
  portals have not been crawled yet, so this proves little.
* Matching on the ID string alone is **not safe**: two installations' independent counters
  can produce the same `<org>_<seq>` for different works (the org code is not globally
  registered). A false merge would hide a real tender, which is worse than a duplicate.

Measured again in the integration stage (6 October 2026), after a bounded live crawl of
all 35 portals (3,158 tenders from 34 portals with open tenders): **0** (reference number,
closing time) pairs and **0** tender IDs shared by two sources. No rule was added; re-run
the two queries below after the first full crawls on the VPS.

Rule to adopt once real crawls show duplicates:

1. Measure first, after the first full crawl of all sources:
   `SELECT lower(ref_no), closes_at, count(DISTINCT source) FROM tender WHERE ref_no <> ''
   GROUP BY 1, 2 HAVING count(DISTINCT source) > 1;` and the same on `source_tender_id`.
2. If there are duplicates, treat two rows as one tender only when **all** of: the same
   normalised reference number (non-empty, at least 6 characters), the same `closes_at`,
   and a title similarity (`pg_trgm similarity`) of at least 0.8; a matching
   `source_tender_id` is supporting evidence, not proof.
3. Store it as a nullable `Tender.canonical` self-FK (the earliest-seen row is canonical),
   set by the loader after the upsert, never merge or delete rows: each source keeps its
   own URL and crawl history, and a wrong link can be undone.
4. Collapse at read time: search, recommendations, alerts and OCDS use
   `canonical IS NULL`; the tender page lists "Also published on: <portal>".

