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
    # Authenticates the pipeline's iCal feed (calendar apps cannot send a session cookie).
    # Created on first use (services.calendar_token), rotated by an owner or admin.
    calendar_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    # Bid outcomes recorded in the pipeline (L1, bidders) train the shared bid price model
    # (intel.outcomes). On by default with a clear notice; off keeps them for this
    # organisation's own comparables only. Names never leave the organisation either way.
    contribute_outcomes = models.BooleanField(default=True)
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


class Invite(models.Model):
    """An emailed invitation to join an organisation. The link carries a signed token
    (see workspaces.invites); only its nonce's SHA-256 is stored, so a database leak does
    not leak working links. Single use (accepted_at) and expiring (expires_at)."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invites")
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=Membership.Role.choices)
    nonce_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "workspace_invite"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email} -> {self.organization} ({self.role})"


# More bids than this on one tender is a typo, not a market.
MAX_BIDDERS = 500


class BidTrack(models.Model):
    """A tender in an organisation's bid pipeline (one row per organisation and tender)."""

    class Status(models.TextChoices):
        WATCHING = "watching"
        PREPARING = "preparing"
        SUBMITTED = "submitted"
        WON = "won"
        LOST = "lost"
        DROPPED = "dropped"

    # Not submitted yet: these get closing-date reminders and calendar events.
    OPEN_STATUSES = (Status.WATCHING, Status.PREPARING)
    # Money still in play (summary.value_inr_in_play).
    LIVE_STATUSES = (Status.WATCHING, Status.PREPARING, Status.SUBMITTED)

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="bid_tracks"
    )
    tender = models.ForeignKey("tenders.Tender", on_delete=models.CASCADE, related_name="+")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.WATCHING)
    notes = models.TextField(blank=True, default="")
    bid_amount_inr = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    # The result, once known: the lowest (winning) price, who won, how many bid and where
    # we ranked. With a won/lost status these become a training row (intel.outcomes).
    l1_amount_inr = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    winner_name = models.TextField(blank=True, default="")
    num_bidders = models.PositiveSmallIntegerField(null=True, blank=True)
    our_rank = models.PositiveSmallIntegerField(null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bid_track"
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "tender"], name="bidtrack_org_tender"),
            models.CheckConstraint(
                condition=models.Q(bid_amount_inr__isnull=True) | models.Q(bid_amount_inr__gte=0),
                name="bidtrack_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(l1_amount_inr__isnull=True) | models.Q(l1_amount_inr__gte=0),
                name="bidtrack_l1_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(num_bidders__isnull=True)
                | models.Q(num_bidders__gte=1, num_bidders__lte=MAX_BIDDERS),
                name="bidtrack_num_bidders_range",
            ),
            models.CheckConstraint(
                condition=models.Q(our_rank__isnull=True)
                | (
                    models.Q(our_rank__gte=1)
                    & (
                        models.Q(num_bidders__isnull=True)
                        | models.Q(our_rank__lte=models.F("num_bidders"))
                    )
                ),
                name="bidtrack_rank_within_bidders",
            ),
        ]

    def __str__(self):
        return f"{self.organization} / {self.tender_id} ({self.status})"


class ReminderLog(models.Model):
    """One closing-date reminder sent for a tracked tender to one person on one day; the
    unique constraint makes the daily job idempotent (a re-run or retry sends nothing)."""

    bid_track = models.ForeignKey(BidTrack, on_delete=models.CASCADE, related_name="reminders")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    day = models.DateField()  # IST
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bid_reminder_log"
        constraints = [
            models.UniqueConstraint(
                fields=["bid_track", "user", "day"], name="reminder_track_user_day"
            )
        ]

    def __str__(self):
        return f"{self.bid_track_id} -> {self.user_id} on {self.day}"


class ApiKey(models.Model):
    """A REST API key: "tl_" + 43 random URL-safe characters. Only the SHA-256 and a
    visible prefix are stored; the key itself is shown once, when created. Requests made
    with it act as `created_by` inside `organization` (workspaces.auth)."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="api_keys"
    )
    name = models.CharField(max_length=100)
    prefix = models.CharField(max_length=16)  # "tl_" + 8 characters, to recognise a key
    key_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_keys"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "api_key"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.prefix}… ({self.organization})"
