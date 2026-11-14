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

import hashlib
import os
import re

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")

HEURISTIC_DESC = "heuristic（CJK 1 字≈1 token，其余 4 字符≈1 token）"
DEEPSEEK_DESC = "deepseek_estimate（官方比例：1 英文字符≈0.3、1 中文字符≈0.6）"
DEEPSEEK_ENV = "KB_DEEPSEEK_TOKENIZER"
DEEPSEEK_DEFAULT_DIR = os.path.join(
    os.path.expanduser("~"), ".cache", "handoff-kb", "deepseek_v4_tokenizer")
DEEPSEEK_TOKENIZER_FILE = "tokenizer.json"
# 报告里只写「来源」，不写本机绝对路径；指纹靠 sha256 而不是路径。
DEEPSEEK_SOURCE = "DeepSeek official offline tokenizer (deepseek_tokenizer.zip → tokenizer.json)"
TIKTOKEN_SOURCE = "tiktoken encoder (bundled BPE ranks)"


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


def _sha256_file(path: str):
    """文件指纹；读不到就返回 None（报告里宁可缺指纹，也不写绝对路径）。"""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _library_version(module_name: str):
    try:
        module = __import__(module_name)
    except Exception:
        return None
    return getattr(module, "__version__", None) or "unknown"


def _deepseek_encoder():
    """加载 DeepSeek 官方 `tokenizer.json`（可选依赖 `tokenizers`）。"""
    path = os.path.join(deepseek_tokenizer_dir(), DEEPSEEK_TOKENIZER_FILE)
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
    """统一计数器。`count()` 是唯一入口。

    两个名字必须分开：

    - `requested`：用户要的是什么（原样进报告，不因回退而改写）
    - `mode`：**实际**用来计数的算法（`heuristic` / `deepseek_estimate` /
      `deepseek_v4` / `tiktoken`）

    两者只在「请求精确词表、词表缺失、且显式允许回退」时不同。早先 `count()`
    判的是 `requested`，于是回退后报告写着 `deepseek_estimate`、算出来的却是
    heuristic——元数据与结果对不上。现在 `count()` 只看 `mode`。
    """

    def __init__(self, requested: str = "heuristic", allow_fallback: bool = False):
        self.requested = (requested or "heuristic").strip()
        self.allow_fallback = allow_fallback
        self.encoder = None
        self.exact = False
        self.mode = "heuristic"
        self.desc = HEURISTIC_DESC
        # 可复现性指纹：来源 + 词表文件 + 词表 SHA256 + 库版本。
        # 只写名称与哈希，不写本机路径——报告要能公开。
        self.source = "heuristic"
        self.tokenizer_file = None
        self.tokenizer_sha256 = None
        self.library = None
        self.library_version = None
        if self.requested == "heuristic":
            return
        if self.requested == "deepseek_estimate":
            self.mode = "deepseek_estimate"
            self.desc = DEEPSEEK_DESC
            self.source = "documented ratio (0.3 / 0.6)"
            return
        if self.requested in ("deepseek_v4", "deepseek"):
            enc, path = _deepseek_encoder()
            if enc is not None:
                self.encoder = enc
                self.exact = True
                self.mode = "deepseek_v4"
                self.desc = "tokenizers:deepseek_v4"
                self.source = DEEPSEEK_SOURCE
                self.tokenizer_file = os.path.basename(path)
                self.tokenizer_sha256 = _sha256_file(path)
                self.library = "tokenizers"
                self.library_version = _library_version("tokenizers")
                return
            if not allow_fallback:
                raise TokenizerError(
                    "指定了 --tokenizer %s，但没有可用的 DeepSeek 离线 tokenizer。\n"
                    "  需要：pip install tokenizers，并把官方 deepseek_tokenizer.zip 解压到 %s\n"
                    "        （或设环境变量 %s 指向含 tokenizer.json 的目录）\n"
                    "  选项：1) 装好再跑；2) 用 --tokenizer deepseek_estimate（官方比例估算）；\n"
                    "        3) 明确接受估算并加 --allow-tokenizer-fallback"
                    % (self.requested, deepseek_tokenizer_dir(), DEEPSEEK_ENV))
            # 回退走 DeepSeek 官方比例，不是 heuristic：这是请求 deepseek 的唯一合理降级。
            self.mode = "deepseek_estimate"
            self.desc = ("deepseek_estimate（请求 %s 不可用，已按 --allow-tokenizer-fallback "
                         "回退；exact=false）" % self.requested)
            self.source = "estimate (fallback)"
            return
        enc = _tiktoken_encoder(self.requested)
        if enc is not None:
            self.encoder = enc
            self.exact = True
            self.mode = "tiktoken"
            self.desc = "tiktoken:%s" % self.requested
            self.source = TIKTOKEN_SOURCE
            self.library = "tiktoken"
            self.library_version = _library_version("tiktoken")
        elif not allow_fallback:
            raise TokenizerError(
                "指定了 --tokenizer %s，但当前环境没有可用的 tiktoken 编码器。\n"
                "  选项：1) 安装 tiktoken；2) 用 --tokenizer heuristic（估算）；\n"
                "        3) 明确接受估算并加 --allow-tokenizer-fallback"
                % self.requested)
        else:
            self.mode = "heuristic"
            self.desc = ("heuristic（请求 %s 不可用，已按 --allow-tokenizer-fallback "
                         "回退；exact=false）" % self.requested)
            self.source = "estimate (fallback)"

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self.encoder is not None:
            try:
                if self.mode == "deepseek_v4":
                    return len(self.encoder.encode(text, add_special_tokens=False).ids)
                return len(self.encoder.encode(text))
            except Exception:
                raise TokenizerError("tokenizer 编码失败（%s）；重跑或改用 heuristic"
                                     % self.desc)
        if self.mode == "deepseek_estimate":
            return deepseek_estimate(text)
        return heuristic(text)

    def as_dict(self) -> dict:
        """报告用结构：无绝对路径，带足以判定「两次是否同一套词表」的指纹。"""
        return {
            "requested": self.requested,
            "effective_mode": self.mode,
            "actual": self.desc,
            "exact": self.exact,
            "source": self.source,
            "tokenizer_file": self.tokenizer_file,
            "tokenizer_sha256": self.tokenizer_sha256,
            "library": self.library,
            "library_version": self.library_version,
        }


def estimate(text: str, tokenizer: str = "heuristic"):
    """兼容旧接口：返回 (tokens, 说明)。缺编码器时降级并标明（只用于只读工具）。"""
    if tokenizer == "deepseek_estimate":
        return deepseek_estimate(text), DEEPSEEK_DESC
    if tokenizer in ("deepseek_v4", "deepseek"):
        enc, path = _deepseek_encoder()
        if enc is not None:
            try:
                return (len(enc.encode(text or "", add_special_tokens=False).ids),
                        "tokenizers:deepseek_v4")
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
    """计数器描述是否代表精确词表。

    精确实现有两种前缀：`tiktoken:<编码器>` 与 `tokenizers:deepseek_v4`。
    估算路径（`heuristic…` / `deepseek_estimate…` / 回退串）一律为 False。
    """
    text = str(desc)
    return text.startswith("tiktoken:") or text.startswith("tokenizers:")
