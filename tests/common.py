#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试共用工具：临时工作区、CLI 调用、夹具。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def git_identity_env(name="Handoff Test", email="test@example.invalid"):
    """给 git 子进程一个确定的身份，不依赖也不修改本机全局配置。"""
    return {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
            "GIT_CONFIG_NOSYSTEM": "1"}


def no_identity_env(tmp: Path):
    """刻意制造「本机没有提交身份」的环境，用于验证不代填虚构身份。"""
    env = dict(git_identity_env())
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
              "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        env.pop(k, None)
    empty = Path(tmp) / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    env["GIT_CONFIG_GLOBAL"] = str(empty)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def run(script, *args, cwd=None, env=None, input=None, timeout=None):
    """用当前解释器跑脚本，返回 CompletedProcess。"""
    e = dict(os.environ)
    e.setdefault("PYTHONIOENCODING", "utf-8")
    if env:
        e.update(env)
    return subprocess.run([sys.executable, str(SCRIPTS / script)] + [str(a) for a in args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(cwd) if cwd else None, env=e,
                          input=input, timeout=timeout)


def run_json(script, *args, cwd=None, env=None):
    p = run(script, *args, cwd=cwd, env=env)
    try:
        return json.loads(p.stdout), p
    except Exception:
        return None, p


class TempProject(unittest.TestCase):
    """每个测试一个临时项目目录，测试结束清理。"""

    lines = "甲,乙"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kbtest-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "proj"

    def init(self, *extra, lines=None, git=False, env=None):
        args = ["--target", self.root, "--project", "Demo",
                "--lines", lines or self.lines]
        if not git:
            args.append("--no-git")
        elif env is None:
            # kb-init 不再代填虚构身份；测试自己提供，避免依赖本机 git 配置
            env = git_identity_env()
        p = run("kb-init.py", *args, *extra, env=env)
        return p

    def write(self, rel, text, newline="\n"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline=newline) as f:
            f.write(text)
        return p

    def read(self, rel):
        return (self.root / rel).read_text(encoding="utf-8")

    def sha(self, rel):
        import hashlib
        return hashlib.sha256((self.root / rel).read_bytes()).hexdigest()

    def make_v1(self):
        """一个 v1（无 schema / 无 kb:id）的小库。"""
        self.write("00_基线.md", "# 00 基线\n\n## 1. 当前基线\n\n"
                   "| ID | 项 | 当前值 | 状态 | 归属 | 核实方式 |\n"
                   "|---|---|---|---|---|---|\n"
                   "| K-01 | 版本 | 21.02 | 有效 | 固件 | `cat version` |\n\n"
                   "## 2. 策略速览\n\n- 先备份\n\n## 3. 交叉链\n\n"
                   "| 动作 | 波及 | 改前必读 |\n|---|---|---|\n| 刷机 | 无线 | 00 §1 |\n")
        self.write("05_进度仪表盘.md", "# 05 进度仪表盘\n\n## 0. 现状\n\n固件已上线。\n\n"
                   "## 1. 各线状态\n\n| 线 | 状态 |\n|---|---|\n| 固件 | 稳定 |\n\n"
                   "## 2. 待办\n\n| 类型 | 事项 |\n|---|---|\n| 进行中 | 等测速 |\n")
        self.write("06_会话日志.md", "# 06\n\n- 2026-11-01 初始化\n")
        self.write("90_过程档案.md", "# 90\n\n## §A 背景\n\n（无）\n")
        self.write("01_固件.md", "# 01 固件\n\n## 1. 当前值\n\n| 项 | 值 |\n|---|---|\n| 版本 | 21.02 |\n")

    def make_filled(self):
        """v2 + 已填写事实（用于 context / benchmark）。"""
        self.init()
        self.write("00_基线.md", """<!-- kb:schema: 2 -->
# 00 · 基线 — Demo

<!-- kb:id: baseline.facts -->
## 0. 基线（K-xx）

| ID | 项 | 当前值 | 状态 | 证据 | 核实时间 |
|---|---|---|---|---|---|
| K-01 | 固件版本 | 21.02.3 | 有效 | `cat /etc/version` | 2026-11-10 |
| K-02 | 信道 | 149 | 待核 | — | — |
| K-03 | 旧 DNS | 192.0.2.1 | 已作废 → K-04 | 改用 DoH | 2026-10-01 |
| K-04 | 新 DNS | 1.1.1.1 | 有效 | `dig @1.1.1.1` | 2026-11-09 |

<!-- kb:id: baseline.chains -->
## 2. 交叉链

| 改这里 | 同时要动 | 判据 |
|---|---|---|
| 固件升级 | 运行态重启脚本 | 自检全绿 |
""")
        self.write("05_进度仪表盘.md", """<!-- kb:schema: 2 -->
# 05 · 进度仪表盘 — Demo

<!-- kb:id: dashboard.current -->
## 0. 现状

固件 21.02.3 稳定运行 3 天；测速未完成。

<!-- kb:id: dashboard.next -->
## 1. 下一手

- `ssh r1 'iwinfo'` 采集信号。

<!-- kb:id: dashboard.lines -->
## 2. 各线状态

| 线 | 状态 | 一句话 |
|---|---|---|
| 固件 | 稳定 | 21.02.3 |
| 运行态 | 观察 | 无重启 |

<!-- kb:id: dashboard.todo -->
## 3. 待办

| 类型 | 事项 | 归属 | 证据 / 备注 |
|---|---|---|---|
| 进行中 | 采集信号 | 测速 | 等 iwinfo |
| 阻塞 | 无 | - | 无阻塞 |

<!-- kb:id: dashboard.constraints -->
## 7. 硬约束

- 不擅自重启 r1；凭证不入库。

<!-- kb:id: dashboard.summary -->
## 8. 最近 5 条

- [2026-11-10 22:00] 固件 刷机完成 → 采信号
""")
        self.write("10_甲.md", """<!-- kb:schema: 2 -->
# 10 · 甲 — 事实分册

<!-- kb:id: fact.current -->
## 1. 当前值

| 项 | 值 | 状态 | 证据 |
|---|---|---|---|
| 版本 | 21.02.3 | 有效 | `cat /etc/version` |

<!-- kb:id: fact.commands -->
## 2. 判据与命令

```bash
ssh r1 'cat /etc/version'
```

<!-- kb:id: fact.pitfalls -->
## 3. 踩过的坑

- 升级后 NSS 掉速 → 重载 qca-nss-ecm。
""")
        self.write("06_流水/甲.md", """# 06 · 流水分片 — 甲

<!-- kb:id: shard.log -->
## 流水

- [2026-11-10 22:00] 甲 刷机完成，`cat /etc/version` 已核 → 采信号
""")


def write_txn(root, name, entries, state="prepared", schema=2):
    """在 root/.kb-txn/<name> 写一个 v2 journal（带 checksum 与真实备份）。

    entries: [{"path","sha_before","sha_after","op","backup_bytes"}]
    schema=1 用于构造「旧/不支持 schema」的损坏现场。
    """
    import json
    import os
    import time
    sys.path.insert(0, str(SCRIPTS))
    from lib import safeio

    d = Path(root) / ".kb-txn" / name
    (d / "backup").mkdir(parents=True, exist_ok=True)
    jentries = []
    for e in entries:
        bp = d / "backup" / e["path"]
        bp.parent.mkdir(parents=True, exist_ok=True)
        bp.write_bytes(e.get("backup_bytes", b"OLD\n"))
        jentries.append({
            "path": e["path"], "op": e.get("op", "append"),
            "sha_before": e["sha_before"], "sha_after": e["sha_after"],
            "backup": (Path("backup") / e["path"]).as_posix(),
            "backup_sha256": safeio.sha256_bytes(bp.read_bytes()),
            "state": "staged",
        })
    journal = {"schema_version": schema, "transaction_id": name, "root_id": "test",
               "pid": os.getpid(), "host": safeio.host_name(), "session": "t",
               "created": time.time(), "updated": time.time(), "state": state,
               "entry_count": len(jentries), "entries": jentries}
    journal["checksum"] = safeio.journal_checksum(journal)
    (d / "journal.json").write_text(
        json.dumps(journal, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return d

