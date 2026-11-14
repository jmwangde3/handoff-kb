#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查 scripts/ 只依赖标准库 + 本地 lib。

Python 标准库是**唯一必需依赖**。允许出现的可选第三方依赖只有：

    tiktoken     精确 BPE 计数（cl100k_base / o200k_base）
    tokenizers   DeepSeek 官方离线 tokenizer（deepseek_v4，读 tokenizer.json）

两者都必须满足：

  - 出现在**函数体内**，不能是模块顶层 import（缺包时模块仍可导入）
  - 包在 `try` / `except` 中（缺包时降到带标注的估算，或明确报错退出 2）

其余任何第三方导入都算失败（退出码 1）。检查走完整 AST，不只看顶层：
`def f(): import requests` 这种写法同样会被抓出来。

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

# 标准库但在低版本 Python 里还没有的模块。`sys.stdlib_module_names` 是按**当前进程**
# 的版本给的，所以 3.10 的 CI 会把 `import tomllib` 判成第三方——那是检查器的错，
# 不是代码的错。列在这里的模块必须同时满足：新版标准库 + 调用点自带版本兜底
# （函数内 try/except，缺模块时降级并说明）。加条目等同于声明「这是标准库」，
# 别拿它当第三方白名单用。
STDLIB_LATE = {
    "tomllib": "3.11 (PEP 680)",   # kb-hooks.py 用它校验 TOML，3.10 上跳过校验
}


def _walk(node, ancestors=(), guarded=False):
    """Yield (node, ancestors, guarded_by_try) for every node in the tree."""
    yield node, ancestors, guarded
    body_ids = set()
    if isinstance(node, ast.Try):
        body_ids = {id(child) for child in node.body}
    for child in ast.iter_child_nodes(node):
        yield from _walk(child, ancestors + (node,), guarded or id(child) in body_ids)


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
    for node, ancestors, guarded in _walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for name in _imported_names(node):
            root = name.split(".")[0]
            if root in STDLIB or root in STDLIB_LATE or root in LOCAL:
                continue
            lineno = getattr(node, "lineno", 0)
            if root not in OPTIONAL:
                problems.append(
                    "%s:%d: 第三方依赖 %s（必需依赖只能是 Python 标准库；"
                    "确需可选依赖请先加进 OPTIONAL 并说明理由）"
                    % (filename, lineno, name))
                continue
            in_function = any(
                isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef)) for a in ancestors)
            if not in_function:
                problems.append(
                    "%s:%d: 可选依赖 %s 出现在模块顶层（缺包会让整个模块导入失败；"
                    "请移到函数内）" % (filename, lineno, name))
            elif not guarded:
                problems.append(
                    "%s:%d: 可选依赖 %s 没有包在 try/except 中（缺包时必须能降级或明确报错）"
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
    print("OK: scripts/ 只用标准库 + 本地 lib；可选依赖仅 %s（函数内 try/except）"
          % ", ".join(sorted(OPTIONAL)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
