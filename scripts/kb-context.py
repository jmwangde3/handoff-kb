#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-context.py — 按 Token 预算组装最小上下文

优先级固定（高 → 低）：
  P0 硬约束（dashboard.constraints / AGENTS 硬约束段）——任何预算都不裁
  P1 现状 + 下一手（dashboard.current / dashboard.next）
  P2 本工作线相关事实章节（fact.current / fact.commands）
  P3 基线命中行 + 证据指针（K-xx）
  P4 其余按相关度补满预算（流水与归档降权/默认排除）

预算不足时输出"摘要 + 指针"，并明确报超额；不虚构内容、不静默丢硬约束。

用法：
  py kb-context.py --target . --task "排查 NSS 网络问题" --budget 3000 --explain
  py kb-context.py --target . --task "..." --line 固件 --format json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import markdown as md  # noqa: E402
from lib import protocol, scope, terms as terms_lib, tokens  # noqa: E402


def parse_terms(text: str):
    return terms_lib.parse(text or "")


def split_row(line: str):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def table_rows_matching(doc: md.Document, terms, limit=8):
    """返回 (header_text, [rows])：命中关键词的表格行。"""
    header, out = "", []
    for i, raw in enumerate(doc.lines):
        line = raw.rstrip("\r")
        if line.strip().startswith("|"):
            if not header:
                header = line
            if re.match(r"^\s*\|?[\s:|-]+\|?\s*$", line):
                continue
            if any(t.lower() in line.lower() for t in terms):
                if line != header:
                    out.append((i + 1, line))
        else:
            if out and len(out) >= limit:
                break
            if not line.strip():
                header = header if out else ""
    return header, out[:limit]


def block(priority, title, source, section_id, text, reason, required=False):
    toks, desc = tokens.estimate(text)
    return {"priority": priority, "title": title, "source": source,
            "section_id": section_id, "text": text, "tokens": toks,
            "tokenizer": desc, "reason": reason, "required": required}


def section_text(doc, sid, include_children=True):
    sec = md.find_by_id(doc, sid)
    if not sec:
        return None, None
    text, _ = md.render(doc, sec, include_children=include_children)
    return sec, text


def find_line_fact(files, line: str, terms, task: str = ""):
    """按 --line、任务里出现的线名、或关键词命中挑一条事实分册。"""
    facts = [(protocol.number_of(p.name), p) for p in files.get("fact", [])]
    if not facts:
        return None
    if line:
        for _, p in facts:
            if line.lower() in p.stem.lower():
                return p
        return None
    # 线名直接出现在任务里最可靠（中文不做分词）
    for _, p in facts:
        name = p.stem.split("_", 1)[1] if "_" in p.stem else ""
        if name and name in (task or ""):
            return p
    best, best_score = None, 0
    for _, p in facts:
        name = p.stem.lower()
        score = sum(1 for t in terms if t.lower() in name)
        try:
            doc = md.parse_file(p)
            head = doc.sections[0].title.lower() if doc.sections else ""
            score += sum(1 for t in terms if t.lower() in head)
        except Exception:
            pass
        if score > best_score:
            best, best_score = p, score
    return best if best_score else None


def build(root: Path, files, task: str, line: str, include_archive: bool, budget: int = 3000):
    terms = parse_terms(task)
    blocks, gaps = [], []
    dash_p = files.get("dashboard", [None])[0]
    dash = md.parse_file(dash_p) if dash_p else None

    # P0 硬约束
    if dash:
        sec, text = section_text(dash, "dashboard.constraints", False)
        if sec is None:
            sec, text = section_text(dash, "dashboard.safety", False)
        if text and text.strip():
            blocks.append(block("P0", "硬约束（不裁剪）", dash_p.name, sec.id, text,
                                "任何预算下必读；删掉会让后续会话失去操作边界", required=True))
        else:
            gaps.append("缺少 kb:id: dashboard.constraints —— 硬约束未声明，建议补上")

    # 入口硬约束兜底
    agents = root / "AGENTS.md"
    if agents.is_file() and not any(b["priority"] == "P0" for b in blocks):
        adoc = md.parse_file(agents)
        for s in adoc.sections:
            if "硬约束" in s.title:
                text, _ = md.render(adoc, s, include_children=False)
                blocks.append(block("P0", "硬约束（AGENTS.md）", agents.name, None, text,
                                    "dashboard 没有约束段，退回入口文件", required=True))
                break

    # P1 现状 + 下一手
    if dash:
        for sid, title in (("dashboard.current", "现状"), ("dashboard.next", "下一手")):
            sec, text = section_text(dash, sid, False)
            if text and text.strip():
                blocks.append(block("P1", title, dash_p.name, sid, text,
                                    "接手必读；决定本次任务从哪开始", required=True))
            else:
                gaps.append("缺少 kb:id: %s" % sid)

    # P2 本线事实
    fact = find_line_fact(files, line, terms, task)
    if fact is not None:
        fdoc = md.parse_file(fact)
        sec, text = section_text(fdoc, "fact.current")
        if text and text.strip():
            blocks.append(block("P2", "本线当前值", fact.name, "fact.current", text,
                                "任务关键词命中这条工作线"))
        if any(k in (task or "") for k in ("排查", "命令", "怎么", "如何", "检查", "验证", "怎么跑")):
            sec2, text2 = section_text(fdoc, "fact.commands", False)
            if text2 and text2.strip():
                blocks.append(block("P2", "本线判据与命令", fact.name, "fact.commands", text2,
                                    "任务涉及验证/操作，需要可执行判据"))
        sec3, text3 = section_text(fdoc, "fact.pitfalls", False)
        if sec3 and text3.strip() and any(k in (task or "") for k in ("排查", "问题", "故障", "坑", "报错")):
            blocks.append(block("P2", "本线踩过的坑", fact.name, "fact.pitfalls", text3,
                                "排障类任务优先给已知坑，避免重走旧路"))
    elif terms:
        gaps.append("任务没有命中任何事实分册（用 kb-search.py 再定位）")

    # P3 基线与证据
    base_p = files.get("baseline", [None])[0]
    if base_p and terms:
        bdoc = md.parse_file(base_p)
        header, rows = table_rows_matching(bdoc, terms)
        if rows:
            text = "\n".join([header] + [r[1] for r in rows])
            blocks.append(block("P3", "基线命中 %d 行" % len(rows), base_p.name,
                                "baseline.facts", text,
                                "任务关键词命中基线表：%s" % ", ".join(terms[:4])))
            ev = []
            for _, row in rows:
                cells = split_row(row)
                if len(cells) >= 5 and cells[4] and cells[4] not in ("—", "-"):
                    ev.append("%s ← %s" % (cells[0], cells[4]))
            if ev:
                blocks.append(block("P3", "证据指针", base_p.name, "baseline.facts",
                                    "\n".join("- " + e for e in ev),
                                    "完成项必须有可追溯证据，否则只能算待核"))
        else:
            gaps.append("基线表没有命中；结论可能需要新建 K-xx")

        # 跨线问题：两条线同时出现，或问到影响/波及 → 交叉链必读
        line_names = [p.stem.split("_", 1)[1] for p in files.get("fact", []) if "_" in p.stem]
        hit_lines = [n for n in line_names if n and n in (task or "")]
        cross_hint = any(k in (task or "") for k in ("影响", "波及", "交叉", "同步", "同时"))
        if (len(hit_lines) >= 2 or cross_hint) and md.find_by_id(bdoc, "baseline.chains"):
            sec, text = section_text(bdoc, "baseline.chains", False)
            if text and text.strip():
                blocks.append(block("P3", "交叉链（改 A 波及 B）", base_p.name,
                                    "baseline.chains", text,
                                    "任务涉及跨线影响：先看交叉链再动手"))

    # P4 相关度补满：只占预算的 30%，最多 3 块，弱命中不进（防噪声淹没）
    picked = {(b["source"], b["section_id"]) for b in blocks}
    cands = []
    for path, reason in scope.iter_text_files(root, include_archive=include_archive):
        if reason:
            continue
        try:
            doc = md.parse_file(path)
        except Exception:
            continue
        for sec in doc.sections:
            key = (path.name, sec.id)
            if key in picked:
                continue
            body = "\n".join(doc.lines[sec.start:sec.stop])
            text = sec.title + "\n" + body
            score = sum(min(text.lower().count(t.lower()), 3) for t in terms) if terms else 0
            if score >= 2:
                role = protocol.role_of_name(path.name)
                weight = 0.4 if role in ("log", "shard") else (0.3 if role == "archive" else 1.0)
                cands.append((score * weight, path, sec, text))
    cands.sort(key=lambda x: -x[0])
    base_tokens = sum(b["tokens"] for b in blocks)
    p4_cap = max(120, min(int(budget * 0.3), int(base_tokens * 0.6)))
    p4_used, p4_count = 0, 0
    for score, path, sec, text in cands:
        if p4_count >= 3:
            break
        b = block("P4", sec.title, path.name, sec.id, text,
                  "相关度 %.1f（关键词计数，流水/归档已降权）" % score)
        if p4_used + b["tokens"] > p4_cap:
            continue
        blocks.append(b)
        p4_used += b["tokens"]
        p4_count += 1
    return blocks, gaps, terms


def render_markdown(task, line, mode, budget, used, blocks, skipped, gaps, over, tok_desc, explain):
    out = ["# 上下文包 — %s" % (task or "（未给任务）"), ""]
    out.append("预算 %s tokens / 实际 %s tokens（%s）｜模式 %s%s｜%d 块"
               % (budget, used, "估算" if not tok_desc.startswith("tiktoken:") else tok_desc,
                  mode, "｜工作线 %s" % line if line else "", len(blocks)))
    if over:
        out.append("")
        out.append("> **超额**：必读内容已超过预算 %d tokens。别删硬约束——拆任务或提高 --budget。"
                   % (used - budget))
    for b in blocks:
        out.append("")
        out.append("## [%s] %s%s" % (b["priority"], b["title"],
                                     "  · %s" % b["section_id"] if b["section_id"] else ""))
        out.append("<!-- source: %s -->" % b["source"])
        if explain:
            out.append("> 选择理由：%s（%d tokens）" % (b["reason"], b["tokens"]))
        out.append("")
        out.append(b["text"].rstrip())
    out.append("")
    out.append("---")
    out.append("## 预算与取舍")
    out.append("")
    out.append("| 块 | 来源 | tokens | 状态 |")
    out.append("|---|---|---|---|")
    for b in blocks:
        out.append("| %s %s | %s | %d | 已选 |" % (b["priority"], b["title"], b["source"], b["tokens"]))
    for s in skipped:
        out.append("| %s %s | %s | %d | 跳过：%s |"
                   % (s["priority"], s["title"], s["source"], s["tokens"], s["reason"]))
    if gaps:
        out.append("")
        out.append("## 缺口 / 待核")
        out.append("")
        for g in gaps:
            out.append("- %s" % g)
    out.append("")
    out.append("## 需要更多时")
    out.append("")
    out.append("- 精读某一节：`py kb-outline.py --file <文件> --section-id <ID>`")
    out.append("- 找资料：`py kb-search.py --target . --query \"<关键词>\"`")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="按 Token 预算组装最小上下文")
    ap.add_argument("--target", default=".")
    ap.add_argument("--task", default="")
    ap.add_argument("--line", default=None, help="限定工作线（事实分册名）")
    ap.add_argument("--mode", choices=["handoff", "task"], default="task")
    ap.add_argument("--budget", type=int, default=3000)
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown")
    ap.add_argument("--include-archive", action="store_true")
    ap.add_argument("--tokenizer", default="heuristic")
    ap.add_argument("--explain", action="store_true")
    args = ap.parse_args()

    try:
        root = scope.resolve_root(args.target)
    except scope.ScopeError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 2
    if args.budget <= 0:
        print("ERR: --budget 必须为正", file=sys.stderr)
        return 2

    files = scope.role_files(root)
    if not files.get("dashboard") and not files.get("baseline"):
        print("ERR: 这里不像交接库（没有 00/05）；先 kb-init.py 或 kb-migrate.py",
              file=sys.stderr)
        return 2

    blocks, gaps, terms = build(root, files, args.task, args.line,
                                args.include_archive, args.budget)
    # 预算装配：必读先放，其余按优先级放；放不下记 skipped
    used, kept, skipped, over = 0, [], [], False
    for b in blocks:
        fit = used + b["tokens"] <= args.budget
        if fit or b["required"]:
            kept.append(b)
            used += b["tokens"]
            if not fit:
                over = True
        else:
            skipped.append({**b, "reason": "超出预算 %d + %d > %d"
                                          % (used, b["tokens"], args.budget)})

    tok_desc = tokens.estimate("", args.tokenizer)[1]
    if args.format == "json":
        print(json.dumps({
            "task": args.task, "line": args.line, "mode": args.mode,
            "budget": args.budget, "used": used, "over_budget": over,
            "tokenizer": tok_desc, "terms": terms,
            "blocks": [{k: v for k, v in b.items() if k != "text"} | {"chars": len(b["text"])}
                       for b in kept],
            "skipped": [{k: v for k, v in s.items() if k != "text"} for s in skipped],
            "gaps": gaps,
            "context": {b["section_id"] or b["title"]: b["text"] for b in kept},
        }, ensure_ascii=False, indent=2))
        return 1 if over else 0

    print(render_markdown(args.task, args.line, args.mode, args.budget, used,
                          kept, skipped, gaps, over, tok_desc, args.explain))
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
