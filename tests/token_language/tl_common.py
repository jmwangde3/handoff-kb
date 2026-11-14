#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared helpers for the A/B/C token benchmark.

Three variants are compared:

- **A** original Chinese v2.0.3 (frozen under `baseline/v2.0.3/`)
- **B** optimized Chinese v2.0.4 — **a benchmark sample, not a shipped skill**.
  It lives in `sample_b/` precisely so it cannot be installed or discovered as a
  second skill; 2.0.4 ships one skill (`SKILL.md`, English) only.
- **C** the shipped English v2.0.4 skill (`SKILL.md`, `references/*.md`, `assets/en/`)

B is kept because it isolates the *structural* saving (A → B) from the
*language* saving (B → C). Without a Chinese edition of the optimized text the
language term could not be measured at all, and every A → C number would be the
sum of two effects that move in opposite directions. B's bytes are frozen: its
SHA256 is asserted in `test_token_language.py`, so "move the file" can never
silently become "edit the file".

Token counting goes through `scripts/lib/tokens.py::TokenCounter` — this module
never implements a tokenizer of its own.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import sys
from pathlib import Path

TL_DIR = Path(__file__).resolve().parent
ROOT = TL_DIR.parents[1]
SCRIPTS = ROOT / "scripts"
BASELINE = TL_DIR / "baseline" / "v2.0.3"
FIXTURES = TL_DIR / "fixtures" / "paired"
# B lives outside the repo root: one discoverable skill only.
SAMPLE_B = TL_DIR / "sample_b" / "SKILL.zh-CN.md"
# SHA256 of B when it was frozen as a benchmark sample. If this changes, the
# A → B half of every published number changes with it — which is why it is a
# hard assertion rather than a note.
SAMPLE_B_SHA256 = "fb4cad979ce4713bf1517d368509ce6e4675408dcac6261d984e308c119b8c5a"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib import tokens as tokenlib  # noqa: E402

REF_NAMES = ["protocol-v2", "migration", "hooks", "benchmark"]
ASSET_NAMES = [
    "AGENTS.md", "00_baseline.md", "05_dashboard.md", "fact_book.md",
    "06_index.md", "06_log.md", "06_shard.md", "90_archive.md",
    "启动消息.txt", "gitignore.txt", "gitattributes.txt", "migration-prompt.txt",
]

VARIANTS = {
    "A": {
        "label": "Original Chinese v2.0.3 (frozen baseline)",
        "skill": BASELINE / "SKILL.md",
        "ref": lambda name: BASELINE / "references" / ("%s.md" % name),
        "asset": lambda name: BASELINE / "assets" / name,
        "shipped": False,
    },
    "B": {
        "label": "Optimized Chinese v2.0.4 (benchmark sample, not a shipped skill)",
        "skill": SAMPLE_B,
        "ref": lambda name: ROOT / "references" / ("%s.zh-CN.md" % name),
        "asset": lambda name: ROOT / "assets" / name,
        "shipped": False,
    },
    "C": {
        "label": "Optimized English v2.0.4 (the shipped skill)",
        "skill": ROOT / "SKILL.md",
        "ref": lambda name: ROOT / "references" / ("%s.md" % name),
        "asset": lambda name: ROOT / "assets" / "en" / name,
        "shipped": True,
    },
}

VARIANT_NAMES = ["A", "B", "C"]

# The 15% target is defined on these two. DeepSeek's vocabulary is Chinese-heavy,
# so its acceptance criterion is "must not grow" instead — see TokenTargets.
SPEC_TOKENIZERS = ("cl100k_base", "o200k_base")
# Every exact vocabulary the baseline is reproduced against when available.
BASELINE_TOKENIZERS = ("cl100k_base", "o200k_base", "deepseek_v4")

# Six tasks from the specification; the list of documents is what the task
# actually needs to read (never "every reference by default").
TASKS = [
    ("new-project", "New project initialization", ["skill"]),
    ("diagnose", "Existing project diagnosis", ["skill"]),
    ("migrate", "Legacy project migration", ["skill", "ref:migration"]),
    ("recovery", "New-session context recovery", ["skill", "ref:protocol-v2"]),
    ("safe-write", "Safe document write", ["skill", "ref:protocol-v2"]),
    ("hook-install", "Hook installation", ["skill", "ref:hooks"]),
]

TOKENIZERS = ["cl100k_base", "o200k_base", "deepseek_v4", "deepseek_estimate", "heuristic"]
EXACT_TOKENIZERS = {"cl100k_base", "o200k_base", "deepseek_v4"}


def doc_path(variant: str, key: str) -> Path:
    """Resolve a document key such as `skill`, `ref:hooks`, `asset:AGENTS.md`."""
    spec = VARIANTS[variant]
    if key == "skill":
        return spec["skill"]
    if key.startswith("ref:"):
        return spec["ref"](key.split(":", 1)[1])
    if key.startswith("asset:"):
        return spec["asset"](key.split(":", 1)[1])
    raise KeyError(key)


def read_text(path: Path) -> str:
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def frontmatter_description(text: str) -> str:
    """Return the YAML `description` value, without regex (keeps byte behaviour obvious)."""
    if not text.startswith("---"):
        return ""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return ""
    for line in parts[1].splitlines():
        if line.startswith("description:"):
            return line[len("description:"):].strip()
    return ""


def stats(path: Path, counter) -> dict:
    text = read_text(path)
    data = path.read_bytes()
    return {
        "path": path.relative_to(ROOT).as_posix() if str(path).startswith(str(ROOT))
                else path.name,
        "bytes": len(data),
        "chars": len(text),
        "tokens": counter.count(text),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def description_stats(variant: str, counter) -> dict:
    text = read_text(doc_path(variant, "skill"))
    desc = frontmatter_description(text)
    return {"tokens": counter.count(desc), "chars": len(desc),
            "sha256": hashlib.sha256(desc.encode("utf-8")).hexdigest()}


def task_stats(variant: str, keys, counter) -> dict:
    total = 0
    per_file = []
    for key in keys:
        st = stats(doc_path(variant, key), counter)
        per_file.append({"key": key, **st})
        total += st["tokens"]
    return {"tokens": total, "files": per_file}


def saving(base: float, cand: float):
    """1 - cand/base, with an explicit representation when the denominator is zero."""
    if base == 0:
        return None
    return round(1.0 - (cand / base), 6)


def env_info() -> dict:
    """Environment block for the report. Never contains a personal absolute path."""
    info = {
        "python": platform.python_version(),
        "python_impl": platform.python_implementation(),
        "platform": platform.system(),
        "machine": platform.machine(),
    }
    try:
        import tiktoken  # optional
        info["tiktoken"] = getattr(tiktoken, "__version__", "unknown")
    except Exception:
        info["tiktoken"] = None
    try:
        import tokenizers  # optional
        info["tokenizers"] = getattr(tokenizers, "__version__", "unknown")
    except Exception:
        info["tokenizers"] = None
    path = os.path.join(tokenlib.deepseek_tokenizer_dir(),
                        tokenlib.DEEPSEEK_TOKENIZER_FILE)
    info["deepseek_tokenizer_present"] = os.path.isfile(path)
    info["deepseek_tokenizer_file"] = tokenlib.DEEPSEEK_TOKENIZER_FILE \
        if os.path.isfile(path) else None
    info["deepseek_tokenizer_sha256"] = (
        tokenlib._sha256_file(path) if os.path.isfile(path) else None)
    return info


def make_counter(name: str, allow_fallback: bool = False):
    return tokenlib.TokenCounter(name, allow_fallback=allow_fallback)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")
