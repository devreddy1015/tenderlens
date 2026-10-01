from django.core.management.base import BaseCommand

from tenders import search
from tenders.models import Tender


class Command(BaseCommand):
    help = "Create the Elasticsearch index (optionally drop it first) and bulk re-index."

    def add_arguments(self, parser):
        parser.add_argument("--recreate", action="store_true")
        parser.add_argument("--reindex", action="store_true")

    def handle(self, *args, recreate, reindex, **opts):
        search.ensure_index(recreate=recreate)
        self.stdout.write("index ready")
        if reindex or recreate:
            n = search.bulk_index(
                Tender.objects.select_related("buyer_entity").iterator(chunk_size=500)
            )
            self.stdout.write(f"indexed {n} tenders")
