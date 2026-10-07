"""Daily closing-date reminders for the bid pipeline."""

import logging
from collections import defaultdict
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from workspaces.models import BidTrack, Membership, ReminderLog

log = logging.getLogger(__name__)
REMIND_DAYS = 3


def recipients(track: BidTrack) -> list:
    """The track's owner, or the organisation's owners and admins when nobody owns it."""
    if track.owner_id and track.owner.is_active and track.owner.email:
        is_member = Membership.objects.filter(
            user_id=track.owner_id, organization_id=track.organization_id
        ).exists()
        if is_member:
            return [track.owner]
    users = get_user_model().objects.filter(
        memberships__organization_id=track.organization_id,
        memberships__role__in=[Membership.Role.OWNER, Membership.Role.ADMIN],
        is_active=True,
    )
    return [u for u in users.order_by("pk") if u.email]


def _claim(track: BidTrack, user, day) -> bool:
    """Record today's reminder for (track, user); False when one was already recorded."""
    try:
        with transaction.atomic():
            ReminderLog.objects.create(bid_track=track, user=user, day=day)
        return True
    except IntegrityError:
        return False


def _body(tracks: list[BidTrack]) -> str:
    lines = ["These tenders in your TenderLens pipeline close soon and are not submitted yet:", ""]
    for tr in tracks:
        t = tr.tender
        lines += [
            f"- {t.title}",
            f"  Closes {timezone.localtime(t.closes_at):%a %d %b %Y, %I:%M %p} IST"
            f" | status: {tr.status} | tender ID {t.source_tender_id}",
            f"  {settings.SITE_URL}/tenders/{t.pk}",
            "",
        ]
    lines.append(f"Your pipeline: {settings.SITE_URL}/pipeline")
    return "\n".join(lines)


@shared_task
def send_pipeline_reminders() -> int:
    """Email each tracked tender's owner (else the organisation's owners and admins) about
    tenders closing within REMIND_DAYS that are still being watched or prepared. One email
    per person per organisation per day; ReminderLog makes re-runs send nothing new.
    Returns the number of emails sent."""
    now = timezone.now()
    day = timezone.localdate(now)
    tracks = (
        BidTrack.objects.filter(
            status__in=BidTrack.OPEN_STATUSES,
            tender__closes_at__gt=now,
            tender__closes_at__lte=now + timedelta(days=REMIND_DAYS),
        )
        .select_related("tender", "organization", "owner")
        .order_by("tender__closes_at", "id")
    )
    batches: dict[tuple[int, int], list[BidTrack]] = defaultdict(list)
    users = {}
    for track in tracks:
        for user in recipients(track):
            if _claim(track, user, day):
                batches[(user.pk, track.organization_id)].append(track)
                users[user.pk] = user
    sent = 0
    for (user_pk, _org), items in batches.items():
        user, org = users[user_pk], items[0].organization
        n = len(items)
        subject = (
            f"{n} tender{'s' if n > 1 else ''} in {org.name}'s pipeline close"
            f"{'s' if n == 1 else ''} within {REMIND_DAYS} days"
        )
        try:
            send_mail(subject, _body(items), None, [user.email])
            sent += 1
        except Exception:
            # Let tomorrow's run (or a retry) try again for these.
            ReminderLog.objects.filter(bid_track__in=items, user=user, day=day).delete()
            log.exception("pipeline reminder to user %s failed", user_pk)
    return sent
