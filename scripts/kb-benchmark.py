#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-benchmark.py — Token 与接手质量评测（可复现，无网络）

三种读法对比（同一任务）：
  A 全量：把库里所有参与检索的文本当上下文
  B 旧法：只读 00 + 05
  C 新版：kb-context.py 按预算路由

2.0.1 的统计修正（此前的数字不可复现，已重写）：
  - 均值只统计**正常任务**，错误路径单列，不拉低 token 均值
  - 所有 token 都走同一个 TokenCounter（A/B/C 同口径），不再混用 estimate
  - 质量判定改为 `(命中 或 报缺口) 且 硬约束在`，不再「只要约束在就算过」
  - 8 项质量指标逐项计数，避免用一个布尔值掩盖退化

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

from lib import markdown as md  # noqa: E402
from lib import protocol, scope, tokens  # noqa: E402

HERE = Path(__file__).resolve().parent

GATE_MUST_PASS = ("constraint_kept", "error_rejected")

METRIC_KEYS = (
    ("section_hit", "目标章节命中"),
    ("constraint_kept", "硬约束保留"),
    ("gap_honest", "缺口如实报告"),
    ("budget_respected", "预算被遵守"),
    ("tokenizer_consistent", "计数器口径一致"),
    ("error_rejected", "错误路径被拒绝"),
    ("lines_honest", "多工作线加载如实"),
    ("archive_excluded", "归档未混入默认上下文"),
)


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


def build_tasks(root: Path, files, loose: bool = False):
    facts = list(files.get("fact", []))
    names = []
    for p in facts:
        names.append(p.stem.split("_", 1)[1] if "_" in p.stem else p.stem)
    l1 = names[0] if names else "线A"
    l2 = names[1] if len(names) > 1 else l1
    return [
        {"id": 1, "title": "查看当前项目状态", "task": "查看当前项目状态",
         "expect": ("section_id", "dashboard.current")},
        {"id": 2, "title": "单工作线排障", "task": "排查%s的问题" % l1,
         "expect": ("section_id", "fact.pitfalls"), "line": l1},
        {"id": 3, "title": "跨工作线依赖", "task": "改%s会影响%s吗" % (l1, l2),
         "expect": ("section_id", "baseline.chains")},
        {"id": 4, "title": "查找某项事实", "task": "K-01 的当前值是什么",
         "expect": ("section_id", "baseline.facts")},
        {"id": 5, "title": "追踪证据", "task": "K-01 的证据在哪",
         "expect": ("section_id", "baseline.facts")},
        {"id": 6, "title": "处理已作废事实", "task": "%s 有没有已作废的配置" % l1,
         "expect": ("gap_or_hit", "作废"), "line": l1},
        {"id": 7, "title": "冲突知识判断", "task": "%s 哪些结论待核" % l1,
         "expect": ("gap_or_hit", "待核"), "line": l1},
        {"id": 8, "title": "模糊任务要如实报缺口", "task": "哪些事实需要重新核实",
         "expect": ("gap", "")},
        {"id": 9, "title": "无检索命中", "task": "zzz-nonexistent-topic-qqq",
         "expect": ("gap", "缺口")},
        {"id": 10, "title": "错误项目路径", "task": "查看现状",
         "expect": ("exit2", "")},
    ]


def archive_relpaths(root: Path, loose: bool, files) -> set:
    """默认上下文里不该出现的归档来源。

    只认根层归档文件（90_*.md / *归档*.md）与根层归档目录下的文件。
    早先按「任意深层的父目录名像归档」统计，会把备份目录里的同名文件也算进来，
    于是正常块被误判成「归档混入」（真实项目上直接误报 5/9）。
    """
    # 只认根层归档角色的文件：kb-context 的块来源只有根层固定层 + 事实分册，
    # 归档目录里的东西不可能成为来源。之前把归档目录下的全部文件按**文件名**
    # 加进来，真实项目「归档/ 下有一份整库备份」时会与正常文件撞名 → 误报。
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
    rows, metrics = [], {k: {"passed": 0, "total": 0} for k, _ in METRIC_KEYS}

    def mark(key, ok, counted=True):
        if not counted:
            return
        metrics[key]["total"] += 1
        metrics[key]["passed"] += 1 if ok else 0

    tasks = build_tasks(root, files, args.loose)
    for t in tasks:
        kind, want = t["expect"]
        started = time.time()
        if kind == "exit2":
            _payload, code, err = run_json(
                "kb-context.py", ["--target", str(root / "__no_such_dir__"),
                                  "--task", t["task"], "--format", "json"] + ctx_args)
            ok = code == 2 and "ERR" in (err or "")
            mark("error_rejected", ok)
            rows.append({"id": t["id"], "title": t["title"], "a": 0, "b": b_tokens,
                         "c": 0, "noise": 0.0, "counted": False, "graded": True,
                         "quality": "拒绝错误路径" if ok else "未拒绝",
                         "pass": ok, "ms": int((time.time() - started) * 1000)})
            continue

        if kind == "section_id" and unmigrated:
            rows.append({"id": t["id"], "title": t["title"], "a": a_tokens,
                         "b": b_tokens, "c": 0, "noise": 0.0, "counted": False,
                         "graded": False,
                         "quality": "跳过：未迁移库没有 kb:id",
                         "pass": False, "ms": 0})
            continue

        payload, code, _err = run_json(
            "kb-context.py", ["--target", str(root), "--task", t["task"],
                              "--budget", str(args.budget), "--format", "json"] + ctx_args)
        blocks = payload.get("blocks", [])
        ids = [b.get("section_id") for b in blocks]
        gaps = " ".join(payload.get("gaps", []))
        text_all = json.dumps(payload.get("context", {}), ensure_ascii=False)
        sources = [b.get("source") for b in blocks]
        constraint = any(b.get("priority") == "P0" for b in blocks)
        used = payload.get("used", 0)

        hit = (want in ids) or (want in text_all) or (want in gaps)
        if kind == "section_id":
            ok = want in ids and constraint
            label = "命中 %s" % want if ok else "未命中 %s" % want
            mark("section_hit", want in ids)
        elif kind == "gap_or_hit":
            # 2.0.1：命中或报缺口都必须成立，且约束仍在（此前只要约束在就算过）
            ok = hit and constraint
            if ok:
                label = ("命中 %s" % want if (want in ids or want in text_all)
                         else "如实报缺口")
            elif not constraint:
                label = "命中/缺口都在，但硬约束丢失"
            else:
                label = "未命中 %s" % want
            mark("gap_honest", bool(gaps) or hit)
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
        budget_ok = used <= args.budget and payload.get("over_budget") == (used > args.budget)
        mark("budget_respected", budget_ok)
        mark("tokenizer_consistent",
             payload.get("requested") == args.tokenizer
             and payload.get("exact") == counter.exact)
        selected = payload.get("selected_lines") or []
        omitted = payload.get("omitted_lines") or []
        lines_ok = not (set(selected) & set(omitted))
        if omitted:
            lines_ok = lines_ok and all(("工作线「%s」" % n) in gaps for n in omitted)
        mark("lines_honest", lines_ok)
        mark("archive_excluded", not (set(sources) & archive_names))

        p4 = sum(b["tokens"] for b in blocks if b.get("priority") == "P4")
        c = used
        rows.append({"id": t["id"], "title": t["title"], "a": a_tokens, "b": b_tokens,
                     "c": c, "noise": round(p4 / c, 3) if c else 0.0, "counted": True,
                     "graded": True,
                     "quality": label,
                     "pass": ok, "ms": int((time.time() - started) * 1000)})

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
    # 关键项不接受「被平均值抹平」：硬约束丢失、错误路径被放行都是硬失败
    hard_ok = all(metrics[k]["total"] and metrics[k]["passed"] == metrics[k]["total"]
                  for k in GATE_MUST_PASS)
    need = max(1, int(round(len(graded) * 0.8)))
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
        "gate": {"min_rate": 0.8, "min_passes": need,
                 "must_pass": list(GATE_MUST_PASS),
                 "hard_ok": hard_ok, "passed": gate_ok},
        "rows": rows,
        "files": [{"path": p, "tokens": n} for p, n in per_file],
        "notes": [
            "A/B/C 用同一个 TokenCounter（%s），口径一致" % tok_desc,
            "A=全部参与检索文本，B=00+05，C=单次任务上下文；三者统计范围不同",
            "C 均值只统计 %d 个正常任务；%d 个错误路径单列，不参与均值" % (len(counted), len(errors)),
            "可评任务 %d 个（未迁移库的 section 类任务会标为跳过，不混进通过率）"
            % len(graded),
            "质量判定：命中（或如实报缺口）且硬约束仍在；不是「约束在就算过」",
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
    print("| 质量项 | 通过 |")
    print("|---|---|")
    for key, label in METRIC_KEYS:
        m = metrics[key]
        print("| %s | %d/%d |" % (label, m["passed"], m["total"]))
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
