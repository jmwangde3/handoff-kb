#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共享协议常量（handoff-kb 2.0）

所有脚本共用：文件角色判定、保留编号、ID 格式、必备章节、事实元数据键。
改动此文件等于改协议，需同步 references/protocol-v2.md 与 assets/ 模板。
"""

from __future__ import annotations

import re

SCHEMA_VERSION = 2

# 保留编号：这些编号永远属于固定层，不得用作事实分册
RESERVED_NUMBERS = {0: "baseline", 5: "dashboard", 6: "log", 90: "archive"}

# 事实分册编号：新建用 10–17（最多 8 条线）；旧库的 01–04 继续合法
FACT_RANGE = (10, 17)
LEGACY_FACT_RANGE = (1, 4)
MAX_LINES = 8

# 规范文件名（新库）；旧库按别名识别
CANON_BASELINE = ("00_基线.md", "00_baseline.md")
CANON_DASHBOARD = ("05_进度仪表盘.md", "05_dashboard.md")
CANON_LOG = ("06_会话日志.md", "06_log.md")
CANON_ARCHIVE = ("90_过程档案.md", "90_archive.md")
SHARD_DIR = "06_流水"
ENTRY_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")

# 宽松模式下的目录别名（作用在目录名上）：`60_流水/`、`90_归档/` 等自有命名
SHARD_DIR_RE = re.compile(r"^(?:\d{2,3}[_\- ]?)?(?:流水|会话流水|shards?|sessions?)$", re.I)
ARCHIVE_DIR_RE = re.compile(r"^(?:\d{2,3}[_\- ]?)?(?:归档|旧档|历史|archive|archived)$", re.I)

# 宽松模式的别名（正则，作用在文件名上）
ALIASES = {
    "dashboard": re.compile(r"(进度|现状|dashboard|status)", re.I),
    "baseline": re.compile(r"(INDEX|索引|baseline|基线)", re.I),
    "log": re.compile(r"(流水|日志|log|handoff)", re.I),
    "archive": re.compile(r"(归档|archive)", re.I),
}

FACT_NAME_RE = re.compile(r"^(\d{2})_.+\.md$")
SHARD_SUFFIX = ".md"

# 事实 / 结论 ID：K-01 / G-007
FACT_ID_RE = re.compile(r"\b([KG]-\d{2,3})\b")
SECTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
KB_ID_COMMENT_RE = re.compile(r"^\s*<!--\s*kb:id:\s*([A-Za-z0-9][A-Za-z0-9_.:-]*)\s*-->\s*$")
KB_SCHEMA_COMMENT_RE = re.compile(r"^\s*<!--\s*kb:schema:\s*(\d+)\s*-->\s*$")

# 状态取值（中英都收）
STATUS_VALID = {"有效", "valid", "active"}
STATUS_PENDING = {"待核", "pending", "unverified", "todo"}
STATUS_SUPERSEDED = {"已作废", "作废", "superseded", "deprecated"}

VOLATILITY = {"stable", "dynamic"}

FACT_META_KEYS = ("status", "evidence", "verified_at", "owner", "volatility", "superseded_by")

# 交接检查依赖的章节 ID
REQUIRED_SECTION_IDS = ("dashboard.current", "dashboard.next")

# 供 kb-context 使用的"硬约束"章节 ID（任何预算下都不丢）
SAFETY_SECTION_IDS = ("dashboard.constraints", "dashboard.safety")

# 体积统计/检索默认跳过的资料目录（小写比较）
DATA_DIRS = {
    "ai_files", "assets", "data", "output", "evidence", "paktools",
    "build", "dist", "vendor", "tmp", "node_modules", "__pycache__",
    ".git", ".kb-txn", ".kb.lock", ".venv", "venv", ".idea", ".vscode",
    # 解包/工具产物与备份残留：正文里出现这些目录基本都是数据，不是交接文档
    "unpack", "unpacked", "_tmp", ".trash",
    # AI 客户端的规则/记忆目录。里面的 md 是 agent 工作日志（当天流水、项目索引卡），
    # 不是交接正文：进去检索会拿到「某天做过什么」，把真正的分册结论挤出预算。
    # 实测某库 50 个待检索文件里 16 个属于这类，且 .workbuddy/memory 常是 .shared/memory
    # 的软链，同一份内容被算两遍、命中分翻倍，更容易抢占 P4 名额。
    ".workbuddy", ".shared", ".codex", ".qoder", ".trae", ".claude",
    ".cursor", ".gemini", ".aider", ".continue", ".windsurf", ".agents",
    ".kiro", ".zed", ".junie",
}

MAX_TEXT_BYTES = 2 * 1024 * 1024  # 超过按数据产物处理

TEXT_EXTS = (".md", ".txt")


def number_of(name: str):
    """从 `NN_xxx.md` 取编号；不是该形式返回 None。"""
    m = FACT_NAME_RE.match(name)
    if not m:
        return None
    return int(m.group(1))


def role_of_name(name: str, loose: bool = False):
    """按文件名判定角色：entry/baseline/dashboard/log/shard/fact/archive/other。

    loose=True 时允许别名（*进度* / *INDEX* / *流水* 等）。
    """
    if name in ENTRY_FILES:
        return "entry"
    num = number_of(name)
    if num is not None:
        if num == 0:
            return "baseline"
        if num == 5:
            return "dashboard"
        if num == 6:
            return "log"
        if num == 90:
            return "archive"
        if FACT_RANGE[0] <= num <= FACT_RANGE[1]:
            return "fact"
        if LEGACY_FACT_RANGE[0] <= num <= LEGACY_FACT_RANGE[1]:
            return "fact"
    if loose:
        for role in ("dashboard", "log", "baseline", "archive"):
            if ALIASES[role].search(name):
                return role
        # 自有命名项目的数字分册兜底：`20_数据与解包` / `30_mod开发` / `50_死路与坑`
        # 不在 10–17 规范区间，但同样是事实线。别名先判，避免把 `60_进度` 吞成 fact。
        if num is not None:
            return "fact"
    return "other"


def fact_shard_range_text() -> str:
    return "%02d–%02d" % FACT_RANGE
