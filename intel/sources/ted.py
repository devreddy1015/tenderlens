"""EU Tenders Electronic Daily: contract award notices, CSV subset 2006-2023 (DG GROW).

One zip per year (`ted-contract-award-notices-<year>.zip`, 20-110 MB, one 0.1-0.7 GB CSV
inside), read straight out of the zip without extracting it. Rows are contract awards (the
section V of a notice), one per lot/award pair; the official codebook (TED(csv) data
information v3.4) is the reference for every column used here.

Only rows that teach the price model something are emitted: an award with both the
estimated value (AWARD_EST_VALUE_EURO) and the final value (AWARD_VALUE_EURO) of the same
contract award, whose ratio lies inside the HistoricalAward band. Measured on the 2022 file,
framework agreements and their call-offs are what pollutes the ratio (the estimate is the
whole framework's, the award one call-off: 38-53% of those ratios are below 0.2), so every
framework / DPS indication is dropped. So is an award exactly equal to its estimate: the
2.0.9 form requires a value and many buyers type it into both fields (87% of Finland's,
72% of Sweden's rows), which is a copied number, not a bid.
"""

import csv
import gzip
import io
import logging
import re
import zipfile
from collections import Counter
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TextIO

from intel.models import RATIO_MAX, RATIO_MIN
from intel.sources.base import AwardRow, ImportContext, Source, cpv_sector, register

log = logging.getLogger(__name__)

DATASET_API = "https://data.europa.eu/api/hub/search/datasets/ted-csv"
YEAR_URL = "https://data.europa.eu/api/hub/store/data/ted-contract-award-notices-{year}.zip"
FIRST_YEAR, LAST_YEAR = 2006, 2023  # frozen since 2024-01-25 (eForms replaced the forms)
_YEARLY_TITLE = re.compile(r"^TED - Contract award notices (\d{4})$")

COUNTRY_FIX = {"UK": "GB", "EL": "GR"}  # EU codes -> ISO 3166-1
CATEGORY = {"W": "works", "S": "services", "U": "goods"}
# TOP_TYPE, codebook 3.4. NIC/NIP (negotiated with a call) and the CFC spellings NEC/NEG
# are not open competition, but not a direct award either.
METHOD = {
    "OPE": "open",
    "RES": "limited",
    "NOC": "single",
    "NOP": "single",
    "AWP": "single",
    "COD": "other",
    "INP": "other",
    "NIC": "other",
    "NIP": "other",
    "NEC": "other",
    "NEG": "other",
}
# Beyond this an amount is a typo ("123456789"), and it would overflow the 20-digit
# real-rupee columns once converted.
MAX_EUR = Decimal("5e10")
MAX_BIDDERS = 999


def _amount(text: str) -> Decimal | None:
    try:
        value = Decimal(text.strip())
    except (InvalidOperation, AttributeError):
        return None
    return value if value.is_finite() and 0 < value < MAX_EUR else None


def parse_date(text: str) -> date | None:
    """'28/12/21' (2016 on), '15-DEC-06' (older files); four-digit years and ISO too."""
    text = (text or "").strip()
    for fmt in ("%d/%m/%y", "%d-%b-%y", "%d/%m/%Y", "%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.title() if "-" in text else text, fmt).date()
        except ValueError:
            continue
    return None


def open_csv(path: Path) -> Iterator[TextIO]:
    """The CSV text stream(s) inside a yearly zip (or a .csv.gz / .csv), never extracted."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".csv"):
                    with zf.open(name) as raw:
                        yield io.TextIOWrapper(
                            raw, encoding="utf-8-sig", errors="replace", newline=""
                        )
    elif path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8-sig", errors="replace", newline="") as fh:
            yield fh
    else:
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
            yield fh


@register
class TED(Source):
    key = "ted"
    name = "EU TED contract award notices (CSV subset, 2006-2023)"
    url = "https://data.europa.eu/data/datasets/ted-csv"
    license = "CC BY 4.0 / European Commission reuse notice (Decision 2011/833/EU), per year"
    kind = "outcomes"
    min_interval_seconds = 1.0

    def __init__(self):
        self.counts: Counter = Counter()

    def year_urls(self, ctx: ImportContext) -> dict[int, str]:
        """Yearly distributions from the data.europa.eu catalogue; the store URL pattern if
        the catalogue is unreachable or changes shape."""
        urls = {}
        try:
            payload = ctx.get(DATASET_API).json()
            for dist in (payload.get("result") or payload).get("distributions", []):
                title = dist.get("title") or {}
                title = title.get("en", "") if isinstance(title, dict) else str(title)
                m = _YEARLY_TITLE.match(title.strip())
                links = [*(dist.get("download_url") or []), *(dist.get("access_url") or [])]
                zips = [u for u in links if u.endswith(".zip")]
                if m and (zips or links):
                    urls[int(m.group(1))] = (zips or links)[0]
        except Exception as exc:  # the files are what matter; the listing is a convenience
            log.warning("ted: dataset listing failed (%s); using the URL pattern", exc)
        return urls or {y: YEAR_URL.format(year=y) for y in range(FIRST_YEAR, LAST_YEAR + 1)}

    def rows(self, ctx: ImportContext) -> Iterator[AwardRow]:
        if ctx.file:
            yield from self.read(ctx.file)
            return
        urls = self.year_urls(ctx)
        for year in sorted(y for y in urls if y >= (ctx.since or FIRST_YEAR)):
            name = f"ted-contract-award-notices-{year}{Path(urls[year]).suffix or '.zip'}"
            yield from self.read(ctx.download(urls[year], name=name))
        log.info("ted: %s", dict(self.counts))

    def read(self, path: Path) -> Iterator[AwardRow]:
        csv.field_size_limit(1 << 28)  # a few concatenated text fields are very long
        for fh in open_csv(path):
            reader = csv.reader(fh)
            header = [h.strip().upper() for h in next(reader, [])]
            for line, values in enumerate(reader, start=2):
                row = self.to_row(dict(zip(header, values, strict=False)), line)
                if row is not None:
                    yield row

    def skip(self, reason: str) -> None:
        self.counts[reason] += 1

    def to_row(self, r: dict[str, str], line: int = 0) -> AwardRow | None:
        """One CSV row -> AwardRow, or None (with the reason counted) when it cannot be a
        clean ratio row."""
        self.counts["rows"] += 1
        if r.get("CANCELLED") == "1" or r.get("INFO_ON_NON_AWARD"):
            return self.skip("cancelled_or_not_awarded")
        if (
            r.get("B_FRA_AGREEMENT") == "Y"
            or r.get("B_DYN_PURCH_SYST") == "Y"
            or r.get("B_FRA_CONTRACT") == "Y"
            or r.get("FRA_ESTIMATED")  # K keyword / A several awards per lot / C via the CN
        ):
            return self.skip("framework_or_dps")
        est, award = (
            _amount(r.get("AWARD_EST_VALUE_EURO", "")),
            _amount(r.get("AWARD_VALUE_EURO", "")),
        )
        if est is None or award is None:
            return self.skip("no_estimate_or_award")
        if est == award:
            return self.skip("award_equals_estimate")
        if not RATIO_MIN <= award / est <= RATIO_MAX:
            return self.skip("ratio_out_of_band")
        country = (r.get("ISO_COUNTRY_CODE") or "").strip().upper()
        country = COUNTRY_FIX.get(country, country)
        if not re.fullmatch(r"[A-Z]{2}", country):
            return self.skip("no_country")
        notice = (r.get("ID_NOTICE_CAN") or "").strip()
        if not notice:
            return self.skip("no_id")
        offers = (r.get("NUMBER_OFFERS") or "").strip()
        bidders = int(offers) if offers.isdigit() and 0 < int(offers) <= MAX_BIDDERS else None
        year = int(r["YEAR"]) if (r.get("YEAR") or "").strip().isdigit() else None
        awarded = parse_date(r.get("DT_AWARD", ""))
        if awarded is None or (year and not year - 10 <= awarded.year <= year):
            # Missing or mistyped: the notice was dispatched within weeks of the award.
            awarded = parse_date(r.get("DT_DISPATCH", ""))
        notice_url = (r.get("TED_NOTICE_URL") or "").strip()
        self.counts["emitted"] += 1
        return AwardRow(
            source_id=f"{notice}:{r.get('ID_AWARD') or r.get('ID_LOT') or line}",
            country=country,
            buyer=(r.get("CAE_NAME") or "").strip(),
            title=(r.get("TITLE") or "").replace("---", "; ").strip(),
            category=CATEGORY.get((r.get("TYPE_OF_CONTRACT") or "").strip(), ""),
            sector=cpv_sector(r.get("CPV")),
            method=METHOD.get((r.get("TOP_TYPE") or "").strip(), ""),
            currency="EUR",
            estimated_value=est,
            award_value=award,
            num_bidders=bidders,
            winner=(r.get("WIN_NAME") or "").replace("---", "; ").strip(),
            award_date=awarded,
            year=year,
            url=f"https://{notice_url}" if notice_url and "://" not in notice_url else notice_url,
        )
