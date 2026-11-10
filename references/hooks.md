# 客户端 Hook（可选，默认不安装）

> 先读这句：**事件名、JSON 结构、stdout/stderr 语义与退出码含义，各客户端不同，且会随版本变化。**
> 本仓库只承诺「生成项目级配置 + 只读运行时」，不承诺与某个客户端版本的字节级兼容；
> 安装前用 `--plan` 看清楚，必要时对照该客户端当前官方文档改一行。

## 1. 设计原则

1. **默认关闭**：不装就完全没影响。
2. **只读**：`run` 不写文档、不 `git commit`、不改配置、不联网、不调 LLM。
3. **不阻断**：`run` 任何异常都吞掉并退出 0；不用 Hook 阻止压缩或结束任务。
4. **项目级**：只写 `<target>/.claude/settings.json` 或 `<target>/.codex/…`，绝不改全局。
5. **可撤销**：`uninstall` 只删自己写入的条目（命令里含 `kb-hooks.py`），保留别人的 Hook。

## 2. 事件行为

| 事件 | 行为 | 输出 |
|---|---|---|
| `SessionStart` | 跑 `kb-context.py --mode handoff --budget 1200` | 精简上下文到 stdout |
| `PreCompact` | 提醒收尾 | 一行提示：先 `kb-handoff.py check` + `kb-write.py` 写回 |
| `PostCompact` | 给指针 | 一行提示：读 `dashboard.current` / `dashboard.next` |
| `Stop` | 跑 `kb-handoff.py check` | 不完整时写 stderr 提醒；退出 0，不循环阻断 |
| `SessionEnd` | 跑 `kb-check.py --json` | stderr 打一行 OK/WARN/ERR 计数；不提交 |

## 3. 安装位置

| 客户端 | 文件 | 说明 |
|---|---|---|
| Claude Code | `.claude/settings.json` | `hooks.<Event>[].hooks[{type:"command",command}]` 结构；与已有配置合并 |
| Codex | `.codex/hooks.json` + `.codex/hooks.snippet.toml.txt` | 描述文件 + TOML 片段；**需按 Codex 当前文档并入 `config.toml`** |

生成的命令用**绝对路径**（配置是按机器生成的，`$KB` 之类变量不会展开）：

```bash
python "C:/Users/<你>/.skills-manager/skills/handoff-kb/scripts/kb-hooks.py" run \
  --client claude --event SessionStart --target .
```

## 4. 用法

```bash
KB="$HOME/.skills-manager/skills/handoff-kb"
py "$KB/scripts/kb-hooks.py" install   --client claude --target . --plan    # 只看计划
py "$KB/scripts/kb-hooks.py" install   --client claude --target . --write   # 写盘
py "$KB/scripts/kb-hooks.py" uninstall --client claude --target . --write
py "$KB/scripts/kb-hooks.py" run --client claude --event SessionStart --target .
```

- `--plan` 与不带 `--write` 都只打印，不落盘。
- 重复 `install` 幂等（同一事件只保留一条本文具产生的命令）。
- `uninstall` 幂等；文件里没有本文具的条目时不动任何东西。

## 5. 已知不确定点（按需核对官方文档）

- Claude Code 的 `Stop` / `SessionEnd` 是否支持阻断、stdout 是否作为上下文注入，版本间有差异。
- Codex 的 Hook 配置位置与键名（`hooks` 表 / `[[hooks.Event]]`）以其文档为准；本仓库只给片段。
- 某些客户端对 Hook 有信任/沙箱限制（未信任工作区不执行）。此时降级为手动跑 CLI，功能不缺。

## 6. 出问题怎么退

1. `uninstall --write` 撤掉条目；
2. 手动删 `.claude/settings.json` 里含 `kb-hooks.py` 的项；
3. Hook 报错不影响会话（`run` 永远 0），需要诊断就直接跑同一条 `run` 命令看输出。
