from django.core.management.base import BaseCommand
from django.db import transaction

from tenders import resolution
from tenders.models import BuyerAlias, BuyerEntity, BuyerReview, Tender


class Command(BaseCommand):
    help = (
        "Re-run buyer entity resolution over every tender. With --rebuild, all entities, "
        "aliases and open reviews are dropped first (manual merges are replayed)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--rebuild", action="store_true")

    def handle(self, *args, rebuild, **opts):
        manual = []
        with transaction.atomic():
            if rebuild:
                manual = list(
                    BuyerAlias.objects.filter(method=BuyerAlias.Method.MANUAL)
                    .select_related("entity")
                    .values_list("alias", "entity__canonical_name")
                )
                Tender.objects.update(buyer_entity=None)
                BuyerReview.objects.all().delete()
                BuyerAlias.objects.all().delete()
                BuyerEntity.objects.all().delete()

            # Most frequent spelling first, so it becomes the canonical name.
            names = resolution.buyer_home_states()
            touched = 0
            for name, state, _count in names:
                res = resolution.resolve(name, state)
                touched += (
                    Tender.objects.filter(buyer_raw=name)
                    .exclude(buyer_entity_id=res.entity_id)
                    .update(buyer_entity_id=res.entity_id)
                )

            for alias, canonical in manual:
                target = BuyerEntity.objects.filter(canonical_name=canonical).first()
                if target is not None:
                    review, _ = BuyerReview.objects.get_or_create(
                        alias=alias, candidate=target, defaults={"score": 0}
                    )
                    if review.status == BuyerReview.Status.OPEN:
                        resolution.merge_review(review)

        stats = {
            "raw_names": len(names),
            "entities": BuyerEntity.objects.count(),
            "aliases_fuzzy": BuyerAlias.objects.filter(method="fuzzy").count(),
            "aliases_exact": BuyerAlias.objects.filter(method="exact").count(),
            "open_reviews": BuyerReview.objects.filter(status="open").count(),
            "tenders_relinked": touched,
        }
        self.stdout.write(" ".join(f"{k}={v}" for k, v in stats.items()))
