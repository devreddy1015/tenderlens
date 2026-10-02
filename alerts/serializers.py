import re

from rest_framework import serializers

from alerts.models import AlertSubscription
from tenders.pincode import ALL_STATES
from tenders.sectors import SECTOR_BY_SLUG

MAX_ALERTS_PER_USER = 10


class AlertCriteriaSerializer(serializers.Serializer):
    states = serializers.ListField(
        child=serializers.CharField(max_length=64), required=False, default=list, max_length=40
    )
    pin_prefixes = serializers.ListField(
        child=serializers.CharField(max_length=6), required=False, default=list, max_length=20
    )
    sectors = serializers.ListField(
        child=serializers.CharField(max_length=32), required=False, default=list, max_length=20
    )
    keywords = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)
    min_value_inr = serializers.DecimalField(
        required=False, allow_null=True, max_digits=18, decimal_places=2, min_value=0
    )

    def validate_states(self, value):
        unknown = sorted(set(value) - ALL_STATES)
        if unknown:
            raise serializers.ValidationError(f"unknown state: {', '.join(unknown)}")
        return sorted(set(value))

    def validate_pin_prefixes(self, value):
        for p in value:
            if not re.fullmatch(r"[1-9]\d{1,5}", p):
                raise serializers.ValidationError(
                    f"{p!r}: a PIN prefix is 2 to 6 digits, e.g. 490 for Bhilai/Durg"
                )
        return sorted(set(value))

    def validate_sectors(self, value):
        unknown = sorted(set(value) - set(SECTOR_BY_SLUG))
        if unknown:
            raise serializers.ValidationError(f"unknown sector: {', '.join(unknown)}")
        return sorted(set(value))


class AlertSerializer(AlertCriteriaSerializer, serializers.ModelSerializer):
    class Meta:
        model = AlertSubscription
        fields = [
            "id",
            "name",
            "states",
            "pin_prefixes",
            "sectors",
            "keywords",
            "min_value_inr",
            "active",
            "created_at",
            "last_sent_at",
        ]
        read_only_fields = ["id", "created_at", "last_sent_at"]

    def validate(self, attrs):
        request = self.context["request"]
        if self.instance is None and request.user.alerts.count() >= MAX_ALERTS_PER_USER:
            raise serializers.ValidationError(f"you can have at most {MAX_ALERTS_PER_USER} alerts")
        return attrs
