"""QLoRA fine-tuning of the copilot model on out/dataset (build_dataset.py), sized for an 8 GB
RTX 4060.

    uv sync --extra train
    uv run python train_qlora.py                              # Qwen/Qwen3.5-4B, ~6 GB VRAM
    uv run python train_qlora.py --base Qwen/Qwen3-4B-Instruct-2507 --name qwen3-4b
    uv run python train_qlora.py --smoke                      # CPU, tiny model, 8 steps

Recipe: base weights in 4-bit NF4 (double quantisation, bf16 compute), LoRA r=16 / alpha=32 /
dropout 0.05 on every linear layer of the language model (attention, Gated DeltaNet
projections, MLP; never the vision tower), sequence 2048, gradient checkpointing, batch 1 x
gradient accumulation 16, lr 2e-4 cosine with 3% warm-up, 2 epochs, paged 8-bit AdamW.

Loss is on the answer tokens only, and logits are computed only at those positions
(`logits_to_keep`): Qwen3.5's vocabulary is 248k, so full-sequence logits at 2048 tokens
would cost ~4 GB of VRAM (fp32 logits + their gradient) for nothing.

The prompt is rendered with the model's own chat template and enable_thinking=False, exactly
what llama.cpp sends at inference (`--jinja --chat-template-kwargs '{"enable_thinking":false}'`).
Output: out/qlora/<name>/adapter (LoRA weights), metrics.json; then export_gguf.py.
"""

import argparse
import json
import math
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SMOKE_MODEL = "trl-internal-testing/tiny-Qwen3ForCausalLM"
SKIP_MODULES = ("visual", "vision", "mtp", "lm_head", "embed")


def load_rows(path: Path) -> list[list[dict]]:
    return [json.loads(line)["messages"] for line in path.read_text().splitlines() if line.strip()]


def encode(tok, messages: list[dict], seq: int) -> dict | None:
    """input_ids + labels (-100 on the prompt); None when the example does not fit `seq`."""
    prompt = tok.apply_chat_template(
        messages[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False
    )
    end = tok.eos_token or "<|im_end|>"
    answer = messages[-1]["content"] + end
    p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    a_ids = tok(answer, add_special_tokens=False)["input_ids"]
    if len(p_ids) + len(a_ids) > seq:
        return None
    return {"input_ids": p_ids + a_ids, "labels": [-100] * len(p_ids) + a_ids}


def load_model(base: str, smoke: bool):
    import torch
    import transformers as tf

    kwargs: dict = {"dtype": torch.float32 if smoke else torch.bfloat16}
    if not smoke:
        kwargs["quantization_config"] = tf.BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
        kwargs["device_map"] = {"": 0}
    # Qwen3.5 checkpoints are image-text-to-text; text-only fine-tuning still works through
    # the conditional-generation class (the vision tower is simply never used).
    for cls in (tf.AutoModelForCausalLM, tf.AutoModelForImageTextToText):
        try:
            return cls.from_pretrained(base, **kwargs)
        except (ValueError, KeyError) as e:
            last = e
    raise SystemExit(f"cannot load {base}: {last}")


def lora_targets(model) -> list[str]:
    """Leaf names of every linear layer outside the vision tower / MTP head / lm_head."""
    names = set()
    for name, mod in model.named_modules():
        if any(s in name for s in SKIP_MODULES):
            continue
        if type(mod).__name__ in ("Linear", "Linear4bit", "Linear8bitLt"):
            names.add(name.rsplit(".", 1)[-1])
    return sorted(names)


def vram() -> str:
    import torch

    if not torch.cuda.is_available():
        return "cpu"
    gb = 1024**3
    return (
        f"VRAM allocated {torch.cuda.memory_allocated() / gb:.2f} GB, "
        f"peak {torch.cuda.max_memory_allocated() / gb:.2f} GB, "
        f"reserved {torch.cuda.memory_reserved() / gb:.2f} GB / "
        f"{torch.cuda.get_device_properties(0).total_memory / gb:.1f} GB"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="Qwen/Qwen3.5-4B")
    ap.add_argument("--data", type=Path, default=HERE / "out" / "dataset")
    ap.add_argument("--name", default="qwen3.5-4b-tender")
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--seq", type=int, default=2048)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--accum", type=int, default=16)
    ap.add_argument("--smoke", action="store_true", help="CPU, tiny model, 8 steps, no 4-bit")
    a = ap.parse_args()

    import torch
    import transformers as tf
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    if a.smoke:
        a.base, a.name, a.seq, a.accum = SMOKE_MODEL, "smoke", 2048, 2
    elif not torch.cuda.is_available():
        raise SystemExit("no CUDA GPU visible; see README 'GPU', or use --smoke for a CPU check")
    out = HERE / "out" / "qlora" / a.name
    out.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(7)

    tok = tf.AutoTokenizer.from_pretrained(a.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    data: dict[str, list[dict]] = {}
    for split in ("train", "val"):
        rows = load_rows(a.data / f"{split}.jsonl")
        enc = [e for e in (encode(tok, m, a.seq) for m in rows) if e]
        print(f"{split}: {len(enc)}/{len(rows)} examples fit {a.seq} tokens", flush=True)
        data[split] = enc[:32] if a.smoke else enc
    lens = [len(e["input_ids"]) for e in data["train"]]
    print(f"train tokens: mean {sum(lens) / len(lens):.0f}, max {max(lens)}, total {sum(lens)}")

    model = load_model(a.base, a.smoke)
    if not a.smoke:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
        print(f"base loaded in 4-bit: {vram()}", flush=True)
    targets = lora_targets(model)
    print(f"LoRA targets: {targets}")
    model = get_peft_model(
        model,
        LoraConfig(
            r=a.r,
            lora_alpha=a.alpha,
            lora_dropout=0.05,
            target_modules=targets,
            exclude_modules=r".*(visual|vision|mtp).*",
            task_type="CAUSAL_LM",
        ),
    )
    model.print_trainable_parameters()

    def collate(batch: list[dict]) -> dict:
        n = max(len(b["input_ids"]) for b in batch)
        pad = tok.pad_token_id
        return {
            "input_ids": torch.tensor(
                [b["input_ids"] + [pad] * (n - len(b["input_ids"])) for b in batch]
            ),
            "attention_mask": torch.tensor(
                [[1] * len(b["input_ids"]) + [0] * (n - len(b["input_ids"])) for b in batch]
            ),
            "labels": torch.tensor([b["labels"] + [-100] * (n - len(b["labels"])) for b in batch]),
        }

    class AnswerOnlyTrainer(tf.Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            labels = inputs.pop("labels")
            # position p predicts token p+1: keep only positions whose next token is a target
            keep = (labels[:, 1:] != -100).any(dim=0).nonzero().squeeze(-1)
            outputs = model(**inputs, logits_to_keep=keep, use_cache=False)
            logits = outputs.logits.float()
            target = labels[:, keep + 1]
            loss = torch.nn.functional.cross_entropy(
                logits.reshape(-1, logits.size(-1)),
                target.reshape(-1),
                ignore_index=-100,
                reduction="sum",
            )
            n = num_items_in_batch if num_items_in_batch is not None else (target != -100).sum()
            loss = loss / n
            return (loss, outputs) if return_outputs else loss

    class VramLog(tf.TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kw):
            print(f"step {state.global_step}/{state.max_steps} {logs} | {vram()}", flush=True)

    steps_per_epoch = math.ceil(len(data["train"]) / (a.batch * a.accum))
    targs = tf.TrainingArguments(
        output_dir=str(out / "checkpoints"),
        num_train_epochs=a.epochs,
        max_steps=8 if a.smoke else -1,
        per_device_train_batch_size=a.batch,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=a.accum,
        learning_rate=a.lr,
        lr_scheduler_type="cosine",
        warmup_steps=max(1, round(0.03 * steps_per_epoch * a.epochs)),  # 3%; int for v4 and v5
        weight_decay=0.0,
        optim="adamw_torch" if a.smoke else "paged_adamw_8bit",
        bf16=not a.smoke,
        gradient_checkpointing=not a.smoke,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        logging_steps=1 if a.smoke else 5,
        eval_strategy="steps",
        eval_steps=4 if a.smoke else max(10, steps_per_epoch // 2),
        save_strategy="steps",
        save_steps=8 if a.smoke else max(10, steps_per_epoch // 2),
        save_total_limit=2,
        report_to=[],
        remove_unused_columns=False,
        dataloader_num_workers=0,
        use_cpu=a.smoke,
        seed=7,
    )
    trainer = AnswerOnlyTrainer(
        model=model,
        args=targs,
        train_dataset=data["train"],
        eval_dataset=data["val"][:8] if a.smoke else data["val"],
        data_collator=collate,
        callbacks=[VramLog()],
    )
    t0 = time.time()
    result = trainer.train()
    ev = trainer.evaluate()
    model.save_pretrained(out / "adapter")
    tok.save_pretrained(out / "adapter")
    metrics = {
        "base": a.base,
        "train_examples": len(data["train"]),
        "val_examples": len(data["val"]),
        "train_loss": result.training_loss,
        "eval_loss": ev.get("eval_loss"),
        "minutes": round((time.time() - t0) / 60, 1),
        "vram": vram(),
        "args": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(a).items()},
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1))
    print(json.dumps(metrics, indent=1))
    print(f"adapter: {out / 'adapter'}  next: python export_gguf.py --adapter {out / 'adapter'}")


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    main()
