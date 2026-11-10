#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 解析与章节定位：围栏、重复标题、稳定 ID、CRLF、边界。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib import markdown as md  # noqa: E402


class ParseTest(unittest.TestCase):
    def test_fenced_headings_ignored(self):
        text = ("# T\n\n```bash\n# 不是标题\n```\n\n"
                "~~~~\n## 也不是\n~~~~\n\n## 真标题\n\n正文\n")
        doc = md.parse(text)
        titles = [s.title for s in doc.sections]
        self.assertEqual(titles, ["T", "真标题"])

    def test_long_fence_and_closing_length(self):
        text = "````\n# fake\n```\n## still fake\n````\n## real\n"
        doc = md.parse(text)
        self.assertEqual([s.title for s in doc.sections], ["real"])

    def test_duplicate_titles_raise(self):
        doc = md.parse("## 同名\n\na\n\n## 同名\n\nb\n")
        with self.assertRaises(md.MarkdownError):
            md.find(doc, "同名")
        self.assertIsNotNone(md.find(doc, 1))

    def test_stable_id_binding(self):
        text = "<!-- kb:id: dashboard.current -->\n## 0. 现状\n\n正文\n\n## 1. 其它\n"
        doc = md.parse(text)
        self.assertEqual(doc.sections[0].id, "dashboard.current")
        self.assertIsNone(doc.sections[1].id)
        self.assertIsNotNone(md.find_by_id(doc, "dashboard.current"))

    def test_id_not_attached_after_content(self):
        doc = md.parse("## A\n\n文字\n\n<!-- kb:id: x.y -->\n\n## B\n")
        self.assertIsNone(doc.sections[0].id)
        self.assertEqual(doc.sections[1].id, "x.y")

    def test_section_id_inside_fence_ignored(self):
        doc = md.parse("## A\n\n```\n<!-- kb:id: nope -->\n```\n")
        self.assertIsNone(doc.sections[0].id)

    def test_body_does_not_include_next_id_comment(self):
        text = "## A\n\n正文\n\n<!-- kb:id: b -->\n## B\n\n正文2\n"
        doc = md.parse(text)
        body, _ = md.render(doc, doc.sections[0], include_children=False)
        self.assertNotIn("kb:id", body)

    def test_no_children(self):
        text = "## A\n\na\n\n### A1\n\nsub\n\n## B\n"
        doc = md.parse(text)
        full, _ = md.render(doc, doc.sections[0], include_children=True)
        only, _ = md.render(doc, doc.sections[0], include_children=False)
        self.assertIn("sub", full)
        self.assertNotIn("sub", only)

    def test_crlf_and_no_trailing_newline(self):
        doc = md.parse("## A\r\n\r\n正文\r\n\r\n## B\r\n\r\n尾巴")
        self.assertEqual([s.title for s in doc.sections], ["A", "B"])
        self.assertEqual(doc.sections[1].title, "B")

    def test_closing_hashes_stripped(self):
        doc = md.parse("## 标题 ##\n")
        self.assertEqual(doc.sections[0].title, "标题")

    def test_offset_and_max_lines(self):
        text = "## A\n" + "\n".join("行%d" % i for i in range(10)) + "\n"
        doc = md.parse(text)
        sec = doc.sections[0]
        out, meta = md.render(doc, sec, max_lines=3, offset=2)
        self.assertEqual(meta["lines"], 3)
        self.assertTrue(meta["truncated"])
        self.assertEqual(out.splitlines()[0], "行2")
        with self.assertRaises(md.MarkdownError):
            md.render(doc, sec, offset=-1)

    def test_duplicate_ids_detected(self):
        doc = md.parse("<!-- kb:id: a -->\n## A\n\n<!-- kb:id: a -->\n## B\n")
        self.assertEqual(doc.duplicate_ids, ["a"])

    def test_parse_file_hashes(self):
        import tempfile
        p = Path(tempfile.mkdtemp()) / "x.md"
        p.write_text("## A\n", encoding="utf-8")
        doc = md.parse_file(p)
        self.assertEqual(len(doc.sha256_file), 64)
        self.assertEqual(len(doc.short_hash), 12)


if __name__ == "__main__":
    unittest.main()
