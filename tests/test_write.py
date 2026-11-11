#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-write.py：哈希冲突、锁、事务、恢复、路径穿越。"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import TempProject, run, run_json, write_txn  # noqa: E402


class WriteTest(TempProject):
    def setUp(self):
        super().setUp()
        self.make_filled()

    def sha(self, rel):
        import hashlib
        return hashlib.sha256((self.root / rel).read_bytes()).hexdigest()

    def changes(self, updates, name="changes.json"):
        p = self.tmp / name
        p.write_text(json.dumps({"schema_version": 1, "updates": updates},
                                ensure_ascii=False), encoding="utf-8")
        return p

    def test_read_returns_full_hash_and_sections(self):
        data, p = run_json("kb-write.py", "read", "--target", self.root,
                           "--file", "05_进度仪表盘.md", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(data["sha256"]), 64)
        ids = [s["id"] for s in data["sections"]]
        self.assertIn("dashboard.current", ids)
        self.assertIn("kb:id", json.dumps(data, ensure_ascii=False))

    def test_replace_section_body(self):
        sha = self.sha("05_进度仪表盘.md")
        ch = self.changes([{"path": "05_进度仪表盘.md", "expected_sha256": sha,
                            "operation": "replace_section",
                            "section_id": "dashboard.current",
                            "content": "- 固件已稳定 5 天；测速完成。"}])
        p = run("kb-write.py", "apply", "--target", self.root, "--changes", ch)
        self.assertEqual(p.returncode, 0, p.stderr)
        text = self.read("05_进度仪表盘.md")
        self.assertIn("固件已稳定 5 天", text)
        self.assertIn("## 1. 下一手", text)  # 其它章节保留
        self.assertNotEqual(sha, self.sha("05_进度仪表盘.md"))

    def test_append(self):
        sha = self.sha("06_流水/甲.md")
        ch = self.changes([{"path": "06_流水/甲.md", "expected_sha256": sha,
                            "operation": "append",
                            "content": "- [2026-11-11 01:00] 甲 收尾 → 无"}])
        p = run("kb-write.py", "apply", "--target", self.root, "--changes", ch)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("收尾", self.read("06_流水/甲.md"))

    def test_update_fact_row(self):
        sha = self.sha("00_基线.md")
        ch = self.changes([{"path": "00_基线.md", "expected_sha256": sha,
                            "operation": "update_fact", "fact_id": "K-02",
                            "content": "| K-02 | 信道 | 157 | 有效 | `iwinfo` | 2026-11-11 |"}])
        p = run("kb-write.py", "apply", "--target", self.root, "--changes", ch)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("| K-02 | 信道 | 157 |", self.read("00_基线.md"))

    def test_hash_conflict_refuses(self):
        before = self.read("05_进度仪表盘.md")
        ch = self.changes([{"path": "05_进度仪表盘.md", "expected_sha256": "0" * 64,
                            "operation": "append", "content": "x"}])
        p = run("kb-write.py", "apply", "--target", self.root, "--changes", ch)
        self.assertEqual(p.returncode, 1)
        self.assertIn("哈希冲突", p.stderr)
        self.assertEqual(before, self.read("05_进度仪表盘.md"))

    def test_dry_run_no_write(self):
        before = self.read("05_进度仪表盘.md")
        sha = self.sha("05_进度仪表盘.md")
        ch = self.changes([{"path": "05_进度仪表盘.md", "expected_sha256": sha,
                            "operation": "append", "content": "- 不该写入"}])
        p = run("kb-write.py", "apply", "--target", self.root, "--changes", ch, "--dry-run")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("dry_run", p.stdout)
        self.assertEqual(before, self.read("05_进度仪表盘.md"))

    def test_path_traversal_rejected(self):
        ch = self.changes([{"path": "../evil.md", "expected_sha256": "0" * 64,
                            "operation": "append", "content": "x"}])
        p = run("kb-write.py", "apply", "--target", self.root, "--changes", ch)
        self.assertEqual(p.returncode, 2)
        self.assertIn("路径穿越", p.stderr)

    def test_absolute_path_rejected(self):
        ch = self.changes([{"path": str(self.tmp / "x.md"), "expected_sha256": "0" * 64,
                            "operation": "append", "content": "x"}])
        p = run("kb-write.py", "apply", "--target", self.root, "--changes", ch)
        self.assertEqual(p.returncode, 2)

    def test_incomplete_sha_rejected(self):
        ch = self.changes([{"path": "05_进度仪表盘.md", "expected_sha256": "abc",
                            "operation": "append", "content": "x"}])
        p = run("kb-write.py", "apply", "--target", self.root, "--changes", ch)
        self.assertEqual(p.returncode, 1)
        self.assertIn("64", p.stderr)

    def test_multi_file_all_or_nothing(self):
        before = self.read("05_进度仪表盘.md")
        sha = self.sha("05_进度仪表盘.md")
        ch = self.changes([
            {"path": "05_进度仪表盘.md", "expected_sha256": sha,
             "operation": "append", "content": "- 第一条"},
            {"path": "00_基线.md", "expected_sha256": "f" * 64,
             "operation": "append", "content": "x"},
        ])
        p = run("kb-write.py", "apply", "--target", self.root, "--changes", ch)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(before, self.read("05_进度仪表盘.md"))

    def test_lock_held_blocks(self):
        lock = self.root / ".kb.lock"
        lock.mkdir()
        (lock / "meta.json").write_text(json.dumps({"pid": os.getpid(),
                                                    "session": "other"}), encoding="utf-8")
        sha = self.sha("05_进度仪表盘.md")
        ch = self.changes([{"path": "05_进度仪表盘.md", "expected_sha256": sha,
                            "operation": "append", "content": "- x"}])
        p = run("kb-write.py", "apply", "--target", self.root, "--changes", ch,
                env={"KB_LOCK_TIMEOUT": "0.3"})
        self.assertEqual(p.returncode, 1)
        self.assertIn("占用", p.stderr)

    def test_stale_lock_reclaimed(self):
        lock = self.root / ".kb.lock"
        lock.mkdir()
        (lock / "meta.json").write_text(json.dumps({"pid": 999999,
                                                    "session": "dead"}), encoding="utf-8")
        sha = self.sha("05_进度仪表盘.md")
        ch = self.changes([{"path": "05_进度仪表盘.md", "expected_sha256": sha,
                            "operation": "append", "content": "- 回收"}])
        p = run("kb-write.py", "apply", "--target", self.root, "--changes", ch,
                env={"KB_LOCK_TIMEOUT": "0.3"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("回收", self.read("05_进度仪表盘.md"))
        self.assertFalse(lock.exists())

    def test_recover_cleans_completed_transaction(self):
        rel = "05_进度仪表盘.md"
        current = self.sha(rel)
        txn = write_txn(self.root, "t1",
                        [{"path": rel, "sha_before": "a" * 64, "sha_after": current}])
        p = run("kb-write.py", "recover", "--target", self.root, "--apply")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertFalse(txn.exists())

    def test_recover_reports_conflict(self):
        rel = "05_进度仪表盘.md"
        txn = write_txn(self.root, "t2",
                        [{"path": rel, "sha_before": "a" * 64, "sha_after": "b" * 64}])
        p = run("kb-write.py", "recover", "--target", self.root, "--apply")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertTrue(txn.exists(), "冲突事务不得被自动清理")
        self.assertIn("changed-by-others", p.stdout)


if __name__ == "__main__":
    unittest.main()
