#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-benchmark.py — Token 与接手质量评测（可复现，无网络）

三种读法对比（同一任务）：
  A 全量：把库里所有参与检索的文本当上下文
  B 旧法：只读 00 + 05
  C 新版：kb-context.py 按预算路由

质量门分两级（2.0.1-hotfix）：
  **必须 100% 通过** —— 硬约束保留、错误路径拒绝、预算如实、工作线无静默遗漏、
  计数器口径一致。任何一项掉一条就是硬失败，不接受「被平均值抹平」。
  **只报告不设 100%** —— 目标章节/事实命中率、证据覆盖、P4 噪声比、归档隔离。
  找不到事实时「明确报缺口」是正确结果，不能为了命中率返回不相关内容。

统计口径：
  - 均值只统计**正常任务**，错误路径单列，不拉低 token 均值
  - 所有 token 都走同一个 TokenCounter（A/B/C 同口径）
  - 多工作线召回分三类：完整召回 / 部分召回并报告 / 静默遗漏
  - 命中判定按**事实 ID / 章节 ID**，不做「全文含某个词」的宽泛包含

用法：
  py kb-benchmark.py --target . --report markdown
  py kb-benchmark.py --target . --report json --budget 3000
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import facts  # noqa: E402
from lib import markdown as md  # noqa: E402
from lib import protocol, scope, tokens  # noqa: E402

HERE = Path(__file__).resolve().parent

# 硬门槛：这些项必须 100% 通过
GATE_MUST_PASS = ("constraint_kept", "error_rejected", "budget_honest",
                  "lines_honest", "tokenizer_consistent")


def count_duplicates(blocks) -> dict:
    """重复装载分两种，分开报，不互相掩盖：

    - exact：同一个 (source_path, section_id, 正文) 进了两次——装配层没去重，
      读者看到同一节被念两遍，还白占预算。
    - cross：正文相同但位置不同——通常是「同一文件被两条路径读到」（软链、
      同名副本），或容器节兜底又把子节整个装了一遍。

    同一节按不同用途拆成多块（例如 baseline.facts 的「命中行」与「证据指针」）
    不算重复：位置相同、正文不同，是补足信息，不是念第二遍。点名事实（P3）
    没有 section_id，不能拿 None 互相比，否则一句「K-01」和「K-02」会被判重。
    """
    stamps, owners, exact, cross = set(), {}, 0, 0
    for b in blocks:
        # blocks 的 JSON 不带正文，只有 text_sha；旧版输出没有该字段就跳过内容比较。
        sha = b.get("text_sha")
        if not sha:
            continue
        key = (b.get("source_path"), b.get("section_id"))
        if key[1]:
            stamp = key + (sha,)
            if stamp in stamps:
                exact += 1
                continue
            stamps.add(stamp)
        if sha in owners and owners[sha] != key:
            cross += 1
        owners.setdefault(sha, key)
    return {"exact": exact, "cross": cross}


def describe_duplicates(blocks) -> dict:
    """「同节多片」是设计（一节按用途拆多块），单列出来免得被误读成重复。"""
    groups = {}
    for b in blocks:
        key = (b.get("source_path"), b.get("section_id"))
        sha = b.get("text_sha")
        if key[1] and sha:
            groups.setdefault(key, set()).add(sha)
    multi = sum(1 for texts in groups.values() if len(texts) > 1)
    return dict(count_duplicates(blocks), split_section=multi)


METRIC_KEYS = (
    ("section_hit", "目标章节命中"),
    ("fact_hit", "目标事实命中（含状态判定）"),
    ("constraint_kept", "硬约束保留"),
    ("gap_honest", "缺口如实报告"),
    ("budget_honest", "预算如实（不谎报）"),
    ("tokenizer_consistent", "计数器口径一致"),
    ("error_rejected", "错误路径被拒绝"),
    ("lines_honest", "工作线无静默遗漏"),
    ("archive_excluded", "归档未混入默认上下文"),
    ("p4_bounded", "P4 受数量与预算约束"),
)


def min_passes(total: int) -> int:
    """80% 门槛下必须通过的任务条数——**向上取整**。

    round() 会把 8 个任务的 6.4 抹成 6：6/8 = 75%，「80% 门槛」名不副实。
    用整数运算而不是 math.ceil(total * 0.8)：0.8 在二进制里不精确，
    15 * 0.8 = 12.000000000000002，ceil 会给出 13。
    """
    return max(1, (total * 4 + 4) // 5)


def run_json(script, args):
    p = subprocess.run([sys.executable, str(HERE / script)] + args,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return json.loads(p.stdout), p.returncode, p.stderr
    except Exception:
        return {"_stdout": p.stdout, "_stderr": p.stderr}, p.returncode, p.stderr


def corpus_tokens(root: Path, counter):
    total = 0
    files = []
    for p, reason in scope.iter_text_files(root, include_archive=True):
        if reason:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n = counter.count(text)
        total += n
        files.append((p.relative_to(root).as_posix(), n))
    return total, files


def pick_facts(root: Path, loose: bool) -> dict:
    """按状态挑出可用于评测的事实 ID。没有对应状态的任务会被标为「跳过」。"""
    defs, _ = facts.parse_fact_definitions(root, loose=loose)
    out = {"valid": [], "pending": [], "deprecated": [], "total": len(defs)}
    for fid in sorted(defs):
        items = defs[fid]
        for bucket in ("valid", "pending", "deprecated"):
            if any(d.status == bucket for d in items):
                out[bucket].append(fid)
    return out


def build_tasks(files, picked: dict):
    names = []
    for p in files.get("fact", []):
        names.append(p.stem.split("_", 1)[1] if "_" in p.stem else p.stem)
    l1 = names[0] if names else "线A"
    l2 = names[1] if len(names) > 1 else l1
    valid = picked["valid"][0] if picked["valid"] else None
    pending = picked["pending"][0] if picked["pending"] else None
    dead = picked["deprecated"][0] if picked["deprecated"] else None
    tasks = [
        {"id": 1, "title": "查看当前项目状态", "task": "查看当前项目状态",
         "expect": ("section_id", "dashboard.current")},
        {"id": 2, "title": "单工作线排障", "task": "排查%s的问题" % l1,
         "expect": ("section_id", "fact.pitfalls"), "line": l1},
        {"id": 3, "title": "跨工作线依赖", "task": "改%s会影响%s吗" % (l1, l2),
         "expect": ("section_id", "baseline.chains")},
        {"id": 4, "title": "按 ID 定位事实", "task": "%s 的当前值是什么" % (valid or "K-01"),
         "expect": ("fact", valid), "skip": None if valid else "库里没有「有效」事实"},
        {"id": 5, "title": "作废事实要指向替代",
         "task": "%s 现在还算数吗" % (dead or "K-03"),
         "expect": ("fact_status", (dead, ("已作废", "作废", "deprecated"))),
         "skip": None if dead else "库里没有「已作废」事实"},
        {"id": 6, "title": "待核事实要标待核",
         "task": "%s 核实过了吗" % (pending or "K-02"),
         "expect": ("fact_status", (pending, ("待核", "pending"))),
         "skip": None if pending else "库里没有「待核」事实"},
        {"id": 7, "title": "模糊任务要如实报缺口", "task": "哪些事实需要重新核实",
         "expect": ("gap", "")},
        {"id": 8, "title": "无检索命中", "task": "zzz-nonexistent-topic-qqq",
         "expect": ("gap", "")},
        {"id": 9, "title": "错误项目路径", "task": "查看现状", "expect": ("exit2", "")},
        {"id": 10, "title": "多工作线召回", "task": "改%s会影响%s吗" % (l1, l2),
         "expect": ("lines", [l1, l2]), "skip": None if len(names) >= 2 else "只有一条工作线"},
    ]
    return tasks


def archive_relpaths(root: Path, loose: bool, files) -> set:
    """默认上下文里不该出现的归档来源。

    只认根层归档文件（90_*.md / *归档*.md）与根层归档目录下的文件。
    早先按「任意深层的父目录名像归档」统计，会把备份目录里的同名文件也算进来，
    于是正常块被误判成「归档混入」（真实项目上直接误报 5/9）。
    """
    return {p.name for p in files.get("archive", [])}


def is_unmigrated(files) -> bool:
    """库是否还没有任何 kb:id（v1）。未迁移时按章节路由无法验证。"""
    for role in ("dashboard", "baseline"):
        for p in files.get(role, []):
            try:
                doc = md.parse_file(p)
            except Exception:
                continue
            if any(sec.id for sec in doc.sections):
                return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Token 与质量评测")
    ap.add_argument("--target", default=".")
    ap.add_argument("--budget", type=int, default=3000)
    ap.add_argument("--report", choices=["markdown", "json"], default="markdown")
    ap.add_argument("--tokenizer", default="heuristic")
    ap.add_argument("--allow-tokenizer-fallback", action="store_true")
    ap.add_argument("--loose", action="store_true", help="按别名识别固定层（自有命名项目）")
    args = ap.parse_args()

    try:
        root = scope.resolve_root(args.target)
    except scope.ScopeError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 2
    if args.budget <= 0:
        print("ERR: --budget 必须为正", file=sys.stderr)
        return 2

    try:
        counter = tokens.TokenCounter(args.tokenizer, args.allow_tokenizer_fallback)
    except tokens.TokenizerError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 2

    files = scope.role_files(root, loose=args.loose)
    if not files.get("dashboard"):
        print("ERR: 目标不像交接库（没有 05/进度仪表盘）", file=sys.stderr)
        return 2

    a_tokens, per_file = corpus_tokens(root, counter)
    b_tokens = sum(counter.count(p.read_text(encoding="utf-8", errors="replace"))
                   for role in ("baseline", "dashboard") for p in files.get(role, []))
    tok_desc = counter.desc

    ctx_args = ["--tokenizer", args.tokenizer]
    if args.allow_tokenizer_fallback:
        ctx_args.append("--allow-tokenizer-fallback")
    if args.loose:
        ctx_args.append("--loose")

    archive_names = archive_relpaths(root, args.loose, files)
    unmigrated = is_unmigrated(files)
    picked = pick_facts(root, args.loose)
    rows, metrics = [], {k: {"passed": 0, "total": 0} for k, _ in METRIC_KEYS}
    recall = {"full": 0, "partial": 0, "silent": 0}

    def mark(key, ok, counted=True):
        if not counted:
            return
        metrics[key]["total"] += 1
        metrics[key]["passed"] += 1 if ok else 0

    tasks = build_tasks(files, picked)
    for t in tasks:
        kind, want = t["expect"]
        started = time.time()
        if kind == "exit2":
            _payload, code, err = run_json(
                "kb-context.py", ["--target", str(root / "__no_such_dir__"),
                                  "--task", t["task"], "--format", "json"] + ctx_args)
            ok = code == 2 and "ERR" in (err or "")
            mark("error_rejected", ok)
            rows.append({"id": t["id"], "title": t["title"], "task": t["task"], "a": 0, "b": b_tokens,
                         "c": 0, "noise": 0.0, "dup_x": 0, "dup_c": 0, "split": 0, "blocks": 0,
                         "counted": False, "graded": True,
                         "quality": "拒绝错误路径" if ok else "未拒绝",
                         "pass": ok, "ms": int((time.time() - started) * 1000)})
            continue

        if t.get("skip"):
            rows.append({"id": t["id"], "title": t["title"], "task": t["task"], "a": a_tokens,
                         "b": b_tokens, "c": 0, "noise": 0.0, "dup_x": 0, "dup_c": 0, "split": 0, "blocks": 0,
                         "counted": False, "graded": False,
                         "quality": "跳过：%s" % t["skip"], "pass": False, "ms": 0})
            continue

        if kind == "section_id" and unmigrated:
            rows.append({"id": t["id"], "title": t["title"], "task": t["task"], "a": a_tokens,
                         "b": b_tokens, "c": 0, "noise": 0.0, "dup_x": 0, "dup_c": 0, "split": 0, "blocks": 0,
                         "counted": False, "graded": False,
                         "quality": "跳过：未迁移库没有 kb:id",
                         "pass": False, "ms": 0})
            continue

        payload, code, _err = run_json(
            "kb-context.py", ["--target", str(root), "--task", t["task"],
                              "--budget", str(args.budget), "--format", "json"] + ctx_args)
        blocks = payload.get("blocks", [])
        ids = [b.get("section_id") for b in blocks]
        titles = " ".join(b.get("title") or "" for b in blocks)
        gaps = " ".join(payload.get("gaps", []))
        text_all = json.dumps(payload.get("context", {}), ensure_ascii=False) + " " + gaps
        sources = [b.get("source") for b in blocks]
        constraint = any(b.get("priority") == "P0" for b in blocks)
        used = payload.get("used", 0)
        selected = payload.get("selected_lines") or []
        omitted = payload.get("omitted_lines") or []

        lines_marked = False
        if kind == "section_id":
            ok = want in ids and constraint
            label = "命中 %s" % want if ok else "未命中 %s" % want
            mark("section_hit", want in ids)
        elif kind == "fact":
            hit = want in titles or want in text_all
            ok = hit and constraint
            label = "命中事实 %s" % want if ok else "未命中事实 %s" % want
            mark("fact_hit", hit)
        elif kind == "fact_status":
            fid, words = want
            hit = fid in text_all and any(w in text_all for w in words)
            ok = hit and constraint
            if ok:
                label = "按状态报告 %s" % fid
            elif fid not in text_all:
                label = "完全没提到 %s" % fid
            else:
                label = "提到 %s 但没给出状态" % fid
            mark("fact_hit", hit)
        elif kind == "lines":
            missing = [n for n in want if n not in selected]
            silent = [n for n in missing if ("工作线「%s」" % n) not in gaps]
            partial = [n for n in missing if n not in silent]
            if not missing:
                recall["full"] += 1
                label = "两条线都加载"
            elif silent:
                recall["silent"] += 1
                label = "静默遗漏：%s" % "、".join(silent)
            else:
                recall["partial"] += 1
                label = "部分召回并如实报告（%s）" % "、".join(partial)
            ok = not silent and constraint
            mark("lines_honest", not silent)
            lines_marked = True
        else:  # gap：这类任务本来就该「没有命中但如实报缺口」
            ok = bool(gaps) and constraint
            if ok:
                label = "如实报缺口"
            elif not gaps:
                label = "没报缺口"
            else:
                label = "报了缺口，但硬约束丢失"
            mark("gap_honest", bool(gaps))

        mark("constraint_kept", constraint)
        # 预算如实：数值不超预算，或超了就必须自己说「超了」（不能悄悄截断还是报成功）
        actual_over = used > args.budget
        budget_ok = bool(payload.get("over_budget")) == actual_over
        mark("budget_honest", budget_ok)
        mark("tokenizer_consistent",
             payload.get("requested") == args.tokenizer
             and payload.get("exact") == counter.exact)
        lines_ok = not (set(selected) & set(omitted))
        if omitted:
            lines_ok = lines_ok and all(("工作线「%s」" % n) in gaps for n in omitted)
        if not lines_marked:
            mark("lines_honest", lines_ok)
        mark("archive_excluded", not (set(sources) & archive_names))
        p4 = payload.get("p4") or {}
        p4_ok = (p4.get("count", 0) <= 3
                 and p4.get("tokens", 0) <= int(args.budget * 0.30))
        mark("p4_bounded", p4_ok)
        noise = round(p4.get("tokens", 0) / used, 3) if used else 0.0
        dups = describe_duplicates(blocks)

        rows.append({"id": t["id"], "title": t["title"], "task": t["task"], "a": a_tokens, "b": b_tokens,
                     "c": used, "noise": noise, "dup_x": dups["exact"], "dup_c": dups["cross"],
                     "split": dups["split_section"], "blocks": len(blocks),
                     "counted": True, "graded": True,
                     "quality": label if budget_ok else label + "（预算口径不一致）",
                     "pass": ok and budget_ok, "ms": int((time.time() - started) * 1000)})

    counted = [r for r in rows if r["counted"]]
    errors = [r for r in rows if not r["counted"] and r["graded"]]
    graded = [r for r in rows if r["graded"]]
    mean_c = sum(r["c"] for r in counted) / len(counted) if counted else 0
    red_a = (1 - mean_c / a_tokens) if a_tokens else 0
    red_b = (1 - mean_c / b_tokens) if b_tokens else 0
    passes = sum(1 for r in graded if r["pass"])
    total_metrics = sum(m["total"] for m in metrics.values())
    passed_metrics = sum(m["passed"] for m in metrics.values())
    rate = round(passed_metrics / total_metrics, 3) if total_metrics else 0.0
    # 关键项不接受「被平均值抹平」：硬约束丢失、错误路径被放行、预算口径不一致、
    # 工作线静默遗漏、计数器口径不一致，都是硬失败。
    hard_ok = all(metrics[k]["total"] and metrics[k]["passed"] == metrics[k]["total"]
                  for k in GATE_MUST_PASS)
    dup_exact = sum(r.get("dup_x", 0) for r in counted)
    dup_cross = sum(r.get("dup_c", 0) for r in counted)
    split_sections = sum(r.get("split", 0) for r in counted)
    all_blocks = sum(r.get("blocks", 0) for r in counted)
    need = min_passes(len(graded))
    gate_ok = passes >= need and rate >= 0.8 and hard_ok

    result = {
        "target": str(root), "budget": args.budget, "tokenizer": tok_desc,
        "exact": counter.exact, "loose": args.loose, "unmigrated": unmigrated,
        "tokens": {"A_all": a_tokens, "B_00_05": b_tokens, "C_mean": round(mean_c, 1),
                   "C_error_paths": len(errors)},
        "reduction_vs_A": round(red_a, 3),
        "reduction_vs_B": round(red_b, 3),
        "quality": {"passed": passes, "total": len(graded),
                    "rate": round(passes / len(graded), 3) if graded else 0.0},
        "metrics": {k: {"label": label, "passed": metrics[k]["passed"],
                        "total": metrics[k]["total"]} for k, label in METRIC_KEYS},
        "metrics_rate": rate,
        "recall": recall,
        "duplicates": {"exact": dup_exact, "cross": dup_cross,
                       "split_sections": split_sections, "blocks": all_blocks},
        "facts_seen": picked,
        "gate": {"min_rate": 0.8, "min_passes": need,
                 "must_pass": list(GATE_MUST_PASS),
                 "hard_ok": hard_ok, "passed": gate_ok},
        "rows": rows,
        "files": [{"path": p, "tokens": n} for p, n in per_file],
        "notes": [
            "A/B/C 用同一个 TokenCounter（%s），口径一致" % tok_desc,
            "A=全部参与检索文本，B=00+05，C=单次任务上下文；三者统计范围不同",
            "C 均值只统计 %d 个正常任务；%d 个错误路径单列，不参与均值" % (len(counted), len(errors)),
            "可评任务 %d 个（未迁移库的 section 类任务、缺少对应事实的任务会标跳过）"
            % len(graded),
            "硬门槛（必须 100%%）：%s" % "、".join(GATE_MUST_PASS),
            "命中判定按章节 ID / 事实 ID 与其状态，不做「全文含某个词」的宽泛包含",
            "多工作线：完整召回 %d、部分召回并报告 %d、静默遗漏 %d"
            % (recall["full"], recall["partial"], recall["silent"]),
            "重复装载：同节同文 %d 次、异节同文 %d 次（共 %d 块）；只报告，不计入门槛"
            % (dup_exact, dup_cross, all_blocks),
            "同节多片 %d 处是设计（一节按用途拆多块，如命中行 + 证据指针），不算重复"
            % split_sections,
        ],
    }

    if args.report == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if gate_ok else 1

    print("# handoff-kb benchmark — %s" % root)
    print("")
    print("| 指标 | 值 |")
    print("|---|---|")
    print("| A 全量上下文 | %d tokens |" % a_tokens)
    print("| B 旧法（00+05） | %d tokens |" % b_tokens)
    print("| C 新版（均值，预算 %d，%d 个任务） | %.0f tokens |"
          % (args.budget, len(counted), mean_c))
    print("| C 相对 A 降幅 | %.1f%% |" % (red_a * 100))
    print("| C 相对 B 降幅 | %+.1f%% |" % (red_b * 100))
    print("| 任务通过 | %d/%d（可评） |" % (passes, len(graded)))
    print("| 质量项通过 | %d/%d（%.0f%%） |"
          % (passed_metrics, total_metrics, result["metrics_rate"] * 100))
    print("| 工作线召回 | 完整 %d / 部分 %d / 静默 %d |"
          % (recall["full"], recall["partial"], recall["silent"]))
    print("| 重复装载 | 同节同文 %d / 异节同文 %d（共 %d 块；同节多片 %d 处不算重复） |"
          % (dup_exact, dup_cross, all_blocks, split_sections))
    print("| tokenizer | %s |" % tok_desc)
    print("")
    print("| # | 任务 | A | B | C | P4 噪声比 | 质量 | ms |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        print("| %d | %s | %s | %d | %s | %.2f | %s | %d |"
              % (r["id"], r["title"], "-" if not r["counted"] else str(r["a"]),
                 r["b"], "-" if not r["counted"] else str(r["c"]),
                 r["noise"], r["quality"], r["ms"]))
    print("")
    print("| 质量项 | 通过 | 门槛 |")
    print("|---|---|---|")
    for key, label in METRIC_KEYS:
        m = metrics[key]
        print("| %s | %d/%d | %s |"
              % (label, m["passed"], m["total"],
                 "必须 100%" if key in GATE_MUST_PASS else "仅报告"))
    print("")
    print("> A/B/C 同口径（%s）；三者统计范围不同，别把降幅当成 API 账单对比。" % tok_desc)
    print("> 主看「相对 A」：A 才是「全读」的真实成本。相对 B 只在小库上为负，"
          "因为 C 含包装（标题/来源/理由/缺口），B 只有 00+05 原文。")
    print("> 错误路径（%d 个）单列，不参与 token 均值。" % len(errors))
    if not gate_ok:
        print("> **未过质量门**：任务通过 %d/%d（需 ≥%d）、质量项 %.0f%%（需 ≥80%%）、"
              "关键项 %s" % (passes, len(graded), need, rate * 100,
                             "全部通过" if hard_ok else "未全通过"))
    if unmigrated:
        print("> 这个库还没有 kb:id（v1）：按章节路由无法验证，"
              "先跑 `kb-migrate.py --plan` 再评测才有意义。")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    sys.exit(main())
