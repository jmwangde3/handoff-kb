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
    """{role: [paths]}；固定文件优先精确命名，绝不用 `05_*.md` 这类通配。"""
    roles = {}
    if not root.is_dir():
        return roles
    for p in sorted(root.iterdir()):
        if not p.is_file() or p.suffix.lower() not in protocol.TEXT_EXTS:
            continue
        role = protocol.role_of_name(p.name, loose=loose)
        roles.setdefault(role, []).append(p)
    pref = {"baseline": protocol.CANON_BASELINE, "dashboard": protocol.CANON_DASHBOARD,
            "log": protocol.CANON_LOG, "archive": protocol.CANON_ARCHIVE}
    for role, names in pref.items():
        if role in roles and len(roles[role]) > 1:
            for want in names:
                for p in roles[role]:
                    if p.name == want:
                        roles[role] = [p]
                        break
    return roles


def find_shards(root: Path):
    d = root / protocol.SHARD_DIR
    return sorted(p for p in d.glob("*.md") if p.is_file()) if d.is_dir() else []


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
        if any(part.lower() in ("归档", "archive") for part in rel.split("/")[:-1]):
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


def check_thresholds(root: Path, files, rep: Report):
    for role, label, limit in (("baseline", "00 基线规模", 150), ("archive", "90 归档规模", 600)):
        if not files.get(role):
            continue
        p = files[role][0]
        n = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
        rep.add(OK if n <= limit else WARN, label, "%d 行（阈值 ≤%d）" % (n, limit), p)
    shards = find_shards(root)
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


def check_ids(files, shards, searchable, rep: Report, loose: bool = False):
    defs, rows = {}, []
    baseline = files.get("baseline", [None])[0]
    if baseline:
        doc = md.parse_file(baseline)
        for header, block in table_blocks(doc):
            id_col = next((i for i, h in enumerate(header)
                           if h.strip().upper() in ("ID", "编号")), None)
            if id_col is None:
                continue
            status_col = next((i for i, h in enumerate(header)
                               if "状态" in h or h.lower() == "status"), None)
            ev_col = next((i for i, h in enumerate(header)
                           if "证据" in h or "核实" in h or "evidence" in h.lower()), None)
            ver_col = next((i for i, h in enumerate(header)
                            if "时间" in h or "verified" in h.lower()), None)
            for lineno, cells in block:
                if len(cells) <= id_col:
                    continue
                fid = cells[id_col].strip()
                if not protocol.FACT_ID_RE.fullmatch(fid):
                    continue
                status = cells[status_col].strip() if status_col is not None and len(cells) > status_col else ""
                evidence = cells[ev_col].strip() if ev_col is not None and len(cells) > ev_col else ""
                verified = cells[ver_col].strip() if ver_col is not None and len(cells) > ver_col else ""
                if fid in defs:
                    rep.add(ERR, "编号契约", "ID 重复定义：%s（第 %d 与 %d 行）"
                            % (fid, defs[fid]["line"], lineno), baseline, lineno)
                defs[fid] = {"status": status, "evidence": evidence,
                             "verified_at": verified, "line": lineno}
                rows.append((fid, status, evidence, verified, lineno))

    refs = {}
    for p, _ in searchable:
        try:
            doc = md.parse_file(p)
        except Exception:
            continue
        for i, line, in_fence in iter_code_aware(doc):
            if in_fence:
                continue
            defined_here = def_id_at(line)
            for mid in protocol.FACT_ID_RE.finditer(line):
                fid = mid.group(1)
                if fid == defined_here:
                    # 定义位：标题首 / 列表首 / 表格首列，跨文件都算（自命名项目常见）
                    prev = defs.get(fid)
                    if prev and prev.get("line") and p == baseline:
                        continue
                    defs.setdefault(fid, {"status": "", "evidence": "",
                                          "verified_at": "", "line": i, "path": p})
                    continue
                refs.setdefault(fid, []).append((p, i))

    undefined = {k: v for k, v in refs.items() if k not in defs}
    for fid, where in sorted(undefined.items())[:10]:
        p, i = where[0]
        level = WARN if (loose or rep.mode == "template") else ERR
        rep.add(level, "编号引用",
                "引用未定义的 ID：%s（%d 处，首见 %s:%d）"
                % (fid, len(where), p.name, i), p, i)

    superseded = {k for k, v in defs.items()
                  if any(s in v["status"] for s in ("作废", "superseded"))}
    for fid, where in sorted({k: v for k, v in refs.items() if k in superseded}.items())[:10]:
        p, i = where[0]
        rep.add(WARN, "作废引用", "引用了已作废的 %s（改用替代 ID）" % fid, p, i)

    for fid in defs:
        seen, cur = [], fid
        while cur in defs and len(seen) < 6:
            seen.append(cur)
            m = re.search(r"→\s*([KG]-\d{2,3})", defs[cur]["status"])
            cur = m.group(1) if m else None
            if cur in seen:
                rep.add(ERR, "作废链", "循环引用：%s" % " → ".join(seen + [cur]))
                break

    rep.add(OK, "编号契约", "%d 个 K/G 编号定义、%d 处引用"
            % (len(defs), sum(len(v) for v in refs.values())))

    missing_ev = [(fid, ln) for fid, st, ev, ver, ln in rows
                  if any(s in st for s in ("有效", "valid")) and ev in ("", "—", "-", "无")]
    if rep.mode == "template":
        rep.add(OK, "事实证据", "模板未填写，跳过证据检查")
    elif missing_ev:
        rep.add(WARN, "事实证据", "%d 条「有效」事实没有证据：%s"
                % (len(missing_ev), ", ".join("%s(L%d)" % (a, b) for a, b in missing_ev[:5])),
                baseline)
    else:
        rep.add(OK, "事实证据", "有效事实均带证据或全为待核")

    stale, today = [], datetime.date.today()
    for fid, st, ev, ver, ln in rows:
        m = re.search(r"\d{4}-\d{2}-\d{2}", ver or "")
        if not m:
            continue
        try:
            d = datetime.date.fromisoformat(m.group(0))
        except ValueError:
            continue
        if (today - d).days > rep.max_age_days:
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
    check_thresholds(root, files, rep)
    check_todo_and_secrets(main + archive, rep)
    check_ids(files, find_shards(root), main, rep, args.loose)
    check_section_ids(files, find_shards(root), rep)
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
