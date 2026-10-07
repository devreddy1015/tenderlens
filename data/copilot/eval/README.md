# Copilot evaluation set

`questions.jsonl` and `corpus.json` are DocIntel's synthetic benchmark (copied from
`../docintel/data/eval/`): 30 generated notices built from real TenderLens tenders, 480
questions (41 unanswerable). The PDFs (24 MB) are not in this repo; point the command at
DocIntel's copy:

```
uv run --frozen python manage.py copilot_eval --pdfs ../docintel/data/pdfs/synthetic
uv run --frozen python manage.py copilot_eval --pdfs ... --reranker cross-encoder/ms-marco-MiniLM-L-6-v2
uv run --frozen python manage.py copilot_eval --pdfs ... --answers extractive   # no LLM
uv run --frozen python manage.py copilot_eval --pdfs ... --answers llm --limit 30
```

The documents are ingested into a throw-away organisation inside one transaction that is
rolled back at the end, so the command can run against any database.

Format of a question (see DocIntel's README for the full description):

```json
{"id": "2026_ITBP_925996_1:emd", "tender_id": "2026_ITBP_925996_1", "question": "How much bid security has to be paid?",
 "answerable": true, "answer": "Rs. 9,38,100/-", "evidence": ["earnest money", "Rs. 9,38,100/-"],
 "global_question": "... for “Construction of SOs ...”?", "fact": "emd", "split": "test"}
```

A chunk is relevant when it contains every `evidence` fragment (case and whitespace
normalised). Synthetic text is more regular than real notices: treat the numbers as an
upper bound and add hand-written questions on real documents before quoting them.
