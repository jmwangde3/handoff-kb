#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-hooks.py — 客户端 Hook 适配（默认不安装，不联网，不改全局配置）

只做"只读检查 + 精简上下文注入 + 交接提醒"，不自动总结、不自动提交、不阻止压缩。
各客户端事件名与退出码语义不同，这里只生成**项目级**配置，安装前用 --plan 复核：

  py kb-hooks.py install --client claude --target . --plan
  py kb-hooks.py install --client claude --target . --write
  py kb-hooks.py uninstall --client claude --target . --write
  py kb-hooks.py run --client codex --event SessionStart --target .

写入位置：
  claude → .claude/settings.json      （hooks 结构，按官方 settings 文档）
  codex  → .codex/hooks.json + .codex/hooks.snippet.toml.txt（需手工并入 config.toml）

`run` 永远退出 0：Hook 出错不能破坏正常会话。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import scope  # noqa: E402

MARK = "kb-hooks.py"
EVENTS = ["SessionStart", "PreCompact", "PostCompact", "Stop", "SessionEnd"]
CLIENT_EVENTS = {
    # 各客户端实际支持的事件名以其当前官方文档为准；这里只映射我们确认用到的
    "claude": EVENTS,
    "codex": ["SessionStart", "PreCompact", "Stop"],
}


def hook_command(client: str, event: str) -> str:
    """用绝对路径生成命令：Hook 配置是按机器生成的，不吃 $KB 这类未展开变量。"""
    script = Path(__file__).resolve().as_posix()
    return ('python "%s" run --client %s --event %s --target .'
            % (script, client, event))


def build_config(client: str):
    evs = CLIENT_EVENTS[client]
    if client == "claude":
        return {
            "hooks": {
                ev: [{"hooks": [{"type": "command",
                                 "command": hook_command(client, ev)}]}]
                for ev in evs
            }
        }
    return {
        "_comment": "handoff-kb 生成的描述文件；请按 Codex 当前文档把 hooks 段并入 config.toml",
        "hooks": {ev: [{"command": hook_command(client, ev)}] for ev in evs},
    }


def toml_snippet(client: str) -> str:
    lines = ["# handoff-kb hooks（按需并入 config.toml；事件名/语义以客户端文档为准）"]
    for ev in CLIENT_EVENTS[client]:
        lines.append('[[hooks.%s]]' % ev)
        lines.append('command = "%s"' % hook_command(client, ev).replace('"', '\\"'))
        lines.append('')
    return "\n".join(lines)


def target_paths(client: str, root: Path):
    if client == "claude":
        return [(root / ".claude" / "settings.json", "json")]
    return [(root / ".codex" / "hooks.json", "json"),
            (root / ".codex" / "hooks.snippet.toml.txt", "toml")]


def merge_json(path: Path, payload: dict, client: str):
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            raise SystemExit("ERR: %s 不是合法 JSON，拒绝改写" % path)
    hooks = data.setdefault("hooks", {})
    for ev, entries in payload.get("hooks", {}).items():
        cur = hooks.get(ev, [])
        cur = [h for h in cur if MARK not in json.dumps(h, ensure_ascii=False)]
        cur.extend(entries)
        hooks[ev] = cur
    data["hooks"] = hooks
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def strip_json(path: Path):
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    changed = False
    hooks = data.get("hooks", {})
    for ev in list(hooks):
        kept = [h for h in hooks[ev] if MARK not in json.dumps(h, ensure_ascii=False)]
        if len(kept) != len(hooks[ev]):
            changed = True
        if kept:
            hooks[ev] = kept
        else:
            hooks.pop(ev, None)
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def cmd_install(args, root: Path) -> int:
    client = args.client
    payload = build_config(client)
    if args.plan or not args.write:
        print("== 计划：%s → %s" % (client, root))
        for p, kind in target_paths(client, root):
            action = "合并" if p.exists() else "创建"
            print("  %s %s" % (action, p.relative_to(root).as_posix()))
        print("\n-- 将写入的内容（%s）--" % client)
        print(toml_snippet(client) if client == "codex" else
              json.dumps(payload, ensure_ascii=False, indent=2))
        print("\n-- 默认不写盘；确认后加 --write。不修改任何全局配置。")
        return 0 if args.plan or args.write else 2

    for p, kind in target_paths(client, root):
        if kind == "json":
            merge_json(p, payload, client)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(toml_snippet(client), encoding="utf-8")
        print("~ %s" % p.relative_to(root).as_posix())
    print("-- 已写入项目级 Hook 配置（事件：%s）" % ", ".join(CLIENT_EVENTS[client]))
    return 0


def cmd_uninstall(args, root: Path) -> int:
    changed = []
    for p, kind in target_paths(args.client, root):
        if kind == "json" and strip_json(p):
            changed.append(p)
        elif kind == "toml" and p.is_file():
            p.unlink()
            changed.append(p)
    if args.plan or not args.write:
        print("== 计划：从 %s 移除 handoff-kb hooks（%d 个文件受影响）"
              % (root, len(changed)))
        return 0
    for p in changed:
        print("~ %s" % p.relative_to(root).as_posix())
    print("-- 卸载完成（幂等，不影响其它 Hook）")
    return 0


def cmd_run(args, root: Path) -> int:
    """只读：输出精简上下文 / 提醒；任何异常都吞掉并退出 0。"""
    try:
        event = args.event
        if event == "SessionStart":
            out = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("kb-context.py")),
                 "--target", str(root), "--mode", "handoff",
                 "--budget", str(args.budget), "--format", "markdown"],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            print(out.stdout if out.returncode in (0, 1) else
                  "-- handoff-kb: 交接库为空或不可读，跑 kb-check.py 看看")
        elif event == "PreCompact":
            print("-- handoff-kb: 压缩前先收尾 —— py kb-handoff.py check --target .")
            print("   用 kb-write.py 写回 05/06，别把未保存状态留在对话里。")
        elif event == "PostCompact":
            print("-- handoff-kb: 压缩后继续时读 05 的 dashboard.current / dashboard.next，"
                  "历史细节按需 kb-search。")
        elif event == "Stop":
            chk = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("kb-handoff.py")),
                 "check", "--target", str(root)],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            if chk.returncode != 0:
                print("-- handoff-kb: 本任务涉及文档改动但交接不完整（见 kb-handoff.py check）。",
                      file=sys.stderr)
        elif event == "SessionEnd":
            chk = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("kb-check.py")),
                 "--target", str(root), "--json"],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            try:
                data = json.loads(chk.stdout)
                c = data.get("counts", {})
                print("-- handoff-kb: 退出前只读体检 OK %s / WARN %s / ERR %s"
                      % (c.get("OK"), c.get("WARN"), c.get("ERR")), file=sys.stderr)
            except Exception:
                pass
        return 0
    except Exception as exc:  # Hook 绝不破坏会话
        print("-- handoff-kb hook 降级：%s" % exc, file=sys.stderr)
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="handoff-kb Hook 适配（默认不安装）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("install", "uninstall"):
        p = sub.add_parser(name)
        p.add_argument("--client", choices=["claude", "codex"], required=True)
        p.add_argument("--target", default=".")
        p.add_argument("--plan", action="store_true")
        p.add_argument("--write", action="store_true", help="实际写盘（默认只打印计划）")

    r = sub.add_parser("run", help="Hook 运行时入口（只读，永远退出 0）")
    r.add_argument("--client", choices=["claude", "codex"], required=True)
    r.add_argument("--event", required=True)
    r.add_argument("--target", default=".")
    r.add_argument("--budget", type=int, default=1200)

    args = ap.parse_args()
    try:
        root = scope.resolve_root(args.target)
    except scope.ScopeError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 0 if args.cmd == "run" else 2

    if args.cmd == "install":
        return cmd_install(args, root)
    if args.cmd == "uninstall":
        return cmd_uninstall(args, root)
    return cmd_run(args, root)


if __name__ == "__main__":
    sys.exit(main())
