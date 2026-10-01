"""Public tender portals. All run NIC's GePNIC software, so one parser handles them.

The central portal lists tenders from every state; there the state is derived from
the pincode. State portals list only their own state.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    base_url: str  # ends with /app
    state: str | None = None  # None means "derive from pincode"

    @property
    def origin(self) -> str:
        scheme, _, rest = self.base_url.partition("://")
        return f"{scheme}://{rest.split('/', 1)[0]}"

    @property
    def org_index_url(self) -> str:
        return f"{self.base_url}?page=FrontEndTendersByOrganisation&service=page"

    def absolute(self, href: str) -> str:
        if href.startswith("http"):
            return href
        return self.origin + href


SOURCES: dict[str, Source] = {
    s.key: s
    for s in [
        Source(
            "central",
            "Central Public Procurement Portal (GePNIC)",
            "https://eprocure.gov.in/eprocure/app",
        ),
        Source(
            "mp",
            "Madhya Pradesh e-Tendering",
            "https://mptenders.gov.in/nicgep/app",
            "Madhya Pradesh",
        ),
        Source(
            "odisha", "Odisha e-Procurement", "https://tendersodisha.gov.in/nicgep/app", "Odisha"
        ),
        Source("kerala", "Kerala e-Tenders", "https://etenders.kerala.gov.in/nicgep/app", "Kerala"),
        Source(
            "rajasthan",
            "Rajasthan e-Procurement",
            "https://eproc.rajasthan.gov.in/nicgep/app",
            "Rajasthan",
        ),
    ]
}


def get_source(key: str) -> Source:
    try:
        return SOURCES[key]
    except KeyError as exc:
        raise ValueError(f"unknown source {key!r}; known: {', '.join(SOURCES)}") from exc
