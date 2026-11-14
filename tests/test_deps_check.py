#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`tests/deps_check.py` 自己的测试。

存在理由：依赖检查是「CI 能不能发现新增第三方依赖」的唯一护栏，护栏本身
没测过就等于没有。这里既测判据（各种写法该红还是该绿），也测仓库现状
（scripts/ 当前是干净的），还钉住「可选依赖清单只能是 tiktoken 与 tokenizers」
——这样以后有人往清单里加第三个包，测试会先响。

两条曾经真实漏过的判据，各自有专门用例：

- `try/finally` 与 `except ValueError` 曾被当成「已兜底」。它们接不住缺包。
- `tomllib` 曾整条豁免，于是 3.10 的 ImportError 没人管；在 3.12 上
  `sys.stdlib_module_names` 又会让它直接过——两种版本两种错法。现在它按
  「函数内 + 能被 ImportError 接住」判，且判据与当前解释器版本无关。
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

    def test_optional_with_import_error_handler(self):
        source = (
            "def load():\n"
            "    try:\n"
            "        import tokenizers\n"
            "    except ImportError:\n"
            "        return None\n"
        )
        self.assertEqual(problems(source), [])

    def test_optional_with_module_not_found_handler(self):
        source = (
            "def load():\n"
            "    try:\n"
            "        import tokenizers\n"
            "    except ModuleNotFoundError:\n"
            "        return None\n"
        )
        self.assertEqual(problems(source), [])

    def test_optional_with_tuple_of_import_errors(self):
        source = (
            "def load():\n"
            "    try:\n"
            "        import tiktoken\n"
            "    except (ImportError, OSError):\n"
            "        return None\n"
        )
        self.assertEqual(problems(source), [])

    def test_optional_with_bare_except(self):
        source = (
            "def load():\n"
            "    try:\n"
            "        import tiktoken\n"
            "    except:\n"
            "        return None\n"
        )
        self.assertEqual(problems(source), [])

    def test_outer_try_may_guard_inner_try(self):
        """An inner `except ValueError` is harmless if an outer handler catches imports."""
        source = (
            "def load():\n"
            "    try:\n"
            "        try:\n"
            "            import tokenizers\n"
            "        except ValueError:\n"
            "            pass\n"
            "    except ImportError:\n"
            "        return None\n"
        )
        self.assertEqual(problems(source), [])

    def test_both_optional_packages_are_declared(self):
        self.assertEqual(deps_check.OPTIONAL, {"tiktoken", "tokenizers"},
                         "可选依赖清单变了：新增第三方包必须先改文档与理由，"
                         "并同步 README 的依赖声明")

    def test_late_stdlib_with_proper_handling(self):
        """`tomllib` 是 3.11 才进标准库的，3.10 上 `import tomllib` 会 ImportError。

        3.10 的 CI 曾把 `kb-hooks.py` 里那句受控的 `import tomllib` 判成第三方依赖，
        于是六个环境里两个红。现在它不在标准库豁免里，而是按可选依赖同款规则检查：
        函数内 + 能被 ImportError 接住。
        """
        source = (
            "def validate(text):\n"
            "    try:\n"
            "        import tomllib\n"
            "    except Exception:\n"
            "        return None\n"
            "    return tomllib.loads(text)\n"
        )
        self.assertEqual(problems(source), [])

    def test_late_stdlib_list_is_not_a_whitelist(self):
        """迟到的标准库清单不能顺手当成第三方白名单用。

        钉住三件事：清单里只有真·标准库迟到模块；它不是 OPTIONAL；往里加东西
        必须同时改这条用例——加错的那一刻就红。
        """
        self.assertEqual(set(deps_check.STDLIB_LATE), {"tomllib"},
                         "STDLIB_LATE 只能放真正的标准库迟到模块；"
                         "第三方包请走 OPTIONAL 并写理由")
        self.assertFalse(set(deps_check.STDLIB_LATE) & deps_check.OPTIONAL,
                         "同名的模块不能既是标准库又是可选第三方")
        # 加进 STDLIB_LATE 不会顺带放宽「未知第三方」判据
        found = problems("def f():\n    try:\n        import requests\n    except Exception:\n        pass\n")
        self.assertEqual(len(found), 1, "未知第三方依赖必须照旧被拒")


class Rejected(unittest.TestCase):
    def test_optional_at_module_level(self):
        found = problems("import tokenizers\n")
        self.assertEqual(len(found), 1)
        self.assertIn("模块顶层", found[0])

    def test_optional_without_try(self):
        found = problems("def load():\n    import tiktoken\n    return tiktoken\n")
        self.assertEqual(len(found), 1)
        self.assertIn("try/except", found[0])

    def test_optional_inside_try_finally(self):
        """`finally` runs either way; it cannot absorb a missing package."""
        source = (
            "def load():\n"
            "    try:\n"
            "        import tokenizers\n"
            "    finally:\n"
            "        pass\n"
        )
        found = problems(source)
        self.assertEqual(len(found), 1)
        self.assertIn("接不住 ImportError", found[0])

    def test_optional_with_non_import_except(self):
        """`except ValueError` never sees ImportError."""
        source = (
            "def load():\n"
            "    try:\n"
            "        import tokenizers\n"
            "    except ValueError:\n"
            "        pass\n"
        )
        found = problems(source)
        self.assertEqual(len(found), 1)
        self.assertIn("接不住 ImportError", found[0])

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

    def test_unknown_package_in_nested_function(self):
        source = (
            "def outer():\n"
            "    def inner():\n"
            "        try:\n"
            "            import numpy\n"
            "        except Exception:\n"
            "            return None\n"
            "    return inner\n"
        )
        found = problems(source)
        self.assertEqual(len(found), 1)
        self.assertIn("第三方依赖 numpy", found[0])

    def test_unknown_package_in_class_body(self):
        found = problems("class C:\n    import numpy\n")
        self.assertEqual(len(found), 1)
        self.assertIn("第三方依赖 numpy", found[0])

    def test_from_import_is_checked(self):
        found = problems("from tokenizers import Tokenizer\n")
        self.assertEqual(len(found), 1)
        self.assertIn("模块顶层", found[0])

    def test_late_stdlib_at_module_level(self):
        """The interpreter is not the judge: `tomllib` exists on 3.11+ and still fails here."""
        found = problems("import tomllib\n")
        self.assertEqual(len(found), 1)
        self.assertIn("模块顶层", found[0])
        self.assertIn("tomllib", found[0])

    def test_late_stdlib_in_function_without_try(self):
        found = problems("def f():\n    import tomllib\n    return tomllib.loads('')\n")
        self.assertEqual(len(found), 1)
        self.assertIn("try/except", found[0])

    def test_late_stdlib_inside_try_finally(self):
        source = (
            "def f():\n"
            "    try:\n"
            "        import tomllib\n"
            "    finally:\n"
            "        pass\n"
        )
        found = problems(source)
        self.assertEqual(len(found), 1)
        self.assertIn("try/except", found[0])

    def test_late_stdlib_rule_does_not_depend_on_the_running_interpreter(self):
        """On 3.12+ `tomllib` is in `sys.stdlib_module_names`; that must not exempt it."""
        if "tomllib" not in deps_check.STDLIB:
            self.skipTest("this interpreter predates tomllib; the bypass cannot occur")
        self.assertIn("tomllib", deps_check.STDLIB)
        found = problems("import tomllib\n")
        self.assertEqual(len(found), 1,
                         "a late stdlib module present in this interpreter was exempted from "
                         "the function/handler rule — that is the 3.10 regression coming back")

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
