import pytest

from tenders import resolution
from tenders.models import BuyerAlias, BuyerEntity, BuyerReview, Tender
from tenders.pincode import state_from_pincode

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("PWD Bhopal", "public works department bhopal"),
        ("Public Works Department, Bhopal", "public works department bhopal"),
        ("Office of the Executive Engineer, P.W.D.", "executive engineer p w d"),
        ("Govt. of M.P. - PHED", "m p public health engineering department"),
        (
            "DG, Indo-Tibetan Border Police Force",
            "directorate general indo tibetan border police force",
        ),
        ("Roads & Buildings", "roads buildings"),
    ],
)
def test_normalise(raw, expected):
    assert resolution.normalise(raw) == expected


def test_abbreviation_and_spelling_variants_resolve_to_one_entity():
    a = resolution.resolve("Public Works Department || Bhopal Division", "Madhya Pradesh")
    b = resolution.resolve("PWD || Bhopal Division", "Madhya Pradesh")
    c = resolution.resolve("Public Works Deptt. || Bhopal Divison", "Madhya Pradesh")  # typo
    assert a.entity_id == b.entity_id == c.entity_id
    assert b.method == BuyerAlias.Method.EXACT
    assert c.method == BuyerAlias.Method.FUZZY and c.score >= resolution.AUTO_MERGE
    assert BuyerEntity.objects.count() == 1
    assert set(BuyerAlias.objects.values_list("alias", flat=True)) == {
        "Public Works Department || Bhopal Division",
        "PWD || Bhopal Division",
        "Public Works Deptt. || Bhopal Divison",
    }


def test_blocking_keeps_states_apart():
    a = resolution.resolve("Public Works Department || Bhopal", "Madhya Pradesh")
    b = resolution.resolve("Public Works Department || Bhopal", "Rajasthan")
    # Same alias string is already mapped; a *different* spelling in another state is not merged.
    c = resolution.resolve("PWD || Bhopal Division", "Rajasthan")
    assert a.entity_id == b.entity_id  # identical alias reuses the mapping
    assert c.entity_id != a.entity_id


def test_blocking_requires_same_first_token():
    a = resolution.resolve("Water Resources Department || Indore", "Madhya Pradesh")
    b = resolution.resolve("Indore Water Resources Department", "Madhya Pradesh")
    assert a.entity_id != b.entity_id  # different first token: never compared


def test_review_band_creates_new_entity_and_review_item():
    a = resolution.resolve("Municipal Corporation Bhopal || Engineering Wing", "Madhya Pradesh")
    b = resolution.resolve("Municipal Corpn Bhopal || Engineering Wing", "Madhya Pradesh")
    assert a.entity_id != b.entity_id
    review = BuyerReview.objects.get()
    assert resolution.REVIEW_LOW <= review.score < resolution.AUTO_MERGE
    assert review.candidate_id == a.entity_id
    assert review.alias == "Municipal Corpn Bhopal || Engineering Wing"


def test_sibling_departments_are_not_merged():
    """Plain token_set_ratio scores this pair 90.4 and would auto-merge it."""
    a_norm = resolution.normalise("Municipal Corporation Bhopal || Engineering Wing")
    b_norm = resolution.normalise("Municipal Corporation Bhopal || Health Wing")
    assert resolution.score(a_norm, b_norm, guards=False) >= resolution.AUTO_MERGE
    assert resolution.score(a_norm, b_norm) < resolution.REVIEW_LOW
    a = resolution.resolve("Municipal Corporation Bhopal || Engineering Wing", "Madhya Pradesh")
    b = resolution.resolve("Municipal Corporation Bhopal || Health Wing", "Madhya Pradesh")
    assert a.entity_id != b.entity_id


def test_different_numbers_never_auto_merge():
    a = resolution.resolve("PWD || Bhopal Division No 1", "Madhya Pradesh")
    b = resolution.resolve("PWD || Bhopal Division No 2", "Madhya Pradesh")
    assert a.entity_id != b.entity_id
    assert BuyerReview.objects.get().score == resolution.DISTINGUISHING_CAP


@pytest.mark.parametrize(
    "a,b",
    [
        (
            "Archaeological Survey of India || O/o SA-ASI-Delhi Circle-Delhi",
            "Archaeological Survey of India || O/o SA-ASI-Agra Circle-Agra",
        ),
        (
            "All India Institute of Medical Sciences-Bhopal",
            "All India Institute of Medical Sciences-Raipur",
        ),
        (
            "Bhabha Atomic Research Centre || Bhabha Atomic Research Centre Mumbai",
            "Bhabha Atomic Research Centre || Bhabha Atomic Research Centre Kalpakkam",
        ),
    ],
)
def test_place_names_distinguish_real_world_siblings(a, b):
    """Pairs from the live crawl that plain token_set_ratio would merge."""
    na, nb = resolution.normalise(a), resolution.normalise(b)
    assert resolution.score(na, nb) < resolution.AUTO_MERGE


@pytest.mark.parametrize(
    "a,b",
    [
        (
            "Archaeological Survey of India || O/o SA - ASI - Merrut circle",
            "Archaeological Survey of India || O/o SA-ASI-Meerut Circle-Meerut",
        ),
        (
            "All India Institute of Medical Science-New Delhi || Store DO - AIIMS New Delhi",
            "All India Institute of Medical Sciences-New Delhi || Store DO - AIIMS New Delhi",
        ),
    ],
)
def test_typos_still_merge(a, b):
    na, nb = resolution.normalise(a), resolution.normalise(b)
    assert resolution.score(na, nb) >= resolution.AUTO_MERGE


def test_normalise_keeps_hierarchy():
    assert (
        resolution.normalise("PWD || Bhopal Division")
        == "public works department | bhopal division"
    )


def test_low_score_creates_new_entity_without_review():
    resolution.resolve("Public Works Department || Bhopal", "Madhya Pradesh")
    resolution.resolve("Public Health Engineering Department || Gwalior", "Madhya Pradesh")
    assert BuyerEntity.objects.count() == 2
    assert BuyerReview.objects.count() == 0


def test_merge_review_moves_alias_and_tenders(make_page):
    from ingest.loader import load_detail_page
    from tests.conftest import fixture_text

    load_detail_page(make_page(fixture_text("gepnic_central/detail_01.html")))
    t = Tender.objects.get()
    target = BuyerEntity.objects.create(canonical_name="AMU Electricity", norm_key="x", state="")
    review = BuyerReview.objects.create(alias=t.buyer_raw, candidate=target, score=85)
    old = t.buyer_entity_id
    resolution.merge_review(review)
    t.refresh_from_db()
    assert t.buyer_entity_id == target.id
    assert not BuyerEntity.objects.filter(id=old).exists()
    assert BuyerAlias.objects.get(alias=t.buyer_raw).method == BuyerAlias.Method.MANUAL


@pytest.mark.parametrize(
    "pin,state",
    [
        ("110001", "Delhi"),
        ("202002", "Uttar Pradesh"),
        ("248001", "Uttarakhand"),
        ("247001", "Uttar Pradesh"),
        ("403001", "Goa"),
        ("496001", "Chhattisgarh"),
        ("500001", "Telangana"),
        ("751001", "Odisha"),
        ("793012", "Meghalaya"),
        ("799012", "Tripura"),
        ("834001", "Jharkhand"),
        ("800001", "Bihar"),
        ("160017", "Chandigarh"),
        ("682555", "Lakshadweep"),
        ("605001", "Puducherry"),
        ("", ""),
        ("12345", ""),
        ("012345", ""),
        ("NA", ""),
    ],
)
def test_state_from_pincode(pin, state):
    assert state_from_pincode(pin) == state
