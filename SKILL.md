---
name: handoff-kb
description: Build and maintain a layered knowledge handoff system for long-running, multi-session projects. Supports budget-aware context retrieval, safe concurrent writes, evidence-based handoffs, project migration and optional client hooks. Use for context compression, multi-workstream coordination and long-term project documentation. Do not use for simple one-off handoffs or small single-session tasks.
---

# Layered Handoff Knowledge Base (handoff-kb 2.0.5)

> **Tool version** `2.0.5` | **Protocol version** `2` (`<!-- kb:schema: 2 -->`).
> Independent: tool upgrades never alter the protocol or require existing libraries to migrate.

> **One skill: English instructions, any library language.** Instruction language and
> library language are independent — this skill manages Chinese, English, or mixed
> libraries. Never translate existing documents on your own initiative.

## 1. Purpose and Applicability

**Decide first. If this is not your case, stop** — run no script, create no file, read no further; use the six-line handoff below.

| Situation | Action |
|---|---|
| One session, next session just needs a handover note | **Do not use this skill** → simple handoff |
| Fewer than 3 docs, no parallel sessions, one-off task | **Do not use this skill** → simple handoff |
| Need a "continue prompt" for the current session | **Do not use this skill** → simple handoff |
| Multiple workstreams + parallel sessions + context pressure + long-term upkeep | Use this skill, start at §3 |
| Legacy project with scattered documents | Use this skill: §3 diagnosis + `references/migration.md` |

Simple handoff (paste into next session; no files, no library, no git):

```text
Take over [TASK], working directory [DIR].
Done: [1–2 lines]
In progress / blocked: [1 line]
Next: [1 line]
Files / commits: [paths or git log -3]
Do not repeat: [1 line, delete if none]
```

Override: if a project puts `This project uses simple handoff; do not load handoff-kb` on line 1 of `AGENTS.md`, project rules win.

## 2. Architecture and Core Rules

| Layer | Files | Content | Read when |
|---|---|---|---|
| L0 entry | `AGENTS.md` (+ `CLAUDE.md`/`GEMINI.md` pointers) | Read/write rules. **Never stores current values** | Always |
| L1 facts | `00` (`K-xx` + status + evidence) + `10–17` per line | Current values / commands / pitfalls | Per workstream |
| L2 state | `05_进度仪表盘.md` (`kb:id` sections) | Current state / next step / status / todo / constraints | **Required** |
| L3 log | `06_会话日志.md` (read-only) + `06_流水/<line>.md` | Append-only timeline | Forensics only |
| L4 archive | `90_过程档案.md` + `归档/` | Process evidence / verification snapshots | Not required |

2.0 moved fact shards to `10–17` (`01–04` stay valid, `00/05/06/90` reserved), added `kb:id` anchors, `sha256` + lock + journal writes, and budgeted routing.

Non-negotiable rules:

- **P0 constraints are never silently discarded.** If budget cannot hold them, keep them and report the overrun.
- P1 (current state and next step) is always kept. P2 (workstream facts) may be skipped, listing the skip.
- P3 must cite explicit fact IDs and evidence. P4 additions are bounded and relevance-scored.
- **Gaps and omitted content must be reported honestly.** Never present "not loaded" as "nothing to load".
- Compatible with existing v2 projects: no renaming, renumbering, or body rewrites.

## 3. Quick Start and Recovery

```bash
KB="$HOME/.skills-manager/skills/handoff-kb"   # Windows PowerShell: README.md §5
ls "$KB/scripts"                               # verify path before running
```

Client dirs usually symlink this path (one real dir). Scripts read/write only inside `--target`; escapes, `..`, absolute paths and out-of-root symlinks fail.

New project (`--lang zh` default; `--lang en` switches templates only, 17 files, same `kb:id` set):

```bash
py "$KB/scripts/kb-init.py" --target "~/projects/new" --project "new" --lines "a,b" --lang en --plan
```

Then fill `00` `K-xx` rows (value / status / evidence) and `05` state, next step and constraints; extend `.gitignore`; replace `scripts/handoff-check.sh`; run `kb-handoff.py check --target . --strict`.

Safety: `--plan` writes nothing; existing git repos are not nested or auto-committed; only whitelisted `git add --`; credentials block commit (`--force` cannot bypass); protected configs require `--force --overwrite-config`.

Legacy project:

```bash
py "$KB/scripts/kb-check.py"   --target ./old --loose   # read-only diagnosis
py "$KB/scripts/kb-migrate.py" --target ./old --plan    # hash-bound plan
py "$KB/scripts/kb-migrate.py" --target ./old --apply   # refuses on hash drift
```

`kb-migrate.py` adds only `<!-- kb:schema: 2 -->` and `kb:id`: no renaming `01–04`, no reordering, no body edits, no evidence deleted; idempotent. Uncommitted changes refuse (`--force` only if no concurrent session). Restructuring follows `references/migration.md` five-step SOP.

Recovery: `kb-write.py recover --inspect` shows journal, `--apply` rolls back, `recover --break-lock` only after confirming peer death. Migration rollback: `git checkout -- 00_*.md 05_*.md`.

## 4. Context Routing

```bash
py "$KB/scripts/kb-context.py" --target . --task "<task>" --budget 3000 --explain --loose
git status && git log --oneline -5
py "$KB/scripts/kb-search.py"  --target . --query "<keyword>" --limit 5
py "$KB/scripts/kb-outline.py" --file 05_进度仪表盘.md --section-id dashboard.next
```

Order: **P0** constraints → **P1** state + next step → **P2** matching line facts → **P3** baseline + evidence + cross-links → **P4** relevance (≤3 blocks, ≤30% budget, ≥2 hits or 1 unique ≥4-char term; task-named files excluded from P4; superseded facts blanked per line unless `--include-superseded` or "history").

- Over budget: **never drop P0** — split task or raise `--budget`, report overrun.
- No hit: report a gap and run `kb-search`. Never invent content.
- **P4 adds sections, not whole lines**: use `--line <name>` for a full workstream; `p4_facts` are real shards, `p4_candidates` are leads (weight 0.5).
- P0 fallback: `dashboard.constraints` → `dashboard.safety` → `AGENTS.md` hard-constraints (out-of-root symlinks or placeholders ignored; shared by `kb-check` and `kb-context`).
- Client state dirs (`.workbuddy`, `.shared`, `.claude`, etc.) are skipped.
- Counting defaults to `heuristic`; exact counts require `--tokenizer cl100k_base` + `tiktoken` (missing exits 2 unless `--allow-tokenizer-fallback`).

## 5. Safe Write Rules

Never overwrite a whole file.

**Finish levels** (decide from work done, before reading KB; project rules remain binding):
- **L0**: no durable change or new conclusion → skip completely (read no KB, generate no JSON, call no script; `--level L0` is for tests/diagnostics only).
- **L1 (default)**: reuse session context; write only changed state/next step/event via persistent UTF-8 JSON and one call `py "$KB/scripts/kb-finish.py" --target . --input task.json` (`--dry-run` previews without writing):
```json
{"updates":[{"path":"05_进度仪表盘.md","section_id":"dashboard.next","before":"old","after":"new"}],"event":{"id":"task-id","path":"06_流水/line.md","content":"- done; evidence: ..."}}
```
  Normally skip full-library checks. On conflict or unfinished txn, keep input, re-read/recover, and merge; never overwrite blindly.
- **L2**: release, major architecture change, phase closeout, or migration (length alone is not a trigger). Read needed shards/state/logs, update via `kb-finish.py` or `kb-write.py`, and run §6 checks as needed; never report L1 writes as a completed full review.
- **Subagents**: if available, delegate L1 with input path, rules, and line ownership, and wait for completion before reporting success. Do not treat session-bound subagents as independent background services; retained JSON is a recovery artifact, not a running queue.

Complex edits (`kb-write.py`):
1. `py "$KB/scripts/kb-write.py" read --target . --file 05_进度仪表盘.md --json` → get `sha256` + section IDs.
2. Build `changes.json` (`replace_section` / `append` / `update_fact`, 64-hex `expected_sha256`), `--dry-run`, then `apply`.
3. `CONFLICT`: re-read, merge, rewrite. **Never retry a blind overwrite.** `LockHeld`: wait; `recover --break-lock` only after peer death.

Routing: state/todo/next → `05`; >3-line details → `06_流水/<line>.md`; durable facts → `00`/`10–17`; snapshots → `90`. **Never rewrite another session's lines.**

Guarantees: current `sha256` required; Lock conflicts are never bypassed silently (dead same-host holder reclaimed after re-checking `owner_token`); unfinished/corrupt txn or orphan backup blocks new writes until `recover`; **multi-file writes are not database-level atomic transactions** (backups/rollback/git audit); No credentials may be committed (not bypassable with `--force`).

## 6. Handoff and Validation

```bash
py "$KB/scripts/kb-handoff.py" check --target . --strict   # or --loose
py "$KB/scripts/kb-check.py"   --target . --loose    # or --strict
```

Grades 8 items (task/done/evidence/unverified/blockers/next/files/do-not-repeat); placeholders or "valid without evidence" fail `--strict`. `kb-check` verifies names, layer sizes, thresholds, `K-xx`/`kb:id` integrity, evidence/staleness, tables, TODOs, credentials and git.

Thresholds (record in `05`, act when crossed): `05` state >4 lines → compress; `05` recent >5 or >3 lines → `06_流水/<line>.md`; `06` shard >200 lines/60 KB → `90`; `00` >150 lines or >30 `K-xx` → index; `90` >600 lines → split/`归档/`; shards >8 → merge. Acceptance: `05` alone states line status, next step, evidence, and pre-edit files.

## 7. Reference Loading Guide

**References are not default reading.** Load one only when the current task needs it:

| Task | Read |
|---|---|
| Protocol IDs, `changes.json`, locks, transactions, exit codes | `references/protocol-v2.md` |
| Reorganizing a library, v1 → v2 upgrade | `references/migration.md` |
| Installing or debugging a client hook | `references/hooks.md` |
| Interpreting token or quality numbers | `references/benchmark.md` |
| Historical v1 design rationale (Chinese, archived) | `references/protocol.md` |

Chinese editions (`references/*.zh-CN.md`) are optional reading, **not a second skill**; never mix languages within one answer.

## 8. Anti-patterns and Safety

| Pitfall | Consequence |
|---|---|
| Duplicating long text | Edits miss copies; wording drifts |
| Listing references as required reading | Burns tens of thousands of tokens |
| Filling `05` with completed todos / deleting pitfalls | Todo diluted / pitfalls repeated |
| Credentials or huge binaries in `git init` / `git add -A` | History polluted / steals peer work |
| Whole-file overwrite of `05` / reordering `K-xx` | Loses peer appends / breaks refs |
| Claiming "fixed" without evidence / default hooks | Unverifiable handoff / unwanted dep |

Rules that survive any refactor: P0 never dropped; hash required; lock conflicts not bypassed; atomicity not overstated; migration preserves source content; hooks never block a session and always exit 0; no credentials committed; existing v2 projects keep working.

## 9. File Index

| Path | Purpose |
|---|---|
| `scripts/kb-init.py` | Scaffold (`10–17`, `--lang zh\|en`), pre-checks, whitelisted commit |
| `scripts/kb-check.py` | Read-only diagnosis (`--loose` / `--strict` / `--json` / `--mode`) |
| `scripts/kb-outline.py` | Outline, `--section-id`, `--hash` |
| `scripts/kb-write.py` | Safe writes (hash / lock / transaction / `recover`) |
| `scripts/kb-finish.py` | L0/L1/L2 finish entry (`--dry-run`, exact-text updates, deduped events) |
| `scripts/kb-migrate.py` | Lossless v1 → v2 migration (hash-bound plan) |
| `scripts/kb-search.py` | Section full-text search |
| `scripts/kb-context.py` | Budget-aware routing (`--explain`) |
| `scripts/kb-handoff.py` | Handoff grading (evidence first) |
| `scripts/kb-hooks.py` | Client hook adapter (never installed by default) |
| `scripts/kb-benchmark.py` | Token and quality benchmark |
| `scripts/lib/` | Shared library |
| `references/` | `protocol-v2.md`, `protocol.md`, `migration.md`, `hooks.md`, `benchmark.md` |
| `assets/`, `assets/en/` | Chinese and English skeleton templates |
| `tests/`, `tests/token_language/` | unittest, smoke, deps_check; zh/en token benchmark and parity |
