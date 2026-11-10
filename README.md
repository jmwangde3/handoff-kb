# handoff-kb 2.0

**给多会话并行项目的分层交接库。** 一套 Markdown 协议 + 十个零依赖 Python 脚本：让「上下文快满、几条线同时推、文档越堆越多」的项目，新会话接手时只读固定的一小份，而不是全库重读。

2.0 的重点不是加脚本，而是把四件事做实：**按预算取上下文、带证据的交接、带哈希校验的写入、能跑起来的测试**。仍然是纯文本、可 diff、无服务、无 embedding、无 SQLite。

```
接手 → kb-context（预算内最小上下文）→ 干活 → kb-write（哈希校验写回）→ kb-handoff（交接自检）
```

---

## 1. 它解决什么（算术问题，不是文风问题）

中文 UTF-8 约 4.5 字节 / token。全读一遍的代价随文档总量线性增长，而**真正决定接手质量的信息**（现在在干嘛、下一手、别做什么）通常不到 20 KB。

答案不是「把文档写薄」，而是**把「存」和「读」解耦**：总量可以涨，单次必读集合恒定。

两个口径的数字，别混：

| 场景 | 结果 | 口径 |
|---|---|---|
| 真实路由器项目（v1 时代） | 全库 1,759 行 / 221 KB → 接手 20.6 KB（`05`+`00`），降 90% | 实际文件体积，非估算 |
| 本仓库合成夹具（v2 benchmark） | A 全量 3,056 / B `00+05` 389 / C 路由 89 tokens，质量 10/10 | `heuristic` **估算**，夹具 ~11 KB |

第二行可用两条命令复现（`py tests/make_fixture.py ../kbdemo` → `py scripts/kb-benchmark.py --target ../kbdemo`），只说明「路由确实能压到比 00+05 更小」，**不代表真实项目或 API 账单**；口径与逐任务明细见 `references/benchmark.md`。

---

## 2. 适用与不适用

| 你的情况 | 怎么办 |
|---|---|
| 单会话、任务做完传给下一个会话、只要一份交接说明 | **别用**，写 6 行 handoff |
| 文档 < 3 份、没有并行会话、一次性任务 | **别用** |
| 多条线 + 多会话并行 + 上下文容易满 + 长期维护 | 用，`kb-init.py` |
| 老项目已有一堆文档（`00/05/06/90` 或自有命名） | 用，`kb-check.py --loose` 诊断 → `kb-migrate.py` 增量迁移 |

```text
接手 [任务]，工作目录 [DIR]。
已完成：[1–2 行]
进行中 / 卡点：[1 行]
下一手：[1 行]
相关文件 / 提交：[路径 或 git log -3]
别重复踩：[1 行，没有就删]
```

---

## 3. 分层模型

| 层 | 文件 | 放什么 | 改动频率 | 接手必读 |
|---|---|---|---|---|
| L0 入口 | `AGENTS.md`（+ `CLAUDE.md` / `GEMINI.md` 指针） | 读哪份、怎么写。**绝不写当前值** | 极少 | 读 |
| L1 事实 | `00` 共享页（`K-xx` + 状态 + 证据）+ `10–17` 按线分册 | 当前值 / 判据 / 命令 / 坑 | 少 | 按线读 |
| L2 现状 | `05_进度仪表盘.md`（`kb:id` 章节） | 现状 / 下一手 / 各线状态 / 待办 / 硬约束 | 常改 | **必读** |
| L3 流水 | `06_会话日志.md`（历史卷只读）+ `06_流水/<线>.md` | append-only 时间线 | 按线只写自己那份 | 追溯才读 |
| L4 归档 | `90_过程档案.md` + `归档/` | 过程证据 / 验证快照 / 版本考古 | 折叠时才写 | 非必读 |

**编号契约**：`00/05/06/90` 是保留层；新建事实分册用 **10–17**（最多 8 条线）；旧库的 `01–04` 继续合法，**迁移不重命名**。`K-xx` / `G-xxx` 与章节 `kb:id` 作废后保留、永不复用。

**一写者一文件**：`06_流水/<线>.md` 从根上消除共享单文件的读-改-写覆盖；冲突信号靠 `git status` + `kb-write.py` 的哈希校验。

---

## 4. 一键初始化

**依赖**：Python 3.10+，只用标准库。`tiktoken` 是唯一的可选依赖，只用于「精确 token 计数」，不装也能跑（自动降级为启发式估算并在输出里标注）；`tests/deps_check.py` 会在 CI 里守住这条。

```bash
KB="$HOME/.skills-manager/skills/handoff-kb"   # 换成你的安装目录
py "$KB/scripts/kb-init.py" \
    --target "~/projects/新项目" --project "新项目" \
    --lines "固件,运行态,服务端,测速"
```

生成 `AGENTS.md` / `CLAUDE.md` / `GEMINI.md`、`00_基线.md`、`10..17_<线>.md`、`05_进度仪表盘.md`（带 `kb:id`）、`06_会话日志.md` + `06_流水/*.md`、`90_过程档案.md`、启动消息、`.gitignore` / `.gitattributes`、自检脚本占位、`归档/`。

安全边界（不是可选建议）：

- `--plan` 只打印创建/跳过/覆盖清单，**不落盘**。
- 只有「目标与父目录都没有 git 仓库」时才自动 `git init` + 首次 commit；已有仓库**不嵌套、不自动提交**。
- 只 `git add -- <本次生成的白名单>`，**从不** `git add -A`；暂存区出现白名单外文件就 `git reset` 并失败。
- 敏感信息命中 → 拒绝提交、返回非 0；`--force` **不绕过**凭证检查。
- `.gitignore` / `.gitattributes` / `AGENTS.md` 属于受保护配置，覆盖要 `--force --overwrite-config`。
- 线名重复（大小写 / Unicode 折叠后）、保留名（`其他`）、`NN_` 前缀、超过 8 条线 → 直接拒绝。

```
--no-git  只生成文件          --force  覆盖模板（不含受保护配置）
--shards auto|none           auto=按线分片（默认）；none=单份 06
--json    机器可读
```

---

## 5. 旧库迁移（v1 → v2，无损）

```bash
py "$KB/scripts/kb-check.py"   --target ./old --loose      # 先只读诊断
py "$KB/scripts/kb-migrate.py" --target ./old --plan       # 计划写 .kb-migrate-plan.json
py "$KB/scripts/kb-migrate.py" --target ./old --apply      # 校验源哈希后再写
```

只做**增量**：补 `<!-- kb:schema: 2 -->`、给已知章节补 `kb:id`。不重命名 `01–04`、不重排章节、不改正文、不删证据。计划绑定源文件哈希——文件被别的会话改过就拒绝，重跑 `--plan` 即可。重复迁移幂等。

---

## 6. 新会话恢复：按预算取上下文

```bash
py "$KB/scripts/kb-context.py" --target . --task "排查 NSS 网络问题" --budget 3000 --explain
```

装配顺序（高 → 低）：

```
P0 硬约束（dashboard.constraints / AGENTS 硬约束段）   ← 任何预算都不裁
P1 现状 + 下一手（dashboard.current / dashboard.next）
P2 本线事实（fact.current / fact.commands / fact.pitfalls）
P3 基线命中行 + 证据指针 + 交叉链（改 A 波及 B）
P4 其余按相关度补充（≤ 预算 30%、≤3 块，流水/归档降权）
```

- 默认预算 3000；`--format json` 给 CI / Hook 用，`--explain` 说明每块为什么被选。
- 预算不足时**必读块仍然保留**，并输出「超额」与 `skipped` 清单——不会静默丢掉硬约束。
- 没有任何命中 → 输出缺口清单，让你去 `kb-search`，**不虚构上下文**。
- Token 默认 `heuristic` 估算（CJK 1 字≈1 token，其余 4 字符≈1 token）；装了 `tiktoken` 且指定 `--tokenizer cl100k_base` 才用真实编码，输出里会标明用的是哪个。

---

## 7. 检索与按节精读

```bash
py "$KB/scripts/kb-search.py"  --target . --query "NSS 网络问题" --limit 5
py "$KB/scripts/kb-outline.py" --file 05_进度仪表盘.md --section-id dashboard.next
py "$KB/scripts/kb-outline.py" --file 05_进度仪表盘.md --find 磁盘
```

- 检索直接扫 Markdown（无索引服务）：中文按「整段 + 二元组」近似，英文不分大小写；打分顺序 = 精确 ID / 事实 ID 行 > 文件名 / 工作线 > 标题 > 正文；流水降权，归档与已作废行默认排除。
- 只回定位（文件 / 章节 ID / 行号 / 160 字摘要 / 分数 / 哈希 / 估算 token），正文用 `kb-outline.py` 按节读。
- `--hash` 传了就校验：文档变了就拒绝读（退出码 2），防止按过期目录取到错节。

---

## 8. 安全写回（哈希 + 锁 + 事务）

```bash
py "$KB/scripts/kb-write.py" read  --target . --file 05_进度仪表盘.md --json
py "$KB/scripts/kb-write.py" apply --target . --changes changes.json --dry-run
py "$KB/scripts/kb-write.py" apply --target . --changes changes.json
py "$KB/scripts/kb-write.py" recover --target . [--dry-run|--apply] [--break-lock]
```

`changes.json`（协议固定 `schema_version: 1`）：

```json
{
  "schema_version": 1,
  "updates": [
    {"path": "05_进度仪表盘.md", "expected_sha256": "<64 位>",
     "operation": "replace_section", "section_id": "dashboard.current",
     "content": "<新章节正文>"},
    {"path": "06_流水/固件.md", "expected_sha256": "<64 位>",
     "operation": "append", "content": "- [2026-11-11 01:00] 固件 ... → 下一手"},
    {"path": "00_基线.md", "expected_sha256": "<64 位>",
     "operation": "update_fact", "fact_id": "K-02",
     "content": "| K-02 | 信道 | 157 | 有效 | `iwinfo` | 2026-11-11 |"}
  ]
}
```

- 写入必须带**全量 64 位** `expected_sha256`，不符即 `CONFLICT`，不覆盖、报最新哈希、提示重新读。
- 跨平台目录锁（原子 mkdir + 进程存活判断）：活进程锁不抢占；死进程锁可回收并在 stderr 说明；显式解锁 `recover --break-lock`。
- 多文件：**先全部校验 → 备份 → 逐个 `os.replace` → 失败回滚**；有 journal，崩溃后 `recover` 逐文件判定「已写入 / 未写入 / 被他人改动」，有冲突就拒绝自动恢复。
- 单文件写入用同目录临时文件 + `os.replace`，并沿用原文件的换行风格（避免整文件 CRLF 噪声）。
- 路径限制：只接受工作区内相对路径，拒绝绝对路径 / `..` / 符号链接越界 / 非 `.md`·`.txt`。

**诚实声明**：多个 `os.replace()` 不是跨文件原子事务。这里提供的是「全量预检 + 备份 + 失败回滚 + 崩溃后恢复」，Git 仍是最终审计与回滚手段。

---

## 9. 交接检查（证据优先）

```bash
py "$KB/scripts/kb-handoff.py" check  --target . --strict
py "$KB/scripts/kb-handoff.py" report --target . --json
```

逐项判定 8 个问题：当前任务 / 确实完成了什么 / 证据 / 未核实项 / 阻塞 / 下一步 / 受影响文件 / 禁止重复的操作。

- 模板占位（`[填` / `TODO`）算**待核**，不算完成。
- 基线里「有效」却没有证据的条目 → 待核；不会自动升级成已验证。
- `--strict` 下有待核项即失败（退出码 1），适合放进收尾流程。

---

## 10. 体检

```bash
py "$KB/scripts/kb-check.py" --target .                  # 人读
py "$KB/scripts/kb-check.py" --target . --strict         # WARN 也算失败
py "$KB/scripts/kb-check.py" --target . --loose          # 自有命名体系
py "$KB/scripts/kb-check.py" --target . --json           # CI / Hook
py "$KB/scripts/kb-check.py" --target . --mode template  # 刚初始化的空模板
```

检查：必需文件（精确命名优先，不用 `05_*.md` 通配）、各层体积与接手成本、阈值命中、`K-xx` 重复定义 / 未定义引用 / 作废引用 / 循环作废链、`kb:id` 重复与非法格式、事实证据与核实时效、表格列数、残留 TODO、明文凭证、git 未提交改动。ERROR > 0 退出码 1。

体积统计跳过 `AI_files/` / `assets/` / `data/` / `output/` / `evidence/` / `node_modules/` / `build/` 等资料目录与 >2 MB 文本。

---

## 11. Hook（默认不安装）

```bash
py "$KB/scripts/kb-hooks.py" install   --client claude --target . --plan
py "$KB/scripts/kb-hooks.py" install   --client claude --target . --write
py "$KB/scripts/kb-hooks.py" uninstall --client claude --target . --write
```

- 只写**项目级**配置（`.claude/settings.json`、`.codex/hooks.json` + TOML 片段），不动全局。
- 事件语义：`SessionStart` 注入小预算上下文；`PreCompact` 提醒收尾；`PostCompact` 给指针；`Stop` 做交接检查（只提醒、不阻断）；`SessionEnd` 只读体检。
- `run` **永远退出 0**：Hook 自己出错也不能破坏会话。不联网、不自动提交、不重写事实文档。
- 事件名与退出码语义以各客户端当前官方文档为准（见 `references/hooks.md`），`--plan` 先看清楚再 `--write`。

---

## 12. 测试与 benchmark

```bash
python -m unittest discover -s tests -v     # 80 个用例
python tests/smoke.py                       # 端到端：init→check→search→context→handoff→write→migrate
python tests/deps_check.py                  # scripts/ 不得引入标准库以外的依赖
python scripts/kb-benchmark.py --target . --report markdown
```

- 测试覆盖：编号冲突、路径穿越、符号链接越界、并发锁、事务回滚、恢复、哈希冲突、ID 引用、围栏解析、预算超额、Hook 卸载幂等、迁移幂等与计划过期。
- CI：`.github/workflows/test.yml`，Ubuntu + Windows × Python 3.10 / 3.12 / 3.13，无网络、无凭证、库依赖只有标准库（可选 `tiktoken` 由 `deps_check.py` 显式放行并限制在函数内）。
- benchmark 对比 A 全量 / B `00+05` / C 路由，10 个固定任务；输出 Markdown 与 JSON，并显式标注 tokenizer 与估算口径。

---

## 13. 协议兼容

| 项目 | v1 | v2 |
|---|---|---|
| 保留层 | `00/05/06/90` | 不变 |
| 事实分册 | `01–08`（与 05/06 冲突） | 新建 `10–17`；旧 `01–04` 继续合法 |
| 章节定位 | 标题文字 / `--section N` | 新增 `<!-- kb:id: ... -->`，旧接口保留 |
| 交接 | 人工看 `05` | `kb-handoff.py` 逐项判定（缺证据=待核） |
| 写入 | 人肉追加 | `kb-write.py`（哈希 + 锁 + 事务） |
| 上下文 | 全读或 00+05 | `kb-context.py` 按预算路由 |
| 哈希 | 12 位文本短哈希 | 写入用全量 64 位，短哈希保留为兼容读取 |

旧命令全部可用：`kb-init` / `kb-check` / `kb-outline` 的参数没有删除，只新增。

---

## 14. 风险、限制与恢复

- **不做**：向量库 / SQLite 索引 / embedding / MCP 常驻 / 多项目中心 / 知识图谱 / 云同步 / 自动 LLM 总结。
- 规模上限靠机制（git + 阈值）守，不靠纪律；超过约 8 条线或 `00` 超 150 行该合并或升级，而不是继续加文档。
- 普通编辑器直接改文件会绕过锁，所以**哈希重校验必须保留**；`kb-write` 会拒绝过期哈希。
- Hook 依赖客户端事件语义，客户端升级可能改变行为；`run` 出错只打印、不阻断。
- 崩溃恢复：`kb-write.py recover --dry-run` 先看，再 `--apply`；有他人改动时只报告不覆盖。
- 凭证：扫描是正则启发式，命中即阻断；但**没命中不等于安全**，`.gitignore` 仍要在第一次 `git add` 之前写好。

---

## 15. 文件

```text
SKILL.md                    技能主体（判定 / 建库 / 迁移 / 接手 / 写回 / 体检 / Hooks）
references/protocol-v2.md   2.0 协议：编号、章节 ID、changes.json、并发与恢复
references/protocol.md      v1 设计原理（历史，仍可读）
references/migration.md     存量改造手册（含 v1 → v2）
references/hooks.md         Codex / Claude Code Hook 语义与安装
references/benchmark.md     评测口径、任务集、如何解读
assets/                     模板（AGENTS / 00 / 05 / 10–17 / 06 / 90 / 启动消息 / git 配置）
scripts/kb-init.py          脚手架 + 预检查 + 白名单提交 + 凭证阻断
scripts/kb-check.py         只读体检（--loose / --json / --mode）
scripts/kb-outline.py       目录树 + 稳定章节 ID + 按节读 + hash 校验
scripts/kb-write.py         安全写入（哈希 / 锁 / 事务 / recover）
scripts/kb-migrate.py       v1 → v2 无损迁移（计划绑定哈希）
scripts/kb-search.py        轻量全文检索（章节级打分）
scripts/kb-context.py       预算内上下文路由（--explain）
scripts/kb-handoff.py       交接有效性检查（证据优先）
scripts/kb-hooks.py         客户端 Hook 适配（默认不安装）
scripts/kb-benchmark.py     Token 与质量评测
scripts/lib/                共享库：protocol / scope / markdown / safeio / security / tokens / terms
tests/                      80 个 unittest + 端到端 smoke + 依赖检查 + 夹具生成器
tests/make_fixture.py       生成 benchmark 用的合成夹具（README §1 的数字可复现）
tests/deps_check.py         非标准库导入检查（只允许可选的 tiktoken）
.github/workflows/test.yml  Ubuntu + Windows × 3 个 Python 版本
```

## License

MIT，见 `LICENSE`。
