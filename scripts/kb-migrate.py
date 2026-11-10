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
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import markdown as md  # noqa: E402
from lib import protocol, scope  # noqa: E402
from lib.safeio import atomic_write, read_text, sha256_file  # noqa: E402

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
        text = read_text(p)
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


def main() -> int:
    ap = argparse.ArgumentParser(description="v1 → v2 无损迁移")
    ap.add_argument("--target", default=".")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true", help="有未提交改动时仍生成计划/执行")
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
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        stale = [e["path"] for e in plan["entries"]
                 if not (root / e["path"]).is_file()
                 or sha256_file(root / e["path"]) != e["sha256_before"]]
        if stale:
            print("ERR: 计划已过期，这些文件被改过：%s" % ", ".join(stale), file=sys.stderr)
            print("     重跑 --plan 生成新计划（不覆盖任何内容）", file=sys.stderr)
            return 1
        dirty = git_dirty(root)
        if dirty and not args.force:
            print("ERR: 有 %d 个未提交改动，默认拒绝迁移（--force 可继续）：%s"
                  % (len(dirty), ", ".join(x.strip()[:40] for x in dirty[:3])), file=sys.stderr)
            return 1
        done = []
        for e in plan["entries"]:
            p = root / e["path"]
            text = read_text(p)
            lines = text.splitlines()
            for op in sorted(e["operations"], key=lambda o: (-o["at"],
                                                            0 if o["type"] != "prepend" else 1)):
                lines.insert(op["at"], op["text"])
            new = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
            if hashlib.sha256(new.encode("utf-8")).hexdigest() != e["sha256_after"]:
                print("ERR: %s 计算结果与计划不符，已中止（未写入）" % e["path"], file=sys.stderr)
                return 1
            atomic_write(p, new)
            done.append({"path": e["path"], "sha256": e["sha256_after"]})
        plan_path.unlink()
        payload = {"migrated": done, "schema": protocol.SCHEMA_VERSION}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json
              else "-- 迁移完成，%d 个文件：\n%s"
                   % (len(done), "\n".join("   ~ %s" % d["path"] for d in done)))
        return 0

    # --plan
    entries = build_plan(root, files)
    dirty = git_dirty(root)
    plan = {"schema_version": protocol.SCHEMA_VERSION, "target": str(root),
            "detected": state, "entries": entries,
            "git_dirty": dirty or [], "generated_by": "kb-migrate.py"}
    (root / PLAN_FILE).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

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
    print("\n计划已写入 %s（绑定源文件哈希；变了就重跑）" % PLAN_FILE)
    print("执行：py kb-migrate.py --target \"%s\" --apply" % root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
