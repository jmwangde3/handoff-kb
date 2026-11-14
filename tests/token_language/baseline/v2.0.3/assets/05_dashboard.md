<!-- kb:schema: {{SCHEMA}} -->
# 05 · 进度仪表盘 — {{PROJECT}}

> **接手必读、禁膨胀**。所有会话同步状态的唯一地方：读这一份就知道各线在哪、下一手做什么。
> 完整流水在 `06_流水/<线>.md`；深归档在 `90`（非必读）。
> 章节 `kb:id` 是稳定引用点：`kb-context.py` / `kb-handoff.py` / `kb-write.py` 都按 ID 定位，不依赖标题文字。

> 最后更新：{{DATE}} (GMT+8)

<!-- kb:id: dashboard.current -->
## 0. 现状（最多 4 行）

{{INITIAL_STATUS}}

<!-- kb:id: dashboard.next -->
## 1. 下一手（具体到命令 / 文件）

- [填：下一个人第一步做什么，别写「继续推进」]

<!-- kb:id: dashboard.lines -->
## 2. 各线状态

| 线 | 状态 | 一句话 | 最近动作 |
|---|---|---|---|
{{LINE_STATUS}}

<!-- kb:id: dashboard.todo -->
## 3. 待办 / 待定 / 进行中

| 类型 | 事项 | 归属 | 证据 / 备注 |
|---|---|---|---|
| 进行中 | [填] | [填] | [填] |

> 已完成的事从本表移走，写进 `06_流水/<线>.md`；别让待办区被历史稀释。

<!-- kb:id: dashboard.cross -->
## 4. 交叉点（一次只动一条线）

| 动作 | 同时波及 | 规矩 |
|---|---|---|
| [填] | [填] | 改完立刻写 `05` + 分片 + commit |

<!-- kb:id: dashboard.order -->
## 5. 接手顺序

1. `py "$KB/scripts/kb-context.py" --target . --task "<任务>" --budget 3000`
2. 按线读：{{ROUTE_INLINE}}；跨层基线一律读 `00`。
3. 跑 `sh scripts/handoff-check.sh`（只读）→ 再动手。
4. 收尾：`kb-write.py` 写回 → `kb-handoff.py check` → `git add -- <文件>` + commit。

<!-- kb:id: dashboard.rules -->
## 6. 维护规则（不许膨胀）

- **§0 最多 4 行**；**最近记录只留 5 条摘要、单条 ≤3 行**，超了整条写分片，本文件只留一行摘要 + 指针。
- 改前 `git status`（有没有别的会话在改），改后 `git diff` 自查。
- 写回用 `kb-write.py`（带 `expected_sha256`），**别整文件覆盖写**。
- 单分片超 **200 行 / 60 KB** 按主题折叠进 `90`（触线再拆）。

<!-- kb:id: dashboard.constraints -->
## 7. 硬约束（任何预算下都不许省略）

- [填：绝对不能违反的操作边界，例如「不擅自重启生产」「凭证不入库」]
- 本段由 `kb-context.py` 强制保留；删掉它等于让后续会话失去安全上下文。

<!-- kb:id: dashboard.summary -->
## 8. 最近 5 条（完整流水见分片）

（尚无记录。每条一行 `[YYYY-MM-DD HH:MM] <线> <做了什么 → 下一手>`）
