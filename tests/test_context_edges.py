#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2.0.2 验收补的边界用例。

三个真实形态，都是「按条数 / 按字符数拍脑袋」会漏掉的：

- 刚建线、只有一条事实的分册（`## G-001 当前 MTU`）：不该因为没凑够两条就被
  判成散文，也不该让 `--line` 变成空操作。
- 容器兜底的 600 token 边界：599 / 600 触发，601 不触发；判据必须和预算用
  同一个计数器，否则 cl100k 下两套单位打架。
- 去重不能伤到 P0：硬约束宁可重复也不能被「别处有同文」挤掉；不同事实、
  同名不同路径的文件不能被错误合并。
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1] / "scripts"))
sys.path.insert(0, str(HERE.parent))

from lib import facts, markdown as md, tokens  # noqa: E402

from common import TempProject, run_json  # noqa: E402


SHARD = """# 20 · 网络配置

## G-001 当前 MTU

WAN 当前使用 MTU 1480。修改前必须检查运营商连接要求。
"""

CONSTRAINT = "- 不擅自重启 r1；凭证不入库。"


def load_script(name: str):
    """按路径加载 scripts/ 下的脚本（文件名带连字符，不能直接 import）。"""
    path = HERE.parents[1] / "scripts" / ("%s.py" % name)
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MinimalLibrary(TempProject):
    """只有 00 / 05 / AGENTS 的 v2 库：P0 与 P1 之外没有噪声候选。"""

    def make_minimal(self, files=None, constraint=CONSTRAINT):
        self.write("00_基线.md",
                   "<!-- kb:schema: 2 -->\n# 00 · 基线\n\n"
                   "| ID | 项 | 当前值 | 状态 | 证据 |\n|---|---|---|---|---|\n"
                   "| K-01 | 固件版本 | 21.02.3 | 有效 | `ls` |\n")
        self.write("05_进度仪表盘.md",
                   "<!-- kb:schema: 2 -->\n# 05 · 进度仪表盘\n\n"
                   "<!-- kb:id: dashboard.constraints -->\n## 7. 硬约束\n\n"
                   + constraint + "\n\n"
                   "<!-- kb:id: dashboard.current -->\n## 0. 现状\n\n"
                   "固件 21.02.3 稳定运行。\n\n"
                   "<!-- kb:id: dashboard.next -->\n## 1. 下一手\n\n"
                   "- 采集信号。\n")
        self.write("AGENTS.md", "# AGENTS\n\n## 硬约束\n\n- 不擅自重启 r1。\n")
        for rel, text in (files or {}).items():
            self.write(rel, text)

    def ctx(self, *args):
        return run_json("kb-context.py", "--target", self.root,
                        "--format", "json", *args)


class SingleFactShardTest(MinimalLibrary):
    """一条事实的分册：自动检索要能发现，--line 要真加载。"""

    def setUp(self):
        super().setUp()
        self.make_minimal({"20_网络配置.md": SHARD})

    def test_single_entry_shard_is_structured_not_prose(self):
        conf = facts.fact_confidence(self.root / "20_网络配置.md", loose=True)
        self.assertEqual(conf, "structured",
                         "标题就是 G-001，一条也算事实分册；判成散文会让它只拿 0.5 权重")

    def test_single_entry_mentions_in_body_stay_candidate(self):
        """正文里提到一次编号不算分册：那可能只是举例（弱证据仍要 ≥2 条）。"""
        self.write("30_备忘.md", "# 30 · 备忘\n\n- G-001 只是举例说明。\n")
        self.assertEqual(facts.fact_confidence(self.root / "30_备忘.md", loose=True),
                         "candidate")

    def test_auto_retrieval_keeps_the_only_fact(self):
        data, p = self.ctx("--loose", "--task", "当前 WAN MTU 是多少", "--budget", "3000")
        self.assertEqual(p.returncode, 0, p.stderr)
        got = [b for b in data["blocks"] if b["priority"] == "P4"]
        self.assertEqual(len(got), 1, [b["title"] for b in data["blocks"]])
        text = data["context"][got[0]["section_id"] or got[0]["title"]]
        self.assertIn("MTU 1480", text)
        self.assertIn("运营商连接要求", text, "装进来的必须是整节，不能只剩标题")
        self.assertEqual([r["source_path"] for r in data["p4_facts"]],
                         ["20_网络配置.md"],
                         "它确实是事实节，不能报成「只有编号、没有事实条目」")
        self.assertFalse([g for g in data["gaps"] if "没有事实条目" in g], data["gaps"])

    def test_line_loads_shard_without_kb_ids(self):
        """`--line` 指定了这条线，分册没打 kb:id 也必须能取到事实节。"""
        data, p = self.ctx("--loose", "--line", "网络配置", "--task", "检查当前 MTU",
                           "--budget", "3000")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(data["selected_lines"], ["网络配置"])
        p2 = [b for b in data["blocks"] if b["priority"] == "P2"]
        self.assertEqual(len(p2), 1, [b["title"] for b in data["blocks"]])
        text = data["context"][p2[0]["section_id"] or p2[0]["title"]]
        self.assertIn("MTU 1480", text)
        self.assertFalse([g for g in data["gaps"] if "没有可加载" in g],
                         "已经装进来了还说没有可加载的节：%s" % data["gaps"])
        self.assertIn("网络配置 已加载", " ".join(data["gaps"]), data["gaps"])

    def test_line_squeezed_by_budget_is_reported_honestly(self):
        """预算不够时不能假装加载，也不能悄悄少装。"""
        data, p = self.ctx("--loose", "--line", "网络配置", "--task", "检查当前 MTU",
                           "--budget", "120")
        self.assertIn(p.returncode, (0, 1), p.stderr)
        self.assertTrue(data["over_budget"], data["used"])
        self.assertEqual(data["omitted_lines"], ["网络配置"], data)
        joined = " ".join(data["gaps"])
        self.assertIn("预算", joined, data["gaps"])
        self.assertNotIn("网络配置 已加载", joined, data["gaps"])

    def test_strict_mode_still_ignores_the_numbered_shard(self):
        """严格模式不改原有规则：非协议编号不进事实线。"""
        data, p = self.ctx("--task", "当前 WAN MTU 是多少", "--budget", "3000")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(data["selected_lines"], [])
        self.assertIn("没有事实分册", " ".join(data["gaps"]), data["gaps"])


class ContainerLimitTest(MinimalLibrary):
    """600 token 容器兜底：按实际参与判定的那段文本、按同一个计数器。"""

    def setUp(self):
        super().setUp()
        self.make_minimal()

    def container_text(self, target: int) -> str:
        """构造一个 h1 容器节，子树文本的 heuristic 计数恰好等于 target。

        判据读的是 `lines[sec.start:sec.stop]` 连起来的那段（含标题），
        所以这里也用同一段文本去对齐，而不是拿字符数估。
        """
        # 子节只出现「刷机」一个词：够不上「≥2 个关键词」，只能靠父节兜底；
        # 父节标题「固件刷机恢复」才同时命中三个词。
        base = ("# 24 · 固件刷机恢复\n\n"
                "## 日志甲\n\n"
                "- 刷机记录：")
        body = base
        for _ in range(4000):
            p = self.write("24_庚.md", body + "\n")
            doc = md.parse_file(p)
            raw = "\n".join(doc.lines[doc.sections[0].start:doc.sections[0].stop])
            n = tokens.heuristic(raw)
            if n == target:
                return body
            body = body + "x" if n < target else body[:-1]
        raise AssertionError("没能把容器节调到 %d token" % target)

    def p4_titles(self, target: int):
        self.container_text(target)
        data, p = self.ctx("--loose", "--task", "固件刷机后怎么恢复", "--budget", "3000")
        self.assertEqual(p.returncode, 0, p.stderr)
        return data, [b["title"] for b in data["blocks"] if b["priority"] == "P4"]

    def test_599_tokens_falls_back(self):
        data, titles = self.p4_titles(599)
        self.assertIn("相关补充 · 24 · 固件刷机恢复", titles, titles)

    def test_600_tokens_still_falls_back(self):
        data, titles = self.p4_titles(600)
        self.assertIn("相关补充 · 24 · 固件刷机恢复", titles, titles)

    def test_601_tokens_is_not_forced_in(self):
        data, titles = self.p4_titles(601)
        self.assertNotIn("相关补充 · 24 · 固件刷机恢复", titles,
                         "超过 600 还靠小容器规则硬装，会挤掉别的结论：%s" % titles)

    def test_p4_caps_hold_at_the_boundary(self):
        for target in (599, 600):
            data, titles = self.p4_titles(target)
            self.assertLessEqual(len(titles), 3, titles)
            self.assertLessEqual(data["p4"]["tokens"], 3000 * 0.30, data["p4"])
            self.assertFalse(data["over_budget"], data["used"])

    def test_container_cutoff_uses_the_selected_counter(self):
        """阈值必须跟着 `TokenCounter` 走，不能固定用 heuristic。

        cl100k 与 heuristic 对同一段中文能差三成；两边各算一套单位时，
        「599 还是 601」就没有确定答案。
        """
        m = load_script("kb-context")
        self.container_text(10)
        # 与 CLI 同口径：`scope.resolve_root()` 返回的是真实路径。GitHub Windows
        # runner 的临时目录是 8.3 短名（RUNNER~1），不 resolve 会 `relative_to` 失败。
        root = Path(self.root).resolve()

        class Fixed:
            def __init__(self, n):
                self.n = n

            def count(self, text):
                return self.n

        rows600, _ = m.p4_candidates(root, ["刷机", "恢复"], set(), set(), False, True,
                                     counter=Fixed(600))
        rows601, _ = m.p4_candidates(root, ["刷机", "恢复"], set(), set(), False, True,
                                     counter=Fixed(601))
        self.assertTrue([r for r in rows600 if "24 ·" in (r["heading"] or "")], rows600)
        self.assertFalse([r for r in rows601 if "24 ·" in (r["heading"] or "")], rows601)


class DedupSafetyTest(MinimalLibrary):
    """内容去重只删「重复」，不能删掉约束、也不能合并不同事实。"""

    def test_p0_survives_when_another_line_repeats_it(self):
        """别的线把硬约束原句抄了一遍：P0 必须留，重复的那块被跳过并记账。"""
        self.make_minimal({
            "10_甲.md": "<!-- kb:schema: 2 -->\n# 10 · 甲\n\n"
                        "<!-- kb:id: fact.current -->\n## 0. 当前值\n\n"
                        + CONSTRAINT + "\n",
        })
        data, p = self.ctx("--loose", "--line", "甲", "--task", "甲 的约束是什么",
                           "--budget", "3000")
        self.assertEqual(p.returncode, 0, p.stderr)
        p0 = [b for b in data["blocks"] if b["priority"] == "P0"]
        self.assertEqual(len(p0), 1, [b["title"] for b in data["blocks"]])
        text = data["context"][p0[0]["section_id"] or p0[0]["title"]]
        self.assertIn("不擅自重启", text, "P0 被去重吃掉了：%s" % text)
        self.assertTrue(data["deduped"], "重复的那块要能被查到，不能静默")
        self.assertEqual(data["deduped"][0]["kept_in"]["section_id"],
                         "dashboard.constraints", data["deduped"])
        self.assertFalse([d for d in data["deduped"] if d["priority"] == "P0"],
                         "required 块永远不参与去重：%s" % data["deduped"])

    def test_near_identical_facts_are_not_merged(self):
        """只差一个数字的两条事实是两条事实，不能因为「看着像」合成一条。"""
        self.make_minimal({
            "10_甲.md": "<!-- kb:schema: 2 -->\n# 10 · 甲\n\n"
                        "<!-- kb:id: fact.current -->\n## 0. 当前值\n\n"
                        "WAN 当前使用 MTU 1480。\n",
            "11_乙.md": "<!-- kb:schema: 2 -->\n# 11 · 乙\n\n"
                        "<!-- kb:id: fact.current -->\n## 0. 当前值\n\n"
                        "WAN 当前使用 MTU 1492。\n",
        })
        data, p = self.ctx("--loose", "--line", "甲,乙", "--task", "对比两条线的 MTU",
                           "--budget", "3000")
        self.assertEqual(p.returncode, 0, p.stderr)
        texts = " ".join(data["context"].values())
        self.assertIn("1480", texts)
        self.assertIn("1492", texts, "两条数值不同的事实被合并了：%s" % texts)
        self.assertFalse(data["deduped"], data["deduped"])

    def test_same_name_in_two_dirs_is_not_treated_as_used(self):
        """子目录同名文件内容不同，两个都要能进来（去重键是相对路径）。"""
        self.make_minimal({
            "甲/40_丁.md": "# 40 · 丁\n\n## G-001 甲侧值\n\n"
                           "甲侧刷机恢复用 A 方案。\n",
            "乙/40_丁.md": "# 40 · 丁\n\n## G-001 乙侧值\n\n"
                           "乙侧刷机恢复用 B 方案。\n",
        })
        data, p = self.ctx("--loose", "--task", "刷机恢复用哪个方案", "--budget", "3000")
        self.assertEqual(p.returncode, 0, p.stderr)
        paths = {b["source_path"] for b in data["blocks"] if b["priority"] == "P4"}
        self.assertEqual(paths, {"甲/40_丁.md", "乙/40_丁.md"},
                         "同名不同路径被当成同一份了：%s" % paths)


class H1IntroDedupTest(MinimalLibrary):
    """P4 去冗余：h1 的独有事实不能被「关键词是子集」误删。"""

    # h1 正文有一句子节完全没有的事实；关键词上 h1 是 h2 的超集（3 ⊃ 2），
    # 旧判据会把 h1 删掉，连带「参数 YY 必须禁用」一起消失。
    INTRO = """# 当前 NSS 配置

参数 YY 必须禁用；NSS 服务保持运行。

## NSS 排障

NSS 禁用失败时检查服务。
"""

    # h1 正文与子节逐字重复：这是真导语，允许去重。
    DUP = """# 当前 NSS 配置

NSS 禁用失败时检查服务。

## NSS 排障

NSS 禁用失败时检查服务。
"""

    # 任务相关短句（2 个实义字符）：按「<4 一律忽略」会被当成空内容，
    # h1 连同「只读」这条操作约束一起消失。
    SHORT = """# 当前配置

只读。

## 操作说明

当前配置请先检查。
"""

    # 用户给的 4 字短句夹具：恰好压在旧阈值上，用来钉住边界不被改回去。
    SHORT4 = """# 当前配置

禁止写入。

## 操作说明

请先检查配置。
"""

    # 导语与约束混在同一句：整句因「适用版本」被跳过，后半句禁令一起丢。
    META_MIX = """# 当前配置

适用版本 2.0，生产环境禁止写入。

## 操作说明

生产环境请先检查配置。
"""

    # 纯导语：全部片段都是版本/更新时间，仍应正常去重。
    META_ONLY = """# 当前配置

适用版本 2.0，最后更新 2026-11-13。

## 当前配置检查

当前配置请先检查。
"""

    def run_ctx(self, shard, task="NSS 参数 禁用"):
        self.make_minimal({"20_NSS配置.md": shard})
        data, p = self.ctx("--loose", "--task", task, "--budget", "3000")
        self.assertEqual(p.returncode, 0, p.stderr)
        return data

    def test_h1_with_unique_fact_survives_subsection(self):
        data = self.run_ctx(self.INTRO)
        joined = "\n".join(data["context"].values())
        self.assertIn("参数 YY 必须禁用", joined,
                      "h1 的独有事实被子节关键词覆盖误删：%s" % joined)
        self.assertIn("NSS 禁用失败时检查服务", joined,
                      "子节本身也要在：%s" % joined)
        p4 = [b for b in data["blocks"] if b["priority"] == "P4"]
        self.assertLessEqual(len(p4), 3, "P4 最多三块的上限不能被去重逻辑带跑")

    def test_h1_repeating_subsection_is_dropped(self):
        data = self.run_ctx(self.DUP)
        p4 = [b for b in data["blocks"] if b["priority"] == "P4"]
        titles = [b["title"] for b in p4]
        self.assertEqual(len(titles), 1, "h1 正文已被子节完全覆盖，应当去重：%s" % titles)
        self.assertIn("NSS 排障", titles[0], titles)
        self.assertEqual("\n".join(data["context"].values()).count("NSS 禁用失败时检查服务"),
                         1, "同一句话不该出现两遍")

    def test_short_task_constraint_survives_subsection(self):
        data = self.run_ctx(self.SHORT, task="当前配置 只读")
        joined = "\n".join(data["context"].values())
        self.assertIn("只读", joined,
                      "任务相关的短句被长度阈值吞掉，操作约束整条消失：%s" % joined)
        p4 = [b for b in data["blocks"] if b["priority"] == "P4"]
        self.assertLessEqual(len(p4), 3, "P4 最多三块的上限不变")

    def test_four_char_short_sentence_boundary(self):
        data = self.run_ctx(self.SHORT4, task="当前配置 禁止写入")
        joined = "\n".join(data["context"].values())
        self.assertIn("禁止写入", joined, "4 字短句也必须保留：%s" % joined)

    def test_meta_prefixed_sentence_keeps_constraint(self):
        data = self.run_ctx(self.META_MIX, task="生产环境 禁止写入")
        joined = "\n".join(data["context"].values())
        self.assertIn("生产环境禁止写入", joined,
                      "含「适用版本」的句子不能整句跳过，后半句是操作禁令：%s" % joined)
        # 导语片段只是在「是否重复」的判断里不算独有内容；整节输出仍不缩水，
        # 所以这里不断言 text 被裁剪，只钉住去重判据。
        p4 = [b for b in data["blocks"] if b["priority"] == "P4"]
        self.assertLessEqual(len(p4), 3, "P4 最多三块的上限不变")

    def test_pure_version_note_still_deduped(self):
        data = self.run_ctx(self.META_ONLY, task="当前配置")
        p4 = [b for b in data["blocks"] if b["priority"] == "P4"]
        titles = [b["title"] for b in p4]
        self.assertEqual(len(titles), 1,
                         "h1 只有版本/更新时间这类导语，仍应去重：%s" % titles)
        self.assertIn("当前配置检查", titles[0], titles)
        self.assertNotIn("最后更新", "\n".join(data["context"].values()))


if __name__ == "__main__":
    unittest.main()
