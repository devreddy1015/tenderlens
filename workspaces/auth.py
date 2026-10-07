"""REST API keys: `Authorization: Api-Key tl_...`.

A key belongs to an organisation and acts as the member who created it, so everything
scoped "to the active organisation" (pipeline, exports, recommendations) works unchanged
through request.auth (see services.request_org). The key stops working when it is
revoked, when its creator leaves the organisation, or when the plan loses the `api`
feature (402, so the client knows an upgrade fixes it rather than a new key).
"""

import hashlib
import secrets
from datetime import timedelta

from django.utils import timezone
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import authentication, exceptions
from rest_framework.throttling import SimpleRateThrottle

from billing.entitlements import require_feature
from workspaces.models import ApiKey, Membership

KEY_PREFIX = "tl_"
VISIBLE_CHARS = 11  # "tl_" + 8: enough to tell keys apart in a list, useless to an attacker
# last_used_at is a hint for "is this key still in use?", not an audit log: writing it on
# every request would turn each read into a write.
LAST_USED_RESOLUTION = timedelta(minutes=5)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def create_key(org, user, name: str) -> tuple[ApiKey, str]:
    """A new key for org; returns (row, the secret key, which is never stored)."""
    key = new_key()
    row = ApiKey.objects.create(
        organization=org,
        name=name,
        prefix=key[:VISIBLE_CHARS],
        key_hash=hash_key(key),
        created_by=user,
    )
    return row, key


class ApiKeyAuthentication(authentication.BaseAuthentication):
    keyword = "Api-Key"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("latin-1")
        scheme, _, key = header.partition(" ")
        if scheme.lower() != self.keyword.lower():
            return None  # not ours: let session authentication try
        key = key.strip()
        if not key.startswith(KEY_PREFIX) or len(key) > 100:
            raise exceptions.AuthenticationFailed("Invalid API key.")
        row = (
            ApiKey.objects.select_related("organization", "created_by")
            .filter(key_hash=hash_key(key), revoked_at__isnull=True)
            .first()
        )
        if row is None or not row.created_by.is_active:
            raise exceptions.AuthenticationFailed("Invalid API key.")
        if not Membership.objects.filter(
            user_id=row.created_by_id, organization_id=row.organization_id
        ).exists():
            raise exceptions.AuthenticationFailed("This API key's owner left the organisation.")
        require_feature(row.organization, "api")
        now = timezone.now()
        if row.last_used_at is None or now - row.last_used_at > LAST_USED_RESOLUTION:
            ApiKey.objects.filter(pk=row.pk).update(last_used_at=now)
            row.last_used_at = now
        return row.created_by, row


class ApiKeyRateThrottle(SimpleRateThrottle):
    """Rate limit per API key (scope "api_key", settings API_KEY_RATE_LIMIT); requests
    signed in with a session are left to the user/anon throttles."""

    scope = "api_key"

    def get_cache_key(self, request, view):
        if not isinstance(request.auth, ApiKey):
            return None
        return self.cache_format % {"scope": self.scope, "ident": request.auth.pk}


class ApiKeyScheme(OpenApiAuthenticationExtension):
    """Documents the scheme in the OpenAPI schema (/api/docs/)."""

    target_class = "workspaces.auth.ApiKeyAuthentication"
    name = "ApiKeyAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "`Api-Key tl_...` (plan feature `api`)",
        }
