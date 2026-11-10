#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-search.py — 轻量全文检索（无 SQLite、无服务、无 embedding）

扫描工作区文本文件（默认排除归档与资料目录），按稳定章节切块打分：
精确 ID > 文件名/线 > 标题 > 正文；历史流水降权，已作废事实默认排除。
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

from lib import markdown as md  # noqa: E402
from lib import protocol, scope, terms as terms_lib, tokens  # noqa: E402

SNIPPET = 160


def parse_query(q: str):
    return terms_lib.parse(q)


def score_section(sec, body: str, terms, fname: str, line_name: str,
                  include_superseded: bool = False):
    """返回 (score, reasons, matched_terms)。

    已作废的行默认不参与打分（同节里其它行照常命中），ID 行命中给最高权重。
    """
    score, reasons, matched = 0, [], []
    lines = [ln for ln in body.splitlines()
             if include_superseded or "已作废" not in ln]
    body_l = "\n".join(lines).lower()
    fname_l, title_l = fname.lower(), (sec.title or "").lower()
    sid = (sec.id or "").lower()
    for t in terms:
        tl = t.lower()
        if sid and sid == tl:
            score += 1000
            reasons.append("ID 精确命中 %s" % t)
            matched.append(t)
        if re.fullmatch(r"[KG]-\d{2,3}", t, re.I) and any(
                re.match(r"^\s*\|\s*%s\s*\|" % re.escape(t), ln, re.I) for ln in lines):
            score += 1000
            reasons.append("事实 ID 行命中 %s" % t)
            matched.append(t)
        if tl in fname_l:
            score += 300
            reasons.append("文件名命中 %s" % t)
            matched.append(t)
        if line_name and tl in line_name.lower():
            score += 250
            reasons.append("工作线命中 %s" % t)
            matched.append(t)
        if tl in title_l:
            score += 200
            reasons.append("标题命中 %s" % t)
            matched.append(t)
        if tl in body_l:
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
            if tl in ln.lower():
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

    hits, errors, scanned = [], [], 0
    for path, reason in scope.iter_text_files(root, include_archive=args.include_archive):
        if reason:
            continue
        scanned += 1
        try:
            doc = md.parse_file(path)
        except Exception as exc:
            errors.append((str(path), str(exc)))
            continue
        rel = path.relative_to(root).as_posix()
        role = protocol.role_of_name(path.name)
        line_name = (path.stem.split("_", 1)[1] if "_" in path.stem else path.stem) \
            if role in ("fact", "shard") else ""
        if args.line and args.line.lower() not in (rel + " " + line_name).lower():
            continue
        weight = 1.0
        if role in ("log", "shard"):
            weight = 0.4
        elif role == "archive":
            weight = 0.3

        # 前言（第一个标题之前）
        pre_end = doc.sections[0].line - 1 if doc.sections else len(doc.lines)
        pre_body = "\n".join(doc.lines[:pre_end])
        if pre_body.strip() and meaningful(pre_body):
            pseudo = md.Section(n=0, level=0, title=Path(path).name, line=1,
                                end=pre_end, start=0, stop=pre_end, id=None)
            sc, rs, mt = score_section(pseudo, pre_body, terms, path.name, line_name)
            if sc:
                hits.append({"file": rel, "section_id": None, "heading": Path(path).name,
                             "line": 1, "score": round(sc * weight, 1),
                             "matched": mt, "reasons": rs,
                             "snippet": snippet_for(pre_body, terms),
                             "sha256_12": doc.sha256_file[:12],
                             "tokens": tokens.estimate(pre_body)[0]})

        for sec in doc.sections:
            body = "\n".join(doc.lines[sec.start:sec.stop])
            text = (sec.title or "") + "\n" + body
            sc, rs, mt = score_section(sec, body, terms, path.name, line_name,
                                       include_superseded=args.include_superseded)
            if not sc:
                continue
            hits.append({"file": rel, "section_id": sec.id, "heading": sec.title,
                         "line": sec.line, "score": round(sc * weight, 1),
                         "matched": mt, "reasons": rs,
                         "snippet": snippet_for(text, terms),
                         "sha256_12": doc.sha256_file[:12],
                         "tokens": tokens.estimate(text)[0]})

    hits.sort(key=lambda h: (-h["score"], h["file"], h["line"]))
    hits = hits[:max(1, args.limit)]

    if args.json:
        print(json.dumps({"query": args.query, "terms": terms, "scanned": scanned,
                          "hits": hits, "errors": [{"file": a, "error": b} for a, b in errors]},
                         ensure_ascii=False, indent=2))
    else:
        if not hits:
            print("未命中：%s" % args.query)
            print("-- 已扫描 %d 个文本文件；试更短的关键词，或 --include-archive" % scanned)
        for h in hits:
            print("== %.0f 分  %s  L%s%s" % (h["score"], h["file"], h["line"],
                                             "  [%s]" % h["section_id"] if h["section_id"] else ""))
            print("   %s" % h["heading"])
            print("   %s" % h["snippet"])
            print("   hash=%s  ≈%d tokens  命中：%s"
                  % (h["sha256_12"], h["tokens"], ", ".join(h["reasons"][:4])))
        if errors:
            print("\n无法解析 %d 个文件：%s" % (len(errors), errors[0][0]))
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())
