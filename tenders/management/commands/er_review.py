from django.core.management.base import BaseCommand, CommandError

from tenders import resolution
from tenders.models import BuyerReview


class Command(BaseCommand):
    help = "List the 80-90 review band, or approve / reject a pair by id."

    def add_arguments(self, parser):
        parser.add_argument("--approve", type=int, nargs="*", default=[])
        parser.add_argument("--reject", type=int, nargs="*", default=[])

    def handle(self, *args, approve, reject, **opts):
        for rid in approve:
            review = BuyerReview.objects.filter(pk=rid, status="open").first()
            if review is None:
                raise CommandError(f"no open review {rid}")
            resolution.merge_review(review)
            self.stdout.write(f"merged {review.alias!r} -> {review.candidate.canonical_name!r}")
        if reject:
            n = BuyerReview.objects.filter(pk__in=reject, status="open").update(status="rejected")
            self.stdout.write(f"rejected {n}")
        if approve or reject:
            return
        for r in (
            BuyerReview.objects.filter(status="open").select_related("candidate").order_by("-score")
        ):
            self.stdout.write(
                f"[{r.pk}] {r.score:5.1f}  {r.alias}\n         ~ {r.candidate.canonical_name}"
            )
