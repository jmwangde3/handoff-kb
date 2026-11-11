#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-hooks.py — 客户端 Hook 适配（默认不安装、默认不写盘、不改全局配置）

设计原则：
  1. **预览零写入**：install / uninstall 默认只打印计划（--plan），只有 --write 才落盘。
  2. **只动自己的条目**：按「精确命令签名」识别 handoff-kb 写入的 hook，
     不做宽泛子串匹配，不碰别人的 hook、未知字段、未知事件。
  3. **写前校验哈希**：读 → 合并/剥离 → 重算 → 校验原文件未被改动 → 原子写。
  4. **不改全局配置**：只写项目级 `.claude/settings.json` / `.codex/hooks.json`。
  5. **run 永远退出 0**：Hook 出错不能破坏会话；输出遵循各客户端事件协议。

写入位置：
  claude → .claude/settings.json   （Claude Code 原生 hooks 结构）
  codex  → .codex/hooks.json       （Codex 三级结构）+ .codex/hooks.snippet.toml.txt（备用片段）

用法：
  py kb-hooks.py install   --client codex --target . --plan
  py kb-hooks.py install   --client codex --target . --write [--loose] [--python PATH]
  py kb-hooks.py uninstall --client codex --target . --plan | --write
  py kb-hooks.py run       --client codex --event SessionStart --target . [--loose]
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import scope  # noqa: E402
from lib.safeio import (SafeIOError, atomic_write, read_text_strict,  # noqa: E402
                        sha256_bytes, sha256_file)

SCRIPT = Path(__file__).resolve()
MARK = "kb-hooks.py"

# 各客户端支持的事件与 matcher（以各自当前官方文档为准；不同客户端语义不通用）
CLIENT_SPEC = {
    "claude": {
        "events": {
            "SessionStart": "startup|resume|clear|compact",
            "PreCompact": None,
            "Stop": None,
            "SessionEnd": None,
        },
        "style": "claude",
    },
    "codex": {
        "events": {
            "SessionStart": "startup|resume|compact|fork",
            "PreCompact": None,
            "Stop": None,
        },
        "style": "codex",
    },
}
EVENTS = list(CLIENT_SPEC["codex"]["events"])


# --------------------------------------------------------------------------- #
# 命令构造与识别
# --------------------------------------------------------------------------- #

def python_exe(explicit: str | None = None) -> str:
    return explicit or sys.executable or "python"


def build_argv(client: str, event: str, root: Path, loose: bool,
               py: str | None = None) -> list[str]:
    argv = [python_exe(py), str(SCRIPT), "run", "--client", client,
            "--event", event, "--target", str(root)]
    if loose:
        argv.append("--loose")
    return argv


def quote_argv(argv: list[str]) -> str:
    """按当前平台规则拼命令串：Windows 用 list2cmdline，POSIX 用 shlex.quote。"""
    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def hook_command(client: str, event: str, root: Path, loose: bool,
                 py: str | None = None) -> str:
    return quote_argv(build_argv(client, event, root, loose, py))


def command_windows(client: str, event: str, root: Path, loose: bool,
                    py: str | None = None) -> str:
    return subprocess.list2cmdline(build_argv(client, event, root, loose, py))


def _norm(cmd: str) -> str:
    return " ".join(str(cmd or "").split())


def is_managed_command(cmd: str) -> bool:
    """精确识别：命令里必须同时出现本脚本路径与 kb-hooks.py 的 run 子命令。"""
    c = _norm(cmd)
    if MARK not in c:
        return False
    return (" run " in c) and ("--client" in c) and ("--event" in c)


def is_managed_group(group: dict) -> bool:
    """Claude / Codex 的「事件组」里只要含我们的 hook 就算受管。"""
    if not isinstance(group, dict):
        return False
    inner = group.get("hooks")
    if isinstance(inner, list):
        return any(isinstance(h, dict) and is_managed_command(h.get("command", ""))
                   for h in inner)
    return is_managed_command(group.get("command", ""))


# --------------------------------------------------------------------------- #
# 纯函数：生成 / 合并 / 剥离
# --------------------------------------------------------------------------- #

def build_payload(client: str, root: Path, loose: bool, py: str | None = None) -> dict:
    spec = CLIENT_SPEC[client]
    hooks = {}
    for ev, matcher in spec["events"].items():
        hook_obj = {"type": "command", "command": hook_command(client, ev, root, loose, py)}
        if matcher:
            group = {"matcher": matcher, "hooks": [hook_obj]}
        else:
            group = {"hooks": [hook_obj]}
        hooks[ev] = [group]
    payload = {"hooks": hooks}
    if client == "codex":
        payload = {"description": "handoff-kb project lifecycle hooks", "hooks": hooks}
    return payload


def merge_payload(data: dict, payload: dict) -> tuple[dict, list]:
    """把 handoff-kb 的事件组并进现有配置；先移除自己的旧条目（幂等升级）。"""
    if not isinstance(data, dict):
        raise SafeIOError("配置文件顶层不是对象，拒绝改写")
    data, _ = strip_payload(data)
    out = dict(data)
    hooks = out.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    else:
        hooks = dict(hooks)
    added = []
    for ev, groups in payload.get("hooks", {}).items():
        cur = hooks.get(ev)
        cur = list(cur) if isinstance(cur, list) else []
        cur.extend(groups)
        hooks[ev] = cur
        added.append(ev)
    out["hooks"] = hooks
    if payload.get("description") and not out.get("description"):
        out["description"] = payload["description"]
    return out, added


def strip_payload(data: dict) -> tuple[dict, list]:
    """纯函数：移除本工具写入的 hook，保留其余一切（含未知字段）。"""
    if not isinstance(data, dict):
        raise SafeIOError("配置文件顶层不是对象，拒绝改写")
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data, []
    out_hooks = {}
    removed = []
    for ev, groups in hooks.items():
        if not isinstance(groups, list):
            out_hooks[ev] = groups
            continue
        kept_groups = []
        for g in groups:
            if not isinstance(g, dict):
                kept_groups.append(g)
                continue
            inner = g.get("hooks")
            if isinstance(inner, list):
                kept_inner = [h for h in inner
                              if not (isinstance(h, dict)
                                      and is_managed_command(h.get("command", "")))]
                if len(kept_inner) != len(inner):
                    removed.append(ev)
                if not kept_inner:
                    continue                     # 整组都是我们的 → 去掉空组
                g2 = dict(g)
                g2["hooks"] = kept_inner
                kept_groups.append(g2)
                continue
            if is_managed_command(g.get("command", "")):
                removed.append(ev)
                continue
            kept_groups.append(g)
        if kept_groups:
            out_hooks[ev] = kept_groups
    out = dict(data)
    if out_hooks:
        out["hooks"] = out_hooks
    else:
        out.pop("hooks", None)
    if out.get("description") == "handoff-kb project lifecycle hooks":
        out.pop("description", None)
    return out, removed


def toml_snippet(client: str, root: Path, loose: bool, py: str | None = None) -> str:
    lines = ["# handoff-kb hooks（备用片段；优先使用 .codex/hooks.json，只启用一种来源）"]
    for ev, matcher in CLIENT_SPEC[client]["events"].items():
        lines.append("[[hooks.%s]]" % ev)
        if matcher:
            lines.append('matcher = "%s"' % matcher)
        lines.append("")
        lines.append("[[hooks.%s.hooks]]" % ev)
        lines.append('type = "command"')
        lines.append('command = "%s"' % _toml_escape(hook_command(client, ev, root, loose, py)))
        lines.append("")
    return "\n".join(lines)


def _toml_escape(s: str) -> str:
    out = s.replace("\\", "\\\\").replace('"', '\\"')
    return out.replace("\n", "\\n").replace("\t", "\\t")


def toml_validate(text: str):
    """用 stdlib tomllib 校验（3.11+）；3.10 无此模块时返回 (None, 原因)。"""
    try:
        import tomllib
    except Exception:
        return None, "tomllib 不可用（Python < 3.11），跳过结构校验"
    try:
        tomllib.loads(text)
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def strip_toml(text: str) -> tuple[str, int]:
    """移除片段中属于 handoff-kb 的 TOML 块。

    判定只看块内容，不做宽泛匹配：
      - `[[hooks.X.hooks]]` 块：block 内 `command =` 指向本脚本 → 属于我们
      - `[[hooks.X]]` 块：只在该事件下确实删掉了我们的子块、且它自身没有 command 时一并删
    其它块、注释、未知字段原样保留。
    """
    lines = text.splitlines()
    blocks, pre = [], []
    cur = None
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if cur:
                blocks.append(cur)
            cur = {"header": s, "lines": [line]}
        elif cur is None:
            pre.append(line)
        else:
            cur["lines"].append(line)
    if cur:
        blocks.append(cur)

    owned_events = set()
    kept_blocks, removed = [], 0
    for b in blocks:
        body = "\n".join(b["lines"][1:])
        cmd_line = next((ln for ln in b["lines"] if ln.strip().startswith("command =")), "")
        is_child = b["header"].startswith("[[hooks.") and b["header"].endswith(".hooks]]")
        if is_child and MARK in cmd_line and " run " in cmd_line:
            owned_events.add(b["header"][len("[[hooks."):-len(".hooks]]")])
            removed += 1
            continue
        kept_blocks.append(b)

    final_blocks = []
    for b in kept_blocks:
        s = b["header"]
        is_parent = (s.startswith("[[hooks.") and s.endswith("]]")
                     and not s.endswith(".hooks]]"))
        if is_parent:
            ev = s[len("[[hooks."):-2]
            if ev in owned_events:
                body = [ln for ln in b["lines"][1:] if ln.strip()]
                if len(body) <= 1 and not any(ln.strip().startswith("command") for ln in body):
                    removed += 1
                    continue
        final_blocks.append(b)

    kept_pre = [ln for ln in pre
                if not (ln.strip().startswith("#") and "handoff-kb" in ln)]
    out_lines = list(kept_pre)
    for b in final_blocks:
        out_lines.extend(b["lines"])
    body = "\n".join(ln for ln in out_lines if ln.strip())
    return (body + "\n") if body else "", removed


# --------------------------------------------------------------------------- #
# 预览
# --------------------------------------------------------------------------- #

def target_paths(client: str, root: Path):
    if client == "claude":
        return [(root / ".claude" / "settings.json", "json")]
    return [(root / ".codex" / "hooks.json", "json"),
            (root / ".codex" / "hooks.snippet.toml.txt", "toml")]


def _render_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def plan_install(args, root: Path) -> list[dict]:
    payload = build_payload(args.client, root, args.loose, args.python)
    rows = []
    for path, kind in target_paths(args.client, root):
        row = {"path": path.relative_to(root).as_posix(), "kind": kind,
               "exists": path.exists(), "added": [], "removed": [], "kept": 0,
               "sha_before": None, "sha_after": None, "changed": False, "error": None}
        if kind == "json":
            before = ""
            data = {}
            if path.is_file():
                before = read_text_strict(path)
                row["sha_before"] = sha256_file(path)
                try:
                    data = json.loads(before)
                except Exception as exc:
                    row["error"] = "现有文件不是合法 JSON（%s）：拒绝改写" % exc
                    rows.append(row)
                    continue
            merged, added = merge_payload(data, payload)
            after = _render_json(merged)
            row["added"] = added
            row["kept"] = sum(len(v) if isinstance(v, list) else 0
                              for k, v in (data.get("hooks") or {}).items()
                              if k not in added)
            row["sha_after"] = sha256_bytes(after.encode("utf-8"))
            row["changed"] = after != before
            row["_text"] = after
        else:
            before = read_text_strict(path) if path.is_file() else ""
            if path.is_file():
                row["sha_before"] = sha256_file(path)
            after = toml_snippet(args.client, root, args.loose, args.python)
            ok, msg = toml_validate(after)
            if ok is False:
                row["error"] = "生成的 TOML 无法解析：%s" % msg
            row["added"] = [ev for ev in CLIENT_SPEC[args.client]["events"]]
            row["sha_after"] = sha256_bytes(after.encode("utf-8"))
            row["changed"] = after != before
            row["_text"] = after
        rows.append(row)
    return rows


def plan_uninstall(args, root: Path) -> list[dict]:
    rows = []
    for path, kind in target_paths(args.client, root):
        row = {"path": path.relative_to(root).as_posix(), "kind": kind,
               "exists": path.exists(), "added": [], "removed": [], "kept": 0,
               "sha_before": None, "sha_after": None, "changed": False, "error": None}
        if not path.is_file():
            rows.append(row)          # 不存在 → 零写入、幂等
            continue
        row["sha_before"] = sha256_file(path)
        text = read_text_strict(path)
        if kind == "json":
            try:
                data = json.loads(text)
            except Exception as exc:
                row["error"] = "现有文件不是合法 JSON（%s）：拒绝改写" % exc
                rows.append(row)
                continue
            stripped, removed = strip_payload(data)
            after = _render_json(stripped) if stripped.get("hooks") else \
                (json.dumps(stripped, ensure_ascii=False, indent=2) + "\n"
                 if stripped else "")
            row["removed"] = sorted(set(removed))
            row["kept"] = sum(len(v) if isinstance(v, list) else 0
                              for v in (stripped.get("hooks") or {}).values())
            row["sha_after"] = sha256_bytes(after.encode("utf-8"))
            row["changed"] = after != text
            row["_text"] = after
            row["_delete"] = after.strip() == ""
        else:
            after, removed = strip_toml(text)
            row["removed"] = ["toml:%d 块" % removed] if removed else []
            row["sha_after"] = sha256_bytes(after.encode("utf-8"))
            row["changed"] = after != text
            row["_text"] = after
            row["_delete"] = after.strip() == ""
        rows.append(row)
    return rows


def print_plan(rows, action: str, client: str):
    print("== %s：%s（%s）" % ("安装计划" if action == "install" else "卸载计划",
                              client, "仅预览，未改动磁盘"))
    for r in rows:
        state = "存在" if r["exists"] else "不存在"
        print("\n-- %s（%s）" % (r["path"], state))
        if r["error"]:
            print("   !! %s" % r["error"])
            continue
        if action == "install":
            print("   新增事件：%s" % (", ".join(r["added"]) or "无"))
        else:
            print("   移除事件：%s" % (", ".join(r["removed"]) or "无"))
        print("   保留其它 hook 组：%d" % r["kept"])
        print("   SHA-256：%s → %s" % ((r["sha_before"] or "-")[:12],
                                      (r["sha_after"] or "-")[:12]))
        print("   变更：%s" % ("是" if r["changed"] else "否（已是最新/无需改动）"))


# --------------------------------------------------------------------------- #
# 执行（唯一写盘处）
# --------------------------------------------------------------------------- #

def apply_rows(root: Path, rows, action: str) -> int:
    bad = 0
    for r in rows:
        if r.get("error"):
            print("ERR: %s：%s" % (r["path"], r["error"]), file=sys.stderr)
            bad += 1
            continue
        if not r["changed"]:
            print("= %s（无需改动）" % r["path"])
            continue
        path = root / r["path"]
        if r["sha_before"] is not None and path.is_file():
            now = sha256_file(path)
            if now != r["sha_before"]:
                print("ERR: %s 在预览后被改动（%s… → %s…），已放弃写入"
                      % (r["path"], r["sha_before"][:8], now[:8]), file=sys.stderr)
                bad += 1
                continue
        if r.get("_delete") or not str(r.get("_text") or "").strip():
            if path.is_file():
                path.unlink()
                print("- %s（已删除空配置）" % r["path"])
            continue
        atomic_write(path, r["_text"])
        print("~ %s" % r["path"])
    return bad


def cmd_install(args, root: Path) -> int:
    rows = plan_install(args, root)
    if not args.write:
        print_plan(rows, "install", args.client)
        print("\n-- 默认不写盘；确认后加 --write。只写项目级配置，不改全局。")
        return 0
    if any(r.get("error") for r in rows):
        print_plan(rows, "install", args.client)
        print("\nERR: 存在无法安全改写的问题，未做任何写入。", file=sys.stderr)
        return 2
    bad = apply_rows(root, rows, "install")
    if bad:
        return 2
    print("-- 已写入 %s hooks：%s" % (args.client, ", ".join(CLIENT_SPEC[args.client]["events"])))
    if args.client == "codex":
        print("-- 提示：.codex/hooks.json 与 hooks.snippet.toml.txt 只启用一种来源，"
              "优先 hooks.json；不要把两处内容同时并入。")
    return 0


def cmd_uninstall(args, root: Path) -> int:
    rows = plan_uninstall(args, root)
    if not args.write:
        print_plan(rows, "uninstall", args.client)
        print("\n-- 默认不写盘；确认后加 --write。只移除 handoff-kb 自己写入的条目。")
        return 0
    if any(r.get("error") for r in rows):
        print_plan(rows, "uninstall", args.client)
        print("\nERR: 存在无法安全改写的文件，未做任何写入。", file=sys.stderr)
        return 2
    bad = apply_rows(root, rows, "uninstall")
    if bad:
        return 2
    print("-- 卸载完成（幂等；未触碰其它 Hook）")
    return 0


# --------------------------------------------------------------------------- #
# 运行时
# --------------------------------------------------------------------------- #

def _stdin_ready(timeout: float) -> bool:
    """只问「现在有没有数据」，绝不阻塞读。管道/重定向/终端三种情况都要安全。"""
    try:
        fd = sys.stdin.fileno()
    except Exception:
        return False
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.windll.kernel32
            handle = k32.GetStdHandle(-10)          # STD_INPUT_HANDLE
            if handle in (0, -1):
                return False
            avail = wintypes.DWORD(0)
            deadline = time.time() + timeout
            while True:
                ok = k32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(avail), None)
                if not ok:
                    return False                     # 控制台/非管道：当作没有输入
                if avail.value:
                    return True
                if time.time() >= deadline:
                    return False
                time.sleep(0.01)
        except Exception:
            return False
    try:
        import select
        r, _, _ = select.select([fd], [], [], timeout)
        return bool(r)
    except Exception:
        return False


def read_hook_input(timeout: float = 0.2):
    """读客户端通过 stdin 传的 JSON（只取 cwd，其余忽略）。

    先探测再读：客户端没写 stdin 时直接返回 {}，不会把会话启动卡住。
    """
    if sys.stdin is None or not _stdin_ready(timeout):
        return {}
    chunks, total = [], 0
    try:
        fd = sys.stdin.fileno()
        while total < (1 << 20) and _stdin_ready(0.05):
            b = os.read(fd, 65536)
            if not b:
                break
            chunks.append(b)
            total += len(b)
    except Exception:
        return {}
    raw = b"".join(chunks).decode("utf-8", "replace")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def resolve_hook_root(args) -> tuple[Path | None, str]:
    """决定这次 Hook 该读哪个库：安装时记录的根 + 运行时的 cwd 交叉校验。"""
    stdin = read_hook_input()
    cwd = stdin.get("cwd") or stdin.get("workspace") or ""
    target_raw = str(args.target or ".")
    target = Path(target_raw)
    note = ""
    if target.is_absolute():
        root = target
        if cwd:
            try:
                c = Path(cwd).resolve()
                r = root.resolve()
                if not (scope.is_within(r, c) or scope.is_within(c, r)):
                    return None, ("Hook 的 cwd=%s 不在已安装的项目 %s 内；"
                                  "为避免误用别的库，本次不注入上下文。" % (cwd, root))
            except Exception:
                note = "cwd 解析失败，按安装记录的项目根继续"
    else:
        # 旧配置（--target .）：只信 cwd，且必须像个交接库
        if cwd and Path(cwd).is_dir():
            root = Path(cwd)
            note = "旧配置：使用事件 cwd"
        else:
            root = Path.cwd()
            note = "未拿到 cwd，使用进程工作目录"
    try:
        if not root.is_dir():
            return None, "项目根不存在：%s" % root
        files = scope.role_files(root, loose=getattr(args, "loose", False))
        if not files.get("dashboard") and not files.get("baseline"):
            return None, "%s 不像交接库（没有 00/05）" % root
    except Exception as exc:
        return None, "项目根不可用：%s" % exc
    return root, note


def _emit(payload: dict):
    print(json.dumps(payload, ensure_ascii=False))


def _context_text(root: Path, budget: int, loose: bool) -> str:
    cmd = [sys.executable, str(SCRIPT.with_name("kb-context.py")),
           "--target", str(root), "--mode", "handoff",
           "--budget", str(budget), "--format", "markdown"]
    if loose:
        cmd.append("--loose")
    out = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if out.returncode not in (0, 1):
        return ""
    return (out.stdout or "").strip()


def _handoff_issues(root: Path, loose: bool):
    cmd = [sys.executable, str(SCRIPT.with_name("kb-handoff.py")),
           "check", "--target", str(root), "--json"]
    if loose:
        cmd.append("--loose")
    out = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    try:
        data = json.loads(out.stdout)
    except Exception:
        return None
    bad = [i for i in data.get("items", []) if i.get("status") != "ok"]
    return [i for i in bad if i.get("status") == "missing"] or bad


def cmd_run(args, root: Path) -> int:
    """只读；任何异常都降级为零输出并退出 0。"""
    try:
        if root is None:
            return 0
        client, event = args.client, args.event
        loose = bool(getattr(args, "loose", False))

        if event == "SessionStart":
            text = _context_text(root, args.budget, loose)
            if not text:
                return 0
            if client == "codex":
                _emit({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                              "additionalContext": text}})
            else:
                _emit({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                              "additionalContext": text}})
            return 0

        if event == "PreCompact":
            msg = ("handoff-kb：压缩前先收尾——py kb-handoff.py check --target .%s；"
                   "未保存的状态用 kb-write.py 写回 05/06。这是提醒，不阻止压缩。"
                   % (" --loose" if loose else ""))
            _emit({"systemMessage": msg})
            return 0

        if event == "Stop":
            issues = _handoff_issues(root, loose)
            if issues:
                names = "、".join("%s(%s)" % (i.get("key"), i.get("status")) for i in issues[:4])
                _emit({"systemMessage": "handoff-kb：交接还不完整——%s。"
                                        "补齐后结束更稳。" % names})
            else:
                _emit({})
            return 0

        if event == "SessionEnd":
            _emit({})
            return 0

        _emit({})
        return 0
    except Exception:
        # Hook 绝不破坏会话：降级为无输出
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="handoff-kb Hook 适配（默认不安装、不写盘）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("install", "uninstall"):
        p = sub.add_parser(name)
        p.add_argument("--client", choices=["claude", "codex"], required=True)
        p.add_argument("--target", default=".")
        p.add_argument("--plan", action="store_true", help="只预览（默认行为）")
        p.add_argument("--write", action="store_true", help="实际写盘")
        p.add_argument("--loose", action="store_true", help="按别名识别 05/06/90")
        p.add_argument("--python", default=None, help="生成命令用的解释器路径")

    r = sub.add_parser("run", help="Hook 运行时入口（只读，永远退出 0）")
    r.add_argument("--client", choices=["claude", "codex"], required=True)
    r.add_argument("--event", required=True)
    r.add_argument("--target", default=".")
    r.add_argument("--budget", type=int, default=1200)
    r.add_argument("--loose", action="store_true")

    args = ap.parse_args()

    if args.cmd == "run":
        try:
            root, note = resolve_hook_root(args)
        except Exception:
            return 0
        if root is None:
            return 0
        return cmd_run(args, root)

    try:
        root = scope.resolve_root(args.target)
    except scope.ScopeError as exc:
        print("ERR: %s" % exc, file=sys.stderr)
        return 2

    return cmd_install(args, root) if args.cmd == "install" else cmd_uninstall(args, root)


if __name__ == "__main__":
    sys.exit(main())
