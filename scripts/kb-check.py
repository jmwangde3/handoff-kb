#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-check.py — 分层交接库只读体检（不改任何文件）

用法：
  py scripts/kb-check.py --target "~/projects/某项目"
  py scripts/kb-check.py --target . --strict      # WARN 也算失败

检查：必需文件、各层体积与接手成本、膨胀阈值、残留 TODO/明文凭证、
编号契约（K-xx / G-xxx 重复定义）、Markdown 表格列数一致、git 未提交改动。
ERROR > 0 → 退出码 1；--strict 时 WARN > 0 也返回 1。
"""
from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OK, WARN, ERR = "OK", "WARN", "ERR"
report: list[tuple[str, str, str]] = []

SECRET_PATTERNS = [
    (re.compile(r"LTAI[0-9A-Za-z]{8,}"), "云厂商 AK"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "私钥 PEM"),
    (re.compile(r"(?i)(password|passwd|secret|token)\s*[:=]\s*['\"][^'\"$]{6,}['\"]"), "明文口令/令牌"),
    (re.compile(r"(?i)sk-[0-9A-Za-z]{20,}"), "API key"),
]

THRESHOLDS = {
    "s6_max_items": 5,
    "s0_max_lines": 4,
    "log_max_lines": 200,
    "log_max_bytes": 60 * 1024,
    "baseline_max_lines": 150,
    "archive_max_lines": 600,
}


def add(level, item, msg):
    report.append((level, item, msg))
    print("[%-4s] %-30s %s" % (level, item, msg))


def read(p: Path) -> str:
    return io.open(p, encoding="utf-8").read()


def sections(text):
    out, cur, buf = {}, None, []
    for line in text.splitlines():
        if re.match(r"^##\s", line):
            if cur is not None:
                out[cur] = buf
            cur, buf = line.strip(), []
        else:
            buf.append(line)
    if cur is not None:
        out[cur] = buf
    return out


def sec(out, num):
    for k, v in out.items():
        if re.match(r"^##\s*%s[\.\s]" % re.escape(str(num)), k):
            return v
    return []


def nlines(p: Path) -> int:
    return len(read(p).splitlines())


def find(target: Path, prefix: str):
    hits = sorted(target.glob("%s*.md" % prefix))
    return hits[0] if hits else None


def sh(args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def table_blocks(lines):
    """只认含 Markdown 分隔行（| --- | --- |）的表格块，避免把代码块 / 行内管道当表格。"""
    blocks, cur, start = [], [], 0
    for i, raw in enumerate(lines, 1):
        s = raw.strip()
        is_row = s.startswith("|") and s.endswith("|") and len(s) >= 3
        if is_row:
            if not cur:
                start = i
            cur.append((i, s.replace(r"\|", "").count("|") - 1))
        else:
            if cur:
                blocks.append((start, cur))
                cur = []
    if cur:
        blocks.append((start, cur))
    out = []
    for start, rows in blocks:
        has_sep = any(re.match(r"^\|[\s:\-|]+\|$", lines[i - 1].strip())
                      for i, _ in rows)
        if has_sep and len(rows) >= 2:
            out.append((start, rows))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="分层交接库只读体检")
    ap.add_argument("--target", default=".", help="项目目录，默认当前目录")
    ap.add_argument("--strict", action="store_true", help="WARN 也算失败")
    ap.add_argument("--loose", action="store_true",
                    help="已有自有命名体系的项目（如 60_进度.md）：必需文件缺失降为 WARN，"
                         "仍检查体积 / 阈值 / 编号 / git")
    args = ap.parse_args()

    t = Path(args.target).expanduser().resolve()
    if not t.is_dir():
        print("目标不存在或不是目录：%s" % t, file=sys.stderr)
        return 2
    print("== 体检：%s\n" % t)

    # 1. 必需文件（允许别名，兼容 60_进度.md / 00_INDEX.md 这类自有命名）
    def pick(prefixes):
        for pre in prefixes:
            p = find(t, pre)
            if p and p.exists():
                return p
        return None

    required = {
        "AGENTS.md": lambda: t / "AGENTS.md",
        "00 基线": lambda: pick(["00_", "*INDEX*", "*索引*"]),
        "05 现状": lambda: pick(["05_", "*进度*", "*现状*"]),
        "06 流水": lambda: pick(["06_", "*流水*", "*日志*"]),
        "90 归档": lambda: pick(["90_", "*过程档案*", "*归档*"]),
        ".gitignore": lambda: t / ".gitignore",
    }
    paths = {}
    for label, getter in required.items():
        p = getter()
        if p and p.exists():
            add(OK, "必需文件 · " + label, p.name)
            paths[label] = p
        else:
            add(WARN if args.loose else ERR, "必需文件 · " + label,
                "缺失" + ("（--loose：自有命名体系，跳过）" if args.loose else ""))

    for name in ("CLAUDE.md", "GEMINI.md"):
        p = t / name
        if not p.exists():
            add(WARN, "入口指针 · " + name, "缺失（部分客户端不认 AGENTS.md）")
        elif p.stat().st_size > 400:
            add(WARN, "入口指针 · " + name, "%d B，疑似塞了事实内容，应只留两行指针" % p.stat().st_size)
        else:
            add(OK, "入口指针 · " + name, "%d B，仅指针" % p.stat().st_size)

    # 2. 体积表 + 接手成本
    print("\n-- 体积表（.md / .txt，排除 .git 与 归档/）")
    all_docs = [p for p in t.rglob("*") if p.is_file()
                and p.suffix.lower() in (".md", ".txt")
                and ".git" not in p.parts and "归档" not in p.parts
                and ".workbuddy" not in p.parts]
    # 数据产物不是交接文档：>2 MB 文本、解包 / 采集 / 构建目录下的 .md/.txt 一律跳过
    DATA_DIRS = {"AI_files", "assets", "data", "output", "evidence", "paktools",
                 "node_modules", "build", "dist", "vendor", "tmp"}
    big, datafiles, docs = [], [], []
    for p in all_docs:
        rel = p.relative_to(t)
        if p.stat().st_size > 2_000_000:
            big.append(p)
        elif set(rel.parts[:-1]) & DATA_DIRS:
            datafiles.append(p)
        else:
            docs.append(p)
    total = 0
    for p in sorted(docs):
        b = p.stat().st_size
        total += b
        print("   %-34s %8d B %5d 行" % (str(p.relative_to(t)), b, nlines(p)))
    core_names = {paths.get("00 基线").name, paths.get("05 现状").name} if (
        "00 基线" in paths and "05 现状" in paths) else set()
    core = sum(p.stat().st_size for p in docs if p.name in core_names)
    if big or datafiles:
        print("   （已跳过 %d 个数据产物：>2 MB 文本 %d / 资料目录 %d，非交接文档）"
              % (len(big) + len(datafiles), len(big), len(datafiles)))
    print("   %-34s %8d B" % ("全库合计", total))
    if core:
        print("   %-34s %8d B ≈ %.1f k tokens" % ("接手必读（00 + 05）", core, core / 4500))
        ratio = 100.0 * core / total if total else 0
        add(OK, "接手成本", "%d B / 全库 %d B = %.1f%%（中文按 4.5 B/token 估 ≈ %.1f k）"
            % (core, total, ratio, core / 4500))
        # 小项目全库本来就小，比例天然偏高，只有总量 >50 KB 时比例才有意义
        if ratio > 25 and total > 50_000:
            add(WARN, "接手成本偏高", "必读集合占全库 %.1f%%，考虑把内容从 00/05 下沉" % ratio)
    else:
        add(ERR, "接手成本", "无法计算（00 或 05 缺失）")

    # 3. 膨胀阈值
    print("")
    if "05 现状" in paths:
        p = paths["05 现状"]
        out = sections(read(p))
        s0 = [x for x in sec(out, 0) if x.strip() and not x.strip().startswith(">")]
        if len(s0) > THRESHOLDS["s0_max_lines"]:
            add(ERR, "05 §0 现状", "%d 行 > %d 行上限，压缩并把细节写 06"
                % (len(s0), THRESHOLDS["s0_max_lines"]))
        else:
            add(OK, "05 §0 现状", "%d 行（≤%d）" % (len(s0), THRESHOLDS["s0_max_lines"]))
        s6 = sec(out, 6)
        items = [x for x in s6 if re.match(r"^\s*\[\d{4}-\d{2}-\d{2}", x)]
        if len(items) > THRESHOLDS["s6_max_items"]:
            add(ERR, "05 §6 摘要", "%d 条 > %d 条上限，整条移进 06"
                % (len(items), THRESHOLDS["s6_max_items"]))
        else:
            add(OK, "05 §6 摘要", "%d 条（≤%d）" % (len(items), THRESHOLDS["s6_max_items"]))
        longs = [x for x in items if len(x) > 300]
        if longs:
            add(WARN, "05 §6 单条长度", "%d 条 > 300 字，按规则应整条写 06 只留摘要" % len(longs))
        if len(p.read_text(encoding="utf-8").splitlines()) > 90:
            add(WARN, "05 总行数", "%d 行，接近需拆分 06 的规模" % nlines(p))

    if "06 流水" in paths:
        main_log = paths["06 流水"]
        shard_dir = t / "06_流水"
        shards = sorted(shard_dir.glob("*.md")) if shard_dir.is_dir() else []
        if shards:
            add(OK, "06 流水分片", "%d 个分片（%s）+ 历史卷 %d 行只读"
                % (len(shards), "、".join(p.stem for p in shards), nlines(main_log)))
            worst, bad = 0, []
            for p in shards:
                n, b = nlines(p), p.stat().st_size
                worst = max(worst, n)
                if n > THRESHOLDS["log_max_lines"] or b > THRESHOLDS["log_max_bytes"]:
                    bad.append(p.stem)
            if bad:
                add(ERR, "06 分片轮转", "%s 触线（200 行 / 60 KB），按主题折叠进 90" % "、".join(bad))
            else:
                add(OK, "06 分片轮转", "全部 %d 个分片未触线，最大 %d 行" % (len(shards), worst))
        else:
            n, b = nlines(main_log), main_log.stat().st_size
            if n > THRESHOLDS["log_max_lines"] or b > THRESHOLDS["log_max_bytes"]:
                add(ERR, "06 流水轮转", "%d 行 / %d B 触线（200 行 / 60 KB），按主题折叠进 90" % (n, b))
            else:
                add(OK, "06 流水轮转", "%d 行 / %d B，未触线" % (n, b))

    if "00 基线" in paths:
        bp = paths["00 基线"]
        n = nlines(bp)
        id_count = len(set(re.findall(r"\b[KG]-\d{2,3}\b", read(bp))))
        # 已是结论索引（编号 >= 20）时放宽阈值：它本来就该比普通基线表长
        limit = 250 if id_count >= 20 else THRESHOLDS["baseline_max_lines"]
        kind = "结论索引 %d 条" % id_count if id_count >= 20 else "普通基线表"
        if n > limit:
            add(WARN, "00 基线规模", "%d 行 > %d（%s），考虑分卷" % (n, limit, kind))
        else:
            add(OK, "00 基线规模", "%d 行（≤%d，%s）" % (n, limit, kind))

    if "90 归档" in paths:
        n = nlines(paths["90 归档"])
        if n > THRESHOLDS["archive_max_lines"]:
            add(WARN, "90 归档规模", "%d 行 > 600，考虑再分卷或移 归档/" % n)
        else:
            add(OK, "90 归档规模", "%d 行（非必读）" % n)

    # 4. 残留 TODO / 明文凭证
    print("")
    todo = 0
    secret_hits = []
    for p in docs:
        text = read(p)
        todo += len(re.findall(r"\b(TODO|FIXME|XXX)\b", text))
        for pat, label in SECRET_PATTERNS:
            if pat.search(text):
                secret_hits.append((str(p.relative_to(t)), label))
    if todo:
        add(WARN, "残留 TODO/FIXME", "%d 处（模板占位符属正常，改造后应为 0）" % todo)
    else:
        add(OK, "残留 TODO/FIXME", "0 处")
    if secret_hits:
        for f, label in secret_hits[:10]:
            add(ERR, "明文凭证", "%s [%s] —— 立刻改环境变量并加进 .gitignore" % (f, label))
    else:
        add(OK, "明文凭证", "0 处")

    # 5. 编号契约 + 表格列数
    print("")
    id_defs = {}
    all_ids = set()
    col_issues = []
    for p in docs:
        text = read(p)
        # 全库唯一 ID 数（含引用）；首列定义单独统计用于查重复
        all_ids.update(re.findall(r"\b[KG]-\d{2,3}\b", text))
        # 允许 ID 被 ** / ` 包裹（结论索引常见写法）
        for m in re.finditer(r"^\|\s*[*`]*\s*([KG]-\d{2,3})", text, re.M):
            id_defs.setdefault(m.group(1), []).append(str(p.relative_to(t)))
        # 只检查含分隔行的真表格块；报告「主列数 + 异常行」，不刷屏
        for start, rows in table_blocks(text.splitlines()):
            mode = Counter(c for _, c in rows).most_common(1)[0][0]
            bad = [(i, c) for i, c in rows if c != mode]
            if bad:
                col_issues.append("%s:%d 主列数=%d，异常行 %s" % (
                    str(p.relative_to(t)), start, mode,
                    ",".join("%d:%d" % (i, c) for i, c in bad[:6])))
    dup = {k: v for k, v in id_defs.items() if len(v) > 1}
    if dup:
        for k, v in list(dup.items())[:10]:
            add(ERR, "编号重复定义", "%s 在 %s 定义多次（ID 永不复用）" % (k, ", ".join(v)))
    else:
        add(OK, "编号契约", "%d 个 K/G 编号（表格首列定义 %d 个），无重复定义"
            % (len(all_ids), len(id_defs)))
    if col_issues:
        for c in col_issues[:10]:
            add(WARN, "表格列数不一致", c)
    else:
        add(OK, "表格列数一致性", "全部表格块内列数一致")

    # 6. git
    print("")
    g = sh(["git", "rev-parse", "--is-inside-work-tree"], cwd=t)
    if g.returncode != 0 or g.stdout.strip() != "true":
        add(ERR, "版本控制", "不是 git 仓库 —— 并发覆盖无兜底，先 git init")
    else:
        add(OK, "版本控制", "git 仓库")
        st = sh(["git", "status", "--porcelain"], cwd=t)
        dirty = [x for x in st.stdout.splitlines() if x.strip()]
        if dirty:
            add(WARN, "未提交改动", "%d 个文件（可能是别的会话正在改，动笔前先看清）" % len(dirty))
            for d in dirty[:5]:
                print("        %s" % d)
        else:
            add(OK, "未提交改动", "0，工作区干净")
        lg = sh(["git", "log", "--oneline", "-5"], cwd=t)
        if lg.stdout.strip():
            print("   -- 最近 5 条 commit：")
            for line in lg.stdout.strip().splitlines():
                print("      %s" % line)

    # 汇总
    ne = sum(1 for lv, _, _ in report if lv == ERR)
    nw = sum(1 for lv, _, _ in report if lv == WARN)
    no = sum(1 for lv, _, _ in report if lv == OK)
    print("\n== 汇总：OK %d / WARN %d / ERR %d" % (no, nw, ne))
    if ne:
        print("== 有 ERROR，先修再收尾（常见：缺文件、明文凭证、06 触线、编号重复）")
    if args.strict and nw:
        print("== --strict：WARN 也算失败")
    return 1 if ne or (args.strict and nw) else 0


if __name__ == "__main__":
    sys.exit(main())
