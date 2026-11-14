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

- [ ] Every protocol identifier, command and JSON key in `SKILL.md` matches the implementation, not just the reference text.
- [ ] Error conditions and exit codes in `SKILL.md` match the implementation.
- [ ] The eight strength-bearing sentences the test pins still read as prohibitions after any rewording (Never / no … may, not should / consider).
- [ ] Chinese templates and the four Chinese references are still byte-identical to v2.0.3.

## Not verified — do not claim otherwise

- [ ] A real client (Codex / Claude Code) reading this English skill while maintaining a Chinese library. The *CLI* cross-language path is covered by tests above; the *agent following the instructions* has not been run in a real client.
- [ ] The English template set after months of use in a long-lived English library.
