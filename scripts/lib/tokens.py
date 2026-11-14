#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Token 计数（handoff-kb 2.0.4）

- 默认 `heuristic`：CJK 1 字 ≈ 1 token，其余 4 字符 ≈ 1 token（**估算**）
- `tiktoken:<编码器>`：真实 BPE 计数（可选依赖，未安装时默认报错，不静默回退）
- `deepseek_v4`：DeepSeek 官方离线 tokenizer（`tokenizers` + `tokenizer.json`，可选依赖）
- `deepseek_estimate`：DeepSeek 官方换算比例（1 英文字符 ≈ 0.3、1 中文字符 ≈ 0.6），**仅估算**
- 一次构建只初始化一个 `TokenCounter`，所有块、包装、benchmark 都用同一个

调用方永远不要自己 `len(text)` 或另建计数器，否则会出现「顶部显示
tiktoken:o200k_base，块内却按启发式算」的不一致。
"""

from __future__ import annotations

import os
import re

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")

HEURISTIC_DESC = "heuristic（CJK 1 字≈1 token，其余 4 字符≈1 token）"
DEEPSEEK_DESC = "deepseek_estimate（官方比例：1 英文字符≈0.3、1 中文字符≈0.6）"
DEEPSEEK_ENV = "KB_DEEPSEEK_TOKENIZER"
DEEPSEEK_DEFAULT_DIR = os.path.join(
    os.path.expanduser("~"), ".cache", "handoff-kb", "deepseek_v4_tokenizer")


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


def deepseek_tokenizer_dir() -> str:
    """DeepSeek 离线 tokenizer 目录：环境变量优先，其次约定缓存路径。"""
    return os.environ.get(DEEPSEEK_ENV) or DEEPSEEK_DEFAULT_DIR


def _deepseek_encoder():
    """加载 DeepSeek 官方 `tokenizer.json`（可选依赖 `tokenizers`）。"""
    path = os.path.join(deepseek_tokenizer_dir(), "tokenizer.json")
    if not os.path.isfile(path):
        return None, path
    try:
        import tokenizers  # 可选依赖，未安装则为 None
    except Exception:
        return None, path
    try:
        return tokenizers.Tokenizer.from_file(path), path
    except Exception:
        return None, path


def heuristic(text: str) -> int:
    """CJK 按字、其余按 4 字符折 token。"""
    if not text:
        return 0
    cjk = len(CJK_RE.findall(text))
    rest = max(len(text) - cjk, 0)
    return int(round(cjk + rest / 4.0))


def deepseek_estimate(text: str) -> int:
    """DeepSeek 官方换算比例（估算）：1 英文字符 ≈ 0.3 token，1 中文字符 ≈ 0.6 token。

    只用于「按官方口径估一下」，**不是账单**；要精确用 `deepseek_v4` 的离线 tokenizer。
    """
    if not text:
        return 0
    cjk = len(CJK_RE.findall(text))
    rest = max(len(text) - cjk, 0)
    return int(round(cjk * 0.6 + rest * 0.3))


class TokenCounter:
    """统一计数器。`count()` 是唯一入口。"""

    def __init__(self, requested: str = "heuristic", allow_fallback: bool = False):
        self.requested = (requested or "heuristic").strip()
        self.allow_fallback = allow_fallback
        self.encoder = None
        self.exact = False
        self.desc = HEURISTIC_DESC
        if self.requested == "heuristic":
            return
        if self.requested == "deepseek_estimate":
            self.desc = DEEPSEEK_DESC
            return
        if self.requested in ("deepseek_v4", "deepseek"):
            enc, path = _deepseek_encoder()
            if enc is not None:
                self.encoder = enc
                self.exact = True
                self.desc = "tokenizers:deepseek_v4(%s)" % path
                return
            if not allow_fallback:
                raise TokenizerError(
                    "指定了 --tokenizer %s，但没有可用的 DeepSeek 离线 tokenizer。\n"
                    "  需要：pip install tokenizers，并把官方 deepseek_tokenizer.zip 解压到 %s\n"
                    "        （或设环境变量 %s 指向含 tokenizer.json 的目录）\n"
                    "  选项：1) 装好再跑；2) 用 --tokenizer deepseek_estimate（官方比例估算）；\n"
                    "        3) 明确接受估算并加 --allow-tokenizer-fallback"
                    % (self.requested, deepseek_tokenizer_dir(), DEEPSEEK_ENV))
            self.desc = ("deepseek_estimate（请求 %s 不可用，已按 --allow-tokenizer-fallback "
                         "回退；exact=false）" % self.requested)
            return
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
                if self.requested in ("deepseek_v4", "deepseek"):
                    return len(self.encoder.encode(text, add_special_tokens=False).ids)
                return len(self.encoder.encode(text))
            except Exception:
                raise TokenizerError("tokenizer 编码失败（%s）；重跑或改用 heuristic"
                                     % self.requested)
        if self.requested == "deepseek_estimate":
            return deepseek_estimate(text)
        return heuristic(text)

    def as_dict(self) -> dict:
        return {"requested": self.requested, "actual": self.desc,
                "exact": self.exact}


def estimate(text: str, tokenizer: str = "heuristic"):
    """兼容旧接口：返回 (tokens, 说明)。缺编码器时降级并标明（只用于只读工具）。"""
    if tokenizer == "deepseek_estimate":
        return deepseek_estimate(text), DEEPSEEK_DESC
    if tokenizer in ("deepseek_v4", "deepseek"):
        enc, path = _deepseek_encoder()
        if enc is not None:
            try:
                return (len(enc.encode(text or "", add_special_tokens=False).ids),
                        "tokenizers:deepseek_v4(%s)" % path)
            except Exception:
                pass
        return deepseek_estimate(text), ("deepseek_estimate（未找到 DeepSeek tokenizer，"
                                         "已按官方比例降级估算）")
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
