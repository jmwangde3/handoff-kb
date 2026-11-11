#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Token 计数（handoff-kb 2.0.1）

- 默认 `heuristic`：CJK 1 字 ≈ 1 token，其余 4 字符 ≈ 1 token（**估算**）
- `tiktoken:<编码器>`：真实 BPE 计数（可选依赖，未安装时默认报错，不静默回退）
- 一次构建只初始化一个 `TokenCounter`，所有块、包装、benchmark 都用同一个

调用方永远不要自己 `len(text)` 或另建计数器，否则会出现「顶部显示
tiktoken:o200k_base，块内却按启发式算」的不一致。
"""

from __future__ import annotations

import re

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")

HEURISTIC_DESC = "heuristic（CJK 1 字≈1 token，其余 4 字符≈1 token）"


class TokenizerError(Exception):
    pass


def _tiktoken_encoder(name: str):
    try:
        import tiktoken  # 可选依赖，未安装则为 None
    except Exception:
        return None
    try:
        if name in ("cl100k_base", "o200k_base", "p50k_base", "r50k_base"):
            return tiktoken.get_encoding(name)
        return tiktoken.encoding_for_model(name)
    except Exception:
        return None


def heuristic(text: str) -> int:
    """CJK 按字、其余按 4 字符折 token。"""
    if not text:
        return 0
    cjk = len(CJK_RE.findall(text))
    rest = max(len(text) - cjk, 0)
    return int(round(cjk + rest / 4.0))


class TokenCounter:
    """统一计数器。`count()` 是唯一入口。"""

    def __init__(self, requested: str = "heuristic", allow_fallback: bool = False):
        self.requested = (requested or "heuristic").strip()
        self.allow_fallback = allow_fallback
        self.encoder = None
        self.exact = False
        self.desc = HEURISTIC_DESC
        if self.requested != "heuristic":
            enc = _tiktoken_encoder(self.requested)
            if enc is not None:
                self.encoder = enc
                self.exact = True
                self.desc = "tiktoken:%s" % self.requested
            elif not allow_fallback:
                raise TokenizerError(
                    "指定了 --tokenizer %s，但当前环境没有可用的 tiktoken 编码器。\n"
                    "  选项：1) 安装 tiktoken；2) 用 --tokenizer heuristic（估算）；\n"
                    "        3) 明确接受估算并加 --allow-tokenizer-fallback"
                    % self.requested)
            else:
                self.desc = ("heuristic（请求 %s 不可用，已按 --allow-tokenizer-fallback "
                             "回退；exact=false）" % self.requested)

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self.encoder is not None:
            try:
                return len(self.encoder.encode(text))
            except Exception:
                raise TokenizerError("tiktoken 编码失败（%s）；重跑或改用 heuristic"
                                     % self.requested)
        return heuristic(text)

    def as_dict(self) -> dict:
        return {"requested": self.requested, "actual": self.desc,
                "exact": self.exact}


def estimate(text: str, tokenizer: str = "heuristic"):
    """兼容旧接口：返回 (tokens, 说明)。缺编码器时降级并标明（只用于只读工具）。"""
    if tokenizer and tokenizer != "heuristic":
        enc = _tiktoken_encoder(tokenizer)
        if enc is not None:
            try:
                return len(enc.encode(text or "")), "tiktoken:%s" % tokenizer
            except Exception:
                pass
        return heuristic(text), "heuristic（未找到 tokenizer %r，已降级估算）" % tokenizer
    return heuristic(text), HEURISTIC_DESC


def is_exact(desc: str) -> bool:
    return str(desc).startswith("tiktoken:")
