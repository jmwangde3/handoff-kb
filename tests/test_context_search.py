#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-search / kb-context：中文检索、排序、预算、降级。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, TempProject, run, run_json  # noqa: E402


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

    def test_unmigrated_dashboard_falls_back_to_head(self):
        """05 没有 kb:id 时不能给空包：退回前 40 行，并报缺口。"""
        self.make_v1()
        data, p = run_json("kb-context.py", "--target", self.root,
                           "--task", "查看当前项目状态", "--budget", "3000",
                           "--format", "json", "--loose")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(data["blocks"], data)
        self.assertTrue(any(b["priority"] == "P1" for b in data["blocks"]))
        self.assertGreater(data["used"], 0)


    def test_missing_dashboard_is_clear_error(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        p = run("kb-context.py", "--target", empty, "--task", "x")
        self.assertEqual(p.returncode, 2)
        self.assertIn("不像交接库", p.stderr)

    def test_p2_fact_blocks_are_actually_assembled(self):
        """回归：build() 曾把 P2 条目只放进 per_line，导致事实块永远不出现。"""
        data, _ = self.ctx("--task", "排查甲的问题", "--budget", "3000")
        ids = [b["section_id"] for b in data["blocks"]]
        self.assertIn("fact.current", ids)
        self.assertIn("fact.pitfalls", ids)
        self.assertEqual(data["selected_lines"], ["甲"])
        self.assertEqual(data["omitted_lines"], [])

    def test_multi_line_loaded_together(self):
        self.write("11_乙.md", """<!-- kb:schema: 2 -->
# 11 · 乙 — 事实分册

<!-- kb:id: fact.current -->
## 1. 当前值

| 项 | 值 |
|---|---|
| 速率 | 300M |
""")
        data, _ = self.ctx("--task", "排查甲和乙的问题", "--budget", "3000")
        self.assertEqual(sorted(data["selected_lines"]), ["乙", "甲"])
        self.assertEqual(data["omitted_lines"], [])
        sources = {b["source"] for b in data["blocks"] if b["priority"] == "P2"}
        self.assertEqual(sources, {"10_甲.md", "11_乙.md"})

    def test_explicit_multi_line_spec(self):
        self.write("11_乙.md", """<!-- kb:schema: 2 -->
# 11 · 乙 — 事实分册

<!-- kb:id: fact.current -->
## 1. 当前值

| 项 | 值 |
|---|---|
| 速率 | 300M |
""")
        data, _ = self.ctx("--task", "随便看看", "--line", "甲,乙")
        self.assertEqual(sorted(data["selected_lines"]), ["乙", "甲"])

    def test_budget_overflow_reports_omitted_line_honestly(self):
        self.write("11_乙.md", """<!-- kb:schema: 2 -->
# 11 · 乙 — 事实分册

<!-- kb:id: fact.current -->
## 1. 当前值

| 项 | 值 |
|---|---|
| 速率 | 300M |
""")
        data, p = self.ctx("--task", "排查甲和乙的问题", "--budget", "200")
        self.assertTrue(data["over_budget"])
        self.assertEqual(p.returncode, 1)
        self.assertTrue(data["omitted_lines"], "装不下的工作线必须列出来")
        joined = " ".join(data["gaps"])
        for name in data["omitted_lines"]:
            self.assertIn("工作线「%s」" % name, joined)

    def test_line_without_fact_sections_is_not_called_budget_issue(self):
        self.write("12_空.md", """<!-- kb:schema: 2 -->
# 12 · 空 — 事实分册

## 没有事实节

随便写点。
""")
        data, _ = self.ctx("--task", "看看空这条线", "--budget", "3000")
        # 没有事实节 ≠ 预算不够：不能借「预算不足」掩盖「这条线没写事实」
        self.assertNotIn("空", data["omitted_lines"])
        self.assertNotIn("空", data["selected_lines"])
        joined = " ".join(data["gaps"])
        self.assertIn("没有 fact.current", joined)
        self.assertNotIn("预算", joined)

    def test_context_keys_do_not_collide(self):
        data, _ = self.ctx("--task", "K-01 的当前值是什么", "--budget", "3000")
        ids = [b["section_id"] for b in data["blocks"]]
        if ids.count("baseline.facts") < 2:
            self.skipTest("这个夹具没有同时产出基线命中与证据指针")
        self.assertEqual(len(data["context"]), len(data["blocks"]),
                         "JSON 上下文不能因同名 section 丢块")

    def test_used_matches_rendered_and_budget(self):
        data, _ = self.ctx("--task", "查看现状", "--budget", "3000")
        self.assertEqual(data["used"], data["rendered_tokens"])
        self.assertLessEqual(data["used"], 3000)
        self.assertFalse(data["over_budget"])

    def test_tokenizer_without_tiktoken_requires_explicit_fallback(self):
        try:
            import tiktoken  # noqa: F401
        except ModuleNotFoundError:
            pass
        else:
            self.skipTest("本机有 tiktoken，这条降级路径不适用")
        p = run("kb-context.py", "--target", self.root, "--task", "x",
                "--tokenizer", "cl100k_base")
        self.assertEqual(p.returncode, 2)
        self.assertIn("--allow-tokenizer-fallback", p.stderr)
        p2 = run("kb-context.py", "--target", self.root, "--task", "x",
                 "--tokenizer", "cl100k_base", "--allow-tokenizer-fallback",
                 "--format", "json")
        self.assertEqual(p2.returncode, 0, p2.stderr)
        self.assertFalse(json.loads(p2.stdout)["exact"])

    def test_missing_next_section_reports_gap(self):
        text = self.read("05_进度仪表盘.md")
        self.write("05_进度仪表盘.md",
                   text.split("<!-- kb:id: dashboard.next -->")[0])
        data, _ = self.ctx("--task", "查看现状")
        self.assertIn("缺少 kb:id: dashboard.next", " ".join(data["gaps"]))

    def test_loose_named_project_context(self):
        import shutil as _shutil
        target = self.tmp / "ffrs"
        _shutil.copytree(ROOT / "tests" / "fixtures" / "ffrs", target)
        data, p = run_json("kb-context.py", "--target", target, "--task",
                           "排查固件的掉速问题", "--format", "json", "--loose")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(data["selected_lines"], ["固件"])
        ids = [b["section_id"] for b in data["blocks"]]
        self.assertIn("dashboard.constraints", ids)
        self.assertIn("fact.pitfalls", ids)
        self.assertEqual(data["omitted_lines"], [])


if __name__ == "__main__":
    unittest.main()
