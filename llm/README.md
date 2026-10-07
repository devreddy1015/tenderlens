# TenderLens LLM kit

Our own tender-specialised LLM, served from our own box, so a copilot answer costs no money
per token. Standalone (own `pyproject.toml`, never installed in the web image):

| File | What it does |
|---|---|
| `prompt.py` | The copilot prompt as plain constants + tiny helpers (stdlib only; the Django `copilot` app copies it). |
| `grounding.py` | Post-check: every amount/date/percentage in an answer must appear in a passage it cites. |
| `corpus.py` | PDF → pages (OCR cache for scanned/garbled Hindi pages) → DocIntel-style chunks, BM25. |
| `build_dataset.py` | Fine-tuning set: grounded, cited answers in English and Hindi + abstentions. |
| `train_qlora.py` | 4-bit QLoRA on an 8 GB RTX 4060 (`--smoke` = CPU check on a tiny model). |
| `export_gguf.py` | adapter → merged model → GGUF → Q4_K_M → Ollama Modelfile. |
| `eval_llm.py` | Scores any OpenAI-compatible endpoint (or two side by side) on DocIntel's eval set. |
| `../deploy/llm/compose.llm.yml` | The `llm` service (llama.cpp server), CPU default + CUDA variant. |
| `../deploy/llm/Modelfile` | The same model for Ollama users. |

```bash
cd llm && uv sync                       # base: pymupdf + httpx (dataset, eval)
uv sync --extra train                   # + torch/transformers/peft/bitsandbytes (training, export)
```

Data comes from `../docintel/data/` (read only): 30 synthetic bilingual tender notices
(`pdfs/synthetic/`, 20 train / 10 test tenders) and 480 labelled questions
(`eval/questions.jsonl`: 15 facts x 30 tenders + 30 unanswerable). `data/ocr/` holds the
Tesseract (eng+hin) copies of the 11 PDFs whose Hindi text layer is garbled.

## 1. Model choice

All four candidates are downloaded as Q4_K_M GGUFs in `models/` (git-ignored). Licences
re-checked on the Hugging Face API on 2026-10-06: **all Apache-2.0, none gated**, so all are
fine for a commercial SaaS (keep the licence notice; no usage caps, no MAU clauses).

| Model | Params | Q4_K_M | Hindi | QLoRA in 8 GB | CPU speed here | Notes |
|---|---:|---:|---|---|---|---|
| **Qwen3.5-4B** (pick) | 4.2 B text (+ vision tower, 4.66 B total) | 2.55 GiB | yes (201 languages) | yes, ~6 GB est. | pp 26.5 / tg 5.8 tok/s* | Newest Qwen; hybrid Gated-DeltaNet/attention (cheap long context); thinking must be switched off. |
| Qwen3.5-2B | 2.3 B | 1.19 GiB | yes | easily (~3.5 GB) | not measured here; ~2x the 4B by size | Fallback for a small CPU VPS; expect weaker abstention (smaller model). |
| Qwen3-4B-Instruct-2507 | 4.0 B | 2.33 GiB | yes (119 languages) | yes, ~5.5 GB | not measured here; similar size to 3.5-4B | Plain transformer: best tooling (Unsloth, vLLM, every converter); non-thinking only. Safe fallback base for training. |
| gemma-4-E4B-it | 8.0 B stored (4 B "effective") | 4.64 GiB | yes | tight: per-layer embeddings make the 4-bit model ~5 GB before activations | not measured here; ~2x the bytes per token of the 4Bs | Strong multilingual, but twice the RAM and disk for the same quality class. |

\* `llama bench`, Q4_K_M, CPU only, i7-12700H **on battery in the "quiet" platform profile**
(cores held at ~0.9 GHz; see §6): `pp1500` 22.4 tok/s (6 threads) / 26.5 (12 threads),
`tg64` 5.8 tok/s (6 threads) / 4.2 (12 threads). Hence `-t 6 -tb 12`: generation is
memory-bound (fewer threads win), prompt processing compute-bound (more threads win). Expect
roughly 3x these numbers on mains power in the "performance" profile, and far more on a GPU.
Server RAM: **3.4 GiB** resident (`docker stats`) with an 8k context.

**Pick: Qwen3.5-4B** for serving and as the default fine-tuning base: Apache-2.0, Hindi, the
newest and strongest of the small Qwen line, fits a 4060 for QLoRA and 4 GB of RAM for
serving, and it is what the server runs today. (This run measured only the served model; a
side-by-side of the other three GGUFs is one command each with `eval_llm.py --sample 40`
against a second llama.cpp container on :8082, best done on mains power.) If its hybrid layers give trouble in training (they need recent transformers;
`flash-linear-attention` + `causal-conv1d` make them fast, the torch fallback is slow but works),
train `--base Qwen/Qwen3-4B-Instruct-2507` instead: the prompt, dataset and eval are unchanged.

## 2. Serving

```bash
docker compose --project-directory . -f deploy/llm/compose.llm.yml up -d llm   # from the repo root
curl -s http://127.0.0.1:8081/v1/models
```

`LLM_BASE_URL=http://llm:8080/v1` (inside compose) or `http://127.0.0.1:8081/v1` (host),
`LLM_MODEL=tenderlens-qwen3.5-4b`. Key flags: `--jinja` (the model's own chat template),
`--reasoning off` + `--chat-template-kwargs '{"enable_thinking":false}'` (Qwen3.5 thinks by
default; thinking costs hundreds of tokens per answer and does not help extraction), `-c 8192`,
`-np 1` on CPU, `-cram 512` (reuses the KV cache of the shared system prompt). Swap in a
fine-tuned model with `LLM_GGUF=... LLM_ALIAS=...`. The CUDA variant is in the same file
(`-ngl 99 -fa on -np 4`). Ollama: `ollama create tenderlens-qwen3.5-4b -f deploy/llm/Modelfile`.

## 3. Prompt (`prompt.py`)

`build_messages(question, passages)` → system prompt + user message with numbered passages
(`[2] NIT.pdf, p. 3`), the question, and a one-line reminder of the two rules a 4B model breaks
most (cite `[n]` after every sentence; the exact abstention sentence). `REQUEST_PARAMS`:
temperature 0, max_tokens 300, `enable_thinking: false`. `clean_answer()` strips `<think>`
(and Gemma's thought channel), and maps an uncited refusal in the model's own words ("The
documents do not state ...") to exactly **"I couldn't find this in the tender documents."**
(such an answer can never pass grounding anyway). Rules: passages only; `[n]` per sentence;
copy amounts/dates exactly with their qualifiers, never calculate; tender synonyms (EMD = earnest
money = bid security, ...); exact abstention; partial answers say what is missing; answer in the
question's language (Hindi or English) keeping figures as written.

Probe (10 train-split items covering each failure mode, `eval_llm.py --probe`), against the
running Qwen3.5-4B:

| Prompt | value match | valid citation | grounded | abstention acc. | confident-wrong | `<think>` leaks |
|---|---:|---:|---:|---:|---:|---:|
| v1 (as found) | 7/8 | 0.80 | 0.90 | 0.80 (0/2 abstained) | 1 | 0 |
| v2 (synonyms, stricter rule 5, reminder, refusal mapping) | 7/8 | 0.89 | 1.00 | 0.90 (1/2) | 1 | 0 |

The remaining "miss" copies "Two similar completed works" as written, while DocIntel's label
says "2 similar works" (the metric's strictness, not a wrong answer); v1 answered "bid
security?" with "the documents do not mention bid security, the EMD is ..." (fixed by the
synonym rule). The hard case left is the no-gold item: with on-topic distractors the model
derives the estimated cost from "60% equals Rs. 8,34,600/-" instead of abstaining; it is
flagged as a hedge, and the grounding post-check rejects any number it computes.

## 4. Fine-tuning

```bash
uv run python build_dataset.py            # -> out/dataset/{train,val}.jsonl, stats.json (13 s)
uv sync --extra train
uv run python train_qlora.py              # Qwen/Qwen3.5-4B, 2 epochs
uv run python export_gguf.py --adapter out/qlora/qwen3.5-4b-tender/adapter
LLM_GGUF=qwen3.5-4b-tender-Q4_K_M.gguf LLM_ALIAS=tenderlens-qwen3.5-4b-ft ...   # serve on :8082
uv run python eval_llm.py --endpoint base=http://127.0.0.1:8081/v1 --endpoint ft=http://127.0.0.1:8082/v1
```

**Dataset (built 2026-10-06):** 1,341 train + 236 validation examples (9.1 MB), from the 20
train tenders (17 train, 3 validation: `2026_DDA_927826_1`, `2026_IITKG_925916_1`,
`2026_UoH_928328_1`); the 10 eval test tenders are never used. Kinds: 1,244 single-fact
answers (English and Hindi), 105 two-fact answers, 67 partial answers, 165 abstentions with
distractor passages (every passage holding the answer removed), 27 abstentions on DocIntel's
unanswerable questions; 1,136 English / 420 Hindi questions (Hindi questions get Hindi answers
with figures as written). Training questions use `train_question` and hand-written paraphrases,
never the eval wording. Passage order is shuffled in half the examples so the gold passage is
not always `[1]` (it was in 69% before). Every templated answer passes `grounding.check` (0
dropped). 1,341/1,341 fit 2,048 tokens (mean 1,432, max 1,774 with the Qwen3 tokenizer); that
window holds 2–3 passages, while production sends 4: use `--seq 3072` if VRAM allows.

Options: `--extra-pdf-dir DIR` adds real tender PDFs (one folder per tender); facts come from
regex rules (`RULES`: EMD, fee, estimated cost, completion, validity, last date) and are kept
only when every match in the tender agrees. `--teacher URL --teacher-model M` asks any
OpenAI-compatible model (e.g. a 32B on a rented GPU) for each answer and keeps it only if it
passes the same checks as the template (grounded, cites the gold passage, right value; else
exact abstention) — more natural wording without trusting the teacher.

**Training (`train_qlora.py`):** NF4 4-bit base with double quantisation, bf16 compute; LoRA
r=16, alpha=32, dropout 0.05 on all language-model linear layers (vision tower excluded);
seq 2048; gradient checkpointing; batch 1 x accumulation 16; lr 2e-4 cosine, 3% warm-up; 2
epochs (~170 optimizer steps); paged 8-bit AdamW; loss on answer tokens only. Logits are
computed only at answer positions (`logits_to_keep`): with Qwen3.5's 248k vocabulary,
full-sequence logits at 2,048 tokens would add ~4 GB (fp32 logits + gradient). VRAM estimate
for Qwen3.5-4B: ~2.6 GB NF4 weights + ~1.3 GB bf16 embeddings + LoRA/optimizer <0.2 GB +
checkpointed activations ~1.5 GB ≈ **6 GB of 8**; the script prints allocated/peak/reserved
VRAM at every log step. Estimated time on a 4060: 1–2 h (2.4 M training tokens x 2 epochs).
`--smoke` ran here on CPU (tiny Qwen3, 8 steps, 55 s, adapter saved): the data path, chat
template, masking, `logits_to_keep` loss and saving work end to end. The real run needs the GPU
(§6).

**Export (`export_gguf.py`):** merges the adapter into the bf16 base on CPU (~9 GB RAM for a 4B
model), runs llama.cpp's `convert_hf_to_gguf.py` (shallow clone into `out/llama.cpp`), quantises
to Q4_K_M with `llama quantize` from the same `llama.cpp:server` image we serve with (Docker, no
local build), writes `models/<name>-Q4_K_M.gguf` and `models/<name>.Modelfile`.

## 5. Evaluation (`eval_llm.py`)

Items: each test-split question with the tender's top-k BM25 chunks (k=4, the copilot default,
in `prompt.py` format; the gold passage is injected in the last slot if BM25 missed it, so this
measures the model, not retrieval), DocIntel's unanswerable questions, and "no-gold" items (the
same question with every passage holding the answer removed). Metrics: exact value match
(DocIntel's, "Rs. 9,38,100/-" == "₹9,38,100"), valid-citation rate, grounding rate, abstention
accuracy, confident-wrong (answered, no hedge, wrong), served-correct/served-wrong (what the
copilot would actually show after the grounding post-check). Results are resumable JSONL in
`out/eval/<run>/`.

**Baseline: Qwen3.5-4B Q4_K_M, prompt v2, k=4, test split** (`--split test --sample 40`, a
fixed stratified sample of 42 items). The run was stopped at **15/42 items** (10 answerable, 1
unanswerable, 4 no-gold) because the laptop was on battery at 12%; resume it with the same
command (`uv run python eval_llm.py --endpoint base=http://127.0.0.1:8081/v1 --split test
--sample 40 --run test-k4-s40`; finished rows are kept) and update this table.

| metric | base (15 items) |
|---|---:|
| exact value match | 0.90 (9/10) |
| valid-citation rate | 0.90 |
| grounding rate (numbers in cited passage) | 1.00 |
| abstention accuracy | 1.00 (5/5 abstained; 0 false abstentions) |
| confident-wrong | 1 |
| served correct / served wrong | 0.90 / 1 |
| `<think>` leaks | 0 |
| prompt / answer tokens (mean) | 2,300 / 34 |
| latency p50 (battery, quiet profile) | 81 s (pp 25.3 tok/s, tg 5.1 tok/s) |

The one "wrong" is again `similar_works`: the model writes "one similar work" where the label
says "1 similar work" and drops "(80% of the estimated cost)" — copied words, so it passes
grounding; fine-tuning targets exactly this (labels keep the qualifier). Small n: treat these as
a smoke-level baseline until the full 197-item test run (≈5 h on this CPU on battery, well under
an hour on mains power or minutes on a GPU).

## 6. GPU: why the RTX 4060 is not usable, and the fix (Arch Linux)

Read-only diagnosis on 2026-10-06:

- `uname -r` → `7.2.7-arch1-1`; `lsmod | grep nvidia` → only `nvidia_wmi_ec_backlight` (no
  `nvidia` module); `lspci -k` shows the AD107M with **no driver in use** (nouveau is
  blacklisted by `/usr/lib/modprobe.d/nvidia-utils.conf`, so nothing drives the card).
- `pacman -Q`: `linux 7.2.7.arch1-1` but **`linux-headers 7.1.5.arch1-2`**;
  `nvidia-open-dkms 610.43.03-5` but **`nvidia-utils 615.71.09-1`**; no
  `nvidia-container-toolkit`.
- `dkms status` → empty; `/var/lib/dkms/` holds only the MOK signing keys; no `nvidia.ko` under
  `/usr/lib/modules/7.2.7-arch1-1/`.
- `/var/log/pacman.log`: on 2026-09-28 `nvidia-utils` (→ 615.71.09) and `linux` (→ 7.2.7) were
  upgraded, but `linux-headers` and `nvidia-open-dkms` were not.

**Cause:** a partial upgrade. Without headers for 7.2.7, DKMS could not build the kernel
module for the new kernel, and the kernel module (610) no longer matches the userspace driver
(615), which would fail with "Driver/library version mismatch" even if it loaded.

**Fix** (needs root; run in a terminal, on mains power):

```bash
sudo pacman -Syu                                     # full upgrade: never upgrade a subset on Arch
sudo pacman -S --needed linux-headers nvidia-open-dkms nvidia-utils   # versions must now match
dkms status                                          # expect: nvidia/615.x, <kernel>, x86_64: installed
# if it is not built: sudo dkms autoinstall -k "$(uname -r)"   (after rebooting into the new kernel)
sudo reboot
nvidia-smi                                           # RTX 4060 Laptop GPU, 8188 MiB
# Docker GPU access for the CUDA llama.cpp image:
sudo pacman -S nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
docker run --rm --gpus all ghcr.io/ggml-org/llama.cpp:server-cuda --version
```

If Secure Boot is on, DKMS signs the module with `/var/lib/dkms/mok.pub`; enroll it once
(`sudo mokutil --import /var/lib/dkms/mok.pub`, reboot, confirm in the MOK manager). To avoid a
repeat: always `pacman -Syu` as a whole, and keep `linux-lts` + `linux-lts-headers` installed as
a bootable fallback.

**CPU speed, while at it:** the laptop was on battery in the `quiet` platform profile with the
`powersave` governor (cores at ~0.9 GHz under load), which is why the numbers above are low. For
benchmarks and training: plug in and select the performance profile
(`echo performance | sudo tee /sys/firmware/acpi/platform_profile`, or the ASUS/GNOME power menu).

## 7. CFO: cost per 1,000 copilot questions

Measured per question (eval runs, k=4 passages): **~2,300 prompt tokens + ~45 answer tokens**
(round to 2,400 + 50). A copilot question is prompt-heavy, so prompt-processing speed decides
cost and latency.

| Option | Assumptions | Cost per 1,000 questions | Latency per answer |
|---|---|---|---|
| (a) Self-hosted CPU VPS | A dedicated 8-vCPU / 16 GB VPS at ~$50/month (assumption: check Hetzner/OVH dedicated-vCPU prices), shared with the web app; ~60 s per question on 8 server cores (between our battery-throttled 95 s and an estimated ~30 s at full clock), one at a time → max ~43,000 questions/month | **$0 marginal**; $1.16 if the whole VPS were charged to a fully used LLM ($50 / 43k); at 5,000 questions/month the VPS share is $10/1,000 | 30–90 s: acceptable only as a background "brief me" job, not as chat |
| (b) Rented GPU, RunPod RTX 4090 at $0.34–0.74/h | llama.cpp CUDA, 4B Q4_K_M: ~5,000–10,000 tok/s prompt, ~150 tok/s generation (assumption from public llama.cpp numbers; not measured here) → ~0.6–0.8 s per question, ~4,500+/hour serially, more with `-np 4` | **$0.08–0.16** at full use (hourly price / 4,500); always-on pod $250–540/month → $25–54 per 1,000 at 10k questions/month, $2.5–5.4 at 100k | ~1 s |
| (c) Paid API | Same 2,400 in + 50 out tokens. Illustrative list prices (assumptions; check the provider's page): small model $0.10/M in, $0.40/M out; mid model $1/M in, $5/M out; frontier $3/M in, $15/M out | small **$0.26**, mid **$2.65**, frontier **$7.95** (= 2.4 x in-price + 0.05 x out-price) | 1–5 s |

Reading it: per question all three are cheap; the real difference is fixed vs variable cost and
latency. Start with (a) on the VPS we already pay for (no new spend, slow, fine for the free tier
and Bid-Brief-style batch questions), move chat to (b) — a GPU pod, or the founder's 4060 once its
driver is fixed — when paid usage passes a few thousand questions a month, and keep (c) only as
an emergency fallback, since every API token is a variable cost and sends customer tender data
to a third party. The fine-tuned 4B is what makes (a)/(b) good enough to skip (c).
