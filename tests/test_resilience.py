#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""故障注入 / 并发 / 恶意输入：真实子进程并发，不留锁与事务残留。"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SCRIPTS, TempProject, run, write_txn  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
from lib import safeio  # noqa: E402


class ConcurrencyTest(TempProject):
    def setUp(self):
        super().setUp()
        self.make_filled()
        self.target = "05_进度仪表盘.md"

    def sha(self, rel):
        import hashlib
        return hashlib.sha256((self.root / rel).read_bytes()).hexdigest()

    def changes(self, name, line, sha):
        p = self.tmp / name
        p.write_text(json.dumps({"schema_version": 1, "updates": [{
            "path": self.target, "operation": "append",
            "expected_sha256": sha, "content": line}]}, ensure_ascii=False),
            encoding="utf-8")
        return p

    def spawn(self, changes_path):
        env = {"KB_LOCK_TIMEOUT": "3", "PYTHONIOENCODING": "utf-8"}
        import os
        e = dict(os.environ)
        e.update(env)
        return subprocess.Popen(
            [sys.executable, str(SCRIPTS / "kb-write.py"), "apply",
             "--target", str(self.root), "--changes", str(changes_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", env=e)

    def test_concurrent_writers_serialize_without_corruption(self):
        base = self.sha(self.target)
        a = self.changes("a.json", "- [2026-11-11] 会话 A 追加\n", base)
        b = self.changes("b.json", "- [2026-11-11] 会话 B 追加\n", base)
        pa, pb = self.spawn(a), self.spawn(b)
        out_a, err_a = pa.communicate(timeout=60)
        out_b, err_b = pb.communicate(timeout=60)
        text = self.read(self.target)
        winners = [x for x in ("会话 A 追加", "会话 B 追加") if x in text]
        self.assertEqual(len(winners), 1,
                         "同一 base 只允许一个写入落地：%s\n%s\n%s"
                         % (winners, out_a + err_a, out_b + err_b))
        codes = sorted([pa.returncode, pb.returncode])
        self.assertEqual(codes, [0, 1], "另一个必须是冲突失败，不能静默成功")
        self.assertIn("CONFLICT", (err_a + err_b))
        self.assertFalse((self.root / ".kb.lock").exists(), "锁必须释放")
        self.assertFalse((self.root / ".kb-txn").exists(), "事务目录必须清理")
        # 内容仍可被解析（没被写坏）
        p = run("kb-check.py", "--target", self.root, "--json")
        self.assertIn(p.returncode, (0, 1), p.stdout + p.stderr)

    def test_lock_timeout_reports_error_and_leaves_file(self):
        before = self.read(self.target)
        sha = self.sha(self.target)
        changes = self.changes("c.json", "- [2026-11-11] 不该写进去\n", sha)
        lock = safeio.WorkspaceLock(self.root, timeout=0.1).acquire()
        try:
            p = run("kb-write.py", "apply", "--target", self.root,
                    "--changes", changes, env={"KB_LOCK_TIMEOUT": "0.3"}, timeout=60)
        finally:
            lock.release()
        self.assertEqual(p.returncode, 1)
        self.assertIn("已被占用", p.stderr)
        self.assertEqual(self.read(self.target), before)

    def test_stale_lock_from_dead_process_is_reclaimed(self):
        d = self.root / ".kb.lock"
        d.mkdir()
        dead = next(pid for pid in range(999999, 998000, -1)
                    if not safeio.pid_alive(pid))
        (d / "meta.json").write_text(json.dumps({
            "schema_version": 1, "owner_token": "c" * 32, "pid": dead,
            "host": safeio.host_name(), "process_start": 1.0,
            "created": 0, "session": "dead"}), encoding="utf-8")
        sha = self.sha(self.target)
        changes = self.changes("d.json", "- [2026-11-11] 回收后写入\n", sha)
        p = run("kb-write.py", "apply", "--target", self.root, "--changes", changes,
                env={"KB_LOCK_TIMEOUT": "5"}, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("回收死进程遗留的锁", p.stderr)
        self.assertIn("回收后写入", self.read(self.target))


class FaultInjectionTest(TempProject):
    def setUp(self):
        super().setUp()
        self.make_filled()

    def test_corrupt_journal_is_never_deleted(self):
        d = self.root / ".kb-txn"
        d.mkdir()
        (d / "journal.json").write_text('{"schema_version": 2, "state": "applying"',
                                        encoding="utf-8")
        p = run("kb-write.py", "recover", "--target", self.root)
        self.assertEqual(p.returncode, 1)
        self.assertTrue((d / "journal.json").is_file(), "journal 不可信时保留现场")
        out = p.stdout + p.stderr
        self.assertIn("人工", out)

    def test_recover_apply_restores_partial_write_via_cli(self):
        target = "05_进度仪表盘.md"
        original = (self.root / target).read_bytes()
        after = original + "\n- [2026-11-11] 半截写入\n".encode("utf-8")
        write_txn(self.root, "cli", [
            {"path": target, "sha_before": safeio.sha256_bytes(original),
             "sha_after": safeio.sha256_bytes(after), "backup_bytes": original},
            {"path": "00_基线.md",
             "sha_before": safeio.sha256_file(self.root / "00_基线.md"),
             "sha_after": "0" * 64, "backup_bytes": b"x\n"},
        ], state=safeio.S_APPLYING)
        (self.root / target).write_bytes(after)
        p = run("kb-write.py", "recover", "--target", self.root, "--apply")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual((self.root / target).read_bytes(), original)
        self.assertIn("rolled-back", p.stdout)

    def test_invalid_utf8_file_is_reported_not_crashed(self):
        (self.root / "坏字节.md").write_bytes(b"\xff\xfe\x00bad")
        p = run("kb-check.py", "--target", self.root)
        self.assertIn(p.returncode, (0, 1, 2))
        self.assertNotIn("Traceback", p.stderr)
        p2 = run("kb-write.py", "read", "--target", self.root, "--file", "坏字节.md")
        self.assertIn(p2.returncode, (1, 2))
        self.assertIn("ENCODING", p2.stderr + p2.stdout)

    def test_malicious_changes_paths_are_refused(self):
        sha = safeio.sha256_file(self.root / "05_进度仪表盘.md")
        bad_specs = [
            {"path": "../outside.md", "operation": "append",
             "expected_sha256": sha, "content": "x"},
            {"path": "/etc/passwd", "operation": "append",
             "expected_sha256": sha, "content": "x"},
            {"path": "05_进度仪表盘.md", "operation": "rm_rf",
             "expected_sha256": sha, "content": "x"},
            {"path": "05_进度仪表盘.md", "operation": "append",
             "expected_sha256": "short", "content": "x"},
        ]
        for i, spec in enumerate(bad_specs):
            p = self.tmp / ("bad%d.json" % i)
            p.write_text(json.dumps({"schema_version": 1, "updates": [spec]},
                                    ensure_ascii=False), encoding="utf-8")
            before = self.read("05_进度仪表盘.md")
            r = run("kb-write.py", "apply", "--target", self.root, "--changes", p)
            self.assertIn(r.returncode, (1, 2), spec)
            self.assertEqual(self.read("05_进度仪表盘.md"), before, spec)
            self.assertNotIn("Traceback", r.stderr)

    def test_update_fact_refuses_ambiguous_and_missing(self):
        sha = safeio.sha256_file(self.root / "00_基线.md")
        for fid, content in (("K-99", "| K-99 | x | y | 有效 | z |"),
                             ("K-01", "| K-01 | 只有三列 | x |")):
            spec = {"schema_version": 1,
                    "updates": [{"path": "00_基线.md", "operation": "update_fact",
                                 "expected_sha256": sha, "fact_id": fid,
                                 "content": content}]}
            p = self.tmp / ("fact-%s.json" % fid)
            p.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            before = self.read("00_基线.md")
            r = run("kb-write.py", "apply", "--target", self.root, "--changes", p)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertEqual(self.read("00_基线.md"), before)

    def test_missing_changes_file_is_clean_error(self):
        r = run("kb-write.py", "apply", "--target", self.root, "--changes",
                self.tmp / "nope.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ERR", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_oversized_file_is_skipped_not_read(self):
        big = self.root / "超大.md"
        big.write_bytes(b"x" * (3 * 1024 * 1024))
        p = run("kb-check.py", "--target", self.root, "--json")
        data = json.loads(p.stdout)
        self.assertEqual(data["stats"]["excluded_files"], 1)
        self.assertTrue(any(f["category"] == "体积排除" for f in data["findings"]))
        self.assertLess(data["stats"]["physical_bytes"], 3 * 1024 * 1024 + 20000)


if __name__ == "__main__":
    unittest.main()
