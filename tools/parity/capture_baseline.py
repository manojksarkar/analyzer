"""Capture an L2 prompt-parity baseline (docs/production-redesign/07 §2).

WHY
---
LLM output is non-deterministic, so a refactor cannot be validated by comparing
generated text. Instead we prove the *input* never changed: capture every prompt
the pipeline sends today, re-capture after a change, and diff. Byte-identical
prompts + same model + same params => the AI's output quality cannot have moved.

HOW
---
* ``LLM_PROMPT_DUMP``    - every ``LlmClient`` call writes its prompt (content-addressed).
* ``LLM_FAKE_RESPONSES`` - deterministic stand-in replies, so this runs on a host
  with **no LLM gateway** and prompts that embed upstream output (e.g. the
  flowchart context's "Purpose:") stay representative instead of going blank.

The repo config ships with descriptions/behaviourNames/summarize **disabled**, so a
default run emits no prompts at all. We therefore write a resolved config with the
LLM features switched ON — pinned here rather than taken from anyone's local
config.local.json, so the baseline is reproducible on any machine.

Usage
-----
    python tools/parity/capture_baseline.py --out .parity/before
    # ...make changes...
    python tools/parity/capture_baseline.py --out .parity/after
    python tools/parity/compare.py .parity/before .parity/after
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE_PROJECT = os.path.join(PROJECT_ROOT, "SampleCppProject")
GROUP = "My Sample"          # must match tests/conftest.py's harness group


def _load_jsonc(path: str) -> dict:
    """Parse the analyzer's JSONC config (// and /* */ comments allowed)."""
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))
    from core.config import load_config           # noqa: E402  (needs sys.path first)
    return load_config(os.path.dirname(os.path.dirname(path)))


def build_capture_config(dest: str) -> str:
    """Write a resolved config with every LLM feature ON, pinned for reproducibility."""
    cfg = _load_jsonc(os.path.join(PROJECT_ROOT, "engine", "config", "config.json"))
    llm = cfg.setdefault("llm", {})
    # Turn the prompt-producing features on. Without these the run is silent.
    llm["descriptions"] = True
    llm["behaviourNames"] = True
    llm["summarize"] = True
    # Pin identity: these values are part of the prompt record, so they must not
    # drift between the "before" and "after" captures.
    llm["provider"] = "ollama"
    llm["defaultModel"] = "parity-baseline-model"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    return dest


def capture(out_dir: str, *, keep_output: bool = False) -> int:
    out_dir = os.path.abspath(out_dir)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)                     # a stale corpus would corrupt the diff
    os.makedirs(out_dir, exist_ok=True)

    cfg_path = build_capture_config(os.path.join(out_dir, "_capture-config.json"))
    env = {
        **os.environ,
        "LLM_PROMPT_DUMP": out_dir,
        "LLM_FAKE_RESPONSES": "1",
        "PYTHONIOENCODING": "utf-8",               # prompts contain non-ASCII source comments
    }
    cmd = [sys.executable, os.path.join(PROJECT_ROOT, "engine", "run.py"),
           SAMPLE_PROJECT, "--clean", "--selected-group", GROUP, "--config", cfg_path]
    print("running:", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env, shell=(os.name == "nt"))

    prompts = sorted(f for f in os.listdir(out_dir) if f.endswith(".json")
                     and not f.startswith("_capture-config"))
    calls_path = os.path.join(out_dir, "calls.jsonl")
    calls = sum(1 for _ in open(calls_path, encoding="utf-8")) if os.path.isfile(calls_path) else 0
    print(f"\nbaseline: {len(prompts)} distinct prompt(s), {calls} call(s) -> {out_dir}")
    if proc.returncode != 0:
        print(f"NOTE: pipeline exited {proc.returncode} — prompts are still valid as a "
              f"baseline provided the *same* failure occurs in the comparison run.")
    if not keep_output:
        pass                                        # model/ + output/ left in place for L3
    return 0 if prompts else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Capture an LLM prompt-parity baseline.")
    ap.add_argument("--out", required=True, help="directory to write the prompt corpus into")
    args = ap.parse_args()
    raise SystemExit(capture(args.out))


if __name__ == "__main__":
    main()
