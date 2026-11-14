# Semantic parity checklist — 2.0.4

Automated layer: `test_token_language.py` (structure, rules, scenarios).
This sheet is for human review after translation changes.

| # | Rule | English | Chinese | Reviewer |
|---|---|---|---|---|
| 1 | P0 never silently discarded | ok | ok | |
| 2 | P1 current state and next step | ok | ok | |
| 3 | P2 workstream facts | ok | ok | |
| 4 | P3 explicit fact IDs and evidence | ok | ok | |
| 5 | P4 bounded relevance | ok | ok | |
| 6 | P0 fallback order | ok | ok | |
| 7 | P4 limits (blocks and budget share) | ok | ok | |
| 8 | superseded fact handling | ok | ok | |
| 9 | gap reporting honest | ok | ok | |
| 10 | write requires current hash | ok | ok | |
| 11 | lock conflicts not bypassed | ok | ok | |
| 12 | multi-file writes not database-atomic | ok | ok | |
| 13 | migration preserves source content | ok | ok | |
| 14 | hooks never block a session | ok | ok | |
| 15 | no credentials committed | ok | ok | |
| 16 | reference loading is not default | ok | ok | |
| 17 | existing v2 projects keep working | ok | ok | |

## Manual review points

- [ ] Every protocol identifier, command and JSON key in the Chinese and English references is byte-identical.
- [ ] No exception was silently dropped from the translated reference.
- [ ] Error conditions and exit codes match the implementation.
- [ ] Security warnings survive translation with the same strength (MUST / MUST NOT, not SHOULD).
- [ ] Chinese templates still render byte-identical to v2.0.3 apart from wording.
- [ ] An English skill over a Chinese project still produces Chinese document content (language is not auto-translated).
