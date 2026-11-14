# Changelog

Tool version and protocol version move independently: a tool upgrade never changes
`<!-- kb:schema: 2 -->` and never requires an existing library to migrate. The long
Chinese chronicle — what each defect did on a real library, before/after numbers —
is in [`README.zh-CN.md`](README.zh-CN.md) §17.

## 2.0.4 — 2026-11-14

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
  token targets, no-silent-fallback, cross-language scenarios (55 cases).
- `tests/test_deps_check.py` — tests the dependency checker itself (32 cases).

### Fixed

- `TokenCounter` kept the requested tokenizer in `count()` instead of the effective
  one. With `deepseek_v4` / `deepseek` and an explicitly allowed fallback the report
  said `deepseek_estimate` while the numbers came from `heuristic()`. `count()` now
  dispatches on a separate `mode`, and every report carries `effective_mode`
  alongside the untouched `requested` value.
- `tests/deps_check.py` treated any import inside a `try` body as guarded, so
  `try/finally` and `except ValueError` passed. It now inspects the handlers and
  accepts only those that can catch an import failure.
- The checker matched exception names on the last attribute segment only, so
  `except local_lib.ImportError` counted as a guard even though it is a different
  class that merely shares the name. A handler now needs a bare name (`ImportError`)
  or an explicit `builtins.` prefix; `except builtins.ImportError`, tuples and bare
  `except` still pass, and aliased modules stay rejected on purpose.
- `STDLIB_LATE` (`tomllib`) bypassed both the scope and the handler rule: on 3.10 it
  was reported as third-party, on 3.12+ it was exempted outright. It is now checked
  before the standard-library exemption and must sit inside a function behind an
  import-error handler, on every interpreter version.
- `tests/token_language` skipped the whole exact-tokenizer loop when the first
  vocabulary was missing, hiding the vocabularies that were installed; each
  vocabulary is now its own test with its own skip reason.
- Four Chinese reference documents were only checked for existence. Their SHA256 is
  now compared against the frozen v2.0.3 copies.
- `kb-init --lang en` without `--lines` generated Chinese workstream file names
  (`10_线A.md`). `--lines` now defaults per `--lang`; an explicit list always wins.

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
- Measured gains (whole `SKILL.md`, frontmatter included): 28.1% on `cl100k_base`,
  15.4% on `o200k_base`, 9.5% on `deepseek_v4`. The 15% target is defined on the
  first two; DeepSeek's Chinese-heavy vocabulary is held to "must not grow".
  Reported as measured, not rounded up.

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
