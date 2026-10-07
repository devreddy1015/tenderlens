"""The copilot prompt for the self-hosted tender LLM.

Copied from the LLM kit's prompt.py (the kit tuned it; it is kept off GitHub, next to the
repository, so it cannot be imported from here). The same prompt builds the fine-tuning set and
is used to evaluate every model: keep the two copies identical, and re-run the kit's
build_dataset.py and eval_llm.py after changing either.
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
3. Copy amounts, percentages, dates, times, periods and counts exactly as the passage writes \
them, with any qualifier that goes with them (such as "(60% of the estimated cost)"). Never \
calculate, convert, round, add up or compare values; if the question needs a calculation, give \
the values as written and say the documents do not state the result.
4. Tender words have synonyms: EMD = earnest money = bid security; tender fee = cost of \
tender document; performance guarantee = performance security; liquidated damages = \
compensation for delay; completion period = time allowed.
5. If the passages do not state the answer, reply with exactly this sentence and nothing \
else, no citation and no explanation of what the passages say instead: {ABSTAIN}
6. If they answer only part of the question, answer that part and say which part the \
documents do not mention.
7. Answer in the language of the question (English or Hindi), keeping amounts and dates as \
written. Rule 5's sentence stays in English.
8. Be brief: one to three sentences of plain text, no headings, lists or preamble."""

# Greedy and short; chat_template_kwargs turns off thinking on Qwen3-style templates
# (llama.cpp, vLLM and SGLang pass it to the template). clean_answer() strips any <think>
# block that still gets through. max_tokens is set per request from LLM_MAX_TOKENS.
REQUEST_PARAMS: dict = {
    "temperature": 0.0,
    "top_p": 1.0,
    "max_tokens": 300,
    "chat_template_kwargs": {"enable_thinking": False},
}

PASSAGE_HEADER = "[{n}] {filename}, p. {page}"

# Repeated after the question: a 4B model follows what it read last most closely.
REMINDER = f"Answer from the passages only, with [n] after every sentence. If they do not \
state the answer, reply exactly: {ABSTAIN}"


def format_passage(n: int, filename: str, page: int | str, text: str) -> str:
    return f"{PASSAGE_HEADER.format(n=n, filename=filename, page=page)}\n{text.strip()}"


def build_user_message(question: str, passages: Iterable[Mapping]) -> str:
    """passages: dicts with filename, page, text; numbered from 1 in the given order
    (best passage first: small models read the top of the context most closely)."""
    blocks = [
        format_passage(i, p["filename"], p["page"], p["text"])
        for i, p in enumerate(passages, start=1)
    ]
    return "Passages:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question.strip()}\n\n{REMINDER}"


def build_messages(question: str, passages: Iterable[Mapping]) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(question, passages)},
    ]


_THINK = re.compile(r"<think>.*?(?:</think>|$)", re.S | re.I)
_GEMMA_THOUGHT = re.compile(r"<\|channel>thought.*?(?:<channel\|>|$)", re.S)


def strip_think(text: str) -> str:
    """Drop reasoning blocks (Qwen <think>...</think>, Gemma thought channel), including an
    unterminated one cut off by max_tokens, and a stray closing tag."""
    text = _GEMMA_THOUGHT.sub("", _THINK.sub("", text))
    return text.replace("</think>", "").strip()


_ABSTAIN_FORMS = (
    "i couldn't find this in the tender documents",
    "i could not find this in the tender documents",
    "i couldn’t find this in the tender documents",
)
# "मुझे ... नहीं मिली" is how small models translate ABSTAIN despite rule 7.
_ABSTAIN_HI = re.compile(r"^(मुझे )?(यह|ये) (जानकारी )?निविदा (दस्तावेज़ों|दस्तावेजों) में नहीं मिल")


def is_abstention(text: str) -> bool:
    t = " ".join(unicodedata.normalize("NFKC", text).split()).strip().lower()
    t = t.strip('"').strip()
    return t.startswith(_ABSTAIN_FORMS) or bool(_ABSTAIN_HI.match(t))


# A refusal in the model's own words with no citation can never pass the grounding check, so
# it is shown as the standard sentence. Answers WITH a citation are left alone (rule 6).
_UNCITED_REFUSAL = re.compile(
    r"\b(?:(?:do|does|did) not (?:mention|specify|state|contain|provide|include|say)"
    r"|(?:is|are) not (?:mentioned|specified|stated|provided|given|available)"
    r"|no (?:information|mention|details?) )|उल्लेख नहीं|नहीं मिल|नहीं दी गई",
    re.I,
)


def clean_answer(text: str) -> str:
    """The text to show: thinking removed, an abstention (or an uncited refusal in other
    words) normalised to ABSTAIN exactly."""
    text = strip_think(text)
    if is_abstention(text) or (not CITATION.search(text) and _UNCITED_REFUSAL.search(text)):
        return ABSTAIN
    return text


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
