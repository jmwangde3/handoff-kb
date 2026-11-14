# Legacy Project Restructuring Manual

> For old projects that already have a pile of documents, several parallel sessions and constant context pressure.
> To build a new library from scratch use `kb-init.py` (SKILL.md §3) — **do not** use this manual.
> Companion prompt: `assets/migration-prompt.txt` (paste it into a new session).
>
> **Already built on v1 and only want v2 (schema marker + stable section IDs)** → jump to §8;
> one `kb-migrate.py` command, do not re-run the five steps.

Chinese edition: `migration.zh-CN.md`.

## 0. Decide whether to change anything

| Signal | Verdict |
|---|---|
| Taking over requires "read all N documents" before any work | Change |
| Library > 100 KB, while what handoff actually needs is < 20 KB | Change |
| "What is happening / what is next" is scattered across 3+ places and they contradict | Change |
| Two or more sessions run in parallel and a shared document was overwritten by a later writer | Change (**do step 1 first**) |
| One workstream, < 30 lines of documents, one session, one-off task | **Do not change** — extra layers mean reading two files |
| Only handing the current session to the next one (a handoff / continue prompt) | **Do not change** — use the six-line template in "Purpose and Applicability" |

The goal is not "thinner documents" but **decoupling storage from reading**: total size may grow while the required reading set per handoff stays at three files or fewer.

## 1. Step 0 — read-only diagnosis (touch nothing yet)

```bash
S="$HOME/.skills-manager/skills/handoff-kb/scripts"
py "$S/kb-check.py" --target "[PROJECT_DIR]" --loose
cd "[PROJECT_DIR]" && git status --short && git log --oneline -5
find . -maxdepth 2 -type f \( -name "*.md" -o -name "*.txt" \) -printf "%s %p\n" | sort -rn | head -20
```

`--loose` is for projects with their own naming scheme (`60_进度.md` / `00_INDEX.md` / `HANDOFF.md`): missing canonical filenames only warn, everything else still runs. **Never start with `kb-init.py` overwriting things** — the scaffold is for empty directories.

> **Data artifacts pollute size accounting**: `.md` / `.txt` under unpack / capture / build directories (and any text > 2 MB) are not handoff documents. `kb-check.py` already skips `AI_files/` / `assets/` / `data/` / `output/` / `evidence/` / `paktools/` / `node_modules/` / `build/` / `dist/` / `vendor/` / `tmp/` and files > 2 MB, and the size table prints "skipped N data artifacts". On one measured game project, skipping 268 of them brought the library from 400 MB back to 454 KB — only then does the 7.5% onboarding cost mean anything.

Read five things from the output and write a 3–5 line conclusion (no need to save it):

1. **Onboarding cost**: what share of the library the state + baseline layers take (> 25% means the required set is too large).
2. **Is there git**: no → step 1 is P0, and no later split can be rolled back.
3. **Plaintext credentials**: yes → handle immediately, they must never enter history.
4. **Numbering contract**: whether `K-xx` / `G-xxx` / `§` numbers are already referenced across documents (if so, never reorder).
5. **Uncommitted changes**: yes → another session is writing; look before you type, and never commit on their behalf.

## 2. Five-step SOP (do not skip, do not split early)

### Step 1 · `git init` (P0: `.gitignore` before `add`)

**Goal**: make every later step diffable, rollback-able, and visible to others.

```bash
cd "[PROJECT_DIR]"
cat > .gitignore <<'EOF'
.workbuddy/
*.log
logs/
*.mp4
*.part
归档/_backup_*/
scripts/_tmp_*
*.bak
Thumbs.db
EOF
git init -b main
git config user.name "Your Name" && git config user.email "you@example.com"   # skip if a global identity exists
git config core.autocrlf false && git config core.quotepath false
printf '* text=auto eol=lf\n' > .gitattributes
git add -A && git commit -m "initial baseline: snapshot before restructuring"
git ls-files | grep -Ei '\.(mp4|zip|log)$' && echo "!! large files in the repo" || echo "OK: no large files"
```

**Pass criteria**: `git status` clean, repository < 10 MB, no video / log / credential in `git ls-files`.
**Pitfalls**:
- A large binary that enters history cannot be removed without `filter-repo` rewriting history — so `.gitignore` must exist **before the first `git add`**.
- Deliverables (xlsx and the like) belong in the repo for rollback, but diffs do not show content → put "version + SHA256" in the commit message.
- On Windows `core.autocrlf=false` plus `.gitattributes` is mandatory, otherwise every checkout produces whole-file CRLF noise.
- Plaintext credentials: move to environment variables or a non-committed memory directory before `add`. `kb-check.py` scans for `LTAI`, PEM private keys, `password=` and `sk-`.

### Step 2 · Sink process into `90`

**Goal**: the main documents keep only "current values / invariants / criteria / commands / pitfalls and conclusions".

| Move out (process) | Keep (asset) |
|---|---|
| Closed historical contradictions and reversals | Current baseline and configuration values |
| Verification snapshots, one-off review records | Criteria and how to verify (commands) |
| Version archaeology, build / release number trails | **Pitfalls and conclusions** |
| Long runs of "11-06 11:32 added …" timestamps | Policies and invariants |
| Resolved contradictions, superseded wording | Frequently used command references |
| One-off task sheets, pre-split backups | Numbering contract (§ / K-xx) |

Method: open `§A`–`§G` in `90_过程档案.md` (or volumes under `归档/`) by topic and **move whole passages verbatim**, leaving `详见 90 §X` at the original position.

```bash
# move the exact line plus byte comparison; never retype
sed -n '70p' 05_进度仪表盘.md >> 90_过程档案.md
sed -n '70p' 05_进度仪表盘.md > /tmp/l70.txt
tail -n 1 90_过程档案.md > /tmp/l90.txt
cmp /tmp/l70.txt /tmp/l90.txt && echo IDENTICAL
```

**Pitfall**: when deleting process it is easy to delete the pitfalls and conclusions with it, and the next session walks the same road. After moving, `grep -rn "详见 90"` to confirm pointers exist, and `kb-check.py` should report 0 for leftover TODO and plaintext credentials.

### Step 3 · Create `05_进度仪表盘.md`

**Goal**: the single state-sync point; one file connects you to every workstream.

Extract "state / todo / progress" from: todo tables at the end of documents, `新会话启动话术.txt`, the "current progress" section of a README, issue/task lists, session summaries.

Fixed structure (§0–§6): `§0 state ≤4 lines` / `§1 per-line status` / `§2 todo · pending · in progress` / `§3 cross-points` / `§4 handoff order` / `§5 maintenance rules and thresholds` / `§6 last 5 entries (each ≤3 lines)`.

```bash
# delete same-source copies: one state in several places is a drift source
grep -rn "现在在做什么\|当前进度\|待办" --include="*.md" --include="*.txt" .
```

**Move completed items out of §2** into `06`; never let history dilute the todo area.
**Acceptance**: from `05` alone you can answer the four questions (§3 of this manual). If you cannot, information is missing or `05` has grown again — do not compensate by reading the entire library.

### Step 4 · Split `06` (only when a threshold is crossed)

**Thresholds** (any one): a single entry in `05` exceeds 3 lines, `05` reaches ~70 lines / 17 KB, or "reading `05` at handoff feels like reading a log".
**Do not split early**: splitting a 30-line progress file means reading two files instead of one.

Two shapes, chosen by concurrency:

| Shape | Fits | Method |
|---|---|---|
| Single volume `06_会话日志.md` | one session / low concurrency | append-only; beyond 200 lines / 60 KB fold into `90` by topic |
| **Per-line shards** `06_流水/<line>.md` | parallel sessions (**recommended**) | one writer per file, no shared file at all; `06_会话日志.md` becomes a read-only history volume |

Shard names follow project workstreams (firmware / runtime / server / benchmark / docs / other); `其他.md` holds cross-line items. Each shard header states: write only your own line, never edit another's lines, 1–3 lines per entry, fold at 200 lines / 60 KB.

```bash
mkdir -p 06_流水
# move the exact line from 05 into the right shard using sed -n 'Np' >> plus cmp; never retype
sed -n 'Np' 05_进度仪表盘.md >> 06_流水/文档线.md
```

The `AGENTS.md` write-back section, `05` §5 and the shard headers are three copies of one rule: change one, sync the other two.

### Step 5 · Add mechanisms (replace discipline with mechanism)

| Mechanism | Acceptance |
|---|---|
| `AGENTS.md` as the single entry (+ two pointer lines in `CLAUDE.md` / `GEMINI.md`) | all three only say "which file to read, how to write", **never current values** |
| `00` `K-xx` numbers + status column (valid / unverified / superseded) | references cite IDs, never restate values; superseded rows keep their ID and are never reused |
| `05` §5 records the threshold table (§0 ≤4 lines, §6 ≤5 entries, shard 200 lines / 60 KB) | act only when crossed |
| End with `git add -A && git commit -m "<line> <what>"` | `git status` clean, one commit per step |
| Read-only self-check script (verify against the real device/remote, echo only) | run it first on every handoff |
| Daily check automation (optional) | reports go to `归档/体检/`, archived only: never into `05`/`06`, never committed |

> Add generated daily directories such as `归档/体检/` to `.gitignore`, or `git status` will permanently show an untracked directory.

## 3. Acceptance

1. **Four questions**: from `05` alone you can answer "status of each line / next step / pending and in progress / which files to read before changing a config".
2. **Diagnosis**: `py kb-check.py --target . --strict` → 0 ERR, 0 WARN.
3. **git**: `git status` clean, `git log --oneline` shows one commit per step.
4. **Onboarding cost**: `00` + `05` < 15% of the library (a measured legacy project landed at 8.2%).
5. **Numbering**: `kb-check.py` reports no duplicate K/G definitions, and cross-document references grep clean.

## 4. Rollback

git is the floor, one commit per step:

```bash
git log --oneline            # find the step to return to
git diff <commit>~1 <commit> # see what that step changed
git revert <commit>          # or git reset --hard <commit> (local, unpushed only)
```

Process content is never lost — it lives in `90` / `归档/`, so "deleted" process can always be recovered. That is the precondition for daring to slim the main documents.

## 5. Difference from building from scratch

| | From scratch | Legacy restructuring |
|---|---|---|
| Entry | `kb-init.py --target DIR --lines ...` | `kb-check.py --target DIR --loose` first |
| First step | generate the skeleton | `git init` + verbatim snapshot commit |
| Content | fill templates | **move** existing content; delete process, never conclusions |
| Risk | low | numbering contract, concurrent overwrites, credentials in history |
| Order | one shot | five steps, one commit each |

## 6. Real case (this project, 2026-11-08)

- Start: 5 documents, 1,262 lines, 221 KB to read on handoff (≈49k tokens), progress scattered across 4 places, no git.
- Path: clean up process → build `90` archive → build `05` → split `06` → `git init` → three `AGENTS.md` entries → `K-01`–`K-18` numbering with status → daily check automation → `kb-outline.py` section reads → six `06_流水/` shards.
- Result: the library grew to 310 KB (process archived, not deleted) while **handoff costs 25 KB / 8.2% (≈5.6k tokens)**, and `kb-check.py` is fully green.
- Concurrency in practice: `git status` repeatedly caught uncommitted `05`/`06` edits from other sessions; "append only + separate commits" avoided overwrites, and sharding brought each line to 10–14 lines, eliminating the shared file.
- Another project, FFRS, was diagnosed directly with `--loose` (custom naming `60_进度.md` / `00_INDEX.md`), producing a list of five WARN readings without any restructuring.

## 7. Anti-patterns

| Pitfall | Consequence |
|---|---|
| Running `git add` before excluding large files / credentials | They enter history and cannot be removed |
| Deleting process together with pitfalls and conclusions | The next session repeats the same road |
| Splitting `06` when the progress file is 30 lines | Handoff requires reading two files |
| Keeping three same-source copies of long text | One edit misses two; wording drifts |
| Reordering `§` or reusing `K-xx` IDs | Every cross-reference breaks |
| Whole-file overwrite of `05` | Erases lines another session just appended |
| A new session reading the whole library first | Keeps burning tokens; the restructuring was wasted |

## 8. v1 → v2 upgrade (`kb-migrate.py`)

A v1 library works; it only lacks three things: a protocol version marker, stable section IDs and hash-checked writes. Adding them requires no reordering and no body edits.

### 8.1 Decide whether to upgrade

```bash
S="$HOME/.skills-manager/skills/handoff-kb/scripts"
py "$S/kb-migrate.py" --target "[PROJECT_DIR]" --plan
```

Read three values: `schema` (`null` = v1), `section_ids` (`0` = no stable IDs), `fact_numbers`.

| Current state | Verdict |
|---|---|
| `schema: 2` and `section_ids > 0` | already v2, do nothing (the script skips it too) |
| `schema: null` | v1, upgrade recommended |
| Fact shards are `01`–`04` | **normal**; v2 compatible, no need to rename to `10`–`17` (see 8.3) |
| More than 8 fact shards | merge shards per §2 step 4 first, then migrate |

### 8.2 Upgrade actions (three kinds of increments only)

| Action | Behavior |
|---|---|
| Add protocol version | insert `<!-- kb:schema: 2 -->` as the first line of `00` / `05` |
| Add section IDs | add `<!-- kb:id: ... -->` to known sections by heading keyword; **sections that already have an ID are skipped** |
| Everything else | **untouched**. No renaming, no renumbering, no line deleted, no body edit |

The mapping lives in `kb-migrate.py::DASHBOARD_IDS` / `BASELINE_IDS`, matched by keyword in order, first hit wins; only `##`-level sections get IDs (`#` is the document title, not a fact section).

```bash
py "$S/kb-migrate.py" --target "[PROJECT_DIR]" --plan    # writes .kb-migrate-plan.json
py "$S/kb-migrate.py" --target "[PROJECT_DIR]" --apply   # verifies hashes, then applies
```

- The plan file `.kb-migrate-plan.json` is a **contract**: `schema_version: 2`, `root_id` (directory fingerprint), per-file `sha256_before` / `sha256_after`, `operations` (whitelist: `prepend` / `insert_before_heading`), `operation_count`, `generated_at`, `git_dirty`.
- `--apply` verifies item by item: schema, `root_id`, path legality (no `..` / absolute path / escape), duplicate paths, 64-hex hashes, operation type, insertion position, **single-line** inserted content, ≤200 operations per file. Any failure → exit 1, **not a single byte written**.
- After validation: take the workspace lock → recompute `sha_after` inside the lock and compare against the disk → start a transaction (backup + journal + rollback). So "someone edited the file after the preview" stops at the first step instead of being overwritten.
- Uncommitted changes refuse migration by default; add `--force` only after confirming those changes are unrelated.
- Idempotent: running twice reports "nothing to migrate" the second time.
- Crash mid-way: `kb-write.py recover --inspect` shows the scene, `--apply` rolls back; a journal checksum mismatch is only reported, the scene is preserved and never auto-cleaned.
- Rollback: `git checkout -- 00_*.md 05_*.md` (migration touches only these two, and both are in git).

### 8.3 Numbering compatibility (the most common misjudgement)

New v2 fact shards use **`10`–`17`**; `00` / `05` / `06` / `90` are reserved; **legacy `01`–`04` fact shards remain valid** — `kb-check.py` does not complain and `kb-context.py` reads them normally.

Why not "rename everything to 10–17": `§` numbers, `K-xx` references, other sessions' todos and external links all point at the old filenames. Reordering for one-off tidiness costs every reference in the library — exactly the root of the last anti-patterns in §7. **Mixing old and new is designed compatibility, not legacy baggage.**

### 8.4 Post-upgrade acceptance

```bash
py "$S/kb-check.py" --target "[PROJECT_DIR]"      # expect 0 ERR
py "$S/kb-outline.py" --target "[PROJECT_DIR]"    # expect a kb:id list
py "$S/kb-context.py" --target "[PROJECT_DIR]" --task "查看当前项目状态"
```

If the third line returns `dashboard.current` instead of nothing, the routing path is connected.
