#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-check.py — 分层交接库只读体检（v2）

保留旧用法与退出码语义，新增：精确文件定位、ID 定义/引用完整性、稳定章节 ID 查重、
事实元数据（状态/证据/有效期）、模板模式、`--json`。

用法：
  py kb-check.py --target .
  py kb-check.py --target . --strict        # WARN 也算失败
  py kb-check.py --target . --loose         # 自有命名体系（60_进度.md 等）
  py kb-check.py --target . --json
  py kb-check.py --target . --mode template # 刚初始化的空模板：不报"证据缺失"

不做：不修改任何文件、不联网、不读工作区外的文件。
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import facts  # noqa: E402
from lib import markdown as md  # noqa: E402
from lib import protocol, scope, security, tokens  # noqa: E402

OK, WARN, ERR = "OK", "WARN", "ERR"


class Report:
    def __init__(self, mode: str):
        self.mode = mode
        self.findings = []
        self.stats = {}
        self.max_age_days = 90

    def add(self, level, category, message, path=None, line=None):
        self.findings.append({"level": level, "category": category, "message": message,
                              "path": str(path) if path else None, "line": line})

    def counts(self):
        c = {OK: 0, WARN: 0, ERR: 0}
        for f in self.findings:
            c[f["level"]] += 1
        return c


def sh(args, cwd):
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except Exception:
        return None


def role_files(root: Path, loose: bool):
    """统一走 scope，避免各脚本对文件名各判一套（2.0.1）。"""
    return scope.role_files(root, loose=loose)


def find_shards(root: Path, loose: bool = False):
    """统一走 scope：loose 模式也认 `60_流水/` 等自有命名。"""
    return scope.shards(root, loose=loose)


def find_facts(roles):
    return sorted((protocol.number_of(p.name), p) for p in roles.get("fact", []))


def split_row(line: str):
    """按未转义的 | 切表格行。"""
    cells, cur, esc = [], "", False
    for ch in line.strip().strip("|"):
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            cur += ch
            esc = True
        elif ch == "|":
            cells.append(cur.strip())
            cur = ""
        else:
            cur += ch
    cells.append(cur.strip())
    return cells


def table_blocks(doc):
    """[(header_cells, [(line_no, cells)])]，跳过 fenced 代码块。"""
    blocks, cur, fence = [], None, None
    for i, raw in enumerate(doc.lines, 1):
        line = raw.rstrip("\r")
        m = re.match(r"^( {0,3})(`{3,}|~{3,})", line)
        if m:
            if fence is None:
                fence = (m.group(2)[0], len(m.group(2)))
            elif m.group(2)[0] == fence[0] and len(m.group(2)) >= fence[1]:
                fence = None
            continue
        if fence is not None:
            continue
        if line.strip().startswith("|") and line.count("|") >= 2:
            if re.match(r"^\s*\|?[\s:|-]+\|?\s*$", line) and cur is not None:
                continue
            cells = split_row(line)
            if cur is None:
                cur = {"header": cells, "rows": []}
                blocks.append(cur)
            else:
                cur["rows"].append((i, cells))
        else:
            cur = None
    return [(b["header"], b["rows"]) for b in blocks]


def check_structure(files, rep: Report, loose: bool):
    for role, label in (("baseline", "00 基线"), ("dashboard", "05 进度仪表盘")):
        if files.get(role):
            rep.add(OK, "必需文件", "%s：%s" % (label, files[role][0].name))
        else:
            rep.add(WARN if loose else ERR, "必需文件", "缺少 %s" % label)
    for role, label in (("log", "06 流水/日志"), ("archive", "90 归档")):
        if files.get(role):
            rep.add(OK, "必需文件", "%s：%s" % (label, files[role][0].name))
        else:
            rep.add(WARN, "必需文件", "缺少 %s" % label)


def check_sizes(root: Path, rep: Report, files):
    """体积统计：正文（非归档）与归档分开记，避免备份把「接手成本」算糊。"""
    main, archive, excluded = [], [], []
    for p, reason in scope.iter_text_files(root, include_archive=True):
        if reason:
            excluded.append((p, reason))
            continue
        size = p.stat().st_size
        rel = p.relative_to(root).as_posix()
        parents = rel.split("/")[:-1]
        if any(scope.is_archive_dir(part) for part in parents) \
                or protocol.role_of_name(p.name, loose=True) == "archive":
            archive.append((p, size))
        else:
            main.append((p, size))
    total = sum(s for _, s in main)
    arch = sum(s for _, s in archive)
    physical = sum(p.stat().st_size for p in root.rglob("*")
                   if p.is_file() and ".git" not in p.parts)
    core = sum(p.stat().st_size for role in ("baseline", "dashboard")
               for p in files.get(role, []))
    rep.stats.update({"physical_bytes": physical, "searchable_bytes": total,
                      "archive_bytes": arch, "searchable_files": len(main),
                      "archive_files": len(archive),
                      "excluded_files": len(excluded), "core_bytes": core,
                      "core_ratio": round(core / total, 4) if total else 0.0})
    rep.add(OK, "接手成本",
            "%d B / 正文 %d B = %.1f%%（≈%.1f k tokens，估算）"
            % (core, total, (core / total * 100) if total else 0, core / 4500))
    if archive:
        rep.add(OK, "体积分层", "归档 %d B / %d 份（不计入接手成本，检索默认跳过）"
                % (arch, len(archive)))
        if total and arch > 3 * total:
            rep.add(WARN, "体积分层",
                    "归档是正文的 %.1f 倍（%d B vs %d B）——备份留太多，建议按主题折叠"
                    % (arch / total, arch, total))
    if excluded:
        rep.add(OK, "体积排除", "已跳过 %d 个数据产物/超限文件（不计入正文）" % len(excluded))
    if total > 50 * 1024 and core / total > 0.35:
        rep.add(WARN, "接手成本", "必读集合占正文 %.0f%%（>35%%，必读太大或库太小）"
                % (core / total * 100))
    return main, archive


def check_dashboard(files, rep: Report):
    if not files.get("dashboard"):
        return
    p = files["dashboard"][0]
    doc = md.parse_file(p)
    if doc.duplicate_ids:
        rep.add(ERR, "章节 ID", "重复 kb:id：%s" % ", ".join(sorted(set(doc.duplicate_ids))), p)

    def by_id(sid):
        return md.find_by_id(doc, sid)

    cur = by_id("dashboard.current")
    if cur:
        body, _ = md.render(doc, cur, include_children=False)
        n = len([x for x in body.splitlines() if x.strip()])
        rep.add(OK if n <= 4 else WARN, "05 现状",
                "%d 行（阈值 ≤4）%s" % (n, "" if n <= 4 else "，压缩后细节进流水"), p, cur.line)
    else:
        rep.add(WARN, "05 现状", "缺少 kb:id: dashboard.current（无法按 ID 定位现状）", p)
    if not by_id("dashboard.next"):
        rep.add(WARN, "05 下一手", "缺少 kb:id: dashboard.next（新会话不知道下一步做什么）", p)
    if not (by_id("dashboard.constraints") or by_id("dashboard.safety")):
        rep.add(WARN, "05 硬约束", "缺少 kb:id: dashboard.constraints（预算裁剪时无安全上下文）", p)

    summ = by_id("dashboard.summary")
    if summ:
        body, _ = md.render(doc, summ, include_children=False)
        items = [x for x in body.splitlines() if x.strip().startswith(("-", "*"))]
        over = len(items) > 5
        rep.add(OK if not over else WARN, "05 最近记录",
                "%d 条（阈值 ≤5）" % len(items), p, summ.line)


def check_thresholds(root: Path, files, rep: Report, loose: bool = False):
    for role, label, limit in (("baseline", "00 基线规模", 150), ("archive", "90 归档规模", 600)):
        if not files.get(role):
            continue
        p = files[role][0]
        n = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
        rep.add(OK if n <= limit else WARN, label, "%d 行（阈值 ≤%d）" % (n, limit), p)
    shards = find_shards(root, loose)
    if shards:
        worst = ("", 0)
        for p in shards:
            n = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
            size = p.stat().st_size
            if n > 200 or size > 60 * 1024:
                rep.add(WARN, "流水轮转", "分片 %s 触线（%d 行 / %d B，阈值 200 行 / 60 KB）"
                        % (p.name, n, size), p)
            if n > worst[1]:
                worst = (p.name, n)
        rep.add(OK, "06 流水分片", "%d 个分片，最大 %s %d 行（按单分片判）"
                % (len(shards), worst[0], worst[1]))
    facts = find_facts(files)
    if len(facts) > protocol.MAX_LINES:
        rep.add(WARN, "事实层数量", "%d 册（阈值 ≤%d，按领域合并）"
                % (len(facts), protocol.MAX_LINES))


def check_todo_and_secrets(searchable, rep: Report):
    todo, secrets_hit = [], []
    for p, _ in searchable:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r"\b(TODO|FIXME)\b", line):
                todo.append((p, i))
        for label, lineno, _ in security.scan_text(text):
            secrets_hit.append((p, label, lineno))
    rep.add(OK if not todo else WARN, "残留 TODO",
            "%d 处 TODO/FIXME" % len(todo) + ("：" + ", ".join(
                "%s:%d" % (p.name, i) for p, i in todo[:5]) if todo else ""))
    if secrets_hit:
        for p, label, lineno in secrets_hit[:10]:
            rep.add(ERR, "明文凭证", "%s 第 %d 行命中「%s」——先处理再提交"
                    % (p.name, lineno, label), p, lineno)
        rep.stats["secrets"] = len(secrets_hit)
    else:
        rep.add(OK, "明文凭证", "0 处")


DEF_HEADING_RE = re.compile(r"^#{1,6}\s*[`*\s]*([KG]-\d{2,3})\b")
DEF_BULLET_RE = re.compile(r"^[-*+]\s*[`*\s]*([KG]-\d{2,3})\b")
DEF_TABLE_RE = re.compile(r"^\|\s*[`*\s]*([KG]-\d{2,3})\s*\|")


def def_id_at(line: str):
    """判断这一行是否在「定义位」上写了个 ID：标题首 / 列表首 / 表格首列。"""
    for rx in (DEF_HEADING_RE, DEF_BULLET_RE, DEF_TABLE_RE):
        m = rx.match(line)
        if m:
            return m.group(1)
    return None


def iter_code_aware(doc):
    """产出 (行号, 行文本, 是否在围栏内)。"""
    fence = None
    for i, raw in enumerate(doc.lines, 1):
        line = raw.rstrip("\r")
        m = re.match(r"^( {0,3})(`{3,}|~{3,})", line)
        if m:
            if fence is None:
                fence = (m.group(2)[0], len(m.group(2)))
            elif m.group(2)[0] == fence[0] and len(m.group(2)) >= fence[1]:
                fence = None
            yield i, line, True
            continue
        yield i, line, fence is not None


def check_ids(root: Path, searchable, rep: Report, loose: bool = False):
    """编号契约检查（统一走 lib/facts.py，三种定义形式一致）。"""
    defs: dict[str, list] = {}
    refs: dict[str, list] = {}
    parsed, failed = 0, []
    for p, _ in searchable:
        rel = p.relative_to(root).as_posix()
        try:
            dlist, rlist = facts.parse_document(p, rel)
        except Exception as exc:
            # 解析失败必须可见：早先这里 continue 掉，于是「一个文件读坏了」
            # 会表现成「那个文件里的事实全部合格」。
            failed.append((rel, str(exc)))
            continue
        parsed += 1
        for d in dlist:
            defs.setdefault(d.id, []).append(d)
        for r in rlist:
            refs.setdefault(r.id, []).append(r)

    if failed:
        rep.add(WARN if loose else ERR, "事实解析",
                "%d 个文件解析失败，其中的事实**未被检查**：%s"
                % (len(failed), "; ".join("%s（%s）" % (a, b[:60]) for a, b in failed[:3])))

    # 1) 重复定义：跨文件也报，列出全部位置。索引页里的条目算指针，不报重复
    dup = facts.duplicates(defs)
    for fid, items in sorted(dup.items())[:10]:
        locs = ", ".join("%s:%d" % (d.path, d.line_start) for d in items[:4])
        rep.add(ERR, "编号契约", "ID 重复定义：%s（%d 处：%s）"
                % (fid, len(items), locs))
    ptr = facts.pointer_only(defs)
    if ptr:
        first = sorted(ptr)[0]
        rep.add(WARN, "编号契约",
                "索引页里有 %d 条指向定义（如 %s 见 %s:%d）：按指针处理，不算重复"
                % (len(ptr), first, ptr[first][0].path, ptr[first][0].line_start))
    # 2) 未定义引用
    undefined = {k: v for k, v in refs.items() if k not in defs}
    for fid, where in sorted(undefined.items())[:10]:
        first = where[0]
        level = WARN if (loose or rep.mode == "template") else ERR
        rep.add(level, "编号引用", "引用未定义的 ID：%s（%d 处，首见 %s:%d）"
                % (fid, len(where), Path(first.path).name, first.line),
                root / first.path, first.line)

    # 3) 作废引用
    superseded = {k for k, v in defs.items()
                  if any(d.status == "deprecated" for d in v)}
    for fid, where in sorted({k: v for k, v in refs.items()
                              if k in superseded}.items())[:10]:
        first = where[0]
        rep.add(WARN, "作废引用", "引用了已作废的 %s（改用替代 ID）" % fid,
                root / first.path, first.line)

    # 4) 作废链循环
    for fid, items in defs.items():
        seen, cur = [], fid
        while cur in defs and len(seen) < 6:
            seen.append(cur)
            nxt = next((d.superseded_by for d in defs[cur] if d.superseded_by), None)
            cur = nxt
            if cur in seen:
                rep.add(ERR, "作废链", "循环引用：%s" % " → ".join(seen + [cur]))
                break

    if defs:
        rep.add(OK, "编号契约", "%d 个 K/G 编号定义、%d 处引用"
                % (len(defs), sum(len(v) for v in refs.values())))
    else:
        # 「没有事实可查」不能报成「全部通过」——那是最容易被当成健康的假绿灯
        rep.add(WARN, "编号契约",
                "没有发现任何事实定义：%d 个文件已扫描、%d 个解析失败。"
                "这不是「全部通过」，请先确认事实写法（标题首 / 列表首 / 表格首列）"
                % (parsed, len(failed)))

    # 统计口径：定义数 / 成功解析 / 有问题 / 待核 / 跳过，一眼看出「查了没有」
    meta_problems = ["%s:%d %s" % (d.path, d.line_start, d.meta_error)
                     for items in defs.values() for d in items if d.meta_error]
    stat = facts.counts(defs, meta_problems)
    stat["files_scanned"] = parsed
    stat["files_failed"] = len(failed)
    rep.add(OK if defs and not meta_problems else WARN, "事实统计",
            "定义 %d（规范 %d / 索引指针 %d）｜有效 %d / 待核 %d / 作废 %d / 未知 %d｜"
            "ID %d｜重复 %d｜文件 %d 解析成功 %d 失败｜元数据问题 %d"
            % (stat["definitions"], stat["canonical"], stat["pointers"],
               stat["valid"], stat["pending"], stat["deprecated"], stat["unknown"],
               stat["ids"], stat["duplicated_ids"],
               stat["files_scanned"] + stat["files_failed"], stat["files_failed"],
               stat["problems"]))

    # 5) 元数据问题（解析失败 / 状态无法识别 / 作废没写替代）
    meta_bad = []
    for fid, items in defs.items():
        for d in items:
            if d.meta_error or (d.status == "unknown" and d.definition_type == "table") \
                    or (d.status == "deprecated" and not d.superseded_by):
                meta_bad.append(d)
    if meta_bad:
        rep.add(WARN, "事实元数据", "%d 处事实元数据有问题：%s"
                % (len(meta_bad), ", ".join("%s(%s)" % (d.id, d.definition_type)
                                            for d in meta_bad[:5])),
                root / meta_bad[0].path, meta_bad[0].line_start)

    # 6) 证据：有效但没证据
    missing_ev = [d for items in defs.values() for d in items
                  if d.status == "valid" and d.evidence in ("", "—", "-", "无")]
    if rep.mode == "template":
        rep.add(OK, "事实证据", "模板未填写，跳过证据检查")
    elif missing_ev:
        rep.add(WARN, "事实证据", "%d 条「有效」事实没有证据：%s"
                % (len(missing_ev),
                   ", ".join("%s(%s:%d)" % (d.id, Path(d.path).name, d.line_start)
                             for d in missing_ev[:5])),
                root / missing_ev[0].path, missing_ev[0].line_start)
    else:
        rep.add(OK, "事实证据", "有效事实均带证据或全为待核")

    # 7) 时效
    stale, today = [], datetime.date.today()
    for fid, items in defs.items():
        for d in items:
            m = re.search(r"\d{4}-\d{2}-\d{2}", d.verified_at or "")
            if not m:
                continue
            try:
                dt = datetime.date.fromisoformat(m.group(0))
            except ValueError:
                rep.add(WARN, "事实元数据", "%s 的核实时间不是合法日期：%s"
                        % (fid, d.verified_at), root / d.path, d.line_start)
                continue
            if (today - dt).days > rep.max_age_days:
                stale.append((fid, m.group(0)))
    if stale:
        rep.add(WARN, "事实过期", "%d 条事实核实时间超过 %d 天（仅告警）：%s"
                % (len(stale), rep.max_age_days,
                   ", ".join("%s@%s" % (a, b) for a, b in stale[:5])))
    else:
        rep.add(OK, "事实过期", "无超期事实（阈值 %d 天）" % rep.max_age_days)
    return defs


def check_section_ids(files, shards, rep: Report):
    seen, dup = {}, []
    for p in (files.get("dashboard", []) + files.get("baseline", []) +
              files.get("archive", []) + shards + [x[1] for x in find_facts(files)]):
        try:
            doc = md.parse_file(p)
        except Exception:
            continue
        for s in doc.sections:
            if not s.id:
                continue
            if not protocol.SECTION_ID_RE.match(s.id):
                rep.add(ERR, "章节 ID", "非法 kb:id：%r" % s.id, p, s.line)
            key = (p.name, s.id)
            if key in seen:
                dup.append("%s:%s" % (p.name, s.id))
            seen[key] = s.line
    if dup:
        rep.add(ERR, "章节 ID", "同一文件内重复：%s" % ", ".join(sorted(set(dup))[:5]))
    else:
        rep.add(OK, "章节 ID", "%d 个稳定章节 ID，无重复" % len(seen))


def check_tables(searchable, rep: Report):
    bad = []
    for p, _ in searchable:
        try:
            doc = md.parse_file(p)
        except Exception:
            continue
        for header, rows in table_blocks(doc):
            want = len(header)
            for lineno, cells in rows:
                if len(cells) != want:
                    bad.append((p.name, lineno, want, len(cells)))
    if bad:
        rep.add(WARN, "表格结构", "%d 行列数不一致：%s"
                % (len(bad), ", ".join("%s:%d(%d≠%d)" % b for b in bad[:5])))
    else:
        rep.add(OK, "表格结构", "全部表格块内列数一致")


def check_git(root: Path, rep: Report):
    r = sh(["git", "rev-parse", "--is-inside-work-tree"], root)
    if not r or r.returncode != 0:
        rep.add(WARN, "版本控制", "不是 git 仓库（并发改动无法 diff / 回滚）")
        return
    # 目标可能只是某个仓库的子目录：此时 `git status` 反映的是外层仓库，
    # 直接拿来报「未提交改动」会把别人的改动算到本项目头上（2.0.1 修正）。
    top = sh(["git", "rev-parse", "--show-toplevel"], root)
    top_path = (top.stdout or "").strip() if top else ""
    try:
        is_top = bool(top_path) and Path(top_path).resolve() == Path(root).resolve()
    except OSError:
        is_top = False
    if not is_top:
        rep.add(WARN, "版本控制", "目标不是仓库根（外层仓库：%s）；改动/提交统计已跳过"
                % (top_path or "未知"))
        return
    st = sh(["git", "status", "--porcelain"], root)
    dirty = [x for x in (st.stdout or "").splitlines() if x.strip()] if st else []
    rep.add(OK if not dirty else WARN, "未提交改动",
            "%d 个文件未提交" % len(dirty) + ("：" + ", ".join(
                x.strip()[:40] for x in dirty[:3]) if dirty else "，工作区干净"))
    lg = sh(["git", "log", "--oneline", "-5"], root)
    entries = [x for x in (lg.stdout or "").splitlines() if x.strip()] if lg else []
    rep.stats["commits"] = entries
    for e in entries[:5]:
        rep.add(OK, "commit", e)


def detect_mode(files, requested: str) -> str:
    if requested in ("template", "project"):
        return requested
    placeholders = 0
    for role in ("baseline", "dashboard"):
        for p in files.get(role, []):
            placeholders += p.read_text(encoding="utf-8", errors="replace").count("[填")
    return "template" if placeholders >= 15 else "project"


def main() -> int:
    ap = argparse.ArgumentParser(description="分层交接库只读体检（v2）")
    ap.add_argument("--target", default=".")
    ap.add_argument("--strict", action="store_true", help="WARN 也算失败")
    ap.add_argument("--loose", action="store_true",
                    help="自有命名体系：必需文件缺失降为 WARN，其余照跑")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--mode", choices=["auto", "template", "project"], default="auto")
    ap.add_argument("--max-age-days", type=int, default=90, help="事实核实过期阈值（天）")
    args = ap.parse_args()

    try:
        root = scope.resolve_root(args.target)
    except scope.ScopeError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 2

    files = role_files(root, args.loose)
    mode = detect_mode(files, args.mode)
    rep = Report(mode)
    rep.max_age_days = args.max_age_days

    check_structure(files, rep, args.loose)
    main, archive = check_sizes(root, rep, files)
    check_dashboard(files, rep)
    check_thresholds(root, files, rep, args.loose)
    check_todo_and_secrets(main + archive, rep)
    check_ids(root, main, rep, args.loose)
    check_section_ids(files, find_shards(root, args.loose), rep)
    check_tables(main, rep)
    check_git(root, rep)

    counts = rep.counts()
    if args.json:
        print(json.dumps({"target": str(root), "mode": mode, "counts": counts,
                          "stats": rep.stats, "findings": rep.findings},
                         ensure_ascii=False, indent=2))
    else:
        print("== 体检：%s（模式 %s）" % (root, mode))
        for f in rep.findings:
            loc = ""
            if f["path"]:
                loc = "  [%s%s]" % (Path(f["path"]).name,
                                    ":%d" % f["line"] if f["line"] else "")
            print("[%-4s] %-12s %s%s" % (f["level"], f["category"], f["message"], loc))
        print("\n== 汇总：OK %d / WARN %d / ERR %d" % (counts[OK], counts[WARN], counts[ERR]))
        print("== 正文 %d B（%d 份）/ 归档 %d B（%d 份）/ 物理总量 %d B"
              % (rep.stats.get("searchable_bytes", 0), rep.stats.get("searchable_files", 0),
                 rep.stats.get("archive_bytes", 0), rep.stats.get("archive_files", 0),
                 rep.stats.get("physical_bytes", 0)))
        print("== 参与检索 ≈%.1f k tokens（估算，不含数据产物）"
              % (rep.stats.get("searchable_bytes", 0) / 4500))
        print("== tokenizer：%s" % tokens.estimate("", "heuristic")[1])

    if counts[ERR] > 0:
        return 1
    if args.strict and counts[WARN] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
