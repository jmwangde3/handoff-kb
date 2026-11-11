#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-hooks：预览零写入、官方事件结构、合并/卸载幂等、运行时不挂起、永远退出 0。"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SCRIPTS, TempProject, run  # noqa: E402

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


def load_hooks_module():
    """kb-hooks.py 带连字符，不能 import —— 按文件路径加载，才能测函数级竞态。"""
    path = SCRIPTS / "kb-hooks.py"
    spec = importlib.util.spec_from_file_location("kb_hooks_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ns(**kw):
    return argparse.Namespace(**kw)


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


class HookLifecycleTest(TempProject):
    """安装/卸载的竞态与多文件安全 —— 函数级测试，能精确制造「预览之后被改」。"""

    def setUp(self):
        super().setUp()
        self.make_filled()
        self.mod = load_hooks_module()

    def _plan(self, action="install", client="claude"):
        args = ns(client=client, target=str(self.root), loose=False, python=None,
                  plan=True, write=True)
        fn = self.mod.plan_install if action == "install" else self.mod.plan_uninstall
        return fn(args, self.root)

    def _apply(self, rows):
        out, err = io.StringIO(), io.StringIO()
        from contextlib import redirect_stderr
        with redirect_stdout(out), redirect_stderr(err):
            code = self.mod.apply_rows(self.root, rows, "install")
        return code, out.getvalue() + err.getvalue()

    def test_session_start_covers_all_official_sources(self):
        """两家官方文档的 SessionStart 来源都是这五个：漏一个就少一次接手机会。"""
        want = ("startup", "resume", "clear", "compact", "fork")
        for client in ("codex", "claude"):
            payload = self.mod.build_payload(client, self.root, False, None)
            matcher = payload["hooks"]["SessionStart"][0]["matcher"]
            for token in want:
                self.assertIn(token, matcher, "%s 的 SessionStart 缺 %s" % (client, token))

    def test_file_created_after_preview_is_not_clobbered(self):
        rows = self._plan()
        target = self.root / ".claude" / "settings.json"
        self.assertFalse(rows[0]["original_exists"])
        target.parent.mkdir()
        target.write_text('{"mine": true}\n', encoding="utf-8")
        code, out = self._apply(rows)
        self.assertEqual(code, 2, out)
        self.assertEqual(target.read_text(encoding="utf-8"), '{"mine": true}\n',
                         "预览后新建的用户文件不得被覆盖")

    def test_file_changed_after_preview_is_not_clobbered(self):
        target = self.root / ".claude" / "settings.json"
        target.parent.mkdir()
        target.write_text('{"hooks": {}}\n', encoding="utf-8")
        rows = self._plan()
        target.write_text('{"hooks": {}, "edited": 1}\n', encoding="utf-8")
        code, out = self._apply(rows)
        self.assertEqual(code, 2, out)
        self.assertIn("预览后被改动", out)
        self.assertEqual(target.read_text(encoding="utf-8"), '{"hooks": {}, "edited": 1}\n')

    def test_multi_file_failure_rolls_back(self):
        """codex 装两个文件：第二个写失败时，第一个必须回滚掉。"""
        rows = self._plan(client="codex")
        self.assertEqual(len(rows), 2)
        real = self.mod.atomic_write

        def boom(path, text):
            if str(path).endswith(".toml.txt"):
                raise OSError("磁盘满了（模拟）")
            return real(path, text)

        err = io.StringIO()
        buf = io.StringIO()
        with mock.patch.object(self.mod, "atomic_write", boom), redirect_stdout(buf):
            from contextlib import redirect_stderr
            with redirect_stderr(err):
                code = self.mod.apply_rows(self.root, rows, "install")
        self.assertEqual(code, 2, buf.getvalue())
        self.assertIn("已回滚", err.getvalue())
        self.assertFalse((self.root / ".codex" / "hooks.json").exists(),
                         "第一个文件本来不存在，回滚后必须仍不存在")

    def test_dir_symlink_outside_is_refused(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        if os.name == "nt":
            r = subprocess.run(["cmd", "/c", "mklink", "/J",
                                str(self.root / ".codex"), str(outside)],
                               capture_output=True)
            if r.returncode != 0:
                self.skipTest("本机无法创建目录链接：%s"
                              % (r.stdout + r.stderr).decode("utf-8", "replace").strip())
        else:
            os.symlink(str(outside), str(self.root / ".codex"), target_is_directory=True)
        p = run("kb-hooks.py", "install", "--client", "codex", "--target", self.root,
                "--write")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("目录不可用", p.stderr)
        self.assertEqual(list(outside.iterdir()), [], "库外目录里一个文件都不能写")

    def test_uninstall_is_idempotent_without_files(self):
        p = run("kb-hooks.py", "uninstall", "--client", "codex", "--target", self.root,
                "--write")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse((self.root / ".codex").exists())

    def test_uninstall_refuses_when_json_edited_after_preview(self):
        run("kb-hooks.py", "install", "--client", "claude", "--target", self.root, "--write")
        rows = self._plan("uninstall")
        target = self.root / ".claude" / "settings.json"
        target.write_text(json.dumps({"hooks": {}, "edited": 1}), encoding="utf-8")
        code, out = self._apply(rows)
        self.assertEqual(code, 2, out)
        self.assertIn("预览后被改动", out)
        self.assertIn("edited", target.read_text(encoding="utf-8"),
                      "拒绝写入时不得改动用户文件")


if __name__ == "__main__":
    unittest.main()
