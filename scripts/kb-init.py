#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-init.py — 一键生成「分层交接库」骨架（handoff-kb skill）

用法（Bash / Git Bash，UTF-8 干净链路）：
  py scripts/kb-init.py --target "~/projects/新项目" --project "新项目" \
      --lines "固件,运行态,服务端,测速"
  py scripts/kb-init.py --target /tmp/demo --no-git
  py scripts/kb-init.py --target . --force        # 覆盖同名模板文件

产出：AGENTS/CLAUDE/GEMINI 入口、00 基线、01..0N 事实层、05 现状、
06 流水、90 归档、启动消息、.gitignore/.gitattributes、handoff-check 占位、归档/。
自动 git init -b main + 首次 commit，并做除密扫描与接手成本估算。
"""
from __future__ import annotations

import argparse
import datetime
import io
import re
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

SECRET_PATTERNS = [
    (re.compile(r"LTAI[0-9A-Za-z]{8,}"), "云厂商 AK"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "私钥 PEM"),
    (re.compile(r"(?i)(password|passwd|secret|token)\s*[:=]\s*['\"][^'\"$]{6,}['\"]"), "明文口令/令牌"),
    (re.compile(r"(?i)sk-[0-9A-Za-z]{20,}"), "API key"),
]


def read(p: Path) -> str:
    return io.open(p, encoding="utf-8").read()


def write(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)


def render(s: str, ctx: dict) -> str:
    for k, v in ctx.items():
        s = s.replace("{{" + k + "}}", str(v))
    # 未提供的占位符一律清空，避免模板残留
    return re.sub(r"\{\{[A-Z_]+\}\}", "", s)


def sh(args, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def scan_secrets(target: Path):
    hits = []
    for p in target.rglob("*"):
        if not p.is_file() or ".git" in p.parts:
            continue
        try:
            if p.stat().st_size > 2_000_000:
                continue
            text = read(p)
        except Exception:
            continue
        for pat, label in SECRET_PATTERNS:
            if pat.search(text):
                hits.append((str(p.relative_to(target)), label))
    return hits


def safe(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", s)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成分层交接库骨架")
    ap.add_argument("--target", required=True, help="目标目录（绝对或相对）")
    ap.add_argument("--project", default=None, help="项目名，默认取目录名")
    ap.add_argument("--lines", default="线A,线B,线C,线D",
                    help="事实层分册名，逗号分隔，决定 01..0N（最多 8）")
    ap.add_argument("--no-git", action="store_true", help="只生成文件，不初始化 git")
    ap.add_argument("--force", action="store_true", help="已存在同名文件时覆盖（默认跳过）")
    ap.add_argument("--shards", choices=["auto", "none"], default="auto",
                    help="auto=按 --lines 生成 06_流水/<线>.md 分片（默认）；none=单份 06_会话日志.md")
    args = ap.parse_args()

    target = Path(args.target).expanduser().resolve()
    project = args.project or target.name
    lines = [x.strip() for x in args.lines.split(",") if x.strip()]
    if not lines:
        lines = ["线A"]
    if len(lines) > 8:
        print("! 事实层分册最多 8 个（编号 01-08，05/06/90 已被占用）", file=sys.stderr)
        return 2

    today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    route_rows, file_rows, status_rows, route_inline = [], [], [], []
    for i, name in enumerate(lines, 1):
        fn = "%02d_%s.md" % (i, safe(name))
        route_rows.append("| %s | `%s` + `00` |" % (name, fn))
        file_rows.append("| `%s` | %s（事实层） |" % (fn, name))
        status_rows.append("| %s | 稳定 | [填] | %s |" % (name, today))
        route_inline.append("%s → `%s`" % (name, fn))

    ctx = {
        "PROJECT": project,
        "PROJECT_ROOT": str(target),
        "DATE": today,
        "ROUTE_TABLE": "\n".join(route_rows),
        "FILE_TABLE": "\n".join(file_rows),
        "LINE_STATUS": "\n".join(status_rows),
        "ROUTE_INLINE": "；".join(route_inline),
        "INITIAL_STATUS": "- [填：一句话现状，例如「XX 已上线，YY 观察中」]",
        "ID": "01",
        "LINE_NAME": "线A",
    }

    # 按线分片：一写者一文件，从根上消除共享单文件的并发覆盖
    shard_names = lines + ["其他"]
    shard_rows = []
    for n in shard_names:
        if n == "其他":
            shard_rows.append("| `06_流水/其他.md` | 无法归类 / 跨线交叉点 |")
        else:
            shard_rows.append("| `06_流水/%s.md` | %s线 |" % (safe(n), n))
    shard_table = "\n".join(shard_rows)
    if args.shards == "auto":
        shard_section = (
            "## 流水分片\n\n"
            "每条线**只写自己那一份**，从根上消除共享单文件的并发覆盖：\n\n"
            "| 分片 | 归它写 |\n|---|---|\n" + shard_table + "\n\n"
            "- 每条 1–3 行；**单分片**超 200 行 / 60 KB 才折叠进 `90`（触线再拆）。\n"
            "- `06_会话日志.md` 是历史卷 + 索引，**只读、不追加流水**。\n"
            "- 与 `05` §5 同源，改一处必须同步另一处。\n"
        )
    else:
        shard_section = (
            "## 流水\n\n"
            "- `06_会话日志.md` 单份 append-only 流水；超 200 行 / 60 KB 折叠进 `90`（触线再拆）。\n"
        )
    ctx["SHARD_TABLE"] = shard_table
    ctx["SHARD_SECTION"] = shard_section

    print("== 目标：%s" % target)
    print("== 项目：%s | 事实层 %d 册：%s" % (project, len(lines), ", ".join(lines)))

    files: dict[str, str] = {}

    def put(rel, src, extra=None):
        c = dict(ctx)
        if extra:
            c.update(extra)
        files[rel] = render(read(ASSETS / src), c)

    put("AGENTS.md", "AGENTS.md")
    pointer = ("按 `AGENTS.md` 执行 —— 本工作区唯一的客户端无关入口，"
               "接手顺序、写回规则与硬约束都在那里。\n")
    files["CLAUDE.md"] = pointer
    files["GEMINI.md"] = pointer
    put("00_基线.md", "00_baseline.md")
    for i, name in enumerate(lines, 1):
        put("%02d_%s.md" % (i, safe(name)), "fact_book.md",
            {"ID": "%02d" % i, "LINE_NAME": name})
    put("05_进度仪表盘.md", "05_dashboard.md")
    if args.shards == "auto":
        put("06_会话日志.md", "06_index.md")
        for n in shard_names:
            put("06_流水/%s.md" % safe(n), "06_shard.md",
                {"LINE_NAME": n, "LINE_SCOPE": "本线"})
    else:
        put("06_会话日志.md", "06_log.md")
    put("90_过程档案.md", "90_archive.md")
    put("新会话启动消息.txt", "启动消息.txt")
    files[".gitignore"] = read(ASSETS / "gitignore.txt")
    files[".gitattributes"] = read(ASSETS / "gitattributes.txt")
    files["scripts/handoff-check.sh"] = (
        "#!/bin/sh\n"
        "# 只读自检模板 —— 按项目填充：把文档里的当前值与实机/远端核对，只 echo，不改任何东西。\n"
        "# 例：uci get passwall.@global[0].node / ssh HOST 'app --version' / 查询 API\n"
        'echo "[handoff-check] TODO: 按项目填充只读核对项"\n'
    )

    created, skipped = [], []
    for rel, content in files.items():
        p = target / rel
        if p.exists() and not args.force:
            skipped.append(rel)
            continue
        write(p, content)
        created.append(rel)
    (target / "归档").mkdir(parents=True, exist_ok=True)
    if not (target / "归档" / ".gitkeep").exists():
        write(target / "归档" / ".gitkeep", "")

    print("\n-- 生成 %d 个文件，跳过 %d 个已存在（--force 可覆盖）" % (len(created), len(skipped)))
    for r in created:
        print("   + %s" % r)
    if skipped:
        print("   = 跳过：%s" % ", ".join(skipped))

    hits = scan_secrets(target)
    if hits:
        print("\n!! 疑似明文凭证 %d 处（入库前处理，或加进 .gitignore）：" % len(hits))
        for f, label in hits[:20]:
            print("   - %s  [%s]" % (f, label))
    else:
        print("\n-- 除密扫描：0 处明文凭证")

    if not args.no_git:
        if (target / ".git").exists():
            print("-- 已是 git 仓库，跳过 init")
        else:
            r = sh(["git", "init", "-b", "main"], cwd=target)
            if r.returncode != 0:  # 老版本 git 不支持 -b
                sh(["git", "init"], cwd=target)
                sh(["git", "checkout", "-b", "main"], cwd=target)
            for k, v in (("core.autocrlf", "false"), ("core.quotepath", "false")):
                sh(["git", "config", k, v], cwd=target)
            # 机器上没有全局身份时补一份本仓库兜底，否则首次 commit 直接失败
            if not sh(["git", "config", "user.name"], cwd=target).stdout.strip():
                sh(["git", "config", "user.name", "handoff-kb"], cwd=target)
            if not sh(["git", "config", "user.email"], cwd=target).stdout.strip():
                sh(["git", "config", "user.email", "handoff-kb@localhost"], cwd=target)
            sh(["git", "add", "-A"], cwd=target)
            r = sh(["git", "commit", "-m",
                    "初始基线：分层交接库骨架（00-0N 事实层 / 05 现状 / 06 流水 / 90 归档 / AGENTS 入口）"],
                   cwd=target)
            if r.returncode == 0:
                print("-- git init + 首次 commit 完成（main）")
            else:
                print("!! commit 失败：%s" % (r.stderr or r.stdout).strip()[:200])
    else:
        print("-- --no-git：跳过版本控制（建议尽快 git init）")

    core = [target / f for f in ("00_基线.md", "05_进度仪表盘.md")]
    b = sum(p.stat().st_size for p in core if p.exists())
    total = sum(p.stat().st_size for p in target.rglob("*")
                if p.is_file() and ".git" not in p.parts)
    print("\n== 接手成本：00 + 05 = %d B ≈ %.1f k tokens（按 4.5 B/token 估）"
          % (b, b / 4500))
    print("== 全库 %d B；按需读而非全读，是这套结构省 token 的关键" % total)
    print("== 下一步：填 00 的 K-xx 基线行 / 05 §0 现状 / AGENTS.md 硬约束；")
    print("   按项目补 .gitignore（大文件先排再 add）、把 handoff-check.sh 换成真实只读核对项；")
    print("   把 新会话启动消息.txt 复制给新会话。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
