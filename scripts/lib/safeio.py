#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安全写入基础设施（handoff-kb 2.0.1）

四层保护，逐层加强：

1. **全量 SHA-256**：文件字节 / 字节串 / 文本，用于乐观并发控制。
2. **工作区锁**：原子 mkdir + owner token + 进程存活判断；
   只有「同机 + 原进程确定已退出」才允许自动回收，回收用原子重命名隔离，
   释放前必须验证 token 仍是自己的。
3. **原子写**：同目录临时文件 → fsync → os.replace → fsync 父目录；
   保留原文件权限、BOM、换行风格；写入前严格 UTF-8 解码。
4. **多文件事务**：预检 → 备份（原始字节 + 哈希）→ journal（原子写 + checksum）
   → 逐个 replace → committed；失败按 sha_after 判定后回滚；崩溃后 recover。

诚实声明：多个 os.replace() **不是**跨文件原子事务。这里给的是
「全量预检 + 字节级备份 + 状态机 journal + 崩溃后分文件判定恢复」。
journal 损坏、备份损坏、目标被第三方改动时一律停下并要求人工介入——
自动「清理」在证据不足时会变成数据销毁。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
import uuid
from pathlib import Path

TXN_DIR = ".kb-txn"
LOCK_DIR = ".kb.lock"
RECLAIM_PREFIX = LOCK_DIR + ".reclaim-"

JOURNAL_SCHEMA = 2
LOCK_SCHEMA = 1

# 事务状态机
S_CREATED = "created"
S_PREPARED = "prepared"
S_APPLYING = "applying"
S_COMMITTED = "committed"
S_ROLLING_BACK = "rolling_back"
S_ROLLED_BACK = "rolled_back"
S_ROLLBACK_CONFLICT = "rollback_conflict"
S_MANUAL = "manual_recovery_required"

VALID_STATES = {S_CREATED, S_PREPARED, S_APPLYING, S_COMMITTED,
                S_ROLLING_BACK, S_ROLLED_BACK, S_ROLLBACK_CONFLICT, S_MANUAL}
VALID_OPS = {"replace_section", "append", "update_fact", "migrate", "replace"}


class SafeIOError(Exception):
    pass


class LockHeld(SafeIOError):
    pass


class LockOwnershipError(SafeIOError):
    pass


class StaleLock(SafeIOError):
    pass


class Conflict(SafeIOError):
    pass


class EncodingError(SafeIOError):
    pass


# --------------------------------------------------------------------------- #
# 哈希与字节 / 文本
# --------------------------------------------------------------------------- #

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def read_bytes(path) -> bytes:
    return Path(path).read_bytes()


def decode_strict(data: bytes) -> tuple[str, str, bool]:
    """严格解码：返回 (文本, 换行风格, 是否带 BOM)。失败抛 EncodingError。"""
    bom = data.startswith(b"\xef\xbb\xbf")
    body = data[3:] if bom else data
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EncodingError(
            "文件不是合法 UTF-8（%s）；拒绝写入以免把非法字节替换成 U+FFFD 破坏原数据。"
            "先用 `python -c \"open(p,'rb').read().decode('utf-8')\"` 定位坏字节。" % exc)
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return text, ("\r\n" if crlf > lf else "\n"), bom


def read_text(path, errors: str = "replace") -> str:
    """读文本。errors='replace' 只用于**只读诊断**；写入路径必须用 read_text_strict。"""
    data = Path(path).read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8", errors=errors)


def read_text_strict(path) -> str:
    text, _, _ = decode_strict(Path(path).read_bytes())
    return text


def dominant_newline(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def _fsync_dir(path: Path):
    """尽力 fsync 目录（POSIX 有效，Windows 打开目录会失败 → 忽略）。"""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


# --------------------------------------------------------------------------- #
# 原子写
# --------------------------------------------------------------------------- #

def atomic_write_bytes(path, data: bytes, mode_from=None) -> None:
    """写字节：临时文件 → fsync → replace → fsync 父目录。可保留原文件权限。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    src = Path(mode_from) if mode_from else (p if p.exists() else None)
    st = None
    if src is not None:
        try:
            st = src.stat()
        except OSError:
            st = None
    fd, tmp = tempfile.mkstemp(prefix=".kb-tmp-", dir=str(p.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if st is not None:
            try:
                os.chmod(tmp, stat.S_IMODE(st.st_mode))
            except OSError:
                pass
        os.replace(tmp, p)
        _fsync_dir(p.parent)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def atomic_write(path, text: str) -> None:
    """写文本：沿用原文件的换行风格与 BOM；新文件用 LF / 无 BOM。"""
    p = Path(path)
    nl, bom = "\n", False
    if p.exists():
        try:
            _, nl, bom = decode_strict(p.read_bytes())
        except EncodingError:
            raise
    if nl == "\r\n" and "\r\n" not in text:
        text = text.replace("\n", "\r\n")
    data = text.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    atomic_write_bytes(p, data, mode_from=p)


# --------------------------------------------------------------------------- #
# 进程存活 / 启动时间
# --------------------------------------------------------------------------- #

def process_start_time(pid: int):
    """进程启动标识（用于识别 PID 复用）。拿不到返回 None，调用方须保守处理。"""
    if not pid or pid <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
            if not h:
                return None
            try:
                created = wintypes.FILETIME()
                exited = wintypes.FILETIME()
                kernel = wintypes.FILETIME()
                user = wintypes.FILETIME()
                ok = k32.GetProcessTimes(h, ctypes.byref(created), ctypes.byref(exited),
                                         ctypes.byref(kernel), ctypes.byref(user))
                if not ok:
                    return None
                return "%d" % ((created.dwHighDateTime << 32) | created.dwLowDateTime)
            finally:
                k32.CloseHandle(h)
        except Exception:
            return None
    try:
        st = Path("/proc/%d/stat" % pid).read_text(encoding="utf-8", errors="replace")
        parts = st.rsplit(")", 1)[-1].split()
        return parts[19] if len(parts) > 19 else None
    except OSError:
        return None


def pid_alive(pid: int):
    """True/False；判断不了返回 True（保守：当作还活着，绝不误抢）。"""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
            if not h:
                return False
            try:
                code = ctypes.c_ulong(0)
                ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
                return bool(ok) and code.value == 259  # STILL_ACTIVE
            finally:
                k32.CloseHandle(h)
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def host_name() -> str:
    if hasattr(os, "uname"):
        try:
            return os.uname().nodename
        except Exception:
            pass
    return os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or ""


# --------------------------------------------------------------------------- #
# 工作区锁
# --------------------------------------------------------------------------- #

class WorkspaceLock:
    """原子目录锁 + owner token。

    目录结构：
        .kb.lock/
            meta.json     {"schema_version":1,"owner_token":...,"pid":...,
                           "host":...,"process_start":...,"created":...,"session":...}

    三种状态：
      正常     meta 可读、token 是本进程的
      占用中   meta 可读、pid 活着或无法判断 → 等待超时后报错
      不完整   mkdir 成功但 meta 缺失/损坏 → **不自动抢占**，要求人工介入
    """

    def __init__(self, root, timeout: float = 5.0, poll: float = 0.1, session: str = ""):
        self.root = Path(root)
        self.dir = self.root / LOCK_DIR
        self.timeout = timeout
        self.poll = poll
        self.session = session or os.environ.get("KB_SESSION", "")
        self.owner_token = uuid.uuid4().hex
        self.pid = os.getpid()
        self.reclaimed = None
        self._held = False

    # -- meta ----------------------------------------------------------- #
    def _read_meta_from(self, d: Path):
        """返回 (meta_dict_or_None, error_str)。"""
        f = d / "meta.json"
        if not f.is_file():
            return None, "meta.json 缺失（加锁过程中断？）"
        try:
            raw = f.read_text(encoding="utf-8")
        except OSError as exc:
            return None, "meta.json 不可读：%s" % exc
        try:
            meta = json.loads(raw)
        except Exception as exc:
            return None, "meta.json 不是合法 JSON：%s" % exc
        if not isinstance(meta, dict):
            return None, "meta.json 不是对象"
        if meta.get("schema_version") not in (None, LOCK_SCHEMA):
            return None, "meta.json schema_version=%r 不受支持" % meta.get("schema_version")
        return meta, None

    def meta(self):
        return self._read_meta_from(self.dir)[0] or {}

    def describe(self) -> dict:
        """给 break-lock / 报错用：锁现状 + 判读。"""
        if not self.dir.exists():
            return {"exists": False}
        meta, err = self._read_meta_from(self.dir)
        info = {"exists": True, "path": str(self.dir), "incomplete": err is not None,
                "meta_error": err, "meta": meta or {}}
        if meta:
            pid = int(meta.get("pid") or 0)
            alive = pid_alive(pid)
            cur_start = process_start_time(pid) if alive else None
            info.update({
                "pid": pid, "alive": alive,
                "host": meta.get("host") or "",
                "same_host": (meta.get("host") or "") == host_name(),
                "session": meta.get("session") or "",
                "created": meta.get("created"),
                "pid_reused": bool(alive and meta.get("process_start")
                                   and cur_start and cur_start != meta["process_start"]),
            })
        return info

    # -- acquire -------------------------------------------------------- #
    def acquire(self):
        deadline = time.time() + self.timeout
        while True:
            try:
                self.dir.mkdir()
            except FileExistsError:
                if self._try_reclaim():
                    continue
                if time.time() >= deadline:
                    raise LockHeld(self._held_message())
                time.sleep(self.poll)
                continue
            # 抢到了目录：立刻写 meta（原子写，避免半截 JSON）
            try:
                meta = {
                    "schema_version": LOCK_SCHEMA,
                    "owner_token": self.owner_token,
                    "pid": self.pid,
                    "host": host_name(),
                    "process_start": process_start_time(self.pid),
                    "created": time.time(),
                    "session": self.session,
                }
                atomic_write_bytes(self.dir / "meta.json",
                                   json.dumps(meta, ensure_ascii=False, indent=2)
                                   .encode("utf-8"))
            except Exception:
                # 写 meta 失败：把自己的目录清掉，避免留下不完整锁
                shutil.rmtree(self.dir, ignore_errors=True)
                raise
            self._held = True
            return self

    def _held_message(self) -> str:
        info = self.describe()
        if info.get("incomplete"):
            return ("工作区锁不完整：%s（%s）。可能上次加锁时进程被杀。\n"
                    "  确认没有其他会话在写之后：kb-write.py recover --break-lock --force"
                    % (self.dir, info.get("meta_error")))
        meta = info.get("meta") or {}
        return ("工作区已被占用：%s（pid=%s, host=%s, session=%s, created=%s）；"
                "等待 %.1fs 超时。\n  若确认对方已死：kb-write.py recover --break-lock"
                "（先不带 --force 看判读，再用 --force 执行）"
                % (self.dir, meta.get("pid") or "?", meta.get("host") or "-",
                   meta.get("session") or "-",
                   time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(meta.get("created") or 0)),
                   self.timeout))

    def _try_reclaim(self) -> bool:
        """死锁回收：同机 + 原进程确定已退出才允许。返回 True 表示重试加锁。"""
        meta, err = self._read_meta_from(self.dir)
        if err is not None:
            # 不完整锁：不自动抢占
            return False
        host = meta.get("host") or ""
        pid = int(meta.get("pid") or 0)
        if host and host != host_name():
            return False                      # 别的主机：不碰
        if not pid:
            return False                      # 没有 pid：当未知，不抢
        alive = pid_alive(pid)
        if alive:
            rec_start = meta.get("process_start")
            cur_start = process_start_time(pid)
            if not rec_start or not cur_start or rec_start == cur_start:
                return False                  # 真是活锁，或判断不了 → 不抢
            # 启动时间不同 = PID 被复用，原进程已退出 → 可回收
        # 原子隔离：重命名成唯一名字，避免两个回收者同时删同一目录
        iso = Path(self.root) / (RECLAIM_PREFIX + uuid.uuid4().hex)
        try:
            os.rename(self.dir, iso)
        except OSError:
            return True                       # 别人先动手了，回到主循环重试
        try:
            meta2, err2 = self._read_meta_from(iso)
            if err2 is not None or (meta2 or {}).get("owner_token") != meta.get("owner_token"):
                # 隔离到的不是我们判定的那把锁（竞争中被替换）→ 原样放回
                try:
                    os.rename(iso, self.dir)
                except OSError:
                    pass
                return True
            shutil.rmtree(iso, ignore_errors=True)
            self.reclaimed = meta
            return True
        except Exception:
            shutil.rmtree(iso, ignore_errors=True)
            return True

    # -- release -------------------------------------------------------- #
    def release(self) -> bool:
        """释放锁。锁已被别人替换时**拒绝删除**并报错（旧持有者没资格删新锁）。"""
        if not self._held:
            return False
        self._held = False
        if not self.dir.exists():
            return False
        meta, err = self._read_meta_from(self.dir)
        if err is not None:
            raise LockOwnershipError(
                "释放锁失败：%s 的 meta 不可读（%s）。为免误删他人锁，未做任何删除；"
                "请人工检查。" % (self.dir, err))
        if meta.get("owner_token") != self.owner_token:
            raise LockOwnershipError(
                "释放锁失败：锁已被其他会话接管（当前 token=%s…，我方=%s…）。"
                "未删除任何内容。" % (str(meta.get("owner_token"))[:8], self.owner_token[:8]))
        if int(meta.get("pid") or 0) != self.pid:
            raise LockOwnershipError(
                "释放锁失败：meta.pid=%s 不是本进程 %s，未删除。"
                % (meta.get("pid"), self.pid))
        shutil.rmtree(self.dir, ignore_errors=True)
        return True

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False


def break_lock(root, plan: bool = True, force: bool = False) -> dict:
    """显式解锁。默认 plan（只看不动）；force 才真的删，且删前重验 token。"""
    root = Path(root)
    d = root / LOCK_DIR
    if not d.exists():
        return {"exists": False, "action": "none", "message": "没有锁目录"}
    lock = WorkspaceLock(root)
    info = lock.describe()
    info["action"] = "plan" if plan else "refused"
    if plan:
        info["message"] = "预览：未改动磁盘。确认后用 --break-lock --force 执行。"
        return info
    if info.get("incomplete"):
        if not force:
            info["message"] = "锁不完整且未加 --force：拒绝删除（可能是别人正在加锁）。"
            return info
    else:
        if info.get("alive") and not info.get("pid_reused"):
            if not force:
                info["message"] = ("持有者 pid=%s 仍在运行：拒绝删除。"
                                   "确认那是僵尸/无关进程后再加 --force。" % info.get("pid"))
                return info
    meta, err = lock._read_meta_from(d)
    token = (meta or {}).get("owner_token")
    iso = root / (RECLAIM_PREFIX + uuid.uuid4().hex)
    try:
        os.rename(d, iso)
    except OSError as exc:
        info["message"] = "无法隔离锁目录：%s" % exc
        return info
    try:
        meta2, err2 = lock._read_meta_from(iso)
        if err2 is None and token and (meta2 or {}).get("owner_token") != token:
            os.rename(iso, d)                 # 抢错了，放回去
            info["message"] = "锁在你确认后被替换：已放回，未删除。"
            return info
        shutil.rmtree(iso, ignore_errors=True)
        info["action"] = "removed"
        info["message"] = "已删除锁目录（token=%s…）" % str(token)[:8]
        return info
    except Exception as exc:
        shutil.rmtree(iso, ignore_errors=True)
        info["message"] = "删除过程中出错：%s" % exc
        return info


# --------------------------------------------------------------------------- #
# 事务
# --------------------------------------------------------------------------- #

def root_id(root) -> str:
    return sha256_text(str(Path(root).resolve()).replace("\\", "/"))[:16]


def _canonical(obj: dict) -> bytes:
    body = {k: v for k, v in obj.items() if k != "checksum"}
    return json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def journal_checksum(journal: dict) -> str:
    return sha256_bytes(_canonical(journal))


class Transaction:
    """多文件写入：预检 → 备份 → journal → 逐个 replace → committed。

    每个条目保存原始字节备份与备份哈希；恢复时先验哈希再写回。
    """

    def __init__(self, root, session: str = ""):
        self.root = Path(root).resolve()
        self.session = session or os.environ.get("KB_SESSION", "")
        self.dir = self.root / TXN_DIR
        self.id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.entries = []
        self.journal = None
        self._committed = False

    # -- staging -------------------------------------------------------- #
    def stage(self, rel: str, expected_sha: str, new_text: str, operation: str = "replace_section"):
        from . import scope  # 延迟导入，避免循环依赖
        if operation not in VALID_OPS:
            raise SafeIOError("不支持的操作类型：%r（允许：%s）"
                              % (operation, ", ".join(sorted(VALID_OPS))))
        scope.check_rel_path(self.root, rel)
        p = self.root / rel
        if not p.is_file():
            raise SafeIOError("目标文件不存在：%s" % rel)
        if len(expected_sha or "") != 64:
            raise SafeIOError("expected_sha256 必须是 64 位十六进制：%r" % expected_sha)
        data = p.read_bytes()
        decode_strict(data)                      # 写前严格解码，坏字节直接拒绝
        cur = sha256_bytes(data)
        if cur != expected_sha:
            raise Conflict("哈希冲突：%s\n  期望 %s\n  实际 %s\n"
                           "  处理：重新 read 该文件，合并后重试（不覆盖任何内容）"
                           % (rel, expected_sha, cur))
        if any(e["path"] == rel for e in self.entries):
            raise SafeIOError("同一事务里重复的目标路径：%s" % rel)
        nl, bom = decode_strict(data)[1:]
        text = new_text
        if nl == "\r\n" and "\r\n" not in text:
            text = text.replace("\n", "\r\n")
        payload = text.encode("utf-8")
        if bom:
            payload = b"\xef\xbb\xbf" + payload
        self.entries.append({
            "path": rel, "op": operation,
            "sha_before": cur, "sha_after": sha256_bytes(payload),
            "data": payload,
        })
        return self

    # -- journal -------------------------------------------------------- #
    def _journal_path(self) -> Path:
        return self.dir / "journal.json"

    def _write_journal(self):
        self.journal["entry_count"] = len(self.journal.get("entries", []))
        self.journal["checksum"] = journal_checksum(self.journal)
        self.dir.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(self._journal_path(),
                           json.dumps(self.journal, ensure_ascii=False,
                                      indent=2, sort_keys=True).encode("utf-8"))

    def _set_state(self, state: str):
        self.journal["state"] = state
        self.journal["updated"] = time.time()
        self._write_journal()

    def _prepare(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "backup").mkdir(parents=True, exist_ok=True)
        entries = []
        for e in self.entries:
            src = self.root / e["path"]
            raw = src.read_bytes()
            dst = self.dir / "backup" / e["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(dst, raw)
            bsha = sha256_bytes(raw)
            if bsha != e["sha_before"]:
                raise SafeIOError("备份校验失败：%s（复制后哈希变了）" % e["path"])
            entries.append({"path": e["path"], "op": e["op"],
                            "sha_before": e["sha_before"], "sha_after": e["sha_after"],
                            "backup": (Path("backup") / e["path"]).as_posix(),
                            "backup_sha256": bsha, "state": "staged"})
        self.journal = {
            "schema_version": JOURNAL_SCHEMA,
            "transaction_id": self.id,
            "root_id": root_id(self.root),
            "pid": os.getpid(),
            "host": host_name(),
            "session": self.session,
            "created": time.time(),
            "updated": time.time(),
            "state": S_PREPARED,
            "entry_count": len(entries),
            "entries": entries,
        }
        self._write_journal()

    # -- commit --------------------------------------------------------- #
    def commit(self):
        if not self.entries:
            raise SafeIOError("事务没有任何条目")
        self._prepare()
        self._set_state(S_APPLYING)
        written = []
        try:
            for e in self.entries:
                p = self.root / e["path"]
                cur = sha256_bytes(p.read_bytes()) if p.is_file() else ""
                if cur != e["sha_before"]:
                    raise Conflict("提交前复检失败，%s 已被其他会话改动" % e["path"])
                atomic_write_bytes(p, e["data"], mode_from=p)
                written.append(e)
                self._mark_entry(e["path"], "written")
            self._set_state(S_COMMITTED)
            self._committed = True
        except Exception:
            self._set_state(S_ROLLING_BACK)
            conflicts = self._rollback(written)
            if conflicts:
                self._set_state(S_ROLLBACK_CONFLICT)
            else:
                self._set_state(S_ROLLED_BACK)
            raise
        finally:
            if self._committed:
                shutil.rmtree(self.dir, ignore_errors=True)
        return [{k: e[k] for k in ("path", "op", "sha_before", "sha_after")}
                for e in self.entries]

    def _mark_entry(self, rel: str, state: str):
        for ent in self.journal["entries"]:
            if ent["path"] == rel:
                ent["state"] = state
        self._write_journal()

    def _rollback(self, written):
        """回滚：只对「当前 == sha_after」的文件恢复备份；被第三方改过的不覆盖。"""
        conflicts = []
        for e in written:
            p = self.root / e["path"]
            cur = sha256_bytes(p.read_bytes()) if p.is_file() else ""
            if cur == e["sha_before"]:
                continue                       # 已经是原样，不用动
            if cur != e["sha_after"]:
                conflicts.append(e["path"])    # 第三方改动：不覆盖
                continue
            entry = next((x for x in self.journal["entries"]
                          if x["path"] == e["path"]), None)
            backup = self.dir / entry["backup"] if entry else None
            if not backup or not backup.is_file():
                conflicts.append(e["path"])
                continue
            raw = backup.read_bytes()
            if sha256_bytes(raw) != entry["backup_sha256"]:
                conflicts.append(e["path"])    # 备份坏了：宁可留下现场
                continue
            atomic_write_bytes(p, raw, mode_from=p)
        return conflicts


# --------------------------------------------------------------------------- #
# 事务检查与恢复
# --------------------------------------------------------------------------- #

def _load_journal(tdir: Path):
    """返回 (journal, error)。error 非空表示不可信，任何自动清理都必须放弃。"""
    j = tdir / "journal.json"
    if not j.is_file():
        return None, "journal.json 缺失"
    try:
        data = json.loads(j.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, "journal.json 不可读：%s" % exc
    if not isinstance(data, dict):
        return None, "journal.json 不是对象"
    if data.get("schema_version") != JOURNAL_SCHEMA:
        return None, "journal schema_version=%r 不受支持" % data.get("schema_version")
    checksum = data.get("checksum")
    if not checksum:
        return None, "journal 缺少 checksum"
    if checksum != journal_checksum(data):
        return None, "journal checksum 不匹配（文件被改过或写了一半）"
    if data.get("state") not in VALID_STATES:
        return None, "journal state=%r 非法" % data.get("state")
    if not isinstance(data.get("entries"), list):
        return None, "journal entries 不是数组"
    return data, None


def pending_transactions(root):
    """列出事务目录。不可读的也列出来，但带 error 且 entries=[]，绝不是「零文件事务」。

    两种布局都要认：
      `.kb-txn/journal.json`          —— Transaction 正在/曾经进行中的现场
      `.kb-txn/<id>/journal.json`     —— 归档/测试构造的独立事务目录
    早先只扫子目录，导致真正崩溃留下的 `.kb-txn/journal.json` 对 recover 不可见。
    """
    d = Path(root) / TXN_DIR
    out = []
    if not d.is_dir():
        return out
    dirs = []
    if (d / "journal.json").is_file():
        dirs.append(d)
    for sub in sorted(x for x in d.iterdir() if x.is_dir()):
        if sub.name == "backup" and not (sub / "journal.json").is_file():
            continue
        dirs.append(sub)
    for sub in dirs:
        data, err = _load_journal(sub)
        out.append({"dir": str(sub), "journal": data, "error": err,
                    "readable": err is None})
    return out


def _classify(root: Path, journal: dict):
    """逐文件判定：written / untouched / changed-by-others / missing / backup-corrupt。"""
    from . import scope
    rows, problems = [], []
    seen = set()
    for e in journal.get("entries", []):
        rel = e.get("path")
        row = {"path": rel, "op": e.get("op"), "sha_before": e.get("sha_before"),
               "sha_after": e.get("sha_after"), "sha_now": None, "state": None,
               "backup_ok": None, "note": ""}
        try:
            scope.check_rel_path(root, rel or "")
        except Exception as exc:
            row["state"] = "invalid-path"
            row["note"] = str(exc)
            problems.append(row)
            rows.append(row)
            continue
        if rel in seen:
            row["state"] = "duplicate-path"
            row["note"] = "同一事务里重复路径"
            problems.append(row)
            rows.append(row)
            continue
        seen.add(rel)
        p = root / rel
        row["sha_now"] = sha256_bytes(p.read_bytes()) if p.is_file() else ""
        if not p.is_file():
            row["state"] = "missing"
        elif row["sha_now"] == e.get("sha_after"):
            row["state"] = "written"
        elif row["sha_now"] == e.get("sha_before"):
            row["state"] = "untouched"
        else:
            row["state"] = "changed-by-others"
            problems.append(row)
        backup_rel = e.get("backup") or ""
        bpath = Path(journal.get("_dir") or ".") / backup_rel if backup_rel else None
        if (not backup_rel or Path(backup_rel).is_absolute()
                or ".." in Path(backup_rel).parts):
            row["backup_ok"] = False
            row["note"] = (row["note"] + " 备份路径非法").strip()
            problems.append(row)
        elif not bpath.is_file():
            row["backup_ok"] = False
            row["note"] = (row["note"] + " 备份缺失").strip()
            problems.append(row)
        else:
            ok = sha256_bytes(bpath.read_bytes()) == e.get("backup_sha256")
            row["backup_ok"] = ok
            if not ok:
                row["state"] = "backup-corrupt"
                row["note"] = (row["note"] + " 备份哈希不匹配").strip()
                problems.append(row)
        rows.append(row)
    return rows, problems


def _report(root: Path, txn: dict, apply: bool) -> dict:
    report = {"dir": txn["dir"], "readable": txn["readable"], "error": txn["error"],
              "manual": False, "entries": [], "counts": {}, "action": "plan"}
    if not txn["readable"]:
        report["manual"] = True
        report["action"] = "manual-recovery-required"
        report["message"] = ("journal 不可信（%s）：保留事务目录与备份，未做任何清理。"
                             "人工确认后手动处理。" % txn["error"])
        return report
    journal = dict(txn["journal"])
    journal["_dir"] = txn["dir"]
    rows, problems = _classify(root, journal)
    counts = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    report.update({"id": journal.get("transaction_id"), "state": journal.get("state"),
                   "session": journal.get("session"), "created": journal.get("created"),
                   "entries": rows, "counts": counts,
                   "requires_manual": bool(problems) or journal.get("state") in (
                       S_ROLLBACK_CONFLICT, S_MANUAL)})
    if apply:
        report["action"] = _apply_one(root, report, journal, rows, problems)
    elif report["requires_manual"]:
        report["action"] = "manual-recovery-required"
    else:
        report["action"] = "plan"
    return report


def inspect_transactions(root) -> list:
    """只读检查，返回可直接打印的报告。"""
    root = Path(root).resolve()
    return [_report(root, txn, apply=False) for txn in pending_transactions(root)]


def recover(root, mode: str = "inspect", force: bool = False) -> list:
    """恢复入口。

    mode:
      inspect  只读
      dry-run  只读，但给出将执行的动作（同 inspect，动作字段为 plan）
      apply    持锁执行；证据不足时保留现场并要求人工介入
    """
    root = Path(root).resolve()
    if mode not in ("inspect", "dry-run", "apply"):
        raise SafeIOError("未知 recover 模式：%r" % mode)
    if mode != "apply":
        return inspect_transactions(root)
    lock = WorkspaceLock(root)
    lock.acquire()
    try:
        return [_report(root, txn, apply=True) for txn in pending_transactions(root)]
    finally:
        lock.release()


def _apply_one(root: Path, report: dict, journal: dict, rows, problems) -> str:
    tdir = Path(report["dir"])
    if problems:
        return ("manual-recovery-required（%d 个文件有问题：%s）；保留事务目录与备份"
                % (len(problems), ", ".join(sorted({p["state"] for p in problems}))))

    states = [r["state"] for r in rows]
    if journal.get("state") == S_COMMITTED or all(s == "written" for s in states):
        shutil.rmtree(tdir, ignore_errors=True)
        return "cleaned（全部已写入，仅清 journal）"
    if all(s == "untouched" for s in states):
        shutil.rmtree(tdir, ignore_errors=True)
        return "cleaned（没有任何文件被改，仅清 journal）"

    # 部分写入：回滚已写文件（sha_after → sha_before）
    restored = []
    for r in rows:
        if r["state"] != "written":
            continue
        entry = next(e for e in journal["entries"] if e["path"] == r["path"])
        backup = tdir / entry["backup"]
        if not backup.is_file():
            return "manual-recovery-required（备份缺失：%s）" % r["path"]
        raw = backup.read_bytes()
        if sha256_bytes(raw) != entry["backup_sha256"]:
            return "backup-corrupt（%s 的备份哈希不匹配，拒绝写回）" % r["path"]
        target = root / r["path"]
        atomic_write_bytes(target, raw, mode_from=target)
        restored.append(r["path"])
    shutil.rmtree(tdir, ignore_errors=True)
    return "rolled-back（已恢复 %d 个文件：%s）" % (len(restored), ", ".join(restored))
