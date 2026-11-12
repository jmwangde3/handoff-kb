#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-search.py — 轻量全文检索（无 SQLite、无服务、无 embedding）

扫描工作区文本文件（默认排除归档与资料目录），按稳定章节切块打分：
事实定义位 > 文件名/工作线 > 标题 > 正文；流水与归档降权，已作废定义默认排除。

2.0.1-hotfix 的三处统一：
  1. 事实识别走 `lib/facts.py`，标题首 / 列表首 / 表格首列三种定义位同权；
     不再为表格单独写一条正则，于是 `## G-010` 与 `| K-02 |` 的精确搜索同分。
  2. 作废判定按 `status`（规范化的 valid/pending/deprecated/unknown），
     不是「这一行里有没有『已作废』四个字」；被排除的定义会进 `superseded` 列表，
     并尽可能给出替代 ID，避免用户以为「查不到 = 不存在」。
  3. 角色判定按**相对路径**（`06_流水/x.md` 是 shard），不再只看 `path.name`。

只返回定位信息 + 160 字摘要，正文另用 kb-outline.py 按节读。

用法：
  py kb-search.py --target . --query "NSS 网络问题" --limit 5
  py kb-search.py --target . --query "K-07" --json
  py kb-search.py --target . --query 备份 --line 固件 --include-archive
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

SNIPPET = 160
FACT_ID_ONLY = re.compile(r"^[KG]-\d{2,3}$", re.I)


def parse_query(q: str):
    return terms_lib.parse(q)


def blank_deprecated(doc, defs, include_superseded: bool) -> list[str]:
    """把作废定义的行置空（保留行号），返回新行列表。

    置空而不是「跳过整节」：一个当前有效的章节里可能夹着一条已作废的旧行，
    删整节会把同节仍然有效的事实一起弄丢。
    """
    lines = list(doc.lines)
    if include_superseded:
        return lines
    for d in defs:
        if d.status != "deprecated":
            continue
        for i in range(max(1, d.line_start), min(len(lines), d.line_end) + 1):
            lines[i - 1] = ""
    return lines


def score_block(title: str, body: str, terms, fname: str, line_name: str,
                fact_ids: set):
    """返回 (score, reasons, matched_terms)。`fact_ids` 是本块内定义的事实 ID。"""
    score, reasons, matched = 0, [], []
    body_l = body.lower()
    fname_l, title_l = fname.lower(), (title or "").lower()
    for t in terms:
        tl = t.lower()
        if FACT_ID_ONLY.fullmatch(t) and t.upper() in fact_ids:
            # 三种定义位都由 facts.parse_document 判定，这里只认「定义」不认「引用」
            score += 1000
            reasons.append("事实定义位命中 %s" % t.upper())
            matched.append(t)
            continue
        if tl and tl in fname_l:
            score += 300
            reasons.append("文件名命中 %s" % t)
            matched.append(t)
        if line_name and tl in line_name.lower():
            score += 250
            reasons.append("工作线命中 %s" % t)
            matched.append(t)
        if tl and tl in title_l:
            score += 200
            reasons.append("标题命中 %s" % t)
            matched.append(t)
        if tl and tl in body_l:
            n = body_l.count(tl)
            score += min(60 * n, 240)
            reasons.append("正文命中 %s×%d" % (t, n))
            matched.append(t)
    return score, reasons, sorted(set(matched))


def snippet_for(body: str, terms, limit: int = SNIPPET):
    lines = body.splitlines()
    for t in terms:
        tl = t.lower()
        for ln in lines:
            if tl and tl in ln.lower():
                s = ln.strip()
                return s[:limit] + ("…" if len(s) > limit else "")
    for ln in lines:
        if ln.strip() and not ln.strip().startswith("|") and not ln.strip().startswith("<!--"):
            return ln.strip()[:limit]
    return ""


def meaningful(text: str) -> bool:
    """只有注释/空行/分隔线的块不算正文，避免把 schema 注释当命中。"""
    for ln in text.splitlines():
        s = ln.strip()
        if s and not s.startswith("<!--") and not set(s) <= set("-|: "):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="轻量全文检索（章节级打分）")
    ap.add_argument("--target", default=".")
    ap.add_argument("--query", required=True)
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--line", default=None, help="只看某条工作线（文件/分片名）")
    ap.add_argument("--include-archive", action="store_true")
    ap.add_argument("--include-superseded", action="store_true", help="包含已作废事实")
    ap.add_argument("--loose", action="store_true",
                    help="按别名识别固定层（自有命名项目，如 60_进度.md）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        root = scope.resolve_root(args.target)
    except scope.ScopeError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 2

    terms = parse_query(args.query)
    if not terms:
        print("ERR: --query 为空", file=sys.stderr)
        return 2

    hits, errors, superseded, scanned = [], [], [], 0
    audit = []
    for path, reason in scope.iter_text_files(root, include_archive=args.include_archive,
                                              audit=audit):
        if reason:
            continue
        rel = path.relative_to(root).as_posix()
        role = scope.role_of_path(root, path, loose=args.loose)
        # 根级归档（90_*.md）、归档目录、归档别名目录：默认都不搜
        if role == "archive" and not args.include_archive:
            continue
        scanned += 1
        try:
            doc = md.parse_file(path)
        except Exception as exc:
            errors.append((rel, str(exc)))
            continue
        try:
            defs, _ = facts.parse_document(path, rel)
        except Exception as exc:
            errors.append((rel, "事实解析失败：%s" % exc))
            defs = []
        lines = blank_deprecated(doc, defs, args.include_superseded)
        by_line = {d.line_start: d for d in defs}

        line_name = (path.stem.split("_", 1)[1] if "_" in path.stem else path.stem) \
            if role in ("fact", "shard") else ""
        if args.line and args.line.lower() not in (rel + " " + line_name).lower():
            continue
        weight = 1.0
        if role in ("log", "shard"):
            weight = 0.4
        elif role == "archive":
            weight = 0.3

        def emit(title, sid, line_no, start, end):
            body = "\n".join(lines[start:end])
            # 索引页里的条目是「指向」，不给定义位满分——否则搜 G-004 会先命中
            # 00_INDEX.md 上的导航行，而不是 10_xx.md 里的正式定义。
            fact_ids = {d.id.upper() for d in defs
                        if start < d.line_start <= end and not d.pointer}
            if not body.strip() and not (args.include_superseded and fact_ids):
                return
            sc, rs, mt = score_block(title, body, terms, path.name, line_name, fact_ids)
            if not sc:
                return
            d = by_line.get(line_no)
            hits.append({"file": rel, "section_id": sid, "heading": title,
                         "line": line_no, "score": round(sc * weight, 1),
                         "matched": mt, "reasons": rs,
                         "role": role,
                         "fact_id": d.id if d else None,
                         "status": d.status if d else None,
                         "superseded_by": (d.superseded_by or None) if d else None,
                         "snippet": snippet_for(body, terms),
                         "sha256_12": doc.sha256_file[:12],
                         "tokens": tokens.estimate(body)[0]})

        # 前言（第一个标题之前）
        pre_end = doc.sections[0].line - 1 if doc.sections else len(doc.lines)
        pre_body = "\n".join(lines[:pre_end])
        if pre_body.strip() and meaningful(pre_body):
            emit(Path(path).name, None, 1, 0, pre_end)

        for sec in doc.sections:
            emit(sec.title, sec.id, sec.line, sec.start, sec.stop)

        # 被排除的作废定义：显式列出来，别让「查不到」等于「不存在」
        if not args.include_superseded:
            wanted = {t.upper() for t in terms if FACT_ID_ONLY.fullmatch(t)}
            for d in defs:
                if d.status != "deprecated":
                    continue
                if wanted and d.id.upper() not in wanted:
                    continue
                superseded.append({"file": rel, "line": d.line_start, "fact_id": d.id,
                                   "superseded_by": d.superseded_by or None,
                                   "message": "%s 已作废%s，默认不返回其内容"
                                              % (d.id, "，替代事实 %s" % d.superseded_by
                                                 if d.superseded_by else "（未写替代 ID）")})

    hits.sort(key=lambda h: (-h["score"], h["file"], h["line"]))
    hits = hits[:max(1, args.limit)]

    if args.json:
        print(json.dumps({"query": args.query, "terms": terms, "scanned": scanned,
                          "hits": hits, "superseded": superseded,
                          "skipped_paths": [{"path": a, "reason": b, "detail": c}
                                            for a, b, c in audit],
                          "errors": [{"file": a, "error": b} for a, b in errors]},
                         ensure_ascii=False, indent=2))
    else:
        if not hits:
            print("未命中：%s" % args.query)
            print("-- 已扫描 %d 个文本文件；试更短的关键词，或 --include-archive" % scanned)
        for h in hits:
            tag = ""
            if h["status"] == "deprecated":
                tag = "  [已作废%s]" % (" → %s" % h["superseded_by"]
                                        if h["superseded_by"] else "")
            print("== %.0f 分  %s  L%s%s%s"
                  % (h["score"], h["file"], h["line"],
                     "  [%s]" % h["section_id"] if h["section_id"] else "", tag))
            print("   %s" % h["heading"])
            print("   %s" % h["snippet"])
            print("   hash=%s  ≈%d tokens  命中：%s"
                  % (h["sha256_12"], h["tokens"], ", ".join(h["reasons"][:4])))
        for s in superseded[:3]:
            print("\n! %s" % s["message"])
        if audit:
            print("\n跳过 %d 个越界路径（示例：%s）" % (len(audit), audit[0][0]))
        if errors:
            print("\n无法解析 %d 个文件：%s" % (len(errors), errors[0][0]))
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())
