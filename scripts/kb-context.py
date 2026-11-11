#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-context.py — 按 Token 预算组装最小上下文（2.0.1）

优先级固定（高 → 低）：
  P0 硬约束（dashboard.constraints / AGENTS 硬约束段）——任何预算都不裁
  P1 现状 + 下一手（dashboard.current / dashboard.next）
  P2 相关工作线的事实章节（支持一次加载多条线：fact.current / commands / pitfalls）
  P3 基线命中行 + 证据指针 + 交叉链
  P4 其余按相关度补满（流水与归档降权/默认排除）

2.0.1 的三处关键变化：
  1. **多工作线**：`--line 固件,运行态` 或任务里出现多个线名时全部加载；
     预算装不下时报告「已加载 / 未加载」与指针，绝不把部分加载说成完整接手。
  2. **同一个 TokenCounter 贯穿**：块、包装、最终 Markdown 都用同一个计数器。
  3. **预算按最终输出算**：包装（标题/来源/理由/缺口/指针/说明）都计入，
     超预算先丢最低优先级的可选块，必需块超额则如实报告 over_budget。

用法：
  py kb-context.py --target . --task "排查 NSS 网络问题" --budget 3000 --explain
  py kb-context.py --target . --task "..." --line 固件,运行态 --format json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import facts  # noqa: E402
from lib import markdown as md  # noqa: E402
from lib import protocol, scope, terms as terms_lib, tokens  # noqa: E402

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
TASK_VERBS_VERIFY = ("排查", "命令", "怎么", "如何", "检查", "验证", "怎么跑", "复现")
TASK_VERBS_TROUBLE = ("排查", "问题", "故障", "坑", "报错", "崩溃", "掉速")
TASK_VERBS_CROSS = ("影响", "波及", "交叉", "同步", "同时", "依赖")

# P4 的硬约束：数量、预算占比、相关性阈值，三者同时生效
P4_MAX_BLOCKS = 3
P4_BUDGET_SHARE = 0.30
P4_MIN_TERMS = 2
TASK_ID_RE = re.compile(r"\b([KG]-\d{2,3})\b")


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
            if re.match(r"^\s*\|?[\s:| -]+\|?\s*$", line):
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


def section_text(doc, sid, include_children=True):
    sec = md.find_by_id(doc, sid)
    if not sec:
        return None, None
    text, _ = md.render(doc, sec, include_children=include_children)
    return sec, text


def line_name(path: Path) -> str:
    stem = path.stem
    return stem.split("_", 1)[1] if "_" in stem else stem


def find_line_facts(files, line_spec, terms, task: str = ""):
    """返回 ([fact_path...], reason)。

    规则（依次）：
      1. 显式 --line（逗号或重复参数都可）→ 命中的全部
      2. 任务里出现多个线名 → 全部；出现一个 → 那一个
      3. 只有关键词模糊命中 → 取最高分的一条（避免噪声）
    """
    facts = [(protocol.number_of(p.name), p) for p in files.get("fact", [])]
    facts = [p for _, p in sorted(facts, key=lambda x: (x[0] is None, x[0]))]
    if not facts:
        return [], "没有事实分册"

    names = [line_name(p) for p in facts]
    wanted = []
    if line_spec:
        for chunk in re.split(r"[,，;；\s]+", str(line_spec)):
            chunk = chunk.strip().lower()
            if not chunk:
                continue
            for p, n in zip(facts, names):
                if chunk in p.stem.lower() or chunk in n.lower():
                    if p not in wanted:
                        wanted.append(p)
        if wanted:
            return wanted, "显式指定工作线"
        return [], "指定的工作线不存在（可选：%s）" % "、".join(names)

    hit = [p for p, n in zip(facts, names) if n and n in (task or "")]
    if hit:
        return hit, "任务里点名的 %d 条工作线" % len(hit)

    best, best_score = None, 0
    for p in facts:
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
    # 单个关键词命中线名也算命中（"10_NSS.md" + 任务含 NSS）；
    # 只取最高分一条，同分不堆块，避免把噪声工作线一起装进来。
    if best is not None and best_score >= 1:
        return [best], "关键词最高分（%d）" % best_score
    return [], "任务没有命中任何事实分册"


def p4_candidates(root: Path, terms, used_sources: set, used_section_keys: set,
                  include_archive: bool, loose: bool, max_blocks=P4_MAX_BLOCKS):
    """受控 P4：只补「确实相关」的少量章节。

    约束（全部硬性）：
      - 最多 max_blocks 块
      - 至少命中 P4_MIN_TERMS 个不同关键词，否则不补（返回 0 块是正确结果）
      - 归档默认不参与；流水/归档按权重降序靠后
      - 已经被 P0–P3 用过的文件/章节不重复加入
    """
    if not terms:
        return []
    rows = []
    for p, reason in scope.iter_text_files(root, include_archive=include_archive):
        if reason:
            continue
        rel = p.relative_to(root).as_posix()
        if rel in used_sources:
            continue
        role = scope.role_of_path(root, p, loose=loose)
        weight = 0.4 if role in ("log", "shard") else (0.3 if role == "archive" else 1.0)
        try:
            doc = md.parse_file(p)
        except Exception:
            continue
        for sec in doc.sections:
            key = (rel, sec.id or sec.line)
            if key in used_section_keys:
                continue
            body = "\n".join(doc.lines[sec.start:sec.stop])
            text = (sec.title or "") + "\n" + body
            low = text.lower()
            hits = [t for t in terms if t.lower() in low]
            # 单一关键词也能算「确实相关」，但只有它足够长（≥4 字符）才算：
            # 「固件」这种两字词命中满库都是，不该拿来做 P4 的入场券。
            distinctive = len(hits) == 1 and len(hits[0]) >= 4
            if len(hits) < P4_MIN_TERMS and not distinctive:
                continue
            rows.append({"score": len(hits) * weight, "file": rel, "section_id": sec.id,
                         "heading": sec.title, "line": sec.line,
                         "text": text.strip(), "hits": hits, "role": role})
    rows.sort(key=lambda r: (-r["score"], r["file"], r["line"]))
    return rows[:max_blocks]


def build(root: Path, files, task: str, line_spec, include_archive: bool,
          counter, budget: int = 3000, loose: bool = False):
    terms = parse_terms(task)
    blocks, gaps = [], []
    selected_lines, omitted_lines = [], []
    dash_p = files.get("dashboard", [None])[0]
    dash = md.parse_file(dash_p) if dash_p else None

    def add(priority, title, source, sid, text, reason, required=False, line=None):
        blocks.append({"priority": priority, "title": title, "source": source,
                       "section_id": sid, "text": text, "reason": reason,
                       "required": required, "line": line})

    # P0 硬约束
    if dash:
        sec, text = section_text(dash, "dashboard.constraints", False)
        if sec is None:
            sec, text = section_text(dash, "dashboard.safety", False)
        if text and text.strip():
            add("P0", "硬约束（不裁剪）", dash_p.name, sec.id, text,
                "任何预算下必读；删掉会让后续会话失去操作边界", required=True)
        else:
            gaps.append("缺少 kb:id: dashboard.constraints —— 硬约束未声明，建议补上")

    agents = root / "AGENTS.md"
    if agents.is_file() and not any(b["priority"] == "P0" for b in blocks):
        adoc = md.parse_file(agents)
        for s in adoc.sections:
            if "硬约束" in s.title:
                text, _ = md.render(adoc, s, include_children=False)
                add("P0", "硬约束（AGENTS.md）", agents.name, None, text,
                    "dashboard 没有约束段，退回入口文件", required=True)
                break

    # P1 现状 + 下一手
    if dash:
        for sid, title in (("dashboard.current", "现状"), ("dashboard.next", "下一手")):
            sec, text = section_text(dash, sid, False)
            if text and text.strip():
                add("P1", title, dash_p.name, sid, text,
                    "接手必读；决定本次任务从哪开始", required=True)
            else:
                gaps.append("缺少 kb:id: %s" % sid)
        if not any(b["priority"] == "P1" for b in blocks):
            head = "\n".join(dash.lines[:40]).strip()
            if head:
                add("P1", "现状（无 kb:id 兜底）", dash_p.name, None, head,
                    "05 尚未加 kb:id，取前 40 行；跑 kb-migrate.py 可精确到节",
                    required=True)

    # P2 工作线事实（可多条）
    fact_paths, why = find_line_facts(files, line_spec, terms, task)
    if not fact_paths and terms:
        gaps.append(why if "不存在" in why or "没有" in why else
                    "任务没有命中任何事实分册（用 kb-search.py 再定位）")
    want_verify = any(k in (task or "") for k in TASK_VERBS_VERIFY)
    want_trouble = any(k in (task or "") for k in TASK_VERBS_TROUBLE)
    per_line_blocks = []
    for p in fact_paths:
        fdoc = md.parse_file(p)
        name = line_name(p)
        items = []
        _, text = section_text(fdoc, "fact.current")
        if text and text.strip():
            items.append(("本线当前值 · %s" % name, p.name, "fact.current", text,
                          "任务命中这条工作线（%s）" % why))
        if want_verify:
            _, t2 = section_text(fdoc, "fact.commands", False)
            if t2 and t2.strip():
                items.append(("本线判据与命令 · %s" % name, p.name, "fact.commands", t2,
                              "任务涉及验证/操作，需要可执行判据"))
        if want_trouble:
            _, t3 = section_text(fdoc, "fact.pitfalls", False)
            if t3 and t3.strip():
                items.append(("本线踩过的坑 · %s" % name, p.name, "fact.pitfalls", t3,
                              "排障类任务优先给已知坑，避免重走旧路"))
        # P2 必须真正进入 blocks，否则装配器永远看不到工作线事实
        for title, source, sid, text, reason in items:
            add("P2", title, source, sid, text, reason, required=False, line=name)
        per_line_blocks.append((name, items))

    # P3 任务点名的事实（G/K）+ 基线命中 + 证据 + 交叉链
    fact_defs, fact_problems = facts.parse_fact_definitions(
        root, include_archive=include_archive, loose=loose)
    if fact_problems:
        gaps.append("事实解析有 %d 个问题（首条：%s）——这些事实的状况未知"
                    % (len(fact_problems), fact_problems[0]))
    asked = sorted({m.upper() for m in TASK_ID_RE.findall(task or "")})
    for fid in asked:
        items = fact_defs.get(fid) or []
        if not items:
            gaps.append("任务点名 %s，但库里没有这个事实定义（ID 写错？还是还没建？）" % fid)
            continue
        live = [d for d in items if d.status != "deprecated"]
        if not live:
            sup = next((d.superseded_by for d in items if d.superseded_by), "")
            gaps.append("%s 只有已作废定义%s：不作为当前配置；需要时按替代事实查"
                        % (fid, "（替代 %s）" % sup if sup else "（未写替代 ID）"))
            continue
        d = live[0]
        text = facts.definition_text(root, d)
        if text:
            add("P3", "任务点名的事实 %s" % fid, d.path, None, text,
                "%s 的定义位（%s，状态 %s）" % (fid, d.definition_type, d.status))
        if len(live) > 1:
            gaps.append("%s 有 %d 处定义（%s）：已取第一处，建议合并"
                        % (fid, len(live),
                           "、".join("%s:%d" % (x.path, x.line_start) for x in live[:3])))

    base_p = files.get("baseline", [None])[0]
    if base_p and terms:
        bdoc = md.parse_file(base_p)
        header, rows = table_rows_matching(bdoc, terms)
        if rows:
            text = "\n".join([header] + [r[1] for r in rows])
            add("P3", "基线命中 %d 行" % len(rows), base_p.name, "baseline.facts", text,
                "任务关键词命中基线表：%s" % ", ".join(terms[:4]))
            ev = []
            for _, row in rows:
                cells = split_row(row)
                if len(cells) >= 5 and cells[4] and cells[4] not in ("—", "-"):
                    ev.append("%s ← %s" % (cells[0], cells[4]))
            if ev:
                add("P3", "证据指针", base_p.name, "baseline.facts",
                    "\n".join("- " + e for e in ev),
                    "完成项必须有可追溯证据，否则只能算待核")
        else:
            gaps.append("基线表没有命中；结论可能需要新建 K-xx")

        cross = (len(fact_paths) >= 2
                 or any(k in (task or "") for k in TASK_VERBS_CROSS))
        if cross and md.find_by_id(bdoc, "baseline.chains"):
            _, text = section_text(bdoc, "baseline.chains", False)
            if text and text.strip():
                add("P3", "交叉链（改 A 波及 B）", base_p.name, "baseline.chains", text,
                    "任务涉及跨线影响：先看交叉链再动手")

    # P4 受控补充：数量、预算占比、相关性阈值三者同时生效
    used_sources = {b["source"] for b in blocks}
    # 任务点名事实所在的文件整份不参与 P4：那条事实已经由 P3 按状态处理过，
    # 再从全文捞一遍会把「已作废」的内容当补充材料塞回上下文。
    for fid in asked:
        for d in fact_defs.get(fid, []):
            used_sources.add(d.path)
    used_keys = {(b["source"], b["section_id"]) for b in blocks if b["section_id"]}
    # 事实 ID 不作为 P4 关键词：ID 的查找有专门路径（含状态判定），
    # 交给全文匹配只会在整个文件里乱捞。
    p4_terms = [t for t in terms if not TASK_ID_RE.fullmatch(t)]
    p4 = p4_candidates(root, p4_terms, used_sources, used_keys, include_archive, loose)
    p4_cap = int(budget * P4_BUDGET_SHARE)
    picked, used_tokens = [], 0
    for row in p4:
        n = counter.count(row["text"])
        if used_tokens + n > p4_cap:
            continue
        used_tokens += n
        picked.append(row)
    for row in picked:
        add("P4", "相关补充 · %s" % (row["heading"] or row["file"]), row["file"],
            row["section_id"], row["text"],
            "关键词命中 %s（%s，权重 %.1f）" % ("、".join(row["hits"][:3]),
                                             row["role"], row["score"] / max(1, len(row["hits"]))))
    if not picked and terms:
        gaps.append("没有足够的 P4 相关内容（阈值 ≥%d 个关键词）；0 块是正常结果"
                    % P4_MIN_TERMS)

    return {"blocks": blocks, "per_line": per_line_blocks, "gaps": gaps,
            "terms": terms, "fact_paths": fact_paths, "why": why,
            "selected_lines": [line_name(p) for p in fact_paths],
            "p4": {"count": len(picked), "tokens": used_tokens, "cap": p4_cap,
                   "candidates": len(p4)},
            "asked_ids": asked, "dash": dash_p, "base": base_p}


# --------------------------------------------------------------------------- #
# 渲染与预算
# --------------------------------------------------------------------------- #

def render(task, line, mode, budget, kept, skipped, gaps, over, counter, explain,
           used=None):
    """渲染最终 Markdown。`used` 为 None 时先渲染再回填（最多两次迭代收敛）。"""
    def body(actual_text):
        out = ["# 上下文包 — %s" % (task or "（未给任务）"), ""]
        head = ("预算 %s tokens / 实际 %s tokens（%s）｜模式 %s%s｜%d 块"
                % (budget, actual_text, counter.desc, mode,
                   "｜工作线 %s" % line if line else "", len(kept)))
        out.append(head)
        if over:
            out.append("")
            out.append("> **超额**：必读内容已超过预算。别删硬约束——拆任务或提高 --budget。")
        for b in kept:
            out.append("")
            out.append("## [%s] %s%s" % (b["priority"], b["title"],
                                         "  · %s" % b["section_id"] if b["section_id"] else ""))
            out.append("<!-- source: %s -->" % b["source"])
            if explain:
                out.append("> 选择理由：%s（%d tokens）"
                           % (b["reason"], count_block(b, counter)))
            out.append("")
            out.append(b["text"].rstrip())
        out.append("")
        out.append("---")
        out.append("## 预算与取舍")
        out.append("")
        out.append("| 块 | 来源 | tokens | 状态 |")
        out.append("|---|---|---|---|")
        for b in kept:
            out.append("| %s %s | %s | %d | 已选 |"
                       % (b["priority"], b["title"], b["source"], count_block(b, counter)))
        for s in skipped:
            out.append("| %s %s | %s | %d | 跳过：%s |"
                       % (s["priority"], s["title"], s["source"],
                          count_block(s, counter), s["reason"]))
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

    guess = used
    if guess is None:
        guess = counter.count(body("0"))
    text = body(str(guess))
    for _ in range(3):
        size = counter.count(text)
        if size == guess:
            break
        guess = size
        text = body(str(guess))
    return text, counter.count(text)


def count_block(b, counter):
    return counter.count("## [%s] %s  · %s\n<!-- source: %s -->\n> 选择理由：%s\n\n%s"
                         % (b["priority"], b["title"], b["section_id"] or "",
                            b["source"], b["reason"], b["text"]))


def context_map(blocks):
    """section_id → 正文。同一 section_id 可能来自多块（基线命中 + 证据指针），
    早先直接用字典推导会让后一块覆盖前一块，JSON 消费方静默丢内容。"""
    out = {}
    for b in blocks:
        key = b["section_id"] or b["title"]
        if key in out:
            key = "%s · %s" % (key, b["title"])
        base, n = key, 2
        while key in out:
            key = "%s #%d" % (base, n)
            n += 1
        out[key] = b["text"]
    return out


def assemble(task, line, mode, budget, blocks, gaps, counter, explain):
    """两轮装配：必需块先放，可选块按优先级装，超预算丢最低优先级并重算。"""
    required = [b for b in blocks if b["required"]]
    optional = sorted([b for b in blocks if not b["required"]],
                      key=lambda b: PRIORITY_ORDER.get(b["priority"], 9))

    kept, skipped = list(required), []
    for b in optional:
        trial = kept + [b]
        _, size = render(task, line, mode, budget, trial, skipped, gaps, False,
                         counter, explain)
        if size <= budget:
            kept = trial
        else:
            skipped.append({**b, "reason": "试探后超预算"})

    over = False
    for _ in range(len(optional) + 1):
        text, size = render(task, line, mode, budget, kept, skipped, gaps, over,
                            counter, explain)
        if size <= budget:
            return kept, skipped, size, False, text
        droppable = [b for b in kept if not b["required"]]
        if not droppable:
            text, size = render(task, line, mode, budget, kept, skipped, gaps, True,
                                counter, explain)
            return kept, skipped, size, True, text
        drop = droppable[-1]
        kept = [b for b in kept if b is not drop]
        skipped.insert(0, {**drop, "reason": "最终渲染超预算，已移除"})
    text, size = render(task, line, mode, budget, kept, skipped, gaps, True,
                        counter, explain)
    return kept, skipped, size, True, text


def main() -> int:
    ap = argparse.ArgumentParser(description="按 Token 预算组装最小上下文")
    ap.add_argument("--target", default=".")
    ap.add_argument("--task", default="")
    ap.add_argument("--line", default=None, action="append",
                    help="限定工作线；可逗号分隔多条，也可重复该参数（两种写法等价）")
    ap.add_argument("--mode", choices=["handoff", "task"], default="task")
    ap.add_argument("--budget", type=int, default=3000)
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown")
    ap.add_argument("--include-archive", action="store_true")
    ap.add_argument("--loose", action="store_true", help="按别名识别 05/06/90（自有命名项目）")
    ap.add_argument("--tokenizer", default="heuristic")
    ap.add_argument("--allow-tokenizer-fallback", action="store_true")
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

    try:
        counter = tokens.TokenCounter(args.tokenizer, args.allow_tokenizer_fallback)
    except tokens.TokenizerError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 2

    files = scope.role_files(root, loose=args.loose)
    if not files.get("dashboard") and not files.get("baseline"):
        print("ERR: 这里不像交接库（没有 00/05）；先 kb-init.py 或 kb-migrate.py",
              file=sys.stderr)
        return 2

    # --line 支持「逗号分隔」与「重复参数」两种写法，去重保序
    line_spec = None
    if args.line:
        seen, parts = set(), []
        for chunk in args.line:
            for piece in re.split(r"[,，;；\s]+", str(chunk)):
                piece = piece.strip()
                if piece and piece.lower() not in seen:
                    seen.add(piece.lower())
                    parts.append(piece)
        line_spec = ",".join(parts) or None

    built = build(root, files, args.task, line_spec, args.include_archive,
                  counter, args.budget, args.loose)
    kept, skipped, rendered_tokens, over, text = assemble(
        args.task, line_spec, args.mode, args.budget, built["blocks"], built["gaps"],
        counter, args.explain)

    # 工作线：装不下的如实报出来（不把部分加载说成完整接手）
    def split_lines(kept_now):
        loaded_now, omitted_now, empty_now = [], [], []
        for name, items in built["per_line"]:
            if not items:
                empty_now.append(name)
            elif any(b.get("line") == name for b in kept_now):
                loaded_now.append(name)
            else:
                omitted_now.append(name)
        return loaded_now, omitted_now, empty_now

    loaded, omitted, empty = split_lines(kept)
    if omitted or empty:
        for name in omitted:
            built["gaps"].append(
                "工作线「%s」的相关事实未加载（预算 %d 已满）；用 --line %s 单独取，或提高 --budget"
                % (name, args.budget, name))
        for name in empty:
            built["gaps"].append(
                "工作线「%s」里没有 fact.current / commands / pitfalls 可加载的事实节" % name)
        kept, skipped, rendered_tokens, over, text = assemble(
            args.task, line_spec, args.mode, args.budget, built["blocks"],
            built["gaps"], counter, args.explain)
        loaded, omitted, empty = split_lines(kept)

    required_tokens = sum(count_block(b, counter) for b in kept if b["required"])
    block_tokens = sum(count_block(b, counter) for b in kept)
    payload = {
        "task": args.task, "line": line_spec, "mode": args.mode,
        "budget": args.budget,
        "tokenizer": counter.desc, "requested": args.tokenizer,
        "exact": counter.exact,
        "block_tokens": block_tokens, "rendered_tokens": rendered_tokens,
        "required_tokens": required_tokens,
        "optional_tokens": max(block_tokens - required_tokens, 0),
        "used": rendered_tokens, "over_budget": over,
        "selected_lines": loaded, "omitted_lines": omitted,
        "terms": built["terms"],
        "blocks": [{k: v for k, v in b.items() if k != "text"}
                   | {"chars": len(b["text"]), "tokens": count_block(b, counter)}
                   for b in kept],
        "skipped": [{"priority": s["priority"], "title": s["title"],
                     "source": s["source"], "reason": s["reason"],
                     "tokens": count_block(s, counter)} for s in skipped],
        "p4": built["p4"], "asked_ids": built["asked_ids"],
        "gaps": built["gaps"],
        "context": context_map(kept),
    }
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1 if over else 0

    print(text)
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
