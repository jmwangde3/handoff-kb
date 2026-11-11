#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Transaction：原子写、备份校验、回滚判定、journal 损坏保留现场。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import write_txn  # noqa: E402
from lib import safeio  # noqa: E402


class TxnTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kbtxn-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "proj"
        self.root.mkdir(parents=True)

    def f(self, rel, text):
        """按字节写，避免 Windows 上 write_text 把 \n 翻译成 \r\n 影响哈希断言。"""
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
        return p

    def sha(self, rel):
        return safeio.sha256_file(self.root / rel)

    def txn(self):
        return safeio.Transaction(self.root, session="t")

    # 1
    def test_commit_writes_all_and_removes_journal(self):
        self.f("a.md", "A0\n")
        self.f("b.md", "B0\n")
        t = self.txn()
        t.stage("a.md", self.sha("a.md"), "A1\n")
        t.stage("b.md", self.sha("b.md"), "B1\n")
        t.commit()
        self.assertEqual((self.root / "a.md").read_text(encoding="utf-8"), "A1\n")
        self.assertEqual((self.root / "b.md").read_text(encoding="utf-8"), "B1\n")
        self.assertFalse((self.root / safeio.TXN_DIR / t.id).exists())

    # 2
    def test_stage_rejects_unknown_operation(self):
        self.f("a.md", "A0\n")
        with self.assertRaises(safeio.SafeIOError):
            self.txn().stage("a.md", self.sha("a.md"), "x", operation="rm -rf")

    # 3
    def test_stage_rejects_path_traversal(self):
        self.f("a.md", "A0\n")
        with self.assertRaises(Exception):
            self.txn().stage("../evil.md", "0" * 64, "x")

    # 4
    def test_stage_rejects_non_text_extension(self):
        (self.root / "blob.bin").write_bytes(b"\x00\x01")
        with self.assertRaises(Exception):
            self.txn().stage("blob.bin", safeio.sha256_file(self.root / "blob.bin"), "x")

    # 5
    def test_stage_rejects_wrong_sha_with_conflict(self):
        self.f("a.md", "A0\n")
        with self.assertRaises(safeio.Conflict) as ctx:
            self.txn().stage("a.md", "0" * 64, "A1\n")
        self.assertIn("不覆盖任何内容", str(ctx.exception))
        self.assertEqual((self.root / "a.md").read_text(encoding="utf-8"), "A0\n")

    # 6
    def test_stage_rejects_duplicate_path(self):
        self.f("a.md", "A0\n")
        t = self.txn()
        t.stage("a.md", self.sha("a.md"), "A1\n")
        with self.assertRaises(safeio.SafeIOError):
            t.stage("a.md", self.sha("a.md"), "A2\n")

    # 7
    def test_stage_rejects_invalid_utf8(self):
        raw = b"OK\n\xff\xfe broken\n"
        (self.root / "bad.md").write_bytes(raw)
        with self.assertRaises(safeio.EncodingError):
            self.txn().stage("bad.md", safeio.sha256_bytes(raw), "new\n")

    # 8
    def test_commit_conflict_rolls_back_written_files(self):
        self.f("a.md", "A0\n")
        self.f("b.md", "B0\n")
        t = self.txn()
        t.stage("a.md", self.sha("a.md"), "A1\n")
        t.stage("b.md", self.sha("b.md"), "B1\n")
        # 备份准备好之后再让第三方改 b.md：这时才可能「写了一半才发现冲突」
        real = safeio.atomic_write_bytes

        def tamper(path, data, mode_from=None):
            real(path, data, mode_from)
            if Path(path) == self.root / "a.md":      # 只对正文生效，不干扰备份写入
                (self.root / "b.md").write_bytes(b"B-third\n")

        with mock.patch.object(safeio, "atomic_write_bytes", tamper):
            with self.assertRaises(safeio.Conflict):
                t.commit()
        self.assertEqual((self.root / "a.md").read_text(encoding="utf-8"), "A0\n",
                         "已写文件必须回滚")
        self.assertEqual((self.root / "b.md").read_bytes(), b"B-third\n",
                         "第三方改动不得被覆盖")
        txn_dir = self.root / safeio.TXN_DIR
        self.assertTrue((txn_dir / "journal.json").is_file(), "回滚后要留下现场供检查")
        journal = json.loads((txn_dir / "journal.json").read_text(encoding="utf-8"))
        self.assertIn(journal["state"], (safeio.S_ROLLED_BACK,
                                         safeio.S_ROLLBACK_CONFLICT))

    # 8b
    def test_crashed_transaction_is_visible_to_recover(self):
        """Transaction 的现场在 .kb-txn/journal.json，recover 必须能看见。"""
        self.f("a.md", "A0\n")
        write_txn(self.root, "ignored", [])          # 保证 .kb-txn 存在
        (self.root / safeio.TXN_DIR / "ignored" / "journal.json").unlink()
        shutil.rmtree(self.root / safeio.TXN_DIR / "ignored")
        (self.root / safeio.TXN_DIR / "journal.json").write_text(
            json.dumps({"schema_version": safeio.JOURNAL_SCHEMA,
                        "state": safeio.S_APPLYING, "entries": [],
                        "transaction_id": "live", "root_id": "x"}), encoding="utf-8")
        items = safeio.pending_transactions(self.root)
        names = [Path(i["dir"]).name for i in items]
        self.assertIn(".kb-txn", names)

    # 9
    def test_partial_crash_recovery_rolls_back(self):
        """只有一部分文件写进去了（进程被杀）→ apply 必须回滚已写的那些。"""
        self.write_pair()
        write_txn(self.root, "t1", [
            {"path": "a.md", "sha_before": self.sha("a.md"),
             "sha_after": safeio.sha256_text("A1\n"), "backup_bytes": b"A0\n"},
            {"path": "b.md", "sha_before": self.sha("b.md"),
             "sha_after": safeio.sha256_text("B1\n"), "backup_bytes": b"B0\n"},
        ], state=safeio.S_APPLYING)
        (self.root / "a.md").write_bytes(b"A1\n")      # a 写完了，b 还没动
        reports = safeio.recover(self.root, mode="apply")
        self.assertTrue(reports[0]["action"].startswith("rolled-back"),
                        reports[0]["action"])
        self.assertEqual((self.root / "a.md").read_bytes(), b"A0\n")
        self.assertEqual((self.root / "b.md").read_bytes(), b"B0\n")
        self.assertFalse((self.root / safeio.TXN_DIR / "t1").exists())

    # 10
    def test_recover_refuses_when_third_party_changed_file(self):
        self.f("a.md", "A0\n")
        write_txn(self.root, "t2", [
            {"path": "a.md", "sha_before": self.sha("a.md"),
             "sha_after": safeio.sha256_text("A1\n"), "backup_bytes": b"A0\n"},
        ], state=safeio.S_APPLYING)
        (self.root / "a.md").write_bytes(b"A-third\n")
        report = safeio.recover(self.root, mode="apply")[0]
        self.assertIn("manual-recovery-required", report["action"])
        self.assertEqual((self.root / "a.md").read_bytes(), b"A-third\n")
        self.assertTrue(Path(report["dir"]).is_dir(), "证据不足时必须保留现场")

    # 11
    def test_recover_cleans_when_all_written(self):
        self.f("a.md", "A1\n")
        write_txn(self.root, "t3", [
            {"path": "a.md", "sha_before": safeio.sha256_text("A0\n"),
             "sha_after": self.sha("a.md"), "backup_bytes": b"A0\n"},
        ], state=safeio.S_APPLYING)
        report = safeio.recover(self.root, mode="apply")[0]
        self.assertIn("cleaned", report["action"])
        self.assertFalse(Path(report["dir"]).exists())

    # 12
    def test_tampered_journal_is_preserved_and_flagged(self):
        self.f("a.md", "A0\n")
        d = write_txn(self.root, "t4", [
            {"path": "a.md", "sha_before": self.sha("a.md"),
             "sha_after": safeio.sha256_text("A1\n"), "backup_bytes": b"A0\n"},
        ], state=safeio.S_APPLYING)
        data = json.loads((d / "journal.json").read_text(encoding="utf-8"))
        data["entries"][0]["sha_after"] = "f" * 64          # 改内容不改 checksum
        (d / "journal.json").write_text(json.dumps(data), encoding="utf-8")
        report = safeio.recover(self.root, mode="apply")[0]
        self.assertTrue(report["manual"])
        self.assertIn("checksum", report["message"])
        self.assertTrue(d.is_dir(), "journal 不可信时绝不 rmtree")
        self.assertEqual((self.root / "a.md").read_text(encoding="utf-8"), "A0\n")

    # 13
    def test_old_schema_journal_not_supported(self):
        self.f("a.md", "A0\n")
        d = write_txn(self.root, "t5", [
            {"path": "a.md", "sha_before": self.sha("a.md"),
             "sha_after": safeio.sha256_text("A1\n"), "backup_bytes": b"A0\n"},
        ], state=safeio.S_APPLYING, schema=1)
        report = safeio.inspect_transactions(self.root)[0]
        self.assertTrue(report["manual"])
        self.assertIn("schema_version", report["error"])
        self.assertTrue(d.is_dir())

    # 14
    def test_dry_run_never_writes(self):
        self.f("a.md", "A1\n")
        d = write_txn(self.root, "t6", [
            {"path": "a.md", "sha_before": safeio.sha256_text("A0\n"),
             "sha_after": self.sha("a.md"), "backup_bytes": b"A0\n"},
        ], state=safeio.S_APPLYING)
        report = safeio.recover(self.root, mode="dry-run")[0]
        self.assertEqual(report["action"], "plan")
        self.assertEqual((self.root / "a.md").read_text(encoding="utf-8"), "A1\n")
        self.assertTrue(d.is_dir())

    # 15
    def test_atomic_write_preserves_bom_crlf_and_mode(self):
        p = self.root / "win.md"
        p.write_bytes(b"\xef\xbb\xbfA\r\nB\r\n")
        safeio.atomic_write(p, "A\r\nB\r\nC\r\n")
        raw = p.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "BOM 必须保留")
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"A\nB", raw.replace(b"\r\n", b""))

    # 16
    def test_pending_transactions_lists_unreadable_ones(self):
        self.f("a.md", "A0\n")
        write_txn(self.root, "ok", [
            {"path": "a.md", "sha_before": self.sha("a.md"),
             "sha_after": safeio.sha256_text("A1\n"), "backup_bytes": b"A0\n"},
        ])
        bad = self.root / safeio.TXN_DIR / "bad"
        bad.mkdir(parents=True)
        (bad / "journal.json").write_text("{not json", encoding="utf-8")
        items = safeio.pending_transactions(self.root)
        self.assertEqual(len(items), 2)
        by_name = {Path(i["dir"]).name: i for i in items}
        self.assertTrue(by_name["ok"]["readable"])
        self.assertFalse(by_name["bad"]["readable"])
        self.assertIn("不可读", by_name["bad"]["error"])

    # 17
    def test_write_failure_keeps_original_content(self):
        self.f("a.md", "A0\n")
        t = self.txn()
        t.stage("a.md", self.sha("a.md"), "A1\n")
        real = safeio.atomic_write_bytes
        calls = {"n": 0}

        def boom(path, data, mode_from=None):
            calls["n"] += 1
            if calls["n"] >= 2:              # 第一次是备份，第二次才是正文
                raise OSError("磁盘写失败（模拟）")
            return real(path, data, mode_from)

        with mock.patch.object(safeio, "atomic_write_bytes", boom):
            with self.assertRaises(OSError):
                t.commit()
        self.assertEqual((self.root / "a.md").read_text(encoding="utf-8"), "A0\n")

    def write_pair(self):
        self.f("a.md", "A0\n")
        self.f("b.md", "B0\n")


if __name__ == "__main__":
    unittest.main()
