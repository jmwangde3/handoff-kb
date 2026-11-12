#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-benchmark：同口径计数、错误路径单列、8 项质量指标、真实自有命名项目可跑。"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, TempProject, run, run_json  # noqa: E402

FFRS = ROOT / "tests" / "fixtures" / "ffrs"


def load_script(name: str):
    """按路径加载 scripts/ 下的脚本（文件名带连字符，不能直接 import）。"""
    path = ROOT / "scripts" / ("%s.py" % name)
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GateThresholdTest(unittest.TestCase):
    """质量门的 80% 必须向上取整，不能被 round() 抹成 75%。"""

    def test_min_passes_rounds_up(self):
        m = load_script("kb-benchmark")
        cases = {1: 1, 2: 2, 3: 3, 4: 4, 5: 4, 6: 5, 7: 6, 8: 7, 9: 8, 10: 8,
                 11: 9, 12: 10, 13: 11, 14: 12, 15: 12, 16: 13, 20: 16, 100: 80}
        for total, want in cases.items():
            self.assertEqual(m.min_passes(total), want, "total=%d" % total)

    def test_no_float_rounding_error(self):
        """15*0.8 在二进制里是 12.000000000000002：ceil(total*0.8) 会错给 13。"""
        m = load_script("kb-benchmark")
        self.assertEqual(m.min_passes(15), 12)
        self.assertEqual(m.min_passes(25), 20)

    def test_eight_graded_tasks_need_seven(self):
        """8 个可评任务时 6 个通过只有 75%，必须判红。"""
        m = load_script("kb-benchmark")
        self.assertEqual(m.min_passes(8), 7)
        self.assertLess(6, m.min_passes(8))


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
        err = [r for r in data["rows"] if not r["counted"] and r["graded"]]
        self.assertEqual(len(err), 1)
        self.assertEqual(err[0]["title"], "错误项目路径")
        self.assertEqual(err[0]["c"], 0)
        self.assertIn("拒绝", err[0]["quality"])

    def test_mean_excludes_error_paths(self):
        data, _ = self.bench()
        counted = [r for r in data["rows"] if r["counted"]]
        self.assertTrue(counted)
        mean = sum(r["c"] for r in counted) / len(counted)
        self.assertEqual(data["tokens"]["C_mean"], round(mean, 1))

    def test_quality_metrics_present(self):
        data, _ = self.bench()
        want = {"section_hit", "fact_hit", "constraint_kept", "gap_honest",
                "budget_honest", "tokenizer_consistent", "error_rejected",
                "lines_honest", "archive_excluded", "p4_bounded"}
        self.assertEqual(set(data["metrics"]), want)
        for key, m in data["metrics"].items():
            self.assertLessEqual(m["passed"], m["total"], key)
            self.assertTrue(m["label"])
        self.assertEqual(data["metrics"]["error_rejected"]["passed"], 1)
        self.assertEqual(data["metrics"]["constraint_kept"]["total"], 9)

    def test_must_pass_set_is_declared_and_hard(self):
        data, _ = self.bench()
        must = set(data["gate"]["must_pass"])
        self.assertEqual(must, {"constraint_kept", "error_rejected", "budget_honest",
                               "lines_honest", "tokenizer_consistent"})
        self.assertTrue(must <= set(data["metrics"]))
        self.assertTrue(data["gate"]["hard_ok"], "正常夹具上关键项应全部通过")

    def test_word_in_constraints_does_not_grant_fact_pass(self):
        """P0 里有「作废」两个字不算命中：作废任务必须真的找到那个事实 ID 和状态。"""
        dash = self.read("05_进度仪表盘.md").replace(
            "- 不擅自重启 r1；凭证不入库。",
            "- 不擅自重启 r1；作废与待核都要标明。")
        self.write("05_进度仪表盘.md", dash)
        # 把唯一的作废事实整行删掉，再看作废任务是被判「跳过」还是「通过」
        base = self.read("00_基线.md")
        lines = [ln for ln in base.splitlines()
                 if not ln.strip().startswith("| K-03 |")]
        self.write("00_基线.md", "\n".join(lines) + "\n")
        data, _ = self.bench()
        row = next(r for r in data["rows"] if r["id"] == 5)
        self.assertIn("跳过", row["quality"],
                      "库里没有作废事实时必须跳过，不能用 P0 里的词冒充命中：%s" % row)

    def test_multi_line_recall_is_classified(self):
        data, _ = self.bench()
        recall = data["recall"]
        self.assertEqual(sum(recall.values()), 1, "多工作线任务只有一条")
        self.assertIn(recall["full"] + recall["partial"] + recall["silent"], (0, 1))
        self.assertEqual(data["metrics"]["lines_honest"]["total"], 9)

    def test_p4_bounded_is_reported(self):
        data, _ = self.bench()
        m = data["metrics"]["p4_bounded"]
        self.assertEqual(m["total"], 9)
        self.assertEqual(m["passed"], m["total"], "正常任务上 P4 都应在 3 块 / 30% 之内")

    def test_gate_threshold_matches_graded_count(self):
        """端到端锁住取整：min_passes 必须等于 ceil(可评任务数 × 0.8)。"""
        data, _ = self.bench()
        total = data["quality"]["total"]
        self.assertGreater(total, 0)
        self.assertEqual(data["gate"]["min_passes"], max(1, (total * 4 + 4) // 5))
        self.assertGreaterEqual(data["gate"]["min_passes"], total * 0.8)

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
