# handoff-kb 2.0.4

> **Tool version** `2.0.4` (script behavior) | **Protocol version** `2` (document layout, `<!-- kb:schema: 2 -->`).
> The two are independent: a tool upgrade does not change the protocol and does not require an existing library to migrate.

Chinese edition: [`README.zh-CN.md`](README.zh-CN.md) (full manual and version chronicle).

**A layered handoff library for projects with parallel sessions.** One Markdown protocol plus ten zero-dependency Python scripts, so that a project with "context almost full, several workstreams moving at once, documents piling up" only has to read a fixed small slice when a new session takes over — instead of re-reading the whole library.

2.0 is not about adding scripts. It makes four things real: **budget-aware context retrieval, evidence-backed handoff, hash-verified writes, tests that actually run**. Still plain text, diffable, no service, no embeddings, no SQLite.

```
take over → kb-context (smallest context within budget) → work → kb-write (hash-verified write-back) → kb-handoff (handoff self-check)
```

---

## 1. What it solves (an arithmetic problem, not a style problem)

Chinese UTF-8 runs roughly 4.5 bytes per token; English roughly 4 characters per token, and a translation needs about 2.5–3× the characters of the Chinese original. Either way, reading everything costs linearly in total library size, while **the information that actually decides handoff quality** (what is happening now, what is next, what not to do) is usually under 20 KB.

The answer is not "write thinner documents". It is **decoupling storage from reading**: the total may grow, the per-session mandatory set stays constant.

Two kinds of numbers, never mixed:

| Scenario | Result | Basis |
|---|---|---|
| Real router project (v1 era) | library 1,759 lines / 221 KB → handoff 20.6 KB (`05`+`00`), −90% | actual file size, not an estimate |
| Synthetic fixture (2.0.1-hotfix benchmark) | A full 3,082 / B `00+05` 389 / C routed 454 tokens, tasks 10/10, quality items 63/63 | `heuristic` **estimate**, fixture ~11 KB |
| Desensitized FFRS fixture (custom naming, `--loose`) | A 1,248 / B 446 / C 561 tokens (−55% vs A) | same estimate, all content fictional |

The first two rows are reproducible with two commands (`py tests/make_fixture.py ../kbdemo` → `py scripts/kb-benchmark.py --target ../kbdemo`). **Note that C (454) is not smaller than B (389) on this fixture**: C includes packaging (title / source / reason / gap), B is just `00+05` verbatim; the fixture is too small, so packaging overhead fills the budget. What matters is the 85% against A — A is the "read everything" cost. Definitions and per-task detail: `references/benchmark.md`.

English-edition numbers are in §12.2 and `tests/token_language/out/token-benchmark-all.md`. They are measured, and the shortfall against the 15% target on DeepSeek's own vocabulary is reported rather than hidden.

---

## 2. When to use it, when not to

| Your situation | What to do |
|---|---|
| One session, task done, next session just needs a handover note | **Do not use this** — write a 6-line handoff |
| Fewer than 3 documents, no parallel sessions, one-off task | **Do not use this** |
| Several workstreams + parallel sessions + context fills up + long-term maintenance | Use it, `kb-init.py` |
| Old project already has a pile of documents (`00/05/06/90` or custom names) | Use it: `kb-check.py --loose` to diagnose → `kb-migrate.py` for incremental migration |

```text
Take over [task], working directory [DIR].
Done: [1–2 lines]
In progress / blocked: [1 line]
Next: [1 line]
Related files / commits: [paths or git log -3]
Do not repeat: [1 line, delete if none]
```

---

## 3. Language: one skill, any library language (new in 2.0.4)

2.0.4 ships **one** skill — `SKILL.md`, written in English. Its instruction language is not the library's language, and the two are chosen independently. **Pick the template set by the project's existing documents, not by the operator's language.**

| Situation | Templates | What the agent reads |
|---|---|---|
| Chinese project (docs already in Chinese) | `assets/` — the default, `--lang zh` | English skill + Chinese documents |
| English project (docs already in English) | `assets/en/` — `--lang en` | English skill + English documents |
| Mixed legacy project | **Keep the dominant language of the existing documents**; convert nothing | English skill + whatever is already there |
| New project, no documents yet | Ask once, or follow the user's message language | English skill + the chosen template set |

Hard rules:

- **Never auto-translate existing content.** The templates, the protocol status vocabulary (`有效` / `待核` / `已作废`), the reserved filenames (`00_基线.md`, `05_进度仪表盘.md`, …) and the `kb:id` values are protocol data, not prose. An English project still uses the protocol's literal status words and IDs; a Chinese project still gets Chinese filenames.
- **The instructions stay English whatever the library language is.** An agent maintaining a Chinese library reads English instructions and writes Chinese documents — the two never have to match.
- **One library, one language for its prose.** Mixing two prose languages inside one library doubles retrieval noise without adding information.
- **The choice is per library, not global, and almost no CLI flag carries it.** `kb-context` / `kb-check` / `kb-write` are language-agnostic and take no `--lang`; only `kb-init` does, because only scaffolding needs a template set.

`kb-init.py --lang {zh,en}` selects the template set. Both produce the **same 17 files with the same relative paths, the same placeholders and the same `kb:id` set**; a parity test enforces it (`tests/token_language/test_token_language.py::TemplateParity`).

Chinese **reference** editions (`references/*.zh-CN.md`) ship as optional reading, with the same protocol IDs, commands, JSON shapes and exit codes as the English ones. They are reference material, not a second skill: `SKILL.md` is the only discoverable skill document, and a test asserts it.

One consequence worth naming: an English project still gets `新会话启动消息.txt` for its copy-paste startup note, because that path is part of the skeleton's fixed slot. It is not protocol data and no script requires the name; the reason for keeping it uniform is that a language-dependent filename would make the parity test compare slot sets instead of literal paths, and the literal-path check is the one that catches a genuinely missing file. Rename it locally if it bothers you — nothing breaks.

---

## 4. Layered model

| Layer | File | Holds | Change rate | Required on handoff |
|---|---|---|---|---|
| L0 entry | `AGENTS.md` (+ `CLAUDE.md` / `GEMINI.md` pointers) | what to read, how to write. **Never holds current values** | rare | read |
| L1 facts | `00` shared page (`K-xx` + status + evidence) + `10–17` per-line books | current values / criteria / commands / pitfalls | occasional | by line |
| L2 state | `05_进度仪表盘.md` (`kb:id` sections) | state / next step / line status / backlog / hard constraints | frequent | **required** |
| L3 journal | `06_会话日志.md` (old volumes read-only) + `06_流水/<line>.md` | append-only timeline | each line writes only its own | only for archaeology |
| L4 archive | `90_过程档案.md` + `归档/` | process evidence / verification snapshots / version archaeology | only when folding | not required |

**Numbering contract**: `00/05/06/90` are reserved layers; new fact books use **10–17** (max 8 lines); an old library's `01–04` stays legal, **migration never renames**. `K-xx` / `G-xxx` and section `kb:id` values are retired, never reused.

**One writer, one file**: `06_流水/<line>.md` removes read-modify-write collisions on a shared single file at the root; the conflict signal is `git status` plus the hash check in `kb-write.py`.

---

## 5. One-command initialization

**Requirements**: Python 3.10+, **standard library only**. Two optional dependencies exist, both for exact token counting and both imported inside a function under `try/except`:

| Optional | Gives | Without it |
|---|---|---|
| `tiktoken` | `--tokenizer cl100k_base` / `o200k_base`, exact BPE counts | requesting one exits **2**; `heuristic` still works |
| `tokenizers` + DeepSeek's `tokenizer.json` | `--tokenizer deepseek_v4`, exact counts on DeepSeek's own vocabulary | requesting it exits **2**; `deepseek_estimate` applies the documented ratio |

Nothing degrades silently: an explicitly requested encoder either works or exits 2, and `--allow-tokenizer-fallback` is the only way to accept an estimate (which then labels itself `exact=false`). `tests/deps_check.py` walks the full AST of every script and fails on any third-party import outside this table, at module level, or outside `try/except`; `tests/test_deps_check.py` tests the checker itself so a new dependency cannot slip in unnoticed.

```bash
KB="$HOME/.skills-manager/skills/handoff-kb"   # your install path
python "$KB/scripts/kb-init.py" \
    --target "$HOME/projects/new-project" --project "new-project" \
    --lines "firmware,runtime,server,throughput" --lang en
```

```powershell
$KB = "$HOME\.skills-manager\skills\handoff-kb"
py "$KB\scripts\kb-init.py" --target "$HOME\projects\新项目" --project "新项目" `
    --lines "固件,运行态,服务端,测速"            # 中文项目：省略 --lang（默认 zh）
```

Generates `AGENTS.md` / `CLAUDE.md` / `GEMINI.md`, `00_基线.md`, `10..17_<line>.md`, `05_进度仪表盘.md` (with `kb:id`), `06_会话日志.md` + `06_流水/*.md`, `90_过程档案.md`, a startup message, `.gitignore` / `.gitattributes`, a self-check script stub, and `归档/`.

Safety boundary (not optional advice):

- `--plan` only prints the create/skip/overwrite list, **writes nothing**.
- It auto-runs `git init` + first commit **only when neither the target nor its parent is already inside a git repository**; an existing repository is never nested into and never auto-committed.
- It only ever `git add -- <whitelist generated this run>`, **never** `git add -A`; if a non-whitelisted file appears in the index it `git reset`s and fails.
- A sensitive-information hit → refuses to commit, returns non-zero; `--force` **does not bypass** the credential check.
- `.gitignore` / `.gitattributes` / `AGENTS.md` are protected configuration; overwriting them requires `--force --overwrite-config`.
- Duplicate line names (after case / Unicode folding), reserved names (`其他`), an `NN_` prefix, or more than 8 lines → rejected outright.

```
--no-git  generate files only      --force  overwrite templates (not protected config)
--shards auto|none                 auto = one shard per line (default); none = single 06
--lang zh|en                       template language (default zh)
--json    machine readable
```

---

## 6. Migrating an old library (v1 → v2, lossless)

```bash
python "$KB/scripts/kb-check.py"   --target ./old --loose      # read-only diagnosis first
python "$KB/scripts/kb-migrate.py" --target ./old --plan       # writes .kb-migrate-plan.json
python "$KB/scripts/kb-migrate.py" --target ./old --apply      # verifies source hashes, then writes
```

Incremental only: adds `<!-- kb:schema: 2 -->` and `kb:id` to known sections. It does not rename `01–04`, does not reorder sections, does not rewrite prose, does not delete evidence. The plan is bound to source file hashes — if another session changed a file, the apply is refused; re-run `--plan`. Repeating a migration is idempotent.

---

## 7. New-session recovery: context within a budget

```bash
python "$KB/scripts/kb-context.py" --target . --task "debug NSS network issue" --budget 3000 --explain
python "$KB/scripts/kb-context.py" --target . --loose --task "current project status"   # custom naming
```

Assembly order (high → low):

```
P0 hard constraints (dashboard.constraints / AGENTS constraints)  ← never trimmed by any budget
P1 state + next step (dashboard.current / dashboard.next)
P2 this line's facts  (fact.current / fact.commands / fact.pitfalls)
P3 baseline hit lines + evidence pointers + cross links (change A, B is affected)
P4 the rest by relevance (≤ 30% of budget, ≤ 3 blocks; journal/archive down-weighted)
```

- Default budget 3000; `--format json` for CI / hooks, `--explain` says why each block was chosen.
- When the budget is short, **mandatory blocks stay** and an "over budget" line plus a `skipped` list is printed — hard constraints are never silently dropped.
- No hits at all → prints the gap list and points you at `kb-search`; it **never invents context**.
- Tokens default to the `heuristic` estimate (CJK 1 char ≈ 1 token, other 4 chars ≈ 1 token). With `tiktoken` installed and `--tokenizer cl100k_base` you get a real encoding, and the output always names which one was used. `--tokenizer deepseek_v4` uses DeepSeek's official offline tokenizer (see §12).

---

## 8. Search and section-level reading

```bash
python "$KB/scripts/kb-search.py"  --target . --query "NSS network issue" --limit 5
python "$KB/scripts/kb-outline.py" --file 05_进度仪表盘.md --section-id dashboard.next
python "$KB/scripts/kb-outline.py" --file 05_进度仪表盘.md --find 磁盘
```

- Search scans Markdown directly (no index service): Chinese approximates by "whole run + bigrams", English is case-insensitive; score order = exact ID / fact ID line > filename / workstream > heading > body; journal down-weighted, archive and retired lines excluded by default.
- It returns locations only (file / section ID / line / 160-char snippet / score / hash / token estimate); read the body with `kb-outline.py`.
- If `--hash` is supplied it is verified: a changed document is refused (exit 2), so a stale outline cannot deliver the wrong section.

---

## 9. Safe write-back (hash + lock + transaction)

```bash
python "$KB/scripts/kb-write.py" read  --target . --file 05_进度仪表盘.md --json
python "$KB/scripts/kb-write.py" apply --target . --changes changes.json --dry-run
python "$KB/scripts/kb-write.py" apply --target . --changes changes.json
python "$KB/scripts/kb-write.py" recover --target . [--dry-run|--apply] [--break-lock]
```

`changes.json` (protocol-fixed `schema_version: 1`):

```json
{
  "schema_version": 1,
  "updates": [
    {"path": "05_进度仪表盘.md", "expected_sha256": "<64 hex>",
     "operation": "replace_section", "section_id": "dashboard.current",
     "content": "<new section body>"},
    {"path": "06_流水/固件.md", "expected_sha256": "<64 hex>",
     "operation": "append", "content": "- [2026-11-11 01:00] firmware ... → next"},
    {"path": "00_基线.md", "expected_sha256": "<64 hex>",
     "operation": "update_fact", "fact_id": "K-02",
     "content": "| K-02 | channel | 157 | 有效 | `iwinfo` | 2026-11-11 |"}
  ]
}
```

- Every write must carry a **full 64-hex** `expected_sha256`; a mismatch is `CONFLICT` — no overwrite, the current hash is reported, you re-read.
- Cross-platform directory lock (atomic mkdir + liveness probe): a live process's lock is not stolen; a dead process's lock is reclaimed with a note on stderr; explicit unlock is `recover --break-lock`.
- Multiple files: **validate all → back up → `os.replace` one by one → roll back on failure**; a journal lets `recover` classify each file afterwards (written / not written / changed by someone else) and refuses to auto-recover when there is a conflict.
- Single-file writes use a temp file in the same directory plus `os.replace`, preserving the original newline style (no whole-file CRLF churn).
- Path limits: workspace-relative paths only; absolute paths, `..`, symlink escapes and non-`.md`/`.txt` are rejected.

**Honest statement**: several `os.replace()` calls are not a cross-file atomic transaction. What is offered is "full pre-check + backup + rollback on failure + post-crash recovery". Git remains the final audit and rollback mechanism.

---

## 10. Handoff check (evidence first)

```bash
python "$KB/scripts/kb-handoff.py" check  --target . --strict
python "$KB/scripts/kb-handoff.py" check  --target . --loose   # fall back to headings when kb:id is absent
python "$KB/scripts/kb-handoff.py" report --target . --json
```

Grades eight questions: current task / what was actually completed / evidence / unverified items / blockers / next step / affected files / operations not to repeat.

- Template placeholders (`[填]` / `TODO`) count as **unverified**, not done.
- A baseline entry marked `有效` without evidence → unverified; it is never auto-promoted to "verified".
- `--strict` fails on any unverified item (exit 1), suitable for a wrap-up pipeline.

---

## 11. Health check

```bash
python "$KB/scripts/kb-check.py" --target .                  # human readable
python "$KB/scripts/kb-check.py" --target . --strict         # WARN also fails
python "$KB/scripts/kb-check.py" --target . --loose          # custom naming
python "$KB/scripts/kb-check.py" --target . --json           # CI / hooks
python "$KB/scripts/kb-check.py" --target . --mode template  # freshly initialized empty template
```

Checks: required files (exact name first, no `05_*.md` globbing), layer sizes and handoff cost, threshold hits, `K-xx` duplicate / undefined-reference / retired-reference / cyclic-retirement, `kb:id` duplicates and illegal formats, fact evidence and verification age, table column counts, leftover TODO, plaintext credentials, uncommitted git changes. ERROR > 0 exits 1.

Size statistics are reported **in two layers**: body (excluding `归档/`) and archive counted separately, with handoff cost computed on the body only; data directories (`AI_files/`, `assets/`, `data/`, `output/`, `evidence/`, `unpack/`, `_tmp/`, `node_modules/`, `build/`, …) and text files over 2 MB are skipped. An archive more than 3× the body size raises a WARN — it is time to fold.

Numbering checks accept "definition positions": heading start, list start, table first column, **across files** (`## G-010 …` is a definition); a mention inside a sentence is a reference. Under `--loose`, an undefined reference is downgraded to WARN, so a custom-naming project does not open with 10 ERRs. `--loose` also treats numbered books like `20_数据` / `30_mod开发` / `50_死路与坑` as fact lines (aliases are matched first; `60_进度` etc. keep their own roles).

---

## 12. Tests and benchmarks

```bash
python -m unittest discover -s tests        # 392 tests (341 existing + 40 token_language + 11 deps_check)
python tests/smoke.py                       # end to end: init→check→search→context→handoff→write→migrate
python tests/deps_check.py                  # scripts/ must not import outside the standard library
python scripts/kb-benchmark.py --target . --report markdown
python tests/token_language/run_token_benchmark.py --all --out tests/token_language/out
```

- The existing suite covers lock ownership / dead-lock reclamation / never stealing an incomplete lock, transaction rollback and journal checksums, `recover` three-state, migration plan bound to hashes and `root_id`, path escapes and symlink pruning, the three fact definition positions and index-page pointers, retirement chains and immutable IDs, multi-workstream assembly and budget convergence, P3/P4 containment, `--loose` custom naming (numbered-book fallback and candidate down-weighting), agent directories excluded from retrieval, P4 scoring only on own body text, the P4 insertion boundary and `p4_facts`, the three-level P0 fallback (including symlink escapes and placeholders), fenced content excluded from counts, hook preview writing nothing / multi-file rollback / official event structures, real subprocess concurrency and fault injection, benchmark metrics and quality gates, content-level dedupe and duplicate-loading metrics, single-fact books and the `--line` fallback, container 599/600/601 boundaries, haiku-preamble demotion (sentence-by-sentence body comparison / short sentences by task relevance / preamble-and-fact mixed sentences).
- `tests/fixtures/ffrs/` is a desensitized "custom naming" fixture (`60_进度.md` / `61_流水.md` / `60_流水/`), all fictional, used to prove `--loose` is equivalent to standard naming; `tests/fixtures/plain/` is an ordinary numbered library (`00/05/20/30/40/50`, no `kb:id`, no fact structure), used to prove "looks like a book" ≠ "contains facts".
- CI: `.github/workflows/test.yml`, Ubuntu + Windows × Python 3.10 / 3.12 / 3.13, no network, no credentials, standard library only (`tiktoken` and `tokenizers` are the declared optional imports, and must sit inside a function under `try/except`).

### 12.1 Benchmark (routing quality)

Compares A full / B `00+05` / C routed across 10 fixed tasks (one is an error path, listed separately, excluded from the mean); A/B/C go through the same `TokenCounter`; it reports 10 quality metrics of which 5 are hard gates (constraints preserved, error path refused, budget reported honestly, no silent workstream omission, counter consistency), immune to averaging; the task pass threshold (80%) rounds **up** (8 tasks require 7, since `round()` would turn 6.4 into 6).

### 12.2 Bilingual token benchmark (new in 2.0.4)

Three variants: **A** original Chinese v2.0.3 (frozen) · **B** optimized Chinese v2.0.4 — **a benchmark sample, not a shipped skill** · **C** the shipped English v2.0.4 skill.
`structure = 1 − B/A`, `language = 1 − C/B`, `total = 1 − C/A`. A zero denominator is reported explicitly, never as 0%.

**The total is a language gain, not a structural one.** `structure` lands at −1.3% / −0.9% / +0.1% across the three exact vocabularies: restructuring the prose into 9 sections did not make the Chinese text smaller. Everything the total shows comes from `language`. Quoting "2.0.4 is 27.9% smaller" as a structural achievement would be wrong — the structure paid for itself in readability and in *not growing*.

B exists for one reason: without a Chinese edition of the *optimized* text, `A → C` would mix restructuring and translation into one number that cannot be attributed. Keeping B lets each term be measured on its own. It lives in `tests/token_language/sample_b/`, its bytes are pinned by a SHA256 assertion, and it is not installable — 2.0.4 ships one skill.

`SKILL.md` body, measured 2026-11-14:

| Tokenizer | A | C | total saving | 15% target |
|---|---|---|---|---|
| `cl100k_base` (tiktoken, exact) | 5,416 | 3,903 | **27.9%** | met |
| `o200k_base` (tiktoken, exact) | 4,571 | 3,878 | **15.2%** | met |
| `deepseek_v4` (official offline `tokenizer.json`, exact) | 4,343 | 3,943 | **9.2%** | **not met — reported, not gamed** |
| `deepseek_estimate` (documented ratio 0.3 / 0.6, **estimate**) | 3,261 | 4,583 | −40.5% | not applicable |

Including the YAML description — what a client actually loads before reading anything — the totals are 5,533 → 3,972 on `cl100k_base` (−28.2%) and 4,406 → 4,014 on `deepseek_v4` (−8.9%). On DeepSeek the description alone *grows*, 63 → 71 tokens: the English trigger sentence needs more of that vocabulary than the Chinese one. The body dominates, so the total still falls.

Reference files, `deepseek_v4`: protocol-v2 5,171 → 4,969 (+3.9%), migration 4,675 → 4,452 (+4.8%), hooks 2,377 → 2,300 (+3.2%), benchmark 5,424 → 5,193 (+4.3%). Templates: `AGENTS.md` 1,232 → 1,237, `05_dashboard.md` 784 → 760 — i.e. **templates are language-neutral within noise**, which is the point: a template is mostly placeholders and protocol vocabulary.

Why DeepSeek lands below 15%: its vocabulary is Chinese-heavy, so the Chinese source is already dense (4,343 tokens for ~7.7 k characters), while the English edition needs ~12.4 k characters for the same content. The same restructuring gains 27.9% on a Latin-script-heavy vocabulary and 9.2% on a Chinese-heavy one — which is why the gate is split: **15% on `cl100k_base` / `o200k_base`, "must not grow" on `deepseek_v4`**. Per-section detail, per-task reading paths and the full per-file table are in `tests/token_language/out/token-benchmark-all.md` (JSON alongside it).

Method notes, so nobody reads more into these numbers than they support:

- `cl100k_base` / `o200k_base` are reproducible proxies, not any specific model's billing tokenizer.
- Every report names the vocabulary it used: `deepseek_v4` records the file name, the `tokenizer.json` SHA256 and the `tokenizers` version, and no report contains a personal path — two numbers can be proved to come from the same vocabulary without publishing anyone's directory layout. The current hash is `89085f12…c9614`.
- `deepseek_estimate` only applies the documented ratio (1 English char ≈ 0.3, 1 Chinese char ≈ 0.6) and is labeled as an estimate everywhere. **The ratio model is invalid for cross-language comparison** — a translation has more characters, so the formula reports a grow where the real tokenizer reports a saving. That comparison is kept in the report on purpose, as evidence of the formula's limit.
- The heuristic counter (CJK 1 char ≈ 1 token, other 4 chars ≈ 1 token) is reported as an estimate only and is never used for a conclusion.
- A missing tokenizer is an error (exit 2), not a silent downgrade: a report never claims exactness it does not have.
- Structure is compared through section headings and protocol IDs, not through sentence-by-sentence semantic equivalence; `tests/token_language/test_token_language.py` holds the rule table (19 required rules in the shipped skill).

---

## 13. Hooks (never installed by default)

```bash
python "$KB/scripts/kb-hooks.py" install   --client claude --target . --plan
python "$KB/scripts/kb-hooks.py" install   --client claude --target . --write
python "$KB/scripts/kb-hooks.py" uninstall --client claude --target . --write
```

- Writes **project-level** configuration only (`.claude/settings.json`, `.codex/hooks.json` + a TOML fragment); never global.
- Events: `SessionStart` (inject a small budget context) / `PreCompact` (remind to wrap up) / `Stop` (handoff self-check, reminder only) / `SessionEnd` (empty response on the Claude side). Codex uses the official three-level shape `{matcher, hooks:[{type, command}]}`; Claude has its own structure. **No `decision: block`** — no event ever blocks a session.
- Preview is the default: `--plan` and any call without `--write` only print "add / remove / keep / SHA before-after" and **write nothing**; `--write` persists, re-verifying SHA first and giving up if someone else changed the file.
- `run` **always exits 0**: a hook's own failure must not break the session. No network, no auto-commit, no rewriting of fact documents.
- Event names and exit-code semantics follow each client's current official documentation (see `references/hooks.md` / `references/hooks.zh-CN.md`); read `--plan` before `--write`.

---

## 14. Protocol compatibility

| Item | v1 | v2 |
|---|---|---|
| Reserved layers | `00/05/06/90` | unchanged |
| Fact books | `01–08` (collides with 05/06) | new `10–17`; old `01–04` stays legal |
| Section addressing | heading text / `--section N` | adds `<!-- kb:id: ... -->`, old interface kept |
| Handoff | human reads `05` | `kb-handoff.py` grades item by item (missing evidence = unverified) |
| Writing | hand-appended | `kb-write.py` (hash + lock + transaction) |
| Context | read everything or `00+05` | `kb-context.py` routes within a budget |
| Hashing | 12-char text short hash | full 64-hex for writes, short hash kept for compatible reads |

Every old command still works: no `kb-init` / `kb-check` / `kb-outline` argument was removed, only added.

---

## 15. Risks, limits and recovery

- **Not doing**: vector store / SQLite index / embeddings / resident MCP / multi-project hub / knowledge graph / cloud sync / automatic LLM summarization.
- Scale is bounded by mechanism (git + thresholds), not discipline; beyond about 8 lines or `00` over 150 lines, merge or upgrade instead of adding more documents.
- A plain editor saving a file bypasses the lock, so **hash re-verification is mandatory**; `kb-write` refuses stale hashes.
- Hooks depend on client event semantics, which can change on client upgrade; `run` failures print and never block.
- Crash recovery: `kb-write.py recover --dry-run` first, then `--apply`; when someone else changed a file it reports and does not overwrite.
- Credentials: scanning is a regex heuristic, a hit blocks the write — but **no hit is not proof of safety**; `.gitignore` must be in place before the first `git add`.

---

## 16. Files

```text
CHANGELOG.md                    short version history; the long chronicle is README.zh-CN.md §17
SKILL.md                        the skill — English, 9 numbered sections, the only skill document
references/protocol-v2.md       2.0 protocol: numbering, section IDs, changes.json, concurrency and recovery
references/protocol-v2.zh-CN.md Chinese edition of the above (optional reading)
references/protocol.md          v1 design rationale (historical, Chinese only)
references/migration.md         legacy restructuring manual (incl. v1 → v2)
references/migration.zh-CN.md   Chinese edition
references/hooks.md             Codex / Claude Code hook semantics and installation
references/hooks.zh-CN.md       Chinese edition
references/benchmark.md         benchmark methodology, task set, how to read it
references/benchmark.zh-CN.md   Chinese edition
assets/                         Chinese templates (AGENTS / 00 / 05 / 10–17 / 06 / 90 / startup message / git config)
assets/en/                      English templates (same placeholders, same kb:id set)
scripts/kb-init.py              scaffold + pre-checks + whitelisted commit + credential block
scripts/kb-check.py             read-only health check (--loose / --json / --mode)
scripts/kb-outline.py           outline + stable section IDs + section reads + hash verification
scripts/kb-write.py             safe write (hash / lock / transaction / recover)
scripts/kb-migrate.py           lossless v1 → v2 migration (plan bound to hashes)
scripts/kb-search.py            lightweight full-text search (section-level scoring)
scripts/kb-context.py           budget-aware context routing (--explain)
scripts/kb-handoff.py           handoff validity check (evidence first)
scripts/kb-hooks.py             client hook adapter (never installed by default)
scripts/kb-benchmark.py         token and quality benchmark
scripts/lib/                    shared library: protocol / scope / markdown / safeio / security / tokens / terms / facts
tests/                          unittest suite + end-to-end smoke + dependency check + fixture generator
tests/make_fixture.py           synthetic benchmark fixture (the numbers in §1 are reproducible)
tests/fixtures/ffrs/            desensitized custom-naming fixture (--loose, all fictional)
tests/token_language/           A/B/C token benchmark, rule and layout tests, frozen v2.0.3 baseline
tests/token_language/sample_b/  frozen Chinese 2.0.4 text — benchmark sample only, not a skill
tests/deps_check.py             non-stdlib import check (full AST; only tiktoken / tokenizers allowed)
.github/workflows/test.yml      Ubuntu + Windows × 3 Python versions
```

---

## 17. Version history

| Version | Focus |
|---|---|
| 2.0.1-hotfix | Path/symlink/transaction hardening, hook protocol fixes, fact-ID immutability, P4 containment, withdrawn numbers |
| 2.0.2 | Quality-gate rounding, "recent records" counting, `--loose` numbered books; six assembly-layer defects (agent dirs, parent-section scoring, file preamble, false P0 gap, `other` weight, small books); five judgment-layer defects (two P0 implementations, fenced content, loose prose books, P4 gap withdrawal, duplicate loading) |
| 2.0.3 | Four early-return / half-check defects: P0 level-by-level fallback, h1 sentence comparison, short-sentence relevance, preamble-and-fact mixed sentences |
| 2.0.4 | English skill + bilingual templates + measured token benchmark (this release) |

The full Chinese chronicle — what each defect did on a real library, before/after numbers, and the withdrawn figures — is in [`README.zh-CN.md`](README.zh-CN.md) §16.

### 17.1 What 2.0.4 changed

- `SKILL.md` rewritten in English as **9 numbered sections**: Purpose and Applicability / Architecture and Core Rules / Quick Start and Recovery / Context Routing / Safe Write Rules / Handoff and Validation / Reference Loading Guide / Anti-patterns and Safety / File Index. It states in its opening block that instruction language and library language are independent.
- **One skill, not two.** The Chinese optimized text is not shipped: it lives at `tests/token_language/sample_b/SKILL.zh-CN.md` as the B sample of the token benchmark, byte-frozen by a SHA256 assertion. A test asserts that `SKILL.md` is the only skill document outside `tests/`.
- `references/*.md` are English; the Chinese originals moved to `references/*.zh-CN.md` **without wording changes**, kept as optional reading with the same protocol IDs, commands, JSON shapes and exit codes. `references/protocol.md` stays Chinese on purpose (it is a historical design note).
- `assets/en/` added: 12 templates with the same placeholders and the same `kb:id` set as `assets/`. The Chinese templates are untouched.
- `scripts/kb-init.py --lang {zh,en}`: selects the template set and localizes the generated table headers, route separator, initial status, shard section, `CLAUDE.md`/`GEMINI.md` pointer and the self-check script stub. `--lang zh` is the default, so existing behaviour is unchanged.
- `scripts/lib/tokens.py`: `TokenCounter` gains `deepseek_v4` (official offline tokenizer, exact) and `deepseek_estimate` (documented ratio, labeled estimate). Each counter now reports a fingerprint — source, vocabulary file name, vocabulary SHA256, library version — with no personal path, and `is_exact()` recognises both exact prefixes. A missing encoder raises instead of silently downgrading.
- `tests/deps_check.py`: now walks the **full AST** instead of module-level imports only, and requires optional imports to sit inside a function **and** inside `try/except`. `tokenizers` joined `tiktoken` as a declared optional dependency, which is what the code had been using since the DeepSeek counter landed.
- `tests/token_language/`: A/B/C measurement, frozen v2.0.3 baseline whose bytes / SHA256 / token counts are re-verified against **all three exact vocabularies**, rule table for the shipped skill, identifier/JSON contract checks against the implementation, template parity, token targets, no-silent-fallback, cross-language scenario tests.

**What did not change**: protocol version stays `2`; document IDs, reserved filenames, section IDs, command arguments, JSON schemas and migration behavior are all untouched; an existing Chinese library needs no migration and is still read correctly. Security, concurrency, transaction, hashing and recovery rules are preserved verbatim in substance — nothing was removed to make the token numbers look better.

---

## 18. Test and verification status (honest version)

Stating what was and was not tested is worth more than a few more PASS lines.

### 18.1 Local tests

| Item | Result |
|---|---|
| `python -m unittest discover -s tests` | **392 tests, OK (1 skipped)** — 341 existing + 40 `token_language` + 11 `test_deps_check`; the single local skip is an existing degradation test that only applies when `tiktoken` is *absent* |
| the same suite **with no optional encoder** (what CI sees) | 392 tests, **7 skipped**, 0 failures: the numeric token tests need an exact vocabulary. Every skip names the missing encoder (`cl100k_base` / `o200k_base` / `deepseek_v4`); the encoder-free properties — layout, rules, identifiers, JSON contract, templates, cross-language scenarios, fallback exit codes — all still run |
| Runtime | Windows 11 (10.0.26200) / Python 3.13 (local `G:\Python313`) |
| `python tests/smoke.py` | all pass: init → read/write → migrate → check → route → benchmark, including exit-code assertions on conflicts and bad paths |
| `python tests/deps_check.py` | OK: `scripts/` uses only the standard library plus local `lib`; `tiktoken` and `tokenizers` are the two declared optional exceptions, both function-scoped and `try`-guarded. `tests/test_deps_check.py` (11 cases) tests the checker itself |
| `python tests/token_language/run_token_benchmark.py --all` | produces the table in §12.2; `deepseek_v4` requires the offline tokenizer, otherwise exit 2 |

### 18.2 CI (six environments)

`Ubuntu × {3.10, 3.12, 3.13}` + `Windows × {3.10, 3.12, 3.13}`, see `.github/workflows/test.yml`. Each environment runs: environment info → unit tests (`-v`) → end-to-end smoke → dependency check.

The 2.0.3 run (run `43451488874`, 2026-11-13) was green in all six environments with 341 tests, no skips.

For 2.0.4 the authoritative statement is the PR's CI status, not this file: the run for the current HEAD is on pull request [#5](https://github.com/jmwangde3/handoff-kb/pull/5). Each job runs 392 tests; the 7 skips are the numeric token tests, which need an exact encoder that CI deliberately does not install — they are not hiding a failure, and the numbers themselves are reproducible locally with one command (§12.2).

> Known noise: GitHub warns about Node 20 deprecation in `actions/checkout@v4` and `setup-python@v5`; that is an action-upgrade reminder and does not affect results.

### 18.3 Client hooks

- **Verified**: configuration shape matches both vendors' official formats, preview writes nothing, a SHA change aborts the install, multi-file rollback (including atomic writes and third-party conflict), all five `SessionStart` sources covered, `PreCompact` output split per vendor (Claude plain text / Codex `systemMessage`, neither carries `decision` / `continue`) — all through simulated events.
- **Not verified**: the actual injection behavior when a real client starts the process. Tests stop at "configuration shape and event mapping"; no real Claude Code / Codex run was performed. `references/hooks.md` states the same boundary.

### 18.4 Benchmark basis

- The three token counts (A/B/C) go through **one** `TokenCounter` instance; the default is the `heuristic` estimate (CJK 1 char ≈ 1 token, other 4 chars ≈ 1 token), **not** an API bill.
- For real counting install `tiktoken` and pass `--tokenizer cl100k_base` explicitly; if it cannot be installed the tool exits 2 rather than silently downgrading.
- A includes every searchable text file in the subdirectories (data directories and files over 2 MB excluded), so a real library's A is very large; the percentage varies with the library's size distribution — **do not compare across libraries**.
- The bilingual benchmark's A is **frozen** at `tests/token_language/baseline/v2.0.3/` with a `MANIFEST.json` (19 files with bytes / chars / sha256 / token counts), so the comparison cannot drift when the working tree changes.

### 18.5 Known residual risks

| Risk | Current state | Impact |
|---|---|---|
| Multi-file recovery is not a database transaction | per-file write + second SHA + keep the scene on failure; no WAL / two-phase commit | a kill between two writes can leave a "partially written" scene; `recover` reports it and asks for confirmation instead of pretending success |
| External editors bypass the lock | the lock only exists inside `kb-write` | a direct save in VS Code / Typora is not intercepted; the `sha256` comparison before write-back detects the conflict |
| Large real libraries are not stress-tested | read-only runs on FFRS (body 47 files / 0.6 MB, archive 795 files / 5.6 MB, ~36 GB physical including assets) | that is "many files", not "one big file"; a single file over 10 MB or more than 500 searchable body files is untested, and `kb-context` still scans the whole library, so it may be slow |
| Cross-process race | lock + second verification, not CAS | two `kb-write` runs on the same file may both have to retry in an extreme interleaving; nothing is silently overwritten |
| Client startup not verified end to end | see §18.3 | a hook that is installed but ineffective is only discoverable by "no context was injected" |
| P4's "asking about history" is a keyword guess | only `历史 / 以前 / 作废 / 沿革…` bring retired content back | a different phrasing ("back then", "before the rollback") may not trigger it; the explicit switch is `--include-superseded`, and the model side only sees the gap note |
| Retired content is blanked at the "definition line" | only definition positions parsed by `lib/facts.py` | a section restating an old value in prose (not written as a definition) is not blanked; mark the old value `status: deprecated` when writing |
| Token numbers are tokenizer-dependent | 27.9% / 15.2% / 9.2% on cl100k / o200k / deepseek_v4 | quoting a single percentage without naming the tokenizer is misleading; the report always names it and records the vocabulary SHA256 |
| English templates are new | parity tests compare file sets, placeholders and `kb:id`, plus a live `kb-init --lang en` run through `kb-check` | no long-running English library has been produced with them yet, so "reads well after six months" is unproven |
| English skill over a Chinese library | the **CLI** path is covered by tests (init / check / context on the Chinese fixture) | an **agent** following the English instructions in a real Codex / Claude Code session has not been run; the checklist marks this unverified |

---

## License

MIT, see `LICENSE`.
