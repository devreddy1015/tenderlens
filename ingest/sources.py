"""Public tender portals TenderLens crawls.

Every portal here runs NIC's GePNIC software (kind="gepnic"), so one parser handles them.
Each one was verified with a single GET of its organisation index; dates and counts are in
docs/SOURCE_NOTES.md, along with the candidates that were rejected and why.

`state` is the state a portal serves. None means a multi-state portal (central government,
PSUs, defence): there the state is derived from each tender's pincode.

Other kinds ("gem", "cppp") are reserved for the adapter interface (ingest/pipeline.py).
No adapter exists for them: GeM's data endpoint and CPPP's listings are protected or
CAPTCHA-gated, and we never work around that (see docs/SOURCE_NOTES.md).
"""

from dataclasses import dataclass
from typing import Literal

Kind = Literal["gepnic", "gem", "cppp"]


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    base_url: str  # GePNIC: ends with /app
    state: str | None = None  # None means "derive from pincode"
    kind: Kind = "gepnic"
    # Registry switch: False keeps a known portal out of "all" (e.g. while it misbehaves).
    enabled: bool = True

    @property
    def origin(self) -> str:
        scheme, _, rest = self.base_url.partition("://")
        return f"{scheme}://{rest.split('/', 1)[0]}"

    @property
    def host(self) -> str:
        return self.origin.split("://", 1)[1]

    @property
    def org_index_url(self) -> str:
        return f"{self.base_url}?page=FrontEndTendersByOrganisation&service=page"

    @property
    def url(self) -> str:
        """The portal's public home page: where users go for documents and to bid."""
        return self.base_url

    def absolute(self, href: str) -> str:
        if href.startswith("http"):
            return href
        return self.origin + href


def _g(key: str, name: str, base_url: str, state: str | None = None) -> Source:
    return Source(key, name, base_url, state)


SOURCES: dict[str, Source] = {
    s.key: s
    for s in [
        # --- central government, PSUs, defence (state from pincode) ---------------------
        _g(
            "central",
            "Central Public Procurement Portal (GePNIC)",
            "https://eprocure.gov.in/eprocure/app",
        ),
        _g(
            "etenders",
            "Government eProcurement System (central PSUs)",
            "https://etenders.gov.in/eprocure/app",
        ),
        _g(
            "defence",
            "Defence eProcurement (Ministry of Defence)",
            "https://defproc.gov.in/nicgep/app",
        ),
        _g("mod-psu", "eProcurement for PSUs under MoD", "https://eprocuremdl.nic.in/nicgep/app"),
        _g("coalindia", "Coal India eTenders", "https://coalindiatenders.nic.in/nicgep/app"),
        _g("iocl", "Indian Oil Corporation eTenders", "https://iocletenders.nic.in/nicgep/app"),
        _g("ntpc", "NTPC eProcurement", "https://eprocurentpc.nic.in/nicgep/app"),
        _g("bhel", "BHEL eProcurement", "https://eprocurebhel.co.in/nicgep/app"),
        # --- states and union territories ------------------------------------------------
        _g(
            "mp",
            "Madhya Pradesh e-Tendering",
            "https://mptenders.gov.in/nicgep/app",
            "Madhya Pradesh",
        ),
        _g("odisha", "Odisha e-Procurement", "https://tendersodisha.gov.in/nicgep/app", "Odisha"),
        _g("kerala", "Kerala e-Tenders", "https://etenders.kerala.gov.in/nicgep/app", "Kerala"),
        _g(
            "rajasthan",
            "Rajasthan e-Procurement",
            "https://eproc.rajasthan.gov.in/nicgep/app",
            "Rajasthan",
        ),
        _g("haryana", "Haryana e-Tenders", "https://etenders.hry.nic.in/nicgep/app", "Haryana"),
        _g("up", "Uttar Pradesh e-Tender", "https://etender.up.nic.in/nicgep/app", "Uttar Pradesh"),
        _g(
            "uttarakhand",
            "Uttarakhand e-Tenders",
            "https://uktenders.gov.in/nicgep/app",
            "Uttarakhand",
        ),
        _g(
            "hp",
            "Himachal Pradesh e-Tenders",
            "https://hptenders.gov.in/nicgep/app",
            "Himachal Pradesh",
        ),
        _g(
            "jk",
            "Jammu and Kashmir e-Tenders",
            "https://jktenders.gov.in/nicgep/app",
            "Jammu and Kashmir",
        ),
        _g("punjab", "Punjab e-Procurement", "https://eproc.punjab.gov.in/nicgep/app", "Punjab"),
        _g(
            "delhi",
            "Delhi Government e-Procurement",
            "https://govtprocurement.delhi.gov.in/nicgep/app",
            "Delhi",
        ),
        _g(
            "chandigarh",
            "Chandigarh e-Tenders",
            "https://etenders.chd.nic.in/nicgep/app",
            "Chandigarh",
        ),
        _g("wb", "West Bengal e-Tenders", "https://wbtenders.gov.in/nicgep/app", "West Bengal"),
        _g(
            "jharkhand",
            "Jharkhand e-Tenders",
            "https://jharkhandtenders.gov.in/nicgep/app",
            "Jharkhand",
        ),
        _g("assam", "Assam e-Tenders", "https://assamtenders.gov.in/nicgep/app", "Assam"),
        _g(
            "arunachal",
            "Arunachal Pradesh e-Tenders",
            "https://arunachaltenders.gov.in/nicgep/app",
            "Arunachal Pradesh",
        ),
        _g("manipur", "Manipur e-Tenders", "https://manipurtenders.gov.in/nicgep/app", "Manipur"),
        _g(
            "meghalaya",
            "Meghalaya e-Tenders",
            "https://meghalayatenders.gov.in/nicgep/app",
            "Meghalaya",
        ),
        _g("mizoram", "Mizoram e-Tenders", "https://mizoramtenders.gov.in/nicgep/app", "Mizoram"),
        _g(
            "nagaland",
            "Nagaland e-Tenders",
            "https://nagalandtenders.gov.in/nicgep/app",
            "Nagaland",
        ),
        _g("sikkim", "Sikkim e-Tenders", "https://sikkimtender.gov.in/nicgep/app", "Sikkim"),
        _g("tripura", "Tripura e-Tenders", "https://tripuratenders.gov.in/nicgep/app", "Tripura"),
        _g("tn", "Tamil Nadu e-Tenders", "https://tntenders.gov.in/nicgep/app", "Tamil Nadu"),
        _g(
            "puducherry",
            "Puducherry e-Tenders",
            "https://pudutenders.gov.in/nicgep/app",
            "Puducherry",
        ),
        _g("goa", "Goa e-Procurement", "https://eprocure.goa.gov.in/nicgep/app", "Goa"),
        # Disabled: mahatenders.gov.in/robots.txt is "User-agent: * / Disallow: /" (checked
        # 2026-10-07), and we honour robots.txt. Re-enable only with the portal's permission.
        Source(
            "maharashtra",
            "Maharashtra e-Tenders",
            "https://mahatenders.gov.in/nicgep/app",
            "Maharashtra",
            enabled=False,
        ),
        _g(
            "dnh",
            "Dadra and Nagar Haveli e-Tenders",
            "https://dnhtenders.gov.in/nicgep/app",
            "Dadra and Nagar Haveli and Daman and Diu",
        ),
    ]
}


def get_source(key: str) -> Source:
    try:
        return SOURCES[key]
    except KeyError as exc:
        raise ValueError(f"unknown source {key!r}; known: {', '.join(SOURCES)}") from exc


def resolve_keys(keys: list[str] | tuple[str, ...]) -> list[str]:
    """CRAWLER_SOURCES -> source keys. "all" means every enabled source in registry order;
    blanks are ignored and unknown keys raise, so a typo fails at startup, not at 3 a.m."""
    out: list[str] = []
    for key in (k.strip() for k in keys):
        if not key:
            continue
        expanded = [s.key for s in SOURCES.values() if s.enabled] if key == "all" else [key]
        for k in expanded:
            get_source(k)
            if k not in out:
                out.append(k)
    return out
