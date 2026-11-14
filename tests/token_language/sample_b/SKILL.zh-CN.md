---
name: handoff-kb
description: 为多会话并行、长期维护的项目建立分层知识库，支持上下文预算路由、安全写入、交接检查和旧库迁移。适用于上下文压缩、知识库整理、多工作线协作、长期项目交接和存量文档改造。不适用于单会话、一次性任务或只需简单 handoff 的场景。
---

# 分层交接库（handoff-kb 2.0.4）

> **工具版本** `2.0.4`（脚本行为）｜**协议版本** `2`（文档布局，`<!-- kb:schema: 2 -->`）。
> 两者独立：换工具版本不改协议，也不要求现有库迁移。

本文件的英文版：`SKILL.md`。中文参考手册：`references/*.zh-CN.md`。

## 1. 用途与适用边界

**先判断。不匹配就立刻停**——不跑脚本、不建文件、不读后续章节，直接用下面的六行 handoff。

| 你的情况 | 怎么办 |
|---|---|
| 单会话、任务做完传给下一个会话、只要一份交接说明 | **别用本 skill** → 简单 handoff |
| 文档 < 3 份、没有并行会话、一次性任务 | **别用本 skill** → 简单 handoff |
| 想给当前会话留个「继续提示词」 | **别用本 skill** → 简单 handoff |
| 多条线 + 多会话并行 + 上下文容易满 + 需要长期维护 | 用本 skill，从 §3 开始 |
| 老项目已有一堆文档要整理成库 | 用本 skill：§3 诊断 + `references/migration.md` |

简单 handoff 模板（贴进新会话即可，不落盘、不建库、不 git）：

```text
接手 [任务]，工作目录 [DIR]。
已完成：[1–2 行]
进行中 / 卡点：[1 行]
下一手：[1 行]
相关文件 / 提交：[路径 或 git log -3]
别重复踩：[1 行，没有就删]
```

项目侧兜底：某个项目确定不用这套库，在它自己的 `AGENTS.md` 第一行写「本项目用简单 handoff，不加载 handoff-kb」，agent 优先听项目规则。

## 2. 分层模型与核心规则

| 层 | 文件 | 放什么 | 接手必读 |
|---|---|---|---|
| L0 入口 | `AGENTS.md`（+ `CLAUDE.md`/`GEMINI.md` 指针） | 读哪份、怎么写。**不写当前值** | 读 |
| L1 事实 | `00`（`K-xx` + 状态 + 证据）+ `10–17` 按线分册 | 当前值 / 判据 / 命令 / 坑 | 按线读 |
| L2 现状 | `05_进度仪表盘.md`（`kb:id` 章节） | 现状 / 下一手 / 各线状态 / 待办 / 硬约束 | **必读** |
| L3 流水 | `06_会话日志.md`（历史卷只读）+ `06_流水/<线>.md` | append-only 时间线 | 追溯才读 |
| L4 归档 | `90_过程档案.md` + `归档/` | 过程证据 / 验证快照 | 非必读 |

2.0 相对 v1 的实质变化：

1. **编号不再冲突**：事实分册 `10–17`（旧库 `01–04` 仍合法），`00/05/06/90` 固定不动。
2. **章节可被稳定引用**：`<!-- kb:id: dashboard.current -->`，与标题文字、行号解耦。
3. **写回有并发保护**：全量 `sha256` + 文件锁 + 事务日志，`CONFLICT` 不覆盖。
4. **上下文按预算取**：`kb-context.py` 分 P0–P4 装配，硬约束永不裁。
5. **交接带证据**：`kb-handoff.py` 把「没证据的完成」判为待核。
6. **旧库能迁移**：`kb-migrate.py` 只补 schema 注释与章节 ID，不改正文。

不可让步的规则：

- **P0 硬约束永不静默丢弃**。预算装不下就保留并报超额，不许裁掉换低 token 数。
- P1（现状 + 下一手）必留；P2（本线事实）可跳，但跳过必须列出来。
- P3 必须给明确事实 ID 与证据；P4 是有上限、按相关度补的。
- **缺口与省略必须如实报告**，不把「没装」说成「没有」。
- 兼容现有 v2 项目：不改名、不重排编号、不改正文。

## 3. 快速开始与恢复

安装与定位：

```bash
KB="$HOME/.skills-manager/skills/handoff-kb"   # Windows: C:/Users/<你>/.skills-manager/skills/handoff-kb
ls "$KB/scripts"                               # 先确认路径再往下跑
```

客户端目录里的 `skills/handoff-kb` 通常是软链（`~/.workbuddy`、`~/.codex`、项目内 `.claude/skills`），真实目录只有一份。所有脚本只读写 `--target` 指定的根目录内部；路径逃出根、`..`、绝对路径、符号链接越界都会被拒绝。

新建项目：

```bash
py "$KB/scripts/kb-init.py" --target "~/projects/新项目" --project "新项目" \
    --lines "固件,运行态,服务端,测速"
py "$KB/scripts/kb-init.py" --target "~/projects/新项目" --plan      # 只看计划
py "$KB/scripts/kb-init.py" --target "~/projects/新项目" --lines "a,b" --lang en   # 英文模板
```

生成：`AGENTS.md`、`CLAUDE.md`/`GEMINI.md`、`00_基线.md`、`10–17_<线>.md`、`05_进度仪表盘.md`、`06_会话日志.md` + `06_流水/*.md`、`90_过程档案.md`、`新会话启动消息.txt`、`.gitignore`/`.gitattributes`、`scripts/handoff-check.sh` 占位、`归档/`。

生成后必做三件事：填 `00` 的 `K-xx`（值 / 状态 / 证据）与 `05` 的现状、下一手、硬约束；按项目补 `.gitignore`（大文件、凭证先排），把 `handoff-check.sh` 换成真实只读核对；跑 `py "$KB/scripts/kb-handoff.py" check --target . --strict` 看还缺什么。

安全边界：`--plan` 不落盘；已有 git 仓库不嵌套、不自动提交；只 `git add --` 白名单；凭证命中即拒绝提交（`--force` 不绕过）；受保护配置要 `--force --overwrite-config`。

存量项目（先诊断，再迁移）：

```bash
py "$KB/scripts/kb-check.py"   --target ./old --loose      # 只读诊断（不要求改名）
py "$KB/scripts/kb-migrate.py" --target ./old --plan       # 计划绑定源哈希
py "$KB/scripts/kb-migrate.py" --target ./old --apply      # 哈希不符就拒绝
```

`kb-migrate.py` 只补 `<!-- kb:schema: 2 -->` 与已知章节的 `kb:id`：不重命名 `01–04`、不重排章节、不改正文、不删证据；重复执行幂等。有未提交改动时默认拒绝（确认无并发会话才 `--force`）。结构改造（过程下沉 `90`、建 `05`、拆 `06`）仍按 `references/migration.md` 的五步 SOP，别跳步、别提前拆。

恢复入口：`kb-write.py recover --inspect` 看现场，`--apply` 回滚，确认对端进程已死才 `recover --break-lock`。迁移回滚是 `git checkout -- 00_*.md 05_*.md`（迁移只碰这两份）。

## 4. 上下文路由

```bash
py "$KB/scripts/kb-context.py" --target . --task "<本次任务>" --budget 3000 --explain
py "$KB/scripts/kb-context.py" --target . --loose --task "<本次任务>"   # 自有命名项目
git status && git log --oneline -5
py "$KB/scripts/kb-search.py"  --target . --query "<关键词>" --limit 5
py "$KB/scripts/kb-outline.py" --file 05_进度仪表盘.md --section-id dashboard.next
```

装配顺序：**P0** 硬约束 → **P1** 现状 + 下一手 → **P2** 本线事实 → **P3** 基线命中 + 证据 + 交叉链 → **P4** 相关度补满（≤3 块、≤30% 预算，且命中 ≥2 个关键词或 1 个 ≥4 字符的独特词；任务点名的事实所在文件不参与 P4；已作废事实按行置空，整节相关性都来自作废内容时整节跳过；问「以前 / 历史」或加 `--include-superseded` 才原样带回，并标注「已作废」与替代 ID）。

- 报「超额」时**不要删硬约束**：拆任务或提高 `--budget`，并把超额项写进输出让用户知情。
- 没有命中就报缺口，去 `kb-search`，别编。
- **P4 只补节，不等于整线加载**：缺口里出现「P4 只补入 N 个事实节」时，说明这条工作线只按关键词取了几节；要整线取用 `--line <线名>`。JSON 的 `p4_facts` 是真事实分册的节，`p4_candidates` 是「编号像分册、里面没事实条目」的普通文档（权重 0.5，当线索读）。
- P0 走三级兜底：`dashboard.constraints` → `dashboard.safety` → `AGENTS.md`「硬约束」段；越界的软链入口、只写占位符的段落都不算已声明。`kb-check` 与 `kb-context` 同一判据。
- `.workbuddy` / `.shared` / `.claude` 等客户端状态目录不算正文，检索与装配都跳过。
- token 默认 `heuristic` 估算；用 `--tokenizer cl100k_base` 且装了 tiktoken 才是真实计数；缺编码器直接非零退出，除非显式 `--allow-tokenizer-fallback`。

## 5. 安全写入规则

禁止整文件覆盖。

1. `py "$KB/scripts/kb-write.py" read --target . --file 05_进度仪表盘.md --json` → 拿 `sha256` 与章节 ID。
2. 组装 `changes.json`（`replace_section` / `append` / `update_fact`，每条带 64 位 `expected_sha256`）。
3. `--dry-run` 看差异 → `apply` 落盘。
4. `CONFLICT` = 别人改过：重新 `read`、合并、重写，**不重试覆盖**。
5. `LockHeld` = 另一个会话在写：等；确认对端进程已死才 `recover --break-lock`。

分流规则：状态/待办/下一手写 `05`；超 3 行的细节整条写 `06_流水/<线>.md`；长期事实进 `00` 或 `10–17`（带证据）；过程与验证快照进 `90`。**不改别人的行**。

保证与边界：

- 写入必须带当前 `sha256`；哈希过期即 `CONFLICT`，不自动合并。
- 锁冲突不得静默绕过；只有同机的死进程在重验 `owner_token` 后才可回收。
- **多文件写入不是数据库级原子事务**。协议给的是「全量预检 + 字节级备份 + 失败回滚 + 崩溃后检测」，git 仍是最终审计与回滚手段。
- 凭证不得入库。提交前跑明文扫描，`--force` 也不绕过。

## 6. 交接检查与阈值

```bash
py "$KB/scripts/kb-handoff.py" check --target . --strict
py "$KB/scripts/kb-handoff.py" check --target . --loose   # 无 kb:id 时按标题兜底
py "$KB/scripts/kb-check.py" --target . --loose
py "$KB/scripts/kb-check.py" --target . --strict
```

八个问题逐项判定：任务 / 已完成 / 证据 / 待核 / 阻塞 / 下一步 / 受影响文件 / 禁止重复的操作。占位符（`[填`、`TODO`）与「有效但无证据」都算待核，`--strict` 直接失败。

`kb-check` 检查：必需文件（精确命名）、各层体积与接手成本（正文与归档分开算）、阈值、`K-xx` 重复/未定义/作废/循环引用、`kb:id` 重复与非法、事实证据与时效、表格列数、残留 TODO、明文凭证、git 状态。

阈值表（写进 `05`，触线才动手）：

| 对象 | 阈值 | 动作 |
|---|---|---|
| `05` 现状 | > 4 行 | 压缩，细节进流水 |
| `05` 最近记录 | > 5 条 / 单条 > 3 行 | 整条移进 `06_流水/<线>.md` |
| `06` 单分片 | > 200 行 或 > 60 KB | 折叠进 `90`，只留标题 + 指针 |
| `00` 基线 | > 150 行 或 `K-xx` > 30 条 | 升级成结论索引 |
| `90` 归档 | > 600 行 | 再分卷或移 `归档/` |
| 事实分册 | > 8 个 | 按领域合并 |

验收只看 `05` 一份：各条线现在什么状态、下一手做什么、哪些待定/进行中/已完成且证据是什么、动某个具体配置该读哪几份。答不出 = `05` 缺信息或又膨胀了，别去全读全库补。

## 7. 参考手册加载指引

**参考手册不是默认读物的**。只在当前任务需要时加载一份：

| 任务 | 读哪份 |
|---|---|
| 协议标识、章节 ID、`changes.json`、锁与事务、退出码 | `references/protocol-v2.zh-CN.md` |
| 存量库改造、v1 → v2 升级 | `references/migration.zh-CN.md` |
| 安装或排查客户端 Hook | `references/hooks.zh-CN.md` |
| 判读 token 与质量数字 | `references/benchmark.zh-CN.md` |
| v1 设计原理（历史存档） | `references/protocol.md` |

英文版把 `.zh-CN.md` 换成 `.md`。中英文手册携带相同的协议 ID、命令、JSON 结构与退出码；按项目语言选一套，别在一次回答里混用。

## 8. 反模式与安全

| 坑 | 后果 |
|---|---|
| 长话术多份同源 | 改一处漏两处，口径漂移 |
| 参考手册列进「接手必读」 | 每个新会话白烧几十 k token |
| `05` 堆已完成的待办 | 待办区被历史稀释 |
| 删过程时连坑一起删 | 下次重走旧路 |
| 明文凭证直接 `git init` | 永久进历史，删不掉 |
| 大视频没排除就 `add` | 仓库几十 MB，历史不可清 |
| `git add -A` | 把别的会话的半成品一起提交 |
| 整文件覆盖写 `05` | 抹掉别人刚追加的行 |
| 重排 §编号 / 复用 `K-xx` | 全库引用失效 |
| 没证据就写「已修复」 | 交接不可验证，等于没交 |
| 默认装 Hook | 会话凭空多一层依赖 |

任何重构都必须保住的底线：P0 不丢、写入要哈希、锁冲突不绕过、原子性不夸大、迁移不改源内容、Hook 不阻断会话且永远退出 0、凭证不入库、现有 v2 项目继续可用。

## 9. 文件索引

| 路径 | 用途 |
|---|---|
| `scripts/kb-init.py` | 脚手架（`10–17` 编号，`--lang zh\|en`）+ 预检查 + 白名单提交 + 凭证阻断 |
| `scripts/kb-check.py` | 只读体检（`--loose` / `--strict` / `--json` / `--mode`） |
| `scripts/kb-outline.py` | 目录树 + `--section-id` + 按节读 + `--hash` 校验 |
| `scripts/kb-write.py` | 安全写入（哈希 / 锁 / 事务 / `recover`） |
| `scripts/kb-migrate.py` | v1 → v2 无损迁移（计划绑定哈希） |
| `scripts/kb-search.py` | 轻量全文检索（章节级打分） |
| `scripts/kb-context.py` | 预算内上下文路由（`--explain`） |
| `scripts/kb-handoff.py` | 交接有效性检查（证据优先） |
| `scripts/kb-hooks.py` | 客户端 Hook 适配（默认不安装） |
| `scripts/kb-benchmark.py` | Token 与质量评测 |
| `scripts/lib/` | 共享库：protocol / scope / markdown / safeio / security / tokens / terms / facts |
| `references/protocol-v2.zh-CN.md` | 2.0 协议（编号 / 章节 ID / changes.json / 并发恢复） |
| `references/protocol.md` | v1 设计原理（历史） |
| `references/migration.zh-CN.md` | 存量改造手册（含 v1 → v2） |
| `references/hooks.zh-CN.md` | Hook 语义与安装 |
| `references/benchmark.zh-CN.md` | 评测口径 |
| `assets/` | 中文骨架模板 |
| `assets/en/` | 英文骨架模板（占位符与 ID 与中文一致） |
| `tests/` | unittest + smoke + 依赖检查 |
| `tests/token_language/` | 中英文 token 评测与语义对等测试 |
| `tests/fixtures/ffrs/` | 脱敏「自有命名」项目夹具（`--loose` 用，内容全部虚构） |
