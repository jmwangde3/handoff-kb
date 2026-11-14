# Semantic checklist — 2.0.4 (one skill, English instructions)

Automated layer: `test_token_language.py` (layout, rules, identifiers, scenarios, token targets).
This sheet is the human review that remains after the automated checks.

| # | Rule | In `SKILL.md` | Reviewer |
|---|---|---|---|
| 1 | P0 never silently discarded | ok | |
| 2 | P1 current state and next step | ok | |
| 3 | P2 workstream facts | ok | |
| 4 | P3 explicit fact IDs and evidence | ok | |
| 5 | P4 bounded relevance | ok | |
| 6 | P0 fallback order | ok | |
| 7 | P4 limits (blocks and budget share) | ok | |
| 8 | superseded fact handling | ok | |
| 9 | gap reporting honest | ok | |
| 10 | write requires current hash | ok | |
| 11 | lock conflicts not bypassed | ok | |
| 12 | multi-file writes not database-atomic | ok | |
| 13 | migration preserves source content | ok | |
| 14 | hooks never block a session | ok | |
| 15 | no credentials committed | ok | |
| 16 | reference loading is not default | ok | |
| 17 | existing v2 projects keep working | ok | |
| 18 | language independence declared | ok | |
| 19 | never auto-translate existing documents | ok | |

## Verified automatically

- One discoverable skill; no second skill document outside `tests/`.
- Frontmatter name/description; 9 numbered sections.
- Every `scripts/kb-*.py` named in the skill exists, and every script that exists is named.
- Every documented `--flag` is implemented (`--help` of each script and subcommand).
- `changes.json` keys and operation names exist in `kb-write.py`.
- Every cited `dashboard.*` id is either defined by a template or recognised by the P0 resolver as a legacy alias.
- Chinese project / English project: `kb-check` clean, `kb-context` routes, `kb-init --lang {zh,en}` scaffold the same file set.
- `--lines` defaults per `--lang` (`线A…` / `lineA…`), an explicit list always wins, and both defaults keep the same `kb:id` set and reserved filenames.
- The four Chinese references are byte-identical to their v2.0.3 baseline (SHA256), so the A/B/C measurement cannot drift.
- A fallback counts with the algorithm it reports (`effective_mode`), and a missing vocabulary raises unless fallback is explicit.
- Vocabulary fingerprint (file name, SHA256, library version) present and free of personal paths; a missing encoder exits 2.

## Manual review points

- [x] Every protocol identifier, command and JSON key in `SKILL.md` matches the implementation, not just the reference text.
- [x] Error conditions and exit codes in `SKILL.md` match the implementation.
- [x] The eight strength-bearing sentences the test pins still read as prohibitions after any rewording (Never / no … may, not should / consider).
- [x] Chinese templates and the four Chinese references are still byte-identical to v2.0.3.

## Review evidence — 2026-11-14

Self-review by the implementing agent on tree `63f6ac0`, against the checked-out code and live CLI runs. **It is not an independent third-party audit.**

| # | Check | Compared against | Tests | Result |
|---|---|---|---|---|
| 1 | Protocol ids, commands, JSON keys, script names, flags | `references/protocol-v2.md`, `scripts/kb-write.py`, `scripts/`, every `--help` | `test_protocol_ids_are_consistent`, `test_json_contract_matches_implementation`, `test_every_script_is_mentioned`, `test_documented_flags_exist` | 4 `dashboard.*` ids reachable (3 templates + 1 resolver alias); 10 scripts match in both directions; 27/27 cited flags implemented |
| 2 | Error conditions and exit codes | implementation + live runs | `test_hash_conflict_refuses`, `test_lock_held_blocks`, `test_secret_blocks_write`, `test_recover_apply_restores_partial_write_via_cli`, `test_break_lock_refuses_live_holder` | missing encoder → 2, then 0 with `exact=false`; `CONFLICT` → 1; `LockHeld` → 1; path escape → 2; `--strict` → 1; migration hash drift → 1 with nothing written; `--dry-run` wrote nothing. Atomicity is stated as *not* database-level — no overstatement found |
| 3 | Eight strength-bearing sentences | `SKILL.md` wording | `test_security_wording_did_not_decay` | all eight still prohibitions (never / are never / not / no … may), no should / consider |
| 4 | Frozen Chinese content | `baseline/v2.0.3/` + `MANIFEST.json` | `test_chinese_references_are_byte_identical_to_v203`, `test_manifest_matches_files`, `test_no_extra_baseline_files`, `test_chinese_templates_are_unchanged_from_v203` | 4/4 references and 12/12 templates SHA256-equal; 19 frozen files, none extra or missing |

## Not verified — do not claim otherwise

- [ ] A real client (Codex / Claude Code) reading this English skill while maintaining a Chinese library. The *CLI* cross-language path is covered by tests above; the *agent following the instructions* has not been run in a real client.
- [ ] The English template set after months of use in a long-lived English library.
