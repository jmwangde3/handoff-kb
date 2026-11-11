#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-migrate.py — v1 → v2 无损迁移（不改文件名、不重排编号）

只做三类**增量**改动：
  1. 在 00/05 顶部补 `<!-- kb:schema: 2 -->`
  2. 给已知章节补 `<!-- kb:id: ... -->`（已有则跳过）
  3. 不重命名 01–04 事实分册、不改任何正文、不删除证据

计划绑定源文件哈希：`--plan` 写 `.kb-migrate-plan.json`，`--apply` 先校验哈希，
文件被别的会话改过就拒绝（退出码 1），不覆盖任何内容。

用法：
  py kb-migrate.py --target ./old --plan
  py kb-migrate.py --target ./old --apply [--force]
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import markdown as md  # noqa: E402
from lib import protocol, scope  # noqa: E402
from lib.safeio import (Conflict, LockHeld, LockOwnershipError, SafeIOError,  # noqa: E402
                        Transaction, WorkspaceLock, atomic_write, read_text_strict,
                        sha256_file)

PLAN_FILE = ".kb-migrate-plan.json"

# 标题关键词 → 稳定章节 ID（按顺序匹配，命中即停）
DASHBOARD_IDS = [
    ("现状", "dashboard.current"),
    ("下一手", "dashboard.next"),
    ("各线", "dashboard.lines"),
    ("待办", "dashboard.todo"),
    ("交叉", "dashboard.cross"),
    ("接手顺序", "dashboard.order"),
    ("维护规则", "dashboard.rules"),
    ("硬约束", "dashboard.constraints"),
    ("最近", "dashboard.summary"),
]
BASELINE_IDS = [
    ("基线", "baseline.facts"),
    ("策略", "baseline.policy"),
    ("交叉", "baseline.chains"),
    ("维护", "baseline.rules"),
    ("资料", "baseline.paths"),
]


def detect(files):
    """返回当前协议状态描述。"""
    dash = files.get("dashboard", [None])[0]
    base = files.get("baseline", [None])[0]
    ids = 0
    schema = None
    for p in (dash, base):
        if not p:
            continue
        try:
            doc = md.parse_file(p)
        except Exception:
            continue
        ids += sum(1 for s in doc.sections if s.id)
        schema = schema or doc.schema
    facts = [protocol.number_of(p.name) for p in files.get("fact", [])]
    return {
        "schema": schema,
        "section_ids": ids,
        "fact_numbers": sorted(x for x in facts if x is not None),
        "legacy_fact_numbers": sorted(x for x in facts
                                      if x is not None and x in range(10)),
        "needs_schema": schema != protocol.SCHEMA_VERSION,
        "needs_ids": ids == 0,
    }


def plan_file(path: Path, wanted):
    """为单个文件生成插入计划：[(0基插入位置, 文本)]。"""
    doc = md.parse_file(path)
    ops = []
    if doc.schema != protocol.SCHEMA_VERSION:
        ops.append({"at": 0, "text": "<!-- kb:schema: %d -->" % protocol.SCHEMA_VERSION,
                    "type": "prepend"})
    for kw, sid in wanted:
        if md.find_by_id(doc, sid):
            continue
        for sec in doc.sections:
            # 只给 ## 章节打 ID：H1 是文档标题，不是事实章节
            if sec.level != 2:
                continue
            if kw in sec.title:
                # 插在标题上一行；若上一行已是 kb:id 注释就跳过
                prev = doc.lines[sec.line - 2].strip() if sec.line >= 2 else ""
                if prev.startswith("<!--") and "kb:id" in prev:
                    break
                ops.append({"at": sec.line - 1,
                            "text": "<!-- kb:id: %s -->" % sid,
                            "type": "insert_before_heading",
                            "heading": sec.title})
                break
    return ops


def build_plan(root: Path, files):
    entries = []
    for role, wanted in (("dashboard", DASHBOARD_IDS), ("baseline", BASELINE_IDS)):
        p = files.get(role, [None])[0]
        if not p:
            continue
        ops = plan_file(p, wanted)
        if not ops:
            continue
        text = read_text_strict(p)
        lines = text.splitlines()
        for op in sorted(ops, key=lambda o: (-o["at"],
                                             0 if o["type"] != "prepend" else 1)):
            lines.insert(op["at"], op["text"])
        new = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        entries.append({
            "path": p.relative_to(root).as_posix(),
            "sha256_before": sha256_file(p),
            "sha256_after": hashlib.sha256(new.encode("utf-8")).hexdigest(),
            "operations": ops,
        })
    return entries


def git_dirty(root: Path):
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return [x for x in r.stdout.splitlines() if x.strip()]


PLAN_SCHEMA = 2
ALLOWED_OPS = {"prepend", "insert_before_heading"}


def _apply_ops(text: str, operations) -> str:
    lines = text.splitlines()
    for op in sorted(operations, key=lambda o: (-o["at"],
                                                0 if o["type"] != "prepend" else 1)):
        lines.insert(op["at"], op["text"])
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def validate_plan(plan, root: Path):
    """严格校验计划：非法就抛 SafeIOError，绝不在可疑计划上写盘。"""
    if not isinstance(plan, dict):
        raise SafeIOError("计划文件顶层不是对象")
    if plan.get("schema_version") != PLAN_SCHEMA:
        raise SafeIOError("计划 schema_version=%r 不受支持（本版只认 %d）"
                          % (plan.get("schema_version"), PLAN_SCHEMA))
    if plan.get("root_id") != safeio_root_id(root):
        raise SafeIOError("计划不是为这个目录生成的（root_id 不符）："
                          "计划=%s 目录=%s" % (plan.get("root_id"), safeio_root_id(root)))
    entries = plan.get("entries")
    if not isinstance(entries, list):
        raise SafeIOError("计划 entries 不是数组")
    seen = set()
    for e in entries:
        if not isinstance(e, dict):
            raise SafeIOError("计划条目不是对象")
        rel = e.get("path")
        scope.check_rel_path(root, rel or "")
        if rel in seen:
            raise SafeIOError("计划里有重复路径：%s" % rel)
        seen.add(rel)
        for key in ("sha256_before", "sha256_after"):
            v = e.get(key) or ""
            if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
                raise SafeIOError("%s 的 %s 不是 64 位十六进制" % (rel, key))
        ops = e.get("operations")
        if not isinstance(ops, list) or not ops:
            raise SafeIOError("%s 没有操作" % rel)
        if len(ops) > 200:
            raise SafeIOError("%s 操作过多（%d），拒绝执行" % (rel, len(ops)))
        for op in ops:
            if not isinstance(op, dict):
                raise SafeIOError("%s 的操作不是对象" % rel)
            if op.get("type") not in ALLOWED_OPS:
                raise SafeIOError("%s 含不支持的操作：%r" % (rel, op.get("type")))
            at = op.get("at")
            if not isinstance(at, int) or isinstance(at, bool) or at < 0:
                raise SafeIOError("%s 的插入位置非法：%r" % (rel, at))
            text = op.get("text")
            if not isinstance(text, str) or not text.strip():
                raise SafeIOError("%s 的插入内容为空" % rel)
            if "\n" in text or "\r" in text:
                raise SafeIOError("%s 的插入内容含换行（只允许单行注释）" % rel)
    return entries


def safeio_root_id(root: Path) -> str:
    from lib.safeio import root_id as _rid
    return _rid(root)


def main() -> int:
    ap = argparse.ArgumentParser(description="v1 → v2 无损迁移")
    ap.add_argument("--target", default=".")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="有未提交改动时仍生成计划/执行（不绕过任何哈希与路径校验）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        root = scope.resolve_root(args.target)
    except scope.ScopeError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 2
    if not (args.plan or args.apply):
        print("用法：--plan 看变更，--apply 执行（计划需先存在）", file=sys.stderr)
        return 2

    files = scope.role_files(root, loose=True)
    state = detect(files)

    if args.apply:
        plan_path = root / PLAN_FILE
        if not plan_path.is_file():
            print("ERR: 没有迁移计划（先跑 --plan）", file=sys.stderr)
            return 1
        try:
            plan = json.loads(read_text_strict(plan_path))
        except Exception as exc:
            print("ERR: 计划文件无法解析：%s" % exc, file=sys.stderr)
            return 1
        try:
            entries = validate_plan(plan, root)
        except ScopeError as exc:
            print("ERR: 计划含非法路径：%s" % exc, file=sys.stderr)
            return 1
        except SafeIOError as exc:
            print("ERR: 计划不可信：%s" % exc, file=sys.stderr)
            return 1

        dirty = git_dirty(root)
        if dirty and not args.force:
            print("ERR: 有 %d 个未提交改动，默认拒绝迁移（--force 可继续）：%s"
                  % (len(dirty), ", ".join(x.strip()[:40] for x in dirty[:3])), file=sys.stderr)
            return 1

        # 锁内重算：所有冲突必须在写之前发现
        done = []
        try:
            with WorkspaceLock(root, timeout=float(os.environ.get("KB_LOCK_TIMEOUT", "5"))) as lock:
                if lock.reclaimed:
                    print("-- 回收死进程遗留的锁：pid=%s" % lock.reclaimed.get("pid"),
                          file=sys.stderr)
                stale, computed = [], []
                for e in entries:
                    p = root / e["path"]
                    if not p.is_file():
                        stale.append("%s（文件不存在）" % e["path"])
                        continue
                    cur = sha256_file(p)
                    if cur != e["sha256_before"]:
                        stale.append(e["path"])
                        continue
                    text = read_text_strict(p)
                    new = _apply_ops(text, e["operations"])
                    got = hashlib.sha256(new.encode("utf-8")).hexdigest()
                    if got != e["sha256_after"]:
                        stale.append("%s（重算哈希与计划不符）" % e["path"])
                        continue
                    computed.append((e, cur, new))
                if stale:
                    print("ERR: 计划已过期或内容不符，未写入任何文件：%s"
                          % ", ".join(stale), file=sys.stderr)
                    print("     重跑 --plan 生成新计划", file=sys.stderr)
                    return 1
                txn = Transaction(root)
                for e, cur, new in computed:
                    txn.stage(e["path"], cur, new, "migrate")
                try:
                    result = txn.commit()
                except Conflict as exc:
                    print("CONFLICT: %s" % exc, file=sys.stderr)
                    return 1
                except SafeIOError as exc:
                    print("ERR: 迁移事务失败：%s" % exc, file=sys.stderr)
                    print("     现场已保留，可跑 kb-write.py recover --inspect 查看",
                          file=sys.stderr)
                    return 1
        except LockHeld as exc:
            print("ERR: %s" % exc, file=sys.stderr)
            return 1
        except LockOwnershipError as exc:
            print("ERR: %s" % exc, file=sys.stderr)
            return 1

        plan_path.unlink()
        done = [{"path": r["path"], "sha256": r["sha_after"]} for r in result]
        payload = {"migrated": done, "schema": protocol.SCHEMA_VERSION}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json
              else "-- 迁移完成，%d 个文件：\n%s"
                   % (len(done), "\n".join("   ~ %s" % d["path"] for d in done)))
        return 0

    # --plan
    entries = build_plan(root, files)
    dirty = git_dirty(root)
    plan = {"schema_version": PLAN_SCHEMA, "kb_schema": protocol.SCHEMA_VERSION,
            "root_id": safeio_root_id(root), "target": str(root),
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "generated_by": "kb-migrate.py 2.0.1",
            "detected": state, "entries": entries,
            "operation_count": sum(len(e["operations"]) for e in entries),
            "git_dirty": dirty or []}
    atomic_write(root / PLAN_FILE,
                 json.dumps(plan, ensure_ascii=False, indent=2) + "\n")

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    print("== 迁移计划：%s" % root)
    print("检出：schema=%s，章节 ID %d 个，事实分册编号 %s"
          % (state["schema"] or "v1", state["section_ids"], state["fact_numbers"]))
    if not entries:
        print("-- 已是 v%d，无需迁移（幂等）" % protocol.SCHEMA_VERSION)
    for e in entries:
        print("~ %s（%d 处插入）" % (e["path"], len(e["operations"])))
        for op in e["operations"]:
            print("   + L%-4d %s" % (op["at"] + 1, op["text"]))
    if dirty:
        print("! 有 %d 个未提交改动；--apply 默认会拒绝（确认无并发会话后可 --force）" % len(dirty))
    print("\n计划已写入 %s（绑定 root_id + 源文件哈希；变了就重跑）" % PLAN_FILE)
    print("执行：py kb-migrate.py --target \"%s\" --apply" % root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
