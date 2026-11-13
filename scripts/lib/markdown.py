#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 解析与稳定章节定位（handoff-kb 2.0）

要点：
- 跳过 fenced code block（``` / ~~~，长度可变）里的伪标题、伪表格、伪 kb:id
- ATX 标题，容忍行尾 `###`、无空格标题、CRLF、无末尾换行
- `<!-- kb:id: xxx -->` 绑定"紧随其后"的标题，ID 与行号/标题文字解耦
- 章节 end 由"下一个同级或更高级标题"决定，子节可含可去
- 同时给两种哈希：文件字节 sha256（写入校验）与文本 sha256（旧 outline 短哈希兼容）
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
HEADING_RE = re.compile(r"^( {0,3})(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
ID_COMMENT_RE = re.compile(r"^\s*<!--\s*kb:id:\s*([A-Za-z0-9][A-Za-z0-9_.:-]*)\s*-->\s*$")
SCHEMA_COMMENT_RE = re.compile(r"^\s*<!--\s*kb:schema:\s*(\d+)\s*-->\s*$")


class MarkdownError(Exception):
    pass


@dataclass
class Section:
    n: int                      # 1 基序号（文档顺序），即旧 --section N
    level: int
    title: str
    line: int                   # 标题所在行（1 基）
    end: int                    # 本节末行（含）1 基；无内容时等于 line
    start: int                  # 正文起始（0 基，标题下一行）
    stop: int                   # 正文结束（0 基，不含）
    id: Optional[str] = None
    parent: Optional[int] = None  # 父节 n
    children: list = field(default_factory=list)

    @property
    def span(self) -> int:
        return self.end - self.line + 1


@dataclass
class Document:
    path: Path
    text: str
    lines: list
    sections: list
    sha256_file: str
    sha256_text: str
    schema: Optional[int] = None

    @property
    def short_hash(self) -> str:
        return self.sha256_text[:12]

    @property
    def duplicate_ids(self):
        seen, dup = set(), []
        for s in self.sections:
            if s.id:
                if s.id in seen:
                    dup.append(s.id)
                seen.add(s.id)
        return dup


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _strip_closing_hashes(title: str) -> str:
    t = title.rstrip()
    if re.search(r"\s#+$", t):
        t = re.sub(r"\s#+$", "", t).rstrip()
    return t


def scan_fences(lines):
    """产出 `(行号 0 基, 行文本, in_fence)`。

    `in_fence=True` 包含**围栏标记行本身**与围栏内的每一行。围栏规则与
    `parse()` 完全一致：≤3 空格缩进、3 个以上 ``` 或 ~~~、闭合必须同字符且长度不小于
    开启、闭合行除围栏外不能有别的内容（语言标记只允许出现在开启行）。

    只写这一份实现：早先 `facts.py` / `kb-check.py` / `kb-context.py` 各写一遍，
    于是「围栏内的表格算不算表格」在不同脚本里答案不一样。
    """
    fence_ch, fence_len = None, 0
    for idx, raw in enumerate(lines):
        line = raw.rstrip("\r")
        m = FENCE_RE.match(line)
        if fence_ch:
            if m and m.group(2)[0] == fence_ch and len(m.group(2)) >= fence_len \
                    and not m.group(3).strip():
                fence_ch = None
            yield idx, line, True
            continue
        if m:
            fence_ch, fence_len = m.group(2)[0], len(m.group(2))
            yield idx, line, True
            continue
        yield idx, line, False


def unfenced_lines(doc):
    """产出 `(1 基行号, 行文本)`：跳过围栏标记行与围栏内的所有行。"""
    for idx, line, fenced in scan_fences(doc.lines):
        if fenced:
            continue
        yield idx + 1, line


def parse(text: str, path: Optional[Path] = None) -> Document:
    lines = text.splitlines()
    heads = []           # (idx, level, title, id)
    id_lines = set()     # 属于"下一个标题"的 kb:id 注释行号（0 基）
    fence_ch = None
    fence_len = 0
    pending_id = None
    schema = None
    for idx, raw in enumerate(lines):
        line = raw.rstrip("\r")
        if fence_ch:
            m = FENCE_RE.match(line)
            if m and m.group(2)[0] == fence_ch and len(m.group(2)) >= fence_len \
                    and not m.group(3).strip():
                fence_ch = None
            continue
        m = FENCE_RE.match(line)
        if m:
            fence_ch = m.group(2)[0]
            fence_len = len(m.group(2))
            pending_id = None
            continue
        ms = SCHEMA_COMMENT_RE.match(line)
        if ms:
            schema = int(ms.group(1))
            continue
        mid = ID_COMMENT_RE.match(line)
        if mid:
            pending_id = mid.group(1)
            id_lines.add(idx)
            continue
        mh = HEADING_RE.match(line)
        if mh:
            heads.append((idx, len(mh.group(2)), _strip_closing_hashes(mh.group(3) or ""),
                          pending_id))
            pending_id = None
            continue
        if line.strip():
            pending_id = None

    sections = []
    stack = []
    for k, (idx, lvl, title, sid) in enumerate(heads):
        end_idx = len(lines)
        for idx2, lvl2, _, _ in heads[k + 1:]:
            if lvl2 <= lvl:
                end_idx = idx2
                break
        stop = end_idx
        # 尾部空行与"下一个标题的 kb:id 注释"不属于本节
        while stop > idx + 1 and (not lines[stop - 1].strip() or (stop - 1) in id_lines):
            stop -= 1
        end = max(stop, idx + 1)
        parent = None
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        if stack:
            parent = stack[-1][1]
        sec = Section(n=k + 1, level=lvl, title=title, line=idx + 1, end=end,
                      start=idx + 1, stop=stop, id=sid, parent=parent)
        sections.append(sec)
        if parent is not None:
            sections[parent - 1].children.append(sec.n)
        stack.append((lvl, sec.n))

    return Document(path=path or Path("-"), text=text, lines=lines, sections=sections,
                    sha256_file=sha256_file(path) if path and Path(path).is_file() else "",
                    sha256_text=sha256_text(text), schema=schema)


def parse_file(path) -> Document:
    p = Path(path)
    data = p.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    text = data.decode("utf-8", errors="replace")
    return parse(text, p)


def find(doc: Document, spec) -> Optional[Section]:
    """spec：整数/数字串 → 第 N 个标题；否则先按 id 精确匹配，再按标题子串。"""
    if isinstance(spec, int) or (isinstance(spec, str) and spec.strip().isdigit()):
        idx = int(spec) - 1
        if 0 <= idx < len(doc.sections):
            return doc.sections[idx]
        return None
    s = str(spec).strip()
    for sec in doc.sections:
        if sec.id == s:
            return sec
    cand = [sec for sec in doc.sections if s.lower() in sec.title.lower()]
    if len(cand) == 1:
        return cand[0]
    if len(cand) > 1:
        raise MarkdownError("多个标题匹配 %r：%s（用 --section <N> 或 --section-id 精确选择）"
                            % (s, ", ".join("#%d %s" % (c.n, c.title) for c in cand)))
    return None


def find_by_id(doc: Document, section_id: str) -> Optional[Section]:
    for sec in doc.sections:
        if sec.id == section_id:
            return sec
    return None


def body_range(doc: Document, sec: Section, include_children: bool = True):
    stop = sec.stop
    if not include_children:
        for child_n in sec.children:
            stop = min(stop, doc.sections[child_n - 1].line - 1)
    return sec.start, max(stop, sec.start)


def render(doc: Document, sec: Section, *, include_children: bool = True,
           max_lines: int = 0, offset: int = 0, line_numbers: bool = False):
    """返回 (文本, 元信息)。offset/max_lines 以本节正文为基准。"""
    if offset < 0 or max_lines < 0:
        raise MarkdownError("offset / max-lines 不能为负")
    a, b = body_range(doc, sec, include_children)
    body = doc.lines[a:b]
    if offset:
        body = body[offset:]
    truncated = bool(max_lines and len(body) > max_lines)
    if truncated:
        body = body[:max_lines]
    if line_numbers:
        text = "\n".join("%5d| %s" % (a + offset + i + 1, ln) for i, ln in enumerate(body))
    else:
        text = "\n".join(body)
    meta = {
        "title": sec.title, "n": sec.n, "id": sec.id,
        "line": sec.line, "from": (a + offset + 1) if body else sec.line,
        "to": (a + offset + len(body)) if body else sec.line,
        "lines": len(body), "total_lines": b - a,
        "truncated": truncated, "next_offset": offset + max_lines if truncated else None,
        "hash": doc.short_hash,
    }
    return text, meta


def outline(doc: Document):
    return [{"n": s.n, "line": s.line, "lines": s.span, "level": s.level,
             "title": s.title, "id": s.id} for s in doc.sections]


def front_matter_schema(doc: Document):
    return doc.schema
