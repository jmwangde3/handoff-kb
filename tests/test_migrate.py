#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-migrate：计划绑定哈希、计划校验、加锁执行、拒绝可疑计划。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SCRIPTS, TempProject, run  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
from lib import safeio  # noqa: E402


class MigrateTest(TempProject):
    def setUp(self):
        super().setUp()
        self.make_v1()

    def plan(self):
        p = run("kb-migrate.py", "--target", self.root, "--plan", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def plan_path(self) -> Path:
        return self.root / ".kb-migrate-plan.json"

    def test_plan_reports_ops_and_writes_plan_file(self):
        before = self.read("05_进度仪表盘.md")
        plan = self.plan()
        self.assertEqual(plan["schema_version"], 2)
        self.assertEqual(plan["root_id"], safeio.root_id(self.root))
        self.assertTrue(plan["entries"])
        self.assertGreater(plan["operation_count"], 0)
        self.assertTrue(self.plan_path().is_file())
        self.assertEqual(self.read("05_进度仪表盘.md"), before, "计划阶段不得改动正文")

    def test_plan_is_idempotent_on_v2(self):
        run("kb-migrate.py", "--target", self.root, "--plan")
        run("kb-migrate.py", "--target", self.root, "--apply")
        p = run("kb-migrate.py", "--target", self.root, "--plan", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["entries"], [])

    def test_apply_without_plan_refuses(self):
        p = run("kb-migrate.py", "--target", self.root, "--apply")
        self.assertEqual(p.returncode, 1)
        self.assertIn("--plan", p.stderr + p.stdout)

    def test_apply_executes_and_is_verifiable(self):
        plan = self.plan()
        p = run("kb-migrate.py", "--target", self.root, "--apply")
        self.assertEqual(p.returncode, 0, p.stderr)
        text = self.read("05_进度仪表盘.md")
        self.assertIn("<!-- kb:schema: 2 -->", text)
        self.assertIn("<!-- kb:id: dashboard.current -->", text)
        self.assertFalse(self.plan_path().exists(), "执行成功后计划文件应清理")
        chk = run("kb-check.py", "--target", self.root, "--json")
        self.assertIn(chk.returncode, (0, 1), chk.stderr)
        self.assertGreater(len(plan["entries"]), 0)

    def test_apply_refuses_when_source_changed(self):
        self.plan()
        original = self.read("05_进度仪表盘.md")
        with open(self.root / "05_进度仪表盘.md", "a", encoding="utf-8") as f:
            f.write("\n- 计划生成后别人又改了一行\n")
        changed = self.read("05_进度仪表盘.md")
        p = run("kb-migrate.py", "--target", self.root, "--apply")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.read("05_进度仪表盘.md"), changed,
                         "哈希不符时必须原样保留，不能覆盖")
        self.assertNotEqual(original, changed)

    def test_apply_refuses_plan_for_other_root(self):
        plan = self.plan()
        plan["root_id"] = "0" * 16
        self.plan_path().write_text(json.dumps(plan), encoding="utf-8")
        before = self.read("05_进度仪表盘.md")
        p = run("kb-migrate.py", "--target", self.root, "--apply")
        self.assertEqual(p.returncode, 1)
        self.assertIn("root_id", p.stderr + p.stdout)
        self.assertEqual(self.read("05_进度仪表盘.md"), before)

    def test_apply_refuses_malformed_ops(self):
        cases = [
            {"type": "delete_file"},                       # 非白名单操作
            {"type": "prepend", "at": -1, "text": "x"},     # 负位置
            {"type": "prepend", "at": 0, "text": "两\n行"},  # 含换行
            {"type": "prepend", "at": 0, "text": "   "},    # 空内容
        ]
        for op in cases:
            plan = self.plan()
            plan["entries"][0]["operations"] = [op]
            self.plan_path().write_text(json.dumps(plan), encoding="utf-8")
            before = self.read("05_进度仪表盘.md")
            p = run("kb-migrate.py", "--target", self.root, "--apply")
            self.assertEqual(p.returncode, 1, op)
            self.assertEqual(self.read("05_进度仪表盘.md"), before, op)
            self.plan_path().unlink()

    def test_apply_refuses_duplicate_paths(self):
        plan = self.plan()
        plan["entries"] = [plan["entries"][0], dict(plan["entries"][0])]
        self.plan_path().write_text(json.dumps(plan), encoding="utf-8")
        p = run("kb-migrate.py", "--target", self.root, "--apply")
        self.assertEqual(p.returncode, 1)
        self.assertIn("重复路径", p.stderr + p.stdout)

    def test_apply_refuses_while_locked(self):
        self.plan()
        lock = safeio.WorkspaceLock(self.root, timeout=0.1).acquire()
        try:
            p = run("kb-migrate.py", "--target", self.root, "--apply", timeout=60)
        finally:
            lock.release()
        self.assertEqual(p.returncode, 1)
        self.assertIn("已被占用", p.stderr + p.stdout)

    def test_plan_records_git_dirty_state(self):
        plan = self.plan()
        self.assertIn("git_dirty", plan)
        self.assertIsInstance(plan["git_dirty"], list)


if __name__ == "__main__":
    unittest.main()
