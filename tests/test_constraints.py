#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 硬约束的三级兜底（lib/constraints）。

kb-context 注入、kb-check 体检必须同口径。这里直接测 `resolve()`，
因为两边都只是它的调用方 —— 差异只可能出在这一层。
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import TempProject  # noqa: E402
from lib import constraints, markdown as md  # noqa: E402


def link_file(target, link) -> None:
    link = Path(link)
    if os.name == "nt":
        os.symlink(str(target), str(link))
        return
    os.symlink(str(target), str(link))


class MeaningfulTest(unittest.TestCase):
    """「有正文」的判据：装饰、占位符、空标题都不算。"""

    def test_decor_only_is_empty(self):
        for text in ("## 硬约束", "- - -", "| --- | --- |", "<!-- kb:id: x -->", "***"):
            self.assertFalse(constraints.meaningful(text), text)

    def test_placeholder_is_empty(self):
        for text in ("## 硬约束\n\n- [填]\n", "TODO: 待补\n", "- TBD 稍后\n",
                     "- 占位\n"):
            self.assertFalse(constraints.meaningful(text), text)

    def test_real_line_counts(self):
        self.assertTrue(constraints.meaningful("## 硬约束\n\n- 不擅自重启生产节点。\n"))
        self.assertTrue(constraints.meaningful("见 05 §7"))

    def test_strip_decor_keeps_words(self):
        self.assertEqual(constraints.strip_decor("- **不要** 动 `配置`"), "不要动配置")


class ResolveTest(TempProject):
    def dash(self, body):
        """写一个 05，返回 (doc, path) 供 resolve 使用。"""
        p = self.write("05_进度仪表盘.md",
                       "<!-- kb:schema: 2 -->\n# 05 · 进度仪表盘 — Demo\n\n" + body)
        return md.parse_file(p), p

    def resolve(self):
        doc, p = self.dash_cache
        return constraints.resolve(self.root, doc, p, p.name)

    def set_dash(self, body):
        self.dash_cache = self.dash(body)

    def test_dashboard_constraints_wins(self):
        self.set_dash("<!-- kb:id: dashboard.constraints -->\n## 7. 硬约束\n\n"
                      "- 不擅自重启 r1。\n")
        got = self.resolve()
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["source"], "dashboard")
        self.assertIn("dashboard.constraints", got["detail"])

    def test_empty_id_falls_back_and_says_why(self):
        """有 ID 但为空是最坏情形：不能静默当成「已配好」。"""
        self.write("AGENTS.md", "# 规则\n\n## 硬约束\n\n- 变更窗口只在周二。\n")
        self.set_dash("<!-- kb:id: dashboard.constraints -->\n## 7. 硬约束\n\n")
        got = self.resolve()
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["source"], "agents")
        self.assertIn("dashboard.constraints", got["detail"],
                      "兜底成功也要说明 dashboard 那边是空的：%s" % got["detail"])

    def test_safety_section_is_second_choice(self):
        self.set_dash("<!-- kb:id: dashboard.safety -->\n## 7. 安全边界\n\n"
                      "- 生产只读。\n")
        got = self.resolve()
        self.assertEqual(got["source"], "dashboard")
        self.assertIn("dashboard.safety", got["detail"])

    def test_agents_heading_without_body_is_gap(self):
        self.write("AGENTS.md", "# 规则\n\n## 硬约束\n\n- [填]\n")
        self.set_dash("")
        got = self.resolve()
        self.assertFalse(got["ok"], got)
        self.assertIn("有标题但没正文", got["gap"], got["gap"])
        self.assertIn("不算已声明硬约束", got["gap"], got["gap"])

    def test_no_sources_at_all_reports_gap(self):
        self.set_dash("")
        got = self.resolve()
        self.assertFalse(got["ok"])
        self.assertIn("硬约束未声明", got["gap"])

    def test_fenced_heading_is_not_a_constraint_section(self):
        """文档里贴的示例 `## 硬约束` 不是真的硬约束段。"""
        self.write("AGENTS.md", "# 规则\n\n```markdown\n## 硬约束\n\n- 示例而已\n```\n")
        self.set_dash("")
        got = self.resolve()
        self.assertFalse(got["ok"], got)
        self.assertEqual(got["status"], "no-section")

    def test_agents_symlink_outside_is_refused(self):
        """AGENTS.md 指向库外时不能把别人的文件当本库硬约束。"""
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "AGENTS.md").write_text(
            "# 别人的规则\n\n## 硬约束\n\n- 这是库外文件。\n", encoding="utf-8")
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            link_file(outside / "AGENTS.md", self.root / "AGENTS.md")
        except (OSError, NotImplementedError) as exc:
            self.skipTest("本机无法创建文件符号链接：%s" % exc)
        self.set_dash("")
        got = self.resolve()
        self.assertFalse(got["ok"], got)
        self.assertEqual(got["status"], "outside", got)
        self.assertIn("指向工作区外", got["gap"])


class CheckSameVerdictTest(TempProject):
    """kb-context 与 kb-check 对同一个库必须给同一个结论。"""

    def test_empty_constraints_both_say_not_ok(self):
        from common import run, run_json
        self.init()
        self.write("05_进度仪表盘.md",
                   "<!-- kb:schema: 2 -->\n# 05\n\n"
                   "<!-- kb:id: dashboard.constraints -->\n## 7. 硬约束\n\n")
        # kb-init 会建一份带「硬约束」段的 AGENTS.md；两边都空才算真的没声明
        self.write("AGENTS.md", "# 规则\n\n## 硬约束\n\n- [填]\n")
        ctx, _ = run_json("kb-context.py", "--target", self.root, "--task", "看现状",
                          "--format", "json")
        check, _ = run_json("kb-check.py", "--target", self.root, "--json")
        self.assertTrue(any("硬约束" in g for g in ctx["gaps"]),
                        "context 应报缺口：%s" % ctx["gaps"])
        levels = [f["level"] for f in check["findings"]
                  if f["category"] == "05 硬约束"]
        self.assertTrue(levels, check["findings"])
        self.assertNotIn("OK", levels,
                         "check 和 context 结论不一致：%s" % check["findings"])
        # 约束缺失是 WARN 级（不阻断接手）：只有 --strict 才当失败
        self.assertEqual(run("kb-check.py", "--target", self.root,
                             "--strict").returncode, 1)


if __name__ == "__main__":
    unittest.main()
