#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""敏感信息检测（handoff-kb 2.0）

单一实现，供 kb-init / kb-check / kb-write 共用；命中即阻断提交或写入报告。
只做本地正则匹配，不联网、不外传。
"""

from __future__ import annotations

import re
from pathlib import Path

PATTERNS = [
    ("云厂商 AK", re.compile(r"\bLTAI[0-9A-Za-z]{8,}\b")),
    ("AWS AK", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("私钥 PEM", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("明文口令/令牌", re.compile(
        r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\b\s*[:=]\s*"
        r"['\"][^'\"\s$]{6,}['\"]")),
    ("API key", re.compile(r"\bsk-[0-9A-Za-z]{20,}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z]{20,}\b")),
    ("Bearer token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}")),
]

# 明确的占位符/示例值不算命中
ALLOWLIST = re.compile(
    r"(?i)(your[_-]?|<|\$|\{\{|xxx+|placeholder|example|changeme|redacted|\*\*\*)")


def scan_text(text: str):
    """返回 [(标签, 行号, 命中片段)]，行号 1 基。"""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        for label, rx in PATTERNS:
            for m in rx.finditer(line):
                snippet = m.group(0)
                if ALLOWLIST.search(snippet):
                    continue
                hits.append((label, i, snippet[:80]))
    return hits


def scan_file(path: Path):
    try:
        data = Path(path).read_bytes()
    except OSError:
        return []
    if len(data) > 4 * 1024 * 1024:
        return []
    if b"\x00" in data[:2048]:
        return []
    return scan_text(data.decode("utf-8", errors="replace"))


def scan_paths(paths):
    """返回 [(相对路径, 标签, 行号, 片段)]。"""
    out = []
    for p in paths:
        for label, lineno, snip in scan_file(Path(p)):
            out.append((str(p), label, lineno, snip))
    return out


def has_secret(text: str) -> bool:
    return bool(scan_text(text))
