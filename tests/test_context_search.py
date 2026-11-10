#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-search / kb-context：中文检索、排序、预算、降级。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import TempProject, run, run_json  # noqa: E402


class SearchTest(TempProject):
    def setUp(self):
        super().setUp()
        self.make_filled()

    def test_chinese_bigram_hit(self):
        p = run("kb-search.py", "--target", self.root, "--query", "固件版本")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("00_基线.md", p.stdout)

    def test_id_match_ranks_first(self):
        data, p = run_json("kb-search.py", "--target", self.root,
                           "--query", "K-01", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(data["hits"])
        self.assertEqual(data["hits"][0]["score"], max(h["score"] for h in data["hits"]))
        self.assertIn("命中 K-01", " ".join(data["hits"][0]["reasons"]))

    def test_line_filter(self):
        p = run("kb-search.py", "--target", self.root, "--query", "NSS", "--line", "甲")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("10_甲.md", p.stdout)
        self.assertNotIn("11_乙.md", p.stdout)

    def test_archive_excluded_by_default(self):
        self.write("归档/旧闻.md", "# 旧\n\n## 秘辛\n\n- 绝密口令XYZ 在此\n")
        p = run("kb-search.py", "--target", self.root, "--query", "绝密口令XYZ")
        self.assertEqual(p.returncode, 1)
        p2 = run("kb-search.py", "--target", self.root, "--query", "绝密口令XYZ",
                 "--include-archive")
        self.assertEqual(p2.returncode, 0, p2.stderr)
        self.assertIn("旧闻", p2.stdout)

    def test_superseded_excluded(self):
        p = run("kb-search.py", "--target", self.root, "--query", "192.0.2.1")
        self.assertEqual(p.returncode, 1, p.stdout)

    def test_json_shape(self):
        data, _ = run_json("kb-search.py", "--target", self.root,
                           "--query", "固件", "--json", "--limit", "2")
        self.assertIn("terms", data)
        self.assertLessEqual(len(data["hits"]), 2)
        for h in data["hits"]:
            for key in ("file", "heading", "line", "score", "snippet", "sha256_12", "tokens"):
                self.assertIn(key, h)


class ContextTest(TempProject):
    def setUp(self):
        super().setUp()
        self.make_filled()

    def ctx(self, *args):
        return run_json("kb-context.py", "--target", self.root, "--format", "json", *args)

    def test_constraints_always_present(self):
        data, p = self.ctx("--task", "随便看看", "--budget", "3000")
        self.assertEqual(p.returncode, 0, p.stderr)
        ids = [b["section_id"] for b in data["blocks"]]
        self.assertIn("dashboard.constraints", ids)

    def test_over_budget_keeps_required_and_reports(self):
        data, p = self.ctx("--task", "查看现状", "--budget", "10")
        self.assertTrue(data["over_budget"])
        self.assertEqual(p.returncode, 1)
        ids = [b["section_id"] for b in data["blocks"]]
        self.assertIn("dashboard.constraints", ids)
        self.assertIn("dashboard.current", ids)

    def test_budget_respected_when_enough(self):
        data, _ = self.ctx("--task", "查看现状", "--budget", "3000")
        self.assertLessEqual(data["used"], 3000)
        self.assertFalse(data["over_budget"])

    def test_line_fact_selected(self):
        data, _ = self.ctx("--task", "排查甲的问题", "--budget", "3000")
        ids = [b["section_id"] for b in data["blocks"]]
        self.assertIn("fact.pitfalls", ids)

    def test_cross_line_pulls_chains(self):
        data, _ = self.ctx("--task", "改固件会不会影响运行态", "--budget", "3000")
        ids = [b["section_id"] for b in data["blocks"]]
        self.assertIn("baseline.chains", ids)

    def test_no_hit_reports_gaps(self):
        data, _ = self.ctx("--task", "zzz-nonexistent-qqq", "--budget", "3000")
        self.assertTrue(data["gaps"])

    def test_markdown_has_priority_headers(self):
        p = run("kb-context.py", "--target", self.root, "--task", "查看现状")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("## [P0]", p.stdout)
        self.assertIn("预算与取舍", p.stdout)

    def test_missing_dashboard_is_clear_error(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        p = run("kb-context.py", "--target", empty, "--task", "x")
        self.assertEqual(p.returncode, 2)
        self.assertIn("不像交接库", p.stderr)


if __name__ == "__main__":
    unittest.main()
