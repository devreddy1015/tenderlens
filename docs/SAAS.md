# Workspaces, pipeline, exports and billing

How the multi-tenant parts behave and why. The API contract itself is in
[PLATFORM_V2.md](PLATFORM_V2.md) sections 3 and 5. This page covers the choices the contract
leaves open.

## Organisations and roles

- **Active organisation.** Every user has exactly one active organisation, stored as
  `Membership.is_active` (one per user, enforced by a partial unique index). It is stored
  in the database, not the session, so it follows the user across devices.
  `GET /api/workspaces` lists the user's organisations. `POST /api/workspace/switch {organization}`
  switches between them. On a user's first request a personal organisation is created
  with that user as owner.
- **Roles.**
  - `owner` can do everything: change roles, remove anyone, and manage billing.
  - `admin` can edit the workspace and company profile, invite people, remove members,
    manage API keys, rotate the calendar link and manage billing.
  - `member` can use the pipeline, Copilot and alerts.

  An organisation always keeps at least one owner. Anyone can leave
  (`DELETE /api/workspace/members/<own membership id>`). Member ids in that API are
  **membership** ids; `user_id` is also returned.
- **Other organisations' objects** answer 404, never 403, so ids cannot be probed.

## Invitations and seats

- **Inviting.** `POST /api/workspace/invites {email, role: admin|member}` emails
  `SITE_URL/invite/<token>`.
- **The token.** The token is a `django.core.signing` value holding the invite id and a
  random nonce. The database stores only the nonce's SHA-256. The token is:
  - signature-checked,
  - expiring after `INVITE_MAX_AGE_DAYS` (7 by default),
  - single use, because accepting it takes a row lock.
- **Seats** = members + open invites. An open invite holds a seat until it is accepted,
  revoked or expires, so a team cannot over-invite and have everyone accept later.
  Accepting checks members only.
- **The invitee must sign in with the invited email address.** This means a forwarded
  link does not grant access.
- **The frontend's `/invite/<token>` page** reads `GET /api/workspace/invites/<token>` to
  learn the organisation, email, role and expiry. To join, it calls
  `POST .../accept`, which returns the workspace and makes it the user's active one.

## Bid pipeline

- **Adding a tender is idempotent.** `POST /api/pipeline {tender}` returns the existing
  entry (200) when the tender is already tracked. A new entry's owner is its creator.
- **`summary.closing_soon`** lists tenders still being watched or prepared that close within
  7 days.
- **`value_inr_in_play`** is the sum of watching, preparing and submitted entries. Each
  counts at its `bid_amount_inr` if one is set, otherwise at the tender's estimated value.
- **Reminders.** Every day at 08:00 IST, `workspaces.tasks.send_pipeline_reminders` emails
  about tenders that are watching or preparing and close within 3 days.
  - The email goes to the entry's owner. When nobody owns it, it goes to the
    organisation's owners and admins.
  - Each person gets one email per organisation per day.
  - `ReminderLog (track, user, day)` makes re-runs send nothing new.

## Calendar feed

- **The feed URL** is `GET /api/pipeline/calendar.ics?token=…`. The token is a random
  per-organisation value of 43 characters. It is shown to every member as
  `calendar_url` in `GET /api/workspace`, and an owner or admin can rotate it with
  `POST /api/workspace/calendar-token`.
- **The format** is RFC 5545, written by hand:
  - CRLF line endings, lines folded at 75 octets without splitting UTF-8 characters,
  - escaped TEXT values,
  - UTC times, so no VTIMEZONE is needed,
  - stable UIDs (`bidtrack-<id>-due@host`, `bidtrack-<id>-opening@host`),
  - a reminder alarm one day before.
- **Events.** Each tender gets a "Bid due" event (the 30 minutes before bid submission
  closes) and, when the tender has one, a "Bid opening" event.
- **Pre-bid meetings are not in the feed yet.** The `Tender` model has no pre-bid date;
  the Copilot's Bid Brief extracts one (`prebid_meeting`), so the integration stage can
  add it as a third event.

## Recommendations

`GET /api/recommendations` lists open tenders that match the profile:

- in the profile's `states`, if any are set,
- in its `sectors`, if any are set,
- not already in the pipeline,
- worth at most **3 × annual_turnover_inr**, when both values are known.

On the turnover rule: Indian tenders usually ask for an average annual turnover of
30–50 % of the estimated cost (CPWD asks for 30 %), so 3 × turnover is about the largest
tender a company can plausibly qualify for. Tenders with no stated value are kept.

- **Order.** Newest first.
- **Narrowing.** Any `/api/tenders` filter (`q`, `min_value`, …) narrows the list further.
- **`reasons`** gives the matched sector, state and "Within your turnover limit".
- **Empty profile.** When neither states nor sectors are set, the response is
  `profile_incomplete: true` with no results.

## API keys

- **The key.** A key is `tl_` followed by 43 URL-safe characters. Only its SHA-256 and the
  first 11 characters are stored, and the secret is shown once.
- **Sending it.** Clients send `Authorization: Api-Key <key>`.
- **What a request can do.** A key request acts as the key's creator inside the key's
  organisation. It can read data and use the pipeline, recommendations and exports. It
  cannot manage the workspace (invites, keys, billing), because those endpoints are
  session-only.
- **When a key stops working:**
  - when it is revoked,
  - when its creator leaves the organisation,
  - when the plan loses the `api` feature (the response is then 402).
- **Rate limit.** Requests are limited per key: `API_KEY_RATE_LIMIT`, 600/min by default.
- **`last_used_at`** is updated at most every 5 minutes.

## Exports

- **CSV.** `GET /api/export/tenders.csv` needs the plan feature `export`.
  - It returns the same tenders and order as `/api/tenders`, up to 10,000 rows.
    `X-Total-Count` and `X-Export-Truncated` describe the full result.
  - The file is UTF-8 with a byte-order mark (BOM).
  - Cells that a spreadsheet would run as a formula get a leading `'`.
  - Every row has `source_portal` and `source_url`, because the portals' content has no
    open licence: we export metadata with attribution and link out.
- **OCDS.** `GET /api/ocds/releases` is public and returns an OCDS 1.1 release package,
  100 releases per page by default. `links.next` and `links.prev` page through it.
  - **`ocid`** = `OCDS_PREFIX-<source>-<tender ID>`. **Before publishing, register a real
    prefix with the Open Contracting Partnership** (https://standard.open-contracting.org/latest/en/guidance/build/#register-an-ocid-prefix)
    and set `OCDS_PREFIX`. The default `ocds-tenderlens` is for development only.
  - **Release contents:**
    - the buyer as a party,
    - the tender's title, value in INR, `tenderPeriod`, `procurementMethodDetails`,
      `mainProcurementCategory` and EMD as `guarantee`,
    - the bid opening date as `awardPeriod.startDate`,
    - one document: a link to the notice on the source portal.
  - **No `license` is claimed.**
  - **Awards** are included automatically if an `Award` model exists in `tenders` or
    `ingest`.

## Billing

- **Organization.plan_code is derived, never set by hand.** `billing.services.sync_plan`
  derives it from the newest subscription in `active` or `pending` (else `free`). Saving a
  subscription in the admin also re-derives it. An Enterprise contract is therefore a
  `manual` subscription.
- **Providers.**
  - **`BILLING_PROVIDER=fake`** activates a plan at checkout. This is for development and
    tests only.
  - **When the variable is unset,** the provider is `fake` only if `DJANGO_DEBUG` is on,
    and `razorpay` otherwise.
- **Razorpay setup:**
  1. Create the plans in the dashboard.
  2. Set `RAZORPAY_PLAN_{PRO,TEAM}_{MONTH,YEAR}`, `RAZORPAY_KEY_ID` and
     `RAZORPAY_KEY_SECRET`.
  3. Add a webhook to `https://<site>/api/billing/webhook` with a secret
     (`RAZORPAY_WEBHOOK_SECRET`) and the `subscription.*` events.
- **Checkout** creates a Razorpay subscription, and the browser opens Razorpay Checkout
  with `key_id` and `subscription_id`. Only the webhook changes the plan.
- **Webhooks.**
  - Each delivery is verified by HMAC-SHA256 over the raw body.
  - Deliveries are idempotent per `X-Razorpay-Event-Id`.
  - `activated`, `charged` and `resumed` switch the plan on. `pending` keeps it while
    Razorpay retries. `halted`, `cancelled` and `completed` revert to free.
  - A cancelled or completed subscription never re-activates.
- **Cancel** cancels at the end of the paid period on Razorpay, and immediately for
  fake or manual subscriptions.
- **Alerts limit.** The plan's `alerts` limit counts every alert of every member of the
  organisation.
