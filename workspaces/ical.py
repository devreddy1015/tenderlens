"""The bid pipeline as an iCalendar (RFC 5545) feed, written by hand (no extra package).

Times are UTC ("...Z"), so no VTIMEZONE is needed and every calendar app shows them in the
user's own zone. UIDs are stable per tracked tender and event kind, so a changed closing
date updates the existing event instead of adding a second one.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone

from workspaces.models import BidTrack, Organization

PRODID = "-//TenderLens//Bid pipeline//EN"
EVENT_MINUTES = 30
PREBID_MINUTES = 60


def escape(text: str) -> str:
    """TEXT value escaping (RFC 5545 3.3.11): backslash, semicolon, comma, newline."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Split a content line into lines of at most 75 octets (RFC 5545 3.1), never inside a
    UTF-8 character; continuation lines start with one space."""
    out: list[str] = []
    current, size, limit = [], 0, 75
    for ch in line:
        n = len(ch.encode())
        if size + n > limit:
            out.append("".join(current))
            current, size, limit = [], 0, 74  # the leading space takes one octet
        current.append(ch)
        size += n
    out.append("".join(current))
    return "\r\n ".join(out)


def utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _host() -> str:
    return urlsplit(settings.SITE_URL).hostname or "tenderlens"


def events(track: BidTrack) -> list[list[str]]:
    """Content lines (unfolded) of the track's events: bid submission end, and the pre-bid
    meeting and bid opening when the tender has them."""
    t = track.tender
    page = f"{settings.SITE_URL}/tenders/{t.pk}"
    stamp = [
        f"DESCRIPTION:{escape(_description(track, page))}",
        f"URL:{page}",
        f"LAST-MODIFIED:{utc(track.updated_at)}",
        f"DTSTAMP:{utc(track.updated_at)}",
    ]
    lines_common = [*stamp, f"LOCATION:{escape(t.location)}"] if t.location else stamp
    out = [
        [
            "BEGIN:VEVENT",
            f"UID:bidtrack-{track.pk}-due@{_host()}",
            f"SUMMARY:{escape('Bid due: ' + t.title)}",
            f"DTSTART:{utc(t.closes_at - timedelta(minutes=EVENT_MINUTES))}",
            f"DTEND:{utc(t.closes_at)}",
            *lines_common,
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{escape('Bid due tomorrow: ' + t.title)}",
            "TRIGGER:-P1D",
            "END:VALARM",
            "END:VEVENT",
        ]
    ]
    if t.prebid_meeting and t.prebid_meeting <= t.closes_at:
        # No LOCATION: the work's location is not where the meeting is held (the notice
        # gives the venue, and the description links to it).
        out.append(
            [
                "BEGIN:VEVENT",
                f"UID:bidtrack-{track.pk}-prebid@{_host()}",
                f"SUMMARY:{escape('Pre-bid meeting: ' + t.title)}",
                f"DTSTART:{utc(t.prebid_meeting)}",
                f"DTEND:{utc(t.prebid_meeting + timedelta(minutes=PREBID_MINUTES))}",
                *stamp,
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{escape('Pre-bid meeting tomorrow: ' + t.title)}",
                "TRIGGER:-P1D",
                "END:VALARM",
                "END:VEVENT",
            ]
        )
    if t.opens_at and t.opens_at > t.closes_at:
        out.append(
            [
                "BEGIN:VEVENT",
                f"UID:bidtrack-{track.pk}-opening@{_host()}",
                f"SUMMARY:{escape('Bid opening: ' + t.title)}",
                f"DTSTART:{utc(t.opens_at)}",
                f"DTEND:{utc(t.opens_at + timedelta(minutes=EVENT_MINUTES))}",
                *lines_common,
                "END:VEVENT",
            ]
        )
    return out


def _description(track: BidTrack, page: str) -> str:
    t = track.tender
    parts = [
        t.title,
        f"Tender ID: {t.source_tender_id}",
        f"Buyer: {t.buyer_raw}",
        f"Status in your pipeline: {track.status}",
        f"TenderLens: {page}",
    ]
    if t.url:
        parts.append(f"Source portal: {t.url}")
    return "\n".join(parts)


def calendar(org: Organization) -> str:
    """The feed: the organisation's tracked tenders that are not submitted yet and close
    in the last 30 days or later (old deadlines drop out of the feed)."""
    tracks = (
        BidTrack.objects.filter(
            organization=org,
            status__in=BidTrack.OPEN_STATUSES,
            tender__closes_at__gte=timezone.now() - timedelta(days=30),
        )
        .select_related("tender")
        .order_by("tender__closes_at", "id")
    )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape(f'TenderLens: {org.name}')}",
        "X-WR-CALDESC:Pre-bid meetings and bid deadlines in your TenderLens pipeline",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    for track in tracks:
        for event in events(track):
            lines += event
    lines.append("END:VCALENDAR")
    return "".join(fold(line) + "\r\n" for line in lines)
