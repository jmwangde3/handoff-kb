#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-outline.py — Markdown 目录树 / 按节读取 / 稳定章节 ID

v2 变化：
- 新增 `--section-id`（`<!-- kb:id: xxx -->` 绑定的稳定 ID），与行号、标题文字解耦
- 解析交给 lib/markdown.py：正确处理长围栏、伪标题、转义、重复标题、CRLF、无末尾换行
- `--hash` 同时接受文本短哈希（旧行为）与文件 sha256 前缀
- 新增 `--json`，供 kb-context / CI 消费

用法：
  py kb-outline.py --file 05_进度仪表盘.md
  py kb-outline.py --file ... --find 磁盘
  py kb-outline.py --file ... --section 12 --hash <HASH>
  py kb-outline.py --file ... --section-id dashboard.current
  py kb-outline.py --file ... --section 12 --max-lines 80 --offset 0
  py kb-outline.py --file ... --section 12 --no-children
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import markdown as md  # noqa: E402


def _hash_ok(doc, given: str) -> bool:
    g = (given or "").strip().lower()
    if not g:
        return True
    return doc.short_hash.startswith(g) or doc.sha256_file.startswith(g) \
        or doc.sha256_text.startswith(g)


def main() -> int:
    ap = argparse.ArgumentParser(description="Markdown 目录树、稳定章节 ID 与按节读取")
    ap.add_argument("--file", required=True, help="目标 .md 文件")
    ap.add_argument("--section", default=None,
                    help="第 N 个标题（纯数字）或标题文字片段；不给则输出目录树")
    ap.add_argument("--section-id", default=None,
                    help="稳定章节 ID（如 dashboard.current），优先于 --section")
    ap.add_argument("--find", default=None, help="只列标题含该关键词的条目")
    ap.add_argument("--hash", default=None,
                    help="source-hash 前缀；传了就校验，不符则拒绝读取（退出码 2）")
    ap.add_argument("--no-children", action="store_true", help="只取本节正文，不含子节")
    ap.add_argument("--max-lines", type=int, default=0, help="最多输出多少行（0=不限）")
    ap.add_argument("--offset", type=int, default=0, help="从本节第几行开始（配合 --max-lines 续读）")
    ap.add_argument("--no-line-numbers", action="store_true", help="输出不带行号")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args()

    p = Path(args.file).expanduser().resolve()
    if not p.is_file():
        print("文件不存在：%s" % p, file=sys.stderr)
        return 2
    doc = md.parse_file(p)
    if args.offset < 0 or args.max_lines < 0:
        print("ERR: --offset / --max-lines 不能为负", file=sys.stderr)
        return 2
    if not _hash_ok(doc, args.hash):
        print("ERR: source-hash 不匹配（传入 %s / 实际 %s）——文档已变更，重跑 outline 再取节"
              % (args.hash, doc.short_hash), file=sys.stderr)
        return 2

    if args.find:
        hits = [s for s in doc.sections if args.find.lower() in s.title.lower()]
        if args.json:
            print(json.dumps({"file": p.name, "hash": doc.short_hash, "hits": [
                {"n": s.n, "line": s.line, "lines": s.span, "level": s.level,
                 "title": s.title, "id": s.id} for s in hits]}, ensure_ascii=False, indent=2))
            return 0
        for s in hits:
            print("  #%-3d L%-5d %4d行  %s%s%s" % (
                s.n, s.line, s.span, "  " * (s.level - 1), s.title,
                "  [%s]" % s.id if s.id else ""))
        print("\nsource-hash: %s | 命中 %d / 共 %d 个标题"
              % (doc.short_hash, len(hits), len(doc.sections)))
        return 0

    if not args.section and not args.section_id:
        if args.json:
            print(json.dumps({"file": p.name, "hash": doc.short_hash, "sha256": doc.sha256_file,
                              "lines": len(doc.lines), "schema": doc.schema,
                              "sections": md.outline(doc)}, ensure_ascii=False, indent=2))
            return 0
        print("# %s" % p.name)
        print("source-hash: %s | %d 行 | %d 个标题 | schema=%s"
              % (doc.short_hash, len(doc.lines), len(doc.sections), doc.schema or "v1"))
        print("按节读：py kb-outline.py --file \"%s\" --section-id <ID> --hash %s\n"
              % (p, doc.short_hash))
        for s in doc.sections:
            print("  #%-3d L%-5d %4d行  %s%s%s" % (
                s.n, s.line, s.span, "  " * (s.level - 1), s.title,
                "  [%s]" % s.id if s.id else ""))
        return 0

    try:
        if args.section_id:
            sel = md.find_by_id(doc, args.section_id.strip())
            if sel is None:
                print("未找到章节 ID：%s（不带参数跑一次可看 id 清单）" % args.section_id,
                      file=sys.stderr)
                return 1
        else:
            sel = md.find(doc, args.section)
            if sel is None:
                print("未找到节：%s（共 %d 个标题，可先跑 --find）"
                      % (args.section, len(doc.sections)), file=sys.stderr)
                return 1
    except md.MarkdownError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    text, meta = md.render(doc, sel, include_children=not args.no_children,
                           max_lines=args.max_lines, offset=args.offset,
                           line_numbers=not args.no_line_numbers)
    if args.json:
        print(json.dumps({"file": p.name, "section": meta, "text": text,
                          "sha256": doc.sha256_file}, ensure_ascii=False, indent=2))
        return 0
    print("== [%s] #%d  L%d–L%d  (%d 行)  hash=%s%s" % (
        meta["title"], meta["n"], meta["from"], meta["to"], meta["lines"],
        meta["hash"], "  id=%s" % meta["id"] if meta["id"] else ""))
    print("=" * 60)
    print(text)
    if meta["truncated"]:
        print("\n[已截断] 本节共 %d 行，续读加 --offset %d"
              % (meta["total_lines"], meta["next_offset"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
