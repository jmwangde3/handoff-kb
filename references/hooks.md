# Client Hooks (optional, never installed by default)

> Read this first: **event names, JSON shapes, stdout/stderr semantics and exit-code meanings differ per client and change between versions.**
> This repository only promises "generate project-level config + read-only runtime"; it does not promise byte-level compatibility with any client version.
> Inspect with `--plan` before installing, and adjust a line against that client's current official docs if needed.

Chinese edition: `hooks.zh-CN.md`.

## 1. Design principles

1. **Off by default**: not installing means zero impact.
2. **Preview first**: without `--write` nothing is written; only "added / removed / kept / SHA before and after" is printed.
3. **Read-only**: `run` writes no document, runs no `git commit`, edits no config, makes no network call, invokes no LLM.
4. **Never blocking**: `run` swallows every exception and exits 0; it **does not use** `decision: block` and never prevents compaction or session end.
5. **Project level**: writes only `<target>/.claude/settings.json` or `<target>/.codex/…`, never global config.
6. **Reversible**: `uninstall` removes only entries this tool wrote (command contains `kb-hooks.py`) and keeps other hooks; event tables emptied in JSON and `[[hooks.X]]` headers emptied in TOML are removed as well, leaving no shells.

## 2. Event behavior and output shape

| Client | Event | Behavior | stdout |
|---|---|---|---|
| Claude / Codex | `SessionStart` | runs `kb-context.py --mode handoff --budget 1200` | `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "<context>"}}` |
| Claude | `PreCompact` | reminds to wrap up (first `kb-handoff.py check`, then `kb-write.py`) | **plain text** (Claude uses it as the compaction-summary instruction) |
| Codex | `PreCompact` | same reminder | `{"systemMessage": "…"}` (Codex shared field) |
| Claude / Codex | `Stop` | runs `kb-handoff.py check`; speaks only when something is incomplete | problems → `{"systemMessage": "…"}`; clean → `{}` |
| Claude only | `SessionEnd` | empty response (placeholder, deliberately does nothing) | `{}` |

- Apart from `Stop`, the hook never "educates" the model; `Stop` nudges once only when the handoff is genuinely incomplete, and **never blocks** the end.
- Unknown event / target is not a handoff library / project root unusable → emit an empty object and exit 0; the session is unaffected.
- Both clients list `SessionStart` sources as `startup|resume|clear|compact|fork`; the generator writes all five for both (2.0.1 omitted `clear`, so "clear the session and restart" got no handoff context; fixed in 2.0.1-hotfix).
- The trigger source does not change runtime behavior: all five inject the same budgeted context.
- **`PreCompact` output is not portable between clients**: Claude Code explicitly "discards a PreCompact hook's `systemMessage` and `continue` fields", so on a non-blocking exit 0 **plain-text stdout** is the compaction instruction; Codex's `PreCompact` honors the shared `systemMessage` field, ignores plain-text stdout, and has no `customInstructions`. The same reminder is therefore emitted per client rather than one JSON for both (2.0.1-hotfix: previously Claude also received `systemMessage`, which said nothing).

## 2.1 Official references (checked 2026-11)

| Client | Docs | Facts this repository relies on |
|---|---|---|
| Codex | `developers.openai.com/codex/hooks` (now redirects to `learn.chatgpt.com/docs/hooks`) | three-level structure `event → [{matcher, hooks:[{type,command}]}]`; five `source` values for `SessionStart`; `hookSpecificOutput.additionalContext`; `PreCompact` exists and honors shared `systemMessage` (matcher is `trigger`: `manual` / `auto`); plain-text stdout ignored in `PreCompact`; no `customInstructions`; `additionalContext` caps around 2500 tokens (over the cap it writes a temp file and shows head/tail previews only) |
| Claude Code | `code.claude.com/docs/en/hooks` | same three-level structure; project-level `.claude/settings.json` applies but is subject to workspace trust; five matcher values for `SessionStart`; `PreCompact` matcher is `manual` / `auto`; **`PreCompact` discards `systemMessage` and `continue`**, so when non-blocking, plain-text stdout is the compaction instruction (cap 10,000 characters); `additionalContext` cap around 10,000 characters |

`--budget 1200` is deliberately below both injection caps: better to give slightly less than to be truncated into a head/tail preview.

## 3. Install location and structure

| Client | File | Structure |
|---|---|---|
| Claude Code | `.claude/settings.json` | `hooks.<Event>[{"matcher": "", "hooks": [{"type": "command", "command": "…"}]}]` |
| Codex | `.codex/hooks.json` | the same **three-level** structure `{matcher, hooks:[{type, command}]}` (2.0.1-hotfix: previously written flat as `{type, command}`, which the official format rejects) |
| Codex | `.codex/hooks.snippet.toml.txt` | an `[[hooks.<Event>]]` snippet to merge manually into `config.toml`, validated with `tomllib` before writing |

Generated commands use **absolute paths** (config is generated per machine; variables such as `$KB` are not expanded):

```bash
python "C:/Users/<you>/.skills-manager/skills/handoff-kb/scripts/kb-hooks.py" run \
  --client claude --event SessionStart --target "C:/proj" [--loose]
```

`--loose` appears verbatim in the generated command; custom-naming projects (`60_进度.md`) must include it.

## 4. How the runtime locates the project root

1. Read the event JSON from stdin (the client puts `cwd` in it).
2. `--target` is an **absolute path** written at install time: cross-checked against the event `cwd`, and only mutual containment counts as the same library; outside that range **nothing is injected** and the reason is stated — so project A never injects project B's context.
3. `--target .` (legacy config): trust the event `cwd` only, and it must look like a handoff library (has `00`/`05`).
4. stdin is **probed before reading** (Windows `PeekNamedPipe` / POSIX `select`): with no input it returns immediately instead of hanging on `sys.stdin.read()` until timeout as before.

## 5. Usage

```bash
KB="$HOME/.skills-manager/skills/handoff-kb"
py "$KB/scripts/kb-hooks.py" install   --client claude --target .            # preview (default)
py "$KB/scripts/kb-hooks.py" install   --client claude --target . --write     # write
py "$KB/scripts/kb-hooks.py" uninstall --client claude --target . --write
py "$KB/scripts/kb-hooks.py" run --client claude --event SessionStart --target . < event.json
```

- `--plan` and omitting `--write` both print only; nothing is written.
- Double pre-check before writing: both `original_exists` and `sha_before` must match the preview. A hash alone cannot distinguish "did not exist" from "exists with identical content", so a user file created after preview would be overwritten as if this tool should create it — that case is now a CONFLICT and nothing is written.
- **A multi-file install is one unit**: pre-check all targets, write only if all pass; on a mid-way failure, restore the files written in this round to their pre-preview content; if rollback finds a file changed by a third party, **preserve the scene** and report a conflict instead of forcing an overwrite. (This is "pre-check + sequential write + best-effort rollback", not a cross-file atomic transaction.)
- Rollback itself uses **atomic byte writes** (temp file → `os.replace` → fsync the directory): it previously used `write_bytes()` directly, so a crash mid-write turned a previously intact config into a truncated file.
- A target directory that is a symlink/junction escaping the library is refused (`ERR … 目录不可用`).
- Invalid existing JSON is **never rewritten** (exit code 2); the tool neither guesses nor swallows your config.
- Repeated `install` is idempotent (one command per event for this tool); `uninstall` is idempotent.

## 6. Known uncertainties (verify against official docs as needed)

- Whether Claude Code's `Stop` / `SessionEnd` support blocking, and whether stdout is injected as context, varies between versions.
- Codex `hooks.json` and `config.toml` are **mutually exclusive sources**; do not enable both. Key names follow its docs.
- **Trust model**: non-managed hooks must be reviewed and trusted at their current hash; editing config returns them to pending review, and they are skipped until trusted. Not being trusted is not a failure — fall back to running the CLI manually; no functionality is lost.
- The conclusions above cover up to 2026-11; after a client upgrade the official docs win, and this repository does not promise byte-level compatibility.

> Verification boundary of this repository: **structure tests pass, simulated events pass, a real client start was not verified.**
> The six-environment CI runs Python unit tests and smoke only; it does not launch Claude/Codex clients.

## 7. Backing out

1. `uninstall --write` removes the entries;
2. or delete the items containing `kb-hooks.py` from `.claude/settings.json` by hand;
3. a hook error never affects the session (`run` always exits 0); to diagnose, run the same `run` command manually and read the output.
