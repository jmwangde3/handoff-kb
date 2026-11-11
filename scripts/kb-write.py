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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import facts, protocol, scope  # noqa: E402
from lib import markdown as md  # noqa: E402
from lib.scope import ScopeError  # noqa: E402
from lib.safeio import (read_text_strict,
                        LOCK_DIR, Conflict, EncodingError, LockHeld,  # noqa: E402
                        LockOwnershipError, SafeIOError, Transaction, WorkspaceLock,
                        break_lock, read_text, recover, sha256_file)

TXN_LABEL = ".kb-txn"


def _print_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_read(args) -> int:
    root = scope.resolve_root(args.target)
    path = scope.check_rel_path(root, args.file)
    if not path.is_file():
        print("文件不存在：%s" % args.file, file=sys.stderr)
        return 2
    try:
        text = read_text_strict(path)
    except EncodingError as exc:
        # 读也不能用替换字符糊过去：调用方会拿着「看起来正常」的文本去改，
        # 写回时就变成不可逆的乱码。宁可这里就报错。
        print("ENCODING: %s" % exc, file=sys.stderr)
        return 1
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
    """三种定义形式统一由 lib/facts.py 处理（标题 / 列表 / 表格）。"""
    try:
        return facts.update_fact_definition(
            text, (spec.get("fact_id") or "").strip(),
            spec.get("content") or "", spec.get("path") or "")
    except facts.FactError as exc:
        raise SafeIOError(str(exc))

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
        try:
            # stage 也会抛 Conflict（哈希不符）：必须走同一个分支，
            # 否则真正的并发冲突被报成普通 ERR，调用方分不清该合并还是该修参数。
            for p in prepared:
                txn.stage(p["path"], p["expected"], p["new"], p["op"])
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
        info = break_lock(root, plan=not args.force, force=args.force)
        if args.json:
            _print_json(info)
        else:
            print("== 锁：%s" % info.get("path", LOCK_DIR))
            if not info.get("exists"):
                print("   没有锁目录（%s）" % info.get("message", ""))
            else:
                meta = info.get("meta") or {}
                print("   owner_token : %s…" % str(meta.get("owner_token"))[:8])
                print("   pid         : %s（%s）"
                      % (meta.get("pid"), "存活" if info.get("alive") else "已退出/未知"))
                print("   host        : %s（%s）"
                      % (meta.get("host") or "-",
                         "本机" if info.get("same_host") else "非本机"))
                print("   session     : %s" % (meta.get("session") or "-"))
                if meta.get("created"):
                    print("   created     : %s" % time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(meta["created"])))
                if info.get("incomplete"):
                    print("   状态        : 不完整锁（%s）" % info.get("meta_error"))
                print("   -> %s" % info.get("message", ""))
        if args.force:
            return 0
        return 0

    mode = "apply" if args.apply else ("dry-run" if args.dry_run else "inspect")
    reports = recover(root, mode=mode)
    if args.json:
        _print_json({"mode": mode, "transactions": reports})
    else:
        if not reports:
            print("没有未完成的事务（%s/ 为空）" % TXN_LABEL)
        for r in reports:
            head = r.get("id") or os.path.basename(r["dir"])
            print("== txn %s  state=%s  action=%s" % (head, r.get("state"), r.get("action")))
            if r.get("error"):
                print("   !! %s" % r["error"])
            for e in r.get("entries", []):
                print("   %-40s %-16s before=%s now=%s"
                      % (e["path"], e["state"], (e.get("sha_before") or "")[:8],
                         (e.get("sha_now") or "")[:8]))
                if e.get("note"):
                    print("        %s" % e["note"])
            if r.get("message"):
                print("   %s" % r["message"])
        if mode == "apply":
            print("\n（apply 已持锁执行；证据不足的事务保留现场，见上面 action）")
    manual = [r for r in reports
              if r.get("requires_manual")
              or str(r.get("action", "")).startswith(("manual", "backup-corrupt"))]
    if manual and mode != "apply":
        print("\n!! %d 个事务需要人工处理（--apply 不会自动清理它们）" % len(manual),
              file=sys.stderr)
    return 1 if manual else 0


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

    c = sub.add_parser("recover", help="检查/恢复未完成事务（默认只读）")
    c.add_argument("--target", default=".")
    c.add_argument("--inspect", action="store_true", help="只读查看（默认）")
    c.add_argument("--dry-run", action="store_true", help="只读，给出将执行的动作")
    c.add_argument("--apply", action="store_true", help="持锁执行恢复")
    c.add_argument("--break-lock", action="store_true", help="查看/清理工作区锁")
    c.add_argument("--force", action="store_true", help="配合 --break-lock：确认强制清理")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_recover)

    args = ap.parse_args()
    try:
        return args.func(args)
    except ScopeError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 2
    except LockOwnershipError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 1
    except EncodingError as exc:
        print("ENCODING: %s" % exc, file=sys.stderr)
        return 1
    except SafeIOError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 1
    except md.MarkdownError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
