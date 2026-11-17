#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Focused tests for kb-finish.py (L0/L1/L2, idempotency, conflict guards, txn recovery, dry-run)."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

import common  # noqa: E402
from lib import safeio  # noqa: E402


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class KbFinishTest(common.TempProject):
    def _write_input(self, name: str, payload: dict) -> Path:
        p = self.tmp / name
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def _make_unfinished_txn(self, rel: str, new_text: str, second_rel: str = "06_流水/甲.md"):
        target = self.root / rel
        orig_bytes = target.read_bytes()
        orig_sha = safeio.sha256_bytes(orig_bytes)
        new_bytes = new_text.encode("utf-8")
        new_sha = safeio.sha256_bytes(new_bytes)

        second_target = self.root / second_rel
        second_orig = second_target.read_bytes()
        second_sha = safeio.sha256_bytes(second_orig)

        txn_dir = self.root / safeio.TXN_DIR
        bpath = txn_dir / "backup" / rel
        bpath.parent.mkdir(parents=True, exist_ok=True)
        bpath.write_bytes(orig_bytes)
        bpath2 = txn_dir / "backup" / second_rel
        bpath2.parent.mkdir(parents=True, exist_ok=True)
        bpath2.write_bytes(second_orig)

        target.write_bytes(new_bytes)
        journal = {
            "schema_version": safeio.JOURNAL_SCHEMA,
            "transaction_id": "prev-crash-1",
            "root_id": safeio.root_id(self.root),
            "pid": 999999,
            "root": str(self.root.resolve()),
            "host": safeio.host_name(),
            "session": "crashed",
            "created": 1.0,
            "updated": 1.0,
            "state": safeio.S_APPLYING,
            "entry_count": 2,
            "entries": [
                {
                    "path": rel,
                    "op": "replace",
                    "sha_before": orig_sha,
                    "sha_after": new_sha,
                    "backup": (Path("backup") / rel).as_posix(),
                    "backup_sha256": orig_sha,
                    "state": "written",
                },
                {
                    "path": second_rel,
                    "op": "replace",
                    "sha_before": second_sha,
                    "sha_after": safeio.sha256_text("untouched-target\n"),
                    "backup": (Path("backup") / second_rel).as_posix(),
                    "backup_sha256": second_sha,
                    "state": "staged",
                },
            ],
        }
        journal["checksum"] = safeio.journal_checksum(journal)
        jpath = txn_dir / "journal.json"
        jpath.write_text(json.dumps(journal, ensure_ascii=False, indent=2, sort_keys=True),
                         encoding="utf-8")
        return jpath, bpath, orig_bytes

    # A. L0
    def test_l0_skips_without_input_or_target(self):
        missing = self.tmp / "nonexistent-kb"
        out, proc = common.run_json("kb-finish.py", "--level", "L0", "--target", missing)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(out, {"level": "L0", "status": "skipped", "files": []})
        self.assertFalse(missing.exists())

    def test_auto_empty_input_skips_as_l0_without_lock_or_txn(self):
        self.init()
        inp = self._write_input("empty.json", {"updates": []})
        out, proc = common.run_json("kb-finish.py", "--target", self.root, "--input", inp)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(out, {"level": "L0", "status": "skipped", "files": []})
        self.assertFalse((self.root / safeio.LOCK_DIR).exists())
        self.assertFalse((self.root / safeio.TXN_DIR).exists())

    # B. L1 update
    def test_l1_updates_unique_section_keeps_others_and_appends_event(self):
        self.init()
        dash_before = self.read("05_进度仪表盘.md")
        old_next = "- [填：下一个人第一步做什么，别写「继续推进」]"
        new_next = "- 运行 tests/test_finish.py 验收"
        self.assertIn(old_next, dash_before)

        inp = self._write_input("l1.json", {
            "updates": [{
                "path": "05_进度仪表盘.md",
                "section_id": "dashboard.next",
                "before": old_next,
                "after": new_next,
            }],
            "event": {
                "id": "t-l1-1",
                "path": "06_流水/甲.md",
                "content": "- 2026-11-17 完成 L1 增量写回测试",
            },
        })
        out, proc = common.run_json("kb-finish.py", "--target", self.root, "--input", inp)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(out["level"], "L1")
        self.assertEqual(out["status"], "written")
        self.assertEqual(set(out["files"]), {"05_进度仪表盘.md", "06_流水/甲.md"})

        dash_after = self.read("05_进度仪表盘.md")
        self.assertEqual(dash_after, dash_before.replace(old_next, new_next, 1))
        shard_after = self.read("06_流水/甲.md")
        self.assertIn("<!-- kb:event:t-l1-1 --> - 2026-11-17 完成 L1 增量写回测试", shard_after)
        self.assertTrue(inp.is_file(), "persistent input must remain on disk")

    # C. Idempotency
    def test_l1_idempotent_rerun_does_not_duplicate(self):
        self.init()
        inp = self._write_input("idem.json", {
            "updates": [{
                "path": "05_进度仪表盘.md",
                "section_id": "dashboard.next",
                "before": "- [填：下一个人第一步做什么，别写「继续推进」]",
                "after": "- 已更新下一步",
            }],
            "event": {
                "id": "t-idem-1",
                "path": "06_流水/甲.md",
                "content": "- 幂等事件记录",
            },
        })
        out1, p1 = common.run_json("kb-finish.py", "--target", self.root, "--input", inp)
        self.assertEqual(p1.returncode, 0, p1.stderr + p1.stdout)
        self.assertEqual(out1["status"], "written")
        dash_sha = self.sha("05_进度仪表盘.md")
        shard_sha = self.sha("06_流水/甲.md")

        out2, p2 = common.run_json("kb-finish.py", "--target", self.root, "--input", inp)
        self.assertEqual(p2.returncode, 0, p2.stderr + p2.stdout)
        self.assertEqual(out2["status"], "unchanged")
        self.assertEqual(out2["files"], [])
        self.assertEqual(self.sha("05_进度仪表盘.md"), dash_sha)
        self.assertEqual(self.sha("06_流水/甲.md"), shard_sha)
        self.assertEqual(self.read("06_流水/甲.md").count("<!-- kb:event:t-idem-1 -->"), 1)

    # D. Conflict protection
    def test_conflict_guards_reject_and_preserve_files(self):
        self.init()
        dash_path = self.root / "05_进度仪表盘.md"
        shard_path = self.root / "06_流水/甲.md"

        # 1. missing section_id
        inp1 = self._write_input("c1.json", {
            "updates": [{"path": "05_进度仪表盘.md", "section_id": "dashboard.missing",
                         "before": "a", "after": "b"}],
        })
        # 2. missing before
        inp2 = self._write_input("c2.json", {
            "updates": [{"path": "05_进度仪表盘.md", "section_id": "dashboard.next",
                         "before": "NOT_PRESENT_ANYWHERE", "after": "b"}],
        })
        # 3. duplicate before
        self.write("06_流水/甲.md",
                   "<!-- kb:schema: 2 -->\n\n<!-- kb:id: log.dup -->\n## 流水\n\n- dup\n- dup\n")
        inp3 = self._write_input("c3.json", {
            "updates": [{"path": "06_流水/甲.md", "section_id": "log.dup",
                         "before": "- dup", "after": "- unique"}],
        })
        # 4. both before and after already exist
        self.write("06_流水/甲.md",
                   "<!-- kb:schema: 2 -->\n\n<!-- kb:id: log.both -->\n## 流水\n\n- old\n- new\n")
        inp4 = self._write_input("c4.json", {
            "updates": [{"path": "06_流水/甲.md", "section_id": "log.both",
                         "before": "- old", "after": "- new"}],
        })
        # 5. duplicate section_id
        self.write("06_流水/甲.md",
                   "<!-- kb:schema: 2 -->\n\n<!-- kb:id: log.x -->\n## A\n- x\n\n<!-- kb:id: log.x -->\n## B\n- y\n")
        inp5 = self._write_input("c5.json", {
            "updates": [{"path": "06_流水/甲.md", "section_id": "log.x",
                         "before": "- x", "after": "- z"}],
        })

        for label, path, inp in [
            ("missing_section", dash_path, inp1),
            ("missing_before", dash_path, inp2),
            ("dup_before", shard_path, inp3),
            ("both_before_after", shard_path, inp4),
            ("dup_section", shard_path, inp5),
        ]:
            with self.subTest(case=label):
                f_before = path.read_bytes()
                i_before = inp.read_bytes()
                out, proc = common.run_json("kb-finish.py", "--target", self.root, "--input", inp)
                self.assertEqual(proc.returncode, 1, label)
                self.assertEqual(out["status"], "failed", label)
                self.assertEqual(path.read_bytes(), f_before, label)
                self.assertEqual(inp.read_bytes(), i_before, label)

        # 6. same event id with different content
        self.write("06_流水/甲.md", "<!-- kb:schema: 2 -->\n\n<!-- kb:event:e-1 --> first\n")
        inp6 = self._write_input("c6.json", {
            "event": {"id": "e-1", "path": "06_流水/甲.md", "content": "second"},
        })
        s_before = shard_path.read_bytes()
        i6_before = inp6.read_bytes()
        out6, p6 = common.run_json("kb-finish.py", "--target", self.root, "--input", inp6)
        self.assertEqual(p6.returncode, 1)
        self.assertEqual(out6["status"], "failed")
        self.assertEqual(shard_path.read_bytes(), s_before)
        self.assertEqual(inp6.read_bytes(), i6_before)

    def test_external_modification_during_commit_is_rejected(self):
        self.init()
        kb_finish = __import__("importlib").import_module("kb-finish")
        inp = self._write_input("race.json", {
            "updates": [{
                "path": "05_进度仪表盘.md",
                "section_id": "dashboard.next",
                "before": "- [填：下一个人第一步做什么，别写「继续推进」]",
                "after": "- updated-by-finish",
            }],
        })
        dash_path = self.root / "05_进度仪表盘.md"
        real_prepare = safeio.Transaction._prepare

        def prepare_then_mutate(txn_self):
            real_prepare(txn_self)
            dash_path.write_text(dash_path.read_text(encoding="utf-8") + "\n<!-- external -->\n",
                                 encoding="utf-8")

        args = type("Args", (), {
            "target": str(self.root),
            "level": "L1",
            "input": str(inp),
            "dry_run": False,
        })()
        with mock.patch.object(safeio.Transaction, "_prepare", prepare_then_mutate):
            with self.assertRaises(safeio.Conflict):
                kb_finish.run(args)
        self.assertIn("<!-- external -->", self.read("05_进度仪表盘.md"))
        self.assertNotIn("updated-by-finish", self.read("05_进度仪表盘.md"))
        self.assertTrue(inp.is_file())

    # E. Transaction recovery
    def test_unfinished_journal_blocks_finish_until_recovered(self):
        self.init()
        jpath, bpath, orig_bytes = self._make_unfinished_txn(
            "05_进度仪表盘.md", "<!-- crashed partial -->\n"
        )
        j_sha = sha256_path(jpath)
        b_sha = sha256_path(bpath)
        dash_sha = self.sha("05_进度仪表盘.md")
        shard_sha = self.sha("06_流水/甲.md")

        inp = self._write_input("after_crash.json", {
            "updates": [{
                "path": "05_进度仪表盘.md",
                "section_id": "dashboard.next",
                "before": "- [填：下一个人第一步做什么，别写「继续推进」]",
                "after": "- recovered-then-updated",
            }],
            "event": {
                "id": "t-rec-1",
                "path": "06_流水/甲.md",
                "content": "- 恢复后再写入",
            },
        })
        out_block, p_block = common.run_json("kb-finish.py", "--target", self.root, "--input", inp)
        self.assertEqual(p_block.returncode, 1)
        self.assertEqual(out_block["status"], "failed")
        self.assertEqual(sha256_path(jpath), j_sha)
        self.assertEqual(sha256_path(bpath), b_sha)
        self.assertEqual(self.sha("05_进度仪表盘.md"), dash_sha)
        self.assertEqual(self.sha("06_流水/甲.md"), shard_sha)

        # Recover safely via kb-write.py recover --apply
        rec_out, rec_proc = common.run_json("kb-write.py", "recover", "--target", self.root, "--apply")
        self.assertEqual(rec_proc.returncode, 0, rec_proc.stderr + rec_proc.stdout)
        self.assertEqual((self.root / "05_进度仪表盘.md").read_bytes(), orig_bytes)
        self.assertFalse((self.root / safeio.TXN_DIR).exists())

        # Now kb-finish succeeds
        out_ok, p_ok = common.run_json("kb-finish.py", "--target", self.root, "--input", inp)
        self.assertEqual(p_ok.returncode, 0, p_ok.stderr + p_ok.stdout)
        self.assertEqual(out_ok["status"], "written")
        self.assertIn("- recovered-then-updated", self.read("05_进度仪表盘.md"))
        self.assertIn("<!-- kb:event:t-rec-1 -->", self.read("06_流水/甲.md"))

    def test_orphan_backup_blocks_finish_and_recover_preserves_it(self):
        self.init()
        bpath = self.root / safeio.TXN_DIR / "backup" / "05_进度仪表盘.md"
        bpath.parent.mkdir(parents=True, exist_ok=True)
        bpath.write_bytes(b"orphan-backup-bytes")
        b_sha = sha256_path(bpath)
        dash_sha = self.sha("05_进度仪表盘.md")

        inp = self._write_input("orphan.json", {
            "event": {"id": "t-orphan", "path": "06_流水/甲.md", "content": "- 应被拒绝"},
        })
        out, proc = common.run_json("kb-finish.py", "--target", self.root, "--input", inp)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(out["status"], "failed")
        self.assertEqual(self.sha("05_进度仪表盘.md"), dash_sha)
        self.assertEqual(sha256_path(bpath), b_sha)

        rec_out, rec_proc = common.run_json("kb-write.py", "recover", "--target", self.root, "--apply", "--json")
        self.assertEqual(rec_proc.returncode, 1, rec_proc.stderr + rec_proc.stdout)
        self.assertTrue(rec_out["transactions"][0]["manual"])
        self.assertTrue(bpath.is_file())
        self.assertEqual(sha256_path(bpath), b_sha)

    # F. dry-run
    def test_dry_run_previews_without_writing_or_creating_txn(self):
        self.init()
        dash_sha = self.sha("05_进度仪表盘.md")
        shard_sha = self.sha("06_流水/甲.md")
        inp = self._write_input("dry.json", {
            "updates": [{
                "path": "05_进度仪表盘.md",
                "section_id": "dashboard.next",
                "before": "- [填：下一个人第一步做什么，别写「继续推进」]",
                "after": "- dry-run preview step",
            }],
            "event": {
                "id": "t-dry-1",
                "path": "06_流水/甲.md",
                "content": "- dry-run event",
            },
        })
        inp_sha = sha256_path(inp)

        out, proc = common.run_json("kb-finish.py", "--target", self.root, "--input", inp, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(out["level"], "L1")
        self.assertEqual(out["status"], "dry-run")
        self.assertEqual(set(out["files"]), {"05_进度仪表盘.md", "06_流水/甲.md"})
        self.assertEqual(len(out["details"]), 2)
        for item in out["details"]:
            self.assertEqual(len(item["sha_before"]), 64)
            self.assertEqual(len(item["sha_after"]), 64)
            self.assertNotEqual(item["sha_before"], item["sha_after"])

        self.assertEqual(self.sha("05_进度仪表盘.md"), dash_sha)
        self.assertEqual(self.sha("06_流水/甲.md"), shard_sha)
        self.assertFalse((self.root / safeio.TXN_DIR).exists())
        self.assertEqual(sha256_path(inp), inp_sha)

    def test_dry_run_refuses_to_overwrite_existing_txn(self):
        self.init()
        jpath, bpath, _ = self._make_unfinished_txn("05_进度仪表盘.md", "partial\n")
        j_sha = sha256_path(jpath)
        b_sha = sha256_path(bpath)
        inp = self._write_input("dry_blocked.json", {
            "event": {"id": "t-dry-2", "path": "06_流水/甲.md", "content": "- blocked"},
        })
        out, proc = common.run_json("kb-finish.py", "--target", self.root, "--input", inp, "--dry-run")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(out["status"], "failed")
        self.assertEqual(sha256_path(jpath), j_sha)
        self.assertEqual(sha256_path(bpath), b_sha)

    # G. L2
    def test_l2_performs_safe_incremental_write_without_faking_full_review(self):
        self.init()
        inp = self._write_input("l2.json", {
            "updates": [{
                "path": "05_进度仪表盘.md",
                "section_id": "dashboard.next",
                "before": "- [填：下一个人第一步做什么，别写「继续推进」]",
                "after": "- L2 release verified",
            }],
        })
        out, proc = common.run_json("kb-finish.py", "--level", "L2", "--target", self.root, "--input", inp)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(out["level"], "L2")
        self.assertEqual(out["status"], "written")
        self.assertEqual(out["files"], ["05_进度仪表盘.md"])
        self.assertNotIn("check_passed", out)
        self.assertNotIn("full_review_complete", out)
        self.assertIn("- L2 release verified", self.read("05_进度仪表盘.md"))


if __name__ == "__main__":
    unittest.main()
