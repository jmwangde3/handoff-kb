# handoff-kb 2.0.4

> **工具版本** `2.0.4`（脚本行为）｜**协议版本** `2`（文档布局，`<!-- kb:schema: 2 -->`）。
> 两者独立：换工具版本不改协议，也不要求现有库迁移。

English edition: [`README.md`](README.md)（英文主手册）。

**给多会话并行项目的分层交接库。** 一套 Markdown 协议 + 十个零依赖 Python 脚本：让「上下文快满、几条线同时推、文档越堆越多」的项目，新会话接手时只读固定的一小份，而不是全库重读。

2.0 的重点不是加脚本，而是把四件事做实：**按预算取上下文、带证据的交接、带哈希校验的写入、能跑起来的测试**。仍然是纯文本、可 diff、无服务、无 embedding、无 SQLite。

```
接手 → kb-context（预算内最小上下文）→ 干活 → kb-write（哈希校验写回）→ kb-handoff（交接自检）
```

---

## 1. 它解决什么（算术问题，不是文风问题）

中文 UTF-8 约 4.5 字节 / token；英文约 4 字符 / token，而同一份内容的英文译文要 2.5–3 倍字符数。无论哪种口径，全读一遍的代价都随文档总量线性增长，而**真正决定接手质量的信息**（现在在干嘛、下一手、别做什么）通常不到 20 KB。

答案不是「把文档写薄」，而是**把「存」和「读」解耦**：总量可以涨，单次必读集合恒定。

两个口径的数字，别混：

| 场景 | 结果 | 口径 |
|---|---|---|
| 真实路由器项目（v1 时代） | 全库 1,759 行 / 221 KB → 接手 20.6 KB（`05`+`00`），降 90% | 实际文件体积，非估算 |
| 合成夹具（2.0.1-hotfix benchmark） | A 全量 3,082 / B `00+05` 389 / C 路由 454 tokens，任务 10/10，质量项 63/63 | `heuristic` **估算**，夹具 ~11 KB |
| 脱敏 FFRS 夹具（自有命名，`--loose`） | A 1,248 / B 446 / C 561 tokens（相对 A 降 55%） | 同上，内容全部虚构 |

前两行可用两条命令复现（`py tests/make_fixture.py ../kbdemo` → `py scripts/kb-benchmark.py --target ../kbdemo`）。**注意夹具上 C（454）并不比 B（389）小**：C 含包装（标题 / 来源 / 理由 / 缺口），B 只是 `00+05` 原文；夹具太小，包装开销占满。真正有意义的是相对 A 的 85%——A 才是「全读」的成本。口径与逐任务明细见 `references/benchmark.zh-CN.md`。

英文版 / 中文精简版的 token 数字见 §12.1，全部实测；DeepSeek 自有词表下达不到 15% 目标的部分照实报，不修饰。

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

## 3. 语言：一个技能，任意知识库语言（2.0.4 新增）

2.0.4 只发**一个**技能：`SKILL.md`，正文英文。它的指令语言不等于知识库语言，两者各自独立选择。**模板按项目现有文档的语言选，不按操作者语言选。**

| 情况 | 用哪套模板 | agent 读到什么 |
|---|---|---|
| 中文项目（文档已是中文） | `assets/`（默认，`--lang zh`） | 英文技能 + 中文文档 |
| 英文项目（文档已是英文） | `assets/en/`（`--lang en`） | 英文技能 + 英文文档 |
| 中英混排的旧项目 | **沿用现有文档的主导语言**，不转换 | 英文技能 + 原有内容 |
| 新建项目、还没有文档 | 问一次，或跟随用户消息语言 | 英文技能 + 选定的模板集 |

硬规则：

- **绝不自动翻译已有内容。** 模板、协议状态词（`有效` / `待核` / `已作废`）、保留文件名（`00_基线.md`、`05_进度仪表盘.md` …）和 `kb:id` 取值都属于协议数据，不是散文。英文项目照样用协议的状态词与 ID；中文项目照样用中文文件名。
- **指令永远是英文，不管知识库是什么语言。** 管着中文库的 agent 读英文指令、写中文文档，两者不需要一致。
- **一个库只用一种散文语言。** 同一库里混两种散文语言，只会让检索噪音翻倍而不增加信息。
- **选择是按库的，不是全局的，而且几乎没有命令行开关承载它。** `kb-context` / `kb-check` / `kb-write` 与语言无关、没有 `--lang`；只有 `kb-init` 有，因为只有搭骨架需要选模板集。

`kb-init.py --lang {zh,en}` 选模板集。两套产出**同样的 17 个文件、同样的相对路径、同样的占位符、同样的 `kb:id` 集合**，由 `tests/token_language/test_token_language.py::TemplateParity` 守住。

中文**参考**版（`references/*.zh-CN.md`）作为可选中读资料一起发，协议 ID、命令、JSON 形状、退出码与英文版一致。它们是参考资料，不是第二个技能：`SKILL.md` 是唯一可发现的技能文件，有测试守住这一条。

有一处要明说：英文项目生成的启动消息仍然叫 `新会话启动消息.txt`，因为那是骨架的固定槽位。它不是协议数据，也没有脚本依赖这个名字；保持统一的原因是——文件名随语言变，一致性用例就只能比对「槽位集」而不是字面路径，而字面路径比对才是能抓出「真少了一个文件」的那种。觉得别扭就本地改名，不会坏任何东西。

---

## 4. 分层模型

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

## 5. 一键初始化

**依赖**：Python 3.10+，**必需依赖只有标准库**。可选依赖两个，都只为精确 token 计数，都在函数内 `try/except` 导入：

| 可选 | 换来什么 | 没有它 |
|---|---|---|
| `tiktoken` | `--tokenizer cl100k_base` / `o200k_base`，精确 BPE 计数 | 指定即退出 **2**；`heuristic` 照常可用 |
| `tokenizers` + DeepSeek 的 `tokenizer.json` | `--tokenizer deepseek_v4`，在 DeepSeek 自有词表上精确计数 | 指定即退出 **2**；`deepseek_estimate` 按官方比例估算 |

没有任何东西静默降级：显式指定的编码器要么能用，要么退出 2；唯一接受估算的办法是 `--allow-tokenizer-fallback`，此时输出自己标 `exact=false`。`tests/deps_check.py` 走每个脚本的**完整 AST**，超出上表的第三方导入、出现在模块顶层、或没包 `try/except`，一律失败；`tests/test_deps_check.py` 再测这个检查器本身，新增依赖不可能不被发现。

```bash
KB="$HOME/.skills-manager/skills/handoff-kb"   # 换成你的安装目录
py "$KB/scripts/kb-init.py" \
    --target "~/projects/新项目" --project "新项目" \
    --lines "固件,运行态,服务端,测速" --lang zh
```

```bash
# 英文项目
py "$KB/scripts/kb-init.py" --target "~/projects/new-project" \
    --project "new-project" --lines "firmware,runtime,server,throughput" --lang en
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
--lang zh|en                 模板语言（默认 zh，行为与 2.0.3 一致）
--json    机器可读
```

---

## 6. 旧库迁移（v1 → v2，无损）

```bash
py "$KB/scripts/kb-check.py"   --target ./old --loose      # 先只读诊断
py "$KB/scripts/kb-migrate.py" --target ./old --plan       # 计划写 .kb-migrate-plan.json
py "$KB/scripts/kb-migrate.py" --target ./old --apply      # 校验源哈希后再写
```

只做**增量**：补 `<!-- kb:schema: 2 -->`、给已知章节补 `kb:id`。不重命名 `01–04`、不重排章节、不改正文、不删证据。计划绑定源文件哈希——文件被别的会话改过就拒绝，重跑 `--plan` 即可。重复迁移幂等。

---

## 7. 新会话恢复：按预算取上下文

```bash
py "$KB/scripts/kb-context.py" --target . --task "排查 NSS 网络问题" --budget 3000 --explain
py "$KB/scripts/kb-context.py" --target . --loose --task "查看当前项目状态"  # 自有命名项目
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
- Token 默认 `heuristic` 估算（CJK 1 字≈1 token，其余 4 字符≈1 token）；装了 `tiktoken` 且指定 `--tokenizer cl100k_base` 才用真实编码，输出里会标明用的是哪个。`--tokenizer deepseek_v4` 走 DeepSeek 官方离线词表（见 §12.1），`deepseek_estimate` 只按官方比例估算并明确标注。

---

## 8. 检索与按节精读

```bash
py "$KB/scripts/kb-search.py"  --target . --query "NSS 网络问题" --limit 5
py "$KB/scripts/kb-outline.py" --file 05_进度仪表盘.md --section-id dashboard.next
py "$KB/scripts/kb-outline.py" --file 05_进度仪表盘.md --find 磁盘
```

- 检索直接扫 Markdown（无索引服务）：中文按「整段 + 二元组」近似，英文不分大小写；打分顺序 = 精确 ID / 事实 ID 行 > 文件名 / 工作线 > 标题 > 正文；流水降权，归档与已作废行默认排除。
- 只回定位（文件 / 章节 ID / 行号 / 160 字摘要 / 分数 / 哈希 / 估算 token），正文用 `kb-outline.py` 按节读。
- `--hash` 传了就校验：文档变了就拒绝读（退出码 2），防止按过期目录取到错节。

---

## 9. 安全写回（哈希 + 锁 + 事务）

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

## 10. 交接检查（证据优先）

```bash
py "$KB/scripts/kb-handoff.py" check  --target . --strict
py "$KB/scripts/kb-handoff.py" check  --target . --loose   # 无 kb:id 时按标题兜底
py "$KB/scripts/kb-handoff.py" report --target . --json
```

逐项判定 8 个问题：当前任务 / 确实完成了什么 / 证据 / 未核实项 / 阻塞 / 下一步 / 受影响文件 / 禁止重复的操作。

- 模板占位（`[填` / `TODO`）算**待核**，不算完成。
- 基线里「有效」却没有证据的条目 → 待核；不会自动升级成已验证。
- `--strict` 下有待核项即失败（退出码 1），适合放进收尾流程。

---

## 11. 体检

```bash
py "$KB/scripts/kb-check.py" --target .                  # 人读
py "$KB/scripts/kb-check.py" --target . --strict         # WARN 也算失败
py "$KB/scripts/kb-check.py" --target . --loose          # 自有命名体系
py "$KB/scripts/kb-check.py" --target . --json           # CI / Hook
py "$KB/scripts/kb-check.py" --target . --mode template  # 刚初始化的空模板
```

检查：必需文件（精确命名优先，不用 `05_*.md` 通配）、各层体积与接手成本、阈值命中、`K-xx` 重复定义 / 未定义引用 / 作废引用 / 循环作废链、`kb:id` 重复与非法格式、事实证据与核实时效、表格列数、残留 TODO、明文凭证、git 未提交改动。ERROR > 0 退出码 1。

体积统计**分两层报**：正文（不含 `归档/`）与归档各自计数，接手成本只对正文算；跳过 `AI_files/` / `assets/` / `data/` / `output/` / `evidence/` / `unpack/` / `_tmp/` / `node_modules/` / `build/` 等资料目录与 >2 MB 文本。归档长期大于正文 3 倍会报 WARN——备份该折叠了。

编号检查认「定义位」：标题首、列表首、表格首列，**跨文件**都算（`## G-010 …` 就是定义）；只在句子里提到的算引用。`--loose` 下未定义引用降为 WARN，避免自有命名项目一上来就 10 条 ERR。`--loose` 还把 `20_数据` / `30_mod开发` / `50_死路与坑` 这类数字分册当事实线（别名先判，`60_进度` 等仍按各自角色走）。

---

## 12. 测试与 benchmark

```bash
python -m unittest discover -s tests        # 392 例（341 既有 + 40 例 token_language + 11 例 deps_check）
python tests/smoke.py                       # 端到端：init→check→search→context→handoff→write→migrate
python tests/deps_check.py                  # scripts/ 不得引入标准库以外的依赖
python scripts/kb-benchmark.py --target . --report markdown
python tests/token_language/run_token_benchmark.py --all --out tests/token_language/out
```

- 既有用例覆盖：锁所有权 / 死锁回收 / 不完整锁不抢占、事务回滚与 journal 校验和、recover 三态、迁移计划绑定哈希与 root_id、路径越界与符号链接剪枝、事实三定义位与索引页指针、作废链与 ID 不可变、多工作线装配与预算收敛、P3/P4 受控、`--loose` 自有命名（含数字分册兜底与候选分册降权）、agent 目录不进检索、P4 只按自有正文打分、P4 补入边界与 `p4_facts`、P0 三级兜底（含软链越界与占位符）、围栏内容不进计数、Hook 预览零写入 / 多文件回滚 / 官方事件结构、真实子进程并发与故障注入、benchmark 指标与质量门、内容级去重与重复装载指标、单事实分册与 `--line` 兜底、容器 599/600/601 边界、P0 去重豁免、P0 两级 dashboard 逐级兜底、h1 导语判定（正文逐句比对 / 短句按任务相关性 / 导语与事实混句）。
- `tests/fixtures/ffrs/` 是脱敏的「自有命名」项目夹具（`60_进度.md` / `61_流水.md` / `60_流水/`），全部虚构内容，用来验证 `--loose` 与标准命名等价；`tests/fixtures/plain/` 是普通数字编号库（`00/05/20/30/40/50`，无 `kb:id`、无事实结构），用来验证「编号像分册」不等于「里面是事实」。
- CI：`.github/workflows/test.yml`，Ubuntu + Windows × Python 3.10 / 3.12 / 3.13，无网络、无凭证、库依赖只有标准库（可选 `tiktoken` 与 `tokenizers` 由 `deps_check.py` 显式放行，且必须写在函数内、包 `try/except`）。
- benchmark 对比 A 全量 / B `00+05` / C 路由，10 个固定任务（其中 1 个是错误路径，单列、不进均值）；A/B/C 用同一个 `TokenCounter`；输出 10 项质量指标，其中 5 项是硬门槛（硬约束保留、错误路径拒绝、预算如实、工作线无静默遗漏、计数器口径一致），不接受被平均值抹平；任务通过率门槛 80% **向上取整**（8 个任务要 7 个过，`round()` 会把 6.4 抹成 6）。

### 12.1 中英双语 token 基准（2.0.4 新增）

三个变体：**A** 原版中文 v2.0.3（冻结） · **B** 优化中文 v2.0.4——**基准测试样本，不是发布技能** · **C** 发布版英文技能 v2.0.4。
`structure = 1 − B/A`，`language = 1 − C/B`，`total = 1 − C/A`。分母为零时显式写「不适用」，不写成 0%。

B 只为一件事存在：没有「优化后文本」的中文版，`A → C` 会把结构精简和改写语言混成一个无法归因的数字。留着 B，两个因子才各自可测。它在 `tests/token_language/sample_b/`，字节由 SHA256 断言钉住，不可安装——2.0.4 只发一个技能。

`SKILL.md` 正文，2026-11-14 实测：

| 词表 | A | C | 总降幅 | 15% 目标 |
|---|---|---|---|---|
| `cl100k_base`（tiktoken，精确） | 5,416 | 3,903 | **27.9%** | 达到 |
| `o200k_base`（tiktoken，精确） | 4,571 | 3,878 | **15.2%** | 达到 |
| `deepseek_v4`（官方离线 `tokenizer.json`，精确） | 4,343 | 3,943 | **9.2%** | **未达到，照实报** |
| `deepseek_estimate`（官方比例 0.3 / 0.6，**估算**） | 3,261 | 4,583 | −40.5% | 不适用 |

把 YAML description 也算进去（客户端真正先加载的那部分），合计是 `cl100k_base` 5,533 → 3,972（−28.2%）、`deepseek_v4` 4,406 → 4,014（−8.9%）。在 DeepSeek 词表上**description 自己是变长的**：63 → 71——同一句触发描述，英文需要更多这个词表的 token。正文占大头，所以合计仍然下降。

参考手册在 `deepseek_v4` 下：protocol-v2 5,171 → 4,969（3.9%）、migration 4,675 → 4,452（4.8%）、hooks 2,377 → 2,300（3.2%）、benchmark 5,424 → 5,193（4.3%）。模板：`AGENTS.md` 1,232 → 1,237、`05_dashboard.md` 784 → 760——**模板在两种语言下基本等长**，这正是预期：模板主要是占位符和协议词汇。

DeepSeek 为什么达不到 15%：它的词表偏中文，中文原文本身已经很紧（约 7.7 k 字符 = 4,343 tokens），同一份内容写成英文要约 12.4 k 字符。同样的结构调整，在拉丁字母为主词表上省 27.9%，在中文为主词表上省 9.2%——所以门槛是分开的：**`cl100k_base` / `o200k_base` 按 15%，`deepseek_v4` 按「不增长」**。逐节、逐任务、逐文件的完整表在 `tests/token_language/out/token-benchmark-all.md`（同目录有 JSON）。

读数口径（避免过度解读）：

- `cl100k_base` / `o200k_base` 是可复现的代理词表，不是任何一个模型的计费 tokenizer。
- 每份报告都写明用了哪套词表：`deepseek_v4` 记录文件名、`tokenizer.json` 的 SHA256 和 `tokenizers` 版本，且报告里没有任何个人路径——既能证明两个数字来自同一套词表，又不用公开谁的目录结构。当前哈希 `89085f12…c9614`。
- `deepseek_estimate` 只套官方公布的比例（1 英文字符≈0.3、1 中文字符≈0.6），在所有输出里都标 `estimate`。**这个比例模型不能用来做跨语言比较**——译文总字符数更多，公式会报「变长了」，而真实词表报「省了」。报告里保留这一组，就是为了把它失效的边界写清楚。
- `heuristic`（CJK 1 字≈1 token，其余 4 字符≈1 token）只作估算报，从不用于结论。
- 词表缺失即报错（退出码 2），不静默降级：报告绝不声称自己拥有并不具备的精确性。
- 结构对照靠章节标题与协议 ID，不逐句做语义等价；规则表（19 条必备规则，只针对发布的那份英文技能）在 `tests/token_language/test_token_language.py`。

---

## 13. Hook（默认不安装）

```bash
py "$KB/scripts/kb-hooks.py" install   --client claude --target . --plan
py "$KB/scripts/kb-hooks.py" install   --client claude --target . --write
py "$KB/scripts/kb-hooks.py" uninstall --client claude --target . --write
```

- 只写**项目级**配置（`.claude/settings.json`、`.codex/hooks.json` + TOML 片段），不动全局。
- 事件：`SessionStart`（注入小预算上下文）/ `PreCompact`（提醒收尾）/ `Stop`（交接自检，只提醒）/ `SessionEnd`（Claude 侧空响应）。Codex 侧按官方三级结构 `{matcher, hooks:[{type, command}]}` 写，Claude 侧独立结构；**不使用** `decision: block`，任何事件都不阻断会话。
- 预览是默认行为：`--plan` 与不带 `--write` 都只打印「新增/移除/保留/SHA 前后」，**零写入**；`--write` 才落盘，且写前重校验 SHA，别人改过就放弃。
- `run` **永远退出 0**：Hook 自己出错也不能破坏会话。不联网、不自动提交、不重写事实文档。
- 事件名与退出码语义以各客户端当前官方文档为准（见 `references/hooks.zh-CN.md`），`--plan` 先看清楚再 `--write`。

---

## 14. 协议兼容

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

## 15. 风险、限制与恢复

- **不做**：向量库 / SQLite 索引 / embedding / MCP 常驻 / 多项目中心 / 知识图谱 / 云同步 / 自动 LLM 总结。
- 规模上限靠机制（git + 阈值）守，不靠纪律；超过约 8 条线或 `00` 超 150 行该合并或升级，而不是继续加文档。
- 普通编辑器直接改文件会绕过锁，所以**哈希重校验必须保留**；`kb-write` 会拒绝过期哈希。
- Hook 依赖客户端事件语义，客户端升级可能改变行为；`run` 出错只打印、不阻断。
- 崩溃恢复：`kb-write.py recover --dry-run` 先看，再 `--apply`；有他人改动时只报告不覆盖。
- 凭证：扫描是正则启发式，命中即阻断；但**没命中不等于安全**，`.gitignore` 仍要在第一次 `git add` 之前写好。

---

## 16. 文件

```text
CHANGELOG.md                   简版版本记录；完整编年史见本文件 §17
SKILL.md                       技能本体——英文，9 个编号章节，唯一的技能文件
references/protocol-v2.md       2.0 协议：编号、章节 ID、changes.json、并发与恢复
references/protocol-v2.zh-CN.md 上者的中文版（可选读物）
references/protocol.md          v1 设计原理（历史，仅中文）
references/migration.md         存量改造手册（含 v1 → v2）
references/migration.zh-CN.md   中文版
references/hooks.md             Codex / Claude Code Hook 语义与安装
references/hooks.zh-CN.md       中文版
references/benchmark.md         评测口径、任务集、如何解读
references/benchmark.zh-CN.md   中文版
assets/                         中文模板（AGENTS / 00 / 05 / 10–17 / 06 / 90 / 启动消息 / git 配置）
assets/en/                      英文模板（占位符与 kb:id 集合与中文版相同）
scripts/kb-init.py              脚手架 + 预检查 + 白名单提交 + 凭证阻断（--lang zh|en）
scripts/kb-check.py             只读体检（--loose / --json / --mode）
scripts/kb-outline.py           目录树 + 稳定章节 ID + 按节读 + hash 校验
scripts/kb-write.py             安全写入（哈希 / 锁 / 事务 / recover）
scripts/kb-migrate.py           v1 → v2 无损迁移（计划绑定哈希）
scripts/kb-search.py            轻量全文检索（章节级打分）
scripts/kb-context.py           预算内上下文路由（--explain）
scripts/kb-handoff.py           交接有效性检查（证据优先）
scripts/kb-hooks.py             客户端 Hook 适配（默认不安装）
scripts/kb-benchmark.py         Token 与质量评测
scripts/lib/                    共享库：protocol / scope / markdown / safeio / security / tokens / terms / facts
tests/                          全量 unittest + 端到端 smoke + 依赖检查 + 夹具生成器
tests/make_fixture.py           生成 benchmark 用的合成夹具（§1 的数字可复现）
tests/fixtures/ffrs/            脱敏「自有命名」项目夹具（--loose 用，内容全部虚构）
tests/token_language/           A/B/C token 基准、规则与布局测试、v2.0.3 冻结基线
tests/token_language/sample_b/  冻结的中文 2.0.4 文本——只作基准样本，不是技能
tests/deps_check.py             非标准库导入检查（走完整 AST，只允许 tiktoken / tokenizers）
.github/workflows/test.yml      Ubuntu + Windows × 3 个 Python 版本
```

---

## 17. 版本变更记录

### 17.1 2.0.1-hotfix 修了什么

2.0.1-hotfix 是**修可靠性**的补丁版：不加协议能力，`kb:schema: 2` 与 v1→v2 迁移方式都没变。
所有改动都能落到一个具体后果上——「这会让谁少踩一次坑」。

#### 17.1.1 安全与并发

- **路径发现不再信字符串**：绝对路径、盘符、UNC、`..` 一律拒绝。POSIX 上 `PurePath("C:/x").drive`
  是空的，所以盘符判定改成正则——此前 Linux 上 `C:/Windows/x.md` 能过。
- **越界判定按路径组成，不按前缀**：`C:\proj` 与 `C:\proj-backup` 不是包含关系；符号链接与 Junction
  越界会被剪枝，并产出 `dir-outside` / `symlink-outside` 诊断，而不是静默跳过。
- **事务目录必须在库内**：`.kb-txn/`、备份、journal 逐个核对；journal 里的 `root_id` 与当前目录不符
  直接判 `manual-recovery-required`（`--force` 也不绕）；写回前二次 `sha256` 校验，冲突就保留现场。
  （**这不是跨进程 CAS**，见 §18.5。）
- **`kb-hooks install` 默认预览**，`--write` 才落盘；写前重校验 SHA；TOML 卸载不留空表头。

#### 17.1.2 Hook 集成

- 安装前预检 `original_exists` + `sha256` 双状态：预览之后文件被别的会话改过，就**放弃整个安装**。
- 多文件安装要么全做要么全退：逐文件写，失败按字节快照回滚，不留半套配置；
  回滚本身也走原子字节写（临时文件 → `os.replace`），不会把旧配置写成半截。
- `SessionStart` 的 matcher 按两家官方语义修正为 `startup|resume|clear|compact|fork`
  （2.0.1 漏了 `clear`，清空会话后重新开始拿不到接手上下文）。
- `PreCompact` 的输出按两家协议分开：Claude Code 丢弃 `systemMessage`，非阻断时
  **stdout 纯文本**才是压缩摘要的指令；Codex 认 `systemMessage`、忽略纯文本。
- 输出用 `hookSpecificOutput.additionalContext` / `systemMessage`，不用 `decision: block`；
  `run` 永远退出 0、只读、不联网。Codex 用官方三级结构 `{matcher, hooks:[{type, command}]}`。

#### 17.1.3 事实（`00` 与 `10–17`）

- **事实 ID 不可变**：`update_fact(K-01, "## K-99 …")` 直接拒绝——那不是更新，是「用一次更新
  把 K-01 换成 K-99」，全库引用会指向空气。多行 `content` 也拒绝（只会替换定义行，多出来的会被丢掉）。
- **三种定义位同权**：标题首 / 列表首 / 表格首列都能定义事实，`kb-check` / `kb-search` /
  `kb-context` / `kb-handoff` / `kb-write` 共用 `lib/facts.py` 一套判定，不再各写一套正则。
- **索引页里的条目是指针**：`00_INDEX.md` 的「待核」列表写着同一批 ID，那是导航不是定义。
  现在标 `pointer`：不算重复定义、不当事实正文、不抢搜索满分。真实库上因此从
  **ERR 4 → ERR 0**（此前每次体检都报 4 条假重复）。
- **查不到 ≠ 通过**：解析失败的文件单独报 ERR 并写明「其中的事实未被检查」；全库零定义时报
  「这不是全部通过」；`counts()` 把定义 / 规范 / 指针 / 有效 / 待核 / 作废 / 未知 / 重复 / 文件失败分开数。

#### 17.1.4 上下文路由

- `kb-search` 与 `kb-context` 真正复用 `lib/facts.py`：作废判定走规范化 `status`，不再看
  「这一行有没有『已作废』四个字」；被排除的定义进 `superseded` 列表并给出替代 ID。
- 任务点名 `K-xx` / `G-xxx` 时走 P3 专线：有效 → 给整段定义；作废 → 报缺口 + 替代 ID；
  待核 → 明说「待核」；库里没有 → 报缺口，不编。
- **P4 受控**：最多 3 块、最多占预算 30%、且必须命中 ≥2 个关键词或 1 个 ≥4 字符的独特词；
  任务点名的事实所在文件整份不参与 P4（否则会把已作废的整篇捞回来），事实 ID 也不作 P4 关键词。
- **只含已作废事实的章节默认不进 P4**（见 §17.1.7）：任务没在问「以前 / 历史」时，作废内容
  按行置空（同节有效内容照留），整节相关性都来自作废内容时整节跳过并在缺口里报数。
- 归档（`90_*`）与流水（`06_流水/`）统一按相对路径定角色降权，`--include-archive` 才升级。

#### 17.1.5 评测

- 10 项质量指标分两级：**5 项必须 100%**（硬约束保留、错误路径拒绝、预算如实、工作线无静默遗漏、
  计数器口径一致），**5 项仅报告**（章节命中、事实命中、缺口如实、归档未混入、P4 受约束）。
  把受夹具内容限制的指标写死成 100%，只是把测试调绿。
- 任务集 10 条，新增「按 ID 定位事实」「作废要指向替代」「待核要标待核」「多工作线召回」。
  没有可测对象时标 `skip` 且不进分母——「没测到」不许冒充「通过了」。
- 召回分 完整 / 部分 / 静默，静默遗漏算硬失败。

#### 17.1.6 撤回的数字

- **「C = 89 tokens / 降 77%」**（2.0 文档）：产生于 P2 事实块根本没进装配队列的缺陷版本，
  少给内容所以数字小，被写成了「路由很省」。
- **「C = 395.6」（合成夹具）/「C ≈ 1,886」（真实库）**：任务集与指标口径都变了
  （8 项 → 10 项，任务集换了 4 条），这组数不再可比，已删除。当前口径下的数字见 §1 与
  `references/benchmark.zh-CN.md`。

#### 17.1.7 PR #1 复审补丁（四处收口）

复审在已经通过六环境 CI 的 `52dcecf` 上又找出四个口子，只修这四处、不扩范围：

1. **`AGENTS.md` 没有路径校验**：`kb-context` 读入口文件前只看 `is_file()`。
   库里放一个指向库外的符号链接，就能把别人的文件当「本库硬约束」注入。
   现在先过 `scope.is_within()`（`resolve()` 展开符号链接与 Windows Junction），
   越界则跳过并写进缺口。`role_files` / `iter_text_files` 早就这么做，只有这处漏了。
2. **P4 不认 `status: deprecated`**：只含已作废事实的章节会被当成普通「相关补充」捞回来，
   而 P3 按 ID 查同一条时明明会说「已作废」。现在 P4 用 `lib/facts.py` 的解析结果标注节内事实，
   与 `kb-search` 用同一口径**按行置空**作废定义：
   - 混合节 → 保留仍然有效的内容，正文前写「已省略 N 条已作废事实：G-014（替代 G-013）」；
   - 整节相关性都来自作废内容（或标题行本身就是那条作废定义）→ 整节跳过并在缺口里报数；
   - 任务在问「以前 / 历史 / 作废」，或显式 `--include-superseded` → 原样带回，
     正文前标「已作废：G-011（替代 K-04）」。
   `p4.deprecated_skipped` 计入 JSON，便于基准区分「被过滤」与「没命中」。
3. **`PreCompact` 用了 Claude 会丢弃的字段**：Claude Code 官方文档写明
   「discards a PreCompact hook's `systemMessage` and `continue` fields」，非阻断时
   **stdout 纯文本**才是压缩摘要的指令。现在 Claude 发纯文本、Codex 发 `{"systemMessage": …}`，
   两家都不发 `decision` / `continue`。此前对 Claude 发 `systemMessage` 等于什么都没说。
4. **回滚用 `write_bytes()` 直接盖**：写到一半崩掉会把本来完好的旧配置变成半截。
   改用 `atomic_write_bytes()`（临时文件 → fsync → `os.replace` → fsync 目录），
   第三方改动的冲突检测保持不变——检测不过就保留现场，不覆盖。

判断依据很简单：`used` 只有 89，而 P0+P1 本身的包装就超过这个量。现在的实现会
1) 先把 P2 真正装配进去，2) 按**最终渲染**收敛预算，3) 把装不下的线写进 `omitted_lines` 与缺口。
宁可数字变大，也不把「漏给」记成「省了」。

### 17.2 2.0.2：门槛取整、记录计数、自有命名分册

三处都是「规则写了，实际没生效」，在真实库（FFRS）上各踩到一次：

1. **质量门 80% 被 `round()` 抹成 75%**：`need = int(round(len(graded) * 0.8))`，
   8 个可评任务时 `round(6.4) = 6`，6/8 = 75% 也能过，报告照样打印「≥80%」。
   现在改用整数运算向上取整 `max(1, (total*4 + 4) // 5)`：全程不碰浮点，
   就没有「差一点点算不算进位」的讨论空间。8 个任务现在需要 7 个通过。
2. **`05 最近记录` 只数 `-` / `*` 行**：全用 `[2026-11-12 09:20] …` 记流水的库恒报「0 条」，
   ≤5 条的阈值形同虚设（真实库明明有 5 条，一直显示 0 条假绿）。
   现在列表项、编号项、时间戳开头三种形态都算，表格行 / 引用行 / 代码围栏跳过。
3. **`--loose` 只把 10–17 当事实分册**：自有命名项目的事实线常是 `20_数据与解包.md` /
   `30_mod开发.md` / `50_死路与坑.md`，此前全被判成 `other`，P2 永远只有第一条线，
   「单工作线排障」任务也就永远命中不了 `fact.pitfalls`。
   现在 loose 下数字分册兜底算 fact——别名先判，`60_进度` / `61_流水` / `00_INDEX` / `90_归档`
   仍按各自角色走，不会被吞成 fact。标准命名（无 `--loose`）行为不变。

### 17.3 2.0.2：装配层的六处「装错东西」

前一组是「指标算错」，这一组是「内容装错」——都在同一台真实库上量出来的：

1. **agent 记忆目录被当正文检索**：`.workbuddy/memory`、`.shared/memory` 这类目录里放的是
   agent 的工作日志（当天流水、项目索引卡），`DATA_DIRS` 里没有它们，于是被判成 `other`、
   权重 1.0，跟分册正文平起平坐。实测「培养表怎么更新」这个任务，P4 装进来的 997 tok
   全是 11-08 的知识库改造日志，占掉 47% 预算。而且 `.workbuddy/memory` 常是
   `.shared/memory` 的软链，同一份内容被算两遍、命中分翻倍，更容易挤进名额。
   现在 `.workbuddy` / `.shared` / `.codex` / `.qoder` / `.trae` / `.claude` / `.cursor`
   等 15 个客户端目录统一排除。

2. **父节靠子节刷分**：markdown 的 section 是「到下一个同级标题为止」，父节的 body 天然
   包含所有子节。按 body 算命中数，父节必 ≥ 子节，永远排前面，装进来的却是整棵子树；
   只有标题的容器节（`## 结论速查`）也能靠标题命中占名额。现在打分与空壳判定只用
   **本节自有正文**（标题到下一个任意级标题），输出仍是整节，信息不缩水。
   例外：子树里含**作废事实**的容器节保留——「本节省略了 N 条」只有它能表达。

3. **文件导语抢名额**：第一个 h1 节装的是「本文件讲什么」和适用版本，整份分册的主题词
   都在里面，按命中个数排序必进前三。现在对 h1 做**条件降权**：子节关键词集合覆盖 h1
   **且** h1 自有正文逐句比对下来没有子节没提的内容时才丢；h1 里有子节没有的内容——
   否定结论、「先看这里」的入口——就保留。逐句比对的两个边界：任务相关的短句
   （`只读`）不按字符数忽略；`适用版本 2.0，生产环境禁止写入` 只剥导语那半，
   禁令那半照常参与判断。无脑跳过会把这类信息一起丢掉。
   改完这一条，「机械冲撞伤害公式」才装得进 G-001，而不是整份 `10_游戏事实.md` 的导语。

4. **P0 假缺口**：先查 `dashboard.constraints`，没有就记缺口，然后才退到 `AGENTS.md` 兜底；
   兜底成功了缺口也没撤回。结果每个任务都带一条「缺少 kb:id: dashboard.constraints」，
   把人引去补一个并不缺的 id。现在三级兜底走完才判缺口，`kb-check` 同口径（能从 AGENTS
   兜住就报 OK，不再边注入边 WARN）。

5. **`other` 跟分册正文同权重**：`other` 装的是 `AGENTS.md`、一次性发布稿、检索记录、
   覆盖率矩阵这类东西——不在知识库结构里。真实库那份 `检索记录_….md` 有 62 KB，
   任务问什么都可能从里面命中几个词，凭体积压过分册条目，P4 的 3 个名额就被它抢走。
   现在权重阶梯是：结构内正文 1.0 / 流水与分片 0.4 / 归档 0.3 / 其余 0.5。

6. **小分册被上一刀误伤**：第 2 条「父节只按自有正文打分」上线后，`1–2 KB` 的小分册
   整条线会消失——`# 02 · 岗位方向与匹配` 只是个名字，三个 h2 各自只出现一次「方向」，
   父节是空壳、子节又够不上「≥2 个关键词」，两边都不参赛。实测求职库「岗位方向怎么选」
   从 2 块变 1 块。现在容器节做兜底：**子树里一个够格的节都没有**、且整节 ≤ 600 tok
   时才整节参赛。大分册（60 KB）的 h1 依然进不来——装整棵子树太贵。
   600 这个数来自实测：1–2 KB 的中文分册整节约 350–450 tok，装整节比拆成子节更划算。

还有一个连带修正：block 的 `source` 只存文件名，P4 比较的是相对路径，子目录里的同名文件
会被判成「没用过」而重复装载。现在按 `role_files` 建名字→相对路径映射后对齐。

### 17.4 2.0.2：判定层的五处「判据本身不对」

前两组是「指标算错」「内容装错」，这一组更靠底层——判据把「看起来像」当成了「是」。
每一处都先在三个真实库（求职 / 路由器和网络 / FFRS）上量到误判，再改判据。

1. **P0 有两条实现，结论能相反**：`kb-context` 看正文有没有字，`kb-check` 只看有没有
   「硬约束」这个标题。于是

   ```
   ## 硬约束
   ```

   （只有标题、正文空）在 check 里报 OK、在 context 里报缺口。同一个库一边说
   「约束正常注入」、一边说「没有约束」，读者只会去补一个并不缺的东西。
   现在三级兜底（`dashboard.constraints` → `dashboard.safety` → `AGENTS.md` 的
   「硬约束」段）收进 `lib/constraints.py`，两个脚本都只调 `resolve()`：
   - 路径安全：入口文件是符号链接 / Junction 时核对真实路径，越界就拒绝注入并说明原因；
   - 内容有效：只认「去掉注释、标题、分隔线、表格分隔行、列表符号之后仍有正文」；
     `[填]` / `TODO` / `TBD` / `待补` 一律算没填；
   - 兜底链上任何一级「有 ID 但空」都写进结论，不静默当作已配好。

2. **代码围栏里的东西被当成库内容**：文档里贴的示例流水、示例 `## 硬约束`、示例表格
   都在 ``` 里。此前「最近记录」按行首判断，示例条目全被计数，阈值当场失效；
   事实占位判定同理。现在 `md.scan_fences()` 是唯一入口：``` 与 ~~~ 都支持、
   围栏长度要匹配、带走语言标记、CRLF / LF 同样处理；摘要条目、事实填充判定、
   章节解析三处共用它，围栏内行一律不算。

3. **`--loose` 把散文当事实分册**：`20_会议记录.md` / `40_临时测试.md` 编号是两位数，
   就按 1.0 权重跟真分册抢 P4 名额、还被 P2 当成工作线去问「本线当前值」——那里根本
   没有事实条目。现在判据换成**内容**：有 `fact.*` 章节 / ≥2 条 K-G 定义 / ≥2 条项目
   自有编号条目才算 `structured`；其余是 `candidate`——P2 不装、P4 按 0.5 权重装，
   缺口写「候选分册补入 N 节，当线索读」。判据里没有任何具体项目的文件名。

4. **P4 补到一节就当成「这条线已加载」**：P2 按线名命中，任务里没线名就空、报一条缺口；
   P4 随后按内容补进该线的一两节，那条缺口撤回——读者于是以为整条工作线都进来了。
   现在撤缺口之后必须补一条边界说明：`P4 只补入 N 个事实节（…）：节级补充，不等于该
   工作线已完整加载`。预算挤掉时另说一句（`已选中但总预算装不下` / `超过 P4 预算占比`），
   不能把「命中但没装下」说成「已补入」。JSON 同步给出 `p4_facts` 与 `p4_candidates`
   两个字段，消费方不必去猜哪条是核实过的事实。

5. **两处 `skipTest` 在掩盖断言**：「本夹具下 P4 没补到事实节，另有用例覆盖」——
   夹具一旦漂移，用例永远绿；改成先断言「必须补到」，漂移就红。
   另一处「这个夹具没有同时产出基线命中与证据指针」改成「夹具必须产出重复 section_id」。
   保留的 skip 只剩环境限制（Windows 无 symlink 权限、本机装了 tiktoken），
   都写明原因，且不影响被测逻辑。

6. **同一段正文装了两遍**：问「K-02 核实过了吗」时，P3 按 ID 给出定义行，
   P3 的基线命中又把同一行装了一次——两块内容完全相同，`deduped` 之前一个都没有，
   等于白花一份预算还让读者以为有两处证据。现在 `add()` 做内容级去重（sha256 前 12 位，
   先装先得，P0 硬约束不受影响），被跳过的块记进 `deduped` 并写明 `kept_in`——
   去重不静默，事后能查到「本来还有一块」。
   benchmark 也补了重复装载指标（`duplicates.exact / cross / split_sections`，
   按 `text_sha` 判，不是只看 section_id）：同节按用途拆两块（基线命中 + 证据指针）
   是设计，不算重复；真正要抓的是「同位置同内容」和「异位同文」。
   合成夹具 C 均值 456 → 440，正是任务 4/6 各少装一行。

7. **一条事实的分册被当成散文，「--line」成了空操作**：刚建线只核了一个值的分册
   （`## G-001 当前 MTU`）过不了「≥2 条」的门槛，被判候选、P4 只给 0.5，缺口还说
   「只有编号、没有事实条目」——它明明有一条。更糟的是显式 `--line 数据与解包`：
   真实库那份 20 KB 分册没有 `fact.*` 章节 ID，于是**一块都不给**，只回一句
   「该线没有可加载的 fact.* 事节」。
   改：标题位置就是事实 ID 时**一条即算结构化**（列表项/表格行这类弱证据仍要 ≥2 条）；
   显式 `--line` 在该线没有 `fact.current` 时取它自己的事实节，最多 3 节、按关键词排序。
   真实库复测：`--line 数据与解包` 从 0 块 → D-011/D-002/D-004 三节（预算 3000 用 2809），
   预算降到 400 时如实报「未加载（预算不足）」。
   只在**显式 `--line`** 时兜底：任务里顺带提到两个线名就整节倒进去，会把
   `baseline.chains` 这类跨线结论挤出预算（这条在真实库 benchmark 上先踩到过一次）。
   顺带把容器兜底的 600 token 判据改用**同一个 TokenCounter**：原先固定用 heuristic，
   与 `--tokenizer cl100k_base` 下的总预算不是一套单位。

### 17.5 2.0.3：复审补丁——四处「提前返回」和「只看一半」

2.0.2 合并后复审又量出四处「规则写了没生效」，形状都一样：某一层提前 return，
或者判据只检查了必要条件。

1. **P0 只兜一级**：`dashboard.constraints` 存在但正文是 `[填]` 时函数直接 return，
   下面有效的 `dashboard.safety` 永远读不到，最后却报「缺少硬约束」。改成逐级尝试、
   每级原因都记下来；两级都无效才回退 `AGENTS.md`，缺口诊断同时报出两个 ID。
   路径越界、空正文、占位符的判定不变，`kb-check` 与 `kb-context` 仍共用 `resolve()`。
2. **h1 只比关键词**：父节正文更长，几乎必然把子节关键词全命中，「关键词是子集」
   于是成立，h1 连同「参数 YY 必须禁用」一起被删。判据加一层正文逐句比对：h1
   自有正文里只要有一句在子节文本里找不到就保留（文件导语句不计入独有内容）。
3. **短句被长度吞掉**：`len(s) < 4` 无条件跳过，「只读」这类两字操作约束正好被跳。
   改成看任务相关性——短句里出现本 h1 命中的任务词才算独有正文；`（无）`、`待补`
   这类无关短句仍不参与判断，正常导语照旧去重。
4. **导语与事实混在一句**：整句含「适用版本」就跳过，`适用版本 2.0，生产环境禁止写入`
   的后半句禁令一起消失。现在含导语提示词时按逗号拆开、只丢导语片段；顿号不拆——
   `本文件讲 A、B、C` 是目录，拆开就成了三条假独有事实。纯版本说明仍正常去重。

用例 333 → 341（constraints +2、context_edges +6），协议仍是 v2，现有库不需要迁移。

### 17.6 2.0.4：英文技能 + 双语模板 + 实测 token 基准

这一版**不动协议**，只动「怎么说」和「怎么量」。`kb:schema: 2`、文档 ID、保留文件名、
章节 ID、命令参数、JSON schema、迁移行为全部保持原样；现有中文库不需要迁移，读取路径不变。

1. **`SKILL.md` 改成英文、9 个编号章节**：用途与适用边界 / 架构与核心规则 / 快速开始与恢复 /
   上下文路由 / 安全写入规则 / 交接与校验 / 参考手册加载指引 / 反模式与安全 / 文件索引。
   原来的 14 个零散章节合并成这 9 个，同一件事只在一处说，其余处交叉引用。开头明确写：
   **指令语言与知识库语言互相独立**。
2. **只发一个技能，不发两个。** 优化后的中文文本不随包发布：它在
   `tests/token_language/sample_b/SKILL.zh-CN.md`，作为 token 基准的 B 样本，字节由 SHA256 断言钉住。
   有测试断言 `tests/` 之外只有 `SKILL.md` 一份技能文件。
3. **`references/*.md` 转英文，中文原稿 `git mv` 到 `references/*.zh-CN.md` 且**不改一字**。
   它们是可选读物，与英文版共用同一套协议 ID、命令、JSON 形状与退出码，不是第二个技能。
   `references/protocol.md` 故意留中文——它是 v1 设计史，不是操作手册。
4. **`assets/en/` 12 份英文模板**：占位符（`{{PROJECT}}` / `{{SCHEMA}}` / `{{SHARD_TABLE}}` …）
   与 `kb:id` 集合与中文版完全相同，协议状态词（`有效` / `待核` / `已作废`）保持字面量，
   因为那是协议数据不是散文。
5. **`kb-init.py --lang {zh,en}`**：选模板集，同时本地化生成的表头、路由分隔符（`; ` / `；`）、
   初始状态、分片章节、`CLAUDE.md`/`GEMINI.md` 指针和自检脚本占位。默认 `zh`，
   所以既有调用行为一字不变。
6. **`tokens.py` 增加 `deepseek_v4`**（官方离线 `tokenizer.json`，精确，函数内 `import tokenizers`）
   与 **`deepseek_estimate`**（官方比例 0.3 / 0.6，明确标 `estimate`）。每个计数器还带一份
   **词表指纹**——来源、词表文件名、词表 SHA256、库版本，且**不含任何个人路径**；
   `is_exact()` 现在同时认 `tiktoken:` 与 `tokenizers:` 两种精确前缀。词表缺失即
   `TokenizerError`（命令行退出 2），除 `--allow-tokenizer-fallback` 外不静默降级。
7. **`tests/deps_check.py` 改成走完整 AST**：不再只看模块顶层，可选依赖必须同时满足
   「在函数内」和「包在 try/except 中」。`tokenizers` 正式列入可选依赖清单——代码从
   DeepSeek 计数器加入那天起就在用它，而文档只说 `tiktoken`，这次把声明补齐。
   `tests/test_deps_check.py`（11 例）测检查器本身，新增第三方依赖会被先发现。
8. **`tests/token_language/`**：A/B/C 实测、v2.0.3 冻结基线（19 份文件 + `MANIFEST.json`，
   带 bytes / chars / sha256 / 三套词表 token 数，**三套精确词表都复现**）、19 条规则表
   （只针对发布的那份英文技能）、标识符与 JSON 契约对照实现、模板一致性、
   token 目标、不静默降级、跨语言场景（中文库跑英文技能、英文库跑英文任务）、基线清单的
   字节/哈希/token 复现，共 40 例。数字化的 token 门槛需要精确词表，CI 不装可选依赖，
   所以那 7 例会带原因 skip（每条点名缺哪个编码器）；其余用例在 CI 照常跑，
   一条命令可本地复现全部：`python tests/token_language/run_token_benchmark.py --all`。

**没变的**：协议版本、文档 ID、保留文件名、章节 ID、命令参数、JSON schema、迁移行为、
安全/并发/事务/哈希/恢复规则。没有为了省 token 删掉任何一条安全规则——只压缩措辞，
不删条目；`--dry-run`、`--plan`、锁、journal、二次哈希、回滚全部保留。

---

## 18. 测试与验证状态（诚实版）

写清楚「测过什么、没测什么」，比多写几个 PASS 有用。

### 18.1 本地测试

| 项 | 结果 |
|---|---|
| `python -m unittest discover -s tests` | **392 例，OK（1 skip）**——341 例既有 + 40 例 `token_language` + 11 例 `test_deps_check`；本机唯一的 skip 是一条既有降级用例，它只在**没装** `tiktoken` 时才适用 |
| 同上，但**不装任何可选编码器**（CI 就是这种环境） | 392 例，**7 skip**，0 失败：数字化的 token 用例必须有精确词表才能算。每条 skip 都在原因里点名缺哪个词表（`cl100k_base` / `o200k_base` / `deepseek_v4`）；不依赖编码器的性质——布局、规则、标识符、JSON 契约、模板、跨语言场景、降级退出码——照常跑 |
| 运行环境 | Windows 11（10.0.26200）/ Python 3.13（本机 `G:\Python313`） |
| `python tests/smoke.py` | 全部通过：建库 → 读写 → 迁移 → 体检 → 路由 → 评测，含冲突与坏路径的退出码断言 |
| `python tests/deps_check.py` | OK：`scripts/` 只用标准库 + 本地 `lib`；`tiktoken` 与 `tokenizers` 是两个已声明的可选例外，都在函数内且包 `try/except`。`tests/test_deps_check.py`（11 例）测检查器本身 |
| `python tests/token_language/run_token_benchmark.py --all` | 产出 §12.1 的表；`deepseek_v4` 需要离线词表，否则退出 2 |

### 18.2 CI（六个环境）

`Ubuntu × {3.10, 3.12, 3.13}` + `Windows × {3.10, 3.12, 3.13}`，见 `.github/workflows/test.yml`。
每个环境跑：环境信息 → 单元测试（`-v`）→ 端到端冒烟 → 依赖检查。

2.0.3 那一轮（run `43451488874`，2026-11-13）六环境全绿、341 例无 skip。
2.0.4 以 **PR 的 CI 状态**为准，不在本文件里自述：当前 HEAD 的运行结果记在
PR [#5](https://github.com/jmwangde3/handoff-kb/pull/5) 上。每个 job 跑 392 例，
那 7 条 skip 是数字化的 token 用例——它们需要精确词表，而 CI 故意不装可选依赖。
**它们不是在掩盖失败**：数字本身一条命令可本地复现（§12.1）。

> 已知噪音：GitHub 提示 `actions/checkout@v4` 与 `setup-python@v5` 的 Node 20 弃用，属行动升级提醒，不影响结果。

### 18.3 客户端 Hook

- **已验证**：配置结构符合两家官方格式、预览零写入、SHA 变更即放弃、多文件回滚（含原子写与
  第三方改动冲突）、`SessionStart` 五种来源都被覆盖、`PreCompact` 按两家协议分别输出
  （Claude 纯文本 / Codex `systemMessage`，都不带 `decision` / `continue`）——均为模拟事件测试。
- **未验证**：真实客户端启动进程时的实际注入效果。测试只到「配置结构与事件映射」这一层，
  没有起 Claude Code / Codex 真跑一遍。`references/hooks.zh-CN.md` 里标了同样的边界。

### 18.4 Benchmark 口径

- 三个 token 数（A/B/C）用**同一个** `TokenCounter` 实例；默认是 `heuristic` 估算
  （CJK 1 字 ≈ 1 token，其余 4 字符 ≈ 1 token），**不是** API 账单。
- 要真实计数就装 `tiktoken` 并显式 `--tokenizer cl100k_base`；装不上会退出 2，不会静默降级。
- A 含子目录全部可检索文本（排除资料目录与 >2 MB 文件），所以真实库的 A 会非常大；
  降幅百分比随库的体积分布变化，**不要跨库比较**。
- 双语基准的 A **冻结**在 `tests/token_language/baseline/v2.0.3/` 并带 `MANIFEST.json`
  （19 份文件的 bytes / chars / sha256 / token 数），工作区变化不会让对比漂移。

### 18.5 已知残余风险

| 风险 | 现状 | 影响 |
|---|---|---|
| 多文件恢复不是数据库事务 | 逐文件写 + 二次 SHA + 失败保留现场；没有 WAL / 两阶段提交 | 进程在两次写之间被 kill，可能留下「部分已写」的现场；`recover` 会报告并要求人工确认，不会假装成功 |
| 外部编辑器绕过锁 | 锁只在 `kb-write` 内部生效 | VS Code / Typora 直接保存不会被拦；靠写回前的 `sha256` 比对发现冲突 |
| 真实大库未压测 | 只读跑过 FFRS（正文 47 份 / 0.6 MB，归档 795 份 / 5.6 MB，物理总量约 36 GB 含素材） | 那是「文件多」不是「单文件大」；>10 MB 单文件或 >500 份参与检索的正文没测过，`kb-context` 仍是全库扫描，可能慢 |
| 跨进程竞态 | 锁 + 二次校验，非 CAS | 两个 `kb-write` 同时写同一文件，极端时序下可能都要重试；不会静默覆盖 |
| 客户端启动未端到端验证 | 见 §18.3 | Hook 装了但没生效时，只能靠「没有注入上下文」这个现象发现 |
| P4 的「在问历史」靠关键词猜 | `历史 / 以前 / 作废 / 沿革…` 命中才带回作废内容 | 换一种说法（「当初」「回滚前」）可能不触发；给人用的显式开关是 `--include-superseded`，模型侧只能看缺口提示 |
| 作废内容按「定义行」置空 | 只认 `lib/facts.py` 解析出的定义位 | 章节里用自然语言复述旧值（没写成定义位）不会被置空；要靠写库时把旧值标成 `status: deprecated` |
| token 数字依赖词表 | cl100k 27.9% / o200k 15.2% / deepseek_v4 9.2% | 只报一个百分比而不说词表就是误导；报告里每次都带词表名与词表 SHA256 |
| 英文模板是新东西 | 一致性用例比对文件集、占位符与 `kb:id`，另有一次真实 `kb-init --lang en` 跑通 `kb-check` | 还没有用它们养过一个长期英文库，「半年后还好读」未经验证 |
| 英文技能管中文库 | **命令行**路径有测试（中文夹具上跑 init / check / context） | **agent** 在真实 Codex / Claude Code 会话里按英文指令操作中文库，没跑过；清单一节明确标为未验证 |

---

## License

MIT，见 `LICENSE`。
