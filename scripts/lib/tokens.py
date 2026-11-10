#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Token 估算（handoff-kb 2.0）

默认启发式：中文（CJK）按 1 字 ≈ 1 token，其余按 4 字符 ≈ 1 token。
这是**估算**，不是任何 API 的计费值；只有用户自带 tiktoken 且指定模型时才用真实计数，
且必须在输出里标明用的是哪个编码器。
"""

from __future__ import annotations

import re

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")


def heuristic(text: str) -> int:
    if not text:
        return 0
    cjk = len(CJK_RE.findall(text))
    rest = max(len(text) - cjk, 0)
    return int(round(cjk + rest / 4.0))


def _tiktoken_encoder(name: str):
    try:
        import tiktoken  # 可选依赖，未安装则为 None
    except Exception:
        return None
    try:
        if name in ("cl100k_base", "o200k_base"):
            return tiktoken.get_encoding(name)
        return tiktoken.encoding_for_model(name)
    except Exception:
        return None


def estimate(text: str, tokenizer: str = "heuristic"):
    """返回 (tokens, 说明)。说明用于输出，避免把估算说成实测。"""
    if tokenizer and tokenizer != "heuristic":
        enc = _tiktoken_encoder(tokenizer)
        if enc is not None:
            try:
                return len(enc.encode(text or "")), "tiktoken:%s" % tokenizer
            except Exception:
                pass
        return heuristic(text), "heuristic（未找到 tokenizer %r，已降级估算）" % tokenizer
    return heuristic(text), "heuristic（CJK 1 字≈1 token，其余 4 字符≈1 token）"


def is_exact(desc: str) -> bool:
    return desc.startswith("tiktoken:")
