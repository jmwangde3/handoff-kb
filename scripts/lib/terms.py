#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询分词（无第三方依赖）

中文不切词，用「整段 + 二元组」近似：`网络问题` → `网络` / `络问` / `问题` / `网络问题`。
两个 CLI（kb-search / kb-context）共用，避免各写一套导致同一 query 结果不一致。
"""

from __future__ import annotations

import re

CJK_RUN = re.compile(r"^[\u3400-\u9fff]+$")

# 只含这些二元组的查询词当作噪声（中文常见虚词/动作词）
STOP_BIGRAMS = {
    "检查", "查看", "现在", "帮我", "一下", "这个", "那个", "什么", "怎么", "如何",
    "是否", "可以", "需要", "处理", "看看", "继续", "当前", "任务", "状态",
}


def parse(text: str):
    """返回去重后的查询词（保序）。引号内整体算一个短语。"""
    chunks = re.findall(r'"([^"]+)"|“([^”]+)”|(\S+)', text or "")
    out = []
    for chunk in chunks:
        s = next((x for x in chunk if x), "").strip()
        if not s:
            continue
        if CJK_RUN.match(s) and len(s) > 2:
            if s not in STOP_BIGRAMS:
                out.append(s)
            for i in range(len(s) - 1):
                bg = s[i:i + 2]
                if bg not in STOP_BIGRAMS:
                    out.append(bg)
        else:
            out.append(s)
    seen, uniq = set(), []
    for t in out:
        k = t.lower()
        if k and k not in seen:
            seen.add(k)
            uniq.append(t)
    return uniq
