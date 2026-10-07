"""Open Contracting Data Standard bulk files from the OCP Data Registry
(data.open-contracting.org), and the publications we import from it.

The registry republishes 130+ national feeds as compiled releases, one JSON object per
line, one gzip file per year (`/en/publication/<id>/download?name=<year>.jsonl.gz`, a 302 to
fastly.data.open-contracting.org). OCDSSource reads any of them; a publication is a
subclass that sets its id, country, currency and years, plus the few things that are
national (how titles, methods and sectors are written).

A ratio is only honest when the award and the estimate cover the same scope. A tender with
several lots (or, in Peru, several items, which SEACE uses as lots) may be awarded piecemeal
while tender.value is the whole budget, so an award is matched to the estimate of exactly
the lots or items it covers, and records where that cannot be done unambiguously are
skipped rather than guessed. The tender-wide numberOfTenderers is only attached to rows
that cover the whole tender.
"""

import gzip
import json
import logging
import re
import time
import unicodedata
from collections import Counter
from collections.abc import Iterator
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import ClassVar

import httpx

from intel.models import RATIO_MAX, RATIO_MIN
from intel.prices import CURRENCY_AREAS
from intel.sources.base import AwardRow, ImportContext, Source, cpv_sector, register

log = logging.getLogger(__name__)

DOWNLOAD_URL = "https://data.open-contracting.org/en/publication/{publication}/download?name={name}"
CATEGORY = {
    "works": "works",
    "goods": "goods",
    "services": "services",
    "consultingServices": "consultancy",
}
METHOD = {"open": "open", "selective": "limited", "limited": "limited", "direct": "single"}
MAX_BIDDERS = 999


def ipv4_client(like: httpx.Client) -> httpx.Client:
    """Same headers and timeouts, bound to IPv4: fastly.data.open-contracting.org advertises
    IPv6 addresses that are unreachable from some hosts (this one included), and httpx would
    otherwise wait out the connect timeout on every download."""
    return httpx.Client(
        transport=httpx.HTTPTransport(local_address="0.0.0.0"),
        timeout=like.timeout,
        headers=like.headers,
        follow_redirects=True,
    )


def _money(value) -> tuple[Decimal | None, str]:
    """OCDS Value object -> (amount > 0 or None, currency)."""
    if not isinstance(value, dict):
        return None, ""
    try:
        amount = Decimal(str(value.get("amount")))
    except (InvalidOperation, ValueError):
        return None, ""
    ok = amount.is_finite() and amount > 0
    return (amount if ok else None), str(value.get("currency") or "").upper()


def _item_value(item: dict) -> tuple[Decimal | None, str]:
    """An item's total: the totalValue extension when published (Peru), else unit x qty."""
    if item.get("totalValue"):
        return _money(item["totalValue"])
    unit, currency = _money((item.get("unit") or {}).get("value"))
    try:
        qty = Decimal(str(item.get("quantity")))
    except (InvalidOperation, ValueError):
        return None, ""
    return (unit * qty if unit and qty.is_finite() and qty > 0 else None), currency


def _day(text) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def fold(text: str) -> str:
    """Lowercase without accents, for keyword rules: 'Electrificación' -> 'electrificacion'."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


class OCDSSource(Source):
    """One OCP Data Registry publication. Subclass, set the ClassVars, @register."""

    publication: ClassVar[int]
    country: ClassVar[str]
    currency: ClassVar[str]  # the publication's own currency; USD and EUR are also accepted
    first_year: ClassVar[int]
    last_year: ClassVar[int | None] = None  # None: the current year (daily-updated feeds)
    force_ipv4: ClassVar[bool] = True
    # Amounts above this are typos, and would overflow the real-rupee columns.
    max_amount: ClassVar[Decimal] = Decimal("1e12")
    kind = "outcomes"
    min_interval_seconds = 1.0

    def __init__(self):
        self.counts: Counter = Counter()

    # --- national conventions (override per publication) -------------------------------

    def title(self, tender: dict) -> str:
        return str(tender.get("title") or tender.get("description") or "").strip()

    def method(self, tender: dict) -> str:
        return METHOD.get(str(tender.get("procurementMethod") or ""), "")

    def sector(self, text: str, category: str, items: list[dict]) -> str:
        for item in items:
            classification = item.get("classification") or {}
            if str(classification.get("scheme", "")).upper() == "CPV":
                return cpv_sector(classification.get("id"))
        return ""

    def state(self, release: dict) -> str:
        buyer_id = (release.get("buyer") or {}).get("id")
        for party in release.get("parties") or []:
            if party.get("id") == buyer_id or "buyer" in (party.get("roles") or []):
                address = party.get("address") or {}
                return str(address.get("region") or "").strip().title()[:64]
        return ""

    # --- reading ------------------------------------------------------------------------

    def rows(self, ctx: ImportContext) -> Iterator[AwardRow]:
        if self.force_ipv4:
            old, ctx.client = ctx.client, ipv4_client(ctx.client)
            old.close()
        if ctx.file:
            yield from self.read(ctx.file, ctx.since)
            return
        last = self.last_year or date.today().year
        for year in range(max(self.first_year, ctx.since or 0), last + 1):
            path = self.fetch(ctx, year)
            if path is not None:
                yield from self.read(path, ctx.since)
        log.info("%s: %s", self.key, dict(self.counts))

    def fetch(self, ctx: ImportContext, year: int, attempts: int = 4) -> Path | None:
        """The year's file (cached). The CDN resets connections now and then, and
        ctx.download does not retry a stream, so this does; a missing year is skipped."""
        name = f"{year}.jsonl.gz"
        url = DOWNLOAD_URL.format(publication=self.publication, name=name)
        for attempt in range(1, attempts + 1):
            try:
                return ctx.download(url, name=name)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    log.warning("%s: no file for %s", self.key, year)
                    return None
                if attempt == attempts or exc.response.status_code < 500:
                    raise
            except httpx.TransportError:
                if attempt == attempts:
                    raise
            log.warning("%s: %s failed (attempt %s), retrying", self.key, name, attempt)
            time.sleep(30 * attempt if ctx.min_interval else 0)
        return None

    def read(self, path: Path, since: int | None = None) -> Iterator[AwardRow]:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    release = json.loads(line)
                except ValueError:
                    self.counts["bad_json"] += 1
                    continue
                if isinstance(release, dict):
                    yield from self.release_rows(release.get("compiledRelease") or release, since)

    # --- one compiled release -> ratio rows ---------------------------------------------

    def skip(self, reason: str) -> None:
        self.counts[reason] += 1

    def scopes(self, tender: dict, awards: list[dict], estimate: Decimal):
        """[(award, estimate of the same scope, covers the whole tender)], or None when the
        award-to-estimate match is ambiguous."""
        lots = tender.get("lots") or []
        if lots:
            lot_value = {lot.get("id"): _money(lot.get("value"))[0] for lot in lots}
            if len(lots) == 1 and len(awards) == 1:
                related = awards[0].get("relatedLots") or [lots[0].get("id")]
                if related == [lots[0].get("id")]:
                    return [(awards[0], lot_value[related[0]] or estimate, True)]
            out, seen = [], set()
            for award in awards:
                related = award.get("relatedLots") or []
                if len(related) != 1 or not lot_value.get(related[0]) or related[0] in seen:
                    return None
                seen.add(related[0])
                out.append((award, lot_value[related[0]], len(lots) == 1))
            return out

        items = {i.get("id"): i for i in tender.get("items") or [] if i.get("id") is not None}
        if len(awards) == 1:
            ids = {i.get("id") for i in awards[0].get("items") or []}
            if len(items) <= 1 or (ids and ids >= set(items)):
                return [(awards[0], estimate, True)]
        # Item-level: every award names tender items, no item is awarded twice, and the
        # tender's items add up to its value (so their values are the estimate's parts).
        values = {k: _item_value(v)[0] for k, v in items.items()}
        if not values or None in values.values():
            return None
        if abs(sum(values.values()) - estimate) > estimate / 100:
            return None
        out, seen = [], set()
        for award in awards:
            ids = [i.get("id") for i in award.get("items") or []]
            if not ids or any(i not in items for i in ids) or seen & set(ids):
                return None
            seen |= set(ids)
            out.append((award, sum(values[i] for i in set(ids)), set(ids) == set(items)))
        return out

    def release_rows(self, release: dict, since: int | None = None) -> Iterator[AwardRow]:
        self.counts["records"] += 1
        tender = release.get("tender") or {}
        estimate, currency = _money(tender.get("value"))
        if estimate is None:
            return self.skip("no_estimate")
        if currency not in {self.currency, "USD", *CURRENCY_AREAS}:
            return self.skip("other_currency")  # would be converted at the wrong rate
        awards = [
            a
            for a in release.get("awards") or []
            if (a.get("status") or "active") == "active" and _money(a.get("value"))[0]
        ]
        if not awards:
            return self.skip("no_award")
        scopes = self.scopes(tender, awards, estimate)
        if scopes is None:
            return self.skip("ambiguous_scope")

        ocid = release.get("ocid") or release.get("id")
        buyer = (release.get("buyer") or {}).get("name") or (
            tender.get("procuringEntity") or {}
        ).get("name")
        category = CATEGORY.get(str(tender.get("mainProcurementCategory") or ""), "")
        tender_items = {i.get("id"): i for i in tender.get("items") or []}
        bidders = tender.get("numberOfTenderers")
        if bidders is None and tender.get("tenderers"):
            bidders = len({t.get("id") or t.get("name") for t in tender["tenderers"]})
        published = _day(
            tender.get("datePublished") or (tender.get("tenderPeriod") or {}).get("startDate")
        )
        title, method, state = self.title(tender), self.method(tender), self.state(release)

        for award, scope_estimate, whole in scopes:
            value, award_currency = _money(award.get("value"))
            if award_currency != currency:
                self.skip("currency_mismatch")
                continue
            if max(value, scope_estimate) > self.max_amount:
                self.skip("implausible_amount")
                continue
            if not RATIO_MIN <= value / scope_estimate <= RATIO_MAX:
                self.skip("ratio_out_of_band")
                continue
            awarded = _day(award.get("date"))
            year = (awarded or published).year if (awarded or published) else None
            if since and year and year < since:
                self.skip("before_since")
                continue
            items = [tender_items.get(i.get("id")) or i for i in award.get("items") or []]
            text = " ".join([title, *(str(i.get("description") or "") for i in items)])
            row_title = (
                title
                if whole
                else "; ".join(
                    dict.fromkeys(str(i.get("description") or "").strip() for i in items)
                )[:1000]
                or title
            )
            self.counts["emitted"] += 1
            yield AwardRow(
                source_id=f"{ocid}:{award.get('id') or 'award'}",
                country=self.country,
                state=state,
                buyer=str(buyer or "").strip(),
                title=row_title,
                category=category,
                # Lot awards often list no items: classify by the tender's then.
                sector=self.sector(text, category, items or list(tender_items.values())),
                method=method,
                currency=currency,
                estimated_value=scope_estimate,
                award_value=value,
                num_bidders=bidders
                if whole and isinstance(bidders, int) and 0 < bidders <= MAX_BIDDERS
                else None,
                winner="; ".join(
                    str(s.get("name") or "").strip() for s in award.get("suppliers") or []
                ),
                tender_date=published,
                award_date=awarded,
                year=year,
            )


# Spanish title keywords -> sector, first match wins. Studies and supervision come first:
# "supervisión de la obra de la carretera" is consultancy, not roads.
SPANISH_SECTORS = [
    ("consultancy", r"consultori|supervision|\bestudios?\b|expediente tecnico|perfil de inversion"),
    ("roads", r"carretera|camino|\bvias?\b|puente|pavimentacion|transitabilidad|pistas y veredas"),
    ("water", r"\bagua|saneamiento|alcantarillado|\briego|desague"),
    ("electrical", r"electrificacion|electric"),
    ("it", r"software|informatic|computo|computador"),
    ("health", r"medicamento|hospital|\bmedic[oa]s?\b|medicina|\bsalud\b"),
    ("security", r"vigilancia|seguridad"),
    ("facility", r"limpieza|mantenimiento de areas"),
    ("buildings", r"edificacion|construccion|institucion educativa"),
]
_SPANISH_SECTORS = [(slug, re.compile(rx)) for slug, rx in SPANISH_SECTORS]
CATEGORY_SECTOR = {"works": "buildings", "goods": "supplies"}  # as tenders.sectors.classify

# Peru's procurementMethodDetails (SEACE names, current law 30225 and the old 1017 regime).
PERU_METHODS = [
    ("reverse_auction", r"subasta inversa"),
    ("single", r"contratacion directa|exoneracion"),
    # Scored on technical merit and price, so the lowest bid does not simply win.
    ("qcbs", r"concurso publico|consultores individuales"),
    ("other", r"convenio|contratacion internacional|regimen especial|concurso de proyecto"),
    ("limited", r"directa selectiva|menor cuantia|comparacion de precios|competencia menor"),
    # "Licitación Pública Abreviada" (2025 law) is still a public call: open.
    (
        "open",
        r"licitacion publica|adjudicacion simplificada|directa publica|procedimiento especial"
        r"|competencia mayor|proceso abierto|abreviad",
    ),
]
_PERU_METHODS = [(slug, re.compile(rx)) for slug, rx in PERU_METHODS]


@register
class Peru(OCDSSource):
    key = "peru"
    name = "Peru OECE (SEACE) open contracting data, OCP registry publication 135"
    url = "https://data.open-contracting.org/en/publication/135"
    license = "CC BY 4.0"
    publication = 135
    country = "PE"
    currency = "PEN"
    first_year = 2003

    def title(self, tender: dict) -> str:
        # tender.title is the process code ("AS-SM-56-2020-MINEDU/UE 108-1"); the
        # description is what was bought.
        return str(tender.get("description") or tender.get("title") or "").strip()

    def method(self, tender: dict) -> str:
        details = fold(str(tender.get("procurementMethodDetails") or ""))
        for slug, rx in _PERU_METHODS:
            if rx.search(details):
                return slug
        return super().method(tender)

    def sector(self, text: str, category: str, items: list[dict]) -> str:
        folded = fold(text)
        for slug, rx in _SPANISH_SECTORS:
            if rx.search(folded):
                return slug
        return CATEGORY_SECTOR.get(category, "other")

    def state(self, release: dict) -> str:
        # SEACE addresses: department (Peru's first-level region) and, as "region", the
        # province.
        for party in release.get("parties") or []:
            if "buyer" in (party.get("roles") or []):
                address = party.get("address") or {}
                return str(address.get("department") or address.get("region") or "").title()[:64]
        return ""
