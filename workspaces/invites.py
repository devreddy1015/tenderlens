"""Invitations: a signed, expiring, single-use link emailed to the invitee.

The token is `django.core.signing` of {"i": invite id, "n": random nonce}: the signature
rejects forged or edited links without a query, the timestamp enforces expiry, and the
nonce (stored only as a SHA-256) ties the link to one Invite row, which is marked accepted
under a row lock, so a link works once even when clicked twice at the same moment.
"""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from billing.entitlements import ensure_capacity
from workspaces.models import Invite, Membership, Organization
from workspaces.services import seats_used, set_active_org

SALT = "workspaces.invite"


def max_age() -> timedelta:
    return timedelta(days=settings.INVITE_MAX_AGE_DAYS)


def _hash(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()


def invite_url(token: str) -> str:
    return f"{settings.SITE_URL}/invite/{token}"


def create_invite(org: Organization, inviter, email: str, role: str) -> tuple[Invite, str]:
    """Create an invite and email its link; returns (invite, token). Raises QuotaExceeded
    when the plan has no free seat (members + open invites)."""
    email = email.strip().lower()
    if org.memberships.filter(user__email__iexact=email).exists():
        raise ValidationError({"email": "This person is already a member."})
    with transaction.atomic():
        # Serialise invites per organisation so two parallel invites cannot share a seat.
        Organization.objects.select_for_update().filter(pk=org.pk).first()
        # Re-inviting the same address replaces the earlier open invite.
        org.invites.filter(email__iexact=email, accepted_at__isnull=True).update(
            revoked_at=timezone.now()
        )
        ensure_capacity(org, "seats", current=seats_used(org))
        nonce = secrets.token_urlsafe(24)
        invite = Invite.objects.create(
            organization=org,
            email=email,
            role=role,
            nonce_hash=_hash(nonce),
            invited_by=inviter,
            expires_at=timezone.now() + max_age(),
        )
    token = signing.dumps({"i": invite.pk, "n": nonce}, salt=SALT, compress=True)
    who = (inviter.get_full_name() or inviter.email) if inviter else "A teammate"
    send_mail(
        subject=f"{who} invited you to {org.name} on TenderLens",
        message=(
            f"{who} invited you to join {org.name} on TenderLens as {role}.\n\n"
            f"Accept the invitation: {invite_url(token)}\n\n"
            f"Sign in with {email} to accept. The link works once and expires on "
            f"{timezone.localtime(invite.expires_at):%d %b %Y}.\n"
        ),
        from_email=None,
        recipient_list=[email],
    )
    return invite, token


def read_token(token: str) -> Invite:
    """The open invite a token points at; NotFound for a bad, expired, used or revoked
    link (one message for all, so the endpoint reveals nothing about other invites)."""
    gone = NotFound("This invitation link is not valid any more. Ask for a new one.")
    try:
        data = signing.loads(token, salt=SALT, max_age=max_age())
    except signing.BadSignature:  # includes SignatureExpired
        raise gone from None
    invite = (
        Invite.objects.select_related("organization").filter(pk=data.get("i")).first()
        if isinstance(data, dict)
        else None
    )
    if (
        invite is None
        or not secrets.compare_digest(invite.nonce_hash, _hash(str(data.get("n", ""))))
        or invite.accepted_at is not None
        or invite.revoked_at is not None
        or invite.expires_at <= timezone.now()
    ):
        raise gone
    return invite


def accept(token: str, user) -> Membership:
    """Join the invite's organisation as `user` (whose email must be the invited one) and
    make it their active organisation."""
    invite = read_token(token)
    if (user.email or "").strip().lower() != invite.email:
        raise PermissionDenied(
            f"This invitation is for {invite.email}. Sign in with that address to accept it."
        )
    with transaction.atomic():
        invite = Invite.objects.select_for_update().get(pk=invite.pk)
        if invite.accepted_at is not None or invite.revoked_at is not None:
            raise NotFound("This invitation link is not valid any more. Ask for a new one.")
        org = invite.organization
        membership = Membership.objects.filter(user=user, organization=org).first()
        if membership is None:
            # The invite already holds a seat, so this checks members only.
            ensure_capacity(org, "seats", current=org.memberships.count())
            membership = Membership.objects.create(user=user, organization=org, role=invite.role)
        invite.accepted_at = timezone.now()
        invite.accepted_by = user
        invite.save(update_fields=["accepted_at", "accepted_by"])
        set_active_org(user, org)
    membership.refresh_from_db()
    return membership
