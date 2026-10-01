import csv
import itertools
import random

from django.core.management.base import BaseCommand

from tenders import resolution


class Command(BaseCommand):
    help = (
        "Write candidate buyer-name pairs for hand labelling. Pairs come from the same "
        "blocks the resolver uses and are sampled across score bands, so the labelled set "
        "covers clear matches, the review band and near misses."
    )

    def add_arguments(self, parser):
        parser.add_argument("out")
        parser.add_argument("--per-band", type=int, default=35)
        parser.add_argument("--seed", type=int, default=7)

    def handle(self, *args, out, per_band, seed, **opts):
        blocks: dict[tuple, list[str]] = {}
        for name, state, _count in resolution.buyer_home_states():
            norm = resolution.normalise(name)
            blocks.setdefault(resolution.block_key(norm, state), []).append(name)

        bands = {"90+": [], "80-90": [], "70-80": []}
        for key, members in blocks.items():
            for a, b in itertools.combinations(sorted(set(members)), 2):
                raw = resolution.score(
                    resolution.normalise(a), resolution.normalise(b), guards=False
                )
                if raw >= 90:
                    bands["90+"].append((a, b, key))
                elif raw >= 80:
                    bands["80-90"].append((a, b, key))
                elif raw >= 70:
                    bands["70-80"].append((a, b, key))

        rng = random.Random(seed)
        rows = []
        for band, pairs in bands.items():
            rng.shuffle(pairs)
            for a, b, key in pairs[:per_band]:
                na, nb = resolution.normalise(a), resolution.normalise(b)
                rows.append(
                    {
                        "name_a": a,
                        "name_b": b,
                        "block_state": key[0],
                        "block_token": key[1],
                        "band_unguarded": band,
                        "score_unguarded": round(resolution.score(na, nb, guards=False), 1),
                        "score_guarded": round(resolution.score(na, nb), 1),
                        "same_entity": "",
                    }
                )
        with open(out, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["name_a"])
            writer.writeheader()
            writer.writerows(rows)
        sizes = ", ".join(f"{k}: {len(v)} candidates" for k, v in bands.items())
        self.stdout.write(f"wrote {len(rows)} pairs to {out} ({sizes})")
