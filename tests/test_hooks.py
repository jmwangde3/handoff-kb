#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-hooks：预览零写入、官方事件结构、合并/卸载幂等、运行时不挂起、永远退出 0。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import TempProject, run  # noqa: E402

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


class HookPlanTest(TempProject):
    def setUp(self):
        super().setUp()
        self.make_filled()

    def test_plan_writes_nothing(self):
        p = run("kb-hooks.py", "install", "--client", "codex", "--target", self.root)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("未改动磁盘", p.stdout)
        self.assertFalse((self.root / ".codex").exists())

    def test_plan_reports_sha_and_events(self):
        p = run("kb-hooks.py", "install", "--client", "claude", "--target", self.root)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("新增事件：", p.stdout)
        self.assertIn("SessionStart", p.stdout)
        self.assertIn("SHA-256：- →", p.stdout)

    def test_write_creates_three_level_structure(self):
        p = run("kb-hooks.py", "install", "--client", "codex", "--target", self.root,
                "--write")
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads((self.root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        hooks = data["hooks"]
        self.assertIn("SessionStart", hooks)
        first = hooks["SessionStart"][0]
        self.assertIn("matcher", first)
        self.assertIsInstance(first["hooks"], list)
        self.assertEqual(first["hooks"][0]["type"], "command")
        self.assertIn("kb-hooks.py", first["hooks"][0]["command"])

    def test_write_creates_valid_toml_snippet(self):
        p = run("kb-hooks.py", "install", "--client", "codex", "--target", self.root,
                "--write")
        self.assertEqual(p.returncode, 0, p.stderr)
        text = (self.root / ".codex" / "hooks.snippet.toml.txt").read_text(encoding="utf-8")
        if tomllib:
            data = tomllib.loads(text)
            self.assertIn("hooks", data)
        self.assertIn("[[hooks.", text)

    def test_write_is_idempotent(self):
        run("kb-hooks.py", "install", "--client", "codex", "--target", self.root, "--write")
        first = (self.root / ".codex" / "hooks.json").read_text(encoding="utf-8")
        p = run("kb-hooks.py", "install", "--client", "codex", "--target", self.root,
                "--write")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("无需改动", p.stdout)
        self.assertEqual((self.root / ".codex" / "hooks.json").read_text(encoding="utf-8"),
                         first)
        self.assertEqual(first.count("kb-hooks.py"), 3, "三个事件各一条，不可重复添加")

    def test_install_keeps_foreign_hooks(self):
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "settings.json").write_text(json.dumps({
            "model": "x",
            "hooks": {"Stop": [{"matcher": "", "hooks": [
                {"type": "command", "command": "echo other"}]}]},
        }), encoding="utf-8")
        p = run("kb-hooks.py", "install", "--client", "claude", "--target", self.root,
                "--write")
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads((self.root / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(data["model"], "x")
        cmds = json.dumps(data)
        self.assertIn("echo other", cmds)
        self.assertIn("kb-hooks.py", cmds)

    def test_uninstall_removes_only_ours(self):
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {"Stop": [{"matcher": "", "hooks": [
                {"type": "command", "command": "echo other"}]}]},
        }), encoding="utf-8")
        run("kb-hooks.py", "install", "--client", "claude", "--target", self.root, "--write")
        p = run("kb-hooks.py", "uninstall", "--client", "claude", "--target", self.root,
                "--write")
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads((self.root / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertIn("echo other", json.dumps(data))
        self.assertNotIn("kb-hooks.py", json.dumps(data))

    def test_bad_existing_json_is_refused_not_clobbered(self):
        (self.root / ".claude").mkdir()
        bad = '{"hooks": { 这是坏 JSON'
        (self.root / ".claude" / "settings.json").write_text(bad, encoding="utf-8")
        p = run("kb-hooks.py", "install", "--client", "claude", "--target", self.root,
                "--write")
        self.assertEqual(p.returncode, 2)
        self.assertIn("不是合法 JSON", p.stdout + p.stderr)
        self.assertEqual((self.root / ".claude" / "settings.json").read_text(encoding="utf-8"),
                         bad)

    def test_loose_flag_reaches_generated_command(self):
        p = run("kb-hooks.py", "install", "--client", "codex", "--target", self.root,
                "--write", "--loose")
        self.assertEqual(p.returncode, 0, p.stderr)
        text = (self.root / ".codex" / "hooks.json").read_text(encoding="utf-8")
        self.assertIn("--loose", text)


class HookRunTest(TempProject):
    def setUp(self):
        super().setUp()
        self.make_filled()

    def test_session_start_emits_additional_context(self):
        p = run("kb-hooks.py", "run", "--client", "codex", "--event", "SessionStart",
                "--target", self.root, input="{}")
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        out = data["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        self.assertIn("上下文包", out["additionalContext"])
        self.assertNotIn("decision", json.dumps(data))

    def test_precompact_uses_system_message(self):
        p = run("kb-hooks.py", "run", "--client", "claude", "--event", "PreCompact",
                "--target", self.root, input="{}")
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        self.assertIn("systemMessage", data)
        self.assertNotIn("decision", data)

    def test_unknown_event_exits_zero_with_empty_object(self):
        p = run("kb-hooks.py", "run", "--client", "codex", "--event", "NoSuchEvent",
                "--target", self.root, input="{}")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout), {})

    def test_no_stdin_does_not_hang(self):
        p = run("kb-hooks.py", "run", "--client", "codex", "--event", "Stop",
                "--target", self.root, input="", timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_cwd_outside_installed_root_skips_injection(self):
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        p = run("kb-hooks.py", "run", "--client", "codex", "--event", "SessionStart",
                "--target", self.root, input=json.dumps({"cwd": str(outside)}))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), "")

    def test_non_library_target_exits_zero(self):
        other = self.tmp / "plain"
        other.mkdir()
        p = run("kb-hooks.py", "run", "--client", "codex", "--event", "SessionStart",
                "--target", other, input="{}")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), "")


class HookTomlStripTest(TempProject):
    """TOML 卸载：只删自己的块，别把别人的表头留下空壳。"""

    def setUp(self):
        super().setUp()
        self.make_filled()

    def test_uninstall_toml_leaves_no_empty_header(self):
        run("kb-hooks.py", "install", "--client", "codex", "--target", self.root, "--write")
        p = run("kb-hooks.py", "uninstall", "--client", "codex", "--target", self.root,
                "--write")
        self.assertEqual(p.returncode, 0, p.stderr)
        path = self.root / ".codex" / "hooks.snippet.toml.txt"
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        self.assertNotIn("kb-hooks.py", text)
        self.assertNotIn("[[hooks.", text)


if __name__ == "__main__":
    unittest.main()
