# Workspace Rules — PairedDemo

> **This is an entry point, not a fact document**: it only says which process applies when, what to read, and how to write back. Current values live in `00`/`10–17`, state in `05`, logs in `06`, deep archive in `90`.
> Client-agnostic: WorkBuddy / Codex / Claude Code / Cursor / Gemini all take over by following this file.

## 0. When to use this library

- Several workstreams in parallel, several sessions that may edit documents at once, or context pressure → follow the process below.
- One session, one small task → do not build a library, do not update `05`; write a six-line handoff for the next session.

## 1. Tooling and scope

The tools live in the handoff-kb skill directory (one real directory; same-named directories under client folders are usually symlinks):

```bash
KB="$HOME/.skills-manager/skills/handoff-kb"   # replace with your actual install path
ls "$KB/scripts"                               # verify the path first
```

This workspace root is `C:\Users\jmwan\.skills-manager\skills\handoff-kb\tests\token_language\fixtures\paired\en`. Every tool reads and writes only inside that root; paths escaping it, or pointing through a symlink to the outside, are rejected.

## 2. Handoff: buy context by budget, never read everything

```bash
py "$KB/scripts/kb-context.py" --target . --task "<one-line task>" --budget 3000 --explain
```

The priority order is fixed: hard constraints → current state → next step → facts of the relevant line → evidence pointers → the rest by relevance.
Search only when you need to locate material, then read by section instead of stuffing whole files:

```bash
py "$KB/scripts/kb-search.py"  --target . --query "<keyword>" --limit 5
py "$KB/scripts/kb-outline.py" --file 05_进度仪表盘.md --section-id dashboard.next
```

When `kb-context.py` reports an overrun, do not delete hard constraints blindly — split the task first, or raise the budget explicitly.

## 3. Write-back: hash check + lock, never overwrite a whole file

1. Read: `py "$KB/scripts/kb-write.py" read --target . --file 05_进度仪表盘.md --json` → get the full `sha256` and section IDs.
2. Write: express the change as `changes.json` (`replace_section` / `append` / `update_fact`, each with `expected_sha256`), `--dry-run` first, then apply.

```bash
py "$KB/scripts/kb-write.py" apply --target . --changes changes.json --dry-run
py "$KB/scripts/kb-write.py" apply --target . --changes changes.json
```

- Touch only your own line: log entries go to `06_流水/<line>.md`; **never edit another session's lines**.
- `05` holds state, todo and next step only; anything longer than 3 lines goes as one entry into `06`.
- Completed items carry evidence (command / file / commit); without evidence write "unverified".

## 4. Conflict handling

- `CONFLICT` from `kb-write.py`: **do not retry the overwrite**. Re-`read` for the current hash, merge, then write.
- `LockHeld`: another session is writing. Wait for the release; only after confirming the peer process is dead run `kb-write.py recover --break-lock`.
- After a crash or power loss: `py "$KB/scripts/kb-write.py" recover --target . [--dry-run]`, then decide from the report whether to clean up or roll back.
- **Never** `git add -A`; commit only the files this task touched.

## 5. Wrap-up and handoff

```bash
py "$KB/scripts/kb-handoff.py" check --target . --strict   # is the handoff verifiable
py "$KB/scripts/kb-check.py"   --target .                  # size / numbering / credentials / git
git add -- <files changed by this task> && git commit -m "<line> <what you did>"
```

A handoff must answer: current task, what was actually completed, evidence, unverified items, blockers, next step, affected files, operations that must not be repeated.

## 6. Lines and files

| Line | Read these |
|---|---|
| firmware | `10_firmware.md` + `00` |
| runtime | `11_runtime.md` + `00` |

| File | Content |
|---|---|
| `00_基线.md` | Baseline (`K-xx` + status + evidence) + policy + cross-links; the single shared page |
| `10_firmware.md` | firmware (fact layer) |
| `11_runtime.md` | runtime (fact layer) |
| `05_进度仪表盘.md` | Current state / next step / per-line status / todo (required on handoff, must not bloat) |
| `06_会话日志.md` | History volume and shard index (read-only) |
| `06_流水/<line>.md` | Per-line append-only log (one writer per file) |
| `90_过程档案.md` | Deep archive, by topic (not required reading) |
| `归档/` | One-off task sheets, pre-split backups |

## Log shards

Each line **writes only its own file**, which removes shared-file concurrent overwrites at the root:

| Shard | Its writer |
|---|---|
| `06_流水/firmware.md` | firmware line |
| `06_流水/runtime.md` | runtime line |
| `06_流水/其他.md` | uncategorised / cross-line |

- 1–3 lines per entry; a **single shard** is folded into `90` only beyond 200 lines / 60 KB.
- `06_会话日志.md` is the history volume + index: **read-only, no log entries**.
- Same source as `05` §5: change one, sync the other.

## 7. Hard constraints (fill per project)

- [fill: credentials / backups / numbering contracts that must not be reordered / machines that must not be touched]
- `K-xx` / `G-xxx` / section IDs are cross-document contracts: edit the content, **never reorder them and never reuse a superseded ID**.
- This file never stores current values; storing one creates a second version of the truth.
