#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkspaceLock：所有权、超时、死锁回收、显式解锁。"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import safeio  # noqa: E402


def dead_pid() -> int:
    for pid in range(999999, 998000, -1):
        if not safeio.pid_alive(pid):
            return pid
    raise unittest.SkipTest("找不到确定已退出的 pid")


class LockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kblock-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "proj"
        self.root.mkdir(parents=True)

    def lock(self, **kw):
        kw.setdefault("timeout", 0.2)
        kw.setdefault("poll", 0.02)
        return safeio.WorkspaceLock(self.root, **kw)

    def fake_lock(self, **over):
        d = self.root / safeio.LOCK_DIR
        d.mkdir(parents=True, exist_ok=True)
        meta = {"schema_version": 1, "owner_token": "a" * 32,
                "pid": dead_pid(), "host": safeio.host_name(),
                "process_start": 1.0, "created": time.time(), "session": "other"}
        meta.update(over)
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return meta

    # 1
    def test_acquire_writes_ownership(self):
        lk = self.lock().acquire()
        try:
            meta = json.loads((self.root / safeio.LOCK_DIR / "meta.json")
                              .read_text(encoding="utf-8"))
            self.assertEqual(meta["owner_token"], lk.owner_token)
            self.assertEqual(meta["pid"], os.getpid())
            self.assertEqual(meta["host"], safeio.host_name())
            self.assertTrue(meta["process_start"])
        finally:
            lk.release()

    # 2
    def test_second_acquire_times_out_with_owner_info(self):
        holder = self.lock().acquire()
        try:
            with self.assertRaises(safeio.LockHeld) as ctx:
                self.lock(timeout=0.1).acquire()
            msg = str(ctx.exception)
            self.assertIn("pid=%s" % os.getpid(), msg)
            self.assertIn("--break-lock", msg)
        finally:
            holder.release()

    # 3
    def test_release_refuses_when_token_replaced(self):
        lk = self.lock().acquire()
        meta = json.loads((self.root / safeio.LOCK_DIR / "meta.json")
                          .read_text(encoding="utf-8"))
        meta["owner_token"] = "b" * 32
        (self.root / safeio.LOCK_DIR / "meta.json").write_text(
            json.dumps(meta), encoding="utf-8")
        with self.assertRaises(safeio.LockOwnershipError):
            lk.release()
        self.assertTrue((self.root / safeio.LOCK_DIR).exists(),
                        "拒绝删除他人锁时不得留下半删状态")

    # 4
    def test_release_refuses_when_pid_differs(self):
        lk = self.lock().acquire()
        meta = json.loads((self.root / safeio.LOCK_DIR / "meta.json")
                          .read_text(encoding="utf-8"))
        meta["pid"] = os.getpid() + 1
        (self.root / safeio.LOCK_DIR / "meta.json").write_text(
            json.dumps(meta), encoding="utf-8")
        with self.assertRaises(safeio.LockOwnershipError):
            lk.release()

    # 5
    def test_dead_lock_is_reclaimed(self):
        meta = self.fake_lock()
        lk = self.lock().acquire()
        try:
            self.assertIsNotNone(lk.reclaimed)
            self.assertEqual(lk.reclaimed["owner_token"], meta["owner_token"])
            self.assertEqual(lk.meta()["owner_token"], lk.owner_token)
            self.assertEqual(list(self.root.glob(".kb.lock.reclaim-*")), [])
        finally:
            lk.release()

    # 6
    def test_live_lock_not_reclaimed(self):
        self.fake_lock(pid=os.getpid(),
                       process_start=safeio.process_start_time(os.getpid()))
        with self.assertRaises(safeio.LockHeld):
            self.lock(timeout=0.1).acquire()
        self.assertTrue((self.root / safeio.LOCK_DIR).exists())

    # 7
    def test_foreign_host_lock_not_reclaimed(self):
        self.fake_lock(host="another-host", process_start=0)
        with self.assertRaises(safeio.LockHeld):
            self.lock(timeout=0.1).acquire()

    # 8
    def test_pid_reuse_is_reclaimed(self):
        """pid 活着但启动时间不同 = 原进程已退出、pid 被复用。"""
        self.fake_lock(pid=os.getpid(), process_start=1.0)
        lk = self.lock().acquire()
        try:
            self.assertIsNotNone(lk.reclaimed)
        finally:
            lk.release()

    # 9
    def test_incomplete_lock_is_not_stolen(self):
        (self.root / safeio.LOCK_DIR).mkdir()
        with self.assertRaises(safeio.LockHeld) as ctx:
            self.lock(timeout=0.1).acquire()
        self.assertIn("不完整", str(ctx.exception))
        self.assertTrue((self.root / safeio.LOCK_DIR).exists())

    # 10
    def test_break_lock_plan_writes_nothing(self):
        self.fake_lock()
        info = safeio.break_lock(self.root, plan=True)
        self.assertEqual(info["action"], "plan")
        self.assertFalse(info["incomplete"])
        self.assertTrue((self.root / safeio.LOCK_DIR).exists())

    # 11
    def test_break_lock_refuses_live_holder(self):
        self.fake_lock(pid=os.getpid(),
                       process_start=safeio.process_start_time(os.getpid()))
        info = safeio.break_lock(self.root, plan=False, force=False)
        self.assertEqual(info["action"], "refused")
        self.assertTrue((self.root / safeio.LOCK_DIR).exists())

    # 12
    def test_break_lock_force_removes_dead_lock(self):
        self.fake_lock()
        info = safeio.break_lock(self.root, plan=False, force=True)
        self.assertEqual(info["action"], "removed")
        self.assertFalse((self.root / safeio.LOCK_DIR).exists())
        self.assertEqual(list(self.root.glob(".kb.lock.reclaim-*")), [])

    # 13
    def test_break_lock_force_on_incomplete(self):
        (self.root / safeio.LOCK_DIR).mkdir()
        refused = safeio.break_lock(self.root, plan=False, force=False)
        self.assertEqual(refused["action"], "refused")
        forced = safeio.break_lock(self.root, plan=False, force=True)
        self.assertEqual(forced["action"], "removed")

    # 14
    def test_root_id_is_stable_and_path_specific(self):
        self.assertEqual(safeio.root_id(self.root), safeio.root_id(self.root))
        other = self.tmp / "other"
        other.mkdir()
        self.assertNotEqual(safeio.root_id(self.root), safeio.root_id(other))
        self.assertEqual(len(safeio.root_id(self.root)), 16)


if __name__ == "__main__":
    unittest.main()
