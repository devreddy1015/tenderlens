"""Parsers for NIC GePNIC portal pages. Pure functions: HTML string in, dataclasses out.

Three page kinds are used, all public and CAPTCHA-free:
  * organisation index  (FrontEndTendersByOrganisation)  -> OrgRow per organisation
  * organisation listing (DirectLink from the index)     -> ListingRow per tender
  * tender detail        (FrontEndViewTender)             -> dict of raw caption -> value
"""

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

_WS = re.compile(r"\s+")


class StaleSession(Exception):
    """The portal discarded our session; links are fine, the cookie is not."""


class NotADetailPage(Exception):
    """The page is not a tender detail page (error page, layout change, ...)."""


@dataclass(frozen=True)
class OrgRow:
    name: str
    tender_count: int
    href: str


@dataclass(frozen=True)
class ListingRow:
    published: str
    closes: str
    opens: str
    title: str
    ref_no: str
    tender_id: str
    org_chain: str
    href: str


def clean(text: str | None) -> str:
    if text is None:
        return ""
    return _WS.sub(" ", text.replace("\xa0", " ")).strip()


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def is_stale_session(html: str) -> bool:
    return "Stale Session" in html and "session has timed out" in html


def parse_org_index(html: str) -> list[OrgRow]:
    if is_stale_session(html):
        raise StaleSession()
    rows: list[OrgRow] = []
    seen: set[str] = set()
    for a in _soup(html).find_all("a", href=True):
        href = a["href"]
        if "page=FrontEndTendersByOrganisation" not in href or "sp=" not in href:
            continue
        tr = a.find_parent("tr")
        if tr is None:
            continue
        cells = [clean(td.get_text(" ")) for td in tr.find_all("td", recursive=False)]
        count_text = clean(a.get_text())
        if not count_text.isdigit() or len(cells) < 3:
            continue
        name = cells[1]
        if name in seen:
            continue
        seen.add(name)
        rows.append(OrgRow(name=name, tender_count=int(count_text), href=href))
    return rows


_BRACKETS = re.compile(r"\[([^\[\]]*)\]")


def _split_title_cell(td) -> tuple[str, str, str, str]:
    """'[Title] [Ref.No][Tender ID]' -> (title, ref_no, tender_id, href)."""
    a = td.find("a", href=True)
    href = a["href"] if a else ""
    title = clean(a.get_text()) if a else ""
    if title.startswith("[") and title.endswith("]"):
        title = title[1:-1].strip()
    rest = clean(td.get_text(" "))
    if a is not None:
        rest = rest.replace(clean(a.get_text(" ")), "", 1)
    parts = [clean(p) for p in _BRACKETS.findall(rest)]
    tender_id = parts[-1] if parts else ""
    ref_no = parts[-2] if len(parts) >= 2 else ""
    return title, ref_no, tender_id, href


def parse_org_listing(html: str) -> list[ListingRow]:
    if is_stale_session(html):
        raise StaleSession()
    soup = _soup(html)
    table = soup.find("table", id="table")
    if table is None:
        return []
    rows: list[ListingRow] = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 6 or not tr.find("a", href=re.compile("FrontEndViewTender")):
            continue
        title, ref_no, tender_id, href = _split_title_cell(tds[4])
        rows.append(
            ListingRow(
                published=clean(tds[1].get_text()),
                closes=clean(tds[2].get_text()),
                opens=clean(tds[3].get_text()),
                title=title,
                ref_no=ref_no,
                tender_id=tender_id,
                org_chain=clean(tds[5].get_text()),
                href=href,
            )
        )
    return rows


# Captions are matched after whitespace cleanup; the rupee sign varies between
# "₹" and "Rs." across portal versions, so both spellings are accepted.
DETAIL_FIELDS = {
    "org_chain": ["Organisation Chain"],
    "ref_no": ["Tender Reference Number"],
    "tender_id": ["Tender ID"],
    "tender_type": ["Tender Type"],
    "category": ["Tender Category"],
    "fee": ["Tender Fee in ₹", "Tender Fee in Rs."],
    "emd": ["EMD Amount in ₹", "EMD Amount in Rs."],
    "title": ["Title"],
    "description": ["Work Description"],
    "value": ["Tender Value in ₹", "Tender Value in Rs."],
    "product_category": ["Product Category"],
    "sub_category": ["Sub category"],
    "location": ["Location"],
    "pincode": ["Pincode"],
    "published": ["Published Date"],
    "opens": ["Bid Opening Date"],
    "prebid": ["Pre Bid Meeting Date"],
    "submission_start": ["Bid Submission Start Date"],
    "closes": ["Bid Submission End Date"],
    "inviting_authority": ["Name"],
    "inviting_address": ["Address"],
}


def parse_detail(html: str) -> dict[str, str]:
    """Return raw strings keyed by DETAIL_FIELDS names. Validation happens elsewhere."""
    if is_stale_session(html):
        raise StaleSession()
    soup = _soup(html)
    captions: dict[str, str] = {}
    for cap in soup.select("td.td_caption"):
        key = clean(cap.get_text(" "))
        value_td = cap.find_next_sibling("td")
        if value_td is None or key in captions:
            continue  # first occurrence wins ("Name" also appears in creator details)
        captions[key] = clean(value_td.get_text(" "))
    if "Tender ID" not in captions and "Organisation Chain" not in captions:
        raise NotADetailPage("no 'Tender ID' or 'Organisation Chain' caption found")
    out: dict[str, str] = {}
    for field, labels in DETAIL_FIELDS.items():
        for label in labels:
            if label in captions:
                out[field] = captions[label]
                break
    out["documents"] = ", ".join(_document_names(soup))
    return out


def _document_names(soup: BeautifulSoup) -> list[str]:
    names = []
    for a in soup.find_all("a", href=True):
        text = clean(a.get_text())
        if re.search(r"\.(pdf|xlsx?|docx?|zip|rar)$", text, re.I):
            names.append(text)
    return names
