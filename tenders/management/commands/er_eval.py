import csv

from django.core.management.base import BaseCommand, CommandError

from tenders import resolution


def evaluate(rows: list[dict], *, guards: bool) -> dict:
    """Judge each pair the way the resolver would: names in different blocks (different
    first normalised token) are never compared, so they can't be merged."""
    tp = fp = fn = review = blocked_out = 0
    for r in rows:
        na, nb = resolution.normalise(r["name_a"]), resolution.normalise(r["name_b"])
        same_block = resolution.block_key(na, "") == resolution.block_key(nb, "")
        s = resolution.score(na, nb, guards=guards) if same_block else 0.0
        truth = r["same_entity"].strip() in {"1", "y", "yes", "true"}
        merged = s >= resolution.AUTO_MERGE
        if merged and truth:
            tp += 1
        elif merged and not truth:
            fp += 1
        elif truth:
            fn += 1
            blocked_out += not same_block
        if resolution.REVIEW_LOW <= s < resolution.AUTO_MERGE:
            review += 1
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    return {
        "auto_merged": tp + fp,
        "true_pos": tp,
        "false_pos": fp,
        "missed": fn,
        "missed_by_blocking": blocked_out,
        "review_band": review,
        "precision": precision,
        "recall": recall,
    }


class Command(BaseCommand):
    help = (
        "Precision/recall of automatic merges on labelled pairs (same_entity column = 1/0). "
        "Pass several CSV files; rows are also reported per `source` column (real/synthetic)."
    )

    def add_arguments(self, parser):
        parser.add_argument("labels", nargs="+")

    def handle(self, *args, labels, **opts):
        rows = []
        for path in labels:
            with open(path, encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    if r.get("same_entity", "").strip() != "":
                        r.setdefault("source", "real")
                        rows.append(r)
        if not rows:
            raise CommandError("no labelled rows (fill the same_entity column with 1 or 0)")
        groups = {"all": rows}
        for r in rows:
            groups.setdefault(r.get("source") or "real", []).append(r)
        for group, members in groups.items():
            if group == "all" and len(groups) == 2:
                continue  # only one source: "all" would repeat it
            positives = sum(r["same_entity"].strip() in {"1", "y", "yes", "true"} for r in members)
            self.stdout.write(
                f"\n[{group}] {len(members)} labelled pairs, {positives} true matches"
            )
            self.stdout.write(
                f"{'scorer':<34}{'merged':>7}{'FP':>5}{'missed':>8}{'(block)':>8}{'review':>8}{'precision':>11}{'recall':>8}"
            )
            for name, guards in (
                ("token_set_ratio alone", False),
                ("token_set_ratio + guards (used)", True),
            ):
                m = evaluate(members, guards=guards)
                self.stdout.write(
                    f"{name:<34}{m['auto_merged']:>7}{m['false_pos']:>5}{m['missed']:>8}{m['missed_by_blocking']:>8}{m['review_band']:>8}"
                    f"{_pct(m['precision']):>11}{_pct(m['recall']):>8}"
                )


def _pct(x: float) -> str:
    return "n/a" if x != x else f"{x:.1%}"  # NaN when there is nothing to divide by
