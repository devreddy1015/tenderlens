"""The copilot prompt for the self-hosted tender LLM, as plain constants and tiny helpers.

Standard library only, so the Django copilot can copy this file (or its constants) as is.
The same prompt is used to build the fine-tuning set and to evaluate every model, so a
change here must be followed by `build_dataset.py` and `eval_llm.py` runs.

Request contract (OpenAI chat completions, any compatible server):
    messages = build_messages(question, passages)
    POST {LLM_BASE_URL}/chat/completions {"model": ..., "messages": messages, **REQUEST_PARAMS}
    answer = clean_answer(response["choices"][0]["message"]["content"])
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping

ABSTAIN = "I couldn't find this in the tender documents."

SYSTEM_PROMPT = f"""You answer questions about Indian public tender documents (notices inviting \
tender, bid documents, corrigenda) for contractors deciding whether and how to bid.

The user message holds numbered passages from the tender documents, each starting with a \
header like "[2] NIT.pdf, p. 3", and then the question.

Rules:
1. Use only the passages. Never add facts from memory or general knowledge.
2. End every sentence with the number of the passage that supports it, like this: \
"The EMD is Rs. 9,38,100/- [2]." Cite only a passage that states the fact.
3. Copy amounts, percentages, dates, times and periods exactly as the passage writes them. \
Never calculate, convert, round, add up or compare values; if the question needs a \
calculation, give the values as written and say the documents do not state the result.
4. If the passages do not answer the question, reply with exactly this sentence and nothing \
else: {ABSTAIN}
5. If they answer only part of the question, answer that part and say which part the \
documents do not mention.
6. Answer in the language of the question (English or Hindi), keeping amounts and dates as \
written. Rule 4's sentence stays in English.
7. Be brief: one to three sentences of plain text, no headings, lists or preamble."""

# Sampling for grounded extraction: greedy, short. presence_penalty is not needed at
# temperature 0; repetition loops are cut by max_tokens. chat_template_kwargs turns off
# thinking on Qwen3/Qwen3.5-style templates (llama.cpp, vLLM and SGLang all pass it to the
# template); servers also run with thinking off (`--reasoning off`), and clean_answer()
# strips any <think> block that still gets through.
REQUEST_PARAMS: dict = {
    "temperature": 0.0,
    "top_p": 1.0,
    "max_tokens": 300,
    "chat_template_kwargs": {"enable_thinking": False},
}

PASSAGE_HEADER = "[{n}] {filename}, p. {page}"


def format_passage(n: int, filename: str, page: int | str, text: str) -> str:
    return f"{PASSAGE_HEADER.format(n=n, filename=filename, page=page)}\n{text.strip()}"


def build_user_message(question: str, passages: Iterable[Mapping]) -> str:
    """passages: dicts with filename, page, text; numbered from 1 in the given order
    (put the best passage first: small models read the top of the context most closely)."""
    blocks = [
        format_passage(i, p["filename"], p["page"], p["text"])
        for i, p in enumerate(passages, start=1)
    ]
    return "Passages:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question.strip()}"


def build_messages(question: str, passages: Iterable[Mapping]) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(question, passages)},
    ]


_THINK = re.compile(r"<think>.*?(?:</think>|$)", re.S | re.I)
_GEMMA_THOUGHT = re.compile(r"<\|channel>thought.*?(?:<channel\|>|$)", re.S)


def strip_think(text: str) -> str:
    """Drop reasoning blocks (Qwen <think>...</think>, Gemma 4 thought channel), including
    an unterminated one cut off by max_tokens, and a stray closing tag."""
    text = _GEMMA_THOUGHT.sub("", _THINK.sub("", text))
    return text.replace("</think>", "").strip()


# "मुझे ... नहीं मिली" is how small models translate ABSTAIN despite rule 6.
_ABSTAIN_FORMS = (
    "i couldn't find this in the tender documents",
    "i could not find this in the tender documents",
    "i couldn’t find this in the tender documents",
)
_ABSTAIN_HI = re.compile(r"^(मुझे )?(यह|ये) (जानकारी )?निविदा (दस्तावेज़ों|दस्तावेजों) में नहीं मिल")


def is_abstention(text: str) -> bool:
    t = " ".join(unicodedata.normalize("NFKC", text).split()).strip().lower()
    t = t.strip('"').strip()
    return t.startswith(_ABSTAIN_FORMS) or bool(_ABSTAIN_HI.match(t))


def clean_answer(text: str) -> str:
    """The text to show: thinking removed, an abstention normalised to ABSTAIN exactly."""
    text = strip_think(text)
    return ABSTAIN if is_abstention(text) else text


CITATION = re.compile(r"\[(\d{1,2}(?:\s*[,–-]\s*\d{1,2})*)\]")


def cited_numbers(text: str) -> list[int]:
    """[2], [1, 3], [1][2] and [2-4] all count; order of first appearance, no repeats."""
    out: list[int] = []
    for m in CITATION.finditer(text):
        for part in m.group(1).split(","):
            lo, _, hi = part.replace("–", "-").partition("-")
            first = int(lo)
            for n in range(first, max(first, int(hi or lo)) + 1):
                if n not in out:
                    out.append(n)
    return out
