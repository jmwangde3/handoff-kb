#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chinese/English token benchmark for handoff-kb (A / B / C).

Usage:
    py tests/token_language/run_token_benchmark.py --tokenizer cl100k_base
    py tests/token_language/run_token_benchmark.py --tokenizer o200k_base --report json
    py tests/token_language/run_token_benchmark.py --all --out tests/token_language/out

`--all` runs every tokenizer the environment can provide exactly, plus the two
estimates (`deepseek_estimate`, `heuristic`) which are always labelled as
estimates and never used for a conclusion.

Exit codes: 0 = report produced; 2 = a requested tokenizer is unavailable
(no silent fallback — pass `--allow-tokenizer-fallback` to accept an estimate).
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tl_common as tl  # noqa: E402  (also puts scripts/ on sys.path)

from lib import tokens as tokenlib  # noqa: E402


def measure(tokenizer: str, allow_fallback: bool = False) -> dict:
    counter = tl.make_counter(tokenizer, allow_fallback=allow_fallback)
    groups = {"T1_description": {}, "T2_skill": {}, "T3_references": {},
              "T4_task_paths": {}, "T5_templates": {}}

    for v in tl.VARIANT_NAMES:
        groups["T1_description"][v] = tl.description_stats(v, counter)
        groups["T2_skill"][v] = tl.stats(tl.doc_path(v, "skill"), counter)

    for name in tl.REF_NAMES:
        row = {}
        for v in tl.VARIANT_NAMES:
            row[v] = tl.stats(tl.doc_path(v, "ref:%s" % name), counter)
        groups["T3_references"][name] = row

    for key, title, keys in tl.TASKS:
        row = {}
        for v in tl.VARIANT_NAMES:
            row[v] = tl.task_stats(v, keys, counter)
        row["title"] = title
        row["required"] = keys
        groups["T4_task_paths"][key] = row

    for name in tl.ASSET_NAMES:
        row = {}
        for v in tl.VARIANT_NAMES:
            row[v] = tl.stats(tl.doc_path(v, "asset:%s" % name), counter)
        groups["T5_templates"][name] = row

    def pair(node, a="A", b="B", c="C"):
        ta, tb, tc = node[a]["tokens"], node[b]["tokens"], node[c]["tokens"]
        return {
            "A": ta, "B": tb, "C": tc,
            "structure_saving": tl.saving(ta, tb),
            "language_saving": tl.saving(tb, tc),
            "total_saving": tl.saving(ta, tc),
        }

    summary = {
        "T1_description": pair(groups["T1_description"]),
        "T2_skill": pair(groups["T2_skill"]),
        "T3_references": {n: pair(r) for n, r in groups["T3_references"].items()},
        "T4_task_paths": {k: dict(pair(r), title=r["title"], required=r["required"])
                          for k, r in groups["T4_task_paths"].items()},
        "T5_templates": {n: pair(r) for n, r in groups["T5_templates"].items()},
    }

    return {
        "tokenizer": tokenizer,
        "counter": counter.as_dict(),
        "exact": counter.exact,
        "env": tl.env_info(),
        "groups": groups,
        "summary": summary,
    }


def pct(value) -> str:
    return "n/a" if value is None else "%+.1f%%" % (value * 100.0)


def markdown(report: dict) -> str:
    c = report["counter"]
    env = report["env"]
    out = []
    out.append("# Token benchmark — A / B / C")
    out.append("")
    out.append("| Item | Value |")
    out.append("|---|---|")
    out.append("| tokenizer requested | `%s` |" % report["tokenizer"])
    out.append("| tokenizer actual | `%s` |" % c["actual"])
    out.append("| exact | %s |" % ("true" if report["exact"] else "false (estimate)"))
    out.append("| source | %s |" % c.get("source"))
    out.append("| vocabulary file | %s |" % (c.get("tokenizer_file") or "n/a"))
    out.append("| vocabulary SHA256 | %s |" % (c.get("tokenizer_sha256") or "n/a"))
    out.append("| counting library | %s |"
               % (("%s %s" % (c["library"], c.get("library_version") or "unknown"))
                  if c.get("library") else "standard library only"))
    out.append("| python | %s |" % env["python"])
    out.append("| tiktoken | %s |" % (env["tiktoken"] or "not installed"))
    out.append("| tokenizers | %s |" % (env["tokenizers"] or "not installed"))
    out.append("| deepseek tokenizer | %s |"
               % ("present" if env["deepseek_tokenizer_present"] else "absent"))
    out.append("| deepseek vocabulary SHA256 | %s |"
               % (env.get("deepseek_tokenizer_sha256") or "n/a"))
    out.append("")
    out.append("Variants: **A** original Chinese v2.0.3 (frozen baseline) · "
               "**B** optimized Chinese v2.0.4 — **benchmark sample, not a shipped skill** · "
               "**C** the shipped English v2.0.4 skill.")
    out.append("B exists only to separate structure from language: `A → B` is the restructuring "
               "gain, `B → C` is the language gain. 2.0.4 ships one skill (`SKILL.md`).")
    out.append("`structure = 1 - B/A`, `language = 1 - C/B`, `total = 1 - C/A`.")
    out.append("Neither the paths above nor the environment block contain a personal directory; "
               "two reports with the same vocabulary SHA256 used the same vocabulary file.")
    out.append("")

    def table(title, rows, header_extra=""):
        out.append(title)
        out.append("")
        out.append("| Item | A | B | C | structure | language | total |")
        out.append("|---|---|---|---|---|---|---|")
        for name, r in rows:
            out.append("| %s | %d | %d | %d | %s | %s | %s |"
                       % (name, r["A"], r["B"], r["C"],
                          pct(r["structure_saving"]), pct(r["language_saving"]),
                          pct(r["total_saving"])))
        out.append("")

    s = report["summary"]
    table("## T1 · YAML description", [("description", s["T1_description"])])
    table("## T2 · SKILL.md", [("SKILL.md", s["T2_skill"])])
    table("## T3 · Reference files (each read alone)",
          [(n, s["T3_references"][n]) for n in tl.REF_NAMES])
    table("## T4 · Complete task reading paths",
          [(s["T4_task_paths"][k]["title"], s["T4_task_paths"][k]) for k, _, _ in tl.TASKS])
    table("## T5 · Project templates (each file alone)",
          [(n, s["T5_templates"][n]) for n in tl.ASSET_NAMES])

    out.append("## T4 detail — which files each task reads")
    out.append("")
    for key, title, keys in tl.TASKS:
        row = s["T4_task_paths"][key]
        out.append("- **%s** (`%s`): reads %s — A %d / B %d / C %d tokens, total %s"
                   % (title, key, ", ".join("`%s`" % k for k in keys),
                      row["A"], row["B"], row["C"], pct(row["total_saving"])))
    out.append("")
    out.append("## Limitations")
    out.append("")
    out.append("- B is a **benchmark sample** (`tests/token_language/sample_b/SKILL.zh-CN.md`), "
               "kept byte-frozen by a SHA256 assertion. It is not installed, not discoverable "
               "as a skill, and not supported; only `SKILL.md` ships.")
    out.append("- tiktoken encodings (`cl100k_base`, `o200k_base`) are reproducible proxies; "
               "they are not every model's billing tokenizer. The 15% target is defined on these two.")
    out.append("- `deepseek_v4` uses the official offline tokenizer "
               "(`tokenizers` + `tokenizer.json`); its acceptance criterion is "
               "\"must not grow\", not 15% — the vocabulary is Chinese-heavy, so the same "
               "restructuring gains less. `deepseek_estimate` only applies the "
               "documented ratio (1 English char ≈ 0.3, 1 Chinese char ≈ 0.6) and is an estimate.")
    out.append("- The heuristic counter (CJK 1 char ≈ 1 token, other 4 chars ≈ 1 token) is "
               "reported as an estimate only and is never used for a conclusion.")
    out.append("- Structure is compared through section headings and protocol IDs, not through "
               "semantic equivalence of every sentence; see `test_token_language.py`.")
    out.append("- Task paths list the documents a task actually needs; references that are not "
               "required are not counted as default-loaded content.")
    out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="A/B/C token benchmark")
    ap.add_argument("--tokenizer", default="cl100k_base",
                    choices=tl.TOKENIZERS)
    ap.add_argument("--all", action="store_true",
                    help="run every tokenizer (exact ones plus the two estimates)")
    ap.add_argument("--report", choices=["markdown", "json"], default="markdown")
    ap.add_argument("--out", default=None, help="output directory")
    ap.add_argument("--allow-tokenizer-fallback", action="store_true",
                    help="accept an estimate when the requested encoder is missing (exact=false)")
    args = ap.parse_args()

    names = tl.TOKENIZERS if args.all else [args.tokenizer]
    reports = []
    for name in names:
        try:
            reports.append(measure(name, allow_fallback=args.allow_tokenizer_fallback))
        except tokenlib.TokenizerError as exc:
            print("ERR: %s" % exc, file=sys.stderr)
            return 2

    if args.report == "json":
        payload = {"schema_version": 1, "benchmark": "token_language",
                   "variants": {v: tl.VARIANTS[v]["label"] for v in tl.VARIANT_NAMES},
                   "tasks": [{"key": k, "title": t, "documents": d} for k, t, d in tl.TASKS],
                   "reports": reports}
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    else:
        text = "\n".join(markdown(r) for r in reports)

    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        suffix = "json" if args.report == "json" else "md"
        name = "token-benchmark-%s.%s" % (names[0] if len(names) == 1 else "all", suffix)
        target = out_dir / name
        with io.open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("wrote %s" % target)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
