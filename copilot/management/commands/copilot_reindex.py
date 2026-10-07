"""Recompute chunk context and embeddings for ready documents (copilot.ingest.reindex).

    manage.py copilot_reindex                      # every ready document
    manage.py copilot_reindex --missing-context    # only documents whose chunks have none
    manage.py copilot_reindex --document 12 --document 15
    manage.py copilot_reindex --organization acme

Run it once after migration copilot 0002 (chunks written before it have no context), and
after changing EMBEDDING_MODEL. Each document is its own transaction, so it can be stopped
and re-run safely.
"""

import time

from django.core.management.base import BaseCommand

from copilot import ingest
from copilot.models import Document


class Command(BaseCommand):
    help = "Recompute Copilot chunk context and embeddings from stored page texts."

    def add_arguments(self, parser):
        parser.add_argument("--document", type=int, action="append", default=[])
        parser.add_argument("--organization", default=None, help="organisation slug")
        parser.add_argument("--missing-context", action="store_true")

    def handle(self, *args, **o):
        qs = Document.objects.filter(status=Document.Status.READY).select_related("tender")
        if o["document"]:
            qs = qs.filter(pk__in=o["document"])
        if o["organization"]:
            qs = qs.filter(organization__slug=o["organization"])
        if o["missing_context"]:
            qs = qs.filter(chunks__context="").distinct()
        t0, docs, chunks = time.perf_counter(), 0, 0
        for doc in qs.order_by("pk").iterator(chunk_size=50):
            chunks += ingest.reindex(doc)
            docs += 1
        self.stdout.write(
            f"Reindexed {docs} documents ({chunks} chunks) in {time.perf_counter() - t0:.1f}s"
        )
