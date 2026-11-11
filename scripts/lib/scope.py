#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""作用域与路径安全（handoff-kb 2.0）

所有脚本的路径判定都走这里，避免各 CLI 各写一套：
- 项目根解析（必须是已存在目录）
- 读写路径必须落在根内（防 `..`、绝对路径、符号链接越界）
- 资料目录 / >2 MB 文本的排除规则
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import protocol

# Windows 绝对路径的**可移植**判定：不能在 POSIX 上依赖 Path.drive
# （PurePosixPath("C:/x").drive == ""，于是同一份输入在 Linux 上会被放行，
#  CI 六环境里就出现「Linux 通过、Windows 拒绝」的分歧）。
_WIN_ABS_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[A-Za-z]:$|\\\\|//)")


class ScopeError(Exception):
    """路径或作用域不合法。"""


def resolve_root(target) -> Path:
    p = Path(target or ".").expanduser()
    if not p.exists():
        raise ScopeError("目标目录不存在：%s" % p)
    if not p.is_dir():
        raise ScopeError("目标不是目录：%s" % p)
    return p.resolve()


def rel_posix(path: Path, root: Path) -> str:
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def is_within(root: Path, path: Path) -> bool:
    root = Path(root).resolve()
    try:
        Path(path).resolve().relative_to(root)
        return True
    except ValueError:
        return False


def check_rel_path(root: Path, rel: str, *, must_be_text: bool = True) -> Path:
    """校验一个相对路径，返回其真实路径。

    拒绝：绝对路径（含 Windows 盘符 / UNC，跨平台一致）、`..`、空路径、符号链接越界、非文本扩展名。
    """
    if not rel or rel.strip() != rel:
        raise ScopeError("路径为空或首尾有空白：%r" % rel)
    candidate = Path(rel)
    if (candidate.is_absolute() or candidate.drive or rel.startswith(("/", "\\"))
            or _WIN_ABS_RE.match(rel)):
        raise ScopeError("拒绝绝对路径：%s" % rel)
    parts = [p for p in candidate.parts if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ScopeError("拒绝路径穿越：%s" % rel)
    full = (Path(root) / candidate)
    if not is_within(root, full):
        raise ScopeError("路径逃出工作区：%s" % rel)
    # 已存在的符号链接必须也落在根内
    if full.is_symlink() and not is_within(root, full):
        raise ScopeError("符号链接指向工作区外：%s" % rel)
    if must_be_text and full.suffix.lower() not in protocol.TEXT_EXTS:
        raise ScopeError("只允许改写文本文件（%s）：%s" % ("/".join(protocol.TEXT_EXTS), rel))
    return full


def excluded_dir_names() -> set:
    return {d.lower() for d in protocol.DATA_DIRS}


def is_data_path(path: Path, root: Path) -> bool:
    """相对根路径中是否含资料/缓存目录（用于体积统计与检索排除）。"""
    try:
        parts = Path(path).resolve().relative_to(Path(root).resolve()).parts
    except ValueError:
        return True
    skip = excluded_dir_names()
    return any(p.lower() in skip for p in parts[:-1])


def is_archive_dir(name: str) -> bool:
    return bool(protocol.ARCHIVE_DIR_RE.match(name))


def iter_text_files(root: Path, *, include_archive: bool = False,
                    include_data: bool = False, max_bytes: int = protocol.MAX_TEXT_BYTES):
    """遍历根下文本文件，产出 (Path, reason_or_None)。reason 非空表示被跳过。"""
    root = Path(root).resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        keep = []
        for name in sorted(dirnames):
            low = name.lower()
            if not include_data and low in excluded_dir_names():
                continue
            if not include_archive and is_archive_dir(name):
                continue
            keep.append(name)
        dirnames[:] = keep
        for name in sorted(filenames):
            p = d / name
            if p.suffix.lower() not in protocol.TEXT_EXTS:
                continue
            if p.is_symlink() and not is_within(root, p):
                yield p, "symlink-outside"
                continue
            try:
                size = p.stat().st_size
            except OSError as exc:
                yield p, "stat-error:%s" % exc
                continue
            if size > max_bytes:
                yield p, "too-large"
                continue
            yield p, None


def load_text(path: Path) -> str:
    """统一 UTF-8 读取；容忍 BOM，保留原有换行（不做 CRLF 归一）。"""
    data = Path(path).read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8", errors="replace")


def role_files(root: Path, loose: bool = False):
    """{role: [paths]}；固定文件优先精确命名，绝不用 `05_*.md` 这类通配。"""
    root = Path(root)
    roles = {}
    if not root.is_dir():
        return roles
    for p in sorted(root.iterdir()):
        if not p.is_file() or p.suffix.lower() not in protocol.TEXT_EXTS:
            continue
        role = protocol.role_of_name(p.name, loose=loose)
        roles.setdefault(role, []).append(p)
    pref = {"baseline": protocol.CANON_BASELINE, "dashboard": protocol.CANON_DASHBOARD,
            "log": protocol.CANON_LOG, "archive": protocol.CANON_ARCHIVE}
    for role, names in pref.items():
        if role in roles and len(roles[role]) > 1:
            for want in names:
                for p in roles[role]:
                    if p.name == want:
                        roles[role] = [p]
                        break
    return roles


def shard_dirs(root: Path, loose: bool = False):
    """分片目录列表：规范 `06_流水/`；loose 再认 `60_流水/` 等别名。"""
    root = Path(root)
    out = []
    canon = root / protocol.SHARD_DIR
    if canon.is_dir():
        out.append(canon)
    if loose:
        skip = excluded_dir_names()
        for p in sorted(root.iterdir()):
            if not p.is_dir() or p in out:
                continue
            if p.name.lower() in skip:
                continue
            if protocol.SHARD_DIR_RE.match(p.name):
                out.append(p)
    return out


def shards(root: Path, loose: bool = False):
    files = []
    for d in shard_dirs(root, loose):
        files.extend(sorted(p for p in d.glob("*.md") if p.is_file()))
    return files
