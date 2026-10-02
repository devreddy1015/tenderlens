import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from accounts import google
from accounts.models import GoogleIdentity

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def csrf_client():
    """A client that enforces CSRF like a browser would."""
    c = APIClient(enforce_csrf_checks=True)
    c.get("/api/auth/me")
    c.credentials(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return c


def fake_verify(**overrides):
    def _verify(credential):
        if credential != "good-token":
            raise google.InvalidGoogleToken("Token used too late")
        data = dict(
            sub="1234567890", email="rahul@example.com", name="Rahul Dev", picture="https://p/x.png"
        )
        data.update(overrides)
        return google.GoogleUser(**data)

    return _verify


def test_me_anonymous_sets_csrf_cookie():
    c = APIClient()
    r = c.get("/api/auth/me")
    assert r.json() == {"authenticated": False, "user": None}
    assert "csrftoken" in r.cookies


def test_google_login_creates_user_and_session(csrf_client, monkeypatch):
    monkeypatch.setattr("accounts.views.google.verify", fake_verify())
    r = csrf_client.post("/api/auth/google", {"credential": "good-token"}, format="json")
    assert r.status_code == 200
    assert r.json()["user"] == {
        "email": "rahul@example.com",
        "name": "Rahul Dev",
        "picture": "https://p/x.png",
    }
    assert csrf_client.get("/api/auth/me").json()["authenticated"] is True
    assert GoogleIdentity.objects.get().user.email == "rahul@example.com"


def test_google_login_again_reuses_user_even_if_email_changed(csrf_client, monkeypatch):
    monkeypatch.setattr("accounts.views.google.verify", fake_verify())
    csrf_client.post("/api/auth/google", {"credential": "good-token"}, format="json")
    monkeypatch.setattr("accounts.views.google.verify", fake_verify(email="new@example.com"))
    # Django rotates the CSRF token at login; a browser re-reads the cookie, so do we.
    csrf_client.credentials(HTTP_X_CSRFTOKEN=csrf_client.cookies["csrftoken"].value)
    r = csrf_client.post("/api/auth/google", {"credential": "good-token"}, format="json")
    assert r.status_code == 200
    assert User.objects.count() == 1
    assert User.objects.get().email == "new@example.com"


def test_bad_google_token_rejected(csrf_client, monkeypatch):
    monkeypatch.setattr("accounts.views.google.verify", fake_verify())
    r = csrf_client.post("/api/auth/google", {"credential": "forged"}, format="json")
    assert r.status_code == 400
    assert User.objects.count() == 0


def test_login_requires_csrf_token(monkeypatch):
    """Login CSRF: a hostile page must not be able to sign a visitor into its account."""
    monkeypatch.setattr("accounts.views.google.verify", fake_verify())
    c = APIClient(enforce_csrf_checks=True)
    r = c.post("/api/auth/google", {"credential": "good-token"}, format="json")
    assert r.status_code == 403


def test_real_verifier_refuses_when_not_configured(settings):
    settings.GOOGLE_CLIENT_ID = ""
    with pytest.raises(google.InvalidGoogleToken, match="not configured"):
        google.verify("anything")


def test_real_verifier_rejects_garbage(settings):
    settings.GOOGLE_CLIENT_ID = "123.apps.googleusercontent.com"
    with pytest.raises(google.InvalidGoogleToken):
        google.verify("not-a-jwt")


def test_dev_login_only_when_enabled(csrf_client, settings):
    settings.DEV_LOGIN_ENABLED = False
    assert (
        csrf_client.post("/api/auth/dev-login", {"email": "a@b.co"}, format="json").status_code
        == 404
    )
    settings.DEV_LOGIN_ENABLED = True
    r = csrf_client.post("/api/auth/dev-login", {"email": "A@B.co", "name": "Dev"}, format="json")
    assert r.json()["user"]["email"] == "a@b.co"


def test_dev_login_is_off_unless_debug():
    """The settings guard itself: DEV_LOGIN_ENABLED requires DEBUG."""
    import importlib
    import os

    os.environ["DEV_LOGIN_ENABLED"] = "true"
    os.environ["DJANGO_DEBUG"] = "false"
    try:
        import config.settings as s

        importlib.reload(s)
        assert s.DEV_LOGIN_ENABLED is False
    finally:
        del os.environ["DEV_LOGIN_ENABLED"], os.environ["DJANGO_DEBUG"]
        importlib.reload(s)


def test_logout(csrf_client, settings):
    settings.DEV_LOGIN_ENABLED = True
    csrf_client.post("/api/auth/dev-login", {"email": "a@b.co"}, format="json")
    csrf_client.credentials(HTTP_X_CSRFTOKEN=csrf_client.cookies["csrftoken"].value)
    r = csrf_client.post("/api/auth/logout")
    assert r.status_code == 200
    assert r.json()["authenticated"] is False
