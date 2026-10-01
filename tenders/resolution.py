"""Buyer-name entity resolution.

normalise -> block -> match:
  * normalise: lowercase, strip punctuation, drop filler words, expand abbreviations;
    the "Org || Department" hierarchy is kept as "org | department"
  * block: only compare names in the same state that share the first normalised token
  * match: RapidFuzz token_set_ratio; >= AUTO_MERGE merges, [REVIEW_LOW, AUTO_MERGE)
    goes to the review list, anything lower becomes a new entity.
"""

import re
import unicodedata
from dataclasses import dataclass

from django.db import transaction
from rapidfuzz import fuzz

from tenders.models import BuyerAlias, BuyerEntity, BuyerReview

AUTO_MERGE = 90.0
REVIEW_LOW = 80.0

# Abbreviations seen on GePNIC portals. Expanded before matching so "PWD Bhopal" and
# "Public Works Department, Bhopal" normalise to the same tokens.
ABBREVIATIONS = {
    "pwd": "public works department",
    "cpwd": "central public works department",
    "phed": "public health engineering department",
    "phe": "public health engineering",
    "rwd": "rural works department",
    "wrd": "water resources department",
    "nhai": "national highways authority of india",
    "morth": "ministry of road transport and highways",
    "dda": "delhi development authority",
    "asi": "archaeological survey of india",
    "bsf": "border security force",
    "crpf": "central reserve police force",
    "itbp": "indo tibetan border police",
    "cisf": "central industrial security force",
    "aiims": "all india institute of medical sciences",
    "iit": "indian institute of technology",
    "nit": "national institute of technology",
    "drdo": "defence research and development organisation",
    "isro": "indian space research organisation",
    "ongc": "oil and natural gas corporation",
    "bsnl": "bharat sanchar nigam limited",
    "ntpc": "ntpc limited",
    "mes": "military engineer services",
    "uad": "urban administration and development",
    "dept": "department",
    "deptt": "department",
    "dte": "directorate",
    "corp": "corporation",
    "ltd": "limited",
    "pvt": "private",
    "univ": "university",
    "mha": "ministry of home affairs",
    "dg": "directorate general",
    "ee": "executive engineer",
    "se": "superintending engineer",
    "ce": "chief engineer",
    "nh": "national highway",
    "dist": "district",
    "distt": "district",
    "mp": "madhya pradesh",
    "up": "uttar pradesh",
}

# Words that carry no identity. "department" stays: "Department of X" vs "X" differ.
FILLERS = {"office", "of", "the", "govt", "government", "and", "for", "in", "at", "a", "an"}

_PUNCT = re.compile(r"[^\w\s]")
PART_SEP = " | "
# A pair with a distinguishing token (see _has_distinguishing_token) is never merged
# automatically, however similar the rest is: its score is capped inside the review band.
DISTINGUISHING_CAP = 85.0
# Two differing tokens count as one spelling ("divison"/"division", "merrut"/"meerut")
# when both are at least this long and this similar.
TYPO_MIN_LEN = 4
TYPO_RATIO = 80.0


def _normalise_part(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().replace("&", " and ")
    text = _PUNCT.sub(" ", text)
    tokens: list[str] = []
    for tok in text.split():
        expanded = ABBREVIATIONS.get(tok, tok)
        for t in expanded.split():
            if t not in FILLERS:
                tokens.append(t)
    return " ".join(tokens)


def normalise(name: str) -> str:
    """'Org || Department' -> 'org tokens | department tokens' (hierarchy kept)."""
    parts = [_normalise_part(p) for p in name.split("||")]
    return PART_SEP.join(p for p in parts if p)


def block_key(norm: str, state: str) -> tuple[str, str]:
    first = norm.split(" ", 1)[0] if norm else ""
    return (state or "", first)


def _has_distinguishing_token(a_tokens: set[str], b_tokens: set[str]) -> bool:
    """True when one name has a token the other lacks that is not just a misspelling.

    token_set_ratio scores the shared tokens and largely ignores what differs, so
    "ASI | Delhi Circle" vs "ASI | Agra Circle", "AIIMS Bhopal" vs "AIIMS Raipur" or
    "Division No 1" vs "Division No 2" all score near 90. Those differing tokens (places,
    numbers, extra words) are exactly what identifies the buyer.
    """
    a_only, b_only = a_tokens - b_tokens, b_tokens - a_tokens

    def has_typo_partner(tok: str, others: set[str]) -> bool:
        return len(tok) >= TYPO_MIN_LEN and any(
            len(o) >= TYPO_MIN_LEN and fuzz.ratio(tok, o) >= TYPO_RATIO for o in others
        )

    return any(not has_typo_partner(t, b_tokens) for t in a_only) or any(
        not has_typo_partner(t, a_tokens) for t in b_only
    )


def score(a_norm: str, b_norm: str, *, guards: bool = True) -> float:
    """token_set_ratio, plus two guards against its known false positives.

    1. Hierarchy: organisation and department parts are scored separately and the lower
       score wins, so two departments of one organisation are not merged because the
       organisation name dominates ("Corporation X | Engineering Wing" vs "| Health Wing").
    2. Distinguishing tokens: see _has_distinguishing_token; such pairs go to review.
    """
    flat_a, flat_b = a_norm.replace(PART_SEP, " "), b_norm.replace(PART_SEP, " ")
    if not guards:
        return fuzz.token_set_ratio(flat_a, flat_b)
    a_parts, b_parts = a_norm.split(PART_SEP), b_norm.split(PART_SEP)
    if len(a_parts) >= 2 and len(b_parts) >= 2:
        s = min(
            fuzz.token_set_ratio(a_parts[0], b_parts[0]),
            fuzz.token_set_ratio(" ".join(a_parts[1:]), " ".join(b_parts[1:])),
        )
    else:
        s = fuzz.token_set_ratio(flat_a, flat_b)
    if _has_distinguishing_token(set(flat_a.split()), set(flat_b.split())):
        s = min(s, DISTINGUISHING_CAP)
    return s


def buyer_home_states() -> list[tuple[str, str, int]]:
    """(buyer name, its most common tender state, tender count), most frequent name first.

    A national buyer can tender in many states; blocking uses the state it tenders in
    most. Ties break alphabetically so rebuilds are deterministic.
    """
    from django.db.models import Count

    from tenders.models import Tender

    per_state: dict[str, dict[str, int]] = {}
    for row in Tender.objects.values("buyer_raw", "state").annotate(n=Count("id")):
        per_state.setdefault(row["buyer_raw"], {})[row["state"]] = row["n"]
    out = []
    for name, states in per_state.items():
        home = sorted(states.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        out.append((name, home, sum(states.values())))
    out.sort(key=lambda r: (-r[2], r[0]))
    return out


@dataclass
class Resolution:
    entity_id: int
    method: str
    score: float
    review_candidate_id: int | None = None


def _best_candidate(norm: str, state: str) -> tuple[BuyerEntity | None, float]:
    _, first = block_key(norm, state)
    if not first:
        return None, 0.0
    best, best_score = None, 0.0
    # The block: same state and same first token. A prefix match on norm_key is the
    # cheap index-friendly way to express "same first token".
    qs = BuyerEntity.objects.filter(state=state or "").filter(
        norm_key__startswith=first + " "
    ) | BuyerEntity.objects.filter(state=state or "", norm_key=first)
    for entity in qs.only("id", "norm_key"):
        s = score(norm, entity.norm_key)
        if s > best_score:
            best, best_score = entity, s
    return best, best_score


@transaction.atomic
def resolve(name: str, state: str = "") -> Resolution:
    """Map a raw buyer name to a BuyerEntity, creating one when nothing matches."""
    alias = BuyerAlias.objects.select_related("entity").filter(alias=name).first()
    if alias:
        return Resolution(alias.entity_id, alias.method, alias.score)

    norm = normalise(name)
    exact = BuyerEntity.objects.filter(norm_key=norm, state=state or "").first()
    if exact:
        BuyerAlias.objects.get_or_create(
            alias=name,
            defaults={"entity": exact, "score": 100.0, "method": BuyerAlias.Method.EXACT},
        )
        return Resolution(exact.id, BuyerAlias.Method.EXACT, 100.0)

    best, best_score = _best_candidate(norm, state)
    if best is not None and best_score >= AUTO_MERGE:
        BuyerAlias.objects.get_or_create(
            alias=name,
            defaults={"entity": best, "score": best_score, "method": BuyerAlias.Method.FUZZY},
        )
        return Resolution(best.id, BuyerAlias.Method.FUZZY, best_score)

    entity = BuyerEntity.objects.create(canonical_name=name, norm_key=norm, state=state or "")
    BuyerAlias.objects.get_or_create(
        alias=name, defaults={"entity": entity, "score": 100.0, "method": BuyerAlias.Method.SEED}
    )
    review_id = None
    if best is not None and best_score >= REVIEW_LOW:
        review, _ = BuyerReview.objects.get_or_create(
            alias=name, candidate=best, defaults={"score": best_score}
        )
        review_id = review.id
    return Resolution(entity.id, BuyerAlias.Method.SEED, 100.0, review_id)


@transaction.atomic
def merge_review(review: BuyerReview) -> None:
    """Approve a review-band pair: move the alias (and its tenders) to the candidate."""
    from tenders.models import Tender

    alias = BuyerAlias.objects.get(alias=review.alias)
    old_entity_id = alias.entity_id
    alias.entity = review.candidate
    alias.method = BuyerAlias.Method.MANUAL
    alias.score = review.score
    alias.save()
    Tender.objects.filter(buyer_raw=review.alias).update(buyer_entity=review.candidate)
    if not BuyerAlias.objects.filter(entity_id=old_entity_id).exists():
        BuyerEntity.objects.filter(id=old_entity_id).delete()
    review.status = BuyerReview.Status.MERGED
    review.save(update_fields=["status"])
