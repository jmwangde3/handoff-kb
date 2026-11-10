#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 benchmark / 演示用的合成夹具（v2 已填写、2 条线）。

用法：
  py tests/make_fixture.py [目标目录]
  py tests/make_fixture.py ../kbdemo && py scripts/kb-benchmark.py --target ../kbdemo

不传目录时建在系统临时目录并打印路径。目录已存在时直接复用（不覆盖已有文件）。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

import common  # noqa: E402


class _Fixture(common.TempProject):
    """借用测试夹具的构造逻辑，但不跑测试。"""

    def runTest(self):  # pragma: no cover - 只为满足 unittest.TestCase
        pass


def main() -> int:
    if len(sys.argv) > 1:
        root = Path(sys.argv[1]).resolve()
    else:
        root = Path(tempfile.mkdtemp(prefix="kbfix-")) / "proj"
    if root.exists() and any(root.iterdir()):
        print("目标已存在且非空，不覆盖：%s" % root, file=sys.stderr)
        return 1
    fx = _Fixture()
    fx.root = root
    fx.tmp = root.parent
    p = fx.init()
    if p.returncode != 0:
        print(p.stdout + p.stderr, file=sys.stderr)
        return p.returncode
    fx.make_filled()
    print(str(root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
