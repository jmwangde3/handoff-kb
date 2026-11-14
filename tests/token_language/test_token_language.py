#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Semantic parity, structural parity and token-target tests for 2.0.4.

Three layers, because keyword presence alone proves nothing:

1. **Structural checks** — section ordinals, script/flag coverage, reference and
   template file sets, `kb:id` sets, placeholder sets, baseline hashes.
2. **Rule checks** — one entry per behavioural rule that must survive the
   Chinese ⇄ English translation; each entry fails if the rule disappears from
   either document.
3. **Scenario checks** — a Chinese project running under the English skill
   (diagnosis, routing, init) must keep working.

Set `KB_EMIT_CHECKLIST=1` to (re)generate `SEMANTIC_CHECKLIST.md`, the
human-review sheet that accompanies these automated checks.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import tl_common as tl  # noqa: E402

from lib import tokens as tokenlib  # noqa: E402

ROOT = tl.ROOT
SCRIPTS = ROOT / "scripts"
PAIRED = tl.FIXTURES
CHECKLIST = HERE / "SEMANTIC_CHECKLIST.md"

# Every rule the specification requires to stay explicit. `en` and `zh` list
# acceptable wordings; a rule fails when neither appears in that language.
RULES = [
    ("P0 never silently discarded",
     ["never silently discarded", "P0", "never dropped"],
     ["永不静默丢弃", "P0"]),
    ("P1 current state and next step",
     ["P1", "current state", "next step"],
     ["P1", "现状", "下一手"]),
    ("P2 workstream facts",
     ["P2", "workstream facts", "facts of the matching workstream"],
     ["P2", "本线事实"]),
    ("P3 explicit fact IDs and evidence",
     ["P3", "fact IDs", "evidence"],
     ["P3", "事实 ID", "证据"]),
    ("P4 bounded relevance",
     ["P4", "relevance", "≤3 blocks"],
     ["P4", "相关度", "≤3 块"]),
    ("P0 fallback order",
     ["dashboard.constraints", "dashboard.safety", "AGENTS.md"],
     ["dashboard.constraints", "dashboard.safety", "AGENTS.md"]),
    ("P4 limits (blocks and budget share)",
     ["≤30%", "≤3 blocks"],
     ["≤30%", "≤3 块"]),
    ("superseded fact handling",
     ["superseded", "include-superseded"],
     ["已作废", "include-superseded"]),
    ("gap reporting honest",
     ["Gaps and omitted content must be reported honestly", "report a gap"],
     ["缺口与省略必须如实报告", "报缺口"]),
    ("write requires current hash",
     ["sha256", "expected_sha256"],
     ["sha256", "expected_sha256"]),
    ("lock conflicts not bypassed",
     ["LockHeld", "break-lock"],
     ["LockHeld", "break-lock"]),
    ("multi-file writes not database-atomic",
     ["not database-level atomic", "not a cross-file atomic transaction"],
     ["不是数据库级原子事务"]),
    ("migration preserves source content",
     ["no body edits", "does not ", "migration touches only"],
     ["不改正文", "不删证据"]),
    ("hooks never block a session",
     ["never blocking", "always 0", "exit 0"],
     ["永远退出 0", "不阻断"]),
    ("no credentials committed",
     ["credentials", "credential hit blocks the commit"],
     ["凭证"]),
    ("reference loading is not default",
     ["References are not default reading", "Load one only when"],
     ["参考手册不是默认读物"]),
    ("existing v2 projects keep working",
     ["existing v2 projects", "compatible with existing v2"],
     ["兼容现有 v2 项目"]),
]

SECTION_ORDINALS = ["1", "2", "3", "4", "5", "6", "7", "8", "9"]


def read(path: Path) -> str:
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def norm(text: str) -> str:
    return " ".join(text.split())


def section_ordinals(text: str):
    """Ordinal prefixes of `## ` headings, e.g. `## 3. Quick Start` -> `3`."""
    out = []
    for line in text.splitlines():
        if line.startswith("## "):
            head = line[3:].strip()
            num = ""
            for ch in head:
                if ch.isdigit():
                    num += ch
                else:
                    break
            out.append(num)
    return out


def headings(text: str):
    return [line[3:].strip() for line in text.splitlines() if line.startswith("## ")]


def script_mentions(text: str):
    found = set()
    for token in text.replace("`", " ").replace("(", " ").replace(")", " ").split():
        name = token.strip().rstrip(".,;:")
        if name.startswith("kb-") and name.endswith(".py"):
            found.add(name)
        elif name.startswith("scripts/kb-") and name.endswith(".py"):
            found.add(name.rsplit("/", 1)[-1])
    return found


def flags(text: str):
    out = set()
    for token in text.replace("`", " ").split():
        token = token.strip().rstrip(".,;:")
        if token.startswith("--") and len(token) > 3:
            out.add(token.split("=")[0])
    return out


def placeholder_set(text: str):
    out = set()
    i = 0
    while True:
        i = text.find("{{", i)
        if i < 0:
            return out
        j = text.find("}}", i)
        if j < 0:
            return out
        out.add(text[i + 2:j])
        i = j + 2


def kb_ids(text: str):
    out = set()
    marker = "<!-- kb:id:"
    i = 0
    while True:
        i = text.find(marker, i)
        if i < 0:
            return out
        j = text.find("-->", i)
        if j < 0:
            return out
        out.add(text[i + len(marker):j].strip())
        i = j + 3


GIT_ONLY_FLAGS = {"--oneline", "--short", "--all", "--amend"}


def help_text(script: str, *args) -> str:
    proc = subprocess.run([sys.executable, str(SCRIPTS / script)] + list(args) + ["--help"],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    return (proc.stdout or "") + (proc.stderr or "")


class BaselineIntegrity(unittest.TestCase):
    def test_manifest_matches_files(self):
        manifest_path = tl.BASELINE / "MANIFEST.json"
        self.assertTrue(manifest_path.is_file(), "baseline MANIFEST.json is missing")
        manifest = json.loads(read(manifest_path))
        for rel, row in manifest["files"].items():
            path = tl.BASELINE / rel
            self.assertTrue(path.is_file(), "baseline file missing: %s" % rel)
            data = path.read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"],
                             "baseline file was modified: %s" % rel)
            self.assertEqual(len(data), row["bytes"], "baseline size drift: %s" % rel)

    def test_no_extra_baseline_files(self):
        manifest = json.loads(read(tl.BASELINE / "MANIFEST.json"))
        on_disk = {p.relative_to(tl.BASELINE).as_posix()
                   for p in tl.BASELINE.rglob("*")
                   if p.is_file() and p.name != "MANIFEST.json"}
        self.assertEqual(on_disk, set(manifest["files"]),
                         "baseline directory gained or lost files")


class VariantCompleteness(unittest.TestCase):
    def test_all_documents_exist(self):
        for variant in tl.VARIANT_NAMES:
            self.assertTrue(tl.doc_path(variant, "skill").is_file(),
                            "%s: SKILL missing" % variant)
            for name in tl.REF_NAMES:
                self.assertTrue(tl.doc_path(variant, "ref:%s" % name).is_file(),
                                "%s: reference %s missing" % (variant, name))
            for name in tl.ASSET_NAMES:
                self.assertTrue(tl.doc_path(variant, "asset:%s" % name).is_file(),
                                "%s: template %s missing" % (variant, name))

    def test_chinese_and_english_structure_match(self):
        zh = read(tl.doc_path("B", "skill"))
        en = read(tl.doc_path("C", "skill"))
        self.assertEqual(section_ordinals(zh), SECTION_ORDINALS)
        self.assertEqual(section_ordinals(en), SECTION_ORDINALS)
        self.assertEqual(len(headings(zh)), len(headings(en)))

    def test_frontmatter_name_and_boundaries(self):
        for variant, must_have in (("B", ["不适用"]), ("C", ["Do not use"])):
            text = read(tl.doc_path(variant, "skill"))
            self.assertTrue(text.startswith("---"), "%s: frontmatter missing" % variant)
            self.assertIn("name: handoff-kb", text)
            desc = tl.frontmatter_description(text)
            self.assertTrue(desc, "%s: description empty" % variant)
            for needle in must_have:
                self.assertIn(needle, desc, "%s: scope exclusion missing" % variant)


class SemanticParity(unittest.TestCase):
    def test_rules_present_in_both_languages(self):
        en = norm(read(tl.doc_path("C", "skill")))
        zh = norm(read(tl.doc_path("B", "skill")))
        missing = []
        for label, en_terms, zh_terms in RULES:
            if not any(t in en for t in en_terms):
                missing.append("EN: " + label)
            if not any(t in zh for t in zh_terms):
                missing.append("ZH: " + label)
        self.assertEqual(missing, [], "rules missing from SKILL.md: %s" % missing)

    def test_rules_present_in_references(self):
        """Protocol-level rules must survive the reference translation too."""
        pairs = [
            ("P0 fallback order", "dashboard.safety", "dashboard.safety"),
            ("lock ownership", "LockOwnershipError", "LockOwnershipError"),
            ("journal checksum", "checksum", "checksum"),
            ("atomicity boundary", "atomic", "原子"),
            ("exit codes", "exit code", "退出码"),
        ]
        for ref in ("protocol-v2", "migration", "hooks", "benchmark"):
            en = read(tl.doc_path("C", "ref:%s" % ref))
            zh = read(tl.doc_path("B", "ref:%s" % ref))
            if ref == "protocol-v2":
                for label, en_needle, zh_needle in pairs:
                    self.assertIn(en_needle.lower(), en.lower(),
                                  "EN protocol-v2 lost %s" % label)
                    self.assertIn(zh_needle.lower(), zh.lower(),
                                  "ZH protocol-v2 lost %s" % label)

    def test_script_coverage_identical(self):
        en = script_mentions(read(tl.doc_path("C", "skill")))
        zh = script_mentions(read(tl.doc_path("B", "skill")))
        self.assertEqual(en, zh, "script coverage differs between languages")
        self.assertGreaterEqual(len(en), 9, "SKILL.md should mention every script")

    def test_documented_flags_exist(self):
        combined = ""
        for script in ("kb-init.py", "kb-check.py", "kb-context.py", "kb-write.py",
                       "kb-migrate.py", "kb-handoff.py", "kb-hooks.py", "kb-benchmark.py",
                       "kb-outline.py", "kb-search.py"):
            combined += help_text(script)
        for sub in ("read", "apply", "recover"):
            combined += help_text("kb-write.py", sub)
        for sub in ("install", "uninstall", "run"):
            combined += help_text("kb-hooks.py", sub)
        for sub in ("check",):
            combined += help_text("kb-handoff.py", sub)
        documented = flags(read(tl.doc_path("C", "skill")))
        documented |= flags(read(tl.doc_path("B", "skill")))
        documented -= GIT_ONLY_FLAGS
        missing = sorted(f for f in documented if f not in combined)
        self.assertEqual(missing, [], "flags documented but not implemented: %s" % missing)

    def test_reference_links_resolve(self):
        for variant in ("B", "C"):
            text = read(tl.doc_path(variant, "skill"))
            for name in tl.REF_NAMES:
                suffix = ".zh-CN.md" if variant == "B" else ".md"
                rel = "references/%s%s" % (name, suffix)
                self.assertIn(rel, text, "%s: reference link missing: %s" % (variant, rel))
                self.assertTrue((ROOT / rel).is_file(), "link target missing: %s" % rel)
            self.assertIn("references/protocol.md", text,
                          "%s: historical protocol link missing" % variant)


class TemplateParity(unittest.TestCase):
    def test_paired_fixtures_share_structure(self):
        zh_root = PAIRED / "zh"
        en_root = PAIRED / "en"
        zh_files = sorted(p.relative_to(zh_root).as_posix()
                          for p in zh_root.rglob("*") if p.is_file())
        en_files = sorted(p.relative_to(en_root).as_posix()
                          for p in en_root.rglob("*") if p.is_file())
        self.assertEqual(zh_files, en_files, "Chinese and English scaffolds differ in file set")
        self.assertGreaterEqual(len(zh_files), 15)

        for rel in zh_files:
            if not rel.endswith(".md"):
                continue
            zh_text = read(zh_root / rel)
            en_text = read(en_root / rel)
            self.assertEqual(kb_ids(zh_text), kb_ids(en_text),
                             "kb:id sets differ in %s" % rel)
            self.assertEqual(placeholder_set(zh_text), placeholder_set(en_text),
                             "placeholders differ in %s" % rel)
            self.assertEqual(len(headings(zh_text)), len(headings(en_text)),
                             "heading count differs in %s" % rel)
            self.assertNotIn("{{", zh_text, "%s: unrendered placeholder" % rel)
            self.assertNotIn("{{", en_text, "%s: unrendered placeholder" % rel)

    def test_templates_keep_protocol_values(self):
        """Status vocabulary is protocol data, not prose: it must stay literal."""
        for variant, root in (("B", ROOT / "assets"), ("C", ROOT / "assets" / "en")):
            base = read(root / "00_baseline.md")
            self.assertIn("有效", base, "%s: status vocabulary lost" % variant)
            self.assertIn("待核", base, "%s: status vocabulary lost" % variant)
            dash = read(root / "05_dashboard.md")
            for sid in ("dashboard.current", "dashboard.next", "dashboard.lines",
                        "dashboard.todo", "dashboard.constraints", "dashboard.summary"):
                self.assertIn(sid, dash, "%s: %s missing from dashboard template" % (variant, sid))


class TokenTargets(unittest.TestCase):
    """Default loading cost must not exceed 85% of v2.0.3; task paths must not grow.

    An exact encoder is an optional dependency. CI installs none, so on CI these
    tests skip with the missing encoder named in the reason — they are never
    silently absent, and the whole class is reproducible on any machine that has
    `tiktoken` (and optionally the DeepSeek offline tokenizer) installed:

        python tests/token_language/run_token_benchmark.py --all
    """

    @classmethod
    def setUpClass(cls):
        cls.counters = {}
        cls.missing = []
        for name in ("cl100k_base", "o200k_base", "deepseek_v4"):
            try:
                cls.counters[name] = tokenlib.TokenCounter(name)
            except tokenlib.TokenizerError:
                cls.counters[name] = None
                cls.missing.append(name)
        cls.manifest = json.loads(read(tl.BASELINE / "MANIFEST.json"))

    SPEC_TOKENIZERS = ("cl100k_base", "o200k_base")

    def available(self, names):
        """Return the usable counters, or skip naming exactly what is missing."""
        usable = {n: self.counters[n] for n in names if self.counters.get(n) is not None}
        if not usable:
            self.skipTest("optional encoder(s) not installed: %s — the numeric gate needs an "
                          "exact tokenizer, see run_token_benchmark.py" % ", ".join(names))
        return usable

    def test_skill_default_loading_saving(self):
        for name, counter in self.available(self.SPEC_TOKENIZERS).items():
            with self.subTest(tokenizer=name):
                a = counter.count(read(tl.doc_path("A", "skill")))
                c = counter.count(read(tl.doc_path("C", "skill")))
                self.assertLessEqual(c, 0.85 * a,
                                     "%s: default SKILL load must drop >=15%% (A=%d C=%d)"
                                     % (name, a, c))

    def test_deepseek_default_loading_does_not_grow(self):
        """DeepSeek's vocabulary is Chinese-heavy, so the English gain is smaller.

        The specification's 15% target is measured with cl100k_base / o200k_base;
        on the DeepSeek tokenizer the honest requirement is "never worse".
        """
        counter = self.available(("deepseek_v4",))["deepseek_v4"]
        a = counter.count(read(tl.doc_path("A", "skill")))
        c = counter.count(read(tl.doc_path("C", "skill")))
        self.assertLessEqual(c, a,
                             "deepseek_v4: English SKILL must not grow (A=%d C=%d)" % (a, c))

    def test_task_paths_do_not_grow(self):
        """Every task reading path must not get more expensive in the English edition.

        Runs per tokenizer as a subtest so one missing encoder cannot hide the
        result of the others.
        """
        for name, counter in self.available(("cl100k_base", "o200k_base", "deepseek_v4")).items():
            for key, title, keys in tl.TASKS:
                with self.subTest(tokenizer=name, task=key):
                    a = tl.task_stats("A", keys, counter)["tokens"]
                    c = tl.task_stats("C", keys, counter)["tokens"]
                    self.assertLessEqual(c, a,
                                         "%s / %s: English task path grew (A=%d C=%d)"
                                         % (name, title, a, c))

    def test_measurement_is_reproducible(self):
        counter = self.available(("o200k_base",))["o200k_base"]
        first = counter.count(read(tl.doc_path("C", "skill")))
        second = tokenlib.TokenCounter("o200k_base").count(read(tl.doc_path("C", "skill")))
        self.assertEqual(first, second, "same tokenizer must give identical counts")

    def test_manifest_matches_tokens_for_every_available_encoder(self):
        """The frozen baseline's recorded counts must still reproduce.

        This is the guard that makes A trustworthy: if the manifest and the live
        count disagree, the "before" number is fiction.
        """
        for name, counter in self.available(self.SPEC_TOKENIZERS).items():
            for rel, entry in sorted(self.manifest["files"].items()):
                path = tl.BASELINE / rel
                with self.subTest(tokenizer=name, path=rel):
                    data = path.read_bytes()
                    self.assertEqual(len(data), entry["bytes"])
                    self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"])
                    self.assertEqual(counter.count(read(path)), entry["tokens"][name],
                                     "%s: baseline token count drifted" % rel)

    def test_zero_denominator_is_explicit(self):
        self.assertIsNone(tl.saving(0, 10))
        self.assertEqual(tl.saving(10, 5), 0.5)


class NoSilentFallback(unittest.TestCase):
    def test_unknown_tokenizer_raises(self):
        with self.assertRaises(tokenlib.TokenizerError):
            tokenlib.TokenCounter("definitely-not-an-encoder")

    def test_deepseek_estimate_is_labelled(self):
        counter = tokenlib.TokenCounter("deepseek_estimate")
        self.assertFalse(counter.exact)
        self.assertIn("estimate", counter.desc.lower())


class CrossLanguageScenarios(unittest.TestCase):
    """A: zh skill + zh project, B: en skill + zh project, C: en skill + en project."""

    def run_script(self, script, *args, cwd=None):
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return subprocess.run([sys.executable, str(SCRIPTS / script)] + [str(a) for a in args],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=str(cwd) if cwd else None, env=env)

    def test_chinese_project_works(self):
        """kb-check must exit 0 and emit no `[ERR` line for either fixture.

        The bare substring "ERR" also occurs in the summary line
        `== 汇总：OK 20 / WARN 1 / ERR 0`, so match the per-check prefix instead.
        """
        for name in ("zh", "en"):
            root = PAIRED / name
            proc = self.run_script("kb-check.py", "--target", root, "--loose")
            self.assertEqual(proc.returncode, 0,
                             "%s project: kb-check exited %d\n%s"
                             % (name, proc.returncode, proc.stdout[-800:]))
            err_lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("[ERR")]
            self.assertEqual(err_lines, [],
                             "%s project reports ERR under the English skill:\n%s"
                             % (name, "\n".join(err_lines) or proc.stdout[-800:]))

    def test_routing_works_on_chinese_project(self):
        root = PAIRED / "zh"
        proc = self.run_script("kb-context.py", "--target", root, "--loose",
                               "--task", "查看当前状态", "--budget", "2500")
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        self.assertIn("dashboard.current", proc.stdout,
                      "Chinese project lost P1 routing:\n%s" % proc.stdout[:500])

    def test_english_project_routes_with_english_task(self):
        root = PAIRED / "en"
        proc = self.run_script("kb-context.py", "--target", root, "--loose",
                               "--task", "show current status", "--budget", "2500")
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        self.assertIn("dashboard.current", proc.stdout)

    def test_scaffold_lang_flag(self):
        import tempfile
        import shutil
        tmp = Path(tempfile.mkdtemp(prefix="kblang-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        target = tmp / "enproj"
        proc = self.run_script("kb-init.py", "--target", target, "--project", "Demo",
                               "--lines", "a,b", "--no-git", "--lang", "en")
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        agents = read(target / "AGENTS.md")
        self.assertIn("Workspace Rules", agents)
        self.assertNotIn("{{", agents)
        zh_target = tmp / "zhproj"
        proc = self.run_script("kb-init.py", "--target", zh_target, "--project", "Demo",
                               "--lines", "a,b", "--no-git")
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        self.assertIn("工作区规则", read(zh_target / "AGENTS.md"))


def emit_checklist() -> str:
    en = norm(read(tl.doc_path("C", "skill")))
    zh = norm(read(tl.doc_path("B", "skill")))
    lines = ["# Semantic parity checklist — 2.0.4", "",
             "Automated layer: `test_token_language.py` (structure, rules, scenarios).",
             "This sheet is for human review after translation changes.", "",
             "| # | Rule | English | Chinese | Reviewer |", "|---|---|---|---|---|"]
    for i, (label, en_terms, zh_terms) in enumerate(RULES, 1):
        e = "ok" if any(t in en for t in en_terms) else "**missing**"
        z = "ok" if any(t in zh for t in zh_terms) else "**missing**"
        lines.append("| %d | %s | %s | %s | |" % (i, label, e, z))
    lines += ["", "## Manual review points", "",
              "- [ ] Every protocol identifier, command and JSON key in the Chinese and English "
              "references is byte-identical.",
              "- [ ] No exception was silently dropped from the translated reference.",
              "- [ ] Error conditions and exit codes match the implementation.",
              "- [ ] Security warnings survive translation with the same strength "
              "(MUST / MUST NOT, not SHOULD).",
              "- [ ] Chinese templates still render byte-identical to v2.0.3 apart from wording.",
              "- [ ] An English skill over a Chinese project still produces Chinese document "
              "content (language is not auto-translated).", ""]
    return "\n".join(lines) + "\n"


def setUpModule():
    if os.environ.get("KB_EMIT_CHECKLIST") == "1":
        CHECKLIST.write_text(emit_checklist().rstrip("\n") + "\n", encoding="utf-8",
                             newline="\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
