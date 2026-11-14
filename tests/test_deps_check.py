#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`tests/deps_check.py` 自己的测试。

存在理由：依赖检查是「CI 能不能发现新增第三方依赖」的唯一护栏，护栏本身
没测过就等于没有。这里既测判据（各种写法该红还是该绿），也测仓库现状
（scripts/ 当前是干净的），还钉住「可选依赖清单只能是 tiktoken 与 tokenizers」
——这样以后有人往清单里加第三个包，测试会先响。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import deps_check  # noqa: E402


def problems(source: str):
    return deps_check.check_source(source, "sample.py")


class Allowed(unittest.TestCase):
    def test_stdlib(self):
        self.assertEqual(problems("import os\nimport json\nfrom pathlib import Path\n"), [])

    def test_local_lib(self):
        self.assertEqual(problems("from lib import tokens\nfrom lib.tokens import TokenCounter\n"), [])

    def test_optional_inside_try(self):
        source = (
            "def count(text):\n"
            "    try:\n"
            "        import tiktoken\n"
            "    except Exception:\n"
            "        return None\n"
            "    return tiktoken.get_encoding('o200k_base')\n"
        )
        self.assertEqual(problems(source), [])

    def test_both_optional_packages_are_declared(self):
        self.assertEqual(deps_check.OPTIONAL, {"tiktoken", "tokenizers"},
                         "可选依赖清单变了：新增第三方包必须先改文档与理由，"
                         "并同步 README 的依赖声明")


class Rejected(unittest.TestCase):
    def test_optional_at_module_level(self):
        found = problems("import tokenizers\n")
        self.assertEqual(len(found), 1)
        self.assertIn("模块顶层", found[0])

    def test_optional_without_try(self):
        found = problems("def load():\n    import tiktoken\n    return tiktoken\n")
        self.assertEqual(len(found), 1)
        self.assertIn("try/except", found[0])

    def test_unknown_package_even_when_nested(self):
        """核心用例：函数内 + try/except 也不能引入新的第三方依赖。"""
        source = (
            "def f():\n"
            "    try:\n"
            "        import requests\n"
            "    except Exception:\n"
            "        return None\n"
        )
        found = problems(source)
        self.assertEqual(len(found), 1)
        self.assertIn("第三方依赖 requests", found[0])

    def test_unknown_package_in_class_body(self):
        found = problems("class C:\n    import numpy\n")
        self.assertEqual(len(found), 1)
        self.assertIn("第三方依赖 numpy", found[0])

    def test_from_import_is_checked(self):
        found = problems("from tokenizers import Tokenizer\n")
        self.assertEqual(len(found), 1)
        self.assertIn("模块顶层", found[0])

    def test_syntax_error_is_reported(self):
        found = problems("def broken(:\n")
        self.assertEqual(len(found), 1)
        self.assertIn("语法错误", found[0])


class RepositoryState(unittest.TestCase):
    def test_scripts_directory_is_clean(self):
        found = []
        for path in sorted(deps_check.SCRIPTS.rglob("*.py")):
            rel = path.relative_to(deps_check.ROOT).as_posix()
            found.extend(deps_check.check_source(path.read_text(encoding="utf-8"), rel))
        self.assertEqual(found, [], "scripts/ 出现未声明的依赖：\n%s" % "\n".join(found))


if __name__ == "__main__":
    unittest.main(verbosity=2)
