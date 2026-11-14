# handoff-kb 2.0 Protocol

> This file is a **contract**. It contains no project facts. Scripts, templates and tests follow it;
> any protocol change must update `scripts/lib/protocol.py`, `assets/`, `tests/` and this file together.

Chinese edition: `protocol-v2.zh-CN.md`.

## 1. Version and compatibility

| Item | v1 | v2 |
|---|---|---|
| Schema marker | none | first line of the file: `<!-- kb:schema: 2 -->` |
| Fact shards | `01–08` (collides with `05`/`06`) | `10–17`; legacy `01–04` remain valid |
| Section addressing | heading text / ordinal | `<!-- kb:id: ... -->`, legacy lookups kept |
| Writes | manual append | full `sha256` + lock + transaction |
| Hashing | 12-char text short hash | 64-hex for writes; short hash only for compatible reads |

A legacy library needs no renaming to be read by v2 tools (`kb-check.py --loose`); `kb-migrate.py` only adds annotations.

## 2. File roles and reserved numbers

| Number | Role | Canonical name | Notes |
|---|---|---|---|
| — | Entry | `AGENTS.md` + `CLAUDE.md` / `GEMINI.md` | Rules only, never current values |
| `00` | Baseline | `00_基线.md` (`00_baseline.md`) | Single shared page: `K-xx` + status + evidence |
| `05` | State | `05_进度仪表盘.md` | Required on handoff; must not bloat |
| `06` | Log | `06_会话日志.md` + `06_流水/<line>.md` | History volume read-only; one writer per shard |
| `10–17` | Fact shards | `10_<line>.md` … `17_<line>.md` | At most 8 workstreams |
| `01–04` | Legacy fact shards | original filenames | Read-compatible; never renamed by migration |
| `90` | Archive | `90_过程档案.md` | Not required reading |

Role detection uses the file name only (`scripts/lib/protocol.py: role_of_name`). Size accounting and search skip `AI_files/`, `assets/`, `data/`, `output/`, `evidence/`, `paktools/`, `build/`, `dist/`, `vendor/`, `tmp/`, `node_modules/`, `.git`, `.kb-txn`, `.kb.lock`, `unpack/`, `_tmp/`, `.trash/`, and any text file larger than 2 MB.

**AI client directories are skipped too**: `.workbuddy`, `.shared`, `.codex`, `.qoder`, `.trae`, `.claude`, `.cursor`, `.gemini`, `.aider`, `.continue`, `.windsurf`, `.agents`, `.kiro`, `.zed`, `.junie`. Markdown there is agent work logs and project index cards, not handoff body text; searching them returns "what happened on some day" and pushes shard conclusions out of the budget. `.workbuddy/memory` is often a symlink to `.shared/memory`, so the same content would be counted twice and hit scores doubled.

### 2.1 Custom naming (`--loose`)

Legacy projects need no renaming: under `--loose`, fixed layers are recognized by **alias**.

| Role | Canonical | Alias (regex on file name, case-insensitive) |
|---|---|---|
| Baseline | `00_基线.md` | contains `INDEX` / `索引` / `baseline` / `基线` |
| State | `05_进度仪表盘.md` | contains `进度` / `现状` / `dashboard` / `status` |
| Log | `06_会话日志.md` | contains `流水` / `日志` / `log` / `handoff` |
| Archive | `90_过程档案.md` | contains `归档` / `archive` |
| Log shard dir | `06_流水/` | dir matches `^(\d{2,3}[_\- ]?)?(流水|会话流水|shards?|sessions?)$`, e.g. `60_流水/` |
| Archive dir | `归档/` | dir matches `^(\d{2,3}[_\- ]?)?(归档|旧档|历史|archive|archived)$`, e.g. `90_归档/` |

When several match, the **canonical name wins** (`role_files()` picks explicitly), so an extra `60_进度.md` never displaces `05_进度仪表盘.md`. If both `06_流水/` and `60_流水/` exist, both are collected, without duplicates.

**Fact-shard fallback**: after alias matching, under `--loose` any `NN_xxx.md` whose number is not reserved (`00/05/06/90`) is treated as a fact shard — custom-naming projects commonly use `20_数据与解包.md` / `30_mod开发.md` / `50_死路与坑.md` for D/M/O/X entries, and these take part in P2 assembly and fact parsing exactly like `10–17`. Aliases match first, so `60_进度.md` (dashboard) and `61_流水.md` (log) are not swallowed as facts. Canonical naming is unaffected.

A number is an entry ticket, not a verdict: prose files such as `20_会议记录.md` / `40_临时测试.md` are still collected under `--loose`, but since they contain no fact entries they are treated as candidate shards (not a workstream in P2, weight 0.5 in P4, and the gap says "read as leads"). The criterion lives in `facts.fact_confidence()`; `01–04` and `10–17` are protocol-designated fact positions and never take this downgrade — missing `fact.*` sections there is a writing problem. Conversely, a single-fact shard whose heading is `G-001` counts as structured: one fact is still a fact, not prose.

## 3. Section IDs

```markdown
<!-- kb:id: dashboard.current -->
## 0. 现状
```

- Format: `[A-Za-z0-9][A-Za-z0-9_.:-]*`; the convention is `<domain>.<section>`, e.g. `dashboard.next`, `fact.pitfalls`.
- Binding: the comment must be **adjacent** to the heading, only blank lines between; inside a code fence it does not count.
- Uniqueness: no duplicates within a file (`kb-check.py` reports ERR).
- Decoupling: an ID is independent of heading text and line numbers; renaming or inserting sections never breaks references.
- Reserved IDs (tool-dependent): `dashboard.current`, `dashboard.next`, `dashboard.lines`, `dashboard.todo`, `dashboard.constraints` (or `dashboard.safety`), `dashboard.summary`, `baseline.facts`, `baseline.policy`, `baseline.chains`, `baseline.rules`, `fact.current`, `fact.commands`, `fact.pitfalls`, `fact.refs`.
- When an ID is missing, tools fall back to heading/ordinal matching but **do not guarantee** stability across sessions; `kb-check.py` reports WARN.

## 4. Fact metadata (the `00` baseline table)

| Column | Meaning | Values |
|---|---|---|
| `ID` | Fact number | `K-01` / `G-007`; kept when superseded, never reused |
| `状态` | Current trust | `有效` / `待核` / `已作废 → K-xx` |
| `证据` | Reproducible source | command / file path / test name / commit |
| `核实时间` | Last verified | `YYYY-MM-DD`; older than `--max-age-days` (default 90) only warns |

Optional fields: `owner` (owning workstream), `volatility` (`stable` / `dynamic`), `superseded_by`.

Rules: `有效` with empty evidence → `kb-check.py` WARN and `kb-handoff.py` grades it unverified; **"the AI said it is done" is never evidence**; exceeding the age limit never rewrites the value, it only warns.

## 5. `changes.json` (write protocol)

```json
{
  "schema_version": 1,
  "updates": [
    {"path": "05_进度仪表盘.md", "expected_sha256": "<64 hex>",
     "operation": "replace_section", "section_id": "dashboard.current",
     "content": "<new body>"},
    {"path": "06_流水/固件.md", "expected_sha256": "<64 hex>",
     "operation": "append", "content": "<appended content>"},
    {"path": "00_基线.md", "expected_sha256": "<64 hex>",
     "operation": "update_fact", "fact_id": "K-02", "content": "<new table row>"}
  ]
}
```

| Operation | Semantics | Required fields |
|---|---|---|
| `replace_section` | Replace the body of that ID's section; if `content` starts with a heading, the heading is replaced too | `section_id`, `content` |
| `append` | Append at end of file, preceded by one blank line | `content` |
| `update_fact` | Locate the fact definition (heading / list / table) and replace the whole line; if not found it errors instead of inserting | `fact_id`, `content` |

Hard validation: `schema_version == 1`; `expected_sha256` must be 64 hex; paths must be relative to the workspace root, extension `.md`/`.txt`, without `..`, without crossing symlinks; all updates are validated before the first byte is written.

**Fact definition positions** (shared by `update_fact` and `kb-check` via `lib/facts.py`):

| Form | Example | Notes |
|---|---|---|
| Heading | `## K-01 固件版本` | the first token of the heading is the ID |
| List | `- K-01：固件 21.02` or `- **K-01** 固件 21.02` | the colon is optional; text after it is the description |
| Table | `| K-01 | 项 | 值 |` | the **first column** is the ID |

The same text inside a code fence is **not** a definition. Other IDs mentioned on a definition line are references (e.g. `已作废 → K-04`). When one ID has **multiple** definitions in a file, `update_fact` refuses to write (ambiguous) rather than guessing.

## 6. Hashing, locking, transactions

- **Hashing**: `sha256(file bytes)`; `kb-write read` returns the full value, `kb-outline --hash` accepts the legacy 12-char text short hash (prefix match).
- **Lock**: `<root>/.kb.lock/` (atomic `mkdir` + `meta.json` with `owner_token`(uuid4), `pid`, `host`, `process_start`, `created`, `session`). Rules:
  - live process → wait until timeout (`KB_LOCK_TIMEOUT`, default 5s), then `LockHeld` with the peer's pid/host/session in the message;
  - dead process **on the same host** → `os.rename` to `.kb.lock.reclaim-<uuid>` → re-check `owner_token` → only then delete;
  - `pid` alive but a different `process_start` (PID reuse) → treat as exited and reclaimable;
  - missing or corrupt `meta.json` → **do not seize**, require manual confirmation;
  - `release()` verifies `owner_token` and `pid`; if another process took over the lock, it **refuses to delete** and raises `LockOwnershipError`;
  - explicit unlock is `kb-write.py recover --break-lock` (preview by default), `--force` actually deletes and re-verifies the token first.
- **Transaction**: `<root>/.kb-txn/` (`journal.json` + `backup/`). State machine `created → prepared → applying → committed`; failure goes `rolling_back → rolled_back | rollback_conflict`. Order: 1) full pre-checks (strict UTF-8, paths, hashes, duplicate paths) → 2) byte-level backup + `backup_sha256` → 3) write journal (`prepared`, with checksum) → 4) atomic replace one by one, writing back each entry's state → 5) `committed` → 6) delete the transaction directory; any failure rolls back from backups and marks `rolled_back`.
- **Journal schema 2**: carries `checksum` (serialize with `sort_keys` after removing the checksum, then `sha256`). Checksum mismatch, unsupported schema or illegal state makes the journal **untrusted**: `recover` reports `manual-recovery-required` and keeps the transaction directory and backups **exactly as they are** — never `rmtree`.
- **Recovery**: `recover` compares each file's current hash against `sha_before` / `sha_after`:
  - `now == sha_after` → already written; rollback restores the backup;
  - `now == sha_before` → untouched, skip;
  - anything else → `changed-by-others`, **do not overwrite**, escalate to manual handling.
  A backup whose hash does not match is `backup-corrupt`, and the scene is preserved likewise. `recover` accepts both `.kb-txn/journal.json` (in-flight) and `.kb-txn/<id>/journal.json`.
- **Atomicity boundary**: several `os.replace()` calls are not a cross-file atomic transaction. The protocol promises full pre-checks, backups, rollback on failure and post-crash detection; git remains the final audit and rollback mechanism.

## 7. Context assembly (`kb-context`)

| Priority | Content | When the budget is short |
|---|---|---|
| P0 | `dashboard.constraints` / `dashboard.safety` (fallback: the `AGENTS.md` hard-constraints section) | **kept**, and the overrun is reported |
| P1 | `dashboard.current`, `dashboard.next` | kept |
| P2 | `fact.current` (plus `fact.commands` / `fact.pitfalls` for troubleshooting tasks) | may be skipped and recorded in `skipped` |
| P3 | matched baseline rows, evidence pointers, `baseline.chains` (cross-line or "impact" questions) | may be skipped |
| P4 | the rest by relevance (≤30% of budget and ≤3 blocks; log ×0.4, archive ×0.3, other ×0.5) | may be skipped |

P4 candidate filtering has three hard gates, each earned from a real failure:

- **Score against the section's own body only.** A section runs "to the next heading of the same level", so a parent's body naturally contains all children; scoring on that body makes every parent outrank its children while pulling in the whole subtree. Scoring and "empty shell" detection use only the content between the heading and the next heading of any level; output is still the whole section. Exception: a container section whose subtree holds superseded facts is kept — only it can say "N entries omitted here".
- **Skip the duplicated part of a file preamble.** The first `level==1` section holds "what this file is about" and the applicable version, so every topic word of the shard is in it and it always ranks top by hit count. It is not dropped unconditionally: it is dropped only when the child keyword set covers the h1 **and** a sentence-by-sentence comparison finds nothing in the h1's own body that the children omit. If the h1 holds something the children do not (negative conclusions, entry pointers), it stays. Task-relevant short phrases (`只读`) are not ignored by character count; when preamble and fact share one sentence (`适用版本 2.0，生产环境禁止写入`), only the preamble half is stripped and the prohibition still participates.
- **Skip heading-only shells** (empty own body and no superseded facts in the subtree). Exception: the **small-shard fallback** — if no qualifying section exists anywhere in a container's subtree and the section is ≤600 tok, it competes as a whole. Otherwise a 1–2 KB shard disappears entirely (parent is a shell, children each hit only one word).

Weight ladder: structural body (`fact` / `baseline` / `dashboard`) 1.0, log and shards 0.4, archive 0.3, everything else (`other`: entry files, one-off release notes, search records, coverage matrices) 0.5. `other` used to be 1.0, and a 62 KB search record could hit a few words for any task and outrank shard entries by sheer size, taking one of P4's three slots.

**Candidate shards** (under `--loose`, numbered like a shard but not shaped like one) are judged by content, in two evidence tiers:

- strong evidence: **the heading itself is a fact ID** (`## G-001 当前 MTU` / `### D-011 …`) — **one is enough** for `structured`. A newly created line with a single verified value is a legitimate state and must not be graded as prose for lacking a second entry.
- weak evidence: list items / first table column / IDs mentioned in prose may just be examples — still requires **≥2**; a `fact.*` section ID also counts as structured.

Everything else becomes `fact-candidate`: not assembled as a workstream in P2 (there are no fact sections there), weight 0.5 in P4, and the gap states "added N sections from candidate shards: numbers only, no fact entries, read as leads". No project-specific filename appears in the criteria, so another custom-naming project needs no code change.

**`--line` fallback**: when a workstream is named explicitly and its shard has no `fact.current` / `fact.commands` / `fact.pitfalls`, take its own fact sections (heading is the fact ID, at most 3, ordered by task keywords). Otherwise `--line 数据与解包` in a custom-naming project returns 0 blocks — a line was named and nothing was delivered. This applies only to an **explicit `--line`**; a line name merely mentioned inside the task does not take this path, which keeps a whole section from flushing out cross-line conclusions such as `baseline.chains`.

P4's `used_sources` compares relative paths, not file names: the `source` field stores only the file name for humans, so same-named files in subdirectories would be judged unused and loaded twice. A content-hash dedupe additionally prevents the same text arriving by another path (symlink, copy) from being loaded twice.

**Added ≠ whole line loaded**: P2 matches by line name, so a task without a line name leaves it empty and reports a gap; P4 then adds one or two sections of that line by content and the gap is withdrawn — but nobody should conclude the whole workstream came in. After withdrawal the boundary must be stated: `P4 added N fact sections (…): section-level supplement, not a complete load of that workstream; use --line for the whole line`. When the budget drops it, the wording differs: `selected but does not fit the total budget` / `exceeds the P4 budget share` — never "added".

- **Multiple workstreams**: `--line 固件,运行态`, or all lines named in the task are loaded; keyword-only matches take the single highest score.
- The budget converges on the **final rendered text**: wrappers (headings / sources / reasons / gaps / pointers) all count. Lines that do not fit go to `omitted_lines` and `gaps` ("relevant facts of workstream X were not loaded…"); a line with no fact sections is explained separately ("no fact.current…"). **Never describe "not written" as "budget too small".**
- Default budget 3000; `--format json` outputs `blocks / skipped / gaps / used / over_budget / selected_lines / omitted_lines / block_tokens / rendered_tokens / required_tokens / exact / p4 / p4_facts / p4_candidates / deduped`. `p4_facts` holds sections from real fact shards; `p4_candidates` holds sections from candidate shards (numbers only, no fact entries) so consumers need not guess what was verified.
- Every block carries `text_sha` (first 12 hex of the body sha256): JSON blocks carry no body, so this is the only way to tell "same passage loaded twice" from "one section split into two blocks by purpose".
- `deduped` lists content-deduped blocks and their `kept_in`. It is listed only when the kept copy actually entered the context — if that copy was also trimmed by the budget, the content never arrived and reporting "deduped" would mislead.
- Keys of `context` are `section_id`; when one ID yields several blocks (baseline hit + evidence pointer) suffixes are added automatically, so they never overwrite each other.
- No hit at all → explain in `gaps`; **never invent**.
- Tokens: `heuristic` (CJK 1 char ≈ 1 token, other 4 chars ≈ 1 token) by default; when tiktoken is available the encoder name is recorded. A requested tiktoken encoder that cannot be installed → exit 2; only an explicit `--allow-tokenizer-fallback` degrades (`exact: false`).

## 8. Exit codes

| Code | Meaning |
|---|---|
| 0 | success / nothing missing (under `--strict`, a WARN also returns 1) |
| 1 | validation failure, conflict, unverified item, budget overrun, any ERR |
| 2 | usage or environment error (missing target, illegal path, conflicting arguments) |

`kb-hooks.py run` is the exception: **always 0**. A hook must never break a session.

## 9. Explicitly out of scope

Vector stores / SQLite indexes / embeddings / long-running MCP / multi-project hub / knowledge graph / cloud sync / automatic LLM summarization / automatic commits / global config edits. Scale limits are held by mechanisms (git + thresholds), not by discipline.
