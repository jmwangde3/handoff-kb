#!/usr/bin/env python3
"""Small, explicit handoff writer; input remains on disk for retry and review."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import markdown, scope
from lib.safeio import (
    Conflict,
    SafeIOError,
    Transaction,
    WorkspaceLock,
    assert_transaction_slot_clean,
    decode_strict,
)

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,100}$")


def run(args):
    # The caller can decide L0 without reading input, project, or creating a lock.
    if args.level == "L0":
        return {"level": "L0", "status": "skipped", "files": []}
    if not args.input:
        raise ValueError("--input is required except for L0")
    record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError("input must be an object")
    raw_updates = record.get("updates")
    updates = [] if raw_updates is None else raw_updates
    event = record.get("event")
    if not isinstance(updates, list):
        raise ValueError("updates must be an array")
    if args.level == "auto" and not updates and event is None:
        return {"level": "L0", "status": "skipped", "files": []}
    level = "L1" if args.level == "auto" else args.level
    if not updates and event is None:
        return {"level": level, "status": "skipped", "files": []}
    root = scope.resolve_root(args.target)
    paths = {}
    for item in updates:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k] for k in ("path", "section_id", "before", "after")):
            raise ValueError("each update requires path, section_id, before and after strings")
        paths.setdefault(item["path"], []).append(item)
    if event is not None:
        if not isinstance(event, dict) or not all(isinstance(event.get(k), str) and event[k] for k in ("id", "path", "content")) or not ID.fullmatch(event["id"]):
            raise ValueError("event requires path, content and a safe stable id")
        if "\n" in event["content"] or "\r" in event["content"]:
            raise ValueError("event content must be one line")
        paths.setdefault(event["path"], [])
    with WorkspaceLock(root, timeout=float(os.environ.get("KB_LOCK_TIMEOUT", "5")), session="kb-finish"):
        assert_transaction_slot_clean(root)
        prepared = []
        for rel, edits in paths.items():
            path = scope.check_rel_path(root, rel)
            if not path.is_file():
                raise ValueError("file does not exist: " + rel)
            raw = path.read_bytes()
            text, newline, _ = decode_strict(raw)
            original = text
            for edit in edits:
                doc = markdown.parse(text)
                matches = [s for s in doc.sections if s.id == edit["section_id"]]
                if len(matches) != 1:
                    raise ValueError("section missing or ambiguous: " + edit["section_id"])
                sec = matches[0]
                lines = text.splitlines(keepends=True)
                body = "".join(lines[sec.start:sec.stop])
                before, after = edit["before"], edit["after"]
                if before == after:
                    if before not in body:
                        raise Conflict("expected text missing in " + rel + ":" + edit["section_id"])
                    continue
                if before in after or after in before:
                    raise ValueError("before and after must not contain one another")
                before_count = body.count(before)
                after_count = body.count(after)
                if before_count == 0 and after_count == 1:
                    # Repeated application is safe only if the exact replacement is present.
                    continue
                if before_count != 1 or after_count != 0:
                    raise Conflict("expected text missing, duplicated or replacement already exists in " + rel + ":" + edit["section_id"])
                body = body.replace(before, after, 1)
                text = "".join(lines[:sec.start]) + body + "".join(lines[sec.stop:])
            if event is not None and rel == event["path"]:
                marker = "<!-- kb:event:" + event["id"] + " -->"
                entry = marker + " " + event["content"]
                existing = [line for line in text.splitlines() if marker in line]
                if existing and existing != [entry]:
                    raise Conflict("event id already exists with different content: " + event["id"])
                if not existing:
                    if text.strip():
                        text = text.rstrip("\r\n") + newline + newline + entry + newline
                    else:
                        text = entry + newline
            if text != original:
                prepared.append((rel, hashlib.sha256(raw).hexdigest(), text))
        if not prepared:
            return {"level": level, "status": "unchanged", "files": [], "details": []}
        txn = Transaction(root, session="kb-finish")
        for rel, expected, text in prepared:
            txn.stage(rel, expected, text, "replace")
        details = [
            {"path": e["path"], "sha_before": e["sha_before"], "sha_after": e["sha_after"]}
            for e in txn.entries
        ]
        if getattr(args, "dry_run", False):
            return {
                "level": level,
                "status": "dry-run",
                "files": [item["path"] for item in details],
                "details": details,
            }
        result = txn.commit()
    return {
        "level": level,
        "status": "written",
        "files": [item["path"] for item in result],
        "details": [
            {"path": item["path"], "sha_before": item["sha_before"], "sha_after": item["sha_after"]}
            for item in result
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=".")
    parser.add_argument("--level", choices=["auto", "L0", "L1", "L2"], default="auto")
    parser.add_argument("--input", help="persistent UTF-8 JSON input; retained on failure")
    parser.add_argument("--dry-run", action="store_true", help="validate and preview updates without writing")
    args = parser.parse_args()
    try:
        output = run(args)
        code = 0
    except Exception as exc:
        output = {"level": args.level, "status": "failed", "files": [],
                  "error": type(exc).__name__ + ": " + str(exc), "pending_input": args.input}
        code = 1
    print(json.dumps(output, ensure_ascii=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
