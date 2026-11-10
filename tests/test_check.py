#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-check.py：编号、引用、章节 ID、证据、模板模式、JSON。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import TempProject, run, run_json  # noqa: E402


class CheckTest(TempProject):
    def report(self, *extra):
        data, p = run_json("kb-check.py", "--target", self.root, "--json", *extra)
        self.assertIsNotNone(data, p.stderr)
        return data, p

    def levels(self, data, category):
        return [f["level"] for f in data["findings"] if f["category"] == category]

    def test_fresh_template_is_clean(self):
        self.init()
        data, p = self.report()
        self.assertEqual(data["counts"]["ERR"], 0, data["findings"])
        self.assertEqual(p.returncode, 0)
        self.assertEqual(data["mode"], "template")

    def test_duplicate_id_is_error(self):
        self.make_filled()
        self.write("00_基线.md", self.read("00_基线.md").replace(
            "| K-04 | 新 DNS |",
            "| K-01 | 重复 | x | 有效 | y | 2026-11-09 |\n| K-04 | 新 DNS |"))
        data, _ = self.report()
        self.assertIn("ERR", self.levels(data, "编号契约"))

    def test_undefined_reference_is_error(self):
        self.make_filled()
        self.write("10_甲.md", self.read("10_甲.md") + "\n- 另见 K-99\n")
        data, _ = self.report()
        self.assertIn("ERR", self.levels(data, "编号引用"))

    def test_superseded_reference_warns(self):
        self.make_filled()
        self.write("10_甲.md", self.read("10_甲.md") + "\n- 旧值见 K-03\n")
        data, _ = self.report()
        self.assertIn("WARN", self.levels(data, "作废引用"))

    def test_table_mismatch_warns(self):
        self.make_filled()
        text = self.read("05_进度仪表盘.md").replace(
            "| 固件 | 稳定 | 21.02.3 |", "| 固件 | 稳定 |")
        self.write("05_进度仪表盘.md", text)
        data, _ = self.report()
        self.assertIn("WARN", self.levels(data, "表格结构"))

    def test_secret_is_error(self):
        self.make_filled()
        self.write("10_甲.md", self.read("10_甲.md") + '\n- password = "hunter2xyz"\n')
        data, _ = self.report()
        self.assertIn("ERR", self.levels(data, "明文凭证"))

    def test_template_mode_skips_evidence(self):
        self.init()
        data, _ = self.report("--mode", "template")
        self.assertIn("OK", self.levels(data, "事实证据"))

    def test_evidence_missing_warns_in_project_mode(self):
        self.make_filled()
        self.write("00_基线.md", self.read("00_基线.md").replace(
            "| K-01 | 固件版本 | 21.02.3 | 有效 | `cat /etc/version` | 2026-11-10 |",
            "| K-01 | 固件版本 | 21.02.3 | 有效 | — | — |"))
        data, _ = self.report("--mode", "project")
        self.assertIn("WARN", self.levels(data, "事实证据"))

    def test_legacy_fact_shard_recognized(self):
        self.make_v1()
        data, p = self.report()
        self.assertEqual(data["counts"]["ERR"], 0, data["findings"])
        self.assertEqual(p.returncode, 0)

    def test_shard_threshold_warns(self):
        self.make_filled()
        rows = "\n".join("- [2026-11-11 00:%02d] 甲 %d → 无" % (i % 60, i)
                         for i in range(210))
        self.write("06_流水/甲.md", "# 06 · 分片\n\n## 流水\n\n" + rows + "\n")
        data, _ = self.report()
        self.assertIn("WARN", self.levels(data, "流水轮转"))

    def test_json_shape(self):
        self.make_filled()
        data, _ = self.report()
        for key in ("target", "mode", "counts", "stats", "findings"):
            self.assertIn(key, data)
        self.assertIn("core_bytes", data["stats"])

    def test_loose_self_named_project_no_false_err(self):
        """自有命名项目：60_进度.md + 标题里定义的 G-xxx，不该报「引用未定义」。"""
        self.write("60_进度.md", "# 60 进度\n\n## 现在在做什么\n\n- 在做甲。\n\n"
                   "## 待办\n\n| 事项 | 条目 |\n|---|---|\n| 采信号 | G-002 |\n")
        self.write("00_INDEX.md", "# 索引\n\n## 结论速查\n\n"
                   "| 关键词 | 摘要 | 条目 |\n|---|---|---|\n| 甲 | 结论 | G-001、G-002 |\n\n"
                   "## G-001 甲结论\n\n详情。\n\n## G-002 乙结论\n\n详情。\n")
        data, pr = self.report("--loose")
        self.assertEqual(data["counts"]["ERR"], 0, data["findings"])
        self.assertEqual(pr.returncode, 0)
        cats = [f["category"] for f in data["findings"] if f["level"] == "OK"]
        self.assertIn("编号契约", cats)

    def test_undefined_id_is_warn_only_in_loose(self):
        self.make_filled()
        self.write("10_甲.md", self.read("10_甲.md") + "\n见 G-999。\n")
        strict, _ = self.report()
        self.assertEqual(strict["counts"]["ERR"], 1)
        loose, pr = self.report("--loose")
        self.assertEqual(loose["counts"]["ERR"], 0)
        self.assertEqual(pr.returncode, 0)

    def test_archive_counted_separately(self):
        self.make_filled()
        self.write("归档/旧备份.md", "# 旧\n\n" + "- 旧记录\n" * 200)
        data, _ = self.report()
        self.assertGreater(data["stats"]["archive_bytes"], 0)
        self.assertGreater(data["stats"]["searchable_bytes"], 0)
        self.assertGreater(data["stats"]["physical_bytes"],
                           data["stats"]["searchable_bytes"])


    def test_scope_outside_rejected(self):
        p = run("kb-check.py", "--target", self.tmp / "nope")
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main()
