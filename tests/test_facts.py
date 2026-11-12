#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""facts：三种定义位、状态归一、引用/重复、元数据校验、定点改写。"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import facts  # noqa: E402


class FactsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kbfacts-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "proj"
        self.root.mkdir(parents=True)

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def defs(self, rel="00_基线.md"):
        d, _ = facts.parse_document(self.root / rel, rel)
        return d

    # 1
    def test_heading_definition(self):
        self.write("00_基线.md", "# 00\n\n## K-01 固件版本\n\n- 值：21.02\n")
        d = self.defs()[0]
        self.assertEqual((d.id, d.definition_type, d.title), ("K-01", "heading", "固件版本"))

    # 2
    def test_list_definition(self):
        self.write("00_基线.md", "# 00\n\n- **K-02** 信道 149\n")
        d = self.defs()[0]
        self.assertEqual((d.id, d.definition_type), ("K-02", "list"))

    # 3
    def test_table_first_column_definition(self):
        self.write("00_基线.md",
                   "# 00\n\n| ID | 项 | 值 | 状态 | 证据 |\n|---|---|---|---|---|\n"
                   "| K-03 | 速率 | 300M | 有效 | iwinfo |\n")
        d = self.defs()[0]
        self.assertEqual((d.id, d.definition_type, d.status), ("K-03", "table", "valid"))

    # 4
    def test_fenced_code_is_not_a_definition(self):
        self.write("00_基线.md", "# 00\n\n```\n| K-09 | 假 | x | 有效 | - |\n```\n")
        self.assertEqual(self.defs(), [])

    # 5
    def test_status_normalization(self):
        cases = {"有效": "valid", "valid": "valid", "待核": "pending",
                 "已作废": "deprecated", "乱写": "unknown"}
        for text, want in cases.items():
            self.assertEqual(facts.normalize_status(text), want, text)

    # 6
    def test_definition_line_other_ids_count_as_references(self):
        self.write("00_基线.md",
                   "# 00\n\n| ID | 项 | 值 | 状态 | 证据 |\n|---|---|---|---|---|\n"
                   "| K-01 | DNS | 1.1.1.1 | 已作废 → K-02 | dig |\n"
                   "| K-02 | DNS 新 | 8.8.8.8 | 有效 | dig |\n")
        defs, refs = facts.parse_document(self.root / "00_基线.md", "00_基线.md")
        self.assertEqual({d.id for d in defs}, {"K-01", "K-02"})
        self.assertEqual([r.id for r in refs], ["K-02"])

    # 7
    def test_duplicate_definitions_reported_with_all_locations(self):
        self.write("00_基线.md", "# 00\n\n- **K-05** a\n\n- **K-05** b\n")
        by_id, _ = facts.parse_fact_definitions(self.root)
        dups = facts.duplicates(by_id)
        self.assertIn("K-05", dups)
        self.assertEqual(len(dups["K-05"]), 2)

    # 8
    def test_bad_fact_meta_json_reports_error(self):
        self.write("00_基线.md",
                   "# 00\n\n## K-01 固件\n<!-- kb:fact-meta: {not json} -->\n\n正文\n")
        d = self.defs()[0]
        self.assertIn("fact-meta 解析失败", d.meta_error)

    # 9
    def test_good_fact_meta_is_parsed(self):
        self.write("00_基线.md",
                   '# 00\n\n## K-01 固件\n<!-- kb:fact-meta: {"status":"待核",'
                   '"owner":"固件","volatility":"dynamic"} -->\n\n正文\n')
        d = self.defs()[0]
        self.assertEqual((d.status, d.owner, d.volatility), ("pending", "固件", "dynamic"))

    # 10
    def test_verified_at_placeholder_is_not_an_error(self):
        self.write("00_基线.md",
                   "# 00\n\n| ID | 项 | 值 | 状态 | 证据 | 核实时间 |\n|---|---|---|---|---|---|\n"
                   "| K-02 | 信道 | 待测 | 待核 | — | — |\n")
        issues, _ = facts.validate_fact_metadata(self.root)
        self.assertEqual([i for i in issues if i["kind"] == "verified_at"], [])

    # 11
    def test_valid_without_evidence_is_flagged(self):
        self.write("00_基线.md",
                   "# 00\n\n| ID | 项 | 值 | 状态 | 证据 |\n|---|---|---|---|---|\n"
                   "| K-01 | 版本 | 21.02 | 有效 | — |\n")
        issues, _ = facts.validate_fact_metadata(self.root)
        self.assertTrue(any(i["kind"] == "evidence" for i in issues))

    # 12
    def test_superseded_arrow_in_table_row(self):
        self.write("00_基线.md",
                   "# 00\n\n| ID | 项 | 值 | 状态 | 证据 |\n|---|---|---|---|---|\n"
                   "| K-03 | 旧 DNS | 192.0.2.1 | 已作废 → K-04 | x |\n"
                   "| K-04 | 新 DNS | 1.1.1.1 | 有效 | y |\n")
        d = {x.id: x for x in self.defs()}
        self.assertEqual(d["K-03"].superseded_by, "K-04")
        issues, _ = facts.validate_fact_metadata(self.root)
        self.assertFalse(any(i["kind"] == "superseded" for i in issues))

    # 13
    def test_deprecated_without_superseded_is_flagged(self):
        self.write("00_基线.md",
                   "# 00\n\n| ID | 项 | 值 | 状态 | 证据 |\n|---|---|---|---|---|\n"
                   "| K-03 | 旧 DNS | 192.0.2.1 | 已作废 | x |\n")
        issues, _ = facts.validate_fact_metadata(self.root)
        self.assertTrue(any(i["kind"] == "superseded" for i in issues))

    # 14
    def test_update_heading_definition(self):
        text = "# 00\n\n## K-01 固件版本\n\n- 值：21.02\n"
        out = facts.update_fact_definition(text, "K-01", "## K-01 固件版本（已核实）", "00.md")
        self.assertIn("## K-01 固件版本（已核实）", out)
        self.assertIn("- 值：21.02", out)

    # 15
    def test_update_list_and_table_definition(self):
        text = "- **K-02** 信道 149\n"
        out = facts.update_fact_definition(text, "K-02", "- **K-02** 信道 153", "00.md")
        self.assertIn("153", out)

        table = ("| ID | 项 | 值 |\n|---|---|---|\n| K-03 | 速率 | 300M |\n")
        out = facts.update_fact_definition(
            table, "K-03", "| K-03 | 速率 | 866M |", "00.md")
        self.assertIn("| K-03 | 速率 | 866M |", out)

    # 16
    def test_update_rejects_wrong_shape(self):
        text = "## K-01 固件\n"
        with self.assertRaises(facts.FactError):
            facts.update_fact_definition(text, "K-01", "- 不是标题行", "00.md")
        table = "| ID | 项 | 值 |\n|---|---|---|\n| K-03 | 速率 | 300M |\n"
        with self.assertRaises(facts.FactError):
            facts.update_fact_definition(table, "K-03", "| K-03 | 只有两列 |", "00.md")

    # 17
    def test_update_rejects_ambiguous_and_missing(self):
        twice = "## K-01 a\n\n## K-01 b\n"
        with self.assertRaises(facts.FactError):
            facts.update_fact_definition(twice, "K-01", "## K-01 c", "00.md")
        with self.assertRaises(facts.FactError):
            facts.update_fact_definition("# 空\n", "K-01", "## K-01 c", "00.md")

    # 18
    def test_find_fact_and_references(self):
        self.write("00_基线.md", "# 00\n\n- **K-01** 版本 21.02\n")
        self.write("05_进度仪表盘.md", "# 05\n\nK-01 已核；K-99 未定义。\n")
        found = facts.find_fact(self.root, "K-01")
        self.assertEqual(len(found), 1)
        refs = facts.find_fact_references(self.root)
        self.assertIn(("05_进度仪表盘.md", "K-01"),
                      [(r.path, r.id) for r in refs])

    # 19
    def test_update_refuses_to_change_fact_id(self):
        """update_fact 只能改内容，不能顺手换 ID —— 换了就等于删掉旧事实。"""
        text = "## K-01 固件版本\n\n- 值：21.02\n- 证据：a.log\n"
        for evil in ("## K-99 新事实", "### K-99 新事实", "## G-01 换个前缀"):
            with self.assertRaises(facts.FactError) as ctx:
                facts.update_fact_definition(text, "K-01", evil, "00.md")
            self.assertIn("不可变", str(ctx.exception), evil)
        self.assertEqual(text, "## K-01 固件版本\n\n- 值：21.02\n- 证据：a.log\n",
                         "被拒绝时不得改动原文本")

    def test_update_heading_keeps_following_body(self):
        text = "## G-010 当前 NSS 配置\n\n证据：`nss.log`\n其余说明也保留\n"
        out = facts.update_fact_definition(text, "G-010", "## G-010 当前 NSS 配置（已核实）")
        self.assertIn("证据：`nss.log`", out)
        self.assertIn("其余说明也保留", out)

    def test_update_rejects_multiline_content(self):
        """只替换定义行；多行 content 会被静默丢弃 → 必须拒绝而不是替用户删内容。"""
        text = "## K-01 固件\n\n- 值：1\n"
        with self.assertRaises(facts.FactError) as ctx:
            facts.update_fact_definition(text, "K-01", "## K-01 新标题\n\n新正文")
        self.assertIn("单行", str(ctx.exception))

    # 20
    def test_counts_separate_empty_from_all_good(self):
        """一条事实都没有 ≠ 全部通过：统计口径必须能区分。"""
        empty, problems = facts.parse_fact_definitions(self.root)
        c = facts.counts(empty, problems)
        self.assertEqual(c["definitions"], 0)
        self.write("10_固件.md", "# 10\n\n- **K-01** 版本 21.02\n")
        defs, problems = facts.parse_fact_definitions(self.root)
        c = facts.counts(defs, problems)
        self.assertEqual(c["definitions"], 1)
        self.assertEqual(c["ids"], 1)

    # 21
    def test_definition_text_includes_table_header(self):
        self.write("00_基线.md",
                   "# 00\n\n| ID | 项 | 值 | 状态 | 证据 |\n|---|---|---|---|---|\n"
                   "| K-01 | 版本 | 21.02 | 有效 | x |\n")
        defs, _ = facts.parse_fact_definitions(self.root)
        d = defs["K-01"][0]
        text = facts.definition_text(self.root, d)
        self.assertIn("| ID | 项 | 值 | 状态 | 证据 |", text)
        self.assertIn("| K-01 | 版本 | 21.02 | 有效 | x |", text)

    def test_definition_text_heading_returns_body(self):
        self.write("10_固件.md", "# 10\n\n## G-010 当前 NSS 配置\n\n证据：nss.log\n")
        defs, _ = facts.parse_fact_definitions(self.root)
        d = defs["G-010"][0]
        text = facts.definition_text(self.root, d)
        self.assertIn("G-010 当前 NSS 配置", text)
        self.assertIn("证据：nss.log", text)

    # 索引页里的条目是指针，不是第二条定义（真实库上曾报 4 条假重复）
    def test_index_page_pointer_is_not_a_duplicate(self):
        self.write("00_INDEX.md",
                   "# 索引\n\n## 当前空白\n\n- G-018：菜单未整理；G-004：上限有歧义。\n")
        self.write("10_游戏事实.md",
                   "# 10\n\n### G-018 菜单\n- 结论：未整理。\n\n"
                   "### G-004 上限\n- 结论：两套口径。\n")
        by_id, _ = facts.parse_fact_definitions(self.root)
        self.assertEqual(facts.duplicates(by_id), {})
        # 一条列表项只定义它开头那个 ID，句中的 G-004 仍算引用
        self.assertEqual(sorted(facts.pointer_only(by_id)), ["G-018"])
        c = facts.counts(by_id, [])
        self.assertEqual((c["definitions"], c["canonical"], c["pointers"]), (3, 2, 1))
        self.assertEqual(c["duplicated_ids"], 0)
        # 规范定义（分册）排在指针之前
        self.assertEqual(facts.canonical(by_id["G-018"])[0].path, "10_游戏事实.md")

    def test_same_id_twice_in_one_index_page_still_duplicates(self):
        """索引页内部自己重复两遍，就没有「规范定义」可退回，必须照报。"""
        self.write("00_索引.md", "# 索引\n\n- K-01：a\n\n- K-01：b\n")
        by_id, _ = facts.parse_fact_definitions(self.root)
        self.assertIn("K-01", facts.duplicates(by_id))

    def test_index_named_page_holding_only_facts_keeps_them(self):
        """整页都叫索引、但全库只有这样一份事实：不能因为「是指针」就丢掉。"""
        self.write("00_INDEX.md",
                   "# 索引\n\n| ID | 项 | 状态 | 证据 |\n|---|---|---|---|\n"
                   "| K-07 | 版本 | 有效 | x |\n")
        by_id, _ = facts.parse_fact_definitions(self.root)
        self.assertEqual(by_id["K-07"][0].status, "valid")
        self.assertEqual(facts.canonical(by_id["K-07"])[0].path, "00_INDEX.md")
        self.assertEqual(facts.counts(by_id, [])["pointers"], 0)

    def test_similar_name_is_not_an_index_page(self):
        for name in ("00_共享页.md", "索引式清单说明.md", "10_游戏事实.md"):
            self.assertFalse(facts.is_index_page(name), name)
        for name in ("00_INDEX.md", "00_索引.md", "TOC.md", "00_索引_ffrs.md"):
            self.assertTrue(facts.is_index_page(name), name)


if __name__ == "__main__":
    unittest.main()
