#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture the v2.0.3 baseline manifest used by the token benchmark.

The baseline copies under `baseline/v2.0.3/` are never edited after capture;
this script only (re)writes `MANIFEST.json` for them, and the test suite fails
if any baseline file no longer matches its recorded SHA256.

    py tests/token_language/capture_baseline.py
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tl_common as tl  # noqa: E402

from lib import tokens as tokenlib  # noqa: E402


def _describe(counter):
    """Counter metadata without local absolute paths.

    `as_dict()["actual"]` embeds the resolved tokenizer.json path, which would
    put a machine-specific absolute path into a committed artifact. Keep the
    encoder identity, drop the directory.
    """
    if counter is None:
        return None
    row = counter.as_dict()
    actual = row.get("actual") or ""
    if "(" in actual and actual.endswith(")"):
        head, _, tail = actual.partition("(")
        row["actual"] = "%s(%s)" % (head, Path(tail[:-1]).name)
    return row


def git(*args) -> str:
    try:
        out = subprocess.run(["git"] + list(args), cwd=str(tl.ROOT),
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace")
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def main() -> int:
    counters = {}
    for name in ("cl100k_base", "o200k_base", "deepseek_v4"):
        try:
            counters[name] = tokenlib.TokenCounter(name)
        except tokenlib.TokenizerError:
            counters[name] = None

    files = {}
    for path in sorted(tl.BASELINE.rglob("*")):
        if not path.is_file() or path.name == "MANIFEST.json":
            continue
        text = io.open(path, encoding="utf-8").read()
        row = {
            "bytes": len(path.read_bytes()),
            "chars": len(text),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "tokens": {},
        }
        for name, counter in counters.items():
            row["tokens"][name] = counter.count(text) if counter is not None else None
        files[path.relative_to(tl.BASELINE).as_posix()] = row

    payload = {
        "schema_version": 1,
        "variant": "A",
        "label": "Original Chinese v2.0.3",
        "source_tag": git("describe", "--tags", "420644e") or "v2.0.3",
        "source_commit": git("rev-parse", "420644e") or "",
        "captured_from": "git show 420644e:<path>",
        "note": "Baseline copies are immutable; the test suite verifies their SHA256.",
        "tokenizers": {name: _describe(c) for name, c in counters.items()},
        "files": files,
    }
    tl.write_json(tl.BASELINE / "MANIFEST.json", payload)
    print("wrote %s (%d files)" % (tl.BASELINE / "MANIFEST.json", len(files)))
    for name, counter in counters.items():
        print("  %-12s %s" % (name, "ok" if counter is not None else "unavailable"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
