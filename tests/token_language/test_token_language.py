#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Layout, rule and token-target tests for 2.0.4 (one skill, English instructions).

2.0.4 ships **one** skill: `SKILL.md`, written in English. It manages a Chinese
library, an English library or a mixed one — instruction language and document
language are independent concerns, and the tests are organised along that line:

1. **Layout** — exactly one skill document is discoverable; the Chinese optimized
   text survives only as a frozen benchmark sample under `tests/`.
2. **Rules** — every behavioural rule that must survive the rewrite is present in
   `SKILL.md`, and the identifiers it cites exist in the implementation.
3. **Scenarios** — a Chinese project and an English project both work under the
   English skill (init, health check, routing).
4. **Tokens** — the measured targets, the frozen baseline, and the fingerprint
   that makes a measurement reproducible.

What this file can *not* prove: that a real client (Codex, Claude Code) reading
`SKILL.md` will behave correctly on a Chinese library. That needs a client run;
see `SEMANTIC_CHECKLIST.md`, which keeps it explicitly unverified.

Set `KB_EMIT_CHECKLIST=1` to (re)generate `SEMANTIC_CHECKLIST.md`.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import shutil
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

# Every rule the specification requires to stay explicit in the shipped skill.
# One entry per rule, English needles only: there is no second skill to sync with.
RULES = [
    ("P0 never silently discarded",
     ["P0", "never silently discarded"]),
    ("P1 current state and next step",
     ["P1", "current state and next step"]),
    ("P2 workstream facts",
     ["P2", "workstream facts"]),
    ("P3 explicit fact IDs and evidence",
     ["P3", "fact IDs", "evidence"]),
    ("P4 bounded relevance",
     ["P4", "relevance"]),
    ("P0 fallback order",
     ["dashboard.constraints", "dashboard.safety", "AGENTS.md"]),
    ("P4 limits (blocks and budget share)",
     ["≤30%", "≤3 blocks"]),
    ("superseded fact handling",
     ["superseded", "include-superseded"]),
    ("gap reporting honest",
     ["Gaps and omitted content must be reported honestly", "report a gap"]),
    ("write requires current hash",
     ["sha256", "expected_sha256"]),
    ("lock conflicts not bypassed",
     ["LockHeld", "break-lock"]),
    ("multi-file writes not database-atomic",
     ["not database-level atomic"]),
    ("migration preserves source content",
     ["no body edits", "no evidence deleted"]),
    ("hooks never block a session",
     ["hooks never block a session", "always exit 0"]),
    ("no credentials committed",
     ["credentials"]),
    ("reference loading is not default",
     ["References are not default reading", "Load one only when"]),
    ("existing v2 projects keep working",
     ["Compatible with existing v2 projects"]),
    ("language independence declared",
     ["Instruction language and", "library language are independent"]),
    ("never auto-translate existing documents",
     ["Never translate existing documents"]),
]

# `changes.json` keys and operation names that the shipped skill and the protocol
# reference both cite; they must still exist in the implementation.
JSON_KEYS = ["schema_version", "expected_sha256", "operation", "section_id",
             "content", "fact_id"]
OPERATIONS = ["replace_section", "append", "update_fact"]

SECTION_ORDINALS = [str(i) for i in range(1, 10)]

# Strength-bearing sentences on the safety rules. If one of these is softened into
# "consider…" / "should…", the rule has been weakened even though the topic still
# appears — which is exactly the failure mode a keyword check would miss.
CRITICAL_SENTENCES = [
    ("P0 never dropped", "keep them and report the overrun"),
    ("no whole-file overwrite", "Never overwrite a whole file"),
    ("no blind retry", "Never retry a blind overwrite"),
    ("credentials", "No credentials may be committed"),
    ("lock not bypassed", "Lock conflicts are never bypassed silently"),
    ("atomicity not overstated", "not database-level atomic transactions"),
    ("hooks never block", "always exit 0"),
    ("language not auto-converted", "Never translate existing documents"),
]

GIT_ONLY_FLAGS = {"--oneline", "--short", "--all", "--amend"}


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


def help_text(script: str, *args) -> str:
    proc = subprocess.run([sys.executable, str(SCRIPTS / script)] + list(args) + ["--help"],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    return (proc.stdout or "") + (proc.stderr or "")


class SingleSkillLayout(unittest.TestCase):
    """2.0.4 ships one skill. A second discoverable skill is a defect, not a feature."""

    def test_root_has_exactly_one_skill_document(self):
        found = sorted(p.name for p in ROOT.glob("SKILL*.md") if p.is_file())
        self.assertEqual(found, ["SKILL.md"],
                         "the repository root must hold exactly one skill document")

    def test_no_skill_document_outside_root_and_tests(self):
        strays = []
        for path in ROOT.rglob("SKILL*.md"):
            rel = path.relative_to(ROOT).as_posix()
            if rel == "SKILL.md" or rel.startswith("tests/"):
                continue
            strays.append(rel)
        self.assertEqual(strays, [], "skill documents outside the allowed locations: %s" % strays)

    def test_frontmatter_is_valid(self):
        text = read(ROOT / "SKILL.md")
        self.assertTrue(text.startswith("---\n"), "frontmatter must open the file")
        head = text.split("---", 2)[1]
        self.assertIn("name: handoff-kb", head)
        self.assertEqual(len([ln for ln in head.splitlines() if ln.startswith("name:")]), 1,
                         "frontmatter must declare exactly one name")
        desc = tl.frontmatter_description(text)
        self.assertTrue(desc, "description must not be empty")
        self.assertIn("Do not use", desc, "scope exclusion missing from description")

    def test_benchmark_sample_is_frozen(self):
        """B is a measurement artefact: moving it must never become editing it."""
        self.assertTrue(tl.SAMPLE_B.is_file(), "benchmark sample B is missing")
        digest = hashlib.sha256(tl.SAMPLE_B.read_bytes()).hexdigest()
        self.assertEqual(digest, tl.SAMPLE_B_SHA256,
                         "sample B changed; every published structure/language split "
                         "was measured against these exact bytes")
        self.assertTrue(str(tl.SAMPLE_B).startswith(str(ROOT / "tests")),
                        "sample B must stay under tests/ so it cannot be installed")

    def test_chinese_references_are_kept_as_optional_reading(self):
        for name in tl.REF_NAMES:
            path = ROOT / "references" / ("%s.zh-CN.md" % name)
            self.assertTrue(path.is_file(), "optional Chinese reference missing: %s" % path.name)
        skill = read(ROOT / "SKILL.md")
        self.assertIn("*.zh-CN.md", skill,
                      "the skill must tell the agent that Chinese reference editions exist")


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

    def test_benchmark_samples_stay_structurally_comparable(self):
        """A → B must measure restructuring, B → C must measure language.

        That split only holds while B and C keep the same section order. This is a
        measurement-validity check on a test artefact, not a requirement that the
        shipped skill has a Chinese twin.
        """
        sample = read(tl.doc_path("B", "skill"))
        shipped = read(tl.doc_path("C", "skill"))
        self.assertEqual(section_ordinals(sample), SECTION_ORDINALS)
        self.assertEqual(section_ordinals(shipped), SECTION_ORDINALS)

    def test_shipped_skill_sections(self):
        shipped = read(ROOT / "SKILL.md")
        self.assertEqual(len(headings(shipped)), len(SECTION_ORDINALS),
                         "the shipped skill must have exactly 9 numbered sections")


class SkillRuleCoverage(unittest.TestCase):
    """Rules and identifiers: the skill's claims must match the implementation."""

    def test_every_rule_is_present(self):
        text = norm(read(ROOT / "SKILL.md"))
        missing = [label for label, needles in RULES
                   if not all(n in text for n in needles)]
        self.assertEqual(missing, [], "rules missing from SKILL.md: %s" % missing)

    def test_protocol_ids_are_consistent(self):
        """Every `dashboard.*` id cited by the skill must be reachable.

        Reachable means: defined by a template, or recognised by the P0 resolver as
        a legacy alias (`dashboard.safety` predates the current skeleton and is still
        honoured by `constraints.py`). An id that is neither is a typo in the skill.
        """
        dash = read(ROOT / "assets" / "00_baseline.md") + read(ROOT / "assets" / "05_dashboard.md") \
            + read(ROOT / "assets" / "en" / "00_baseline.md") \
            + read(ROOT / "assets" / "en" / "05_dashboard.md")
        resolver = read(SCRIPTS / "lib" / "constraints.py")
        skill = read(ROOT / "SKILL.md")
        cited = set()
        i = 0
        while True:
            i = skill.find("dashboard.", i)
            if i < 0:
                break
            j = i
            while j < len(skill) and (skill[j].isalnum() or skill[j] in "._"):
                j += 1
            cited.add(skill[i:j].rstrip("."))
            i = j
        self.assertTrue(cited, "the skill cites no dashboard section IDs at all")
        unreachable = [sid for sid in sorted(cited)
                       if sid not in dash and sid not in resolver]
        self.assertEqual(unreachable, [],
                         "ids cited by the skill that no template defines and no resolver "
                         "recognises: %s" % unreachable)

    def test_json_contract_matches_implementation(self):
        protocol = read(ROOT / "references" / "protocol-v2.md")
        write_py = read(SCRIPTS / "kb-write.py")
        for key in JSON_KEYS:
            self.assertIn(key, protocol, "protocol-v2.md lost the key %s" % key)
            self.assertIn(key, write_py, "kb-write.py no longer handles %s" % key)
        for op in OPERATIONS:
            self.assertIn(op, protocol, "protocol-v2.md lost the operation %s" % op)
            self.assertIn(op, write_py, "kb-write.py no longer implements %s" % op)

    def test_security_wording_did_not_decay(self):
        text = norm(read(ROOT / "SKILL.md"))
        softened = [label for label, sentence in CRITICAL_SENTENCES
                    if norm(sentence) not in text]
        self.assertEqual(softened, [],
                         "these rules were softened or dropped: %s" % softened)

    def test_reference_links_resolve(self):
        text = read(ROOT / "SKILL.md")
        for name in tl.REF_NAMES:
            rel = "references/%s.md" % name
            self.assertIn(rel, text, "reference link missing: %s" % rel)
            self.assertTrue((ROOT / rel).is_file(), "link target missing: %s" % rel)
        self.assertIn("references/protocol.md", text,
                      "historical protocol link missing")
        for target in ("references/protocol.md", "references/protocol-v2.md"):
            self.assertTrue((ROOT / target).is_file())

    def test_every_script_is_mentioned(self):
        mentioned = script_mentions(read(ROOT / "SKILL.md"))
        on_disk = {p.name for p in SCRIPTS.glob("kb-*.py")}
        self.assertEqual(mentioned - on_disk, set(),
                         "SKILL.md names scripts that do not exist: %s"
                         % sorted(mentioned - on_disk))
        self.assertEqual(on_disk - mentioned, set(),
                         "SKILL.md omits scripts that do exist: %s"
                         % sorted(on_disk - mentioned))

    def test_documented_flags_exist(self):
        combined = ""
        for script in sorted(p.name for p in SCRIPTS.glob("kb-*.py")):
            combined += help_text(script)
        for sub in ("read", "apply", "recover"):
            combined += help_text("kb-write.py", sub)
        for sub in ("install", "uninstall", "run"):
            combined += help_text("kb-hooks.py", sub)
        for sub in ("check",):
            combined += help_text("kb-handoff.py", sub)
        documented = flags(read(ROOT / "SKILL.md")) - GIT_ONLY_FLAGS
        missing = sorted(f for f in documented if f not in combined)
        self.assertEqual(missing, [], "flags documented but not implemented: %s" % missing)


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
        for label, root in (("zh", ROOT / "assets"), ("en", ROOT / "assets" / "en")):
            base = read(root / "00_baseline.md")
            for word in ("有效", "待核"):
                self.assertIn(word, base, "%s: status vocabulary lost (%s)" % (label, word))
            dash = read(root / "05_dashboard.md")
            for sid in ("dashboard.current", "dashboard.next", "dashboard.lines",
                        "dashboard.todo", "dashboard.constraints", "dashboard.summary"):
                self.assertIn(sid, dash, "%s: %s missing from dashboard template" % (label, sid))

    def test_chinese_templates_are_unchanged_from_v203(self):
        """The Chinese template set is still byte-identical to the frozen baseline."""
        manifest = json.loads(read(tl.BASELINE / "MANIFEST.json"))
        checked = 0
        for rel, entry in manifest["files"].items():
            if not rel.startswith("assets/"):
                continue
            live = ROOT / rel.replace("assets/", "assets/", 1)
            self.assertTrue(live.is_file(), "template missing: %s" % rel)
            self.assertEqual(hashlib.sha256(live.read_bytes()).hexdigest(), entry["sha256"],
                             "Chinese template changed: %s" % rel)
            checked += 1
        self.assertEqual(checked, len(tl.ASSET_NAMES))


class TokenTargets(unittest.TestCase):
    """Default loading cost must drop >=15% against v2.0.3 on the spec tokenizers.

    An exact encoder is an optional dependency. CI installs none, so on CI these
    tests skip with the missing encoder named in the reason — they are never
    silently absent, and everything here is reproducible on any machine that has
    `tiktoken` (and optionally the DeepSeek offline tokenizer) installed:

        python tests/token_language/run_token_benchmark.py --all
    """

    @classmethod
    def setUpClass(cls):
        cls.counters = {}
        for name in tl.BASELINE_TOKENIZERS:
            try:
                cls.counters[name] = tokenlib.TokenCounter(name)
            except tokenlib.TokenizerError:
                cls.counters[name] = None
        cls.manifest = json.loads(read(tl.BASELINE / "MANIFEST.json"))

    SPEC_TOKENIZERS = tl.SPEC_TOKENIZERS
    BASELINE_TOKENIZERS = tl.BASELINE_TOKENIZERS

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
        for name, counter in self.available(self.BASELINE_TOKENIZERS).items():
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

        Covers all three exact vocabularies, not just the two the 15% gate uses:
        `BASELINE_TOKENIZERS` is a separate set on purpose, so "DeepSeek is not
        required to hit 15%" never turns into "DeepSeek is not verified at all".
        A missing vocabulary skips that vocabulary only.
        """
        for name, counter in self.available(self.BASELINE_TOKENIZERS).items():
            for rel, entry in sorted(self.manifest["files"].items()):
                path = tl.BASELINE / rel
                with self.subTest(tokenizer=name, path=rel):
                    data = path.read_bytes()
                    self.assertEqual(len(data), entry["bytes"])
                    self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"])
                    self.assertIn(name, entry["tokens"],
                                  "baseline manifest has no %s count for %s" % (name, rel))
                    self.assertEqual(counter.count(read(path)), entry["tokens"][name],
                                     "%s: baseline token count drifted" % rel)

    def test_zero_denominator_is_explicit(self):
        self.assertIsNone(tl.saving(0, 10))
        self.assertEqual(tl.saving(10, 5), 0.5)


class TokenizerFingerprint(unittest.TestCase):
    """A count is only evidence if the vocabulary behind it can be identified."""

    def test_is_exact_matches_every_counter(self):
        cases = [("cl100k_base", True), ("o200k_base", True),
                 ("deepseek_v4", True), ("deepseek_estimate", False),
                 ("heuristic", False)]
        for name, expected in cases:
            try:
                counter = tokenlib.TokenCounter(name)
            except tokenlib.TokenizerError:
                self.skipTest("encoder %s not installed in this environment" % name)
            with self.subTest(tokenizer=name):
                self.assertEqual(counter.exact, expected)
                self.assertEqual(tokenlib.is_exact(counter.desc), expected,
                                 "is_exact() disagrees with the counter for %r" % name)

    def test_is_exact_rejects_estimates_by_prefix(self):
        self.assertFalse(tokenlib.is_exact(tokenlib.HEURISTIC_DESC))
        self.assertFalse(tokenlib.is_exact(tokenlib.DEEPSEEK_DESC))
        self.assertFalse(tokenlib.is_exact("deepseek_estimate（回退；exact=false）"))
        self.assertTrue(tokenlib.is_exact("tiktoken:o200k_base"))
        self.assertTrue(tokenlib.is_exact("tokenizers:deepseek_v4"))

    def test_no_absolute_path_in_counter_description(self):
        home = os.path.expanduser("~")
        for name in tl.TOKENIZERS:
            try:
                counter = tokenlib.TokenCounter(name)
            except tokenlib.TokenizerError:
                continue
            with self.subTest(tokenizer=name):
                blob = json.dumps(counter.as_dict(), ensure_ascii=False)
                self.assertNotIn(home, blob, "counter metadata leaked the home directory")
                self.assertNotIn(":\\", blob, "counter metadata leaked a drive path")
                self.assertNotIn("/.cache/", blob, "counter metadata leaked a cache path")

    def test_deepseek_fingerprint_is_complete(self):
        try:
            counter = tokenlib.TokenCounter("deepseek_v4")
        except tokenlib.TokenizerError:
            self.skipTest("deepseek_v4 tokenizer not installed")
        info = counter.as_dict()
        self.assertEqual(info["tokenizer_file"], "tokenizer.json")
        self.assertRegex(info["tokenizer_sha256"] or "", r"^[0-9a-f]{64}$",
                         "the vocabulary hash is what makes two runs comparable")
        self.assertEqual(info["library"], "tokenizers")
        self.assertTrue(info["library_version"])
        self.assertTrue(info["exact"])

    def test_report_markdown_has_no_personal_path(self):
        import run_token_benchmark
        home = os.path.expanduser("~")
        for name in ("heuristic", "deepseek_v4"):
            try:
                report = run_token_benchmark.measure(name)
            except tokenlib.TokenizerError:
                continue
            with self.subTest(tokenizer=name):
                text = run_token_benchmark.markdown(report)
                self.assertNotIn(home, text)
                self.assertIn("exact", text)


class NoSilentFallback(unittest.TestCase):
    def test_unknown_tokenizer_raises(self):
        with self.assertRaises(tokenlib.TokenizerError):
            tokenlib.TokenCounter("definitely-not-an-encoder")

    def test_deepseek_estimate_is_labelled(self):
        counter = tokenlib.TokenCounter("deepseek_estimate")
        self.assertFalse(counter.exact)
        self.assertIn("estimate", counter.desc.lower())

    def test_explicit_encoder_without_vocabulary_exits_2(self):
        """A CLI asked for an exact encoder must fail loudly, not downgrade."""
        env = dict(os.environ)
        env["KB_DEEPSEEK_TOKENIZER"] = str(HERE / "nonexistent-tokenizer")
        env["PYTHONIOENCODING"] = "utf-8"
        cmd = [sys.executable, str(SCRIPTS / "kb-benchmark.py"),
               "--target", str(PAIRED / "zh"), "--loose", "--tokenizer", "deepseek_v4"]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env)
        self.assertEqual(proc.returncode, 2,
                         "missing encoder must exit 2, got %d\n%s"
                         % (proc.returncode, proc.stderr[-400:]))
        self.assertIn("ERR", proc.stderr)

    def test_explicit_fallback_must_be_requested(self):
        env = dict(os.environ)
        env["KB_DEEPSEEK_TOKENIZER"] = str(HERE / "nonexistent-tokenizer")
        env["PYTHONIOENCODING"] = "utf-8"
        cmd = [sys.executable, str(SCRIPTS / "kb-benchmark.py"),
               "--target", str(PAIRED / "zh"), "--loose", "--tokenizer", "deepseek_v4",
               "--allow-tokenizer-fallback"]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        self.assertIn("exact=false", proc.stdout,
                      "a fallback must label itself as an estimate in the output")


class CrossLanguageScenarios(unittest.TestCase):
    """The English skill must manage a Chinese library, an English one, and a mixed one."""

    def run_script(self, script, *args, cwd=None):
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return subprocess.run([sys.executable, str(SCRIPTS / script)] + [str(a) for a in args],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=str(cwd) if cwd else None, env=env)

    def test_chinese_project_passes_health_check(self):
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

    def test_chinese_project_is_not_translated(self):
        """Reading a Chinese library must not rewrite its prose language."""
        root = PAIRED / "zh"
        before = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in root.rglob("*") if p.is_file()}
        proc = self.run_script("kb-context.py", "--target", root, "--loose",
                               "--task", "查看当前状态", "--budget", "2500")
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        after = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in root.rglob("*") if p.is_file()}
        self.assertEqual(before, after, "a read-only routing run modified the library")

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

        en_files = sorted(p.relative_to(target).as_posix()
                          for p in target.rglob("*") if p.is_file() and ".git" not in p.parts)
        zh_files = sorted(p.relative_to(zh_target).as_posix()
                          for p in zh_target.rglob("*") if p.is_file() and ".git" not in p.parts)
        self.assertEqual(en_files, zh_files,
                         "both --lang values must scaffold the same file set")


def emit_checklist() -> str:
    skill = norm(read(ROOT / "SKILL.md"))
    lines = ["# Semantic checklist — 2.0.4 (one skill, English instructions)", "",
             "Automated layer: `test_token_language.py` (layout, rules, identifiers, "
             "scenarios, token targets).",
             "This sheet is the human review that remains after the automated checks.", "",
             "| # | Rule | In `SKILL.md` | Reviewer |", "|---|---|---|---|"]
    for i, (label, needles) in enumerate(RULES, 1):
        state = "ok" if all(n in skill for n in needles) else "**missing**"
        lines.append("| %d | %s | %s | |" % (i, label, state))
    lines += ["", "## Verified automatically", "",
              "- One discoverable skill; no second skill document outside `tests/`.",
              "- Frontmatter name/description; 9 numbered sections.",
              "- Every `scripts/kb-*.py` named in the skill exists, and every script that "
              "exists is named.",
              "- Every documented `--flag` is implemented (`--help` of each script and "
              "subcommand).",
              "- `changes.json` keys and operation names exist in `kb-write.py`.",
              "- Every cited `dashboard.*` id is either defined by a template or "
              "recognised by the P0 resolver as a legacy alias.",
              "- Chinese project / English project: `kb-check` clean, `kb-context` routes, "
              "`kb-init --lang {zh,en}` scaffold the same file set.",
              "- Vocabulary fingerprint (file name, SHA256, library version) present and "
              "free of personal paths; a missing encoder exits 2.",
              "",
              "## Manual review points", "",
              "- [ ] Every protocol identifier, command and JSON key in `SKILL.md` matches "
              "the implementation, not just the reference text.",
              "- [ ] Error conditions and exit codes in `SKILL.md` match the implementation.",
              "- [ ] The eight strength-bearing sentences the test pins still read as "
              "prohibitions after any rewording (Never / no … may, not should / consider).",
              "- [ ] Chinese templates and the four Chinese references are still "
              "byte-identical to v2.0.3.",
              "",
              "## Not verified — do not claim otherwise", "",
              "- [ ] A real client (Codex / Claude Code) reading this English skill while "
              "maintaining a Chinese library. The *CLI* cross-language path is covered by "
              "tests above; the *agent following the instructions* has not been run in a "
              "real client.",
              "- [ ] The English template set after months of use in a long-lived English "
              "library.",
              ""]
    return "\n".join(lines) + "\n"


def setUpModule():
    if os.environ.get("KB_EMIT_CHECKLIST") == "1":
        CHECKLIST.write_text(emit_checklist().rstrip("\n") + "\n", encoding="utf-8",
                             newline="\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
