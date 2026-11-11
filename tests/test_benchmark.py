#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-benchmark：同口径计数、错误路径单列、8 项质量指标、真实自有命名项目可跑。"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, TempProject, run, run_json  # noqa: E402

FFRS = ROOT / "tests" / "fixtures" / "ffrs"


class BenchmarkTest(TempProject):
    def setUp(self):
        super().setUp()
        self.make_filled()

    def bench(self, *extra):
        return run_json("kb-benchmark.py", "--target", self.root, "--report", "json", *extra)

    def test_json_shape_and_same_tokenizer(self):
        data, p = self.bench()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(data["tokenizer"])
        for key in ("A_all", "B_00_05"):
            self.assertIsInstance(data["tokens"][key], int)
        self.assertIsInstance(data["tokens"]["C_mean"], (int, float))
        self.assertIn("reduction_vs_A", data)
        self.assertIn("reduction_vs_B", data)
        self.assertGreater(data["tokens"]["A_all"], data["tokens"]["B_00_05"])
        # A/B/C 同口径：A 与 B 都为整数 token，且 C 是均值而非字符串
        self.assertIsInstance(data["tokens"]["C_mean"], (int, float))
        self.assertEqual(data["exact"], bool(data.get("exact")))

    def test_error_path_is_listed_separately(self):
        data, _ = self.bench()
        err = [r for r in data["rows"] if not r["counted"]]
        self.assertEqual(len(err), 1)
        self.assertEqual(err[0]["id"], 10)
        self.assertEqual(err[0]["c"], 0)
        self.assertIn("拒绝", err[0]["quality"])

    def test_mean_excludes_error_paths(self):
        data, _ = self.bench()
        counted = [r for r in data["rows"] if r["counted"]]
        self.assertTrue(counted)
        mean = sum(r["c"] for r in counted) / len(counted)
        self.assertEqual(data["tokens"]["C_mean"], round(mean, 1))

    def test_eight_quality_metrics_present(self):
        data, _ = self.bench()
        self.assertEqual(len(data["metrics"]), 8)
        for key, m in data["metrics"].items():
            self.assertLessEqual(m["passed"], m["total"], key)
            self.assertTrue(m["label"])
        self.assertEqual(data["metrics"]["error_rejected"]["passed"], 1)
        self.assertEqual(data["metrics"]["constraint_kept"]["total"], 9)

    def test_gate_fails_when_quality_drops(self):
        """把 05 的硬约束段删掉：约束保留率下降，工具必须报失败而不是照样打勾。"""
        text = self.read("05_进度仪表盘.md")
        cut = text.split("<!-- kb:id: dashboard.constraints -->")[0]
        self.write("05_进度仪表盘.md", cut)
        # 还要堵住 AGENTS.md 的兜底，否则约束仍然在（那是正确行为，不能当失败）
        self.write("AGENTS.md", "# AGENTS\n\n没有硬约束段，也没有 dashboard 约束。\n")
        data, p = self.bench()
        self.assertEqual(p.returncode, 1, "质量项掉下去必须以非零退出")
        self.assertEqual(data["metrics"]["constraint_kept"]["passed"], 0)
        self.assertFalse(data["gate"]["hard_ok"], "关键项失败必须让质量门变红")

    def test_reduction_reported_against_full_corpus(self):
        data, _ = self.bench()
        a = data["tokens"]["A_all"]
        c = data["tokens"]["C_mean"]
        self.assertAlmostEqual(data["reduction_vs_A"], round(1 - c / a, 3), places=3)

    def test_runs_on_loose_named_project(self):
        """独立的「自有命名」夹具：60_进度 / 61_流水 / 60_流水 必须被认出来。"""
        tmp = self.tmp / "ffrs"
        shutil.copytree(FFRS, tmp)
        data, p = run_json("kb-benchmark.py", "--target", tmp, "--report", "json",
                           "--loose")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(data["loose"])
        self.assertGreaterEqual(data["quality"]["passed"], 8)
        self.assertGreaterEqual(data["metrics_rate"], 0.8)


if __name__ == "__main__":
    unittest.main()
