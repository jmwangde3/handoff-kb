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
`vendor/`、`tmp/`、`node_modules/`、`.git`、`.kb-txn`、`.kb.lock`、`unpack/`、`_tmp/`、
`.trash/`，以及 >2 MB 的文本。

**AI 客户端目录也默认跳过**：`.workbuddy`、`.shared`、`.codex`、`.qoder`、`.trae`、
`.claude`、`.cursor`、`.gemini`、`.aider`、`.continue`、`.windsurf`、`.agents`、`.kiro`、
`.zed`、`.junie`。这些目录里的 md 是 agent 工作日志和项目索引卡，不是交接正文；
进去检索会拿到「某天做过什么」，把分册结论挤出预算。`.workbuddy/memory` 常是指向
`.shared/memory` 的软链，同一份内容还会被算两遍、命中分翻倍。

### 2.1 自有命名（`--loose`）

老项目不必改名也能被读：`--loose` 下按**别名**认固定层，语义与标准命名完全等价。

| 角色 | 标准 | 别名（正则作用在文件名上，忽略大小写） |
|---|---|---|
| 基线 | `00_基线.md` | 含 `INDEX` / `索引` / `baseline` / `基线` |
| 现状 | `05_进度仪表盘.md` | 含 `进度` / `现状` / `dashboard` / `status` |
| 流水 | `06_会话日志.md` | 含 `流水` / `日志` / `log` / `handoff` |
| 归档 | `90_过程档案.md` | 含 `归档` / `archive` |
| 流水分片目录 | `06_流水/` | 目录名匹配 `^(\d{2,3}[_\- ]?)?(流水|会话流水|shards?|sessions?)$`，如 `60_流水/` |
| 归档目录 | `归档/` | 目录名匹配 `^(\d{2,3}[_\- ]?)?(归档|旧档|历史|archive|archived)$`，如 `90_归档/` |

同时命中多个时**标准名优先**（`role_files()` 里显式择优），不会因为多了一个 `60_进度.md`
就把 `05_进度仪表盘.md` 挤掉。`06_流水/` 与 `60_流水/` 同时存在时两个都收，且同一目录不会重复收录。

**事实线兜底**：别名判完之后，`--loose` 下任何 `NN_xxx.md`（编号不在保留位 `00/05/06/90`）
都当事实分册——自有命名项目常用 `20_数据与解包.md` / `30_mod开发.md` / `50_死路与坑.md`
承载 D/M/O/X 条目，它们和 `10–17` 一样参与 P2 装配与事实解析。别名先判，所以
`60_进度.md`（dashboard）、`61_流水.md`（log）不会被吞成 fact。标准命名不受影响。

编号只是入场券，不是判决：`20_会议记录.md` / `40_临时测试.md` 这类散文在
`--loose` 下同样被收进来，但**内容里没有一条条事实**，按候选分册处理（P2 不当工作线、
P4 权重 0.5、缺口里明说「当线索读」）。判据在 `facts.fact_confidence()`，
`01–04` 与 `10–17` 是协议指定的事实位，不参与这套降级——它们缺 `fact.*` 章节是写法问题。
反过来，标题就是 `G-001` 的单事实分册算结构化：一条也是事实，不是散文。

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
| `update_fact` | 定位事实定义位（标题 / 列表 / 表格）并整行替换；找不到即报错，不新增 | `fact_id`、`content` |

硬性校验：`schema_version == 1`；`expected_sha256` 必须 64 位；路径必须是工作区内相对路径、
扩展名 `.md`/`.txt`、不含 `..`、不越符号链接；所有 update 先全部校验通过才写第一个字节。

**事实定义位**（`update_fact` 与 `kb-check` 共用 `lib/facts.py`）：

| 形式 | 写法 | 说明 |
|---|---|---|
| 标题 | `## K-01 固件版本` | 章节标题的第一个词就是 ID |
| 列表 | `- K-01：固件 21.02` 或 `- **K-01** 固件 21.02` | 冒号可省，冒号后是描述 |
| 表格 | `| K-01 | 项 | 值 |` | 表格**首列**为 ID |

代码围栏里的同样文本**不算**定义。定义行里提到的其它 ID 算引用（如 `已作废 → K-04`）。
`update_fact` 遇到同一文件里同一个 ID 有**多处**定义时拒绝改写（歧义），不猜。

## 6. 哈希、锁、事务

- **哈希**：`sha256(file bytes)`；`kb-write read` 返回全量值，`kb-outline --hash` 兼容
  12 位文本短哈希（前缀匹配）。
- **锁**：`<root>/.kb.lock/`（原子 `mkdir` + `meta.json`，含 `owner_token`(uuid4)、`pid`、
  `host`、`process_start`、`created`、`session`）。规则：
  - 活进程 → 等待至超时（`KB_LOCK_TIMEOUT`，默认 5s）后 `LockHeld`，报错里带对方的 pid/host/session；
  - 死进程 **且同机** → `os.rename` 隔离成 `.kb.lock.reclaim-<uuid>` → 复核 `owner_token` → 才删；
  - `pid` 活着但 `process_start` 不同（PID 复用）→ 视为原进程已退出，可回收；
  - `meta.json` 缺失/损坏 → **不抢占**，要求人工确认；
  - `release()` 校验 `owner_token` 与 `pid`，锁已被别人接管时**拒绝删除**并报 `LockOwnershipError`；
  - 显式解锁 `kb-write.py recover --break-lock`（默认只预览），`--force` 才真删，删前重验 token。
- **事务**：`<root>/.kb-txn/`（`journal.json` + `backup/`）。状态机
  `created → prepared → applying → committed`，失败走 `rolling_back → rolled_back | rollback_conflict`。
  1) 全部预检（严格 UTF-8、路径、哈希、重复路径）→ 2) 字节级备份 + `backup_sha256`
  → 3) 写 journal(`prepared`，含 checksum) → 4) 逐个原子替换并回写条目状态
  → 5) `committed` → 6) 删除事务目录；任一步失败按备份回滚并标 `rolled_back`。
- **journal schema 2**：带 `checksum`（去掉 checksum 后 `sort_keys` 序列化再 `sha256`）。
  checksum 不符 / schema 不支持 / 状态非法 → 判为**不可信**，`recover` 只报告
  `manual-recovery-required`，事务目录与备份**原样保留**，绝不 `rmtree`。
- **恢复**：`recover` 逐文件比对当前哈希与 journal 的 `sha_before` / `sha_after`：
  - `now == sha_after` → 已写入，回滚时写回备份；
  - `now == sha_before` → 没动过，跳过；
  - 其它 → `changed-by-others`，**不覆盖**，整体转人工。
  备份哈希不匹配 → `backup-corrupt`，同样保留现场。
  `recover` 同时认 `.kb-txn/journal.json`（正在进行的现场）与 `.kb-txn/<id>/journal.json`。
- **原子性边界**：多个 `os.replace()` 不是跨文件原子事务。协议承诺的是
  「全量预检 + 备份 + 失败回滚 + 崩溃后检测」，Git 仍是最终审计与回滚手段。

## 7. 上下文装配（`kb-context`）

| 优先级 | 内容 | 预算不足时 |
|---|---|---|
| P0 | `dashboard.constraints` / `dashboard.safety`（缺失时退回 `AGENTS.md` 硬约束段） | **保留**，并报超额 |
| P1 | `dashboard.current`、`dashboard.next` | 保留 |
| P2 | `fact.current`（+ 排障类任务加 `fact.commands` / `fact.pitfalls`） | 可跳过并记入 `skipped` |
| P3 | 基线命中行、证据指针、`baseline.chains`（跨线或问「影响」时） | 可跳过 |
| P4 | 其余按相关度（≤ 预算 30% 且 ≤3 块；流水 ×0.4、归档 ×0.3、其他 ×0.5） | 可跳过 |

P4 的候选筛选有三道硬闸，都是实测踩出来的：

- **只按自有正文打分**。section 是「到下一个同级标题为止」，父节 body 天然包含所有
  子节；按 body 算命中数，父节必 ≥ 子节、永远排前面，装进来的却是整棵子树。
  打分与「空壳」判定只用标题到下一个任意级标题之间的内容，输出仍是整节。
  例外：子树里含作废事实的容器节保留——「本节省略了 N 条」只有它能表达。
- **跳过文件导语的重复部分**。第一个 `level==1` 节装的是「本文件讲什么」和适用版本，
  整份分册的主题词都在里面，按命中个数排序必进前三。但它不是无条件丢：某个子节的关键词
  集合完全覆盖 h1 时才丢；h1 里有子节没有的内容（适用版本、否定结论、入口指引）就保留。
- **跳过只含标题的空壳节**（自有正文为空且子树里没有作废事实）。例外是
  **小分册兜底**：容器节子树里一个够格的节都没有、且整节 ≤ 600 tok 时整节参赛。
  否则 1–2 KB 的分册会整条线消失（父节是空壳、子节各只命中一个词）。

权重阶梯：结构内正文（`fact` / `baseline` / `dashboard`）1.0，流水与分片 0.4，
归档 0.3，其余（`other`：入口文件、一次性发布稿、检索记录、覆盖率矩阵）0.5。
`other` 曾经也是 1.0，结果一份 62 KB 的检索记录能从任何任务里命中几个词，
凭体积压过分册条目，占掉 P4 只有 3 个的名额。

**候选分册**（`--loose` 下编号像分册、内容不像）：判据是内容，按证据强度分两档——

- 强证据：**标题位置就是事实 ID**（`## G-001 当前 MTU` / `### D-011 …`），**一条即算**
  `structured`。刚建线、只核了一个值的分册是合法状态，不该因为没凑够两条被判成散文。
- 弱证据：列表项 / 表格首列 / 正文里提到编号，可能只是举例，仍要 **≥2 条**；
  另有 `fact.*` 章节 ID 时直接算结构化。

其余按 `fact-candidate` 处理：P2 不当工作线装（那里没有事实节），P4 权重 0.5，
缺口写明「从候选分册补入 N 节：只有编号、没有事实条目，当线索读」。
判据里没有任何具体项目的文件名，换一个自有命名项目不用改代码。

**`--line` 的兜底**：显式指定工作线时，如果该分册没有 `fact.current` / `fact.commands` /
`fact.pitfalls`，直接取它自己的事实节（标题即事实 ID，最多 3 节，按任务关键词排序）。
否则自有命名项目里 `--line 数据与解包` 会 0 块——点名了一条线却什么都没给。
仅在**显式 `--line`** 时启用；任务里顺带提到线名不走这条路，避免把整节倒进上下文
挤掉 `baseline.chains` 这类跨线结论。

P4 的 `used_sources` 按相对路径比对，不是文件名：`source` 字段只存文件名给人看，
子目录里的同名文件会被判成「没用过」而重复装载。另有一道内容哈希去重：
同一段文字换个路径再来（软链、复制件）不再装第二遍。

**补入 ≠ 整线加载**：P2 按线名命中，任务里没线名就空并报缺口；P4 随后按内容补进该线的
一两节，那条缺口会撤回——但不能让人以为整条工作线都进来了。撤回之后必须补一句边界：
`P4 只补入 N 个事实节（…）：节级补充，不等于该工作线已完整加载；整线用 --line`。
预算挤掉时说法不同：`已选中但总预算装不下` / `超过 P4 预算占比`，不能说成「已补入」。

- **多工作线**：`--line 固件,运行态`，或任务里点名多条线时全部加载；只命中关键词时取最高分一条。
- 预算按**最终渲染文本**收敛：包装（标题 / 来源 / 理由 / 缺口 / 指针）都计入。
  装不下的线写进 `omitted_lines` 与 `gaps`（「工作线「X」的相关事实未加载…」），
  没有事实节的线单独说明（「没有 fact.current…」），**不把「没写」说成「预算不够」**。
- 默认预算 3000；`--format json` 输出 `blocks / skipped / gaps / used / over_budget /
  selected_lines / omitted_lines / block_tokens / rendered_tokens / required_tokens / exact /
  p4 / p4_facts / p4_candidates / deduped`。`p4_facts` 只收真事实分册的节，`p4_candidates`
  收候选分册（只有编号、没有事实条目）的节——消费方不必猜哪条是核实过的。
- 每个 block 带 `text_sha`（正文 sha256 前 12 位）：JSON 里 blocks 不带正文，要判断
  「同一段被装两遍」还是「一节按用途拆两块」只能靠它。
- `deduped` 列出被内容去重跳过的块与 `kept_in`（保留在哪一块）。只在保留的那份真的进了
  上下文时才列出——那一份也被预算裁掉时，这段内容其实没进来，报「已去重」会误导。
- `context` 的键是 `section_id`；同一 ID 出现多块（基线命中 + 证据指针）时自动加后缀，不互相覆盖。
- 找不到任何命中 → `gaps` 说明，**不虚构**。
- token：`heuristic`（CJK 1 字≈1 token，其余 4 字符≈1 token）默认；`tiktoken` 可用时标注编码器名。
  指定了 `tiktoken` 编码器却装不上 → 退出 2，必须显式 `--allow-tokenizer-fallback` 才降级（`exact: false`）。

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
