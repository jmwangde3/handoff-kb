#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一事实解析（handoff-kb 2.0.1）

**唯一**的事实识别实现：kb-check / kb-handoff / kb-search / kb-context / kb-write
都走这里，不再各写一套正则。

三种定义形式（都在代码围栏外才算）：

    ## G-010 当前 NSS 配置          ← 标题定义（定义块 = 该标题下的正文）
    - K-01: 当前配置                ← 列表定义（定义块 = 这一行）
    | K-02 | 名称 | 值 | 有效 | 日志 |  ← 表格定义（定义块 = 这一行，元数据取表头列）

可选元数据（向后兼容，不写就用默认值）：

    ## G-010 当前 NSS 配置
    <!-- kb:fact-meta: {"status":"valid","evidence":"logs/nss.md",
                        "verified_at":"2026-11-10","owner":"固件","volatility":"dynamic"} -->

判定原则：
  - 只有「定义位」才算定义：标题首 / 列表首 / 表格首列。句中提到一律算引用。
  - 重复定义不静默覆盖：全部保留在列表里，由调用方报 ERR。
  - 元数据解析失败不默认「有效」，标 unknown + meta_error。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import markdown as md
from . import protocol, scope

META_RE = re.compile(r"^\s*<!--\s*kb:fact-meta:\s*(\{.*\})\s*-->\s*$")

HEADING_RE = re.compile(r"^(#{1,6})\s*[`*\s]*([KG]-\d{2,3})\b\s*[`*]?\s*(.*)$")
LIST_RE = re.compile(r"^(\s*[-*+]\s*)[`*]*([KG]-\d{2,3})[`*]*\s*(?:[:：]\s*)?(.*)$")
TABLE_RE = re.compile(r"^\|\s*[`*\s]*([KG]-\d{2,3})\s*\|")

STATUS_MAP = {
    "有效": "valid", "valid": "valid", "ok": "valid", "✅": "valid",
    "待核": "pending", "pending": "pending", "待确认": "pending", "?": "pending",
    "作废": "deprecated", "已作废": "deprecated", "deprecated": "deprecated",
    "superseded": "deprecated", "废弃": "deprecated",
}

VOLATILITY_MAP = {
    "static": "static", "静态": "static",
    "dynamic": "dynamic", "动态": "dynamic",
}

COL_STATUS = ("状态", "status")
COL_EVIDENCE = ("证据", "核实", "evidence")
COL_VERIFY = ("核实时间", "时间", "verified")
COL_OWNER = ("归属", "owner", "线")
COL_VOLATILITY = ("时效", "volatility", "类型")


@dataclass
class FactDefinition:
    id: str
    path: str
    definition_type: str            # heading | list | table
    line_start: int
    line_end: int
    title: str = ""
    status: str = "unknown"
    evidence: str = ""
    verified_at: str = ""
    owner: str = ""
    volatility: str = "unknown"
    superseded_by: str = ""
    meta_error: str = ""
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"id": self.id, "path": self.path, "type": self.definition_type,
                "line_start": self.line_start, "line_end": self.line_end,
                "title": self.title, "status": self.status,
                "evidence": self.evidence, "verified_at": self.verified_at,
                "owner": self.owner, "volatility": self.volatility,
                "superseded_by": self.superseded_by, "meta_error": self.meta_error}


@dataclass
class FactReference:
    id: str
    path: str
    line: int


class FactError(Exception):
    pass


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #

def normalize_status(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return "unknown"
    if s in STATUS_MAP:
        return STATUS_MAP[s]
    low = s.lower()
    if low in STATUS_MAP:
        return STATUS_MAP[low]
    for k, v in STATUS_MAP.items():
        if k and k in s:
            return v
    return "unknown"


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _table_meta(header: list[str], row: list[str]) -> dict:
    def pick(names):
        for i, h in enumerate(header):
            hl = h.strip().lower()
            if any(n.lower() in hl for n in names):
                return row[i] if i < len(row) else ""
        return ""
    return {"status": pick(COL_STATUS), "evidence": pick(COL_EVIDENCE),
            "verified_at": pick(COL_VERIFY), "owner": pick(COL_OWNER),
            "volatility": pick(COL_VOLATILITY)}


def _iter_lines(doc):
    """产出 (行号, 行文本, 是否在代码围栏内)。"""
    fence = None
    for i, raw in enumerate(doc.lines, 1):
        line = raw.rstrip("\r")
        m = re.match(r"^( {0,3})(`{3,}|~{3,})", line)
        if m:
            if fence is None:
                fence = (m.group(2)[0], len(m.group(2)))
            elif m.group(2)[0] == fence[0] and len(m.group(2)) >= fence[1]:
                fence = None
            yield i, line, True
            continue
        yield i, line, fence is not None


def _section_end(doc, start: int, level: int) -> int:
    """标题定义的结束行（下一个同级或更高级标题之前）。start 为 1 基行号。"""
    for s in doc.sections:
        if s.line > start and s.level <= level:
            return s.line - 1
    return len(doc.lines)


def parse_document(path: Path, rel: str) -> tuple[list[FactDefinition], list[FactReference]]:
    doc = md.parse_file(path)
    defs: list[FactDefinition] = []
    refs: list[FactReference] = []
    header = None
    in_table = False
    for lineno, line, fenced in _iter_lines(doc):
        if fenced:
            continue
        stripped = line.strip()

        # 表格：跟踪表头，用于列名取元数据
        if stripped.startswith("|"):
            cells = _cells(line)
            if not in_table:
                header, in_table = cells, True
                continue
            if all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells):
                continue                       # 分隔行
            m = TABLE_RE.match(line)
            if m:
                fid = m.group(1)
                meta = _table_meta(header or [], cells)
                # 表格定义位：替代 ID 常写在「状态」列（已作废 → K-04），
                # 只看首列会漏掉，所以把整行作为补充检索范围。
                d = _mk(fid, rel, "table", lineno, lineno, cells[0],
                        meta, doc, lineno, haystack=line)
                defs.append(d)
                _refs_other(line, fid, rel, lineno, refs)
                continue
            for mid in protocol.FACT_ID_RE.finditer(line):
                refs.append(FactReference(mid.group(1), rel, lineno))
            continue
        in_table, header = False, None

        m = HEADING_RE.match(line)
        if m:
            level, fid, title = len(m.group(1)), m.group(2), m.group(3).strip()
            end = _section_end(doc, lineno, level)
            meta = _meta_after(doc, lineno, "heading")
            defs.append(_mk(fid, rel, "heading", lineno, end, title, meta, doc, lineno))
            _refs_other(line, fid, rel, lineno, refs)
            continue

        m = LIST_RE.match(line)
        if m:
            fid, title = m.group(2), m.group(3).strip()
            meta = _meta_after(doc, lineno, "list")
            defs.append(_mk(fid, rel, "list", lineno, lineno, title, meta, doc, lineno))
            _refs_other(line, fid, rel, lineno, refs)
            continue

        for mid in protocol.FACT_ID_RE.finditer(line):
            refs.append(FactReference(mid.group(1), rel, lineno))
    return defs, refs


def _refs_other(line: str, defined_id: str, rel: str, lineno: int, refs: list):
    """定义行里提到的**其它** ID 仍算引用（注意不把定义本身算成引用）。"""
    for mid in protocol.FACT_ID_RE.finditer(line):
        if mid.group(1) != defined_id:
            refs.append(FactReference(mid.group(1), rel, lineno))


def _meta_after(doc, lineno: int, kind: str) -> dict:
    """定义行之后紧跟的 kb:fact-meta 注释（标题：标题的下一行；列表：同一行的行尾也算）。"""
    idx = lineno                            # doc.lines 是 0 基
    if idx < len(doc.lines):
        m = META_RE.match(doc.lines[idx])
        if m:
            return {"_raw": m.group(1)}
    return {}


def _mk(fid, rel, kind, start, end, title, meta, doc, lineno,
        haystack: str = "") -> FactDefinition:
    d = FactDefinition(id=fid, path=rel, definition_type=kind,
                       line_start=start, line_end=end, title=title)
    if meta.get("_raw"):
        try:
            data = json.loads(meta["_raw"])
            if not isinstance(data, dict):
                raise ValueError("fact-meta 不是对象")
            meta = dict(data)
        except Exception as exc:
            d.meta_error = "kb:fact-meta 解析失败：%s" % exc
            meta = {}
    d.meta = meta
    d.status = normalize_status(meta.get("status", ""))
    d.evidence = str(meta.get("evidence", "") or "").strip()
    d.verified_at = str(meta.get("verified_at", "") or "").strip()
    d.owner = str(meta.get("owner", "") or "").strip()
    vol = str(meta.get("volatility", "") or "").strip()
    d.volatility = VOLATILITY_MAP.get(vol, VOLATILITY_MAP.get(vol.lower(), "unknown"))
    sup = str(meta.get("superseded_by", "") or "").strip()
    if not sup and d.status == "deprecated":
        m = re.search(r"→\s*([KG]-\d{2,3})", haystack or title)
        if m:
            sup = m.group(1)
    d.superseded_by = sup
    return d


def text_files(root, include_archive: bool = False, loose: bool = False):
    """参与事实统计的文件（数据目录/超限文件已排除）。"""
    out = []
    for p, reason in scope.iter_text_files(Path(root), include_archive=include_archive):
        if reason:
            continue
        out.append(p)
    return out


def parse_fact_definitions(root, include_archive: bool = False, loose: bool = False):
    """全库扫描。返回 (defs_by_id: dict[str, list[FactDefinition]], problems: list[str])。"""
    root = Path(root).resolve()
    by_id: dict[str, list[FactDefinition]] = {}
    problems = []
    for p in text_files(root, include_archive=include_archive, loose=loose):
        rel = p.relative_to(root).as_posix()
        try:
            defs, _ = parse_document(p, rel)
        except Exception as exc:
            problems.append("%s 解析失败：%s" % (rel, exc))
            continue
        for d in defs:
            by_id.setdefault(d.id, []).append(d)
            if d.meta_error:
                problems.append("%s:%d %s" % (rel, d.line_start, d.meta_error))
    return by_id, problems


def find_fact(root, fact_id: str, include_archive: bool = False):
    defs, _ = parse_fact_definitions(root, include_archive=include_archive)
    return defs.get(fact_id, [])


def find_fact_references(root, include_archive: bool = False) -> list[FactReference]:
    root = Path(root).resolve()
    refs = []
    for p in text_files(root, include_archive=include_archive):
        rel = p.relative_to(root).as_posix()
        try:
            _, r = parse_document(p, rel)
        except Exception:
            continue
        refs.extend(r)
    return refs


def duplicates(defs_by_id) -> dict[str, list[FactDefinition]]:
    return {k: v for k, v in defs_by_id.items() if len(v) > 1}


def validate_fact_metadata(root, include_archive: bool = False):
    """返回问题清单：[{"kind":..,"id":..,"path":..,"line":..,"message":..}]。"""
    root = Path(root).resolve()
    defs, problems = parse_fact_definitions(root, include_archive=include_archive)
    issues = []
    for fid, items in defs.items():
        if len(items) > 1:
            issues.append({"kind": "duplicate", "id": fid, "locations":
                           ["%s:%d" % (d.path, d.line_start) for d in items],
                           "message": "%s 重复定义 %d 次" % (fid, len(items))})
        for d in items:
            if d.meta_error:
                issues.append({"kind": "meta", "id": fid, "path": d.path,
                               "line": d.line_start, "message": d.meta_error})
            if d.status == "unknown" and d.definition_type == "table":
                issues.append({"kind": "status", "id": fid, "path": d.path,
                               "line": d.line_start,
                               "message": "%s 的状态无法识别（用 有效/待核/作废）" % fid})
            if d.status == "valid" and d.evidence in ("", "—", "-", "无", "n/a"):
                issues.append({"kind": "evidence", "id": fid, "path": d.path,
                               "line": d.line_start,
                               "message": "%s 标了有效但没有证据" % fid})
            if d.verified_at and d.verified_at not in ("—", "-", "无", "n/a", "/", "TBD"):
                m = re.search(r"\d{4}-\d{2}-\d{2}", d.verified_at)
                if not m:
                    issues.append({"kind": "verified_at", "id": fid, "path": d.path,
                                   "line": d.line_start,
                                   "message": "%s 的核实时间不是 YYYY-MM-DD" % fid})
            if d.status == "deprecated" and not d.superseded_by:
                issues.append({"kind": "superseded", "id": fid, "path": d.path,
                               "line": d.line_start,
                               "message": "%s 已作废但没写替代 ID（→ K-xx）" % fid})
    return issues, problems


def is_filled(text: str, placeholders=("[填", "TODO", "TBD", "FIXME")) -> bool:
    real = []
    for s in (text or "").splitlines():
        s = s.strip()
        if not s or s.startswith("<!--"):
            continue
        if any(ph in s for ph in placeholders):
            continue
        real.append(s)
    return len("".join(real).strip(" -|:\t")) >= 4


# --------------------------------------------------------------------------- #
# 更新（供 kb-write 使用；纯文本变换，不碰磁盘）
# --------------------------------------------------------------------------- #

def update_fact_definition(text: str, fact_id: str, content: str, rel: str = "") -> str:
    """在**单个文件**里替换事实定义。三种形式都支持，歧义即拒绝。

    - heading：只替换标题行，保留其下正文
    - list   ：替换该列表行
    - table  ：替换该表格行（content 必须是表格行）

    **ID 不可变**：替换后的行必须仍然定义同一个 `fact_id`。
    `update_fact(K-01, "## K-99 新事实")` 会被拒绝 —— 那不是「更新 K-01」，
    而是「用一次更新悄悄把 K-01 换成了 K-99」，全库的 `§`/`K-01` 引用会指向空气。
    """
    if not protocol.FACT_ID_RE.fullmatch(fact_id or ""):
        raise FactError("fact_id 非法：%r（形如 K-01 / G-007）" % fact_id)
    content = (content or "").rstrip("\n")
    if not content.strip():
        raise FactError("update_fact 的 content 为空")
    doc = md.parse(text, Path(rel) if rel else None)
    hits = []                                  # (kind, lineno)
    fence = None
    in_table = False
    for lineno, line, fenced in _iter_lines(doc):
        if fenced:
            continue
        stripped = line.strip()
        if stripped.startswith("|"):
            if not in_table:
                in_table = True
                continue
            if all(re.fullmatch(r":?-{2,}:?", c or "-") for c in _cells(line)):
                continue
            m = TABLE_RE.match(line)
            if m and m.group(1) == fact_id:
                hits.append(("table", lineno))
            continue
        in_table = False
        m = HEADING_RE.match(line)
        if m and m.group(2) == fact_id:
            hits.append(("heading", lineno))
            continue
        m = LIST_RE.match(line)
        if m and m.group(2) == fact_id:
            hits.append(("list", lineno))

    if not hits:
        raise FactError("文件里找不到事实定义 %s（不做新增；新增请显式改基线表）" % fact_id)
    if len(hits) > 1:
        raise FactError("%s 在同一个文件里有 %d 处定义（第 %s 行），歧义：拒绝自动改写"
                        % (fact_id, len(hits), ", ".join(str(h[1]) for h in hits)))

    kind, lineno = hits[0]
    lines = text.splitlines()
    idx = lineno - 1
    body_lines = [ln for ln in content.splitlines() if ln.strip()]
    if len(body_lines) > 1:
        # 只替换定义行；多出来的行会被静默丢弃 —— 那等于替用户删内容
        raise FactError("%s 定义是单行（%s），content 只允许一行；"
                        "要改正文请用 replace_section 写整节" % (fact_id, kind))
    if kind == "heading":
        if not content.lstrip().startswith("#"):
            raise FactError("heading 定义要用标题行替换（content 应以 # 开头）")
        lines[idx] = body_lines[0]
    elif kind == "list":
        if not content.lstrip().startswith(("-", "*", "+")):
            raise FactError("list 定义要用列表行替换（content 应以 - 开头）")
        lines[idx] = body_lines[0]
    else:
        if not content.lstrip().startswith("|"):
            raise FactError("table 定义要用表格行替换（content 应以 | 开头）")
        old_cells = len(_cells(lines[idx]))
        new_line = body_lines[0]
        if len(_cells(new_line)) != old_cells:
            raise FactError("表格行必须保持 %d 列（收到 %d 列）"
                            % (old_cells, len(_cells(new_line))))
        lines[idx] = new_line

    # ID 不可变：替换后的那一行必须仍然定义 fact_id，且定义形式一致
    got = _definition_id_of(lines[idx], kind)
    if got != fact_id:
        raise FactError(
            "替换内容不再定义 %s（这一行定义的是 %r）：事实 ID 不可变。\n"
            "  要换 ID 请显式改名并同步全库引用，不要用 update_fact 顺手改。"
            % (fact_id, got))
    out = "\n".join(lines)
    if text.endswith("\n"):
        out += "\n"
    return out


def _definition_id_of(line: str, kind: str):
    """某一行在指定定义形式下定义的是哪个 ID（不是定义位就返回 None）。"""
    if kind == "heading":
        m = HEADING_RE.match(line)
        return m.group(2) if m else None
    if kind == "list":
        m = LIST_RE.match(line)
        return m.group(2) if m else None
    m = TABLE_RE.match(line)
    return m.group(1) if m else None


def definition_text(root, d: FactDefinition, *, max_chars: int = 4000) -> str:
    """把一条事实定义渲染成可直接放进上下文的文本。

    - heading：标题 + 该标题下的正文（到下一个同级标题前）
    - list   ：这一行
    - table  ：表头 + 这一行（否则只有一行数据，读不出列含义）
    """
    p = Path(root) / d.path
    try:
        doc = md.parse_file(p)
    except Exception:
        return ""
    lines = [ln.rstrip("\r") for ln in doc.lines]
    start = max(0, d.line_start - 1)
    end = min(len(lines), max(d.line_end, d.line_start))
    if d.definition_type == "table":
        header = None
        for i in range(start, -1, -1):
            if lines[i].strip().startswith("|"):
                header = lines[i]
            else:
                break
        body = ([header] if header and header != lines[start] else []) + [lines[start]]
    elif d.definition_type == "list":
        body = [lines[start]]
    else:
        body = lines[start:end]
    text = "\n".join(body).strip()
    return text[:max_chars]


def counts(defs_by_id, problems) -> dict:
    """统计口径：让「一条事实都没解析出来」与「全都通过」在输出里分得开。"""
    items = [d for v in defs_by_id.values() for d in v]
    return {
        "definitions": len(items),
        "ids": len(defs_by_id),
        "valid": sum(1 for d in items if d.status == "valid"),
        "pending": sum(1 for d in items if d.status == "pending"),
        "deprecated": sum(1 for d in items if d.status == "deprecated"),
        "unknown": sum(1 for d in items if d.status == "unknown"),
        "duplicated_ids": sum(1 for v in defs_by_id.values() if len(v) > 1),
        "problems": len(problems),
    }
