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


class SearchFactsTest(TempProject):
    """三种定义位同权、作废按 status 过滤、流水按相对路径降权。"""

    def setUp(self):
        super().setUp()
        self.write("00_基线.md", """# 00 基线

## 0. 基线表

| ID | 项 | 值 | 状态 | 证据 |
|---|---|---|---|---|
| K-02 | 信道 | 149 | 有效 | `iwinfo` |

## 1. 说明

这里只是正文里提到 K-01（引用，不是定义）。
""")
        self.write("10_固件.md", """# 10 固件

## G-010 当前 NSS 配置

- 加速：qca-nss-ecm 已启用

- **K-01** 固件版本 21.02.3
- **K-03** 旧 DNS 192.0.2.1
<!-- kb:fact-meta: {"status":"deprecated","evidence":"旧","superseded_by":"K-04"} -->
""")
        self.write("06_流水/固件.md", "# 06 流水\n\n## 固件 流水\n\n固件版本 21.02.3 已刷。\n")
        self.write("60_流水/运行态.md", "# 60 流水\n\n## 运行态 流水\n\n固件版本 21.02.3 正常。\n")
        self.write("90_归档.md", "# 90\n\n## 旧结论\n\n固件版本 21.02.3 曾出问题。\n")

    def search(self, *args):
        return run_json("kb-search.py", "--target", self.root, *args, "--json")

    def test_heading_list_table_definitions_are_equal(self):
        """标题 / 列表 / 表格三种定义位，精确搜 ID 时都必须排第一。"""
        cases = {"G-010": "10_固件.md", "K-01": "10_固件.md", "K-02": "00_基线.md"}
        for fid, want in cases.items():
            data, p = self.search("--query", fid)
            self.assertEqual(p.returncode, 0, p.stderr)
            top = data["hits"][0]
            self.assertEqual(top["file"], want, "%s 的命中文件不对：%s" % (fid, top))
            self.assertIn("事实定义位命中 %s" % fid, " ".join(top["reasons"]))

    def test_reference_does_not_masquerade_as_definition(self):
        """正文里提到 K-01 算引用，不能拿到定义位的高分。"""
        data, _ = self.search("--query", "K-01")
        by_file = {h["file"]: h for h in data["hits"]}
        self.assertIn("00_基线.md", by_file, "引用仍然应该能被搜到")
        self.assertLess(by_file["00_基线.md"]["score"], by_file["10_固件.md"]["score"])
        self.assertNotIn("事实定义位命中", " ".join(by_file["00_基线.md"]["reasons"]))

    def test_deprecated_definition_is_filtered_by_status(self):
        data, p = self.search("--query", "192.0.2.1")
        self.assertEqual(p.returncode, 1, "作废定义默认不返回内容：%s" % data.get("hits"))
        self.assertTrue(any(s["fact_id"] == "K-03" for s in data["superseded"]),
                        data.get("superseded"))
        data2, p2 = self.search("--query", "192.0.2.1", "--include-superseded")
        self.assertEqual(p2.returncode, 0, p2.stderr)
        self.assertTrue(any("192.0.2.1" in h["snippet"] for h in data2["hits"]))

    def test_superseded_points_to_replacement(self):
        data, _ = self.search("--query", "K-03")
        row = next(s for s in data["superseded"] if s["fact_id"] == "K-03")
        self.assertEqual(row["superseded_by"], "K-04")
        self.assertIn("K-04", row["message"])

    def test_valid_rows_in_same_section_still_searchable(self):
        """同节里有作废行，不能把整节都判死。"""
        data, p = self.search("--query", "qca-nss-ecm")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(data["hits"][0]["file"], "10_固件.md")

    def test_shard_weighted_lower_by_relative_path(self):
        data, _ = self.search("--query", "21.02.3", "--limit", "10")
        by_file = {h["file"]: h for h in data["hits"]}
        fact = by_file["10_固件.md"]["score"]
        shard = by_file["06_流水/固件.md"]["score"]
        self.assertEqual(by_file["06_流水/固件.md"]["role"], "shard")
        self.assertLess(shard, fact, "流水不能用事实文档的权重")

    def test_loose_shard_alias_weighted_lower(self):
        data, _ = self.search("--query", "21.02.3", "--limit", "10", "--loose")
        row = next(h for h in data["hits"] if h["file"] == "60_流水/运行态.md")
        self.assertEqual(row["role"], "shard")

    def test_root_archive_excluded_by_default(self):
        data, p = self.search("--query", "曾出问题")
        self.assertEqual(p.returncode, 1, data.get("hits"))
        data2, p2 = self.search("--query", "曾出问题", "--include-archive")
        self.assertEqual(p2.returncode, 0, p2.stderr)
        self.assertEqual(data2["hits"][0]["role"], "archive")


class ContextFactsTest(TempProject):
    """P3 走统一事实解析、P4 受控、归档开关、--line 两种写法等价。"""

    def setUp(self):
        super().setUp()
        self.make_filled()
        self.write("11_乙.md", """<!-- kb:schema: 2 -->
# 11 · 乙 — 事实分册

<!-- kb:id: fact.current -->
## 1. 当前值

| 项 | 值 | 状态 | 证据 |
|---|---|---|---|
| 端口 | 8443 | 有效 | `ss -lntp` |
""")
        with open(self.root / "10_甲.md", "a", encoding="utf-8", newline="\n") as f:
            f.write("\n### G-010 当前 NSS 配置\n"
                    '<!-- kb:fact-meta: {"status":"valid","evidence":"lsmod",'
                    '"verified_at":"2026-11-10","owner":"固件"} -->\n'
                    "- 加速：`qca-nss-ecm` 已启用\n"
                    "\n### G-011 旧 DNS 处理\n"
                    '<!-- kb:fact-meta: {"status":"deprecated","evidence":"改用 DoH",'
                    '"superseded_by":"K-04"} -->\n'
                    "- 192.0.2.1 已废弃\n")

    def ctx(self, *args):
        data, p = run_json("kb-context.py", "--target", self.root, "--format", "json", *args)
        return data, p

    def titles(self, data, priority="P3"):
        return [b["title"] for b in data["blocks"] if b["priority"] == priority]

    def test_p3_locates_heading_fact(self):
        data, p = self.ctx("--task", "G-010 现在是什么", "--budget", "3000")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(any("G-010" in t for t in self.titles(data)), self.titles(data))
        text = " ".join(data["context"].values())
        self.assertIn("qca-nss-ecm", text, "标题定义的正文必须进来")

    def test_p3_locates_table_fact(self):
        data, _ = self.ctx("--task", "K-01 的当前值是什么", "--budget", "3000")
        self.assertTrue(any("K-01" in t for t in self.titles(data)), self.titles(data))
        text = " ".join(data["context"].values())
        self.assertIn("21.02.3", text)
        self.assertIn("| ID |", text, "表格事实要带表头，否则读不出列含义")

    def test_deprecated_fact_becomes_gap_not_context(self):
        data, _ = self.ctx("--task", "G-011 还能用吗", "--budget", "3000")
        self.assertFalse(any("G-011" in t for t in self.titles(data)))
        joined = " ".join(data["gaps"])
        self.assertIn("已作废", joined)
        self.assertIn("K-04", joined, "作废事实必须指出替代 ID")

    def test_missing_fact_is_reported_not_invented(self):
        data, _ = self.ctx("--task", "K-77 是什么", "--budget", "3000")
        self.assertTrue(any("K-77" in g for g in data["gaps"]), data["gaps"])
        self.assertFalse(any("K-77" in t for t in self.titles(data)))

    def test_p4_capped_by_count_and_budget(self):
        data, _ = self.ctx("--task", "NSS 加速 固件 版本 端口 信道 掉速 升级",
                           "--budget", "3000")
        p4 = [b for b in data["blocks"] if b["priority"] == "P4"]
        self.assertLessEqual(len(p4), 3, "P4 最多 3 块")
        self.assertLessEqual(data["p4"]["tokens"], int(3000 * 0.30), "P4 不得超过预算 30%")
        self.assertLessEqual(data["used"], 3000, "最终渲染必须仍在预算内")

    def test_zero_p4_is_acceptable(self):
        data, _ = self.ctx("--task", "查看当前项目状态", "--budget", "3000")
        self.assertEqual(data["p4"]["count"], 0)
        self.assertTrue(any("P4" in g for g in data["gaps"]), data["gaps"])

    def test_include_archive_really_works(self):
        self.write("归档/旧闻.md", "# 旧闻\n\n## 秘辛\n\n绝密口令ZYX 在旧闻里\n")
        data, _ = self.ctx("--task", "绝密口令ZYX", "--budget", "3000")
        self.assertNotIn("绝密口令ZYX", " ".join(data["context"].values()),
                         "默认不装配归档")
        data2, _ = self.ctx("--task", "绝密口令ZYX", "--budget", "3000",
                            "--include-archive")
        self.assertIn("绝密口令ZYX", " ".join(data2["context"].values()),
                      "给了 --include-archive 就必须真的检索归档")

    def test_line_repeat_equals_comma(self):
        a, _ = self.ctx("--task", "查看现状", "--line", "甲,乙")
        b, _ = self.ctx("--task", "查看现状", "--line", "甲", "--line", "乙")
        self.assertEqual(sorted(a["selected_lines"]), sorted(b["selected_lines"]))
        self.assertEqual(sorted(a["selected_lines"]), ["乙", "甲"])

    def test_line_dedup_and_order(self):
        data, _ = self.ctx("--task", "查看现状", "--line", "乙", "--line", "乙,甲")
        self.assertEqual(data["selected_lines"], ["乙", "甲"], "去重且保留顺序")

    def test_unknown_line_is_reported(self):
        data, _ = self.ctx("--task", "查看现状", "--line", "不存在")
        self.assertEqual(data["selected_lines"], [])
        self.assertTrue(any("不存在" in g for g in data["gaps"]), data["gaps"])

    # -- P4 不能把「已作废」当普通当前上下文 ----------------------------- #
    def test_p4_skips_deprecated_only_section(self):
        self.write("12_旧.md", """<!-- kb:schema: 2 -->
# 12 · 历史记录

## 1. 归档备注

### G-012 旧 DNS 缓存
<!-- kb:fact-meta: {"status":"deprecated","superseded_by":"K-04"} -->
- 缓存令牌ZZZ9377，TTL 3600
""")
        data, _ = self.ctx("--task", "DNS 缓存 TTL 缓存令牌ZZZ9377", "--line", "甲",
                           "--budget", "3000")
        text = " ".join(data["context"].values())
        self.assertNotIn("缓存令牌ZZZ9377", text, "整节已作废的内容默认不得进入上下文")
        self.assertGreaterEqual(data["p4"]["deprecated_skipped"], 1)
        self.assertTrue(any("已作废" in g and "历史" in g for g in data["gaps"]),
                        data["gaps"])

    def test_p4_brings_deprecated_back_when_task_asks_history(self):
        self.write("12_旧.md", """<!-- kb:schema: 2 -->
# 12 · 历史记录

## 1. 归档备注

### G-012 旧 DNS 缓存
<!-- kb:fact-meta: {"status":"deprecated","superseded_by":"K-04"} -->
- 缓存令牌ZZZ9377，TTL 3600
""")
        data, _ = self.ctx("--task", "以前 DNS 缓存 TTL 缓存令牌ZZZ9377 是什么",
                           "--line", "甲", "--budget", "3000")
        p4 = [b for b in data["blocks"] if b["priority"] == "P4"]
        self.assertTrue(any("含已作废" in b["title"] for b in p4), p4)
        text = " ".join(data["context"].values())
        self.assertIn("缓存令牌ZZZ9377", text, "问历史时必须能查到作废内容")
        self.assertIn("已作废：G-012", text, "作废内容必须自带标注，不能冒充当前配置")
        self.assertIn("K-04", text)

    def test_p4_include_superseded_flag_is_explicit(self):
        """不靠中文关键词猜：显式 --include-superseded 也能带回历史。"""
        self.write("12_旧.md", """<!-- kb:schema: 2 -->
# 12 · 历史记录

## 1. 归档备注

### G-012 旧 DNS 缓存
<!-- kb:fact-meta: {"status":"deprecated","superseded_by":"K-04"} -->
- 缓存令牌ZZZ9377，TTL 3600
""")
        data, _ = self.ctx("--task", "DNS 缓存 TTL 缓存令牌ZZZ9377", "--line", "甲",
                           "--budget", "3000", "--include-superseded")
        text = " ".join(data["context"].values())
        self.assertIn("缓存令牌ZZZ9377", text)
        self.assertIn("已作废：G-012", text)

    MIXED = """<!-- kb:schema: 2 -->
# 12 · 历史记录

## 1. 缓存区

### G-013 现行缓存策略
<!-- kb:fact-meta: {"status":"valid","evidence":"cat cfg"} -->
- 缓存令牌ZZZ9377 = 60s

### G-014 旧缓存策略
<!-- kb:fact-meta: {"status":"deprecated","superseded_by":"G-013"} -->
- 缓存令牌ZZZ9377 = 3600s
"""

    def test_mixed_section_keeps_valid_part_and_omits_deprecated(self):
        self.write("12_旧.md", self.MIXED)
        data, _ = self.ctx("--task", "DNS 缓存 TTL 缓存令牌ZZZ9377", "--line", "甲",
                           "--budget", "3000")
        text = " ".join(data["context"].values())
        self.assertIn("60s", text, "同一节里的有效内容不能因为邻居作废而被丢掉")
        self.assertNotIn("3600s", text, "作废的那几行必须置空，不能冒充当前配置")
        self.assertIn("已省略 1 条已作废事实：G-014", text, "省略了就要说，别让读者以为没这条")

    def test_mixed_section_kept_in_full_when_history_is_asked(self):
        self.write("12_旧.md", self.MIXED)
        data, _ = self.ctx("--task", "DNS 缓存 TTL 缓存令牌ZZZ9377", "--line", "甲",
                           "--budget", "3000", "--include-superseded")
        text = " ".join(data["context"].values())
        self.assertIn("60s", text)
        self.assertIn("3600s", text, "问历史时作废值也要给出来")
        self.assertIn("已作废：G-014", text, "给出来时必须标注，并指出替代 G-013")


class EntryFileSafetyTest(TempProject):
    """AGENTS.md 是入口文件，也可能是符号链接：读之前必须核对真实路径。"""

    def setUp(self):
        super().setUp()
        self.make_filled()

    def ctx(self, *args):
        return run_json("kb-context.py", "--target", self.root, "--format", "json", *args)

    def strip_constraints(self):
        """拿掉 dashboard 的硬约束段，逼 kb-context 走 AGENTS.md 兜底。"""
        p = self.root / "05_进度仪表盘.md"
        text = p.read_text(encoding="utf-8")
        head = text.split("<!-- kb:id: dashboard.constraints -->")[0]
        p.write_text(head, encoding="utf-8", newline="\n")

    def test_agents_fallback_still_works(self):
        self.strip_constraints()
        self.write("AGENTS.md", "# AGENTS\n\n## 硬约束\n\n- 不许动 r1\n")
        data, _ = self.ctx("--task", "查看现状", "--budget", "3000")
        titles = [b["title"] for b in data["blocks"] if b["priority"] == "P0"]
        self.assertIn("硬约束（AGENTS.md）", titles)
        self.assertIn("不许动 r1", " ".join(data["context"].values()))

    def test_agents_fallback_does_not_report_false_gap(self):
        """兜底成功了就不该再报「缺 dashboard.constraints」。

        先查 dashboard 就记缺口、后面又从 AGENTS 补上，会让每个任务都带一条
        假缺口，把人引去补一个并不缺的 kb:id。
        """
        self.strip_constraints()
        self.write("AGENTS.md", "# AGENTS\n\n## 硬约束\n\n- 不许动 r1\n")
        data, _ = self.ctx("--task", "查看现状", "--budget", "3000")
        self.assertTrue(any(b["priority"] == "P0" for b in data["blocks"]))
        self.assertFalse([g for g in data["gaps"]
                          if "缺少 kb:id: dashboard.constraints" in g],
                         "已从 AGENTS 兜底到硬约束，不该再报缺 id：%s" % data["gaps"])

    def test_gap_reported_when_nothing_can_supply_constraints(self):
        """三级兜底全落空时才报缺口——不能因为加了兜底就把真缺口也吞掉。"""
        self.strip_constraints()
        agents = self.root / "AGENTS.md"
        if agents.exists():
            agents.unlink()
        data, _ = self.ctx("--task", "查看现状", "--budget", "3000")
        self.assertFalse(any(b["priority"] == "P0" for b in data["blocks"]))
        self.assertTrue(any("缺少 kb:id: dashboard.constraints" in g
                            for g in data["gaps"]), data["gaps"])

    def test_agents_symlink_outside_is_refused(self):
        import os
        self.strip_constraints()
        outside = self.tmp / "outside"
        outside.mkdir(exist_ok=True)
        secret = outside / "AGENTS.md"
        secret.write_text("# 别人的 AGENTS\n\n## 硬约束\n\n- 库外机密约束ZZZ\n",
                          encoding="utf-8")
        link = self.root / "AGENTS.md"
        if link.exists():
            link.unlink()          # kb-init 默认会建一份，先挪开才能放链接
        try:
            os.symlink(str(secret), str(link))
        except (OSError, NotImplementedError) as exc:
            self.skipTest("本机无法创建文件符号链接：%s" % exc)
        data, _ = self.ctx("--task", "查看现状", "--budget", "3000")
        text = " ".join(data["context"].values())
        self.assertNotIn("库外机密约束ZZZ", text, "库外文件不能冒充本库硬约束")
        self.assertFalse(any(b["priority"] == "P0" and "AGENTS" in b["title"]
                             for b in data["blocks"]))
        self.assertTrue(any("工作区外" in g for g in data["gaps"]), data["gaps"])

    def test_agents_junction_dir_named_agents_is_ignored(self):
        """AGENTS.md 若是个目录链接（Junction），不是文件，不该被当成入口。"""
        import os
        import subprocess
        self.strip_constraints()
        outside = self.tmp / "outside2"
        outside.mkdir(exist_ok=True)
        (outside / "x.md").write_text("# 库外\n", encoding="utf-8")
        link = self.root / "AGENTS.md"
        if link.exists():
            link.unlink()
        try:
            os.symlink(str(outside), str(link), target_is_directory=True)
        except (OSError, NotImplementedError):
            r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                               capture_output=True)
            if r.returncode != 0:
                self.skipTest("本机无法创建目录链接：%s"
                              % (r.stdout + r.stderr).decode("utf-8", "replace").strip())
        data, p = self.ctx("--task", "查看现状", "--budget", "3000")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(any("AGENTS" in b["title"] for b in data["blocks"]))


class P4HygieneTest(TempProject):
    """P4 只补「确实相关」的内容——别让噪声抢走那几个名额。

    这里的每一条都对应一次实测浪费：agent 工作日志、空壳父节、文件导语
    都会因为「命中词多」排到前面，把真正的结论条目挤出去。
    """

    def setUp(self):
        super().setUp()
        self.make_filled()

    def ctx(self, *args):
        return run_json("kb-context.py", "--target", self.root, "--format", "json", *args)

    def all_text(self, data):
        return " ".join(data["context"].values())

    def test_agent_memory_dirs_are_not_searched(self):
        """`.workbuddy` / `.shared` 里的 md 是 agent 工作日志，不是交接正文。"""
        log = ("# 工作日志\n\n## 刷机记录\n\n"
               "- 固件 21.02.3 刷机完成，重载 nss 后恢复；这条只该留在日志里\n")
        self.write(".shared/memory/2026-11-10.md", log)
        self.write(".workbuddy/memory/2026-11-10.md", log)
        data, p = self.ctx("--task", "固件刷机完成后怎么恢复", "--budget", "3000")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("这条只该留在日志里", self.all_text(data),
                         "agent 记忆目录不该参与 P4 检索")

    def test_empty_parent_section_never_becomes_p4(self):
        """只有标题、正文全在子节里的父节不参与打分。

        它的子节会各自成为候选；父节命中只说明标题里有那个词，
        装进去就是一段空壳，还占掉一个名额。
        """
        self.write("20_乙.md", "# 20 · 乙\n\n"
                   "## 固件刷机\n\n"
                   "### 刷机后检查\n\n"
                   "- 固件刷机后先 `cat /etc/version` 再重载 nss。\n")
        data, _ = self.ctx("--task", "固件刷机后检查什么", "--budget", "3000")
        heads = [b["title"] for b in data["blocks"] if b["priority"] == "P4"]
        self.assertNotIn("相关补充 · 固件刷机", heads)
        self.assertIn("相关补充 · 刷机后检查", heads, heads)

    def test_document_lead_section_is_skipped(self):
        """文件导语（第一个 h1 节）命中词天然最多，不能靠它抢 P4 名额。"""
        self.write("30_丙.md", "# 30 · 固件刷机总纲\n\n"
                   "固件刷机的全部内容都在本文件：刷机前备份、刷机后检查、nss 重载。\n\n"
                   "## 刷机后检查\n\n"
                   "- 刷机后 `cat /etc/version` 必须回 21.02.3，否则回滚。\n")
        data, _ = self.ctx("--task", "固件刷机后检查", "--budget", "3000")
        heads = [b["title"] for b in data["blocks"] if b["priority"] == "P4"]
        self.assertNotIn("相关补充 · 30 · 固件刷机总纲", heads)
        self.assertIn("相关补充 · 刷机后检查", heads, heads)

    def test_other_role_is_downweighted(self):
        """`other` 不是结构内正文（一次性发布稿、检索记录、入口文件），权重低于 fact。

        真实库里 62 KB 的检索记录凭体积就能从任何任务里命中几个词；跟分册正文
        同权重时，P4 的 3 个名额会被它抢走，装进来的却不是结论。
        """
        self.write("临时记录.md",
                   "# 临时记录\n\n## 固件刷机备忘\n\n- 固件刷机备忘：先备份 ZZQ\n")
        data, _ = self.ctx("--task", "固件刷机备忘", "--budget", "3000")
        reasons = [b["reason"] for b in data["blocks"] if b["priority"] == "P4"]
        self.assertTrue(reasons, "夹具里应该有可补的 P4 内容")
        self.assertTrue(any("权重 0.5" in r and "other" in r for r in reasons), reasons)

    def test_fact_role_keeps_full_weight(self):
        """降权只针对 other：事实分册仍是 1.0，别把真正文一起压下去。"""
        self.write("11_乙.md", "# 11 · 乙\n\n## 固件刷机判据\n\n- 刷机判据 ZZQ\n")
        data, _ = self.ctx("--task", "固件刷机判据", "--budget", "3000")
        reasons = [b["reason"] for b in data["blocks"]
                   if b["priority"] == "P4" and "fact" in b["reason"]]
        self.assertTrue(reasons, [b["reason"] for b in data["blocks"]])
        self.assertTrue(all("权重 1.0" in r for r in reasons), reasons)

    def test_same_content_is_not_loaded_twice(self):
        """block 的 source 只有文件名，P4 比的是相对路径：子目录同名会漏判重复。"""
        body = "- 刷机完成判据：`cat /etc/version` 回 21.02.3。\n"
        self.write("子目录/40_丁.md", "# 40 · 丁\n\n## 刷机完成判据\n\n" + body)
        data, _ = self.ctx("--task", "刷机完成判据", "--budget", "3000")
        text = self.all_text(data)
        self.assertLessEqual(text.count("刷机完成判据"), 2,
                             "同一节被装了不止一次：%s" % text.count("刷机完成判据"))

    def test_p2_gap_is_rewritten_when_p4_fills_facts(self):
        """P2 靠线名命中，任务里没线名就空；P4 补到事实后那条缺口已经作废。"""
        data, _ = self.ctx("--task", "版本 21.02.3 怎么核", "--budget", "3000")
        got_fact = [b for b in data["blocks"]
                    if b["priority"] == "P4" and "当前值" in b["title"]]
        if not got_fact:
            self.skipTest("本夹具下 P4 没补到事实节，另有用例覆盖")
        self.assertFalse([g for g in data["gaps"]
                          if g.startswith("任务没有命中任何事实分册")],
                         "P4 已经补到事实，不该再说「没命中任何事实分册」：%s" % data["gaps"])


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
