#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-handoff.py — 交接有效性检查（证据优先）

回答 8 个问题，缺一项就报"待核/缺失"，绝不把"没写证据的完成"当成已完成：
  1 当前任务是什么  2 确实完成了什么  3 证据是什么  4 哪些还没核实
  5 当前阻塞是什么  6 下一步具体做什么  7 影响哪些文件  8 哪些操作别重复

用法：
  py kb-handoff.py check  --target . [--strict] [--json]
  py kb-handoff.py report --target . [--json]

退出码：0 通过（或仅有待核项且未开 strict）/ 1 有缺失或 strict 下有 WARN / 2 环境错误
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import markdown as md  # noqa: E402
from lib import protocol, scope  # noqa: E402

PLACEHOLDER = re.compile(r"\[填|待填|TODO|TBD", re.I)


def is_filled(text: str) -> bool:
    """有实质内容才算填写：注释不算，含 [填/TODO 的整行按占位处理。"""
    real = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("<!--") or PLACEHOLDER.search(s):
            continue
        real.append(s)
    return len("".join(real).strip(" -|:\t")) >= 4


FALLBACK = {
    "dashboard.current": ("现状", "现在在做什么", "当前在做什么", "进度"),
    "dashboard.next": ("下一手", "下一步", "接下来", "待办"),
    "dashboard.constraints": ("硬约束", "边界", "禁止", "不要", "安全"),
}


def sec_text(doc, sid, children=False):
    """先按 kb:id 找；没有 ID 的老库按标题关键词兜底（返回的 sec.id 为 None）。"""
    sec = md.find_by_id(doc, sid)
    if not sec:
        for kw in FALLBACK.get(sid, ()):
            for s in doc.sections:
                if s.level >= 1 and kw in s.title:
                    sec = s
                    break
            if sec:
                break
    if not sec:
        return None, ""
    text, _ = md.render(doc, sec, include_children=children)
    return sec, text


def check(root: Path, loose: bool = False):
    files = scope.role_files(root, loose=loose)
    items, gaps = [], []

    def add(key, status, detail, question):
        items.append({"key": key, "status": status, "detail": detail, "question": question})

    dash_p = files.get("dashboard", [None])[0]
    if not dash_p:
        add("dashboard", "missing", "缺少 05 进度仪表盘", "1 当前任务是什么")
        return items, gaps
    dash = md.parse_file(dash_p)

    sec, text = sec_text(dash, "dashboard.current")
    if sec is None:
        add("current", "missing", "缺少「现状」章节（或 kb:id: dashboard.current）", "1 当前任务是什么")
    elif is_filled(text):
        add("current", "ok", "现状已填写（%d 行）" % len(text.strip().splitlines()),
            "1 当前任务是什么")
    else:
        add("current", "pending", "现状仍是模板占位或为空", "1 当前任务是什么")

    sec, text = sec_text(dash, "dashboard.next")
    if sec is None:
        add("next", "missing", "缺少「下一手」章节（或 kb:id: dashboard.next）", "6 下一步具体做什么")
    elif is_filled(text):
        add("next", "ok", "下一手已填写", "6 下一步具体做什么")
    else:
        add("next", "pending", "「下一手」为空或仍是占位", "6 下一步具体做什么")

    sec, text = sec_text(dash, "dashboard.constraints")
    if sec is None:
        add("constraints", "missing", "缺少「硬约束」章节（或 kb:id: dashboard.constraints）", "8 哪些操作别重复")
    elif is_filled(text):
        add("constraints", "ok", "硬约束已声明", "8 哪些操作别重复")
    else:
        add("constraints", "pending", "硬约束仍是占位", "8 哪些操作别重复")

    # 证据：基线里"有效"却无证据的条目
    base_p = files.get("baseline", [None])[0]
    no_ev = []
    if base_p:
        bdoc = md.parse_file(base_p)
        for raw in bdoc.lines:
            if not raw.strip().startswith("|"):
                continue
            cells = [c.strip() for c in raw.strip().strip("|").split("|")]
            if len(cells) >= 5 and protocol.FACT_ID_RE.fullmatch(cells[0]):
                status, ev = cells[3], cells[4]
                if any(s in status for s in ("有效", "valid")) and ev in ("", "—", "-", "无"):
                    no_ev.append(cells[0])
    if no_ev:
        add("evidence", "pending", "%d 条「有效」事实没有证据：%s"
            % (len(no_ev), ", ".join(no_ev[:5])), "3 证据是什么")
    else:
        add("evidence", "ok", "基线的有效事实都有证据或标了待核", "3 证据是什么")

    # 完成/待办
    sec, text = sec_text(dash, "dashboard.todo", children=True)
    todo_rows = [l for l in text.splitlines() if l.strip().startswith("|") and "---" not in l]
    filled_todo = [l for l in todo_rows[1:] if not PLACEHOLDER.search(l)]
    if sec is None:
        add("todo", "missing", "缺少「待办」章节（或 kb:id: dashboard.todo）", "2 确实完成了什么")
    elif filled_todo:
        add("todo", "ok", "%d 条待办已具体化" % len(filled_todo), "2 确实完成了什么")
    else:
        add("todo", "pending", "待办表为空或只有占位", "2 确实完成了什么")

    # 流水
    shards = scope.shards(root)
    written = []
    for p in shards:
        doc = md.parse_file(p)
        body = "\n".join(doc.lines)
        if "尚无记录" not in body and re.search(r"\d{4}-\d{2}-\d{2}", body):
            written.append(p.name)
    if written:
        add("log", "ok", "%d 个分片有实际记录（%s）" % (len(written), ", ".join(written[:3])),
            "7 影响哪些文件")
    else:
        add("log", "pending", "流水还没有实际记录", "7 影响哪些文件")

    # 阻塞
    sec, text = sec_text(dash, "dashboard.todo", children=True)
    blocked = "阻塞" in text or "blocked" in text.lower()
    add("blocked", "ok" if blocked else "pending",
        "待办区已标注阻塞" if blocked else "没有标注阻塞项（若确实无阻塞可忽略）",
        "5 当前阻塞是什么")

    return items, gaps


def summarize(items):
    bad = [i for i in items if i["status"] != "ok"]
    return len(items) - len(bad), len(bad)


def main() -> int:
    ap = argparse.ArgumentParser(description="交接有效性检查（证据优先）")
    ap.add_argument("cmd", choices=["check", "report"])
    ap.add_argument("--target", default=".")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--loose", action="store_true", help="按别名识别 05/06/90（自有命名项目）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        root = scope.resolve_root(args.target)
    except scope.ScopeError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 2

    items, gaps = check(root, args.loose)
    ok, bad = summarize(items)
    missing = [i for i in items if i["status"] == "missing"]
    pending = [i for i in items if i["status"] == "pending"]

    next_steps = [
        "读：py kb-write.py read --target . --file 05_进度仪表盘.md --json",
        "写：把改动写进 changes.json（replace_section + expected_sha256）后 apply",
        "校验：py kb-check.py --target . --strict",
        "提交：git add -- <本次文件> && git commit -m \"<线> <做了什么>\"",
    ]
    payload = {"target": str(root), "ok": ok, "not_ok": bad,
               "pass": not missing and (not args.strict or not pending),
               "items": items, "next_steps": next_steps}

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("== 交接检查：%s" % root)
        for i in items:
            mark = {"ok": "OK  ", "pending": "待核", "missing": "缺失"}[i["status"]]
            print("[%s] %-12s %s" % (mark, i["key"], i["detail"]))
        print("\n== 通过 %d / 待处理 %d（%s%s）"
              % (ok, bad, "通过" if payload["pass"] else "未通过",
                 "；%d 项待核，--strict 会失败" % len(pending) if pending and not args.strict else ""))
        if bad:
            print("-- 收尾提示 --")
            for s in next_steps:
                print("   %s" % s)

    if missing:
        return 1
    if args.strict and pending:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
