"""Tender PDFs -> pages -> passages, plus a small BM25, shared by build_dataset.py and
eval_llm.py.

Extraction and chunking follow DocIntel (`docintel/extract.py`, `docintel/chunking.py`), which
the Django copilot ports, so the passages the model trains and is evaluated on look like the
ones it will see in production: clause-aligned chunks with running headers/footers removed.

Scanned pages and pages whose Hindi text layer is garbled need OCR. `python corpus.py ocr`
writes OCR'd copies with ocrmypdf (Tesseract eng+hin); extraction then prefers the OCR'd
page wherever the original page is scanned or garbled.
"""

import argparse
import json
import math
import re
import shutil
import subprocess
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
DOCINTEL = HERE.parent.parent / "docintel"
DEFAULT_PDF_DIR = DOCINTEL / "data" / "pdfs"
DEFAULT_EVAL_DIR = DOCINTEL / "data" / "eval"
DEFAULT_OCR_DIR = HERE / "data" / "ocr"

MIN_TEXT_CHARS = 40
GARBLE_THRESHOLD = 0.05
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_DIGITS = re.compile(r"\d+")


def garbled_devanagari(text: str) -> bool:
    """Hindi text layers in Indian PDFs often map conjuncts to Latin-Extended or private-use
    code points ("निविदा" -> "न ȡ व ȡ दा"); such text is noise for retrieval and the model."""
    deva = sum(1 for c in text if "ऀ" <= c <= "ॿ")
    if deva < 20:
        return False
    junk = sum(1 for c in text if "ƀ" <= c <= "ɏ" or "" <= c <= "" or "̀" <= c <= "ͯ")
    return junk / deva > GARBLE_THRESHOLD


def _garbled_line(line: str) -> bool:
    deva = sum(1 for c in line if "ऀ" <= c <= "ॿ")
    junk = sum(1 for c in line if "ƀ" <= c <= "ɏ" or "" <= c <= "")
    return deva >= 3 and junk >= 2


def clean_text(text: str) -> str:
    """NFKC turns ligatures back into letters ("ﬁnancial" -> "financial"); words hyphenated
    across a line break are rejoined."""
    return _HYPHEN_BREAK.sub(r"\1-\2", unicodedata.normalize("NFKC", text))


@dataclass
class Page:
    number: int
    text: str
    ocr: bool = False


def _read(path: Path) -> list[tuple[str, bool]]:
    out = []
    with pymupdf.open(path) as doc:
        for page in doc:
            raw = page.get_text("text", sort=True)
            garbled = garbled_devanagari(raw)
            text = clean_text(raw)
            scanned = len(text.strip()) < MIN_TEXT_CHARS and bool(page.get_images(full=False))
            out.append((text, scanned or garbled))
    return out


def extract_pages(path: Path, ocr_dir: Path | None = DEFAULT_OCR_DIR) -> list[Page]:
    """Text per page; a scanned or garbled page is replaced by its OCR'd version when one
    exists, otherwise its garbled lines are dropped (better no Hindi than mojibake)."""
    pages = _read(path)
    ocr_pdf = ocr_dir / f"{path.stem}.ocr.pdf" if ocr_dir else None
    redone = _read(ocr_pdf) if ocr_pdf and ocr_pdf.exists() else None
    out = []
    for i, (text, bad) in enumerate(pages):
        if bad and redone and i < len(redone) and len(redone[i][0].strip()) >= MIN_TEXT_CHARS:
            out.append(Page(i + 1, redone[i][0], ocr=True))
            continue
        if bad:
            text = "\n".join(ln for ln in text.splitlines() if not _garbled_line(ln))
        out.append(Page(i + 1, text))
    return out


# --- chunking (DocIntel's clause-aligned chunker) -------------------------------------

_NUMBERED = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,3})[.)]?\s+\S")
_KEYWORD = re.compile(r"^\s*(Section|Clause|Annexure|Schedule|Chapter|Part|Appendix)\b", re.I)
_SENTENCE = re.compile(r"(?<=[.;:।])\s+(?=[A-Z0-9(ऀ-ॿ])")


def approx_tokens(text: str) -> int:
    return max(1, round(len(text.split()) * 1.3))


def is_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90:
        return False
    if _NUMBERED.match(s) or _KEYWORD.match(s):
        return True
    letters = [c for c in s if c.isalpha()]
    return (
        len(letters) >= 6
        and sum(c.isupper() for c in letters) / len(letters) > 0.8
        and len(s.split()) <= 10
    )


def running_lines(pages: list[Page]) -> set[str]:
    if len(pages) < 3:
        return set()
    counts: Counter = Counter()
    for page in pages:
        counts.update({_DIGITS.sub("#", ln.strip()) for ln in page.text.splitlines() if ln.strip()})
    return {k for k, n in counts.items() if n >= max(3, 0.6 * len(pages))}


@dataclass
class Section:
    heading: str
    lines: list[tuple[int, str]] = field(default_factory=list)


def _sections(pages: list[Page]) -> list[Section]:
    out = [Section(heading="")]
    skip = running_lines(pages)
    for page in pages:
        for raw in page.text.splitlines():
            line = raw.strip()
            if not line or _DIGITS.sub("#", line) in skip:
                continue
            if is_heading(line):
                out.append(Section(heading=line, lines=[(page.number, line)]))
            else:
                out[-1].lines.append((page.number, line))
    return [s for s in out if s.lines]


def _split_long(lines, max_tokens: int, overlap: int):
    units = [(p, s) for p, line in lines for s in _SENTENCE.split(line) if s.strip()]
    pieces, cur, cur_tokens = [], [], 0
    for unit in units:
        t = approx_tokens(unit[1])
        if cur and cur_tokens + t > max_tokens:
            pieces.append(cur)
            tail, tail_tokens = [], 0
            for u in reversed(cur):
                tail_tokens += approx_tokens(u[1])
                tail.insert(0, u)
                if tail_tokens >= overlap:
                    break
            cur, cur_tokens = list(tail), tail_tokens
        cur.append(unit)
        cur_tokens += t
    if cur:
        pieces.append(cur)
    return pieces


@dataclass
class Chunk:
    tender_id: str
    filename: str
    ord: int
    page: int  # first page, as the passage header cites it
    page_to: int
    heading: str
    text: str

    @property
    def passage(self) -> dict:
        return {"filename": self.filename, "page": self.page, "text": self.text}


def chunk_pages(
    pages: list[Page],
    *,
    tender_id: str = "",
    filename: str = "",
    target: int = 350,
    max_tokens: int = 600,
    overlap: int = 60,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    buf: list[tuple[int, str]] = []
    buf_heading = ""

    def emit(lines, heading: str) -> None:
        text = "\n".join(t for _, t in lines).strip()
        if text:
            pages_ = [p for p, _ in lines]
            chunks.append(
                Chunk(tender_id, filename, len(chunks), min(pages_), max(pages_), heading, text)
            )

    for sec in _sections(pages):
        sec_text = "\n".join(t for _, t in sec.lines)
        sec_tokens = approx_tokens(sec_text)
        if sec_tokens > max_tokens:
            if buf:
                emit(buf, buf_heading)
                buf = []
            for piece in _split_long(sec.lines, max_tokens, overlap):
                if sec.heading and piece[0][1] != sec.heading:
                    piece = [(piece[0][0], f"{sec.heading} (continued)"), *piece]
                emit(piece, sec.heading)
            continue
        buf_tokens = approx_tokens("\n".join(t for _, t in buf)) if buf else 0
        if buf and buf_tokens + sec_tokens > max_tokens:
            emit(buf, buf_heading)
            buf = []
        if not buf:
            buf_heading = sec.heading
        buf.extend(sec.lines)
        if approx_tokens("\n".join(t for _, t in buf)) >= target:
            emit(buf, buf_heading)
            buf = []
    if buf:
        emit(buf, buf_heading)
    return chunks


# --- tenders ---------------------------------------------------------------------------


@dataclass
class Tender:
    tender_id: str
    split: str  # train | test
    pdfs: list[Path]
    pages: dict[str, list[Page]]  # filename -> pages

    def chunks(self, target: int = 350, max_tokens: int = 600) -> list[Chunk]:
        out: list[Chunk] = []
        for name, pages in self.pages.items():
            out.extend(
                chunk_pages(
                    pages,
                    tender_id=self.tender_id,
                    filename=name,
                    target=target,
                    max_tokens=max_tokens,
                )
            )
        return out

    @property
    def text(self) -> str:
        return "\n".join(p.text for pages in self.pages.values() for p in pages)


def _tender_id_for(pdf: Path, root: Path) -> str:
    rel = pdf.relative_to(root)
    if len(rel.parts) > 1:  # data/pdfs/<tender_id>/<file>.pdf or synthetic/<tender_id>/...
        return rel.parts[-2]
    m = re.match(r"(\d{4}_[A-Za-z0-9&]+_\d+_\d+)", pdf.stem)
    return m.group(1) if m else pdf.stem


def _stable_split(tender_id: str, test_share: float = 0.25) -> str:
    """Deterministic split for tenders the eval corpus does not list (real PDFs)."""
    h = int.from_bytes(tender_id.encode(), "little") % 1000
    return "test" if h < test_share * 1000 else "train"


def load_tenders(
    pdf_dir: Path = DEFAULT_PDF_DIR,
    eval_dir: Path = DEFAULT_EVAL_DIR,
    ocr_dir: Path | None = DEFAULT_OCR_DIR,
) -> list[Tender]:
    """Every PDF under pdf_dir, grouped by tender. Splits come from the eval corpus
    (corpus.json) when it lists the tender, so the eval's test tenders are never trained on."""
    splits: dict[str, str] = {}
    corpus = eval_dir / "corpus.json"
    if corpus.exists():
        splits = {t["tender_id"]: t.get("split", "train") for t in json.loads(corpus.read_text())}
    by_tender: dict[str, list[Path]] = {}
    for pdf in sorted(pdf_dir.rglob("*.pdf")):
        if pdf.name.endswith(".ocr.pdf"):
            continue
        by_tender.setdefault(_tender_id_for(pdf, pdf_dir), []).append(pdf)
    out = []
    for tid, pdfs in sorted(by_tender.items()):
        pages = {p.name: extract_pages(p, ocr_dir) for p in pdfs}
        out.append(Tender(tid, splits.get(tid) or _stable_split(tid), pdfs, pages))
    return out


def load_questions(eval_dir: Path = DEFAULT_EVAL_DIR) -> list[dict]:
    path = eval_dir / "questions.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"\s+", " ", s).replace("- ", "-").strip()


def contains_evidence(text: str, evidence) -> bool:
    """DocIntel's relevance rule: every evidence fragment appears in the passage."""
    frags = [evidence] if isinstance(evidence, str) else list(evidence or [])
    t = norm(text)
    return bool(frags) and all(norm(f) in t for f in frags)


# --- BM25 ------------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9ऀ-ॿ]+")
STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "to",
        "in",
        "on",
        "for",
        "and",
        "or",
        "is",
        "are",
        "be",
        "by",
        "with",
        "what",
        "which",
        "who",
        "when",
        "how",
        "much",
        "many",
        "this",
        "that",
        "these",
        "those",
        "does",
        "do",
        "any",
        "there",
        "their",
        "it",
        "its",
        "from",
        "at",
        "as",
        "must",
        "shall",
        "should",
        "will",
        "can",
        "i",
        "we",
        "our",
        "my",
        "me",
        "you",
        "your",
        "has",
        "have",
        "get",
    ]
)


def tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall(norm(text)) if w not in STOP]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.2, b: float = 0.75):
        self.toks = [tokenize(d) for d in docs]
        self.k1, self.b = k1, b
        self.avg = sum(map(len, self.toks)) / max(1, len(self.toks))
        df: Counter = Counter()
        for t in self.toks:
            df.update(set(t))
        n = len(self.toks)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}
        self.tf = [Counter(t) for t in self.toks]

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, toks in zip(self.tf, self.toks, strict=True):
            s = 0.0
            for w in q:
                if w in tf:
                    f = tf[w]
                    s += (
                        self.idf[w]
                        * f
                        * (self.k1 + 1)
                        / (f + self.k1 * (1 - self.b + self.b * len(toks) / self.avg))
                    )
            out.append(s)
        return out

    def rank(self, query: str) -> list[int]:
        s = self.scores(query)
        return sorted(range(len(s)), key=lambda i: -s[i])


@lru_cache(maxsize=256)
def _bm25_cached(key: tuple) -> BM25:
    return BM25(list(key))


def bm25_rank(chunks: list[Chunk], query: str) -> list[int]:
    return _bm25_cached(tuple(c.text for c in chunks)).rank(query)


# --- OCR -------------------------------------------------------------------------------


def ocr_all(pdf_dir: Path, out_dir: Path) -> int:
    """OCR every PDF that has a scanned or garbled page (eng+hin). Needs ocrmypdf; on a
    machine without it, run this inside the DocIntel image (see README)."""
    if not shutil.which("ocrmypdf"):
        raise SystemExit("ocrmypdf not found (apt install ocrmypdf tesseract-ocr-hin)")
    out_dir.mkdir(parents=True, exist_ok=True)
    done = 0
    for pdf in sorted(pdf_dir.rglob("*.pdf")):
        if pdf.name.endswith(".ocr.pdf"):
            continue
        pages = _read(pdf)
        if not any(bad for _, bad in pages):
            continue
        garbled = any(garbled_devanagari(t) for t, _ in pages)
        dest = out_dir / f"{pdf.stem}.ocr.pdf"
        if dest.exists():
            continue
        subprocess.run(
            [
                "ocrmypdf",
                "--force-ocr" if garbled else "--skip-text",
                "--language",
                "eng+hin",
                "--output-type",
                "pdf",
                "--quiet",
                str(pdf),
                str(dest),
            ],
            check=True,
            timeout=900,
        )
        done += 1
        print(f"ocr {pdf.name} ({'garbled' if garbled else 'scanned'})", flush=True)
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("ocr", help="OCR scanned/garbled PDFs into the OCR cache")
    o.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    o.add_argument("--out", type=Path, default=DEFAULT_OCR_DIR)
    s = sub.add_parser("stats", help="pages, chunks and passage sizes per tender")
    s.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    a = ap.parse_args()
    if a.cmd == "ocr":
        print(f"{ocr_all(a.pdf_dir, a.out)} PDFs OCR'd")
    else:
        tenders = load_tenders(a.pdf_dir)
        for t in tenders:
            ch = t.chunks()
            n_ocr = sum(p.ocr for ps in t.pages.values() for p in ps)
            sizes = [approx_tokens(c.text) for c in ch]
            print(
                f"{t.tender_id:28} {t.split:5} pages={sum(map(len, t.pages.values()))} "
                f"ocr={n_ocr} chunks={len(ch)} tokens~{sizes}"
            )


if __name__ == "__main__":
    main()
