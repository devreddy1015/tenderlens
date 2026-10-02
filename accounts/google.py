"""Verifies a Google Identity Services credential (an ID token) on the server.

The browser never sends us a password or an access token: Google signs a short-lived
JWT that says who the user is, and we check the signature, audience and expiry here.
"""

from dataclasses import dataclass

from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class InvalidGoogleToken(Exception):
    pass


@dataclass
class GoogleUser:
    sub: str
    email: str
    name: str
    picture: str


def verify(credential: str) -> GoogleUser:
    if not settings.GOOGLE_CLIENT_ID:
        raise InvalidGoogleToken("Google sign-in is not configured")
    try:
        info = id_token.verify_oauth2_token(
            credential, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )
    except ValueError as exc:  # bad signature, wrong audience, expired
        raise InvalidGoogleToken(str(exc)) from exc
    if info.get("iss") not in ISSUERS:
        raise InvalidGoogleToken("unexpected issuer")
    if not info.get("email") or not info.get("email_verified"):
        raise InvalidGoogleToken("Google account has no verified email")
    return GoogleUser(
        sub=info["sub"],
        email=info["email"].lower(),
        name=info.get("name", ""),
        picture=info.get("picture", ""),
    )
