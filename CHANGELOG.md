# Changelog

Tool version and protocol version move independently: a tool upgrade never changes
`<!-- kb:schema: 2 -->` and never requires an existing library to migrate. The long
Chinese chronicle — what each defect did on a real library, before/after numbers —
is in [`README.zh-CN.md`](README.zh-CN.md) §17.

## 2.0.4 — unreleased

Still on `feat/2.0.4-english-skill-token-benchmark` (PR #5). No tag, no release.

### Added

- `assets/en/` — 12 English templates with the same placeholders and the same
  `kb:id` set as the Chinese ones. Protocol status vocabulary (`有效` / `待核` /
  `已作废`) stays literal in both, because it is protocol data, not prose.
- `scripts/kb-init.py --lang {zh,en}` — selects the template set and localizes the
  generated table headers, route separator, initial status, shard section,
  `CLAUDE.md` / `GEMINI.md` pointer and self-check stub. `--lang zh` is the default.
- `TokenCounter` gains `deepseek_v4` (official offline `tokenizer.json`, exact) and
  `deepseek_estimate` (documented ratio 0.3 / 0.6, always labelled an estimate).
- Every counter reports a fingerprint — source, vocabulary file name, vocabulary
  SHA256, library version — with no personal path, so two reports can be proved to
  have used the same vocabulary.
- `tests/token_language/` — A/B/C measurement, frozen v2.0.3 baseline reproduced
  against all three exact vocabularies, rule and identifier checks, template parity,
  token targets, no-silent-fallback, cross-language scenarios (40 cases).
- `tests/test_deps_check.py` — tests the dependency checker itself (11 cases).

### Changed

- `SKILL.md` rewritten in English as **9 numbered sections**, and it now states in
  its opening block that instruction language and library language are independent:
  an English skill manages a Chinese library, an English one, or a mixed one.
- `references/*.md` are English. The Chinese originals were moved to
  `references/*.zh-CN.md` **byte for byte** and remain available as optional
  reading — same protocol IDs, commands, JSON shapes and exit codes.
- `tests/deps_check.py` walks the **full AST** instead of module-level imports, and
  requires optional imports to sit inside a function **and** inside `try/except`.
  `tokenizers` joined `tiktoken` as a declared optional dependency.

### Removed

- `SKILL.zh-CN.md` is no longer shipped. 2.0.4 has exactly one skill. The optimized
  Chinese text survives only as `tests/token_language/sample_b/SKILL.zh-CN.md`, the
  B sample of the token benchmark, byte-frozen by a SHA256 assertion so "move the
  file" cannot silently become "edit the file and invalidate the numbers".

### Compatibility

- Protocol stays `2`. Document IDs, reserved filenames, section IDs, command
  arguments, `changes.json` schema and migration behaviour are untouched.
- An existing Chinese library needs no migration and is read exactly as before;
  `--lang zh` remains the default for `kb-init`.
- Measured gains (`SKILL.md` body): 27.9% on `cl100k_base`, 15.2% on `o200k_base`,
  9.2% on `deepseek_v4`. The 15% target is defined on the first two; DeepSeek's
  Chinese-heavy vocabulary is held to "must not grow". Reported as measured, not
  rounded up.

## 2.0.3

- P0 falls back level by level instead of returning at the first invalid ID.
- H1 deduplication compares the body sentence by sentence; short sentences are
  judged by task relevance; a preamble mixed with a fact is split at the comma.

## 2.0.2

- Quality-gate rounding is `ceil`, not `round` (6.4 must not become 6).
- "Recent records" counting accepts list items and `[YYYY-MM-DD HH:MM]` lines.
- `--loose` treats numbered books such as `20`–`50` as fact lines.
- Six assembly-layer and five judgment-layer defects fixed.

## 2.0.1-hotfix

- Path, symlink and transaction hardening; hook protocol fixes; fact-ID
  immutability; P4 containment; withdrawn numbers.

## 2.0.0

- Layered library, protocol v2, budget-aware context routing, hash-verified writes,
  handoff grading, lossless v1 → v2 migration.
