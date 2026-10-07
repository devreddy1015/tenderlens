from rest_framework import serializers

from api.serializers import TenderSerializer
from tenders.sectors import SECTOR_BY_SLUG
from workspaces.models import MAX_BIDDERS, ApiKey, BidTrack, Invite, Membership, Organization

PROFILE_FIELDS = [
    "annual_turnover_inr",
    "largest_similar_work_inr",
    "years_in_business",
    "states",
    "sectors",
    "certifications",
    "gstin",
]


def _string_list(value, *, field: str, max_items: int = 50, max_len: int = 100) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise serializers.ValidationError(f"{field} must be a list of strings.")
    cleaned = []
    for v in value:
        v = v.strip()
        if v and v not in cleaned:
            if len(v) > max_len:
                raise serializers.ValidationError(f"{field}: '{v[:20]}…' is too long.")
            cleaned.append(v)
    if len(cleaned) > max_items:
        raise serializers.ValidationError(f"{field}: at most {max_items} entries.")
    return cleaned


class OrganizationUpdateSerializer(serializers.ModelSerializer):
    """PATCH /api/workspace: name, company-profile fields (flat or under "profile") and
    contribute_outcomes."""

    class Meta:
        model = Organization
        fields = ["name", *PROFILE_FIELDS, "contribute_outcomes"]
        extra_kwargs = {
            "annual_turnover_inr": {"min_value": 0},
            "largest_similar_work_inr": {"min_value": 0},
            "years_in_business": {"max_value": 200},
        }

    def to_internal_value(self, data):
        if isinstance(data, dict) and isinstance(data.get("profile"), dict):
            data = {**{k: v for k, v in data.items() if k != "profile"}, **data["profile"]}
        return super().to_internal_value(data)

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be empty.")
        return value

    def validate_states(self, value):
        return _string_list(value, field="states", max_items=40, max_len=64)

    def validate_sectors(self, value):
        value = _string_list(value, field="sectors", max_items=40, max_len=32)
        unknown = [v for v in value if v not in SECTOR_BY_SLUG]
        if unknown:
            raise serializers.ValidationError(f"Unknown sectors: {', '.join(unknown)}.")
        return value

    def validate_certifications(self, value):
        return _string_list(value, field="certifications", max_items=50, max_len=100)

    def validate_gstin(self, value):
        value = value.strip().upper()
        if value and not (len(value) == 15 and value.isalnum()):
            raise serializers.ValidationError("A GSTIN has 15 letters and digits.")
        return value


class MemberSerializer(serializers.ModelSerializer):
    """A membership; `id` is the membership id (used by DELETE/PATCH members/{id})."""

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    name = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ["id", "user_id", "email", "name", "role", "joined_at"]

    def get_name(self, obj) -> str:
        return obj.user.get_full_name() or ""


class InviteCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(
        choices=[Membership.Role.ADMIN, Membership.Role.MEMBER], default=Membership.Role.MEMBER
    )


class InviteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invite
        fields = ["id", "email", "role", "created_at", "expires_at"]


class ApiKeySerializer(serializers.ModelSerializer):
    created_by = serializers.EmailField(source="created_by.email", read_only=True)

    class Meta:
        model = ApiKey
        fields = ["id", "name", "prefix", "created_by", "created_at", "last_used_at"]


class ApiKeyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, default="API key")


class UserRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()


OUTCOME_FIELDS = ["l1_amount_inr", "winner_name", "num_bidders", "our_rank"]


class BidTrackSerializer(serializers.ModelSerializer):
    tender = TenderSerializer(read_only=True)
    owner = UserRefSerializer(read_only=True, allow_null=True)

    class Meta:
        model = BidTrack
        fields = [
            "id",
            "tender",
            "status",
            "notes",
            "bid_amount_inr",
            *OUTCOME_FIELDS,
            "owner",
            "created_at",
            "updated_at",
        ]


class BidTrackCreateSerializer(serializers.Serializer):
    tender = serializers.IntegerField(min_value=1)
    status = serializers.ChoiceField(choices=BidTrack.Status.choices, required=False)


class BidTrackUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=BidTrack.Status.choices, required=False)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=10_000)
    bid_amount_inr = serializers.DecimalField(
        required=False, allow_null=True, max_digits=18, decimal_places=2, min_value=0
    )
    owner = serializers.IntegerField(required=False, allow_null=True, help_text="user id")
    l1_amount_inr = serializers.DecimalField(
        required=False,
        allow_null=True,
        max_digits=18,
        decimal_places=2,
        min_value=0,
        help_text="the lowest (winning) price, once the result is out",
    )
    winner_name = serializers.CharField(
        required=False, allow_blank=True, max_length=300, trim_whitespace=True
    )
    num_bidders = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=MAX_BIDDERS
    )
    our_rank = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=MAX_BIDDERS, help_text="1 = L1"
    )

    def validate(self, attrs):
        """our_rank <= num_bidders, checked against the stored values for whichever of
        the two this request leaves out (pass the track as `instance`)."""
        rank = attrs.get("our_rank", getattr(self.instance, "our_rank", None))
        bidders = attrs.get("num_bidders", getattr(self.instance, "num_bidders", None))
        if rank is not None and bidders is not None and rank > bidders:
            raise serializers.ValidationError(
                {"our_rank": f"Rank {rank} is more than the {bidders} bidders."}
            )
        return attrs


class RecommendedTenderSerializer(TenderSerializer):
    reasons = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta(TenderSerializer.Meta):
        fields = TenderSerializer.Meta.fields + ["reasons"]
