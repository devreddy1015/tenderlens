import csv

from django.core.management.base import BaseCommand, CommandError

from tenders import resolution


def evaluate(rows: list[dict], *, guards: bool) -> dict:
    tp = fp = fn = review = 0
    for r in rows:
        s = resolution.score(
            resolution.normalise(r["name_a"]), resolution.normalise(r["name_b"]), guards=guards
        )
        truth = r["same_entity"].strip() in {"1", "y", "yes", "true"}
        merged = s >= resolution.AUTO_MERGE
        if merged and truth:
            tp += 1
        elif merged and not truth:
            fp += 1
        elif truth:
            fn += 1
        if resolution.REVIEW_LOW <= s < resolution.AUTO_MERGE:
            review += 1
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    return {
        "auto_merged": tp + fp,
        "true_pos": tp,
        "false_pos": fp,
        "missed": fn,
        "review_band": review,
        "precision": precision,
        "recall": recall,
    }


class Command(BaseCommand):
    help = "Precision/recall of automatic merges on hand-labelled pairs (same_entity column = 1/0)."

    def add_arguments(self, parser):
        parser.add_argument("labels")

    def handle(self, *args, labels, **opts):
        with open(labels, encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh) if r.get("same_entity", "").strip() != ""]
        if not rows:
            raise CommandError("no labelled rows (fill the same_entity column with 1 or 0)")
        positives = sum(r["same_entity"].strip() in {"1", "y", "yes", "true"} for r in rows)
        self.stdout.write(f"{len(rows)} labelled pairs, {positives} true matches\n")
        self.stdout.write(
            f"{'scorer':<34}{'merged':>7}{'FP':>5}{'missed':>8}{'review':>8}{'precision':>11}{'recall':>8}"
        )
        for name, guards in (
            ("token_set_ratio alone", False),
            ("token_set_ratio + guards (used)", True),
        ):
            m = evaluate(rows, guards=guards)
            self.stdout.write(
                f"{name:<34}{m['auto_merged']:>7}{m['false_pos']:>5}{m['missed']:>8}{m['review_band']:>8}"
                f"{m['precision']:>11.1%}{m['recall']:>8.1%}"
            )
