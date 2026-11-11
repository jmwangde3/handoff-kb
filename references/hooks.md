# 客户端 Hook（可选，默认不安装）

> 先读这句：**事件名、JSON 结构、stdout/stderr 语义与退出码含义，各客户端不同，且会随版本变化。**
> 本仓库只承诺「生成项目级配置 + 只读运行时」，不承诺与某个客户端版本的字节级兼容；
> 安装前用 `--plan` 看清楚，必要时对照该客户端当前官方文档改一行。

## 1. 设计原则

1. **默认关闭**：不装就完全没影响。
2. **预览优先**：不写 `--write` 一律零写入；只打印「新增 / 移除 / 保留 / SHA 前后」。
3. **只读**：`run` 不写文档、不 `git commit`、不改配置、不联网、不调 LLM。
4. **不阻断**：`run` 任何异常都吞掉并退出 0；**不使用** `decision: block`，不阻止压缩或结束任务。
5. **项目级**：只写 `<target>/.claude/settings.json` 或 `<target>/.codex/…`，绝不改全局。
6. **可撤销**：`uninstall` 只删自己写入的条目（命令里含 `kb-hooks.py`），保留别人的 Hook；
   JSON 里被清空的事件表、TOML 里被清空的 `[[hooks.X]]` 表头一起收掉，不留空壳。

## 2. 事件行为与输出结构

| 客户端 | 事件 | 行为 | stdout |
|---|---|---|---|
| Claude / Codex | `SessionStart` | 跑 `kb-context.py --mode handoff --budget 1200` | `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "<上下文>"}}` |
| Claude | `PreCompact` | 提醒收尾（先 `kb-handoff.py check`、再 `kb-write.py` 写回） | **纯文本**（Claude 会把它作为压缩摘要的指令） |
| Codex | `PreCompact` | 同上 | `{"systemMessage": "…"}`（Codex 的共享字段） |
| Claude / Codex | `Stop` | 跑 `kb-handoff.py check`；有不完整项才说话 | 有问题→`{"systemMessage": "…"}`；无问题→`{}` |
| 仅 Claude | `SessionEnd` | 空响应（占位，明确不做动作） | `{}` |

- 除 `Stop` 外不主动「教育」模型；`Stop` 只在交接真缺内容时提示一次，**不阻断**结束。
- 未知事件 / 目标不是交接库 / 项目根不可用 → 输出空对象、退出 0，会话不受影响。
- 两家的 `SessionStart` 来源都是 `startup|resume|clear|compact|fork`，生成器对两家都写全五个
  （2.0.1 漏了 `clear`，导致「清空会话后重新开始」拿不到接手上下文；2.0.1-hotfix 补上）。
- 触发来源不影响运行时行为：五种来源都注入同一份按预算裁过的上下文。
- **`PreCompact` 的输出两家不通用**：Claude Code 明确「discards a PreCompact hook's
  `systemMessage` and `continue` fields」，非阻断退出 0 时 **stdout 纯文本**才是压缩摘要的指令；
  Codex 的 `PreCompact` 认共享字段 `systemMessage`，纯文本 stdout 被忽略，也没有
  `customInstructions`。所以同一句提醒按客户端分别输出，不是一份 JSON 打天下
  （2.0.1-hotfix 修：此前对 Claude 也发 `systemMessage`，等于什么都没说）。

## 2.1 官方依据（2026-11 核对）

| 客户端 | 文档 | 本仓库依赖的事实 |
|---|---|---|
| Codex | `developers.openai.com/codex/hooks`（现跳 `learn.chatgpt.com/docs/hooks`） | 三级结构 `事件 → [{matcher, hooks:[{type,command}]}]`；`SessionStart` 的 `source` 五值；`hookSpecificOutput.additionalContext`；`PreCompact` 存在且认共享字段 `systemMessage`（matcher 是 `trigger`：`manual` / `auto`）；纯文本 stdout 在 `PreCompact` 被忽略；无 `customInstructions`；`additionalContext` 默认约 2500 token 上限（超限写临时文件、只给头尾预览） |
| Claude Code | `code.claude.com/docs/en/hooks` | 同三级结构；项目级 `.claude/settings.json` 生效但受 workspace trust 约束；`SessionStart` 的 matcher 五值；`PreCompact` 的 matcher 是 `manual` / `auto`；**`PreCompact` 丢弃 `systemMessage` 与 `continue`**，非阻断时 stdout 纯文本 = 压缩摘要指令（上限 10,000 字符）；`additionalContext` 上限约 10,000 字符 |

`--budget 1200` 是刻意压在两家的注入上限之内的：宁可少给一点，也不要被客户端截成头尾预览。

## 3. 安装位置与结构

| 客户端 | 文件 | 结构 |
|---|---|---|
| Claude Code | `.claude/settings.json` | `hooks.<Event>[{"matcher": "", "hooks": [{"type": "command", "command": "…"}]}]` |
| Codex | `.codex/hooks.json` | 同上**三级结构** `{matcher, hooks:[{type, command}]}`（2.0.1-hotfix 修正：此前写成扁平 `{type, command}`，官方格式不认） |
| Codex | `.codex/hooks.snippet.toml.txt` | 供手工并入 `config.toml` 的 `[[hooks.<Event>]]` 片段，写盘前用 `tomllib` 自检 |

生成的命令用**绝对路径**（配置是按机器生成的，`$KB` 之类变量不会展开）：

```bash
python "C:/Users/<你>/.skills-manager/skills/handoff-kb/scripts/kb-hooks.py" run \
  --client claude --event SessionStart --target "C:/proj" [--loose]
```

`--loose` 会原样出现在生成的命令里，自有命名项目（`60_进度.md`）必须带上。

## 4. 运行时如何定位项目根

1. 从 stdin 读事件 JSON（客户端会把 `cwd` 放进去）。
2. `--target` 是**绝对路径**（安装时写死）：与事件 `cwd` 交叉校验，两者互相包含才算同一个库；
   不在范围内就**不注入**，并说明原因——避免在 A 项目里注入 B 项目的上下文。
3. `--target .`（旧配置）：只信事件 `cwd`，且必须像个交接库（有 `00`/`05`）。
4. stdin 用**先探测再读**（Windows `PeekNamedPipe` / POSIX `select`）：没有输入时立刻返回，
   不再像早先那样 `sys.stdin.read()` 挂到超时。

## 5. 用法

```bash
KB="$HOME/.skills-manager/skills/handoff-kb"
py "$KB/scripts/kb-hooks.py" install   --client claude --target .            # 预览（默认）
py "$KB/scripts/kb-hooks.py" install   --client claude --target . --write     # 写盘
py "$KB/scripts/kb-hooks.py" uninstall --client claude --target . --write
py "$KB/scripts/kb-hooks.py" run --client claude --event SessionStart --target . < event.json
```

- `--plan` 与不带 `--write` 都只打印，不落盘。
- 写盘前**双重预检**：`original_exists` + `sha_before` 都要与预览时一致。
  只看哈希分不清「本来不存在」和「已存在但内容相同」，于是预览之后新建的用户文件
  会被当成自己该建的文件覆盖掉——现在这种情形报 CONFLICT，不写。
- **多文件安装是一个整体**：先对全部目标做预检，全部通过才逐个写；中途失败就把本轮
  已写的文件恢复到预览前内容；若回滚时发现某文件被第三方改过，**保留现场**并报冲突，
  不强行覆盖。（这是「预检 + 逐写 + 尽力回滚」，不是跨文件原子事务。）
- 回滚本身也走**原子字节写**（临时文件 → `os.replace` → fsync 目录）：原来用
  `write_bytes()` 直接盖，写到一半崩掉会把「本来完好的旧配置」变成半截文件。
- 目标目录若是符号链接/Junction 指向库外，直接拒绝写入（`ERR … 目录不可用`）。
- 现有 JSON 不合法时**拒绝改写**（退出码 2），不猜测、不吞掉你的配置。
- 重复 `install` 幂等（同一事件只保留一条本工具的命令）；`uninstall` 幂等。

## 6. 已知不确定点（按需核对官方文档）

- Claude Code 的 `Stop` / `SessionEnd` 是否支持阻断、stdout 是否作为上下文注入，版本间有差异。
- Codex 的 `hooks.json` 与 `config.toml` 两种来源**只启用一种**，别同时开；键名以其文档为准。
- **信任机制**：非托管 Hook 需审阅并按当前 hash 信任；改配置后重新进入待审阅状态，未信任前跳过。
  没被信任不是故障，降级为手动跑 CLI，功能不缺。
- 上述文档结论只覆盖到 2026-11；客户端升级后以官方文档为准，本仓库不承诺字节级兼容。

> 本仓库做过的验证边界：**结构测试通过、模拟事件通过、真实客户端启动未验证。**
> 六环境 CI 只跑 Python 单测与冒烟，不启动 Claude/Codex 客户端。

## 7. 出问题怎么退

1. `uninstall --write` 撤掉条目；
2. 手动删 `.claude/settings.json` 里含 `kb-hooks.py` 的项；
3. Hook 报错不影响会话（`run` 永远 0），需要诊断就直接跑同一条 `run` 命令看输出。
