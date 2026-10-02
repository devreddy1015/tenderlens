"""Builds and sends alert digest emails (HTML + plain text)."""

from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from alerts.matching import describe_area
from tenders.sectors import SECTOR_BY_SLUG

UNSUBSCRIBE_SALT = "alerts.unsubscribe"


def unsubscribe_token(sub) -> str:
    return signing.dumps({"s": sub.pk}, salt=UNSUBSCRIBE_SALT)


def read_unsubscribe_token(token: str) -> int:
    """Raises signing.BadSignature for tampered or foreign tokens. Tokens don't expire:
    an unsubscribe link in an old email must keep working."""
    return int(signing.loads(token, salt=UNSUBSCRIBE_SALT)["s"])


def format_inr(value) -> str:
    if value is None:
        return "Not disclosed"
    v = float(value)
    if v == 0:
        return "Not disclosed"
    if v >= 1e7:
        return f"₹{v / 1e7:,.2f} crore"
    if v >= 1e5:
        return f"₹{v / 1e5:,.2f} lakh"
    return f"₹{v:,.0f}"


def _row(t, now) -> dict:
    days = (t.closes_at - now).days
    return {
        "title": t.title,
        "url": f"{settings.SITE_URL}/tenders/{t.pk}",
        "buyer": t.buyer_entity.canonical_name if t.buyer_entity_id else t.buyer_raw,
        "where": ", ".join(p for p in (t.location, t.state) if p),
        "value": format_inr(t.value_inr),
        "closes": timezone.localtime(t.closes_at).strftime("%d %b %Y, %I:%M %p"),
        "closes_in": "today" if days < 1 else f"in {days} day{'s' if days != 1 else ''}",
        "urgent": days < 3,
        "sector": SECTOR_BY_SLUG.get(t.sector).label if t.sector in SECTOR_BY_SLUG else "",
        "tender_id": t.source_tender_id,
    }


def build_digest(
    sub, tenders, *, first: bool, total: int, test: bool = False
) -> EmailMultiAlternatives:
    now = timezone.now()
    area = describe_area(sub)
    n = len(tenders)
    if test:
        subject = f"[Test] {sub.name}: {total} open tender{'s' if total != 1 else ''} match"
    elif first:
        subject = f"{total} open tender{'s' if total != 1 else ''} in {area} match “{sub.name}”"
    else:
        subject = f"{n} new tender{'s' if n != 1 else ''} in {area}: {sub.name}"
    unsubscribe = f"{settings.SITE_URL}/api/alerts/unsubscribe?token={unsubscribe_token(sub)}"
    ctx = {
        "sub": sub,
        "area": area,
        "sectors": [SECTOR_BY_SLUG[s].label for s in sub.sectors if s in SECTOR_BY_SLUG],
        "rows": [_row(t, now) for t in tenders],
        "total": total,
        "more": max(0, total - n),
        "first": first,
        "test": test,
        "site_url": settings.SITE_URL,
        "manage_url": f"{settings.SITE_URL}/alerts",
        "search_url": f"{settings.SITE_URL}/tenders",
        "unsubscribe_url": unsubscribe,
    }
    msg = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string("alerts/digest.txt", ctx),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[sub.user.email],
        headers={
            "List-Unsubscribe": f"<{unsubscribe}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    )
    msg.attach_alternative(render_to_string("alerts/digest.html", ctx), "text/html")
    return msg
