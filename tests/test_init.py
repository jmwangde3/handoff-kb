#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-init.py：编号、预检查、幂等、git 白名单、凭证阻断。"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import TempProject, no_identity_env, run  # noqa: E402


class InitTest(TempProject):
    def test_one_line_uses_10(self):
        p = self.init(lines="甲")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((self.root / "10_甲.md").is_file())
        self.assertFalse((self.root / "01_甲.md").exists())

    def test_eight_lines_no_conflict(self):
        names = "甲,乙,丙,丁,戊,己,庚,辛"
        p = self.init(lines=names)
        self.assertEqual(p.returncode, 0, p.stderr)
        for n in range(10, 18):
            self.assertTrue(list(self.root.glob("%d_*.md" % n)), "缺少 %d 号分册" % n)
        # 保留层不被占用
        self.assertFalse(list(self.root.glob("1[0-7]_进度*.md")))

    def test_nine_lines_rejected(self):
        p = self.init(lines="a,b,c,d,e,f,g,h,i")
        self.assertEqual(p.returncode, 2)
        self.assertIn("最多 8", p.stderr)

    def test_duplicate_after_casefold(self):
        p = self.init(lines="abc,ABC")
        self.assertEqual(p.returncode, 2)
        self.assertIn("重复", p.stderr)

    def test_reserved_name_other(self):
        p = self.init(lines="其他")
        self.assertEqual(p.returncode, 2)

    def test_illegal_chars_sanitized(self):
        p = self.init(lines="a/b")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((self.root / "10_a_b.md").is_file())

    def test_plan_does_not_touch_disk(self):
        p = run("kb-init.py", "--target", self.root, "--plan", "--no-git")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(self.root.exists())
        self.assertIn("将创建", p.stdout)

    def test_idempotent(self):
        self.init(lines="甲,乙")
        before = self.read("05_进度仪表盘.md")
        p = self.init(lines="甲,乙")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("生成 0 个文件", p.stdout)
        self.assertEqual(before, self.read("05_进度仪表盘.md"))

    def test_force_keeps_protected_config(self):
        self.init(lines="甲")
        self.write(".gitignore", "我的自定义规则\n")
        p = self.init("--force", lines="甲")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.read(".gitignore"), "我的自定义规则\n")
        p = self.init("--force", "--overwrite-config", lines="甲")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("kb.lock", self.read(".gitignore"))

    def test_git_init_stages_whitelist_only(self):
        p = self.init(lines="甲,乙", git=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((self.root / ".git").is_dir())
        log = subprocess.run(["git", "log", "--oneline"], cwd=self.root,
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(len([x for x in log.stdout.splitlines() if x.strip()]), 1)
        st = subprocess.run(["git", "status", "--porcelain"], cwd=self.root,
                            capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(st.stdout.strip(), "")

    def test_git_never_invents_identity(self):
        """没有本机身份时：不代填 handoff-kb@localhost，也不把初始化判失败。"""
        env = no_identity_env(self.tmp)
        p = self.init(lines="甲", git=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("身份", p.stdout)
        for key in ("user.name", "user.email"):
            got = subprocess.run(["git", "config", key], cwd=self.root,
                                 capture_output=True, text=True, encoding="utf-8",
                                 env={**os.environ, **env})
            self.assertEqual(got.stdout.strip(), "", "不得写入虚构身份：%s" % key)
        st = subprocess.run(["git", "status", "--porcelain"], cwd=self.root,
                            capture_output=True, text=True, encoding="utf-8")
        self.assertTrue(st.stdout.strip(), "文件应已暂存，等用户配置身份后再提交")

    def test_nested_git_refused(self):
        parent = self.tmp / "outer"
        parent.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=parent, capture_output=True)
        self.root = parent / "inner"
        p = self.init(lines="甲", git=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse((self.root / ".git").exists())
        self.assertIn("父目录", p.stdout)

    def test_secret_blocks_write(self):
        self.root.mkdir(parents=True)
        self.write("00_基线.md", "| K-01 | key | LTAIabcdefgh1234 | 有效 |\n")
        p = self.init(lines="甲")
        self.assertEqual(p.returncode, 1)
        self.assertIn("敏感信息", p.stderr)

    def test_existing_repo_not_committed(self):
        self.root.mkdir(parents=True)
        subprocess.run(["git", "init", "-b", "main"], cwd=self.root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@local"], cwd=self.root)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.root)
        self.write("keep.txt", "x")
        subprocess.run(["git", "add", "-A"], cwd=self.root)
        subprocess.run(["git", "commit", "-m", "base"], cwd=self.root, capture_output=True)
        p = self.init(lines="甲")
        self.assertEqual(p.returncode, 0, p.stderr)
        log = subprocess.run(["git", "log", "--oneline"], cwd=self.root,
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(len([x for x in log.stdout.splitlines() if x.strip()]), 1)


if __name__ == "__main__":
    unittest.main()
