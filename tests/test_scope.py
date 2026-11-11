#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scope：路径角色、标准/自有命名、分片目录、归档与数据目录排除、路径安全。"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import protocol, scope  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FFRS = ROOT / "tests" / "fixtures" / "ffrs"


class RoleTest(unittest.TestCase):
    def test_canonical_roles(self):
        cases = {"00_基线.md": "baseline", "05_进度仪表盘.md": "dashboard",
                 "06_会话日志.md": "log", "90_过程档案.md": "archive",
                 "10_固件.md": "fact", "01_旧线.md": "fact",
                 "AGENTS.md": "entry", "笔记.md": "other"}
        for name, want in cases.items():
            self.assertEqual(protocol.role_of_name(name), want, name)

    def test_loose_roles(self):
        cases = {"60_进度.md": "dashboard", "61_流水.md": "log",
                 "00_INDEX.md": "baseline", "99_归档.md": "archive",
                 "AGENTS.md": "entry"}
        for name, want in cases.items():
            self.assertEqual(protocol.role_of_name(name, loose=True), want, name)

    def test_reserved_numbers_never_become_facts(self):
        for name in ("00_x.md", "05_x.md", "06_x.md", "90_x.md"):
            self.assertNotEqual(protocol.role_of_name(name), "fact", name)
        self.assertEqual(protocol.role_of_name("18_超范围.md"), "other")


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kbscope-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "proj"
        self.root.mkdir(parents=True)

    def touch(self, rel, text="x\n"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def test_canonical_preferred_over_alias(self):
        self.touch("05_进度仪表盘.md", "canon\n")
        self.touch("60_进度.md", "alias\n")
        files = scope.role_files(self.root, loose=True)
        names = [p.name for p in files["dashboard"]]
        self.assertIn("05_进度仪表盘.md", names)

    def test_shards_canonical_only(self):
        self.touch("06_流水/a.md")
        self.touch("60_流水/b.md")
        self.assertEqual([p.name for p in scope.shards(self.root)], ["a.md"])

    def test_shards_loose_includes_alias_dirs_without_duplicates(self):
        self.touch("06_流水/a.md")
        self.touch("60_流水/b.md")
        self.touch("60_流水/忽略.txt")
        names = [p.name for p in scope.shards(self.root, loose=True)]
        self.assertEqual(sorted(names), ["a.md", "b.md"],
                         "同一目录不能被两个别名重复收录")

    def test_archive_dir_alias(self):
        for name in ("归档", "archive", "90_归档", "旧档"):
            self.assertTrue(scope.is_archive_dir(name), name)
        for name in ("流水", "00_基线.md", "归档说明.md"):
            self.assertFalse(scope.is_archive_dir(name), name)

    def test_iter_text_files_excludes_data_archive_and_big(self):
        self.touch("00_基线.md")
        self.touch("归档/旧.md")
        self.touch("90_归档/旧2.md")
        self.touch("data/产物.md")
        big = self.touch("巨大.md")
        big.write_bytes(b"x" * (protocol.MAX_TEXT_BYTES + 10))
        got = {p.name: reason for p, reason in scope.iter_text_files(self.root)}
        self.assertIn("00_基线.md", got)
        self.assertNotIn("旧.md", got)
        self.assertNotIn("旧2.md", got)
        self.assertNotIn("产物.md", got)
        self.assertEqual(got["巨大.md"], "too-large")
        with_archive = {p.name for p, r in scope.iter_text_files(
            self.root, include_archive=True) if not r}
        self.assertIn("旧.md", with_archive)

    def test_check_rel_path_rejects_unsafe(self):
        self.touch("05_进度仪表盘.md")
        for bad in ("../x.md", "/etc/passwd", "C:/Windows/x.md", "a.exe", "", " x.md"):
            with self.assertRaises(scope.ScopeError, msg=bad):
                scope.check_rel_path(self.root, bad)
        ok = scope.check_rel_path(self.root, "06_流水/新.md")
        self.assertTrue(str(ok).endswith("新.md"))
        sub = self.root / "06_流水"
        sub.mkdir(exist_ok=True)
        ok = scope.check_rel_path(self.root, "06_流水/新.md")
        self.assertTrue(scope.is_within(self.root, ok))

    def test_is_data_path(self):
        p = self.touch("data/产物.md")
        self.assertTrue(scope.is_data_path(p, self.root))
        q = self.touch("06_流水/a.md")
        self.assertFalse(scope.is_data_path(q, self.root))


class FixtureTest(unittest.TestCase):
    """真实「自有命名」项目：角色判定必须与标准命名等价。"""

    def test_ffrs_roles(self):
        files = scope.role_files(FFRS, loose=True)
        self.assertEqual([p.name for p in files["dashboard"]], ["60_进度.md"])
        self.assertEqual([p.name for p in files["log"]], ["61_流水.md"])
        self.assertEqual([p.name for p in files["baseline"]], ["00_INDEX.md"])
        self.assertEqual(sorted(p.name for p in files["fact"]),
                         ["10_固件.md", "11_运行态.md"])
        self.assertIn("AGENTS.md", [p.name for p in files["entry"]])

    def test_ffrs_shards_merge_both_dirs(self):
        names = [p.name for p in scope.shards(FFRS, loose=True)]
        self.assertEqual(sorted(names), ["2026-11-固件.md", "2026-11-运行态.md"])

    def test_ffrs_archive_and_data_excluded(self):
        paths = [p.as_posix() for p, r in scope.iter_text_files(FFRS) if not r]
        self.assertFalse(any("归档" in p for p in paths), paths)
        self.assertFalse(any(p.startswith("data/") for p in paths), paths)


if __name__ == "__main__":
    unittest.main()
