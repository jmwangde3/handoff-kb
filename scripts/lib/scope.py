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
    """真实路径是否落在 root 内。

    用 `resolve()` 规范化后再比较路径组成，**不做字符串前缀判断**：
    `C:\\project-backup` 的前缀是 `C:\\project`，但它是另一个目录。
    """
    root = Path(root).resolve()
    try:
        Path(path).resolve().relative_to(root)
        return True
    except ValueError:
        return False


def real_rel(root: Path, path: Path) -> str:
    """真实路径相对根的 posix 形式；越界返回空串（调用方据此拒绝）。"""
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return ""


def escape_reason(root: Path, path: Path) -> str:
    """越界诊断：同时给出原始路径与真实路径，避免「看起来在库里」。"""
    return "%s → 真实路径 %s 不在 %s 内" % (path, os.path.realpath(str(path)),
                                            Path(root).resolve())


def check_dir(root: Path, path, *, label: str = "目录") -> Path:
    """目录级校验：必须存在、是目录、真实路径仍在根内。

    符号链接与 Windows Junction 都会被 `resolve()` 展开，
    所以「指向库外的目录」在这里一律拒绝，而不是靠 `is_dir()` 放行。
    """
    p = Path(path)
    if not p.exists():
        raise ScopeError("%s不存在：%s" % (label, p))
    if not p.is_dir():
        raise ScopeError("%s不是目录：%s" % (label, p))
    if not is_within(root, p):
        raise ScopeError("%s越界：%s" % (label, escape_reason(root, p)))
    return p


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


def role_of_path(root: Path, path, loose: bool = False) -> str:
    """按**相对路径**判定角色，而不是只看 `path.name`。

    `06_流水/固件.md` 是 shard、`归档/历史.md` 是 archive —— 只看文件名会把它们
    当成普通事实文档，用同样的权重参与检索与装配，流水噪声就会盖过当前结论。
    """
    rel = real_rel(root, path)
    if not rel:
        return "other"
    parts = rel.split("/")
    for seg in reversed(parts[:-1]):
        if is_archive_dir(seg):
            return "archive"
        if seg == protocol.SHARD_DIR or (loose and protocol.SHARD_DIR_RE.match(seg)):
            return "shard"
    return protocol.role_of_name(parts[-1], loose=loose)


def iter_text_files(root: Path, *, include_archive: bool = False,
                    include_data: bool = False, max_bytes: int = protocol.MAX_TEXT_BYTES,
                    audit: list | None = None):
    """遍历根下文本文件，产出 (Path, reason_or_None)。reason 非空表示被跳过。

    目录级安全：每个目录都用 `os.path.realpath` 解析后核对是否仍在根内，
    越界的符号链接 / Windows Junction 会被**剪枝**（不下降、不读取），
    并以 `dir-outside` 产出一次诊断，交给调用方决定报 WARN 还是 ERR。
    """
    root = Path(root).resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        # os.walk 默认不跟随符号链接，但 Junction 在 Windows 上不是 islink，
        # 所以这里逐个用 realpath 核对，不能只信任 walk 的行为。
        if d != root and not is_within(root, d):
            yield d, "dir-outside"
            if audit is not None:
                audit.append((str(d), "dir-outside", escape_reason(root, d)))
            dirnames[:] = []
            continue
        keep = []
        for name in sorted(dirnames):
            low = name.lower()
            if not include_data and low in excluded_dir_names():
                continue
            if not include_archive and is_archive_dir(name):
                continue
            sub = d / name
            if not is_within(root, sub):
                yield sub, "dir-outside"
                if audit is not None:
                    audit.append((str(sub), "dir-outside", escape_reason(root, sub)))
                continue
            keep.append(name)
        dirnames[:] = keep
        for name in sorted(filenames):
            p = d / name
            if p.suffix.lower() not in protocol.TEXT_EXTS:
                continue
            if not is_within(root, p):
                yield p, "symlink-outside"
                if audit is not None:
                    audit.append((str(p), "symlink-outside", escape_reason(root, p)))
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


def role_files(root: Path, loose: bool = False, audit: list | None = None):
    """{role: [paths]}；固定文件优先精确命名，绝不用 `05_*.md` 这类通配。

    只收真实路径仍在根内的文件：根层的符号链接指向库外时跳过并记诊断，
    不能让「库外文件」冒充 00/05 参与装配。
    """
    root = Path(root)
    roles = {}
    if not root.is_dir():
        return roles
    for p in sorted(root.iterdir()):
        if not p.is_file() or p.suffix.lower() not in protocol.TEXT_EXTS:
            continue
        if not is_within(root, p):
            if audit is not None:
                audit.append((str(p), "file-outside", escape_reason(root, p)))
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


def shard_dirs(root: Path, loose: bool = False, audit: list | None = None):
    """分片目录列表：规范 `06_流水/`；loose 再认 `60_流水/` 等别名。

    越界的目录（符号链接 / Junction 指向库外）**不进入结果**，只记诊断。
    """
    root = Path(root)
    out = []
    canon = root / protocol.SHARD_DIR
    if canon.is_dir():
        if is_within(root, canon):
            out.append(canon)
        elif audit is not None:
            audit.append((str(canon), "dir-outside", escape_reason(root, canon)))
    if loose:
        skip = excluded_dir_names()
        for p in sorted(root.iterdir()):
            if not p.is_dir() or p in out:
                continue
            if p.name.lower() in skip:
                continue
            if protocol.SHARD_DIR_RE.match(p.name):
                if is_within(root, p):
                    out.append(p)
                elif audit is not None:
                    audit.append((str(p), "dir-outside", escape_reason(root, p)))
    return out


def shards(root: Path, loose: bool = False, audit: list | None = None):
    """分片文件。目录已由 shard_dirs 把关，这里再核一次文件级真实路径。"""
    files = []
    for d in shard_dirs(root, loose, audit=audit):
        for p in sorted(d.glob("*.md")):
            if not p.is_file():
                continue
            if not is_within(root, p):
                if audit is not None:
                    audit.append((str(p), "file-outside", escape_reason(root, p)))
                continue
            files.append(p)
    return files
