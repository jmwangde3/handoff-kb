---
name: handoff-kb
description: 给「多会话并行 / 上下文容易满 / 需要长期维护」的项目搭分层交接库（00 基线 + 10–17 事实分册 + 05 现状 + 06 流水 + 90 归档 + AGENTS 入口 + git 机制），并提供按 Token 预算的上下文路由、带哈希校验的安全写入、证据驱动的交接检查、v1→v2 无损迁移、客户端 Hook 与评测。触发词：上下文满了、文档臃肿、多会话同步、进度仪表盘、按线分片、结论索引、别再建第 N 份文档、老项目改造、存量迁移、文档库分层、知识库改造、handoff 库、token 预算、safe write。**不适用**：单会话一次性交接、只要一份 handoff / 继续提示词、临时任务收尾、文档少于 3 份且只有一个会话——这类直接写一份 6 行 handoff 即可，不必展开本 skill、不要建库。
---

# 分层交接库（handoff-kb 2.0.1-hotfix）

> **工具版本** `2.0.1-hotfix`（脚本行为）｜**协议版本** `2`（文档布局，`<!-- kb:schema: 2 -->`）。
> 两者独立：换工具版本不改协议，也不要求现有库迁移。

## 适用边界（加载后先读这段）

**判定不匹配就立刻停**：不跑任何脚本、不建任何文件、不读后续章节，直接给下面的简单 handoff。

| 你的情况 | 怎么办 |
|---|---|
| 单会话、任务做完传给下一个会话、只要一份交接说明 | **别用本 skill** → 简单 handoff |
| 文档 < 3 份、没有并行会话、一次性任务 | **别用本 skill** → 简单 handoff |
| 想给当前会话留个「继续提示词」 | **别用本 skill** → 简单 handoff |
| 多条线 + 多个会话并行 + 上下文容易满 + 需要长期维护 | 用本 skill，从 §3 开始 |
| 老项目已有一堆文档要整理成库 | 用本 skill，§4 + `references/migration.md` |

**简单 handoff 模板**（贴进新会话即可，不落盘、不建库、不 git）：

```text
接手 [任务]，工作目录 [DIR]。
已完成：[1–2 行]
进行中 / 卡点：[1 行]
下一手：[1 行]
相关文件 / 提交：[路径 或 git log -3]
别重复踩：[1 行，没有就删]
```

> 项目侧兜底：某个项目确定不用这套库，在它自己的 `AGENTS.md` 第一行写「本项目用简单 handoff，不加载 handoff-kb」，agent 优先听项目规则。

## 1. 分层模型与 2.0 的新增

| 层 | 文件 | 放什么 | 接手必读 |
|---|---|---|---|
| L0 入口 | `AGENTS.md`（+ `CLAUDE.md`/`GEMINI.md` 指针） | 读哪份、怎么写。**不写当前值** | 读 |
| L1 事实 | `00`（`K-xx` + 状态 + 证据）+ `10–17` 按线分册 | 当前值 / 判据 / 命令 / 坑 | 按线读 |
| L2 现状 | `05_进度仪表盘.md`（`kb:id` 章节） | 现状 / 下一手 / 各线状态 / 待办 / 硬约束 | **必读** |
| L3 流水 | `06_会话日志.md`（历史卷只读）+ `06_流水/<线>.md` | append-only 时间线 | 追溯才读 |
| L4 归档 | `90_过程档案.md` + `归档/` | 过程证据 / 验证快照 / 版本考古 | 非必读 |

2.0 相对 v1 的实质变化：

1. **编号不再冲突**：事实分册 `10–17`（旧库 `01–04` 仍合法），`00/05/06/90` 固定不动。
2. **章节可被稳定引用**：`<!-- kb:id: dashboard.current -->`，与标题文字、行号解耦。
3. **写回有并发保护**：全量 `sha256` + 文件锁 + 事务日志，`CONFLICT` 不覆盖。
4. **上下文按预算取**：`kb-context.py` 分 P0–P4 装配，硬约束永不裁。
5. **交接带证据**：`kb-handoff.py` 把「没证据的完成」判为待核。
6. **旧库能迁移**：`kb-migrate.py` 只补 schema 注释与章节 ID，不改正文。

## 2. 安装与作用域

```bash
KB="$HOME/.skills-manager/skills/handoff-kb"   # Windows: C:/Users/<你>/.skills-manager/skills/handoff-kb
ls "$KB/scripts"                               # 先确认路径再往下跑
```

客户端目录里的 `skills/handoff-kb` 通常是软链（`~/.workbuddy`、`~/.codex`、项目内 `.claude/skills` 等），真实目录只有一份。所有脚本只读写 `--target` 指定的根目录内部；路径逃出根、`..`、绝对路径、符号链接越界都会被拒绝。

## 3. 新建项目（一键）

```bash
py "$KB/scripts/kb-init.py" --target "~/projects/新项目" --project "新项目" \
    --lines "固件,运行态,服务端,测速"
py "$KB/scripts/kb-init.py" --target "~/projects/新项目" --plan    # 只看计划
```

生成：`AGENTS.md`、`CLAUDE.md`/`GEMINI.md`、`00_基线.md`、`10–17_<线>.md`、`05_进度仪表盘.md`、`06_会话日志.md` + `06_流水/*.md`、`90_过程档案.md`、`新会话启动消息.txt`、`.gitignore`/`.gitattributes`、`scripts/handoff-check.sh` 占位、`归档/`。

生成后必做三件事：

1. 填 `00` 的 `K-xx` 行（值 / 状态 / 证据）与 `05` 的现状、下一手、硬约束。
2. 按项目补 `.gitignore`（大文件、凭证先排），把 `handoff-check.sh` 换成真实只读核对。
3. `py "$KB/scripts/kb-handoff.py" check --target . --strict` 看还缺什么。

安全边界：`--plan` 不落盘；已有 git 仓库不嵌套、不自动提交；只 `git add --` 白名单；凭证命中即拒绝提交（`--force` 不绕过）；受保护配置要 `--force --overwrite-config`。

## 4. 存量项目（先诊断，再迁移）

```bash
py "$KB/scripts/kb-check.py"   --target ./old --loose      # 只读诊断（不要求改名）
py "$KB/scripts/kb-migrate.py" --target ./old --plan       # 计划绑定源哈希
py "$KB/scripts/kb-migrate.py" --target ./old --apply      # 哈希不符就拒绝
```

`kb-migrate.py` 只补 `<!-- kb:schema: 2 -->` 与已知章节的 `kb:id`：不重命名 `01–04`、不重排章节、不改正文、不删证据；重复执行幂等。有未提交改动时默认拒绝（确认无并发会话才 `--force`）。

结构改造（过程下沉 `90`、建 `05`、拆 `06`）仍按 `references/migration.md` 的五步 SOP，别跳步、别提前拆。

## 5. 接手 SOP

```bash
py "$KB/scripts/kb-context.py" --target . --task "<本次任务>" --budget 3000 --explain
py "$KB/scripts/kb-context.py" --target . --loose --task "<本次任务>"   # 自有命名项目
git status && git log --oneline -5
py "$KB/scripts/kb-search.py"  --target . --query "<关键词>" --limit 5     # 需要定位时
py "$KB/scripts/kb-outline.py" --file 05_进度仪表盘.md --section-id dashboard.next
```

预算装配顺序：P0 硬约束 → P1 现状 + 下一手 → P2 本线事实 → P3 基线命中 + 证据 + 交叉链 → P4 相关度补满（≤3 块、≤30% 预算、且命中 ≥2 个关键词或 1 个 ≥4 字符的独特词；任务点名的事实所在文件不参与 P4；只含已作废事实的章节默认不参与，问「以前 / 历史」或加 `--include-superseded` 才带回，并标注「已作废」与替代 ID）。

- 报「超额」时**不要删硬约束**：拆任务或提高 `--budget`，并把超额项写进输出让用户知情。
- 没有命中就报缺口，去 `kb-search`，别编。
- token 默认 `heuristic` 估算；用 `--tokenizer cl100k_base` 且装了 tiktoken 才是真实计数。

## 6. 写回 SOP（禁止整文件覆盖）

1. `py "$KB/scripts/kb-write.py" read --target . --file 05_进度仪表盘.md --json` → 拿 `sha256` 与章节 ID。
2. 组装 `changes.json`（`replace_section` / `append` / `update_fact`，每条带 64 位 `expected_sha256`）。
3. `--dry-run` 看差异 → `apply` 落盘。
4. `CONFLICT` = 别人改过：重新 `read`、合并、重写，**不重试覆盖**。
5. `LockHeld` = 另一个会话在写：等；确认对端进程已死才 `recover --break-lock`。

分流规则：状态/待办/下一手写 `05`；超 3 行的细节整条写 `06_流水/<线>.md`；长期事实进 `00` 或 `10–17`（带证据）；过程与验证快照进 `90`。**不改别人的行**。

## 7. 交接检查

```bash
py "$KB/scripts/kb-handoff.py" check --target . --strict
py "$KB/scripts/kb-handoff.py" check --target . --loose   # 无 kb:id 时按标题兜底
```

8 个问题逐项判定：任务 / 已完成 / 证据 / 待核 / 阻塞 / 下一步 / 受影响文件 / 禁止重复的操作。占位符（`[填`、`TODO`）与「有效但无证据」都算待核，`--strict` 直接失败。

## 8. 体检

```bash
py "$KB/scripts/kb-check.py" --target .                 # 人读
py "$KB/scripts/kb-check.py" --target . --strict        # WARN 也算失败
py "$KB/scripts/kb-check.py" --target . --json          # CI / Hook
py "$KB/scripts/kb-check.py" --target . --loose         # 自有命名（60_进度.md 等）
py "$KB/scripts/kb-check.py" --target . --mode template # 空模板：不报证据缺失
```

检查：必需文件（精确命名）、各层体积与接手成本（正文与归档分开算）、阈值、`K-xx` 重复/未定义/作废/循环引用、`kb:id` 重复与非法、事实证据与时效、表格列数、TODO、明文凭证、git 状态。

「定义位」= 标题首 / 列表首 / 表格首列，跨文件都算；句子里提到只算引用。列表写法 `- K-01：描述` 或 `- **K-01** 描述`（冒号可省），表格以首列为 ID，代码围栏里的不算。`--loose` 下未定义引用降 WARN；`60_流水/`、`90_归档/` 这类目录别名也被识别。

索引页（`00_INDEX.md` / `00_索引.md` / `TOC.md`）里的同 ID 条目算**指针**，不报「重复定义」，也不当作事实正文——事实现在是什么，读分册那份。同一 ID 在分册里出现两次仍照报 ERR。

## 9. Hook（可选，默认不装）

```bash
py "$KB/scripts/kb-hooks.py" install --client claude --target . --plan
py "$KB/scripts/kb-hooks.py" install --client claude --target . --write
py "$KB/scripts/kb-hooks.py" uninstall --client claude --target . --write
```

只写项目级配置；不带 `--write` 一律**零写入**（只打印新增/移除/保留/SHA 前后），写前重校验 SHA，现有 JSON 不合法就拒绝改写。`run` 只读、永远退出 0、不用 `decision: block`、不联网、不自动提交。Codex 用官方三级结构 `{matcher, hooks:[{type, command}]}`。事件语义见 `references/hooks.md`。

## 10. 评测

```bash
py "$KB/scripts/kb-benchmark.py" --target . --report markdown
```

A 全量 / B `00+05` / C 路由，10 个固定任务（1 个错误路径单列、不进均值），A/B/C 同一个 `TokenCounter`；报 10 项质量指标，分两级：

- **必须 100%**（不达标退出码 1）：硬约束保留、错误路径被拒绝、预算如实、工作线无静默遗漏、计数器口径一致；
- **仅报告**：章节命中、事实命中、缺口如实、归档未混入、P4 受约束。

工作线召回分「完整 / 部分 / 静默」，静默遗漏算失败。**主看 C 相对 A**（全读成本）；小库上 C 可能大于 B，因为 C 含包装。未迁移库（无 `kb:id`）或无对应事实的任务标「跳过」，不进分母。口径见 `references/benchmark.md`——**估算值不要当 API 账单**。

## 11. 阈值表（写进 `05`，触线才动手）

| 对象 | 阈值 | 动作 |
|---|---|---|
| `05` 现状 | > 4 行 | 压缩，细节进流水 |
| `05` 最近记录 | > 5 条 / 单条 > 3 行 | 整条移进 `06_流水/<线>.md` |
| `06` 单分片 | > 200 行 或 > 60 KB | 折叠进 `90`，只留标题 + 指针 |
| `00` 基线 | > 150 行 或 `K-xx` > 30 条 | 升级成结论索引 |
| `90` 归档 | > 600 行 | 再分卷或移 `归档/` |
| 事实分册 | > 8 个 | 按领域合并 |

## 12. 反模式

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

## 13. 验收四问（只看 `05` 一份）

1. 各条线现在什么状态？
2. 下一手做什么？
3. 哪些待定 / 进行中 / 已完成，证据是什么？
4. 动某个具体配置该读哪几份？

答不出 = `05` 缺信息或又膨胀了，别去全读全库补。

## 14. 文件索引

| 路径 | 用途 |
|---|---|
| `scripts/kb-init.py` | 脚手架（10–17 编号）+ 预检查 + 白名单提交 + 凭证阻断 |
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
| `references/protocol-v2.md` | 2.0 协议（编号 / 章节 ID / changes.json / 并发恢复） |
| `references/protocol.md` | v1 设计原理（历史） |
| `references/migration.md` | 存量改造手册（含 v1 → v2） |
| `references/hooks.md` | Hook 语义与安装 |
| `references/benchmark.md` | 评测口径 |
| `assets/` | 骨架模板 |
| `tests/` | 268 个 unittest + smoke + 依赖检查 |
| `tests/fixtures/ffrs/` | 脱敏「自有命名」项目夹具（`--loose` 用，内容全部虚构） |
