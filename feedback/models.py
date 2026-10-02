from django.conf import settings
from django.db import models


class Feedback(models.Model):
    class Kind(models.TextChoices):
        BUG = "bug", "Bug"
        DATA = "data", "Wrong or missing data"
        IDEA = "idea", "Idea or request"
        PRIVATE_WAITLIST = "private_waitlist", "Private tenders waitlist"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        NEW = "new"
        SEEN = "seen"
        DONE = "done"

    kind = models.CharField(max_length=24, choices=Kind.choices)
    message = models.TextField(max_length=4000, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    page = models.CharField(max_length=500, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    user_agent = models.CharField(max_length=300, blank=True, default="")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.NEW)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "feedback"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.message[:60]}"
