import csv
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from tenders.models import BuyerEntity, Tender
from tests.conftest import CENTRAL

pytestmark = pytest.mark.django_db


def run(*args) -> str:
    out = StringIO()
    call_command(*args, stdout=out)
    return out.getvalue()


def test_crawl_sync_command(portal):
    out = run("crawl", "--sync", "--mode", "full")
    assert "succeeded" in out and "new=7" in out
    assert "new=0" in run("crawl", "--sync")  # incremental: everything skipped


def test_backfill_reparses_stored_pages_and_is_rerunnable(make_page):
    day = timezone.now() - timedelta(days=3)
    for p in sorted(CENTRAL.glob("detail_*.html")):
        make_page(p.read_text(encoding="utf-8"), fetched_at=day)
    d = timezone.localtime(day).date().isoformat()
    first = run("backfill", d, d, "--no-index")
    assert "new=18" in first
    second = run("backfill", d, d, "--no-index")
    assert "unchanged=18" in second
    assert Tender.objects.count() == 18


def test_backfill_after_parser_fix_updates_rows(make_page, monkeypatch):
    """The point of storing raw HTML: fix the parser, re-parse, no re-crawl."""
    html = (CENTRAL / "detail_01.html").read_text(encoding="utf-8")
    make_page(html)
    from ingest.parsers import gepnic

    real = gepnic.parse_detail
    monkeypatch.setattr(
        "ingest.loader.gepnic.parse_detail", lambda h: {**real(h), "product_category": "BUG"}
    )
    run("backfill", "2000-01-01", "2100-01-01", "--no-index")
    assert Tender.objects.get().product_category == "BUG"
    monkeypatch.setattr("ingest.loader.gepnic.parse_detail", real)  # the "fix"
    out = run("backfill", "2000-01-01", "2100-01-01", "--no-index")
    assert "updated=1" in out
    assert Tender.objects.get().product_category == "Electrical Works"


def test_backfill_rejects_bad_dates():
    with pytest.raises(CommandError):
        run("backfill", "2026-10-05", "2026-10-01")
    with pytest.raises(CommandError):
        run("backfill", "yesterday", "today")


def test_resolve_buyers_rebuild_is_deterministic(make_page):
    for p in sorted(CENTRAL.glob("detail_*.html")):
        from ingest.loader import load_detail_page

        load_detail_page(make_page(p.read_text(encoding="utf-8")))
    before = sorted(BuyerEntity.objects.values_list("canonical_name", flat=True))
    out = run("resolve_buyers", "--rebuild", "--no-index")
    after = sorted(BuyerEntity.objects.values_list("canonical_name", flat=True))
    assert before == after
    assert "entities=" in out
    assert not Tender.objects.filter(buyer_entity__isnull=True).exists()


def test_er_pairs_and_eval(tmp_path, make_page):
    from ingest.loader import load_detail_page

    for p in sorted(CENTRAL.glob("detail_*.html")):
        load_detail_page(make_page(p.read_text(encoding="utf-8")))
    labels = tmp_path / "labels.csv"
    with labels.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["name_a", "name_b", "same_entity"])
        w.writeheader()
        w.writerow(
            {
                "name_a": "PWD || Bhopal Divison",
                "name_b": "Public Works Department || Bhopal Division",
                "same_entity": "1",
            }
        )
        w.writerow(
            {"name_a": "ASI || Delhi Circle", "name_b": "ASI || Agra Circle", "same_entity": "0"}
        )
        w.writerow(
            {"name_a": "ASI || Merrut Circle", "name_b": "ASI || Meerut Circle", "same_entity": "1"}
        )
    out = run("er_eval", str(labels))
    assert "[real] 3 labelled pairs, 2 true matches" in out
    guarded = next(line for line in out.splitlines() if line.startswith("token_set_ratio + guards"))
    assert "100.0%" in guarded  # no false positive with guards
    plain = next(line for line in out.splitlines() if line.startswith("token_set_ratio alone"))
    assert "66.7%" in plain  # Delhi/Agra merged without guards

    pairs = tmp_path / "pairs.csv"
    assert "wrote" in run("er_pairs", str(pairs))
    synthetic = tmp_path / "synthetic.csv"
    assert "synthetic positive pairs" in run("er_pairs", str(synthetic), "--synthetic", "10")
    rows = list(csv.DictReader(synthetic.open()))
    assert rows and all(r["same_entity"] == "1" and r["name_a"] != r["name_b"] for r in rows)
