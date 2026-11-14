# Token benchmark — A / B / C

| Item | Value |
|---|---|
| tokenizer requested | `cl100k_base` |
| tokenizer actual | `tiktoken:cl100k_base` |
| exact | true |
| python | 3.13.9 |
| tiktoken | 0.14.0 |
| tokenizers | 0.23.2 |
| deepseek tokenizer | present |

Variants: **A** original Chinese v2.0.3, **B** optimized Chinese v2.0.4, **C** optimized English v2.0.4.
`structure = 1 - B/A`, `language = 1 - C/B`, `total = 1 - C/A`.

## T1 · YAML description

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| description | 117 | 117 | 69 | +0.0% | +41.0% | +41.0% |

## T2 · SKILL.md

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| SKILL.md | 5416 | 5486 | 3871 | -1.3% | +29.4% | +28.5% |

## T3 · Reference files (each read alone)

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| protocol-v2 | 6514 | 6514 | 4910 | +0.0% | +24.6% | +24.6% |
| migration | 6012 | 6012 | 4450 | +0.0% | +26.0% | +26.0% |
| hooks | 3013 | 3013 | 2235 | +0.0% | +25.8% | +25.8% |
| benchmark | 6809 | 6809 | 5207 | +0.0% | +23.5% | +23.5% |

## T4 · Complete task reading paths

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| New project initialization | 5416 | 5486 | 3871 | -1.3% | +29.4% | +28.5% |
| Existing project diagnosis | 5416 | 5486 | 3871 | -1.3% | +29.4% | +28.5% |
| Legacy project migration | 11428 | 11498 | 8321 | -0.6% | +27.6% | +27.2% |
| New-session context recovery | 11930 | 12000 | 8781 | -0.6% | +26.8% | +26.4% |
| Safe document write | 11930 | 12000 | 8781 | -0.6% | +26.8% | +26.4% |
| Hook installation | 8429 | 8499 | 6106 | -0.8% | +28.2% | +27.6% |

## T5 · Project templates (each file alone)

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| AGENTS.md | 1558 | 1558 | 1220 | +0.0% | +21.7% | +21.7% |
| 00_baseline.md | 667 | 667 | 540 | +0.0% | +19.0% | +19.0% |
| 05_dashboard.md | 971 | 971 | 751 | +0.0% | +22.7% | +22.7% |
| fact_book.md | 342 | 342 | 266 | +0.0% | +22.2% | +22.2% |
| 06_index.md | 171 | 171 | 140 | +0.0% | +18.1% | +18.1% |
| 06_log.md | 200 | 200 | 149 | +0.0% | +25.5% | +25.5% |
| 06_shard.md | 202 | 202 | 155 | +0.0% | +23.3% | +23.3% |
| 90_archive.md | 190 | 190 | 138 | +0.0% | +27.4% | +27.4% |
| 启动消息.txt | 436 | 436 | 361 | +0.0% | +17.2% | +17.2% |
| gitignore.txt | 225 | 225 | 168 | +0.0% | +25.3% | +25.3% |
| gitattributes.txt | 9 | 9 | 9 | +0.0% | +0.0% | +0.0% |
| migration-prompt.txt | 1150 | 1150 | 825 | +0.0% | +28.3% | +28.3% |

## T4 detail — which files each task reads

- **New project initialization** (`new-project`): reads `skill` — A 5416 / B 5486 / C 3871 tokens, total +28.5%
- **Existing project diagnosis** (`diagnose`): reads `skill` — A 5416 / B 5486 / C 3871 tokens, total +28.5%
- **Legacy project migration** (`migrate`): reads `skill`, `ref:migration` — A 11428 / B 11498 / C 8321 tokens, total +27.2%
- **New-session context recovery** (`recovery`): reads `skill`, `ref:protocol-v2` — A 11930 / B 12000 / C 8781 tokens, total +26.4%
- **Safe document write** (`safe-write`): reads `skill`, `ref:protocol-v2` — A 11930 / B 12000 / C 8781 tokens, total +26.4%
- **Hook installation** (`hook-install`): reads `skill`, `ref:hooks` — A 8429 / B 8499 / C 6106 tokens, total +27.6%

## Limitations

- tiktoken encodings (`cl100k_base`, `o200k_base`) are reproducible proxies; they are not every model's billing tokenizer.
- `deepseek_v4` uses the official offline tokenizer (`tokenizers` + `tokenizer.json`); `deepseek_estimate` only applies the documented ratio (1 English char ≈ 0.3, 1 Chinese char ≈ 0.6) and is an estimate.
- The heuristic counter (CJK 1 char ≈ 1 token, other 4 chars ≈ 1 token) is reported as an estimate only and is never used for a conclusion.
- Structure is compared through section headings and protocol IDs, not through semantic equivalence of every sentence; see `test_token_language.py`.
- Task paths list the documents a task actually needs; references that are not required are not counted as default-loaded content.

# Token benchmark — A / B / C

| Item | Value |
|---|---|
| tokenizer requested | `o200k_base` |
| tokenizer actual | `tiktoken:o200k_base` |
| exact | true |
| python | 3.13.9 |
| tiktoken | 0.14.0 |
| tokenizers | 0.23.2 |
| deepseek tokenizer | present |

Variants: **A** original Chinese v2.0.3, **B** optimized Chinese v2.0.4, **C** optimized English v2.0.4.
`structure = 1 - B/A`, `language = 1 - C/B`, `total = 1 - C/A`.

## T1 · YAML description

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| description | 83 | 83 | 69 | +0.0% | +16.9% | +16.9% |

## T2 · SKILL.md

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| SKILL.md | 4571 | 4612 | 3851 | -0.9% | +16.5% | +15.8% |

## T3 · Reference files (each read alone)

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| protocol-v2 | 5528 | 5528 | 4881 | +0.0% | +11.7% | +11.7% |
| migration | 5016 | 5016 | 4418 | +0.0% | +11.9% | +11.9% |
| hooks | 2499 | 2499 | 2243 | +0.0% | +10.2% | +10.2% |
| benchmark | 5742 | 5742 | 5177 | +0.0% | +9.8% | +9.8% |

## T4 · Complete task reading paths

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| New project initialization | 4571 | 4612 | 3851 | -0.9% | +16.5% | +15.8% |
| Existing project diagnosis | 4571 | 4612 | 3851 | -0.9% | +16.5% | +15.8% |
| Legacy project migration | 9587 | 9628 | 8269 | -0.4% | +14.1% | +13.7% |
| New-session context recovery | 10099 | 10140 | 8732 | -0.4% | +13.9% | +13.5% |
| Safe document write | 10099 | 10140 | 8732 | -0.4% | +13.9% | +13.5% |
| Hook installation | 7070 | 7111 | 6094 | -0.6% | +14.3% | +13.8% |

## T5 · Project templates (each file alone)

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| AGENTS.md | 1316 | 1316 | 1212 | +0.0% | +7.9% | +7.9% |
| 00_baseline.md | 572 | 572 | 533 | +0.0% | +6.8% | +6.8% |
| 05_dashboard.md | 818 | 818 | 746 | +0.0% | +8.8% | +8.8% |
| fact_book.md | 303 | 303 | 266 | +0.0% | +12.2% | +12.2% |
| 06_index.md | 145 | 145 | 142 | +0.0% | +2.1% | +2.1% |
| 06_log.md | 156 | 156 | 148 | +0.0% | +5.1% | +5.1% |
| 06_shard.md | 170 | 170 | 155 | +0.0% | +8.8% | +8.8% |
| 90_archive.md | 153 | 153 | 138 | +0.0% | +9.8% | +9.8% |
| 启动消息.txt | 379 | 379 | 359 | +0.0% | +5.3% | +5.3% |
| gitignore.txt | 196 | 196 | 166 | +0.0% | +15.3% | +15.3% |
| gitattributes.txt | 9 | 9 | 9 | +0.0% | +0.0% | +0.0% |
| migration-prompt.txt | 941 | 941 | 818 | +0.0% | +13.1% | +13.1% |

## T4 detail — which files each task reads

- **New project initialization** (`new-project`): reads `skill` — A 4571 / B 4612 / C 3851 tokens, total +15.8%
- **Existing project diagnosis** (`diagnose`): reads `skill` — A 4571 / B 4612 / C 3851 tokens, total +15.8%
- **Legacy project migration** (`migrate`): reads `skill`, `ref:migration` — A 9587 / B 9628 / C 8269 tokens, total +13.7%
- **New-session context recovery** (`recovery`): reads `skill`, `ref:protocol-v2` — A 10099 / B 10140 / C 8732 tokens, total +13.5%
- **Safe document write** (`safe-write`): reads `skill`, `ref:protocol-v2` — A 10099 / B 10140 / C 8732 tokens, total +13.5%
- **Hook installation** (`hook-install`): reads `skill`, `ref:hooks` — A 7070 / B 7111 / C 6094 tokens, total +13.8%

## Limitations

- tiktoken encodings (`cl100k_base`, `o200k_base`) are reproducible proxies; they are not every model's billing tokenizer.
- `deepseek_v4` uses the official offline tokenizer (`tokenizers` + `tokenizer.json`); `deepseek_estimate` only applies the documented ratio (1 English char ≈ 0.3, 1 Chinese char ≈ 0.6) and is an estimate.
- The heuristic counter (CJK 1 char ≈ 1 token, other 4 chars ≈ 1 token) is reported as an estimate only and is never used for a conclusion.
- Structure is compared through section headings and protocol IDs, not through semantic equivalence of every sentence; see `test_token_language.py`.
- Task paths list the documents a task actually needs; references that are not required are not counted as default-loaded content.

# Token benchmark — A / B / C

| Item | Value |
|---|---|
| tokenizer requested | `deepseek_v4` |
| tokenizer actual | `tokenizers:deepseek_v4(C:\Users\jmwan\.cache\handoff-kb\deepseek_v4_tokenizer\tokenizer.json)` |
| exact | true |
| python | 3.13.9 |
| tiktoken | 0.14.0 |
| tokenizers | 0.23.2 |
| deepseek tokenizer | present |

Variants: **A** original Chinese v2.0.3, **B** optimized Chinese v2.0.4, **C** optimized English v2.0.4.
`structure = 1 - B/A`, `language = 1 - C/B`, `total = 1 - C/A`.

## T1 · YAML description

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| description | 63 | 63 | 71 | +0.0% | -12.7% | -12.7% |

## T2 · SKILL.md

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| SKILL.md | 4343 | 4338 | 3919 | +0.1% | +9.7% | +9.8% |

## T3 · Reference files (each read alone)

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| protocol-v2 | 5171 | 5171 | 4969 | +0.0% | +3.9% | +3.9% |
| migration | 4675 | 4675 | 4452 | +0.0% | +4.8% | +4.8% |
| hooks | 2377 | 2377 | 2300 | +0.0% | +3.2% | +3.2% |
| benchmark | 5424 | 5424 | 5193 | +0.0% | +4.3% | +4.3% |

## T4 · Complete task reading paths

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| New project initialization | 4343 | 4338 | 3919 | +0.1% | +9.7% | +9.8% |
| Existing project diagnosis | 4343 | 4338 | 3919 | +0.1% | +9.7% | +9.8% |
| Legacy project migration | 9018 | 9013 | 8371 | +0.1% | +7.1% | +7.2% |
| New-session context recovery | 9514 | 9509 | 8888 | +0.1% | +6.5% | +6.6% |
| Safe document write | 9514 | 9509 | 8888 | +0.1% | +6.5% | +6.6% |
| Hook installation | 6720 | 6715 | 6219 | +0.1% | +7.4% | +7.5% |

## T5 · Project templates (each file alone)

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| AGENTS.md | 1232 | 1232 | 1237 | +0.0% | -0.4% | -0.4% |
| 00_baseline.md | 539 | 539 | 525 | +0.0% | +2.6% | +2.6% |
| 05_dashboard.md | 784 | 784 | 760 | +0.0% | +3.1% | +3.1% |
| fact_book.md | 286 | 286 | 265 | +0.0% | +7.3% | +7.3% |
| 06_index.md | 137 | 137 | 142 | +0.0% | -3.6% | -3.6% |
| 06_log.md | 152 | 152 | 151 | +0.0% | +0.7% | +0.7% |
| 06_shard.md | 168 | 168 | 161 | +0.0% | +4.2% | +4.2% |
| 90_archive.md | 143 | 143 | 139 | +0.0% | +2.8% | +2.8% |
| 启动消息.txt | 370 | 370 | 371 | +0.0% | -0.3% | -0.3% |
| gitignore.txt | 184 | 184 | 175 | +0.0% | +4.9% | +4.9% |
| gitattributes.txt | 9 | 9 | 9 | +0.0% | +0.0% | +0.0% |
| migration-prompt.txt | 882 | 882 | 834 | +0.0% | +5.4% | +5.4% |

## T4 detail — which files each task reads

- **New project initialization** (`new-project`): reads `skill` — A 4343 / B 4338 / C 3919 tokens, total +9.8%
- **Existing project diagnosis** (`diagnose`): reads `skill` — A 4343 / B 4338 / C 3919 tokens, total +9.8%
- **Legacy project migration** (`migrate`): reads `skill`, `ref:migration` — A 9018 / B 9013 / C 8371 tokens, total +7.2%
- **New-session context recovery** (`recovery`): reads `skill`, `ref:protocol-v2` — A 9514 / B 9509 / C 8888 tokens, total +6.6%
- **Safe document write** (`safe-write`): reads `skill`, `ref:protocol-v2` — A 9514 / B 9509 / C 8888 tokens, total +6.6%
- **Hook installation** (`hook-install`): reads `skill`, `ref:hooks` — A 6720 / B 6715 / C 6219 tokens, total +7.5%

## Limitations

- tiktoken encodings (`cl100k_base`, `o200k_base`) are reproducible proxies; they are not every model's billing tokenizer.
- `deepseek_v4` uses the official offline tokenizer (`tokenizers` + `tokenizer.json`); `deepseek_estimate` only applies the documented ratio (1 English char ≈ 0.3, 1 Chinese char ≈ 0.6) and is an estimate.
- The heuristic counter (CJK 1 char ≈ 1 token, other 4 chars ≈ 1 token) is reported as an estimate only and is never used for a conclusion.
- Structure is compared through section headings and protocol IDs, not through semantic equivalence of every sentence; see `test_token_language.py`.
- Task paths list the documents a task actually needs; references that are not required are not counted as default-loaded content.

# Token benchmark — A / B / C

| Item | Value |
|---|---|
| tokenizer requested | `deepseek_estimate` |
| tokenizer actual | `deepseek_estimate（官方比例：1 英文字符≈0.3、1 中文字符≈0.6）` |
| exact | false (estimate) |
| python | 3.13.9 |
| tiktoken | 0.14.0 |
| tokenizers | 0.23.2 |
| deepseek tokenizer | present |

Variants: **A** original Chinese v2.0.3, **B** optimized Chinese v2.0.4, **C** optimized English v2.0.4.
`structure = 1 - B/A`, `language = 1 - C/B`, `total = 1 - C/A`.

## T1 · YAML description

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| description | 62 | 62 | 119 | +0.0% | -91.9% | -91.9% |

## T2 · SKILL.md

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| SKILL.md | 3261 | 3266 | 4525 | -0.2% | -38.5% | -38.8% |

## T3 · Reference files (each read alone)

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| protocol-v2 | 3830 | 3830 | 5522 | +0.0% | -44.2% | -44.2% |
| migration | 3386 | 3386 | 4925 | +0.0% | -45.5% | -45.5% |
| hooks | 1938 | 1938 | 2753 | +0.0% | -42.1% | -42.1% |
| benchmark | 3850 | 3850 | 5496 | +0.0% | -42.8% | -42.8% |

## T4 · Complete task reading paths

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| New project initialization | 3261 | 3266 | 4525 | -0.2% | -38.5% | -38.8% |
| Existing project diagnosis | 3261 | 3266 | 4525 | -0.2% | -38.5% | -38.8% |
| Legacy project migration | 6647 | 6652 | 9450 | -0.1% | -42.1% | -42.2% |
| New-session context recovery | 7091 | 7096 | 10047 | -0.1% | -41.6% | -41.7% |
| Safe document write | 7091 | 7096 | 10047 | -0.1% | -41.6% | -41.7% |
| Hook installation | 5199 | 5204 | 7278 | -0.1% | -39.9% | -40.0% |

## T5 · Project templates (each file alone)

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| AGENTS.md | 970 | 970 | 1407 | +0.0% | -45.1% | -45.1% |
| 00_baseline.md | 396 | 396 | 584 | +0.0% | -47.5% | -47.5% |
| 05_dashboard.md | 602 | 602 | 834 | +0.0% | -38.5% | -38.5% |
| fact_book.md | 200 | 200 | 288 | +0.0% | -44.0% | -44.0% |
| 06_index.md | 101 | 101 | 156 | +0.0% | -54.5% | -54.5% |
| 06_log.md | 113 | 113 | 170 | +0.0% | -50.4% | -50.4% |
| 06_shard.md | 120 | 120 | 174 | +0.0% | -45.0% | -45.0% |
| 90_archive.md | 110 | 110 | 155 | +0.0% | -40.9% | -40.9% |
| 启动消息.txt | 307 | 307 | 394 | +0.0% | -28.3% | -28.3% |
| gitignore.txt | 133 | 133 | 181 | +0.0% | -36.1% | -36.1% |
| gitattributes.txt | 6 | 6 | 6 | +0.0% | +0.0% | +0.0% |
| migration-prompt.txt | 639 | 639 | 1016 | +0.0% | -59.0% | -59.0% |

## T4 detail — which files each task reads

- **New project initialization** (`new-project`): reads `skill` — A 3261 / B 3266 / C 4525 tokens, total -38.8%
- **Existing project diagnosis** (`diagnose`): reads `skill` — A 3261 / B 3266 / C 4525 tokens, total -38.8%
- **Legacy project migration** (`migrate`): reads `skill`, `ref:migration` — A 6647 / B 6652 / C 9450 tokens, total -42.2%
- **New-session context recovery** (`recovery`): reads `skill`, `ref:protocol-v2` — A 7091 / B 7096 / C 10047 tokens, total -41.7%
- **Safe document write** (`safe-write`): reads `skill`, `ref:protocol-v2` — A 7091 / B 7096 / C 10047 tokens, total -41.7%
- **Hook installation** (`hook-install`): reads `skill`, `ref:hooks` — A 5199 / B 5204 / C 7278 tokens, total -40.0%

## Limitations

- tiktoken encodings (`cl100k_base`, `o200k_base`) are reproducible proxies; they are not every model's billing tokenizer.
- `deepseek_v4` uses the official offline tokenizer (`tokenizers` + `tokenizer.json`); `deepseek_estimate` only applies the documented ratio (1 English char ≈ 0.3, 1 Chinese char ≈ 0.6) and is an estimate.
- The heuristic counter (CJK 1 char ≈ 1 token, other 4 chars ≈ 1 token) is reported as an estimate only and is never used for a conclusion.
- Structure is compared through section headings and protocol IDs, not through semantic equivalence of every sentence; see `test_token_language.py`.
- Task paths list the documents a task actually needs; references that are not required are not counted as default-loaded content.

# Token benchmark — A / B / C

| Item | Value |
|---|---|
| tokenizer requested | `heuristic` |
| tokenizer actual | `heuristic（CJK 1 字≈1 token，其余 4 字符≈1 token）` |
| exact | false (estimate) |
| python | 3.13.9 |
| tiktoken | 0.14.0 |
| tokenizers | 0.23.2 |
| deepseek tokenizer | present |

Variants: **A** original Chinese v2.0.3, **B** optimized Chinese v2.0.4, **C** optimized English v2.0.4.
`structure = 1 - B/A`, `language = 1 - C/B`, `total = 1 - C/A`.

## T1 · YAML description

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| description | 99 | 99 | 99 | +0.0% | +0.0% | +0.0% |

## T2 · SKILL.md

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| SKILL.md | 3913 | 3980 | 3800 | -1.7% | +4.5% | +2.9% |

## T3 · Reference files (each read alone)

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| protocol-v2 | 4704 | 4704 | 4686 | +0.0% | +0.4% | +0.4% |
| migration | 4176 | 4176 | 4156 | +0.0% | +0.5% | +0.5% |
| hooks | 2324 | 2324 | 2298 | +0.0% | +1.1% | +1.1% |
| benchmark | 4709 | 4709 | 4632 | +0.0% | +1.6% | +1.6% |

## T4 · Complete task reading paths

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| New project initialization | 3913 | 3980 | 3800 | -1.7% | +4.5% | +2.9% |
| Existing project diagnosis | 3913 | 3980 | 3800 | -1.7% | +4.5% | +2.9% |
| Legacy project migration | 8089 | 8156 | 7956 | -0.8% | +2.5% | +1.6% |
| New-session context recovery | 8617 | 8684 | 8486 | -0.8% | +2.3% | +1.5% |
| Safe document write | 8617 | 8684 | 8486 | -0.8% | +2.3% | +1.5% |
| Hook installation | 6237 | 6304 | 6098 | -1.1% | +3.3% | +2.2% |

## T5 · Project templates (each file alone)

| Item | A | B | C | structure | language | total |
|---|---|---|---|---|---|---|
| AGENTS.md | 1175 | 1175 | 1188 | +0.0% | -1.1% | -1.1% |
| 00_baseline.md | 476 | 476 | 496 | +0.0% | -4.2% | -4.2% |
| 05_dashboard.md | 701 | 701 | 697 | +0.0% | +0.6% | +0.6% |
| fact_book.md | 228 | 228 | 241 | +0.0% | -5.7% | -5.7% |
| 06_index.md | 122 | 122 | 131 | +0.0% | -7.4% | -7.4% |
| 06_log.md | 140 | 140 | 144 | +0.0% | -2.9% | -2.9% |
| 06_shard.md | 140 | 140 | 145 | +0.0% | -3.6% | -3.6% |
| 90_archive.md | 135 | 135 | 130 | +0.0% | +3.7% | +3.7% |
| 启动消息.txt | 333 | 333 | 332 | +0.0% | +0.3% | +0.3% |
| gitignore.txt | 157 | 157 | 152 | +0.0% | +3.2% | +3.2% |
| gitattributes.txt | 5 | 5 | 5 | +0.0% | +0.0% | +0.0% |
| migration-prompt.txt | 818 | 818 | 848 | +0.0% | -3.7% | -3.7% |

## T4 detail — which files each task reads

- **New project initialization** (`new-project`): reads `skill` — A 3913 / B 3980 / C 3800 tokens, total +2.9%
- **Existing project diagnosis** (`diagnose`): reads `skill` — A 3913 / B 3980 / C 3800 tokens, total +2.9%
- **Legacy project migration** (`migrate`): reads `skill`, `ref:migration` — A 8089 / B 8156 / C 7956 tokens, total +1.6%
- **New-session context recovery** (`recovery`): reads `skill`, `ref:protocol-v2` — A 8617 / B 8684 / C 8486 tokens, total +1.5%
- **Safe document write** (`safe-write`): reads `skill`, `ref:protocol-v2` — A 8617 / B 8684 / C 8486 tokens, total +1.5%
- **Hook installation** (`hook-install`): reads `skill`, `ref:hooks` — A 6237 / B 6304 / C 6098 tokens, total +2.2%

## Limitations

- tiktoken encodings (`cl100k_base`, `o200k_base`) are reproducible proxies; they are not every model's billing tokenizer.
- `deepseek_v4` uses the official offline tokenizer (`tokenizers` + `tokenizer.json`); `deepseek_estimate` only applies the documented ratio (1 English char ≈ 0.3, 1 Chinese char ≈ 0.6) and is an estimate.
- The heuristic counter (CJK 1 char ≈ 1 token, other 4 chars ≈ 1 token) is reported as an estimate only and is never used for a conclusion.
- Structure is compared through section headings and protocol IDs, not through semantic equivalence of every sentence; see `test_token_language.py`.
- Task paths list the documents a task actually needs; references that are not required are not counted as default-loaded content.
