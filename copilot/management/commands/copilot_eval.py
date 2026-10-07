"""Retrieval / answer / Bid Brief benchmark on the synthetic corpus (copilot.evaluate).

    manage.py copilot_eval --pdfs ../docintel/data/pdfs/synthetic
    manage.py copilot_eval --pdfs ... --reranker cross-encoder/ms-marco-MiniLM-L-6-v2
    manage.py copilot_eval --pdfs ... --answers extractive        # no LLM needed
    manage.py copilot_eval --pdfs ... --answers llm --limit 20    # the LLM at LLM_BASE_URL

The PDFs are ingested into a throw-away organisation inside one transaction that is rolled
back at the end (unless --keep), so the benchmark leaves no rows behind.
"""

import hashlib
import json
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from copilot import evaluate, ingest
from copilot.extract import ocr_available
from copilot.models import Document
from workspaces.models import Organization

DEFAULT_EVAL = Path(settings.BASE_DIR) / "data" / "copilot" / "eval"


class Rollback(Exception):
    pass


class Command(BaseCommand):
    help = "Benchmark Copilot retrieval (recall@5, MRR@10), answers and the Bid Brief."

    def add_arguments(self, parser):
        parser.add_argument(
            "--pdfs", type=Path, default=Path(settings.BASE_DIR) / "data/copilot/pdfs"
        )
        parser.add_argument("--questions", type=Path, default=DEFAULT_EVAL / "questions.jsonl")
        parser.add_argument("--corpus", type=Path, default=DEFAULT_EVAL / "corpus.json")
        parser.add_argument(
            "--model", default=None, help="embedding model (default EMBEDDING_MODEL)"
        )
        parser.add_argument("--reranker", default=None, help="adds the hybrid_rerank mode")
        parser.add_argument("--split", default=None, help="only questions of this split")
        parser.add_argument("--answers", choices=["llm", "extractive"], default=None)
        parser.add_argument("--limit", type=int, default=None, help="answer questions to run")
        parser.add_argument("--json", type=Path, default=None, help="write all results here")
        parser.add_argument("--keep", action="store_true", help="keep the ingested documents")

    def handle(self, *args, **o):
        if o["model"]:
            settings.EMBEDDING_MODEL = o["model"]  # this process only
        corpus = json.loads(o["corpus"].read_text())
        questions = evaluate.load_questions(o["questions"], o["split"])
        files = {c["tender_id"]: o["pdfs"] / c["tender_id"] / Path(c["file"]).name for c in corpus}
        missing = [str(p) for p in files.values() if not p.exists()]
        if missing:
            raise CommandError(
                f"{len(missing)} PDFs not found under {o['pdfs']} (e.g. {missing[0]}). Copy "
                "../docintel/data/pdfs/synthetic there or pass --pdfs."
            )
        results: dict = {"embedding_model": settings.EMBEDDING_MODEL, "ocr": ocr_available()}
        try:
            with transaction.atomic():
                self._run(o, files, questions, results)
                if not o["keep"]:
                    raise Rollback
        except Rollback:
            pass
        if o["json"]:
            o["json"].write_text(json.dumps(results, indent=1, default=str))

    def _run(self, o, files, questions, results):
        org, _ = Organization.objects.get_or_create(
            slug="copilot-eval", defaults={"name": "Copilot evaluation"}
        )
        t0 = time.perf_counter()
        docs = {}
        for tid, path in files.items():
            doc, _ = Document.objects.get_or_create(
                organization=org,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                defaults={"filename": path.name, "file": str(path), "bytes": path.stat().st_size},
            )
            docs[tid] = ingest.process(doc, path=path)
        failed = [d.filename for d in docs.values() if d.status != Document.Status.READY]
        n_chunks = sum(d.chunks.count() for d in docs.values())
        self.stdout.write(
            f"Ingested {len(docs)} PDFs ({n_chunks} chunks, OCR "
            f"{'on' if results['ocr'] else 'off'}) with {settings.EMBEDDING_MODEL} in "
            f"{time.perf_counter() - t0:.1f}s; failed: {failed or 'none'}"
        )
        doc_of = {tid: d.pk for tid, d in docs.items() if d.status == Document.Status.READY}

        modes = ["fts", "dense", "hybrid"] + (["hybrid_rerank"] if o["reranker"] else [])
        scores = []
        for scoped in (True, False):
            scores += evaluate.eval_retrieval(
                questions, doc_of, org.pk, modes, scoped=scoped, reranker=o["reranker"]
            )
        self.stdout.write("\n" + evaluate.retrieval_table(scores) + "\n")
        results["retrieval"] = [s.__dict__ for s in scores]

        b = evaluate.eval_brief(questions, {t: d for t, d in docs.items() if t in doc_of})
        self.stdout.write(f"Bid Brief: {b['correct']}/{b['total']} fields correct")
        for key, (ok, n) in sorted(b["per_key"].items()):
            self.stdout.write(f"  {key:22} {ok}/{n}")
        results["brief"] = b

        if o["answers"]:
            qs = questions[: o["limit"]] if o["limit"] else questions
            a = evaluate.eval_answers(qs, doc_of, org.pk, use_llm=o["answers"] == "llm")
            summary = {k: v for k, v in a.items() if k != "rows"}
            self.stdout.write("\nAnswers: " + json.dumps(summary, default=str))
            results["answers"] = a
