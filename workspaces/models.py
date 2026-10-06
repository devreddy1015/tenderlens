from django.conf import settings
from django.db import models


class Organization(models.Model):
    """A customer: the unit that holds a plan, quotas, documents and the bid pipeline.

    Every user gets a personal organisation on first use (workspaces.services.get_active_org),
    so single users and teams go through the same code paths.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    plan_code = models.CharField(max_length=32, default="free")  # key into billing.plans.PLANS

    # Company profile: eligibility checks compare a tender's requirements with these, and
    # alerts use states/sectors as defaults.
    annual_turnover_inr = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="average annual turnover of the last 3 financial years",
    )
    largest_similar_work_inr = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    years_in_business = models.PositiveSmallIntegerField(null=True, blank=True)
    states = models.JSONField(default=list, blank=True)  # where they work
    sectors = models.JSONField(default=list, blank=True)  # tenders.sectors slugs
    # e.g. "MSE", "Startup (DPIIT)", "ISO 9001", "Class-A contractor"
    certifications = models.JSONField(default=list, blank=True)
    gstin = models.CharField(max_length=15, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "organization"

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner"
        ADMIN = "admin"
        MEMBER = "member"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    # The organisation the user is working in (one per user); see services.set_active_org.
    is_active = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "membership"
        constraints = [
            models.UniqueConstraint(fields=["user", "organization"], name="membership_user_org"),
            models.UniqueConstraint(
                fields=["user"], condition=models.Q(is_active=True), name="membership_one_active"
            ),
        ]

    def __str__(self):
        return f"{self.user} @ {self.organization} ({self.role})"
