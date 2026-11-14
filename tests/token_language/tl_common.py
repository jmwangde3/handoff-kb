#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared helpers for the Chinese/English token benchmark.

Three variants are compared:

- **A** original Chinese v2.0.3 (frozen under `baseline/v2.0.3/`)
- **B** optimized Chinese v2.0.4 (`SKILL.zh-CN.md`, `references/*.zh-CN.md`, Chinese templates)
- **C** optimized English v2.0.4 (`SKILL.md`, `references/*.md`, `assets/en/`)

B and C are translations of one another: same sections, same protocol IDs, same
commands. A and B differ in structure (that is the structural saving); B and C
differ only in language (that is the language saving).

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
        "label": "Original Chinese v2.0.3",
        "skill": BASELINE / "SKILL.md",
        "ref": lambda name: BASELINE / "references" / ("%s.md" % name),
        "asset": lambda name: BASELINE / "assets" / name,
    },
    "B": {
        "label": "Optimized Chinese v2.0.4",
        "skill": ROOT / "SKILL.zh-CN.md",
        "ref": lambda name: ROOT / "references" / ("%s.zh-CN.md" % name),
        "asset": lambda name: ROOT / "assets" / name,
    },
    "C": {
        "label": "Optimized English v2.0.4",
        "skill": ROOT / "SKILL.md",
        "ref": lambda name: ROOT / "references" / ("%s.md" % name),
        "asset": lambda name: ROOT / "assets" / "en" / name,
    },
}

VARIANT_NAMES = ["A", "B", "C"]

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
    info = {
        "python": platform.python_version(),
        "python_impl": platform.python_implementation(),
        "platform": platform.platform(),
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
    info["deepseek_tokenizer_dir"] = tokenlib.deepseek_tokenizer_dir()
    info["deepseek_tokenizer_present"] = os.path.isfile(
        os.path.join(tokenlib.deepseek_tokenizer_dir(), "tokenizer.json"))
    return info


def make_counter(name: str, allow_fallback: bool = False):
    return tokenlib.TokenCounter(name, allow_fallback=allow_fallback)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")
