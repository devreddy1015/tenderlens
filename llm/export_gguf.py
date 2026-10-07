"""LoRA adapter -> merged HF model -> GGUF (bf16) -> Q4_K_M -> Ollama Modelfile.

    uv run python export_gguf.py --adapter out/qlora/qwen3.5-4b-tender/adapter
    # then serve it: LLM_GGUF=qwen3.5-4b-tender-Q4_K_M.gguf LLM_ALIAS=tenderlens-qwen3.5-4b-ft
    # and compare:   uv run python eval_llm.py --endpoint base=... --endpoint ft=...

Steps and why:
  1. merge     the base in bf16 on CPU (~9 GB RAM for a 4B model; QLoRA trained against
               the NF4 base, merging into bf16 is the standard, near-lossless route) and
               merge_and_unload(); the processor/tokenizer files are copied so the chat
               template travels with the model;
  2. convert   llama.cpp's convert_hf_to_gguf.py (cloned into out/llama.cpp at a pinned
               depth-1 checkout when --llama-cpp is not given) to a bf16 GGUF;
  3. quantize  `llama quantize ... Q4_K_M` from the same llama.cpp server image we serve with
               (docker), or a local llama-quantize via --quantize-bin;
  4. Modelfile for Ollama next to the GGUF (same template as deploy/llm/Modelfile).
The GGUF lands in llm/models/, which the llm container mounts read-only.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMAGE = "ghcr.io/ggml-org/llama.cpp:server"
LLAMA_CPP_REPO = "https://github.com/ggml-org/llama.cpp"

MODELFILE = '''# Ollama recipe written by llm/export_gguf.py; see deploy/llm/Modelfile for the notes.
#     ollama create {alias} -f {modelfile}
FROM ./{gguf}

TEMPLATE """{{{{- if .System }}}}<|im_start|>system
{{{{ .System }}}}<|im_end|>
{{{{ end }}}}
{{{{- range $i, $_ := .Messages }}}}
{{{{- if eq .Role "user" }}}}<|im_start|>user
{{{{ .Content }}}}<|im_end|>
{{{{ else if eq .Role "assistant" }}}}<|im_start|>assistant
{{{{ .Content }}}}<|im_end|>
{{{{ end }}}}
{{{{- end }}}}<|im_start|>assistant
<think>

</think>

"""

PARAMETER stop "<|im_end|>"
PARAMETER stop "<|endoftext|>"
PARAMETER temperature 0
PARAMETER top_p 1
PARAMETER num_ctx 8192
PARAMETER num_predict 300
'''


def run(cmd: list[str], **kw) -> None:
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def merge(adapter: Path, base: str | None, out: Path) -> str:
    import torch
    import transformers as tf
    from peft import PeftModel

    cfg = json.loads((adapter / "adapter_config.json").read_text())
    base = base or cfg["base_model_name_or_path"]
    model = None
    for cls in (tf.AutoModelForCausalLM, tf.AutoModelForImageTextToText):
        try:
            model = cls.from_pretrained(base, dtype=torch.bfloat16, low_cpu_mem_usage=True)
            break
        except (ValueError, KeyError):
            continue
    if model is None:
        raise SystemExit(f"cannot load {base}")
    model = PeftModel.from_pretrained(model, adapter).merge_and_unload()
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out, safe_serialization=True, max_shard_size="2GB")
    tf.AutoTokenizer.from_pretrained(adapter).save_pretrained(out)
    try:  # VLM checkpoints (Qwen3.5) also need the processor configs for the converter
        tf.AutoProcessor.from_pretrained(base).save_pretrained(out)
    except Exception as e:  # noqa: BLE001 - text-only bases have no processor
        print(f"(no processor copied: {e})")
    print(f"merged -> {out}")
    return base


def llama_cpp_checkout(path: Path | None) -> Path:
    if path:
        return path
    dest = HERE / "out" / "llama.cpp"
    if not (dest / "convert_hf_to_gguf.py").exists():
        run(["git", "clone", "--depth", "1", LLAMA_CPP_REPO, str(dest)])
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--adapter", type=Path, required=True)
    ap.add_argument("--base", help="HF id or path (default: from adapter_config.json)")
    ap.add_argument("--name", help="output stem (default: adapter's parent folder name)")
    ap.add_argument("--quant", default="Q4_K_M")
    ap.add_argument("--models-dir", type=Path, default=HERE / "models")
    ap.add_argument("--llama-cpp", type=Path, help="llama.cpp checkout (for convert_hf_to_gguf.py)")
    ap.add_argument("--quantize-bin", help="local llama-quantize; default: docker " + IMAGE)
    ap.add_argument("--skip-merge", action="store_true", help="reuse out/merged/<name>")
    a = ap.parse_args()

    adapter = a.adapter.resolve()
    name = a.name or adapter.parent.name
    merged = HERE / "out" / "merged" / name
    if not a.skip_merge:
        merge(adapter, a.base, merged)

    lcpp = llama_cpp_checkout(a.llama_cpp)
    a.models_dir.mkdir(parents=True, exist_ok=True)
    work = HERE / "out" / "gguf"
    work.mkdir(parents=True, exist_ok=True)
    f16 = work / f"{name}-bf16.gguf"
    env_path = str(lcpp / "gguf-py")
    run(
        [
            sys.executable,
            str(lcpp / "convert_hf_to_gguf.py"),
            str(merged),
            "--outtype",
            "bf16",
            "--outfile",
            str(f16),
        ],
        env={**os.environ, "PYTHONPATH": env_path},
    )

    gguf = f"{name}-{a.quant}.gguf"
    if a.quantize_bin:
        run([a.quantize_bin, str(f16), str(a.models_dir / gguf), a.quant])
    else:
        run(
            [
                "docker",
                "run",
                "--rm",
                "-u",
                f"{os.getuid()}:{os.getgid()}",
                "-v",
                f"{work}:/in:ro",
                "-v",
                f"{a.models_dir.resolve()}:/out",
                "--entrypoint",
                "/app/llama",
                IMAGE,
                "quantize",
                f"/in/{f16.name}",
                f"/out/{gguf}",
                a.quant,
            ]
        )
    modelfile = a.models_dir / f"{name}.Modelfile"
    alias = f"tenderlens-{name}"
    modelfile.write_text(MODELFILE.format(alias=alias, modelfile=modelfile.name, gguf=gguf))
    size = (a.models_dir / gguf).stat().st_size / 1024**3
    print(f"\n{a.models_dir / gguf} ({size:.2f} GB)\n{modelfile}")
    print(f"serve: LLM_GGUF={gguf} LLM_ALIAS={alias} (deploy/llm/compose.llm.yml)")
    print("free disk: rm -r", merged, f16)


if __name__ == "__main__":
    main()
