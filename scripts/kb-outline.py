#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-outline.py — Markdown 分段读取（outline / section）

给「参考手册型」文档（几百行、非必读）提供目录树 + 按节取，避免整份塞进上下文。
借鉴 agent-memory-vault 的 outline / section + source hash 重验证：
先拿目录与 hash，再按节读；hash 不符说明文档已变，必须重新取目录。

用法：
  py kb-outline.py --file 03_xray-hy服务端_精简交接.md
  py kb-outline.py --file ... --find 磁盘
  py kb-outline.py --file ... --section "3-J" --hash <HASH>
  py kb-outline.py --file ... --section 12 --max-lines 80 --offset 0
  py kb-outline.py --file ... --section 12 --no-children
"""
from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def read(p: Path) -> str:
    return io.open(p, encoding="utf-8").read()


def headings(lines):
    """返回 [(0基行号, level, title)]，跳过 fenced code block 内的 # 行。"""
    out, in_fence, fence_ch = [], False, ""
    for i, line in enumerate(lines):
        s = line.rstrip()
        mf = re.match(r"^\s*(`{3,}|~{3,})", s)
        if mf:
            ch = mf.group(1)[0]
            if not in_fence:
                in_fence, fence_ch = True, ch
            elif ch == fence_ch:
                in_fence = False
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", s)
        if m:
            out.append((i, len(m.group(1)), m.group(2)))
    return out


def build(lines, hs):
    nodes = []
    for k, (i, lvl, title) in enumerate(hs):
        end = len(lines)
        for j, l2, _ in hs[k + 1:]:
            if l2 <= lvl:          # 下一个同级或更高级标题 = 本节结束
                end = j
                break
        while end > i + 1 and not lines[end - 1].strip():
            end -= 1
        nodes.append({"n": k + 1, "line": i + 1, "level": lvl,
                      "title": title, "start": i, "end": end})
    return nodes


def main() -> int:
    ap = argparse.ArgumentParser(description="Markdown 目录树与按节读取")
    ap.add_argument("--file", required=True, help="目标 .md 文件")
    ap.add_argument("--section", default=None,
                    help="第 N 个标题（纯数字）或标题文字片段；不给则输出目录树")
    ap.add_argument("--find", default=None, help="只列标题含该关键词的条目")
    ap.add_argument("--hash", default=None,
                    help="outline 输出的 source-hash 前 12 位；传了就校验，不符则拒绝读取")
    ap.add_argument("--no-children", action="store_true", help="只取本节正文，不含子节")
    ap.add_argument("--max-lines", type=int, default=0, help="最多输出多少行（0=不限）")
    ap.add_argument("--offset", type=int, default=0, help="从本节第几行开始（配合 --max-lines 续读）")
    ap.add_argument("--no-line-numbers", action="store_true", help="输出不带行号")
    args = ap.parse_args()

    p = Path(args.file).expanduser().resolve()
    if not p.is_file():
        print("文件不存在：%s" % p, file=sys.stderr)
        return 2
    text = read(p)
    lines = text.splitlines()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    nodes = build(lines, headings(lines))

    if args.hash and args.hash.strip() != digest:
        print("ERR: source-hash 不匹配（传入 %s / 实际 %s）——文档已变更，重新跑 outline 再取节"
              % (args.hash.strip(), digest), file=sys.stderr)
        return 2

    if args.find:
        hit = [n for n in nodes if args.find.lower() in n["title"].lower()]
        for n in hit:
            print("  #%-3d L%-5d %4d行  %s%s" % (
                n["n"], n["line"], n["end"] - n["start"],
                "  " * (n["level"] - 1), n["title"]))
        print("\nsource-hash: %s | 命中 %d / 共 %d 个标题" % (digest, len(hit), len(nodes)))
        return 0

    if not args.section:
        print("# %s" % p.name)
        print("source-hash: %s | %d 行 | %d 个标题" % (digest, len(lines), len(nodes)))
        print("按节读：py kb-outline.py --file \"%s\" --section <N|标题片段> --hash %s\n" % (p, digest))
        for n in nodes:
            print("  #%-3d L%-5d %4d行  %s%s" % (
                n["n"], n["line"], n["end"] - n["start"],
                "  " * (n["level"] - 1), n["title"]))
        return 0

    sel = None
    if args.section.strip().isdigit():
        idx = int(args.section.strip()) - 1
        if 0 <= idx < len(nodes):
            sel = nodes[idx]
    else:
        cand = [n for n in nodes if args.section.lower() in n["title"].lower()]
        if len(cand) == 1:
            sel = cand[0]
        elif len(cand) > 1:
            print("多个匹配，用 --section <N> 精确选择：", file=sys.stderr)
            for n in cand:
                print("  #%-3d L%-5d %s" % (n["n"], n["line"], n["title"]), file=sys.stderr)
            return 1
    if not sel:
        print("未找到节：%s（共 %d 个标题，可先跑 --find）" % (args.section, len(nodes)),
              file=sys.stderr)
        return 1

    start, end = sel["start"], sel["end"]
    if args.no_children:
        for c in nodes:
            if c["n"] > sel["n"] and c["level"] > sel["level"]:
                end = min(end, c["start"])
                break
    body = lines[start:end]
    if args.offset:
        body = body[args.offset:]
    truncated = bool(args.max_lines and len(body) > args.max_lines)
    if truncated:
        body = body[:args.max_lines]

    print("== [%s] #%d  L%d–L%d  (%d 行)  hash=%s" % (
        sel["title"], sel["n"], sel["line"] + args.offset,
        sel["line"] + args.offset + len(body) - 1, len(body), digest))
    print("=" * 60)
    for k, line in enumerate(body, start + 1 + args.offset):
        print(("%5d| %s" % (k, line)) if not args.no_line_numbers else line)
    if truncated:
        print("\n[已截断] 续读加 --offset %d" % (args.offset + args.max_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
