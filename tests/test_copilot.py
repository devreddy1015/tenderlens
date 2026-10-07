"""Copilot internals without HTTP: extraction, chunking, Bid Brief, grounding, answers,
eligibility. API, ingestion and retrieval-scoping tests are in test_copilot_api.py."""

from datetime import UTC
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

from copilot import answer, brief, eligibility, grounding
from copilot.chunking import chunk_pages, is_heading, running_lines
from copilot.extract import Page, clean_text, extract, garbled_devanagari
from copilot.prompt import ABSTAIN, clean_answer
from copilot.retrieval import Hit, rrf

FIXTURES = Path(__file__).parent / "fixtures" / "copilot"
DDA = FIXTURES / "NIT_2026_DDA_928070_1.pdf"
ITBP = FIXTURES / "NIT_2026_ITBP_925996_1.pdf"


# --- extraction and chunking ------------------------------------------------------------


def test_clean_text_fixes_ligatures_and_line_break_hyphens():
    assert clean_text("ﬁnancial oﬃce e-\nprocurement") == "financial office e-procurement"


def test_garbled_devanagari_is_detected():
    good = "निविदा सूचना हिंदी और अंग्रेज़ी दोनों में जारी की गई है"
    bad = "न ȡ व ȡ दा सूचना ȡकसी भी ȡवसंगतȡ कɺ ȫĀथȡत मȀ अंĩेज़ी पाठ"
    assert not garbled_devanagari(good)
    assert garbled_devanagari(bad)


def test_extract_real_layout_pdf():
    ex = extract(DDA, ocr=False)
    assert len(ex.pages) == 4 and ex.ocr_pages == 0
    assert "Earnest Money Deposit (EMD): Rs. 22,316/-" in " ".join(ex.pages[1].text.split())
    assert "ﬁ" not in ex.pages[0].text  # ligatures normalised


def test_scanned_page_without_ocr_binary_keeps_going(monkeypatch, caplog):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "NOTICE INVITING TENDER. EMD: Rs. 10,000/- " * 3)
    scan = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), 0)
    pix.clear_with(200)
    scan.insert_image(scan.rect, pixmap=pix)  # an image and no text: a scan
    path = Path(pytest.importorskip("tempfile").mkdtemp()) / "scan.pdf"
    doc.save(path)
    monkeypatch.setattr("copilot.extract.shutil.which", lambda name: None)
    ex = extract(path)
    assert len(ex.pages) == 2 and ex.ocr_pages == 0
    assert "need OCR" in caplog.text


def test_headings_and_running_lines():
    assert is_heading("4.2 Financial turnover")
    assert is_heading("ELIGIBILITY CRITERIA")
    assert not is_heading("The bidder shall upload scanned copies of all documents.")
    bodies = ["EMD is payable online", "Turnover criteria apply", "Pre-bid meeting is held"]
    pages = [Page(i, f"Tender X Page {i} of 3\n{b}") for i, b in enumerate(bodies, 1)]
    assert running_lines(pages) == {"Tender X Page # of #"}


def test_chunks_follow_clauses_keep_pages_and_drop_footers():
    ex = extract(DDA, ocr=False)
    chunks = chunk_pages(ex.pages)
    assert chunks and [c.ord for c in chunks] == list(range(len(chunks)))
    emd = next(c for c in chunks if "22,316" in c.text)
    assert emd.page_from <= 2 <= emd.page_to
    assert all("SYNTHETIC TEST DOCUMENT" not in c.text for c in chunks)  # footer dropped
    assert all(c.tokens <= 800 for c in chunks)


def test_long_section_is_split_with_overlap_and_heading_repeated():
    body = " ".join(f"Clause sentence number {i} says something useful." for i in range(400))
    chunks = chunk_pages([Page(1, "GENERAL CONDITIONS\n" + body)], max_tokens=300, overlap=40)
    assert len(chunks) > 3
    assert all(c.tokens <= 360 for c in chunks)
    assert chunks[1].text.startswith("GENERAL CONDITIONS (continued)")
    assert chunks[0].text.splitlines()[-1] in chunks[1].text  # overlap


# --- Bid Brief --------------------------------------------------------------------------


def brief_of(*texts: str) -> dict:
    return {
        k: f.value
        for k, f in brief.extract_fields([Page(i, t) for i, t in enumerate(texts, 1)]).items()
    }


def test_brief_on_synthetic_notice():
    pages = extract(DDA, ocr=False).pages
    fields = brief.extract_fields(pages)
    values = {k: f.value for k, f in fields.items()}
    assert values["emd"] == "Rs. 22,316/-"
    assert values["tender_fee"] == "Rs. 500/-"
    assert values["estimated_value"] == "Rs. 11,15,781/-"
    assert values["bid_submission_end"] == "03-Oct-2026 03:00 PM"
    assert values["prebid_meeting"] == "03-Oct-2026 at 11:00 AM"
    assert values["completion_period"] == "9 months"
    assert values["bid_validity"] == "180 days"
    assert values["min_turnover"] == "Rs. 5,57,890/- (50% of the estimated cost)"
    assert values["similar_work"].startswith("One similar completed work each costing")
    assert fields["similar_work"].amounts == [Decimal("892625")]
    assert values["performance_security"] == "3% of the tendered value"
    assert values["liquidated_damages"].startswith("0.5% of the tendered value per week")
    assert values["liquidated_damages"].endswith("maximum of 10%")
    assert "PAN card" in values["documents_required"]
    assert "bid_opening" not in values and "mse_exemption" not in values
    assert fields["emd"].page == 2 and "22,316" in fields["emd"].quote
    assert fields["estimated_value"].page == 1


def test_brief_on_wrapped_table_cells():
    """Wrapped table labels interleave with their values in extracted text."""
    v = brief_of(
        "Last date and time 05-Oct-2026 06:00 PM for bid submission Period of 12 months "
        "completion Bid validity 120 days from the date of opening"
    )
    assert v["bid_submission_end"] == "05-Oct-2026 06:00 PM"
    assert v["completion_period"] == "12 months"
    assert v["bid_validity"] == "120 days"


def test_brief_indian_formats():
    v = brief_of(
        "Bid Security (EMD) : ₹ 1.5 lakh in the form of a Bank Guarantee.\n"
        "Cost of tender document: INR 1,180/- (non-refundable)\n"
        "Bid Submission End Date 07/10/2026 15:00 hrs\n"
        "Technical bids will be opened on 8th October 2026 at 11:30 AM.\n"
        "Pre-bid meeting: October 1, 2026.\n"
        "The work shall be completed within 180 (one hundred eighty) days from the date of "
        "start.\n"
        "Bids shall remain valid for 120 days.",
        "Estimated value of the work: Rs. 2.40 crore.\n"
        "The bidder shall have an average annual turnover of Rs. 1.20 crore in the last 3 "
        "financial years.\n"
        "Liquidated damages @ 0.5% per week of delay subject to a maximum of 10% of the "
        "contract value.\n"
        "Performance Security: 5% of the contract value.\n"
        "Micro and Small Enterprises registered with NSIC / Udyam are exempted from payment "
        "of EMD and tender fee.",
    )
    assert v["emd"] == "₹ 1.5 lakh"
    assert v["tender_fee"] == "INR 1,180/-"
    assert v["bid_submission_end"] == "07/10/2026 15:00 hrs"
    assert v["bid_opening"] == "8th October 2026 at 11:30 AM"
    assert v["prebid_meeting"] == "October 1, 2026"
    assert v["completion_period"] == "180 (one hundred eighty) days"
    assert v["bid_validity"] == "120 days"
    assert v["estimated_value"] == "Rs. 2.40 crore"
    assert v["min_turnover"] == "Rs. 1.20 crore"
    assert v["liquidated_damages"] == "0.5% per week of delay subject to a maximum of 10%"
    assert v["performance_security"] == "5% of the contract value"
    assert v["mse_exemption"] == "Exempted from EMD, tender fee"


def test_brief_turnover_amount_is_parsed_in_inr():
    pages = [Page(1, "Average annual financial turnover should be at least Rs. 1.20 crore.")]
    assert brief.extract_fields(pages)["min_turnover"].amounts == [Decimal("12000000")]


def test_brief_never_borrows_the_next_rows_value():
    v = brief_of("EMD: Nil\nTender Fee: Rs. 500/-\nCompletion period: as per schedule")
    assert v["tender_fee"] == "Rs. 500/-"
    assert "emd" not in v and "completion_period" not in v


def test_brief_documents_required_from_a_list():
    v = brief_of(
        "7. DOCUMENTS TO BE UPLOADED\n"
        "1. Scanned copy of EMD payment receipt.\n"
        "2. Registration certificate of the contractor.\n"
        "3. Audited balance sheets for the last three financial years;\n"
        "4. Experience certificates of similar works.\n"
        "8. GENERAL CONDITIONS\n"
    )
    assert v["documents_required"] == [
        "Scanned copy of EMD payment receipt",
        "Registration certificate of the contractor",
        "Audited balance sheets for the last three financial years",
        "Experience certificates of similar works",
    ]


def test_brief_api_shape_and_corrigendum_override():
    def doc(pk, name, text, day):
        from datetime import datetime

        return SimpleNamespace(
            pk=pk, filename=name, page_texts=[text], created_at=datetime(2026, 10, day, tzinfo=UTC)
        )

    nit = doc(
        1, "NIT.pdf", "Last date for bid submission: 07-Oct-2026 03:00 PM. EMD: Rs. 10,000/-", 1
    )
    corr = doc(
        2,
        "Corrigendum-1.pdf",
        "CORRIGENDUM. Last date for bid submission: 14-Oct-2026 03:00 PM.",
        2,
    )
    out = brief.brief([corr, nit])
    by_key = {f["key"]: f for f in out["fields"]}
    assert by_key["bid_submission_end"]["value"] == "14-Oct-2026 03:00 PM"
    assert by_key["bid_submission_end"]["document_id"] == 2
    assert by_key["emd"]["filename"] == "NIT.pdf"
    assert set(by_key["emd"]) == {
        "key",
        "label",
        "value",
        "page",
        "quote",
        "document_id",
        "filename",
    }
    assert "tender_fee" in out["missing"] and out["generated_at"]
    assert [f["key"] for f in out["fields"]] == [k for k in brief.KEYS if k in by_key]


# --- grounding, prompt and answers ----------------------------------------------------------


def test_grounding_normalises_indian_amounts_and_dates():
    passages = {1: "EMD of Rs. 16,00,000/- by 07-Oct-2026; performance security 5 %."}
    assert grounding.check("The EMD is ₹16 lakh [1], due 7 October 2026 [1].", passages).ok
    assert grounding.check("Performance security is 5% [1].", passages).ok


def test_grounding_rejects_values_not_in_the_cited_passage():
    passages = {1: "EMD: Rs. 22,316/-.", 2: "Tender fee: Rs. 500/-."}
    rep = grounding.check("The EMD is Rs. 22,316 [2].", passages)
    assert not rep.ok and rep.unsupported == ["Rs. 22,316"]
    computed = grounding.check("EMD plus fee is Rs. 22,816 [1][2].", passages)
    assert not computed.ok
    uncited = grounding.check("The EMD is Rs. 22,316.", passages)
    assert not uncited.ok and uncited.uncited_claims
    assert grounding.check("The fee is Rs. 500 [7].", passages).invalid_citations == [7]


def test_clean_answer_strips_thinking_and_normalises_refusals():
    assert clean_answer("<think>hmm</think>The EMD is Rs. 5 [1].") == "The EMD is Rs. 5 [1]."
    assert clean_answer("The documents do not mention the interest rate.") == ABSTAIN
    assert clean_answer("I could not find this in the tender documents") == ABSTAIN


def hit(n, text, page=1):
    return Hit(n, 10 + n, f"doc{n}.pdf", None, page, page, "", text)


HITS = [
    hit(
        1,
        "2. EARNEST MONEY DEPOSIT\nEarnest Money Deposit (EMD): Rs. 22,316/- (Rupees 0.22 lakh"
        "\nonly), payable online.\nThe EMD of unsuccessful bidders shall be refunded.",
        2,
    ),
    hit(2, "Security deposit shall be recovered at the rate of 5% of each running bill.", 3),
]


def test_judge_answered_with_citation_quotes():
    final = answer.judge("q", "The EMD is Rs. 22,316/- [1].", HITS, 0.0, "m")
    assert final["status"] == "answered" and final["mode"] == "llm"
    (c,) = final["citations"]
    assert c["n"] == 1 and c["document_id"] == 11 and c["page"] == 2
    assert "22,316" in c["quote"]
    assert final["grounding"] == {"unsupported": []}


def test_judge_rejects_ungrounded_and_uncited_answers():
    bad = answer.judge("q", "The EMD is Rs. 25,000 [1].", HITS, 0.0, "m")
    assert bad["status"] == "rejected" and bad["answer"] == ABSTAIN
    assert bad["grounding"]["unsupported"] == ["Rs. 25,000"]
    assert answer.judge("q", "It is payable online.", HITS, 0.0, "m")["status"] == "rejected"
    assert answer.judge("q", ABSTAIN, HITS, 0.0, "m")["status"] == "abstained"


def test_extractive_answer_uses_synonyms_and_cites():
    text, picked = answer.extractive("How much bid security has to be paid?", HITS)
    assert picked and picked[0][0] == 1
    assert "Rs. 22,316/-" in text and text.rstrip().endswith("[1]")
    assert grounding.check(text, {1: HITS[0].text, 2: HITS[1].text}).ok
    assert answer.extractive("Who is the chief guest at the inauguration?", HITS)[0] == ABSTAIN


def test_rrf_uses_ranks_only():
    fused = rrf([1, 2, 3], [3, 1])
    assert [cid for cid, _ in fused] == [1, 3, 2]


# --- eligibility --------------------------------------------------------------------------


def org(**kw):
    base = dict(
        annual_turnover_inr=None,
        largest_similar_work_inr=None,
        years_in_business=None,
        certifications=[],
    )
    return SimpleNamespace(**{**base, **kw})


def fields_for(text: str) -> tuple[dict, list]:
    doc = SimpleNamespace(pk=1, filename="NIT.pdf", page_texts=[text])
    return brief.document_fields(doc), [doc]


CRITERIA = (
    "ELIGIBILITY. Three similar completed works each costing not less than Rs. 40,00,000/- or "
    "two similar completed works each costing not less than Rs. 60,00,000/- or one similar "
    "completed work costing not less than Rs. 80,00,000/-. Average annual financial turnover "
    "during the last three years should be at least Rs. 50,00,000/-. The bidder should have a "
    "minimum 5 years of experience in similar works. MSEs registered with Udyam are exempted "
    "from payment of EMD."
)


def by_key(result):
    return {c["key"]: c for c in result["checks"]}


def test_eligibility_all_pass():
    fields, docs = fields_for(CRITERIA)
    r = eligibility.evaluate(
        fields,
        docs,
        org(
            annual_turnover_inr=Decimal("6000000"),
            largest_similar_work_inr=Decimal("9000000"),
            years_in_business=8,
            certifications=["MSE (Udyam)"],
        ),
    )
    checks = by_key(r)
    assert r["verdict"] == "eligible"
    assert checks["min_turnover"]["status"] == "pass"
    assert checks["min_turnover"]["yours"] == "₹60,00,000"
    assert checks["similar_work"]["status"] == "pass"
    assert checks["years"]["status"] == "pass"
    assert checks["mse_exemption"]["status"] == "pass"
    assert checks["min_turnover"]["source"] == {"document_id": 1, "filename": "NIT.pdf", "page": 1}


def test_eligibility_fails_and_stays_conservative():
    fields, docs = fields_for(CRITERIA)
    low = eligibility.evaluate(
        fields,
        docs,
        org(
            annual_turnover_inr=Decimal("4000000"),
            largest_similar_work_inr=Decimal("9000000"),
            years_in_business=8,
        ),
    )
    assert low["verdict"] == "not_eligible" and by_key(low)["min_turnover"]["status"] == "fail"
    # 70 lakh: enough for "two works of 60 lakh" only if they have two such works -> unknown.
    mid = eligibility.evaluate(
        fields,
        docs,
        org(
            annual_turnover_inr=Decimal("6000000"),
            largest_similar_work_inr=Decimal("7000000"),
            years_in_business=8,
        ),
    )
    assert by_key(mid)["similar_work"]["status"] == "unknown" and mid["verdict"] == "unknown"
    tiny = eligibility.evaluate(
        fields,
        docs,
        org(
            annual_turnover_inr=Decimal("6000000"),
            largest_similar_work_inr=Decimal("3000000"),
            years_in_business=8,
        ),
    )
    assert by_key(tiny)["similar_work"]["status"] == "fail"
    empty = eligibility.evaluate(fields, docs, org())
    assert empty["verdict"] == "unknown"
    assert {c["status"] for c in empty["checks"]} == {"unknown"}
    assert "company profile" in by_key(empty)["min_turnover"]["note"]


def test_eligibility_percent_only_requirement_is_unknown():
    fields, docs = fields_for(
        "Average annual turnover should be at least 30% of the estimated cost."
    )
    r = eligibility.evaluate(fields, docs, org(annual_turnover_inr=Decimal("1")))
    assert by_key(r)["min_turnover"]["status"] == "unknown"
    assert by_key(r)["similar_work"]["status"] == "unknown"  # not found in the documents
    assert r["verdict"] == "unknown"
