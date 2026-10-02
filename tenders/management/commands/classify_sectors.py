from collections import Counter

from django.core.management.base import BaseCommand

from tenders.models import Tender
from tenders.sectors import classify


class Command(BaseCommand):
    help = "(Re)compute every tender's sector, e.g. after changing the rules in tenders/sectors.py."

    def add_arguments(self, parser):
        parser.add_argument("--no-index", action="store_true")

    def handle(self, *args, no_index, **opts):
        changed, counts = [], Counter()
        for t in Tender.objects.only(
            "id", "title", "product_category", "category", "sector"
        ).iterator():
            sector = classify(t.title, t.product_category, t.category)
            counts[sector] += 1
            if sector != t.sector:
                t.sector = sector
                changed.append(t)
        Tender.objects.bulk_update(changed, ["sector"], batch_size=500)
        self.stdout.write(f"{len(changed)} tenders changed sector")
        self.stdout.write(", ".join(f"{k}={v}" for k, v in counts.most_common()))
        if changed and not no_index:
            from django.conf import settings

            from tenders import search

            if settings.ES_ENABLED and search.available():
                ids = [t.id for t in changed]
                n = search.bulk_index(
                    Tender.objects.select_related("buyer_entity").filter(id__in=ids).iterator()
                )
                self.stdout.write(f"re-indexed {n}")
