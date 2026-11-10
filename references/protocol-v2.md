# handoff-kb 2.0 协议

> 这份文件是**契约**，不含项目事实。脚本、模板、测试都以此为准；改协议要同时改
> `scripts/lib/protocol.py`、`assets/`、`tests/` 与本文件。

## 1. 版本与兼容

| 项 | v1 | v2 |
|---|---|---|
| schema 标记 | 无 | 文件首行 `<!-- kb:schema: 2 -->` |
| 事实分册 | `01–08`（与 `05`/`06` 撞号） | 新建 `10–17`；旧 `01–04` 继续合法 |
| 章节定位 | 标题文字 / 序号 | `<!-- kb:id: ... -->`，旧接口保留 |
| 写入 | 人工追加 | 全量 `sha256` + 锁 + 事务 |
| 哈希 | 12 位文本短哈希 | 写入用 64 位；短哈希仅作兼容读取 |

旧库无需改名即可被 v2 工具读取（`kb-check.py --loose`），`kb-migrate.py` 只做增量标注。

## 2. 文件角色与保留编号

| 编号 | 角色 | 规范名 | 说明 |
|---|---|---|---|
| — | 入口 | `AGENTS.md` + `CLAUDE.md` / `GEMINI.md` | 只写规则，不写当前值 |
| `00` | 基线 | `00_基线.md`（`00_baseline.md`） | 唯一共享页：`K-xx` + 状态 + 证据 |
| `05` | 现状 | `05_进度仪表盘.md` | 接手必读，禁膨胀 |
| `06` | 流水 | `06_会话日志.md` + `06_流水/<线>.md` | 历史卷只读；分片一写者一文件 |
| `10–17` | 事实分册 | `10_<线>.md` … `17_<线>.md` | 最多 8 条线 |
| `01–04` | 旧事实分册 | 原文件名 | 兼容读取，不迁移改名 |
| `90` | 归档 | `90_过程档案.md` | 非必读 |

角色判定只看文件名（`scripts/lib/protocol.py: role_of_name`）。体积统计与检索默认跳过
`AI_files/`、`assets/`、`data/`、`output/`、`evidence/`、`paktools/`、`build/`、`dist/`、
`vendor/`、`tmp/`、`node_modules/`、`.git`、`.kb-txn`、`.kb.lock`，以及 >2 MB 的文本。

## 3. 章节 ID

```markdown
<!-- kb:id: dashboard.current -->
## 0. 现状
```

- 格式：`[A-Za-z0-9][A-Za-z0-9_.:-]*`；建议 `<域>.<节>`，如 `dashboard.next`、`fact.pitfalls`。
- 绑定：注释必须**紧邻**标题，中间只允许空行；注释写在代码围栏里不算。
- 唯一性：同一文件内不得重复（`kb-check.py` 报 ERR）。
- 解耦：ID 与标题文字、行号无关；改标题、插新节都不影响引用。
- 保留 ID（工具依赖）：`dashboard.current`、`dashboard.next`、`dashboard.lines`、
  `dashboard.todo`、`dashboard.constraints`（或 `dashboard.safety`）、`dashboard.summary`、
  `baseline.facts`、`baseline.policy`、`baseline.chains`、`baseline.rules`、
  `fact.current`、`fact.commands`、`fact.pitfalls`、`fact.refs`。
- 缺失 ID 时工具退回标题/序号匹配，但**不保证**跨会话稳定；`kb-check.py` 会给 WARN。

## 4. 事实元数据（`00` 基线表）

| 列 | 含义 | 取值 |
|---|---|---|
| `ID` | 事实编号 | `K-01` / `G-007`，作废也保留、永不复用 |
| `状态` | 当前可信度 | `有效` / `待核` / `已作废 → K-xx` |
| `证据` | 可复现来源 | 命令 / 文件路径 / 测试名 / commit |
| `核实时间` | 最后核实 | `YYYY-MM-DD`；超 `--max-age-days`（默认 90）只告警 |

可选字段：`owner`（归属线）、`volatility`（`stable` / `dynamic`）、`superseded_by`。

规则：`有效` 但证据为空 → `kb-check.py` WARN、`kb-handoff.py` 判「待核」；
**不允许**把「AI 说已经完成」当证据；超期不自动改值，只提醒。

## 5. `changes.json`（写入协议）

```json
{
  "schema_version": 1,
  "updates": [
    {"path": "05_进度仪表盘.md", "expected_sha256": "<64 hex>",
     "operation": "replace_section", "section_id": "dashboard.current",
     "content": "<新正文>"},
    {"path": "06_流水/固件.md", "expected_sha256": "<64 hex>",
     "operation": "append", "content": "<追加内容>"},
    {"path": "00_基线.md", "expected_sha256": "<64 hex>",
     "operation": "update_fact", "fact_id": "K-02", "content": "<新表格行>"}
  ]
}
```

| 操作 | 语义 | 必需字段 |
|---|---|---|
| `replace_section` | 替换该 ID 章节的正文；`content` 首行若是标题则连标题一起换 | `section_id`、`content` |
| `append` | 文件末尾追加，前置一个空行 | `content` |
| `update_fact` | 定位 `| K-xx |` 表格行或 `K-xx:` 行并整行替换；找不到即报错，不新增 | `fact_id`、`content` |

硬性校验：`schema_version == 1`；`expected_sha256` 必须 64 位；路径必须是工作区内相对路径、
扩展名 `.md`/`.txt`、不含 `..`、不越符号链接；所有 update 先全部校验通过才写第一个字节。

## 6. 哈希、锁、事务

- **哈希**：`sha256(file bytes)`；`kb-write read` 返回全量值，`kb-outline --hash` 兼容
  12 位文本短哈希（前缀匹配）。
- **锁**：`<root>/.kb.lock/`（原子 `mkdir` + `meta.json{pid,created,session,host}`）。
  活进程 → 等待至超时（`KB_LOCK_TIMEOUT`，默认 5s）后 `LockHeld`；死进程 → 回收并在 stderr 说明；
  显式解锁 `kb-write.py recover --break-lock`。
- **事务**：`<root>/.kb-txn/<id>/`，含 `journal.json` 与 `backup/`。
  1) 全部预检 → 2) 备份原文件 → 3) 写 journal(`prepared`) → 4) 逐个 `os.replace`
  → 5) 写 journal(`committed`) → 6) 删除事务目录；任一步失败按备份回滚并标 `rolled_back`。
- **恢复**：`recover` 逐文件比对当前哈希与 journal 的 `sha_before` / `sha_after`：
  `written` / `untouched` / `changed-by-others`；有 `changed-by-others` 时**只报告不覆盖**。
- **原子性边界**：多个 `os.replace()` 不是跨文件原子事务。协议承诺的是
  「全量预检 + 备份 + 失败回滚 + 崩溃后检测」，Git 仍是最终审计与回滚手段。

## 7. 上下文装配（`kb-context`）

| 优先级 | 内容 | 预算不足时 |
|---|---|---|
| P0 | `dashboard.constraints` / `dashboard.safety`（缺失时退回 `AGENTS.md` 硬约束段） | **保留**，并报超额 |
| P1 | `dashboard.current`、`dashboard.next` | 保留 |
| P2 | `fact.current`（+ 排障类任务加 `fact.commands` / `fact.pitfalls`） | 可跳过并记入 `skipped` |
| P3 | 基线命中行、证据指针、`baseline.chains`（跨线或问「影响」时） | 可跳过 |
| P4 | 其余按相关度（≤ 预算 30% 且 ≤3 块；流水 ×0.4、归档 ×0.3） | 可跳过 |

- 默认预算 3000；`--format json` 输出 `blocks / skipped / gaps / used / over_budget`。
- 找不到任何命中 → `gaps` 说明，**不虚构**。
- token：`heuristic`（CJK 1 字≈1 token，其余 4 字符≈1 token）默认；`tiktoken` 可用时标注编码器名。

## 8. 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功 / 无缺失（`--strict` 下 WARN 也返回 1） |
| 1 | 校验失败、冲突、待核、预算超额、有 ERR |
| 2 | 用法或环境错误（目标不存在、路径非法、参数冲突） |

`kb-hooks.py run` 例外：**永远 0**，Hook 不得破坏会话。

## 9. 明确不做

向量库 / SQLite 索引 / embedding / MCP 常驻 / 多项目中心 / 知识图谱 / 云同步 /
自动 LLM 总结 / 自动提交 / 修改全局配置。规模上限靠机制（git + 阈值）守，不靠纪律。
