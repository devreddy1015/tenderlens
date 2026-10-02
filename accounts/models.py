from django.conf import settings
from django.db import models


class GoogleIdentity(models.Model):
    """Links a Django user to the Google account they signed in with.

    `sub` is Google's stable account id. Email addresses can change; `sub` cannot.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="google"
    )
    sub = models.CharField(max_length=64, unique=True)
    picture = models.URLField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
