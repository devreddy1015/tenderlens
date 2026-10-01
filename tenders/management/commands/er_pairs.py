import csv
import itertools
import random
import re

from django.core.management.base import BaseCommand

from tenders import resolution

# Spelling differences seen between portals and between officers typing the same name.
ABBREVIATE = [
    (r"\bDepartment\b", "Deptt."),
    (r"\bLimited\b", "Ltd"),
    (r"\bGovernment\b", "Govt."),
    (r"\bCorporation\b", "Corpn."),
    (r"\bDirectorate\b", "Dte."),
    (r"\bUniversity\b", "Univ."),
    (r"\bDistrict\b", "Distt."),
    (r"\bExecutive Engineer\b", "EE"),
]


def _abbreviate(name: str, rng: random.Random) -> str | None:
    options = [(p, r) for p, r in ABBREVIATE if re.search(p, name)]
    if not options:
        return None
    pattern, repl = rng.choice(options)
    return re.sub(pattern, repl, name, count=1)


def _punctuation(name: str, rng: random.Random) -> str | None:
    out = re.sub(r"\s*-\s*", " ", name) if "-" in name else re.sub(r",\s*", " , ", name)
    return out if out != name else None


def _upper(name: str, rng: random.Random) -> str | None:
    return name.upper()


def _office_of(name: str, rng: random.Random) -> str | None:
    if "||" not in name:
        return None
    org, dept = name.split("||", 1)
    return f"{org}|| Office of the {dept.strip()}"


def _typo(name: str, rng: random.Random) -> str | None:
    words = [(m.start(), m.group()) for m in re.finditer(r"[A-Za-z]{7,}", name)]
    if not words:
        return None
    start, word = rng.choice(words)
    i = rng.randrange(1, len(word) - 2)
    if rng.random() < 0.5:  # swap two adjacent letters
        new = word[:i] + word[i + 1] + word[i] + word[i + 2 :]
    else:  # drop one letter
        new = word[:i] + word[i + 1 :]
    return name[:start] + new + name[start + len(word) :]


PERTURBATIONS = {
    "abbreviation": _abbreviate,
    "punctuation": _punctuation,
    "upper_case": _upper,
    "office_of_prefix": _office_of,
    "typo": _typo,
}


class Command(BaseCommand):
    help = (
        "Write buyer-name pairs for evaluation. Real pairs come from the resolver's own "
        "blocks, sampled across score bands, and need hand labels. --synthetic writes "
        "known-positive pairs: real names with realistic spelling changes."
    )

    def add_arguments(self, parser):
        parser.add_argument("out")
        parser.add_argument("--per-band", type=int, default=35)
        parser.add_argument("--seed", type=int, default=7)
        parser.add_argument(
            "--synthetic", type=int, metavar="N", help="write N synthetic positive pairs instead"
        )

    def handle(self, *args, out, per_band, seed, synthetic, **opts):
        rng = random.Random(seed)
        rows = self._synthetic(synthetic, rng) if synthetic else self._real(per_band, rng)
        with open(out, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["name_a"])
            writer.writeheader()
            writer.writerows(rows)

    def _row(self, a, b, **extra) -> dict:
        na, nb = resolution.normalise(a), resolution.normalise(b)
        return {
            "name_a": a,
            "name_b": b,
            "score_unguarded": round(resolution.score(na, nb, guards=False), 1),
            "score_guarded": round(resolution.score(na, nb), 1),
            **extra,
        }

    def _real(self, per_band: int, rng: random.Random) -> list[dict]:
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

        rows = []
        for band, pairs in bands.items():
            rng.shuffle(pairs)
            for a, b, key in pairs[:per_band]:
                rows.append(
                    self._row(
                        a,
                        b,
                        source="real",
                        band_unguarded=band,
                        block_state=key[0],
                        same_entity="",
                        note="",
                    )
                )
        sizes = ", ".join(f"{k}: {len(v)} candidates" for k, v in bands.items())
        self.stdout.write(f"wrote {len(rows)} real pairs ({sizes})")
        return rows

    def _synthetic(self, n: int, rng: random.Random) -> list[dict]:
        names = sorted(name for name, _, _ in resolution.buyer_home_states())
        rng.shuffle(names)
        kinds = list(PERTURBATIONS)
        rows = []
        for name in names:
            if len(rows) >= n:
                break
            kind = kinds[len(rows) % len(kinds)]
            variant = PERTURBATIONS[kind](name, rng)
            if variant is None or variant == name:
                continue
            rows.append(
                self._row(
                    name,
                    variant,
                    source="synthetic",
                    band_unguarded="",
                    block_state="",
                    same_entity="1",
                    note=kind,
                )
            )
        self.stdout.write(f"wrote {len(rows)} synthetic positive pairs")
        return rows
