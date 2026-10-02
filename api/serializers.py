from rest_framework import serializers

from tenders.models import BuyerEntity, Tender


class BuyerRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = BuyerEntity
        fields = ["id", "canonical_name"]


class TenderSerializer(serializers.ModelSerializer):
    buyer = BuyerRefSerializer(source="buyer_entity", read_only=True)

    class Meta:
        model = Tender
        fields = [
            "id",
            "source",
            "source_tender_id",
            "ref_no",
            "title",
            "buyer",
            "buyer_raw",
            "category",
            "product_category",
            "sector",
            "value_inr",
            "emd_inr",
            "published_at",
            "closes_at",
            "state",
            "location",
        ]


class TenderDetailSerializer(TenderSerializer):
    class Meta(TenderSerializer.Meta):
        fields = TenderSerializer.Meta.fields + [
            "org_chain",
            "tender_type",
            "fee_inr",
            "opens_at",
            "pincode",
            "url",
            "first_seen",
            "last_seen",
        ]


class TenderQuerySerializer(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True, max_length=200)
    state = serializers.CharField(required=False, max_length=64)
    sector = serializers.CharField(required=False, max_length=32)
    pin = serializers.RegexField(
        r"^[1-9]\d{1,5}$", required=False, help_text="PIN code prefix, e.g. 490 for Bhilai/Durg"
    )
    category = serializers.CharField(required=False, max_length=64)
    source = serializers.CharField(required=False, max_length=32)
    buyer = serializers.IntegerField(required=False, min_value=1, help_text="buyer entity id")
    min_value = serializers.DecimalField(
        required=False, max_digits=18, decimal_places=2, min_value=0
    )
    max_value = serializers.DecimalField(
        required=False, max_digits=18, decimal_places=2, min_value=0
    )
    closes_before = serializers.DateTimeField(required=False)
    closes_after = serializers.DateTimeField(required=False)
    sort = serializers.ChoiceField(
        choices=["relevance", "closing", "newest", "value"], required=False, default="relevance"
    )
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100, default=20)


class FacetBucketSerializer(serializers.Serializer):
    key = serializers.CharField()
    count = serializers.IntegerField()


class FacetsSerializer(serializers.Serializer):
    state = FacetBucketSerializer(many=True)
    sector = FacetBucketSerializer(many=True)
    category = FacetBucketSerializer(many=True)
    value_range = FacetBucketSerializer(many=True)


class TenderPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    search_backend = serializers.ChoiceField(choices=["elasticsearch", "postgres"])
    relaxed = serializers.BooleanField(
        help_text="true when nothing matched every word and results match some words"
    )
    facets = FacetsSerializer()
    results = TenderSerializer(many=True)


class BuyerSerializer(serializers.ModelSerializer):
    aliases = serializers.SerializerMethodField()
    tender_count = serializers.IntegerField()
    total_value_inr = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    open_tender_count = serializers.IntegerField()

    class Meta:
        model = BuyerEntity
        fields = [
            "id",
            "canonical_name",
            "state",
            "aliases",
            "tender_count",
            "open_tender_count",
            "total_value_inr",
        ]

    def get_aliases(self, obj) -> list[dict]:
        return [{"alias": a.alias, "method": a.method, "score": a.score} for a in obj.aliases.all()]
