#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-benchmark.py — Token 与接手质量评测（可复现，无网络）

三种读法对比（同一任务）：
  A 全量：把库里所有参与检索的文本当上下文
  B 旧法：只读 00 + 05
  C 新版：kb-context.py 按预算路由

质量项：目标章节是否命中、硬约束是否保留、是否报缺口、错误路径是否拒绝。
默认 token 数是**估算**（CJK 1 字≈1 token）；装了 tiktoken 且指定 --tokenizer 才用真实编码。

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

from lib import protocol, scope, tokens  # noqa: E402

HERE = Path(__file__).resolve().parent


def run_json(script, args):
    p = subprocess.run([sys.executable, str(HERE / script)] + args,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return json.loads(p.stdout), p.returncode
    except Exception:
        return {"_stdout": p.stdout, "_stderr": p.stderr}, p.returncode


def corpus_tokens(root: Path):
    total = 0
    files = []
    for p, reason in scope.iter_text_files(root, include_archive=True):
        if reason:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n, _ = tokens.estimate(text)
        total += n
        files.append((p.relative_to(root).as_posix(), n))
    return total, files


def build_tasks(root: Path, files):
    facts = [p for p in files.get("fact", [])]
    lines = [p.stem.split("_", 1)[1] for p in facts if "_" in p.stem]
    l1 = lines[0] if lines else "线A"
    l2 = lines[1] if len(lines) > 1 else l1
    return [
        {"id": 1, "title": "查看当前项目状态", "task": "查看当前项目状态",
         "expect": ("section_id", "dashboard.current")},
        {"id": 2, "title": "单工作线排障", "task": "排查%s的问题" % l1,
         "expect": ("section_id", "fact.pitfalls")},
        {"id": 3, "title": "跨工作线依赖", "task": "改%s会影响%s吗" % (l1, l2),
         "expect": ("section_id", "baseline.chains")},
        {"id": 4, "title": "查找某项事实", "task": "K-01 的当前值是什么",
         "expect": ("section_id", "baseline.facts")},
        {"id": 5, "title": "追踪证据", "task": "K-01 的证据在哪",
         "expect": ("section_id", "baseline.facts")},
        {"id": 6, "title": "处理已作废事实", "task": "%s 有没有已作废的配置" % l1,
         "expect": ("gap_or_hit", "作废")},
        {"id": 7, "title": "冲突知识判断", "task": "%s 哪些结论待核" % l1,
         "expect": ("gap_or_hit", "待核")},
        {"id": 8, "title": "过期信息处理", "task": "哪些事实需要重新核实",
         "expect": ("gap_or_hit", "核实")},
        {"id": 9, "title": "无检索命中", "task": "zzz-nonexistent-topic-qqq",
         "expect": ("gap", "缺口")},
        {"id": 10, "title": "错误项目路径", "task": "", "expect": ("exit2", "")},
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description="Token 与质量评测")
    ap.add_argument("--target", default=".")
    ap.add_argument("--budget", type=int, default=3000)
    ap.add_argument("--report", choices=["markdown", "json"], default="markdown")
    ap.add_argument("--tokenizer", default="heuristic")
    args = ap.parse_args()

    try:
        root = scope.resolve_root(args.target)
    except scope.ScopeError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 2
    files = scope.role_files(root)
    if not files.get("dashboard"):
        print("ERR: 目标不像交接库（没有 05）", file=sys.stderr)
        return 2

    a_tokens, per_file = corpus_tokens(root)
    b_tokens = sum(tokens.estimate(p.read_text(encoding="utf-8", errors="replace"))[0]
                   for role in ("baseline", "dashboard") for p in files.get(role, []))
    tok_desc = tokens.estimate("", args.tokenizer)[1]

    rows, passes = [], 0
    tasks = build_tasks(root, files)
    for t in tasks:
        kind, want = t["expect"]
        started = time.time()
        if kind == "exit2":
            payload, code = run_json("kb-check.py", ["--target",
                                                    str(root / "__no_such_dir__"), "--json"])
            ok = code == 2
            rows.append({"id": t["id"], "title": t["title"], "a": 0, "b": 0, "c": 0,
                         "noise": 0.0, "quality": "拒绝错误路径" if ok else "未拒绝",
                         "pass": ok, "ms": int((time.time() - started) * 1000)})
            passes += 1 if ok else 0
            continue

        payload, code = run_json("kb-context.py", ["--target", str(root), "--task", t["task"],
                                                   "--budget", str(args.budget),
                                                   "--format", "json",
                                                   "--tokenizer", args.tokenizer])
        blocks = payload.get("blocks", [])
        ids = [b.get("section_id") for b in blocks]
        gaps = " ".join(payload.get("gaps", []))
        text_all = json.dumps(payload.get("context", {}), ensure_ascii=False)
        constraint = any(b.get("priority") == "P0" for b in blocks)
        if kind == "section_id":
            ok = want in ids and constraint
        elif kind == "gap_or_hit":
            ok = (want in text_all) or (want in gaps) or constraint
        else:  # gap
            ok = bool(gaps) and constraint
        c = payload.get("used", 0)
        p4 = sum(b["tokens"] for b in blocks if b.get("priority") == "P4")
        rows.append({"id": t["id"], "title": t["title"], "a": a_tokens, "b": b_tokens,
                     "c": c, "noise": round(p4 / c, 3) if c else 0.0,
                     "quality": "命中 %s" % want if ok else "未命中 %s" % want,
                     "pass": ok, "ms": int((time.time() - started) * 1000)})
        passes += 1 if ok else 0

    mean_c = sum(r["c"] for r in rows) / len(rows)
    reduction = (1 - mean_c / b_tokens) if b_tokens else 0
    result = {
        "target": str(root), "budget": args.budget, "tokenizer": tok_desc,
        "tokens": {"A_all": a_tokens, "B_00_05": b_tokens, "C_mean": round(mean_c, 1)},
        "reduction_vs_B": round(reduction, 3),
        "quality": {"passed": passes, "total": len(rows),
                    "rate": round(passes / len(rows), 3)},
        "rows": rows,
        "notes": [
            "token 数为估算（%s），不是任何 API 的计费值" % tok_desc,
            "A/B/C 的统计范围不同：A=全部参与检索文本，B=00+05，C=单次任务上下文",
            "质量项按固定 10 个任务判定，不追求最高压缩比",
        ],
    }

    if args.report == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if passes >= 8 else 1

    print("# handoff-kb benchmark — %s" % root)
    print("")
    print("| 指标 | 值 |")
    print("|---|---|")
    print("| A 全量上下文 | %d tokens |" % a_tokens)
    print("| B 旧法（00+05） | %d tokens |" % b_tokens)
    print("| C 新版（均值，预算 %d） | %.0f tokens |" % (args.budget, mean_c))
    print("| C 相对 B 降幅 | %.1f%% |" % (reduction * 100))
    print("| 质量通过 | %d/%d |" % (passes, len(rows)))
    print("| tokenizer | %s |" % tok_desc)
    print("")
    print("| # | 任务 | A | B | C | P4 噪声比 | 质量 | ms |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        print("| %d | %s | %d | %d | %d | %.2f | %s | %d |"
              % (r["id"], r["title"], r["a"], r["b"], r["c"], r["noise"],
                 r["quality"], r["ms"]))
    print("")
    print("> token 数为估算（%s）；A/B/C 统计范围不同，别把降幅当成 API 账单对比。" % tok_desc)
    return 0 if passes >= 8 else 1


if __name__ == "__main__":
    sys.exit(main())
