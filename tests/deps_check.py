#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查 scripts/ 只依赖标准库 + 本地 lib。

`tiktoken` 是**唯一**允许出现的可选依赖，且必须满足：
  - 只在函数内 import（不在模块顶层）
  - 被 try/except 包住（缺包时降级到启发式估算）
其余任何第三方导入都算失败（退出码 1）。

用法：py tests/deps_check.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
STDLIB = set(sys.stdlib_module_names)
LOCAL = {"lib"}
OPTIONAL = {"tiktoken"}


def top_level_imports(tree):
    """只遍历模块顶层的 import 节点。"""
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node


def names(node):
    if isinstance(node, ast.Import):
        for a in node.names:
            yield a.name
    elif node.level == 0 and node.module:
        yield node.module


def main() -> int:
    problems = []
    for path in sorted(SCRIPTS.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            problems.append("%s: 语法错误 %s" % (rel, exc))
            continue
        for node in top_level_imports(tree):
            for name in names(node):
                root = name.split(".")[0]
                if root in STDLIB or root in LOCAL:
                    continue
                if root in OPTIONAL:
                    problems.append("%s: 可选依赖 %s 出现在模块顶层（应在函数内 try/except）"
                                    % (rel, name))
                else:
                    problems.append("%s: 第三方依赖 %s" % (rel, name))
    if problems:
        for p in problems:
            print("ERR: %s" % p)
        return 1
    print("OK: scripts/ 只用标准库 + 本地 lib；可选依赖仅 %s（函数内 try/except）"
          % ", ".join(sorted(OPTIONAL)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
