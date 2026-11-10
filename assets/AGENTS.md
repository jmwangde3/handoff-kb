# 工作区规则 — {{PROJECT}}

> **入口，不是事实文档**：只写「什么时候用哪套流程、怎么读、怎么写回」。当前值在 `00`/`10–17`，进度在 `05`，流水在 `06`，深归档在 `90`。
> 客户端无关：WorkBuddy / Codex / Claude Code / Cursor / Gemini 一律按本文件接手。

## 0. 什么时候用这套库

- 多条线并行、多个会话可能同时改文档，或上下文容易满 → 按下面流程走。
- 单会话一次性小任务 → 别建库、别更新 `05`，写 6 行 handoff 交给下一个会话即可。

## 1. 工具与作用域

工具在 handoff-kb 技能目录（真实目录一份，客户端目录里的同名目录通常是软链）：

```bash
KB="$HOME/.skills-manager/skills/handoff-kb"   # 换成你的实际安装位置
ls "$KB/scripts"                               # 先确认路径
```

本工作区根目录即 `{{PROJECT_ROOT}}`。所有工具只在这个根内读写；路径逃出根、指向符号链接外都会被拒绝。

## 2. 接手：按预算取上下文，不全读

```bash
py "$KB/scripts/kb-context.py" --target . --task "<本次任务一句话>" --budget 3000 --explain
```

优先级固定：硬约束 → 现状 → 下一手 → 本线相关事实 → 证据指针 → 其余按相关度。
需要定位资料时再检索，命中后按章节读，别整份塞进上下文：

```bash
py "$KB/scripts/kb-search.py"  --target . --query "<关键词>" --limit 5
py "$KB/scripts/kb-outline.py" --file 05_进度仪表盘.md --section-id dashboard.next
```

`kb-context.py` 报"超额"时不要盲目删硬约束——先把任务拆小，或显式提高预算。

## 3. 写回：哈希校验 + 锁，禁止整文件覆盖

1. 读：`py "$KB/scripts/kb-write.py" read --target . --file 05_进度仪表盘.md --json` → 拿全量 `sha256` 与章节 ID。
2. 写：把改动写成 `changes.json`（`replace_section` / `append` / `update_fact`，每条带 `expected_sha256`），先 `--dry-run` 再 apply。

```bash
py "$KB/scripts/kb-write.py" apply --target . --changes changes.json --dry-run
py "$KB/scripts/kb-write.py" apply --target . --changes changes.json
```

- 只改自己这条线：流水写 `06_流水/<线>.md`，**不改别人的行**。
- `05` 只放状态、待办、下一手；超 3 行的细节整条进 `06`。
- 完成项要带证据（命令 / 文件 / 提交），没证据就写「待核」。

## 4. 冲突处理

- `kb-write.py` 报 `CONFLICT`：**不要重试覆盖**。重新 `read` 拿最新哈希，合并后再写。
- 报 `LockHeld`：另一个会话在写。等它释放；确认对方进程已死才 `kb-write.py recover --break-lock`。
- 崩溃或断电后：`py "$KB/scripts/kb-write.py" recover --target . [--dry-run]`，按报告决定清理还是回滚。
- **永不** `git add -A`；只提交本任务涉及的文件。

## 5. 收尾与交接

```bash
py "$KB/scripts/kb-handoff.py" check --target . --strict   # 交接是否可验证
py "$KB/scripts/kb-check.py"   --target .                  # 体积 / 编号 / 凭证 / git
git add -- <本次改的文件> && git commit -m "<线> <做了什么>"
```

交接必须能回答：当前任务、确实完成了什么、证据、未核实项、阻塞、下一步、受影响文件、禁止重复的操作。

## 6. 线与文件

| 线 | 读哪几份 |
|---|---|
{{ROUTE_TABLE}}

| 文件 | 放什么 |
|---|---|
| `00_基线.md` | 基线（`K-xx` + 状态 + 证据）+ 策略 + 交叉链，唯一共享页 |
{{FILE_TABLE}}
| `05_进度仪表盘.md` | 现状 / 下一手 / 各线状态 / 待办（接手必读，禁膨胀） |
| `06_会话日志.md` | 历史卷与分片索引（只读） |
| `06_流水/<线>.md` | 按线 append-only 流水（一写者一文件） |
| `90_过程档案.md` | 深归档（按主题，非必读） |
| `归档/` | 一次性任务单、拆分前备份 |

{{SHARD_SECTION}}
## 7. 硬约束（按项目填）

- [填：凭证 / 备份 / 不可重排的编号契约 / 不可触碰的实机]
- 编号 `K-xx` / `G-xxx` / 章节 ID 是跨文档契约：改内容可以，**别重排、别复用已作废的 ID**。
- 本文件不写当前值；一旦写进去就出现第二套说法。
