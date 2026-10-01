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
| Document names | detail | names only; downloads are CAPTCHA-gated |

The saved pages in `tests/fixtures/` are real responses from that day: 1 organisation
index, 2 organisation listings, 18 detail pages from 5 organisations, 1 stale-session
page and 1 state-portal index. Three hand-broken copies are in `fixtures/broken/`.
