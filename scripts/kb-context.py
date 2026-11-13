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
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import constraints  # noqa: E402
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
# 容器节（h1 只是名字、正文全在子节）单独兜底时的整节上限。
# 超过这个量说明它是大分册，装整棵子树太贵，交给子节各自竞争。
# 600 的依据：1–2 KB 的小分册整节约 350–450 tok（实测 430），装整节比拆成
# 子节更划算——不必重复装、上下文完整，还救得回「子节各只命中一个词」的线。
CONTAINER_MAX_TOKENS = 600
# H1 的降权系数。早先直接把首个 h1 整节排除（它装的是「本文件讲什么」，
# 主题词最全、按命中数排必进前三）；但 `# 当前系统状态` 这种 h1 本身
# 就可能是最重要的那段话，只凭「它是 h1」就丢掉是错的。
# 现在改为降权 + 只渲染自有正文：更具体的子节权重更高，自然排在前面。
H1_WEIGHT = 0.6
# 「文件导语」型 h1（写着适用版本、最后更新、本文件讲什么）再降一档
H1_META_WEIGHT = 0.3
H1_META_HINTS = ("最后更新", "适用版本", "适用范围", "本文件", "本文档", "文档说明")
TASK_ID_RE = re.compile(r"\b([KG]-\d{2,3})\b")
# 只有明确在问「过去」的任务，才允许 P4 把已作废章节带回上下文
TASK_HISTORY_HINTS = ("历史", "以前", "旧值", "旧的", "曾经", "当初", "作废",
                      "沿革", "变更记录", "为什么改", "什么时候改")


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


def rel_of(root: Path, p) -> str:
    """块的唯一身份：工作区内的 posix 相对路径。

    `source` 只放文件名给人看（同一个库常有子目录同名文件），去重必须用真实相对
    路径；越界或拿不到时返回空串，由调用方降级为文件名。
    """
    if not p:
        return ""
    try:
        return Path(p).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return ""


def find_line_facts(root, files, line_spec, terms, task: str = "", loose: bool = False):
    """返回 (paths, reason, missing, candidates)。

    规则（依次）：
      1. 显式 --line（逗号或重复参数都可）→ 命中的全部；点不存在的逐个报 missing
      2. 任务里出现多个线名 → 全部；出现一个 → 那一个
      3. 只有关键词模糊命中 → 取最高分的一条（避免噪声）

    `--loose` 下任何数字分册都会成为「事实线」，但编号本身不证明里面是事实。
    有事实结构的（`fact.*` 章节 / ≥2 条 K-G / ≥2 条项目自有编号条目）优先；
    只有编号的按**候选**处理：仍然能被选中，但排在结构化分册之后，理由里写明。
    """
    items = [(protocol.number_of(p.name), p) for p in files.get("fact", [])]
    items = [p for _, p in sorted(items, key=lambda x: (x[0] is None, x[0]))]
    if not items:
        return [], "没有事实分册", [], []

    conf = {}

    def kind(p):
        """structured / candidate。只有「--loose 兜底进来的自有编号」才可能是候选：
        01–04（旧库事实位）与 10–17（规范事实位）是协议指定的事实线，
        它们没有 fact.* 章节是写法问题，不该因此被打成候选。"""
        if p not in conf:
            if loose and facts.is_custom_fact_name(p.name):
                try:
                    conf[p] = facts.fact_confidence(p, loose=loose)
                except Exception:
                    conf[p] = "candidate"
            else:
                conf[p] = "structured"
        return conf[p]

    names = [line_name(p) for p in items]
    wanted, missing = [], []
    if line_spec:
        for chunk in re.split(r"[,，;；\s]+", str(line_spec)):
            chunk = chunk.strip().lower()
            if not chunk:
                continue
            hit = [p for p, n in zip(items, names)
                   if chunk in p.stem.lower() or chunk in n.lower()]
            if not hit:
                missing.append(chunk)
            for p in hit:
                if p not in wanted:
                    wanted.append(p)
        if wanted:
            return (wanted, "显式指定工作线", missing,
                    [p for p in wanted if kind(p) == "candidate"])
        return ([], "指定的工作线不存在（可选：%s）" % "、".join(names),
                missing, [])

    hit = [p for p, n in zip(items, names) if n and n in (task or "")]
    if hit:
        strong = [p for p in hit if kind(p) == "structured"]
        use = strong or hit
        return (use, "任务里点名的 %d 条工作线" % len(use), [],
                [p for p in use if kind(p) == "candidate"])

    def pick(pool):
        best, best_score = None, 0
        for p in pool:
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
        return best, best_score

    # 单个关键词命中线名也算命中（"10_NSS.md" + 任务含 NSS）；
    # 只取最高分一条，同分不堆块，避免把噪声工作线一起装进来。
    best, score = pick([p for p in items if kind(p) == "structured"])
    if best is not None and score >= 1:
        return [best], "关键词最高分（%d）" % score, [], []
    best, score = pick(items)
    if best is not None and score >= 1:
        return ([best], "关键词最高分（%d，候选分册）" % score, [], [best])
    return [], "任务没有命中任何事实分册", [], []


def wants_history(task: str) -> bool:
    """任务是否在问「过去」——只有这种问法才允许 P4 带回已作废章节。"""
    return any(k in (task or "") for k in TASK_HISTORY_HINTS)


def fact_marks(fact_defs) -> dict:
    """{相对路径: [(line_start, line_end, id, status, superseded_by)]}；只看规范定义。

    索引页里的同 ID 行是**指针**（导航），不该把整个索引节标成「已作废」。
    """
    out = {}
    for items in (fact_defs or {}).values():
        for d in items:
            if d.pointer:
                continue
            out.setdefault(d.path, []).append(
                (d.line_start, d.line_end, d.id, d.status, d.superseded_by))
    return out


def section_marks(marks, sec):
    """落在某一节里的定义（Section.line / end 都是 1 基、含端点）。"""
    return [m for m in marks if sec.line <= m[0] <= sec.end]


def dead_note(dead, omitted: bool = False) -> str:
    ids = "、".join("%s%s" % (m[2], "（替代 %s）" % m[4] if m[4] else "") for m in dead[:3])
    if omitted:
        return "> 已省略 %d 条已作废事实：%s —— 要查历史请说明「以前 / 历史 / 作废」\n\n" % (
            len(dead), ids)
    return "> 已作废：%s —— 以下内容仅作历史参考，不是当前配置。\n\n" % ids


def relevant(hits) -> bool:
    """P4 入场券：≥2 个关键词，或 1 个足够长的独特词。

    「固件」这种两字词命中满库都是，不该拿来做 P4 的相关性证据。
    """
    return len(hits) >= P4_MIN_TERMS or (len(hits) == 1 and len(hits[0]) >= 4)


def p4_candidates(root: Path, terms, used_sources: set, used_section_keys: set,
                  include_archive: bool, loose: bool, max_blocks=P4_MAX_BLOCKS,
                  fact_defs=None, allow_deprecated: bool = False):
    """受控 P4：只补「确实相关」的少量章节。

    约束（全部硬性）：
      - 最多 max_blocks 块
      - 至少命中 P4_MIN_TERMS 个不同关键词，否则不补（返回 0 块是正确结果）
      - 归档默认不参与；流水/归档按权重降序靠后
      - 已经被 P0–P3 用过的文件/章节不重复加入
      - **含已作废事实的章节**：默认把作废定义占的行置空（与 kb-search 同一口径），
        同节仍然有效的内容保留并注明「已省略 N 条」；整节相关性全来自作废内容
        （或标题行本身就是那条作废定义）时整节跳过并记进 dropped。
        任务在问「历史/以前/作废」或显式 --include-superseded 时才原样带回，
        并在正文前标注「已作废」。

    返回 (rows, dropped)：dropped 是被整节过滤掉的章节说明（只收「因作废而丢」的）。
    """
    dropped = []
    if not terms:
        return [], dropped
    marks_by_file = fact_marks(fact_defs)
    rows = []
    containers = []
    for p, reason in scope.iter_text_files(root, include_archive=include_archive):
        if reason:
            continue
        rel = p.relative_to(root).as_posix()
        if rel in used_sources:
            continue
        role = scope.role_of_path(root, p, loose=loose)
        # 权重阶梯：结构内的正文 1.0；流水/分片 0.4；归档 0.3；
        # 其余一律 0.5。`other` 曾经也是 1.0，但它装的是 AGENTS.md、一次性
        # 发布稿、检索记录、覆盖率矩阵这类东西——不是知识库结构内的正文。
        # 真实库里 `检索记录_….md` 有 62 KB，任务问什么都可能从里面命中几个词，
        # 凭体积压过分册条目；P4 只有 3 个名额，抢一次就少一条真结论。
        weight = (0.4 if role in ("log", "shard")
                  else 0.3 if role == "archive" else 0.5 if role == "other" else 1.0)
        try:
            doc = md.parse_file(p)
        except Exception:
            continue
        # `--loose` 下「编号是两位数字」就足以被判成 fact，但编号不证明里面是事实：
        # `20_会议记录.md` / `40_临时测试.md` 这类东西给 1.0 权重就会跟真分册抢名额。
        # 没有事实结构的按 0.5（仍可被检索到，只是不占最高档），并在 reason 里写明。
        fact_kind = "structured"
        if role == "fact" and loose and facts.is_custom_fact_name(p.name):
            fact_kind = facts.fact_confidence(p, loose=loose, doc=doc)
            if fact_kind == "candidate":
                weight = 0.5
                role = "fact-candidate"
        marks = marks_by_file.get(rel) or []
        for sec in doc.sections:
            key = (rel, sec.id or sec.line)
            if key in used_section_keys:
                continue
            raw_body = "\n".join(doc.lines[sec.start:sec.stop])
            # markdown 的 section 是「到下一个同级标题为止」，所以父节天然把
            # 所有子节都算进 body。用它打分等于让父节靠子节内容刷分：父节
            # 命中数必 ≥ 子节，永远排前面，装进来的却是整棵子树。
            # 打分与「空壳」判定只认**本节自有正文**（标题到下一个任意级标题），
            # 输出也默认只给自有正文——子节会各自成为候选，重复输出没有意义。
            own_stop = sec.stop
            for nxt in doc.sections[sec.n:]:
                if nxt.line > sec.line:
                    own_stop = min(own_stop, nxt.line - 1)
                    break
            own_body = "\n".join(doc.lines[sec.start:own_stop])
            found = section_marks(marks, sec)
            dead = [m for m in found if m[3] == "deprecated"]

            if not own_body.strip():
                # 只有标题、正文全在子节里的容器节。
                if dead:
                    # 子树里有作废事实：这一节唯一能表达的是「这里有过旧值」。
                    # 默认只给一句指针（几十 token），子树交给子节各自竞争；
                    # 明确在问历史时整棵子树原样带回并标注。
                    hits = [t for t in terms
                            if t.lower() in ((sec.title or "") + "\n" + raw_body).lower()]
                    if not relevant(hits):
                        continue
                    if allow_deprecated:
                        rows.append({
                            "score": len(hits) * weight, "file": rel,
                            "section_id": sec.id, "heading": sec.title,
                            "line": sec.line, "line_start": sec.line,
                            "line_end": sec.end, "range": "subtree",
                            "level": sec.level, "subtree_end": sec.end,
                            "text": dead_note(dead)
                                    + ((sec.title or "") + "\n" + raw_body).strip(),
                            "hits": hits, "role": role,
                            "deprecated": [{"id": m[2], "superseded_by": m[4]}
                                           for m in dead]})
                    else:
                        rows.append({
                            "score": len(hits) * weight, "file": rel,
                            "section_id": sec.id, "heading": sec.title,
                            "line": sec.line, "line_start": sec.line,
                            "line_end": sec.line, "range": "note",
                            "level": sec.level, "subtree_end": sec.end,
                            "text": dead_note(dead, omitted=True).strip(),
                            "hits": hits, "role": role,
                            "deprecated": [{"id": m[2], "superseded_by": m[4]}
                                           for m in dead]})
                    continue
                # 其余容器节先记下来，等本文件的子节都判完再决定要不要兜底：
                # 1–2 KB 的小分册常常是「h1 只是名字、内容全在 h2」，子节
                # 各自只命中一个词、够不上「≥2 个关键词」，整条线会全军覆没。
                containers.append({"rel": rel, "sec": sec, "raw": raw_body,
                                   "weight": weight, "id": sec.id})
                continue

            score_text = (sec.title or "") + "\n" + own_body
            hits = [t for t in terms if t.lower() in score_text.lower()]
            # 相关性先按「原样内容」判：本节确实在讲任务问的东西，
            # 才有资格进 dropped 报告；否则只是无关章节，不该拿来充数。
            if not relevant(hits):
                continue

            # h1 降权而不是排除。早先无条件跳过首个 h1：它装的是「本文件讲什么」
            # 和适用版本，主题词最全，按命中数排序必占前三。但
            # `# 当前系统状态` 这种 h1 本身可能就是最重要的那段话 ——
            # 只凭「它是 h1」丢掉是错的。降权之后更具体的子节自然排在前面。
            sec_weight = weight
            if sec.n == 1 and sec.level == 1 and len(doc.sections) > 1:
                meta = any(h in own_body for h in H1_META_HINTS)
                sec_weight = weight * (H1_META_WEIGHT if meta else H1_WEIGHT)

            body_lines = list(doc.lines[sec.start:own_stop])
            if dead and not allow_deprecated:
                # 置空作废定义占的行（保留行号），而不是整节丢弃：
                # 同一节里往往还夹着仍然有效的当前值。
                for m in dead:
                    for ln in range(max(sec.line + 1, m[0]), min(own_stop, m[1]) + 1):
                        body_lines[ln - 1 - sec.start] = ""
            body = "\n".join(body_lines)
            text = (sec.title or "") + "\n" + body
            if dead and not allow_deprecated:
                # 作废定义被置空后，本节如果不再命中就不该留下：
                # 「原文里有这个词」不能作为保留作废内容的理由。
                hits = [t for t in hits if t.lower() in text.lower()]
                # 标题行即那条作废定义、置空后什么都不剩、或者剩下的内容
                # 已经和任务无关 —— 三种情况都不该把这一节塞进上下文。
                own_dead = [m for m in dead if m[0] == sec.line]
                if own_dead or not body.strip() or not relevant(hits):
                    dropped.append("%s:%d %s（%s）" % (
                        rel, sec.line, sec.title or "（无标题）",
                        "、".join(m[2] for m in dead[:3])))
                    continue
                text = dead_note(dead, omitted=True) + text.strip()
            else:
                text = text.strip()
                if dead:
                    text = dead_note(dead) + text
            row = {"score": len(hits) * sec_weight, "file": rel,
                   "section_id": sec.id, "heading": sec.title, "line": sec.line,
                   "line_start": sec.line, "line_end": own_stop, "range": "own",
                   "level": sec.level, "subtree_end": sec.end,
                   "text": text, "hits": hits, "role": role}
            if dead:
                row["deprecated"] = [{"id": m[2], "superseded_by": m[4]} for m in dead]
            rows.append(row)

    # 容器节兜底：子树里一个够格的节都没有时，才允许把整节端上来——前提是
    # 整节不大（<= CONTAINER_MAX_TOKENS）。这样 1–2 KB 的小分册不会因为
    # 「h1 只是名字、每节只命中一个词」而整条线落空；而 60 KB 的分册 h1
    # 依然进不来（装整棵子树太贵，它本来也不该靠标题抢名额）。
    for c in containers:
        sec = c["sec"]
        if any(r["file"] == c["rel"] and sec.line < r["line"] <= sec.stop for r in rows):
            continue
        if tokens.heuristic(c["raw"]) > CONTAINER_MAX_TOKENS:
            continue
        hits = [t for t in terms if t.lower() in ((sec.title or "") + "\n" + c["raw"]).lower()]
        if not relevant(hits):
            continue
        rows.append({"score": len(hits) * c["weight"], "file": c["rel"],
                     "section_id": c["id"], "heading": sec.title, "line": sec.line,
                     "line_start": sec.line, "line_end": sec.end, "range": "subtree",
                     "level": sec.level, "subtree_end": sec.end,
                     "text": ((sec.title or "") + "\n" + c["raw"]).strip(),
                     "hits": hits, "role": scope.role_of_path(root, root / c["rel"],
                                                             loose=loose)})
    rows.sort(key=lambda r: (-r["score"], r["file"], r["line"]))
    rows = drop_redundant_h1(rows)
    rows = drop_overlaps(rows)
    return rows[:max_blocks], dropped


def drop_redundant_h1(rows):
    """h1 与它的子节同时入选、且子节没带来新关键词时，丢掉 h1。

    `# 30 · 固件刷机总纲` 这类导语装着整份分册的主题词，按命中数排永远靠前；
    降权之后如果仍与某个子节并列，说明它没有提供子节之外的任何关键词 ——
    留着只是把同一批词再说一遍。反过来，h1 有子节没覆盖的词（比如
    `# 当前系统状态` 里那句「参数 YY 已禁止」）时照样保留。
    只对 level==1 生效：更深的父节有自己的正文，不该被这条规则波及。
    """
    out = []
    for r in rows:
        if r.get("level") == 1:
            kids = [k for k in rows
                    if k is not r and k["file"] == r["file"]
                    and r["line"] < k["line"] <= r.get("subtree_end", r["line_end"])]
            if any(set(k["hits"]) <= set(r["hits"]) for k in kids):
                continue
        out.append(r)
    return out


def drop_overlaps(rows):
    """同一个文件里，被更靠前（更相关）的块完全覆盖的章节不再重复输出。

    `rows` 已按分数降序。父节与子节的正文范围天然相交：父节默认只渲染自有
    正文（不与子节重叠），但容器兜底会整棵子树端上来 —— 那种情况下再装一遍
    子节就是同一段文字出现两次。只按行号范围判，同名标题不会被误合并。
    """
    kept = []
    for r in rows:
        covered = any(k["file"] == r["file"]
                      and k["line_start"] <= r["line_start"]
                      and r["line_end"] <= k["line_end"] for k in kept)
        if covered:
            continue
        kept = [k for k in kept
                if not (k["file"] == r["file"]
                        and r["line_start"] <= k["line_start"]
                        and k["line_end"] <= r["line_end"])]
        kept.append(r)
    return kept


def build(root: Path, files, task: str, line_spec, include_archive: bool,
          counter, budget: int = 3000, loose: bool = False,
          include_superseded: bool = False):
    terms = parse_terms(task)
    blocks, gaps = [], []
    selected_lines, omitted_lines = [], []
    dash_p = files.get("dashboard", [None])[0]
    dash = md.parse_file(dash_p) if dash_p else None

    def add(priority, title, source, sid, text, reason, required=False, line=None,
            source_path=None, line_start=None, line_end=None, role=None):
        item = {"priority": priority, "title": title, "source": source,
                "source_path": source_path or source, "section_id": sid,
                "text": text, "reason": reason, "required": required,
                "line": line, "line_start": line_start, "line_end": line_end}
        # role 只给 P4 用（fact / fact-candidate / log / archive / other）：
        # main() 要按它判断「这条是事实节补充」还是「普通相关段落」。
        if role:
            item["role"] = role
        blocks.append(item)

    # P0 硬约束：dashboard 的 kb:id → AGENTS 的「硬约束」段 → 都没有才报缺口。
    # 三级兜底与「什么算有效内容」由 lib/constraints 统一判定（kb-check 同源），
    # 否则同一个库会一边注入成功、一边报「缺少 dashboard.constraints」。
    p0 = constraints.resolve(root, dash, dash_p, rel_of(root, dash_p))
    if p0["ok"]:
        b = p0["block"]
        add("P0", b["title"], b["path"], b.get("section_id"), b["text"],
            "任何预算下必读；来源：%s" % p0["detail"], required=True,
            source_path=b.get("rel"), line_start=b.get("line"))
    else:
        gaps.append(p0["gap"])

    # P1 现状 + 下一手
    if dash:
        for sid, title in (("dashboard.current", "现状"), ("dashboard.next", "下一手")):
            sec, text = section_text(dash, sid, False)
            if text and text.strip():
                add("P1", title, dash_p.name, sid, text,
                    "接手必读；决定本次任务从哪开始", required=True,
                    source_path=rel_of(root, dash_p), line_start=sec.line)
            else:
                gaps.append("缺少 kb:id: %s" % sid)
        if not any(b["priority"] == "P1" for b in blocks):
            head = "\n".join(dash.lines[:40]).strip()
            if head:
                add("P1", "现状（无 kb:id 兜底）", dash_p.name, None, head,
                    "05 尚未加 kb:id，取前 40 行；跑 kb-migrate.py 可精确到节",
                    required=True, source_path=rel_of(root, dash_p))

    # P2 工作线事实（可多条）
    fact_paths, why, missing_lines, candidate_lines = find_line_facts(
        root, files, line_spec, terms, task, loose)
    if not fact_paths and terms:
        gaps.append(why if "不存在" in why or "没有" in why else
                    "任务没有命中任何事实分册（用 kb-search.py 再定位）")
    if missing_lines:
        # 显式点了名就必须逐条交代：不能让「另一条线命中了」把缺失盖过去
        gaps.append("--line 指定的工作线不存在：%s（可选：%s）"
                    % ("、".join("「%s」" % m for m in missing_lines),
                       "、".join(line_name(p) for p in files.get("fact", []))))
    if candidate_lines:
        gaps.append("按候选线处理（只有编号、没发现结构化事实条目）：%s —— "
                    "仍可检索，但权重低于真分册"
                    % "、".join(line_name(p) for p in candidate_lines))
    want_verify = any(k in (task or "") for k in TASK_VERBS_VERIFY)
    want_trouble = any(k in (task or "") for k in TASK_VERBS_TROUBLE)
    per_line_blocks = []
    for p in fact_paths:
        fdoc = md.parse_file(p)
        name = line_name(p)
        prel = rel_of(root, p)
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
            add("P2", title, source, sid, text, reason, required=False, line=name,
                source_path=prel)
        per_line_blocks.append((name, items))

    # P3 任务点名的事实（G/K）+ 基线命中 + 证据 + 交叉链
    fact_defs, fact_problems = facts.parse_fact_definitions(
        root, include_archive=include_archive, loose=loose)
    if fact_problems:
        gaps.append("事实解析有 %d 个问题（首条：%s）——这些事实的状况未知"
                    % (len(fact_problems), fact_problems[0]))
    asked = sorted({m.upper() for m in TASK_ID_RE.findall(task or "")})
    asked_ok = []
    for fid in asked:
        items = facts.canonical(fact_defs.get(fid) or [])
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
            add("P3", "任务点名的事实 %s" % fid, Path(d.path).name, None, text,
                "%s 的定义位（%s，状态 %s）" % (fid, d.definition_type, d.status),
                source_path=d.path, line_start=d.line_start,
                line_end=d.line_end)
            asked_ok.append(fid)
        if len(live) > 1:
            # 索引页指针不算「多处定义」——那只是导航，合并它没有意义
            real = [x for x in live if not x.pointer]
            if len(real) > 1:
                gaps.append("%s 有 %d 处定义（%s）：已取第一处，建议合并"
                            % (fid, len(real),
                               "、".join("%s:%d" % (x.path, x.line_start)
                                        for x in real[:3])))
    base_p = files.get("baseline", [None])[0]
    if base_p and terms:
        bdoc = md.parse_file(base_p)
        header, rows = table_rows_matching(bdoc, terms)
        if rows:
            text = "\n".join([header] + [r[1] for r in rows])
            add("P3", "基线命中 %d 行" % len(rows), base_p.name, "baseline.facts", text,
                "任务关键词命中基线表：%s" % ", ".join(terms[:4]),
                source_path=rel_of(root, base_p))
            ev = []
            for _, row in rows:
                cells = split_row(row)
                if len(cells) >= 5 and cells[4] and cells[4] not in ("—", "-"):
                    ev.append("%s ← %s" % (cells[0], cells[4]))
            if ev:
                add("P3", "证据指针", base_p.name, "baseline.facts",
                    "\n".join("- " + e for e in ev),
                    "完成项必须有可追溯证据，否则只能算待核",
                    source_path=rel_of(root, base_p))
        else:
            gaps.append("基线表没有命中；结论可能需要新建 K-xx")

        cross = (len(fact_paths) >= 2
                 or any(k in (task or "") for k in TASK_VERBS_CROSS))
        if cross and md.find_by_id(bdoc, "baseline.chains"):
            _, text = section_text(bdoc, "baseline.chains", False)
            if text and text.strip():
                add("P3", "交叉链（改 A 波及 B）", base_p.name, "baseline.chains", text,
                    "任务涉及跨线影响：先看交叉链再动手",
                    source_path=rel_of(root, base_p))

    # P4 受控补充：数量、预算占比、相关性阈值三者同时生效
    # 去重键是**归一化相对路径**（source_path），不是文件名：同一个库里
    # `归档/M-013_实测过程.md` 与根目录同名文件并存时，按文件名比对会漏判成
    # 「没用过」，同一份内容被 P3 与 P4 各装一遍。
    used_sources = {b["source_path"] for b in blocks if b.get("source_path")}
    # 任务点名事实所在的文件整份不参与 P4：那条事实已经由 P3 按状态处理过，
    # 再从全文捞一遍会把「已作废」的内容当补充材料塞回上下文。
    for fid in asked:
        for d in fact_defs.get(fid, []):
            used_sources.add(d.path)
    used_keys = {(b["source_path"], b["section_id"])
                 for b in blocks if b["section_id"] and b.get("source_path")}
    # 事实 ID 不作为 P4 关键词：ID 的查找有专门路径（含状态判定），
    # 交给全文匹配只会在整个文件里乱捞。
    p4_terms = [t for t in terms if not TASK_ID_RE.fullmatch(t)]
    p4, p4_dropped = p4_candidates(root, p4_terms, used_sources, used_keys,
                                   include_archive, loose,
                                   fact_defs=fact_defs,
                                   allow_deprecated=(include_superseded
                                                     or wants_history(task)))
    p4_cap = int(budget * P4_BUDGET_SHARE)
    picked, used_tokens, seen_text = [], 0, set()
    for row in p4:
        # 同一段文字换个路径再来一次（两份内容相同的软链、复制件）不再装第二遍
        digest = hashlib.sha256(row["text"].encode("utf-8", "replace")).hexdigest()
        if digest in seen_text:
            continue
        n = counter.count(row["text"])
        if used_tokens + n > p4_cap:
            continue
        seen_text.add(digest)
        used_tokens += n
        picked.append(row)
    for row in picked:
        title = "相关补充 · %s" % (row["heading"] or row["file"])
        reason = ("关键词命中 %s（%s，权重 %.1f）"
                  % ("、".join(row["hits"][:3]), row["role"],
                     row["score"] / max(1, len(row["hits"]))))
        if row.get("deprecated"):
            title += "（含已作废事实）"
            reason += "；含已作废事实 %s，已标注为历史参考" % "、".join(
                d["id"] for d in row["deprecated"][:3])
        add("P4", title, Path(row["file"]).name, row["section_id"], row["text"], reason,
            source_path=row["file"], line_start=row.get("line_start"),
            line_end=row.get("line_end"), role=row["role"])

    # P2 是按「工作线名」命中的：问「机械冲撞」时任务里没有「游戏事实」四个字，
    # 于是 P2 空、报一条缺口；P4 随后按内容把 G-001 补了进来，那条缺口就该撤回。
    # 但「补进来一条相关事实」不等于「这条工作线已完整加载」——所以撤回之后要
    # 换上一条说清楚边界的说明，不能让人以为接手完成。
    fact_picked = [r for r in picked if r["role"] in ("fact", "fact-candidate")]
    if fact_picked:
        # 这里只撤回「没命中」的旧结论；「到底装进去了没有」由 main 在最终装配后写
        # ——此处的 picked 还没经过预算裁剪，先写「已补入」会把被挤掉的块说成已加载。
        gaps[:] = [g for g in gaps if not g.startswith("任务没有命中任何事实分册")]
    if p4_dropped:
        gaps.append("P4 排除了 %d 个只含已作废事实的章节（%s）；"
                    "要查历史请在任务里说明「以前 / 历史 / 作废」"
                    % (len(p4_dropped), "；".join(p4_dropped[:2])))
    if not picked and terms and not fact_paths:
        if asked_ok:
            # 点名事实走的是 P3 的 ID 路径，不是 P2/P4：说「没命中任何事实分册」
            # 会让人以为库里没有相关内容，而实际上定义位已经给了。
            gaps[:] = [g for g in gaps
                       if not g.startswith("任务没有命中任何事实分册")
                       and not g.startswith("P2 未命中任何工作线")]
            gaps.append("P2/P4 没有按工作线装载：已按点名的 %s 给出定义位（P3），"
                        "该工作线的其余内容未加载；要整线用 --line <线名>"
                        % "、".join(asked_ok))
        else:
            gaps.append("P2 未命中任何工作线，P4 也没有足够相关内容（阈值 ≥%d 个关键词）；"
                        "0 块是正常结果，但不代表库里没有——先用 kb-search.py 定位"
                        % P4_MIN_TERMS)

    return {"blocks": blocks, "per_line": per_line_blocks, "gaps": gaps,
            "terms": terms, "fact_paths": fact_paths, "why": why,
            "selected_lines": [line_name(p) for p in fact_paths],
            "p4": {"count": len(picked), "tokens": used_tokens, "cap": p4_cap,
                   "candidates": len(p4), "deprecated_skipped": len(p4_dropped),
                   "fact_candidates": len(fact_picked)},
            "missing_lines": missing_lines, "candidate_lines": candidate_lines,
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
    ap.add_argument("--include-superseded", action="store_true",
                    help="P4 允许带回已作废章节（仍会标注「已作废」，不会冒充当前配置）")
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
                  counter, args.budget, args.loose, args.include_superseded)
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
    added = False
    for name in omitted:
        built["gaps"].append(
            "工作线「%s」的相关事实未加载（预算 %d 已满）；用 --line %s 单独取，或提高 --budget"
            % (name, args.budget, name))
        added = True
    for name in empty:
        built["gaps"].append(
            "工作线「%s」里没有 fact.current / commands / pitfalls 可加载的事实节" % name)
        added = True
    # 显式 --line 时逐条交代：指定的每条线都必须有结论，不能因为「另一条命中了」
    # 或者「P4 补到一条相关内容」就让某条线的缺口消失。
    if line_spec:
        status = ["%s 已加载" % n for n in loaded]
        status += ["%s 该线没有可加载的 fact.* 事节" % n for n in empty]
        status += ["%s 未加载（预算不足）" % n for n in omitted]
        status += ["%s 不存在" % n for n in (built.get("missing_lines") or [])]
        if status:
            built["gaps"].append("--line 逐条结果：" + "；".join(status))
            added = True
    # P4 按关键词补进上下文的东西：build() 撤回了「没命中事实分册」，但「补进一节」
    # 不等于「这条工作线已完整接手」。按最终装配结果再交代一次边界，被预算挤掉的
    # 单独说明是「命中但没装下」，不能两种情形都说成「已补入」。
    # 真事实分册与「编号像分册的普通文档」要分开说：后者按 0.5 权重取用，
    # 把会议记录叫成「事实节」会让读者以为那是核对过的事实。
    p4_facts = [b for b in kept
                if b["priority"] == "P4" and b.get("role") == "fact"]
    p4_cands = [b for b in kept
                if b["priority"] == "P4" and b.get("role") == "fact-candidate"]

    def names_of(rows):
        out = []
        for b in rows:
            n = line_name(Path(b["source_path"] or b["source"]))
            if n and n not in out:
                out.append(n)
        return "、".join("「%s」" % n for n in out)

    if p4_facts:
        built["gaps"].append(
            "P4 只补入 %d 个事实节%s：节级补充，不等于该工作线已完整加载；整线用 --line"
            % (len(p4_facts), "（%s）" % names_of(p4_facts) if names_of(p4_facts) else ""))
        added = True
    if p4_cands:
        built["gaps"].append(
            "P4 从候选分册补入 %d 节%s（权重 0.5）：只有编号、没有事实条目，当线索读"
            % (len(p4_cands), "（%s）" % names_of(p4_cands) if names_of(p4_cands) else ""))
        added = True
    if not p4_facts and not p4_cands and built["p4"].get("fact_candidates"):
        # 两种挤掉法要分开说：P4 自身占比不够 vs 总预算装不下。
        why_ = ("已选中但总预算装不下" if built["p4"]["count"]
                else "超过 P4 预算占比")
        built["gaps"].append(
            "P4 命中 %d 个事实节但%s，一个也没进上下文；用 --line 单独取或提高 --budget"
            % (built["p4"]["fact_candidates"], why_))
        added = True
    if added:
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
        # p4_facts 只收「真事实分册」的节；候选分册（只有编号、没有事实结构）
        # 单列一个字段，消费方不必去猜哪条是核实过的。
        "p4_facts": [{"title": b["title"], "source_path": b["source_path"],
                      "section_id": b["section_id"]} for b in p4_facts],
        "p4_candidates": [{"title": b["title"], "source_path": b["source_path"],
                           "section_id": b["section_id"]} for b in p4_cands],
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
