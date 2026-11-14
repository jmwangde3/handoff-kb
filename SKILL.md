---
name: handoff-kb
description: Build and maintain a layered knowledge handoff system for long-running, multi-session projects. Supports budget-aware context retrieval, safe concurrent writes, evidence-based handoffs, project migration and optional client hooks. Use for context compression, multi-workstream coordination and long-term project documentation. Do not use for simple one-off handoffs or small single-session tasks.
---

# Layered Handoff Knowledge Base (handoff-kb 2.0.4)

> **Tool version** `2.0.4` (script behavior) | **Protocol version** `2` (document layout, `<!-- kb:schema: 2 -->`).
> They are independent: a tool upgrade does not change the protocol, and does not require an existing library to migrate.

> **One skill: English instructions, any library language.** Instruction language and
> library language are independent — this skill manages a Chinese library, an English
> one, or a mixed one. Never translate existing documents on your own initiative.

## 1. Purpose and Applicability

**Decide first. If this is not your case, stop** — run no script, create no file, read no further; hand over with the six-line template below.

| Your situation | Action |
|---|---|
| One session, task ends, next session just needs a handover note | **Do not use this skill** → simple handoff |
| Fewer than 3 documents, no parallel sessions, one-off task | **Do not use this skill** → simple handoff |
| You want a "continue prompt" for the current session | **Do not use this skill** → simple handoff |
| Several workstreams + parallel sessions + context pressure + long-term upkeep | Use this skill, start at §3 |
| Legacy project with scattered documents to reorganize | Use this skill: §3 diagnosis + `references/migration.md` |

Simple handoff template (paste into the next session; no files, no library, no git):

```text
Take over [TASK], working directory [DIR].
Done: [1–2 lines]
In progress / blocked: [1 line]
Next: [1 line]
Files / commits: [paths or git log -3]
Do not repeat: [1 line, delete if none]
```

Project-level override: if a project will not use this library, put `This project uses simple handoff; do not load handoff-kb` as the first line of its own `AGENTS.md`. Project rules win.

## 2. Architecture and Core Rules

| Layer | Files | Content | Read when |
|---|---|---|---|
| L0 entry | `AGENTS.md` (+ `CLAUDE.md`/`GEMINI.md` pointers) | Which file to read, how to write. **Never stores current values** | Always |
| L1 facts | `00` (`K-xx` + status + evidence) + `10–17` per workstream | Current values / criteria / commands / pitfalls | Per workstream |
| L2 state | `05_进度仪表盘.md` (`kb:id` sections) | Current state / next step / line status / todo / hard constraints | **Required** |
| L3 log | `06_会话日志.md` (read-only history) + `06_流水/<line>.md` | Append-only timeline | Forensics only |
| L4 archive | `90_过程档案.md` + `归档/` | Process evidence / verification snapshots | Not required |

2.0 moved fact shards to `10–17` (`01–04` remain valid, `00/05/06/90` reserved), made sections addressable via `<!-- kb:id: dashboard.current -->`, added `sha256` + lock + journal to writes, and routed context under a budget.

Non-negotiable rules:

- **P0 constraints are never silently discarded.** If the budget cannot hold them, keep them and report the overrun.
- P1 (current state and next step) is always kept. P2 (workstream facts) may be skipped, but the skip must be listed.
- P3 must cite explicit fact IDs and evidence. P4 additions are bounded and relevance-scored.
- **Gaps and omitted content must be reported honestly.** Never present "not loaded" as "nothing to load".
- Compatible with existing v2 projects: no renaming, no renumbering, no body rewrites.

## 3. Quick Start and Recovery

Install and locate:

```bash
KB="$HOME/.skills-manager/skills/handoff-kb"   # Windows PowerShell: README.md §5
ls "$KB/scripts"                               # verify the path before running anything
```

Client directories usually symlink this path; one real directory exists. Scripts read and write only inside `--target`; escapes, `..`, absolute paths and out-of-root symlinks are rejected.

New project:

```bash
py "$KB/scripts/kb-init.py" --target "~/projects/new" --project "new" \
    --lines "firmware,runtime,server,bench"
py "$KB/scripts/kb-init.py" --target "~/projects/new" --plan      # plan only
py "$KB/scripts/kb-init.py" --target "~/projects/new" --lines "a,b" --lang en   # English templates
```

`--lang zh` is the default; `--lang en` switches template language only (same 17 files, placeholders and `kb:id` set) and never changes this skill's instruction language.

Generated: `AGENTS.md`, `CLAUDE.md`/`GEMINI.md`, `00_基线.md`, `10–17_<line>.md`, `05_进度仪表盘.md`, `06_会话日志.md` + `06_流水/*.md`, `90_过程档案.md`, `新会话启动消息.txt`, `.gitignore`/`.gitattributes`, `scripts/handoff-check.sh` stub, `归档/`.

Then: fill `00` `K-xx` rows (value / status / evidence) and `05` state, next step and hard constraints; extend `.gitignore` (large files, credentials first); replace the check stub with real read-only checks; run `kb-handoff.py check --target . --strict`.

Safety boundary: `--plan` writes nothing; an existing git repository is never nested or auto-committed; only whitelisted `git add --`; a credential hit blocks the commit (`--force` does not bypass it); protected config files need `--force --overwrite-config`.

Legacy project (diagnose before migrating):

```bash
py "$KB/scripts/kb-check.py"   --target ./old --loose      # read-only diagnosis, no renaming required
py "$KB/scripts/kb-migrate.py" --target ./old --plan       # plan bound to source hashes
py "$KB/scripts/kb-migrate.py" --target ./old --apply      # refuses on hash mismatch
```

`kb-migrate.py` only adds `<!-- kb:schema: 2 -->` and `kb:id` for known sections: no renaming of `01–04`, no reordering, no body edits, no evidence deleted; re-runs are idempotent. Uncommitted changes cause a refusal by default (`--force` only after confirming no concurrent session). Structure work (sink process into `90`, create `05`, split `06`) follows the five-step SOP in `references/migration.md` — do not skip steps, do not split early.

Recovery: `kb-write.py recover --inspect` shows the journal, `--apply` rolls back, `recover --break-lock` only after confirming the peer process is dead. Migration rollback is `git checkout -- 00_*.md 05_*.md` (migration touches only those two).

## 4. Context Routing

```bash
py "$KB/scripts/kb-context.py" --target . --task "<task>" --budget 3000 --explain
py "$KB/scripts/kb-context.py" --target . --loose --task "<task>"   # custom naming
git status && git log --oneline -5
py "$KB/scripts/kb-search.py"  --target . --query "<keyword>" --limit 5
py "$KB/scripts/kb-outline.py" --file 05_进度仪表盘.md --section-id dashboard.next
```

Assembly order: **P0** hard constraints → **P1** current state + next step → **P2** facts of the matching workstream → **P3** baseline hits + evidence + cross-links → **P4** relevance fill (≤3 blocks, ≤30% of budget, and ≥2 keyword hits or one unique term of ≥4 characters; a file named by the task does not participate in P4; superseded facts are blanked line by line and a section whose relevance comes only from superseded content is skipped; `--include-superseded` or asking about "history" brings them back verbatim, marked "superseded" with the replacement ID).

- Over budget: **never drop hard constraints** — split the task or raise `--budget`, and surface the overrun in the output.
- No hit means report a gap and go to `kb-search`. Never invent content.
- **P4 fills sections, not whole workstreams**: a gap line saying "P4 added N fact sections" means only keyword-selected sections were added; use `--line <name>` to load a whole line. In JSON, `p4_facts` are sections from real fact shards; `p4_candidates` are numbered documents without fact entries (weight 0.5, read as leads).
- P0 falls back in three steps: `dashboard.constraints` → `dashboard.safety` → the `AGENTS.md` hard-constraints section. An out-of-root symlink entry, or a section holding only placeholders, does not count as a declaration. `kb-check` and `kb-context` share this rule.
- Client state directories (`.workbuddy`, `.shared`, `.claude`, and the rest) are not body text; both search and assembly skip them.
- Token counting defaults to `heuristic`. Exact counts require `--tokenizer cl100k_base` with `tiktoken` installed; a missing tokenizer exits non-zero unless `--allow-tokenizer-fallback` is explicit.

## 5. Safe Write Rules

Never overwrite a whole file.

1. `py "$KB/scripts/kb-write.py" read --target . --file 05_进度仪表盘.md --json` → obtain `sha256` and section IDs.
2. Build `changes.json` (`replace_section` / `append` / `update_fact`, every entry carrying a 64-hex `expected_sha256`).
3. `--dry-run` to inspect the diff, then `apply`.
4. `CONFLICT` means someone else changed the file: re-read, merge, rewrite. **Never retry a blind overwrite.**
5. `LockHeld` means another session is writing: wait. `recover --break-lock` only after confirming the peer is gone.

Routing: state / todo / next step go to `05`; details longer than three lines go as one entry into `06_流水/<line>.md`; durable facts go to `00` or `10–17` with evidence; process and verification snapshots go to `90`. **Never rewrite another session's lines.**

Guarantees and limits:

- A write requires the current `sha256`; a stale hash is a `CONFLICT`, not a merge.
- Lock conflicts are never bypassed silently; a dead process on the same host may be reclaimed only after re-verifying `owner_token`.
- **Multi-file writes are not database-level atomic transactions.** The protocol provides full pre-checks, byte-level backups, rollback on failure and crash detection; git remains the final audit trail.
- No credentials may be committed. Secret scanning runs before commit and is not bypassable with `--force`.

## 6. Handoff and Validation

```bash
py "$KB/scripts/kb-handoff.py" check --target . --strict
py "$KB/scripts/kb-handoff.py" check --target . --loose   # fall back to headings when kb:id is absent
py "$KB/scripts/kb-check.py" --target . --loose
py "$KB/scripts/kb-check.py" --target . --strict
```

Eight questions are graded one by one: task / done / evidence / unverified / blockers / next step / affected files / do-not-repeat. Placeholders (`[fill`, `TODO`) and "valid but without evidence" both count as unverified; `--strict` fails on them.

`kb-check` inspects required files (exact names), per-layer size and onboarding cost (body versus archive), thresholds, `K-xx` duplicates / undefined / superseded / cycles, `kb:id` duplicates and illegal forms, fact evidence and staleness, table column counts, leftover TODO, plaintext credentials and git state.

Thresholds (write them into `05`, act only when crossed):

| Object | Threshold | Action |
|---|---|---|
| `05` current state | > 4 lines | compress; details to the log |
| `05` recent entries | > 5 entries or an entry > 3 lines | move whole entries to `06_流水/<line>.md` |
| `06` single shard | > 200 lines or > 60 KB | fold into `90`, keep a heading + pointer |
| `00` baseline | > 150 lines or `K-xx` > 30 | promote to a conclusion index |
| `90` archive | > 600 lines | split into volumes or move to `归档/` |
| Fact shards | > 8 | merge by domain |

Acceptance: `05` alone must tell you each line's state, the next step, what is pending / in progress / done with what evidence, and which files to read before changing a config. If it cannot, `05` lost information — do not compensate by reading everything.

## 7. Reference Loading Guide

**References are not default reading.** Load one only when the current task needs it:

| Task | Read |
|---|---|
| Protocol identifiers, section IDs, `changes.json`, locking, transactions, exit codes | `references/protocol-v2.md` |
| Reorganizing an existing library, v1 → v2 upgrade | `references/migration.md` |
| Installing or debugging a client hook | `references/hooks.md` |
| Interpreting token or quality numbers | `references/benchmark.md` |
| Historical v1 design rationale (Chinese, archived) | `references/protocol.md` |

Chinese editions exist as `references/*.zh-CN.md` — optional reading, **not a second skill**. English is the default here. Both editions carry the same protocol IDs, commands, JSON shapes and exit codes; read the one matching the project's prose language and never mix them within one answer.

## 8. Anti-patterns and Safety

| Pitfall | Consequence |
|---|---|
| Same long text stored in several places | One edit misses two copies; wording drifts |
| Reference manuals listed as required reading | Every new session burns tens of thousands of tokens |
| `05` filled with completed todos | The todo area is diluted by history |
| Deleting process together with its pitfalls | The next session repeats the same road |
| Plaintext credentials reaching `git init` | They stay in history forever |
| Large files (video, logs) not excluded before `add` | Repository bloats; history unclearable |
| `git add -A` | Commits another session's half-finished work |
| Whole-file overwrite of `05` | Erases lines another session just appended |
| Reordering section numbers or reusing a `K-xx` | Every cross-reference breaks |
| Claiming "fixed" without evidence | The handoff cannot be verified |
| Installing hooks by default | Sessions acquire a dependency nobody asked for |

Safety rules that must survive any refactor: P0 never dropped; hash required for writes; lock conflicts not bypassed; atomicity not overstated; migration preserves source content; hooks never block a session and always exit 0; no credentials committed; existing v2 projects keep working.

## 9. File Index

| Path | Purpose |
|---|---|
| `scripts/kb-init.py` | Scaffold (`10–17` numbering, `--lang zh\|en`), pre-checks, whitelisted commit, credential block |
| `scripts/kb-check.py` | Read-only diagnosis (`--loose` / `--strict` / `--json` / `--mode`) |
| `scripts/kb-outline.py` | Outline, `--section-id` reads, `--hash` |
| `scripts/kb-write.py` | Safe writes (hash / lock / transaction / `recover`) |
| `scripts/kb-migrate.py` | Lossless v1 → v2 migration (plan bound to hashes) |
| `scripts/kb-search.py` | Section-level full-text search |
| `scripts/kb-context.py` | Budget-aware context routing (`--explain`) |
| `scripts/kb-handoff.py` | Handoff grading (evidence first) |
| `scripts/kb-hooks.py` | Client hook adapter (never installed by default) |
| `scripts/kb-benchmark.py` | Token and quality benchmark |
| `scripts/lib/` | Shared library: protocol / scope / markdown / safeio / security / tokens / terms / facts |
| `references/protocol-v2.md` | Protocol v2: numbering, section IDs, `changes.json`, concurrency recovery |
| `references/protocol.md` | v1 design rationale (historical, Chinese) |
| `references/migration.md` | Legacy restructuring manual (includes v1 → v2) |
| `references/hooks.md` | Hook semantics and installation |
| `references/benchmark.md` | Benchmark methodology |
| `assets/`, `assets/en/` | Chinese and English skeleton templates (same placeholders and IDs) |
| `tests/`, `tests/token_language/` | unittest suite, smoke, dependency check; zh/en token benchmark and parity tests |
