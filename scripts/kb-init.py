#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-init.py — 一键生成分层交接库骨架（handoff-kb 2.0）

v2 关键变化
- 事实分册编号改为 **10–17**（最多 8 条线）。00/05/06/90 是保留层，旧的 01–04 仍被认作事实分册。
- 写盘前完整预检查：目标目录、父目录 git 仓库、文件名碰撞（大小写 / Unicode NFC）、符号链接、敏感信息、暂存区。
- `--plan` 只打印计划，不落盘。
- 只有"独立且没有 git 仓库"的目录才自动 `git init`；已有仓库不再嵌套、不自动提交。
- 只 `git add --` 本次生成的白名单文件（**从不** `git add -A`）。
- 凭证扫描命中 → 拒绝提交并返回非 0，不再"报成功"。
- `.gitignore` / `.gitattributes` / `AGENTS.md` / 入口指针属于受保护配置，覆盖需要 `--overwrite-config`。

用法：
  py kb-init.py --target ./demo --project Demo --lines "固件,运行态,服务端"
  py kb-init.py --target ./demo --project Demo --lang en          # 英文模板 + 英文默认线名
  py kb-init.py --target ./demo --plan
  py kb-init.py --target ./demo --lines "固件" --no-git --force
  py kb-init.py --target ./demo --overwrite-config --force
"""
from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import protocol, security  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

PROTECTED = set(protocol.ENTRY_FILES) | {".gitignore", ".gitattributes"}
ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')

# `--lines` 的默认值跟 `--lang` 走：默认中文名，`--lang en` 时用英文名。
# 不这么写的话，`--lang en` 不显式给 `--lines` 就会生成 `10_线A.md`——模板是英文的，
# 文件名和内容却是中文的，用户还得回头改名。
DEFAULT_LINES = {
    "zh": "线A,线B,线C,线D",
    "en": "lineA,lineB,lineC,lineD",
}


class Refused(Exception):
    """预检查拒绝操作。"""


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(s)


def render(s: str, ctx: dict) -> str:
    for k, v in ctx.items():
        s = s.replace("{{" + k + "}}", str(v))
    return re.sub(r"\{\{[A-Z_]+\}\}", "", s)


def sh(args, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def find_git_repo(path: Path):
    """返回最近的包含 .git 的目录（含自身），没有则 None。"""
    p = path.resolve()
    for cand in [p] + list(p.parents):
        if (cand / ".git").exists():
            return cand
    return None


def normalize_name(raw: str):
    """清洗线名：去控制字符、Unicode NFC、拒绝路径分隔符。返回 (name, warnings)。"""
    warn = []
    n = unicodedata.normalize("NFC", raw).strip()
    if not n:
        raise Refused("线名不能为空")
    if ILLEGAL.search(n):
        cleaned = ILLEGAL.sub("_", n)
        warn.append("线名 %r 含非法字符，已改为 %r" % (n, cleaned))
        n = cleaned
    if n in ("其他",):
        raise Refused("线名 %r 是保留名（分片里已有 其他.md）" % n)
    if protocol.number_of(n + ".md") is not None:
        raise Refused("线名不能以 NN_ 形式开头：%r" % n)
    return n, warn


def build_plan(target: Path, project: str, lines, shards: str, force: bool,
               overwrite_config: bool, lang: str = "zh"):
    """生成 {rel: content} 与元信息；不写盘。"""
    today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    en = lang == "en"
    assets = (ASSETS / "en") if en else ASSETS
    fill = "[fill]" if en else "[填]"
    lo, hi = protocol.FACT_RANGE
    route_rows, file_rows, status_rows, route_inline, shard_rows = [], [], [], [], []
    for i, name in enumerate(lines):
        num = lo + i
        fn = "%02d_%s.md" % (num, name)
        route_rows.append("| %s | `%s` + `00` |" % (name, fn))
        file_rows.append(("| `%s` | %s (fact layer) |" if en else "| `%s` | %s（事实层） |")
                         % (fn, name))
        status_rows.append(("| %s | stable | %s | %s |" if en else "| %s | 稳定 | %s | %s |")
                           % (name, fill, today))
        route_inline.append("%s → `%s`" % (name, fn))
        shard_rows.append(("| `06_流水/%s.md` | %s line |" if en else "| `06_流水/%s.md` | %s线 |")
                          % (name, name))
    shard_rows.append("| `06_流水/其他.md` | uncategorised / cross-line |" if en
                      else "| `06_流水/其他.md` | 无法归类 / 跨线交叉点 |")

    ctx = {
        "PROJECT": project,
        "PROJECT_ROOT": str(target),
        "DATE": today,
        "SCHEMA": protocol.SCHEMA_VERSION,
        "FACT_RANGE": protocol.fact_shard_range_text(),
        "ID": "%02d" % lo,
        "LINE_NAME": lines[0] if lines else ("lineA" if en else "线A"),
        "ROUTE_TABLE": "\n".join(route_rows),
        "FILE_TABLE": "\n".join(file_rows),
        "LINE_STATUS": "\n".join(status_rows),
        "ROUTE_INLINE": ("; " if en else "；").join(route_inline),
        "INITIAL_STATUS": ('- [fill: one line, e.g. "XX is live, YY under observation"]' if en
                           else "- [填：一句话现状，例如「XX 已上线，YY 观察中」]"),
        "SHARD_TABLE": "\n".join(shard_rows),
    }

    if shards == "auto":
        if en:
            ctx["SHARD_SECTION"] = (
                "## Log shards\n\nEach line **writes only its own file**, which removes shared-file "
                "concurrent overwrites at the root:\n\n"
                "| Shard | Its writer |\n|---|---|\n" + ctx["SHARD_TABLE"] + "\n\n"
                "- 1–3 lines per entry; a **single shard** is folded into `90` only beyond 200 lines / 60 KB.\n"
                "- `06_会话日志.md` is the history volume + index: **read-only, no log entries**.\n"
                "- Same source as `05` §5: change one, sync the other.\n"
            )
        else:
            ctx["SHARD_SECTION"] = (
                "## 流水分片\n\n每条线**只写自己那一份**，从根上消除共享单文件的并发覆盖：\n\n"
                "| 分片 | 归它写 |\n|---|---|\n" + ctx["SHARD_TABLE"] + "\n\n"
                "- 每条 1–3 行；**单分片**超 200 行 / 60 KB 才折叠进 `90`（触线再拆）。\n"
                "- `06_会话日志.md` 是历史卷 + 索引，**只读、不追加流水**。\n"
                "- 与 `05` §5 同源，改一处必须同步另一处。\n"
            )
    else:
        ctx["SHARD_SECTION"] = (
            "## Log\n\n- `06_会话日志.md` is a single append-only log; "
            "fold into `90` beyond 200 lines / 60 KB.\n" if en else
            "## 流水\n\n- `06_会话日志.md` 单份 append-only 流水；"
            "超 200 行 / 60 KB 折叠进 `90`（触线再拆）。\n")

    files = {}

    def put(rel, src, extra=None):
        c = dict(ctx)
        if extra:
            c.update(extra)
        files[rel] = render(read(assets / src), c)

    put("AGENTS.md", "AGENTS.md")
    pointer = ("Follow `AGENTS.md` — the only client-agnostic entry for this workspace; "
               "handoff order, write-back rules and hard constraints live there.\n" if en else
               "按 `AGENTS.md` 执行 —— 本工作区唯一的客户端无关入口，"
               "接手顺序、写回规则与硬约束都在那里。\n")
    files["CLAUDE.md"] = pointer
    files["GEMINI.md"] = pointer
    put("00_基线.md", "00_baseline.md")
    for i, name in enumerate(lines):
        num = lo + i
        put("%02d_%s.md" % (num, name), "fact_book.md",
            {"ID": "%02d" % num, "LINE_NAME": name})
    put("05_进度仪表盘.md", "05_dashboard.md")
    if shards == "auto":
        put("06_会话日志.md", "06_index.md")
        for n in lines + ["其他"]:
            put("06_流水/%s.md" % n, "06_shard.md", {"LINE_NAME": n})
    else:
        put("06_会话日志.md", "06_log.md")
    put("90_过程档案.md", "90_archive.md")
    put("新会话启动消息.txt", "启动消息.txt")
    files[".gitignore"] = read(assets / "gitignore.txt")
    files[".gitattributes"] = read(assets / "gitattributes.txt")
    files["scripts/handoff-check.sh"] = (
        "#!/bin/sh\n"
        "# read-only self-check stub -- fill per project: compare documented current values\n"
        "# against the real machine/remote, echo only, change nothing.\n"
        "# e.g. uci get passwall.@global[0].node / ssh HOST 'app --version' / query an API\n"
        'echo "[handoff-check] TODO: fill in read-only checks for this project"\n' if en else
        "#!/bin/sh\n"
        "# 只读自检模板 —— 按项目填充：把文档里的当前值与实机/远端核对，只 echo，不改任何东西。\n"
        "# 例：uci get passwall.@global[0].node / ssh HOST 'app --version' / 查询 API\n"
        'echo "[handoff-check] TODO: 按项目填充只读核对项"\n')

    create, skip, modify, conflicts = [], [], [], []
    for rel, content in files.items():
        p = target / rel
        if p.is_symlink():
            conflicts.append("%s 是符号链接，拒绝穿透写入" % rel)
            continue
        if p.exists():
            try:
                same = read(p) == content
            except Exception:
                same = False
            if same:
                skip.append(rel)
                continue
            if rel in PROTECTED and not (force and overwrite_config):
                skip.append(rel + "（受保护配置，需 --overwrite-config）")
                continue
            if not force:
                skip.append(rel)
                continue
            modify.append(rel)
        else:
            create.append(rel)
    return files, {"create": create, "skip": skip, "modify": modify, "conflicts": conflicts}


def main() -> int:
    ap = argparse.ArgumentParser(description="生成分层交接库骨架（v2：10–17 编号 + 安全预检）")
    ap.add_argument("--target", required=True, help="目标目录（绝对或相对）")
    ap.add_argument("--project", default=None, help="项目名，默认取目录名")
    ap.add_argument("--lines", default=None,
                    help=("事实层分册名，逗号分隔，决定 10..17（最多 8）。"
                          "默认随 --lang 走：zh=线A,线B,线C,线D；en=lineA,lineB,lineC,lineD"))
    ap.add_argument("--no-git", action="store_true", help="只生成文件，不初始化 git")
    ap.add_argument("--force", action="store_true",
                    help="覆盖同名模板文件（不绕过敏感信息检查与受保护配置）")
    ap.add_argument("--overwrite-config", action="store_true",
                    help="允许覆盖 AGENTS.md / .gitignore / .gitattributes（需同时 --force）")
    ap.add_argument("--shards", choices=["auto", "none"], default="auto",
                    help="auto=按 --lines 生成 06_流水/<线>.md 分片（默认）；none=单份 06_会话日志.md")
    ap.add_argument("--plan", action="store_true", help="只输出计划，不写任何文件")
    ap.add_argument("--lang", choices=["zh", "en"], default="zh",
                    help=("模板语言：zh=中文模板（默认）；en=英文模板（assets/en/，"
                          "占位符与协议 ID 与中文一致）"))
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args()

    # `--lines` 的默认值依赖 `--lang`，只能在解析之后补。
    if args.lines is None:
        args.lines = DEFAULT_LINES[args.lang]

    target = Path(args.target).expanduser().resolve()
    project = args.project or target.name or "project"

    # ---- 预检查 1：目标目录 ----
    if target.exists() and not target.is_dir():
        print("ERR: 目标已存在且不是目录：%s" % target, file=sys.stderr)
        return 2

    # ---- 预检查 2：线名 ----
    raw = [x.strip() for x in args.lines.split(",") if x.strip()]
    if not raw:
        raw = [DEFAULT_LINES[args.lang].split(",")[0]]
    if len(raw) > protocol.MAX_LINES:
        print("ERR: 事实分册最多 %d 个（编号 %s；00/05/06/90 是保留层）"
              % (protocol.MAX_LINES, protocol.fact_shard_range_text()), file=sys.stderr)
        return 2
    lines, warnings = [], []
    seen = {}
    for item in raw:
        try:
            name, warn = normalize_name(item)
        except Refused as exc:
            print("ERR: %s" % exc, file=sys.stderr)
            return 2
        warnings.extend(warn)
        key = name.casefold()
        if key in seen:
            print("ERR: 线名重复（大小写/Unicode 折叠后相同）：%r 与 %r"
                  % (seen[key], name), file=sys.stderr)
            return 2
        seen[key] = name
        lines.append(name)

    files, buckets = build_plan(target, project, lines, args.shards,
                                args.force, args.overwrite_config, args.lang)

    # ---- 预检查 3：git 现状 ----
    repo = find_git_repo(target)
    git_action, git_reason = "init", "目标与父目录都没有 git 仓库"
    if repo is not None:
        if repo == target:
            git_action, git_reason = "skip", "目标已是 git 仓库，不重复初始化、不自动提交"
        else:
            git_action, git_reason = "skip", "父目录 %s 已是 git 仓库，拒绝嵌套第二个仓库" % repo

    # ---- 预检查 4：敏感信息（将要写入的内容 + 将被暂存的文件）----
    secret_hits = []
    for rel, content in files.items():
        for label, lineno, snip in security.scan_text(content):
            secret_hits.append((rel, label, lineno, snip))
    for extra in (target / "00_基线.md", target / "05_进度仪表盘.md"):
        if extra.is_file():
            for label, lineno, snip in security.scan_file(extra):
                secret_hits.append((str(extra.relative_to(target)), label, lineno, snip))

    problems = list(buckets["conflicts"])
    if secret_hits:
        problems.append("敏感信息命中 %d 处：%s"
                        % (len(secret_hits),
                           ", ".join("%s:%s(%s)" % (a, c, b) for a, b, c, _ in secret_hits[:5])))

    plan = {
        "target": str(target), "project": project, "schema_version": protocol.SCHEMA_VERSION,
        "fact_range": protocol.fact_shard_range_text(),
        "lines": lines,
        "files": {k: len(v.encode("utf-8")) for k, v in files.items()},
        "create": buckets["create"], "skip": buckets["skip"],
        "modify": buckets["modify"], "conflicts": buckets["conflicts"],
        "git": {"action": git_action, "reason": git_reason, "repo": str(repo) if repo else None},
        "secrets": [{"path": a, "label": b, "line": c} for a, b, c, _ in secret_hits],
        "warnings": warnings, "problems": problems,
    }

    if args.plan:
        if args.json:
            print(json_dumps(plan))
        else:
            print("== 计划（--plan 不写盘）=========================================")
            print("目标：%s\n项目：%s\n事实层：%s（编号 %s）\n"
                  % (target, project, ", ".join(lines), protocol.fact_shard_range_text()))
            print("将创建 %d 个：\n  %s" % (len(buckets["create"]),
                                          "\n  ".join(buckets["create"]) or "（无）"))
            print("将跳过 %d 个：\n  %s" % (len(buckets["skip"]),
                                          "\n  ".join(buckets["skip"]) or "（无）"))
            print("将覆盖 %d 个：%s" % (len(buckets["modify"]),
                                       ", ".join(buckets["modify"]) or "（无）"))
            print("git：%s —— %s" % (git_action, git_reason))
            for w in warnings:
                print("! %s" % w)
            for p in problems:
                print("ERR: %s" % p)
        return 1 if problems else 0

    if problems:
        for p in problems:
            print("ERR: %s" % p, file=sys.stderr)
        print("已拒绝写入：先处理上面的问题（可用 --plan 复看计划）。", file=sys.stderr)
        return 1

    # ---- 写盘 ----
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for rel in buckets["create"] + buckets["modify"]:
        write(target / rel, files[rel])
        written.append(rel)
    (target / "归档").mkdir(parents=True, exist_ok=True)
    if not (target / "归档" / ".gitkeep").exists():
        write(target / "归档" / ".gitkeep", "")

    print("== 目标：%s\n== 项目：%s | 事实层 %d 册：%s"
          % (target, project, len(lines), ", ".join(lines)))
    print("-- 生成 %d 个文件，跳过 %d 个%s"
          % (len(written), len(buckets["skip"]),
             "（--force 可覆盖模板；受保护配置需 --overwrite-config）" if buckets["skip"] else ""))
    for r in written:
        print("   + %s" % r)
    for r in buckets["skip"]:
        print("   = 跳过：%s" % r)

    # ---- git ----
    if args.no_git:
        print("-- --no-git：跳过版本控制（建议尽快 git init）")
    elif git_action == "skip":
        print("-- git：%s（%s）" % (git_action, git_reason))
    else:
        r = sh(["git", "init", "-b", "main"], cwd=target)
        if r.returncode != 0:
            r = sh(["git", "init"], cwd=target)
            if r.returncode == 0:
                sh(["git", "checkout", "-b", "main"], cwd=target)
            else:
                print("!! git init 失败：%s" % (r.stderr or r.stdout).strip()[:200], file=sys.stderr)
                return 1
        for k, v in (("core.autocrlf", "false"), ("core.quotepath", "false")):
            sh(["git", "config", k, v], cwd=target)
        # 2.0.1：不再写 handoff-kb@localhost 这类虚构身份。
        # 提交署名属于用户决定，自动填假身份会污染历史，还会把「本机没配身份」
        # 这个真问题掩盖成「一切正常」。
        ident = {}
        for key in ("user.name", "user.email"):
            probe = sh(["git", "config", "--get", key], cwd=target)
            ident[key] = (probe.stdout or "").strip() if probe.returncode == 0 else ""
        missing = [k for k, v in ident.items() if not v]
        if missing:
            print("-- git 已初始化，但缺少提交身份：%s（本工具不会代填）" % "、".join(missing))
            print("   首次提交前请自行配置：")
            print('     git -C "%s" config user.name "你的名字"' % target)
            print('     git -C "%s" config user.email "you@example.com"' % target)
        else:
            print("-- git 身份：%s <%s>" % (ident["user.name"], ident["user.email"]))

        stage = [p for p in (buckets["create"] + buckets["modify"] + ["归档/.gitkeep"])
                 if (target / p).is_file()]
        r = sh(["git", "add", "--"] + stage, cwd=target)
        if r.returncode != 0:
            print("!! git add 失败：%s" % (r.stderr or r.stdout).strip()[:200], file=sys.stderr)
            return 1
        staged = sh(["git", "diff", "--cached", "--name-only"], cwd=target).stdout.split("\n")
        staged = [s for s in (x.strip() for x in staged) if s]
        outside = [s for s in staged if s not in stage]
        if outside:
            print("!! 暂存区出现了白名单外的文件：%s" % ", ".join(outside[:5]), file=sys.stderr)
            sh(["git", "reset"], cwd=target)
            return 1
        hits = []
        for s in staged:
            for label, lineno, snip in security.scan_file(target / s):
                hits.append((s, label, lineno))
        if hits:
            sh(["git", "reset"], cwd=target)
            print("!! 暂存内容命中敏感信息，已取消提交：", file=sys.stderr)
            for s, label, lineno in hits:
                print("   - %s:%s  [%s]" % (s, lineno, label), file=sys.stderr)
            return 1
        r = sh(["git", "commit", "-m",
                "初始基线：分层交接库骨架 v%d（00 基线 / %s 事实层 / 05 现状 / 06 流水 / 90 归档）"
                % (protocol.SCHEMA_VERSION, protocol.fact_shard_range_text())], cwd=target)
        if r.returncode != 0:
            detail = (r.stderr or r.stdout).strip()
            # 没有提交身份不是库的问题：文件已生成、已暂存，只是这一步没完成。
            # 不代填虚构身份，也不假装成功。
            if "identity" in detail.lower() or "who you are" in detail.lower():
                print("-- git 已初始化并暂存 %d 个文件，但首次 commit 未完成：本机没配提交身份"
                      % len(staged))
                print("   配置后自行提交：")
                print('     git -C "%s" config user.name "你的名字"' % target)
                print('     git -C "%s" config user.email "you@example.com"' % target)
                print('     git -C "%s" commit -m "初始基线"' % target)
            else:
                print("!! commit 失败：%s" % detail[:200], file=sys.stderr)
                return 1
        else:
            print("-- git init + 首次 commit 完成（main），仅暂存本次生成的 %d 个文件" % len(staged))

    core = [target / f for f in ("00_基线.md", "05_进度仪表盘.md")]
    b = sum(p.stat().st_size for p in core if p.exists())
    total = sum(p.stat().st_size for p in target.rglob("*")
                if p.is_file() and ".git" not in p.parts and ".kb-txn" not in p.parts)
    print("\n== 接手成本：00 + 05 = %d B ≈ %.1f k tokens（估算，CJK 1 字≈1 token）"
          % (b, b / 4500))
    print("== 全库 %d B；按需读而非全读，是这套结构省 token 的关键" % total)
    print("== 下一步：填 00 的 K-xx 基线行 / 05 的 kb:id 章节 / AGENTS.md 硬约束；")
    print("   跑 kb-handoff.py check 看还缺什么；把 新会话启动消息.txt 复制给新会话。")
    return 0


def json_dumps(obj):
    import json
    return json.dumps(obj, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refused as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        sys.exit(2)
