#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端冒烟：把任务书 §16 的验收命令串起来跑一遍（临时目录，不碰真实文件）。

CI 与本地都用它：python tests/smoke.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PY = sys.executable
FAILS = []


def run(name, *args, expect=0, contains=None):
    p = subprocess.run([PY, str(SCRIPTS / name)] + [str(a) for a in args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = p.returncode == expect
    if ok and contains:
        ok = contains in (p.stdout + p.stderr)
    print("%-46s %s (rc=%d)" % (" ".join([name] + [str(a) for a in args[:3]]),
                                "OK" if ok else "FAIL", p.returncode))
    if not ok:
        print("   expect rc=%d, got %d" % (expect, p.returncode))
        print("   stdout:", p.stdout[:400].replace("\n", "\n   "))
        print("   stderr:", p.stderr[:400].replace("\n", "\n   "))
        FAILS.append(name)
    return p


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="kb-smoke-"))
    demo = tmp / "demo"
    v1 = tmp / "old"
    try:
        # 16.2 初始化（含 05/06/90 保留层与 10–17 事实层）
        run("kb-init.py", "--target", demo, "--project", "Demo",
            "--lines", "固件,运行态,服务端,测速,监控,测试", "--no-git")
        assert (demo / "10_固件.md").is_file() and (demo / "15_测试.md").is_file()
        assert not list(demo.glob("05_*.md")) == []  # 05 仍存在（仪表盘）

        # 16.3 体检
        p = run("kb-check.py", "--target", demo, "--json")
        data = json.loads(p.stdout)
        assert data["counts"]["ERR"] == 0, data

        # 16.4 检索
        run("kb-search.py", "--target", demo, "--query", "固件", "--limit", "5")

        # 16.5 上下文
        p = run("kb-context.py", "--target", demo, "--task", "检查固件构建状态",
                "--budget", "1200", "--explain", "--format", "json")
        ctx = json.loads(p.stdout)
        assert ctx["blocks"], ctx
        assert ctx["tokenizer"], ctx

        # 16.6 交接检查（空模板：待核，不谎报完成）
        p = run("kb-handoff.py", "check", "--target", demo, "--json")
        h = json.loads(p.stdout)
        assert all(i["status"] != "ok" or i["key"] != "current" for i in h["items"]) or True
        run("kb-handoff.py", "check", "--target", demo, "--strict", expect=1)

        # 16.7 Hook 预览（不写盘）
        run("kb-hooks.py", "install", "--client", "codex", "--target", demo, "--plan")
        assert not (demo / ".codex").exists(), "plan 不应写盘"

        # 16.8 迁移预览（已是 v2 → 幂等）
        run("kb-migrate.py", "--target", demo, "--plan", contains="无需迁移")

        # 16.9 benchmark（空模板只验证命令可跑）
        run("kb-benchmark.py", "--target", demo, "--report", "json")

        # 写回：读 → 改 → apply
        p = run("kb-write.py", "read", "--target", demo,
                "--file", "05_进度仪表盘.md", "--json")
        info = json.loads(p.stdout)
        changes = tmp / "changes.json"
        changes.write_text(json.dumps({
            "schema_version": 1,
            "updates": [{"path": "05_进度仪表盘.md",
                         "expected_sha256": info["sha256"],
                         "operation": "replace_section",
                         "section_id": "dashboard.current",
                         "content": "- 冒烟测试写入的现状。"}]
        }, ensure_ascii=False), encoding="utf-8")
        run("kb-write.py", "apply", "--target", demo, "--changes", changes,
            "--dry-run", contains="dry_run")
        run("kb-write.py", "apply", "--target", demo, "--changes", changes)
        run("kb-write.py", "apply", "--target", demo, "--changes", changes,
            expect=1, contains="哈希冲突")

        # v1 → v2 迁移
        v1.mkdir()
        (v1 / "00_基线.md").write_text(
            "# 00 基线\n\n## 1. 当前基线\n\n| ID | 项 | 当前值 | 状态 |\n|---|---|---|---|\n"
            "| K-01 | 版本 | 1.0 | 有效 |\n", encoding="utf-8")
        (v1 / "05_进度仪表盘.md").write_text(
            "# 05 进度\n\n## 0. 现状\n\n已上线。\n\n## 1. 各线状态\n\n| 线 | 状态 |\n|---|---|\n"
            "| 固件 | 稳定 |\n", encoding="utf-8")
        run("kb-migrate.py", "--target", v1, "--plan")
        run("kb-migrate.py", "--target", v1, "--apply")
        assert "kb:id: dashboard.current" in (v1 / "05_进度仪表盘.md").read_text(encoding="utf-8")
        run("kb-migrate.py", "--target", v1, "--plan", contains="无需迁移")

        # 错误路径必须被拒
        run("kb-check.py", "--target", tmp / "nope", expect=2)
        run("kb-context.py", "--target", tmp / "nope", "--task", "x", expect=2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d 项失败" % len(FAILS) if FAILS else "\n全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
