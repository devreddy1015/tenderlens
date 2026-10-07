"""Which organisation a request acts for, and who may do what in it."""

import secrets

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils.text import slugify
from rest_framework.exceptions import PermissionDenied

from workspaces.models import Membership, Organization


def get_active_org(user) -> Organization:
    """The organisation `user` is working in. The first call creates a personal
    organisation with the user as owner, so every signed-in user has exactly one place
    for their plan, quotas and documents. Safe under concurrent first requests."""
    org = _active(user)
    if org is not None:
        return org
    with transaction.atomic():
        # Serialise first use per user: two parallel requests must not create two orgs.
        get_user_model().objects.select_for_update().filter(pk=user.pk).first()
        org = _active(user)
        if org is not None:
            return org
        membership = user.memberships.select_related("organization").order_by("-joined_at").first()
        if membership is not None:  # member somewhere, nothing marked active (e.g. admin-made)
            Membership.objects.filter(pk=membership.pk).update(is_active=True)
            return membership.organization
        org = _create_org(_personal_name(user))
        Membership.objects.create(
            user=user, organization=org, role=Membership.Role.OWNER, is_active=True
        )
        return org


def set_active_org(user, org: Organization) -> Membership:
    """Switch the user's working organisation (they must be a member)."""
    with transaction.atomic():
        membership = require_role(user, org)
        Membership.objects.filter(user=user, is_active=True).exclude(pk=membership.pk).update(
            is_active=False
        )
        if not membership.is_active:
            membership.is_active = True
            membership.save(update_fields=["is_active"])
    return membership


def require_role(user, org: Organization, *roles: str) -> Membership:
    """The user's membership of `org`; raises PermissionDenied (403) when they are not a
    member or, if roles are given, their role is not one of them."""
    membership = Membership.objects.filter(user_id=user.pk, organization=org).first()
    if membership is None:
        raise PermissionDenied("You are not a member of this organisation.")
    if roles and membership.role not in roles:
        raise PermissionDenied(f"This needs the {' or '.join(roles)} role.")
    return membership


def _active(user) -> Organization | None:
    m = (
        Membership.objects.filter(user_id=user.pk, is_active=True)
        .select_related("organization")
        .first()
    )
    return m.organization if m else None


def _personal_name(user) -> str:
    name = (user.get_full_name() or "").strip()
    if not name:
        name = (user.email or user.get_username()).split("@")[0]
    return name[:200] or "My workspace"


def _create_org(name: str) -> Organization:
    base = slugify(name)[:60] or "org"
    slug = base
    for _ in range(10):
        if not Organization.objects.filter(slug=slug).exists():
            try:
                with transaction.atomic():
                    return Organization.objects.create(name=name, slug=slug)
            except IntegrityError:  # taken by a concurrent signup
                pass
        slug = f"{base}-{secrets.token_hex(3)}"
    raise RuntimeError("could not find a free organisation slug")


def request_org(request) -> Organization:
    """The organisation a request acts for: an API key's own organisation, otherwise the
    signed-in user's active one."""
    from workspaces.models import ApiKey

    if isinstance(request.auth, ApiKey):
        return request.auth.organization
    return get_active_org(request.user)


def calendar_token(org: Organization, *, rotate: bool = False) -> str:
    """The organisation's iCal feed token, created on first use; rotate=True replaces it
    so the old feed URL stops working."""
    if org.calendar_token and not rotate:
        return org.calendar_token
    org.calendar_token = secrets.token_urlsafe(32)
    org.save(update_fields=["calendar_token"])
    return org.calendar_token


def seats_used(org: Organization) -> int:
    """Members plus open invites: an invite holds a seat until it is accepted, revoked or
    expires, so a team cannot invite past its plan and have everyone accept later."""
    from django.utils import timezone

    pending = org.invites.filter(
        accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now()
    ).count()
    return org.memberships.count() + pending
