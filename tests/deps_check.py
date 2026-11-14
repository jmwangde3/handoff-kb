#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查 scripts/ 只依赖标准库 + 本地 lib。

Python 标准库是**唯一必需依赖**。允许出现的可选第三方依赖只有：

    tiktoken     精确 BPE 计数（cl100k_base / o200k_base）
    tokenizers   DeepSeek 官方离线 tokenizer（deepseek_v4，读 tokenizer.json）

两者都必须满足：

  - 出现在**函数体内**，不能是模块顶层 import（缺包时模块仍可导入）
  - 包在一个**能捕获 ImportError 的 `try` 体内**：`except ImportError` /
    `except ModuleNotFoundError` / `except Exception` / 裸 `except` / 含上述
    类型的元组。`try/finally` 没有捕获能力，`except ValueError` 也接不住缺包。
  - handler 里的异常名必须是**裸名**或**明确限定为 `builtins.`**：
    `except ImportError` / `except builtins.ImportError` 算，
    `except local_lib.ImportError` 不算——那是另一个类，恰好同名而已。

其余任何第三方导入都算失败（退出码 1）。检查走完整 AST，不只看顶层：
`def f(): import requests` 这种写法同样会被抓出来。

晚加入标准库的模块（`STDLIB_LATE`）单独一条规则：它们在新版本里是标准库，
所以在 3.12 上 `sys.stdlib_module_names` 会放行——但 3.10 上根本没有这个模块，
缺了就是 ImportError。因此它们**不能**走标准库豁免，必须同样「函数内 + 能被
ImportError 接住」。这条按源码判断，不随当前解释器版本变化。

用法：
    py tests/deps_check.py                 # 检查 scripts/
    from deps_check import check_source    # 对任意源码字符串做同一套判断
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
STDLIB = set(sys.stdlib_module_names)
LOCAL = {"lib"}
OPTIONAL = {"tiktoken", "tokenizers"}

# 能被「缺包」触发的异常名。`Exception` / `BaseException` / 裸 `except` 也算：
# 现有代码有意用宽口径兜底，这比只catch一个名字更保守，不是更松。
IMPORT_ERRORS = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}

# 唯一允许的限定前缀。`except builtins.ImportError` 与 `except ImportError` 是同一个类；
# `except anything_else.ImportError` 不是——不看前缀只看最后一段就会把它当成兜底。
BUILTIN_MODULE = "builtins"

# 标准库但在低版本 Python 里还没有的模块。`sys.stdlib_module_names` 是按**当前
# 进程**的版本给的，所以 3.10 的 CI 会把 `import tomllib` 判成第三方——那是检查器
# 的错；但反过来，3.12 上它会直接放行，于是 3.10 的 ImportError 没人管。两种都错。
# 列在这里的模块按「可选依赖同款」规则处理：函数内 + 能被 ImportError 接住。
# 加条目等同于声明「这是标准库」，别拿它当第三方白名单用。
STDLIB_LATE = {
    "tomllib": "3.11 (PEP 680)",   # kb-hooks.py 用它校验 TOML，3.10 上跳过校验
}

# `except*`（3.11+）与 `except` 结构相同，按同一套规则看。
_TRY_TYPES = tuple(t for t in (getattr(ast, "Try", None), getattr(ast, "TryStar", None)) if t)


def _walk(node, ancestors=(), try_flags=()):
    """Yield (node, ancestors, try_flags).

    `try_flags` 是每层「本节点位于其 try 体内」的布尔元组：该 try 是否有一个能
    接住 ImportError 的 handler。空元组 = 不在任何 try 体内。

    只看 `Try.body`：`finally` 没有捕获能力，`handlers` / `orelse` 也不在保护范围内。
    """
    yield node, ancestors, try_flags
    body_ids = set()
    if isinstance(node, _TRY_TYPES):
        body_ids = {id(child) for child in node.body}
    for child in ast.iter_child_nodes(node):
        child_flags = try_flags
        if id(child) in body_ids:
            child_flags = try_flags + (_try_catches_import_error(node),)
        yield from _walk(child, ancestors + (node,), child_flags)


def _exception_name(node):
    """Bare name, or an explicitly `builtins.`-qualified one; anything else -> None.

    `except ImportError:`            -> "ImportError"
    `except builtins.ImportError:`   -> "ImportError"
    `except local_lib.ImportError:`  -> None   (a different class that shares a name)
    `except pkg.builtins.ImportError:` -> None (only the direct form is recognised)

    Matching on the last attribute segment alone would accept any module's exception
    that happens to be called `ImportError`, which is not the same class at all.
    Aliased modules (`import builtins as bi`) stay rejected on purpose: resolving
    aliases needs scope tracking, and the conservative direction is to reject.
    """
    if isinstance(node, ast.Name):
        return node.id
    if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == BUILTIN_MODULE):
        return node.attr
    return None


def _handler_catches_import_error(handler: ast.ExceptHandler) -> bool:
    """True if this single handler can catch an import failure."""
    exc_type = handler.type
    if exc_type is None:                       # bare `except:`
        return True
    if isinstance(exc_type, ast.Tuple):        # `except (ImportError, OSError):`
        return any(_exception_name(item) in IMPORT_ERRORS for item in exc_type.elts)
    return _exception_name(exc_type) in IMPORT_ERRORS


def _try_catches_import_error(node) -> bool:
    return any(_handler_catches_import_error(h) for h in node.handlers)


def _imported_names(node):
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name
    elif isinstance(node, ast.ImportFrom):
        if node.level == 0 and node.module:
            yield node.module


def check_source(source: str, filename: str = "<string>"):
    """Return a list of problems for one source text. Empty list means clean."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return ["%s: 语法错误 %s" % (filename, exc)]

    problems = []
    for node, ancestors, try_flags in _walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for name in _imported_names(node):
            root = name.split(".")[0]
            lineno = getattr(node, "lineno", 0)
            if root in LOCAL:
                continue
            in_function = any(
                isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef)) for a in ancestors)
            guarded = any(try_flags)

            if root in STDLIB_LATE:
                # 必须在标准库豁免之前判：3.12 认为它是标准库，3.10 认为它不存在。
                version = STDLIB_LATE[root]
                if not in_function:
                    problems.append(
                        "%s:%d: 晚加入标准库的 %s（%s）出现在模块顶层（低版本没有这个模块，"
                        "缺了会让整个脚本导入失败；请移到函数内）"
                        % (filename, lineno, name, version))
                elif not guarded:
                    problems.append(
                        "%s:%d: 晚加入标准库的 %s（%s）没有包在能捕获 ImportError 的 "
                        "try/except 中（低版本没有这个模块，必须显式兜底）"
                        % (filename, lineno, name, version))
                continue
            if root in STDLIB:
                continue
            if root not in OPTIONAL:
                problems.append(
                    "%s:%d: 第三方依赖 %s（必需依赖只能是 Python 标准库；"
                    "确需可选依赖请先加进 OPTIONAL 并说明理由）"
                    % (filename, lineno, name))
                continue
            if not in_function:
                problems.append(
                    "%s:%d: 可选依赖 %s 出现在模块顶层（缺包会让整个模块导入失败；"
                    "请移到函数内）" % (filename, lineno, name))
            elif not try_flags:
                problems.append(
                    "%s:%d: 可选依赖 %s 没有包在 try/except 中（缺包时必须能降级或明确报错）"
                    % (filename, lineno, name))
            elif not guarded:
                problems.append(
                    "%s:%d: 可选依赖 %s 的 try 接不住 ImportError（`finally`、"
                    "`except ValueError`、以及 `except 别的模块.ImportError` 都拦不住缺包；"
                    "只认裸名或 `builtins.` 限定；缺包时必须能降级或明确报错）"
                    % (filename, lineno, name))
    return problems


def main() -> int:
    problems = []
    for path in sorted(SCRIPTS.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        problems.extend(check_source(path.read_text(encoding="utf-8"), rel))

    if problems:
        for problem in problems:
            print("ERR: %s" % problem)
        return 1
    print("OK: scripts/ 只用标准库 + 本地 lib；可选依赖仅 %s（函数内 + 能被 ImportError 接住）；"
          "迟到的标准库 %s 同规则"
          % (", ".join(sorted(OPTIONAL)), ", ".join(sorted(STDLIB_LATE))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
