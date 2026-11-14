#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 硬约束的统一解析（handoff-kb 2.0.4）

`kb-context` 负责注入、`kb-check` 负责体检。两边早先各判一套：
context 看正文有没有内容，check 只看有没有「硬约束」这个标题 —— 于是

    ## 硬约束

（只有标题、正文是空的）

在 check 里报 OK、在 context 里报缺口。同一个库一边说「约束正常注入」、
一边说「没有约束」，读者只会去补一个并不缺的东西。

这里把三级兜底与「什么算有效内容」收成一份实现，两边只调 `resolve()`：

    dashboard.constraints
        ↓ 不存在 / 内容无效
    dashboard.safety
        ↓ 不存在 / 内容无效
    AGENTS.md 的「硬约束」段
        ↓ 不存在 / 越界 / 读不了 / 解析失败 / 内容无效
    报真实缺口（带原因）

「有效内容」= 去掉注释、标题、分隔线、表格分隔行之后，仍有一段实打实的正文，
且不是纯占位符（`[填]` / `TODO` / `TBD` …）。`## 硬约束` 后面只跟一句
「见 05」也算有内容——那是用户的写法，不是我们要替他判断的事。
"""

from __future__ import annotations

import re
from pathlib import Path

from . import markdown as md
from . import scope

# 常见占位符写法：命中即视为「还没填」，不算有效约束
PLACEHOLDER_MARKS = ("[填", "【填", "TODO", "TBD", "FIXME", "XXX", "待补", "待填", "占位")

DECORATION_RE = re.compile(r"^(?:[-*+_=~#>|\s]{0,})$")
TABLE_SEP_RE = re.compile(r"^\|?[\s:|-]+\|?$")


def strip_decor(line: str) -> str:
    """去掉 Markdown 装饰，只留能读的字。

    列表符号、引用符、表格竖线、强调星号、行内代码反引号都剥掉，
    这样 `- `「`- - -`」「`| --- |`」这类「看着有内容其实没有」的行会被判空。
    """
    s = line.strip()
    if not s:
        return ""
    if s.startswith("<!--") and s.endswith("-->"):
        return ""
    if TABLE_SEP_RE.match(s) and "-" in s:
        return ""
    s = re.sub(r"^#{1,6}\s*", "", s)
    s = re.sub(r"^(?:[-*+]\s+)+", "", s)
    s = re.sub(r"^(?:\d+[.)]\s+)+", "", s)
    s = s.lstrip(">").strip()
    s = s.replace("|", " ").replace("*", " ").replace("`", " ").replace("~", " ")
    s = re.sub(r"\s+", "", s)
    return "" if DECORATION_RE.match(s) else s


def meaningful(text: str) -> bool:
    """这段正文是否算「真的写了东西」。"""
    real = []
    for line in (text or "").splitlines():
        body = strip_decor(line)
        if not body:
            continue
        if any(ph.lower() in body.lower() for ph in PLACEHOLDER_MARKS):
            continue
        real.append(body)
    return len("".join(real)) >= 4


def _block_text(doc, sec) -> str:
    """标题 + 自有正文（不含子节）。有正文才算有内容，标题本身不算。"""
    text, _ = md.render(doc, sec, include_children=False)
    return text or ""


def _from_dashboard(doc, dash_path, dash_rel=None):
    """dashboard 的 constraints / safety；返回 (结果|None, 无效原因|None)。

    两级都必须试过才能收工：`dashboard.constraints` 有 ID 但正文是 `[填]`，
    不代表 `dashboard.safety` 也没写。早先在第一个无效 ID 处直接返回，
    等于把「这一级没填」当成「两级都没有」，后面的有效约束永远读不到。
    """
    if doc is None:
        return None, None
    reasons = []
    for sid in ("dashboard.constraints", "dashboard.safety"):
        sec = md.find_by_id(doc, sid)
        if sec is None:
            continue
        text = _block_text(doc, sec)
        if meaningful(text):
            return {"source": "dashboard", "section_id": sid, "text": text,
                    "path": dash_path.name if dash_path else None,
                    "rel": dash_rel or "05", "title": "硬约束（不裁剪）",
                    "line": sec.line}, None
        # 有 ID 但没内容：这比「没有 ID」更该报出来——ID 存在会让人以为已经配好。
        # 先记下原因继续看下一级，两级都无效时一起报。
        reasons.append("%s 为空或只有占位符" % sid)
    return None, "；".join(reasons) if reasons else None


def read_agents(root: Path):
    """安全读取入口文件的「硬约束」段。

    返回 `(结果|None, 状态, 原因)`；`status` 取值：

    - `ok`        读到了有效内容
    - `missing`   没有 AGENTS.md
    - `no-section` 有文件但没有「硬约束」标题
    - `empty`     有标题但正文为空 / 纯占位符
    - `outside`   真实路径越界（符号链接 / Junction 指向库外）
    - `unreadable` 读取失败（权限、编码、IO）
    - `parse-error` 解析抛异常
    """
    root = Path(root)
    agents = root / "AGENTS.md"
    if not agents.exists():
        return None, "missing", "没有 AGENTS.md"

    # 入口文件也可能是符号链接 / Junction：读之前必须核对真实路径，
    # 否则库里放一个指向库外的 AGENTS.md，就能把别人的文件当成本库硬约束注入。
    if not scope.is_within(root, agents):
        return None, "outside", scope.escape_reason(root, agents)

    try:
        doc = md.parse_file(agents)
    except OSError as exc:
        return None, "unreadable", "%s 读取失败：%s" % (agents.name, exc)
    except Exception as exc:  # noqa: BLE001 - 解析器可能抛任何异常，都要变成诊断
        return None, "parse-error", "%s 解析失败：%s" % (agents.name, exc)

    sec = next((s for s in doc.sections if "硬约束" in (s.title or "")), None)
    if sec is None:
        return None, "no-section", "%s 里没有「硬约束」段" % agents.name
    text = _block_text(doc, sec)
    try:
        rel = agents.relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = agents.name
    if not meaningful(text):
        return None, "empty", "%s「%s」为空或只有占位符" % (agents.name, sec.title or "硬约束")
    return {"source": "agents", "section_id": sec.id, "text": text,
            "path": agents.name, "rel": rel, "title": "硬约束（AGENTS.md）",
            "line": sec.line}, "ok", ""


def resolve(root: Path, dash_doc=None, dash_path=None, dash_rel=None):
    """三级兜底走完再判：返回统一结论。

    `{"ok": bool, "block": {...}|None, "source": "dashboard"|"agents"|None,
       "status": str, "detail": str, "gap": str|None}`
    """
    got, why_empty = _from_dashboard(dash_doc, dash_path, dash_rel)
    if got:
        return {"ok": True, "block": got, "source": "dashboard", "status": "ok",
                "detail": "dashboard %s" % got["section_id"], "gap": None}

    got, status, detail = read_agents(root)
    if got:
        extra = "（dashboard %s）" % why_empty if why_empty else ""
        return {"ok": True, "block": got, "source": "agents", "status": "ok",
                "detail": "%s 的「硬约束」段%s" % (got["path"], extra), "gap": None}

    if why_empty:
        gap = "%s，且 %s —— 预算裁剪时无安全上下文" % (why_empty, detail)
    elif status == "outside":
        gap = "AGENTS.md 指向工作区外，已跳过：%s" % detail
    elif status == "unreadable":
        gap = "AGENTS.md 无法读取：%s" % detail
    elif status == "parse-error":
        gap = "AGENTS.md 解析失败：%s" % detail
    elif status == "empty":
        gap = "%s —— 有标题但没正文，不算已声明硬约束" % detail
    else:
        gap = ("缺少 kb:id: dashboard.constraints，且 AGENTS.md 没有「硬约束」段"
               " —— 硬约束未声明，建议补上")
    return {"ok": False, "block": None, "source": None, "status": status,
            "detail": detail, "gap": gap}
