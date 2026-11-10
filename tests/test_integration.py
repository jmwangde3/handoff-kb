#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-migrate / kb-hooks / kb-handoff / kb-outline / kb-benchmark 的集成行为。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import TempProject, run, run_json  # noqa: E402


class MigrateTest(TempProject):
    def test_migrate_adds_ids_and_is_idempotent(self):
        self.make_v1()
        p = run("kb-migrate.py", "--target", self.root, "--plan")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((self.root / ".kb-migrate-plan.json").is_file())
        p = run("kb-migrate.py", "--target", self.root, "--apply")
        self.assertEqual(p.returncode, 0, p.stderr)
        text = self.read("05_进度仪表盘.md")
        self.assertIn("<!-- kb:schema: 2 -->", text)
        self.assertIn("kb:id: dashboard.current", text)
        self.assertTrue(self.read("00_基线.md").startswith("<!-- kb:schema: 2 -->"))
        p = run("kb-migrate.py", "--target", self.root, "--plan")
        self.assertIn("无需迁移", p.stdout)

    def test_stale_plan_refused(self):
        self.make_v1()
        run("kb-migrate.py", "--target", self.root, "--plan")
        self.write("05_进度仪表盘.md", self.read("05_进度仪表盘.md") + "\n新增一行\n")
        p = run("kb-migrate.py", "--target", self.root, "--apply")
        self.assertEqual(p.returncode, 1)
        self.assertIn("过期", p.stderr)

    def test_legacy_fact_file_untouched(self):
        self.make_v1()
        before = self.read("01_固件.md")
        run("kb-migrate.py", "--target", self.root, "--plan")
        run("kb-migrate.py", "--target", self.root, "--apply")
        self.assertEqual(before, self.read("01_固件.md"))


class HooksTest(TempProject):
    def setUp(self):
        super().setUp()
        self.make_filled()

    def test_plan_writes_nothing(self):
        p = run("kb-hooks.py", "install", "--client", "claude",
                "--target", self.root, "--plan")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse((self.root / ".claude").exists())

    def test_install_and_uninstall(self):
        p = run("kb-hooks.py", "install", "--client", "claude",
                "--target", self.root, "--write")
        self.assertEqual(p.returncode, 0, p.stderr)
        settings = json.loads(self.read(".claude/settings.json"))
        self.assertIn("SessionStart", settings["hooks"])
        self.assertIn("kb-hooks.py", json.dumps(settings, ensure_ascii=False))

        # 再装一次应该幂等
        run("kb-hooks.py", "install", "--client", "claude",
            "--target", self.root, "--write")
        settings = json.loads(self.read(".claude/settings.json"))
        self.assertEqual(len(settings["hooks"]["SessionStart"]), 1)

        # 混入外部 hook，卸载只删自己的
        settings["hooks"]["SessionStart"].append({"hooks": [{"type": "command",
                                                             "command": "echo other"}]})
        self.write(".claude/settings.json", json.dumps(settings, ensure_ascii=False))
        p = run("kb-hooks.py", "uninstall", "--client", "claude",
                "--target", self.root, "--write")
        self.assertEqual(p.returncode, 0, p.stderr)
        after = json.loads(self.read(".claude/settings.json"))
        self.assertEqual(len(after["hooks"]["SessionStart"]), 1)
        self.assertIn("echo other", json.dumps(after, ensure_ascii=False))

    def test_codex_writes_descriptor_and_snippet(self):
        p = run("kb-hooks.py", "install", "--client", "codex",
                "--target", self.root, "--write")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((self.root / ".codex" / "hooks.json").is_file())
        self.assertIn("[[hooks.SessionStart]]",
                      self.read(".codex/hooks.snippet.toml.txt"))

    def test_run_is_safe_and_exit_zero(self):
        for ev in ("SessionStart", "PreCompact", "PostCompact", "Stop", "SessionEnd"):
            p = run("kb-hooks.py", "run", "--client", "claude",
                    "--event", ev, "--target", self.root)
            self.assertEqual(p.returncode, 0, "%s 退出码非 0: %s" % (ev, p.stderr))

    def test_run_on_broken_target_still_zero(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        p = run("kb-hooks.py", "run", "--client", "codex",
                "--event", "SessionStart", "--target", empty)
        self.assertEqual(p.returncode, 0)


class HandoffTest(TempProject):
    def test_empty_template_pending_not_done(self):
        self.init()
        data, p = run_json("kb-handoff.py", "check", "--target", self.root, "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        status = {i["key"]: i["status"] for i in data["items"]}
        self.assertEqual(status["current"], "pending")
        p = run("kb-handoff.py", "check", "--target", self.root, "--strict")
        self.assertEqual(p.returncode, 1)

    def test_filled_handoff_passes(self):
        self.make_filled()
        data, p = run_json("kb-handoff.py", "check", "--target", self.root,
                           "--strict", "--json")
        self.assertIsNotNone(data, "stderr=%r" % p.stderr[:600])
        self.assertTrue(data["pass"], data)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_missing_dashboard(self):
        empty = self.tmp / "e"
        empty.mkdir()
        p = run("kb-handoff.py", "check", "--target", empty, "--json")
        self.assertEqual(p.returncode, 1)


class OutlineTest(TempProject):
    def test_section_id_and_hash(self):
        self.make_filled()
        p = run("kb-outline.py", "--file", self.root / "05_进度仪表盘.md")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("dashboard.current", p.stdout)
        self.assertIn("source-hash:", p.stdout)
        short = [l for l in p.stdout.splitlines() if l.startswith("source-hash:")][0]
        h = short.split("source-hash:")[1].split("|")[0].strip()
        p2 = run("kb-outline.py", "--file", self.root / "05_进度仪表盘.md",
                 "--section-id", "dashboard.next", "--hash", h)
        self.assertEqual(p2.returncode, 0, p2.stderr)
        self.assertIn("下一手", p2.stdout)
        p3 = run("kb-outline.py", "--file", self.root / "05_进度仪表盘.md",
                 "--section-id", "dashboard.next", "--hash", "deadbeef1234")
        self.assertEqual(p3.returncode, 2)

    def test_unknown_section(self):
        self.make_filled()
        p = run("kb-outline.py", "--file", self.root / "05_进度仪表盘.md",
                "--section-id", "nope.nope")
        self.assertEqual(p.returncode, 1)


class BenchmarkTest(TempProject):
    def test_benchmark_runs_and_reports(self):
        self.make_filled()
        data, p = run_json("kb-benchmark.py", "--target", self.root,
                           "--report", "json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(data["quality"]["total"], 10)
        self.assertGreaterEqual(data["quality"]["passed"], 8)
        self.assertIn("A_all", data["tokens"])
        self.assertLess(data["tokens"]["C_mean"], data["tokens"]["A_all"])


if __name__ == "__main__":
    unittest.main()
