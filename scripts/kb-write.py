#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-write.py — 安全写入（乐观并发控制 + 锁 + 事务 + 恢复）

读取拿全量 SHA-256，写回必须带 expected_sha256；不符即拒绝，绝不覆盖。
支持 replace_section / append / update_fact 三种受控操作，多文件先全部校验后写。

用法：
  py kb-write.py read    --target ./demo --file 05_进度仪表盘.md [--json]
  py kb-write.py apply   --target ./demo --changes changes.json [--dry-run]
  py kb-write.py recover --target ./demo [--dry-run | --apply] [--break-lock]

退出码：0 成功 / 1 冲突或校验失败 / 2 环境或用法错误
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import protocol, scope  # noqa: E402
from lib import markdown as md  # noqa: E402
from lib.scope import ScopeError  # noqa: E402
from lib.safeio import (Conflict, LockHeld, SafeIOError, Transaction,  # noqa: E402
                        WorkspaceLock, break_lock, read_text, recover, sha256_file)


def _print_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_read(args) -> int:
    root = scope.resolve_root(args.target)
    path = scope.check_rel_path(root, args.file)
    if not path.is_file():
        print("文件不存在：%s" % args.file, file=sys.stderr)
        return 2
    text = read_text(path)
    doc = md.parse(text, path)
    sha = sha256_file(path)
    if args.json:
        _print_json({
            "path": args.file, "sha256": sha, "sha256_text": doc.sha256_text,
            "short_hash": doc.short_hash, "lines": len(doc.lines),
            "schema": doc.schema,
            "sections": [{"n": s.n, "id": s.id, "level": s.level,
                          "line": s.line, "title": s.title} for s in doc.sections],
            "content": text,
        })
    else:
        print("== %s  sha256=%s  %d 行  %d 节" % (args.file, sha, len(doc.lines), len(doc.sections)))
        for s in doc.sections:
            print("  #%-3d L%-5d %s%s" % (s.n, s.line, "  " * (s.level - 1),
                                          s.title + ("  [%s]" % s.id if s.id else "")))
        print("\n-- 全文 --")
        print(text)
    return 0


def _apply_replace_section(text: str, spec: dict) -> str:
    sid = spec.get("section_id") or ""
    if not protocol.SECTION_ID_RE.match(sid):
        raise SafeIOError("section_id 非法：%r（允许 [A-Za-z0-9_.:-]）" % sid)
    doc = md.parse(text)
    sec = md.find_by_id(doc, sid)
    if sec is None:
        raise SafeIOError("找不到章节 ID：%s（先 kb-outline.py --file ... 看 id 清单）" % sid)
    content = spec.get("content") or ""
    lines = text.splitlines()
    body = content.splitlines()
    while body and not body[-1].strip():
        body.pop()
    replace_heading = bool(body) and body[0].lstrip().startswith("#")
    if replace_heading:
        head_idx, stop = sec.line - 1, sec.stop
    else:
        head_idx, stop = sec.line, sec.stop
    out = lines[:head_idx] + body + lines[stop:]
    if not replace_heading and body and stop < len(lines):
        out.insert(head_idx + len(body), "")
    new = "\n".join(out)
    if text.endswith("\n"):
        new += "\n"
    return new


def _apply_append(text: str, spec: dict) -> str:
    content = (spec.get("content") or "").strip("\n")
    if not content:
        raise SafeIOError("append 的 content 为空")
    base = text.rstrip("\n")
    return (base + "\n\n" + content + "\n") if base else (content + "\n")


def _apply_update_fact(text: str, spec: dict) -> str:
    fid = (spec.get("fact_id") or "").strip()
    if not protocol.FACT_ID_RE.fullmatch(fid):
        raise SafeIOError("fact_id 非法：%r（形如 K-01 / G-007）" % fid)
    content = (spec.get("content") or "").rstrip("\n")
    if not content:
        raise SafeIOError("update_fact 的 content 为空")
    lines = text.splitlines()
    hit = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*\|\s*%s\s*\|" % re.escape(fid), line):
            hit = i
            break
        if re.match(r"^\s*(?:[-*]\s*)?%s\s*[:：|\s]" % re.escape(fid), line):
            hit = i
            break
    if hit is None:
        raise SafeIOError("文件中找不到事实 ID %s（不做新增，请显式改基线表）" % fid)
    out = lines[:hit] + content.splitlines() + lines[hit + 1:]
    new = "\n".join(out)
    if text.endswith("\n"):
        new += "\n"
    return new


OPERATIONS = {
    "replace_section": _apply_replace_section,
    "append": _apply_append,
    "update_fact": _apply_update_fact,
}


def _load_changes(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SafeIOError("changes 文件无法解析：%s" % exc)
    if data.get("schema_version") != 1:
        raise SafeIOError("changes.schema_version 必须是 1（当前 %r）" % data.get("schema_version"))
    updates = data.get("updates")
    if not isinstance(updates, list) or not updates:
        raise SafeIOError("changes.updates 必须是非空数组")
    return data


def cmd_apply(args) -> int:
    root = scope.resolve_root(args.target)
    changes = _load_changes(Path(args.changes))
    prepared = []
    # 阶段 1：全部校验 + 计算新内容（不写盘）
    for i, spec in enumerate(changes["updates"], 1):
        rel = spec.get("path") or ""
        full = scope.check_rel_path(root, rel)
        if not full.is_file():
            raise SafeIOError("[%d] 文件不存在：%s" % (i, rel))
        op = spec.get("operation")
        if op not in OPERATIONS:
            raise SafeIOError("[%d] 不支持的操作：%r（可选 %s）"
                              % (i, op, " / ".join(OPERATIONS)))
        expected = (spec.get("expected_sha256") or "").strip()
        if len(expected) != 64:
            raise SafeIOError("[%d] expected_sha256 必须是完整 64 位（收到 %d 位）"
                              % (i, len(expected)))
        text = read_text(full)
        new_text = OPERATIONS[op](text, spec)
        prepared.append({"path": rel, "op": op, "expected": expected,
                         "old": text, "new": new_text})

    plan = [{"path": p["path"], "operation": p["op"],
             "sha_before": sha256_file(root / p["path"]),
             "sha_after_preview": hashlib.sha256(
                 p["new"].encode("utf-8")).hexdigest(),
             "bytes_before": len(p["old"].encode("utf-8")),
             "bytes_after": len(p["new"].encode("utf-8"))} for p in prepared]

    if args.dry_run:
        _print_json({"dry_run": True, "changes": plan})
        return 0

    with WorkspaceLock(root, timeout=float(os.environ.get("KB_LOCK_TIMEOUT", "5")),
                       session=args.session) as lock:
        if lock.reclaimed:
            print("-- 回收死进程遗留的锁：pid=%s" % lock.reclaimed.get("pid"), file=sys.stderr)
        txn = Transaction(root, session=args.session)
        for p in prepared:
            txn.stage(p["path"], p["expected"], p["new"], p["op"])
        try:
            result = txn.commit()
        except Conflict as exc:
            print("CONFLICT: %s" % exc, file=sys.stderr)
            return 1
        except SafeIOError as exc:
            print("ERR: %s" % exc, file=sys.stderr)
            return 1

    _print_json({"ok": True, "written": result,
                 "files": [{"path": r["path"], "sha256": r["sha_after"]} for r in result]})
    return 0


def cmd_recover(args) -> int:
    root = scope.resolve_root(args.target)
    if args.break_lock:
        done = break_lock(root)
        print("锁已清除" if done else "没有锁文件")
        if not args.apply and not args.dry_run:
            return 0
    reports = recover(root, apply=bool(args.apply and not args.dry_run))
    if args.json:
        _print_json({"transactions": reports})
    else:
        if not reports:
            print("没有未完成的事务（%s/ 为空）" % ".kb-txn")
        for r in reports:
            print("== txn %s  state=%s  action=%s" % (r["id"], r["state"], r["action"]))
            for e in r["entries"]:
                print("   %-40s %s" % (e["path"], e["state"]))
    return 1 if any(r["conflicts"] for r in reports) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="handoff-kb 安全写入（哈希校验 + 锁 + 事务）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("read", help="读文件并返回全量哈希与章节表")
    r.add_argument("--target", default=".")
    r.add_argument("--file", required=True)
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_read)

    a = sub.add_parser("apply", help="按 changes.json 写入")
    a.add_argument("--target", default=".")
    a.add_argument("--changes", required=True)
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--session", default="")
    a.set_defaults(func=cmd_apply)

    c = sub.add_parser("recover", help="检查/恢复未完成事务")
    c.add_argument("--target", default=".")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--apply", action="store_true")
    c.add_argument("--break-lock", action="store_true")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_recover)

    args = ap.parse_args()
    try:
        return args.func(args)
    except ScopeError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 2
    except SafeIOError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 1
    except md.MarkdownError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
