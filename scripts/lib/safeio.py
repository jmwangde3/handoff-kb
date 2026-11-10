#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安全写入基础设施（handoff-kb 2.0）

- 全量 SHA-256（文件字节 / 文本）用于乐观并发控制
- 跨平台写锁（原子 mkdir + 进程存活判断；死进程锁可回收，活进程锁不得抢占）
- 单文件原子替换（同目录临时文件 + os.replace，保留原换行风格）
- 多文件事务：先全部校验 → 备份 → 逐个替换 → 失败回滚；有 journal 供 recover

诚实声明：多个 os.replace() 不是跨文件原子事务。这里提供的是
"全量预检 + 备份 + 失败回滚 + 崩溃后 recover"，不是分布式原子性。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

TXN_DIR = ".kb-txn"
LOCK_DIR = ".kb.lock"


class SafeIOError(Exception):
    pass


class LockHeld(SafeIOError):
    pass


class StaleLock(SafeIOError):
    pass


class Conflict(SafeIOError):
    pass


def sha256_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def read_text(path) -> str:
    data = Path(path).read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8", errors="replace")


def dominant_newline(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def atomic_write(path, text: str):
    """写单个文件：同目录临时文件 → fsync → os.replace；沿用原文件的换行风格。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        old = p.read_bytes()
        old_nl = dominant_newline(old.decode("utf-8", errors="replace"))
        if old_nl == "\r\n" and "\r\n" not in text:
            text = text.replace("\n", "\r\n")
    fd, tmp = tempfile.mkstemp(prefix=".kb-tmp-", dir=str(p.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
            if not h:
                return False
            code = ctypes.c_ulong(0)
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        except Exception:
            return True  # 判断不了就当作活着，宁可报锁占用
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


class WorkspaceLock:
    """原子目录锁。锁内 meta.json 记录 pid / 时间 / 会话标识。"""

    def __init__(self, root, timeout: float = 5.0, poll: float = 0.1, session: str = ""):
        self.root = Path(root)
        self.dir = self.root / LOCK_DIR
        self.timeout = timeout
        self.poll = poll
        self.session = session or os.environ.get("KB_SESSION", "")
        self.reclaimed = None
        self._held = False

    def _meta(self):
        try:
            return json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
        except Exception:
            return {}

    def acquire(self):
        deadline = time.time() + self.timeout
        while True:
            try:
                self.dir.mkdir()
                (self.dir / "meta.json").write_text(json.dumps({
                    "pid": os.getpid(), "created": time.time(),
                    "session": self.session, "host": os.uname().nodename
                    if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", ""),
                }, ensure_ascii=False), encoding="utf-8")
                self._held = True
                return self
            except FileExistsError:
                meta = self._meta()
                pid = int(meta.get("pid") or 0)
                if pid and not pid_alive(pid):
                    # 进程已死：可回收，但要在输出里说明，不静默
                    try:
                        shutil.rmtree(self.dir)
                        self.reclaimed = meta
                        continue
                    except OSError:
                        pass
                if time.time() >= deadline:
                    raise LockHeld(
                        "工作区已被占用：%s（pid=%s, session=%s）；等待 %.1fs 超时。"
                        "若确认对方已死，跑 kb-write.py recover --break-lock"
                        % (self.dir, pid or "?", meta.get("session") or "-", self.timeout))
                time.sleep(self.poll)

    def release(self):
        if self._held:
            shutil.rmtree(self.dir, ignore_errors=True)
            self._held = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False


def break_lock(root) -> bool:
    """显式解锁（仅供 recover --break-lock 使用）。"""
    d = Path(root) / LOCK_DIR
    if not d.exists():
        return False
    shutil.rmtree(d, ignore_errors=True)
    return True


class Transaction:
    """多文件写入：全量预检 → 备份 → 逐个 replace → 失败回滚。"""

    def __init__(self, root, session: str = ""):
        self.root = Path(root).resolve()
        self.session = session
        self.dir = self.root / TXN_DIR
        self.id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.entries = []
        self.journal = None
        self._committed = False

    def stage(self, rel: str, expected_sha: str, new_text: str, operation: str = "replace"):
        p = Path(self.root) / rel
        if not p.is_file():
            raise SafeIOError("目标文件不存在：%s" % rel)
        cur = sha256_file(p)
        if expected_sha and cur != expected_sha:
            raise Conflict("哈希冲突：%s\n  期望 %s\n  实际 %s\n"
                           "  处理：重新 read 该文件，合并后重试（不覆盖任何内容）"
                           % (rel, expected_sha, cur))
        self.entries.append({
            "path": rel, "op": operation,
            "sha_before": cur, "sha_after": sha256_bytes(new_text.encode("utf-8")),
            "content": new_text,
        })
        return self

    def _prepare(self):
        (self.dir / "backup").mkdir(parents=True, exist_ok=True)
        for e in self.entries:
            src = self.root / e["path"]
            dst = self.dir / "backup" / e["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        self.journal = {
            "schema_version": 1, "id": self.id, "pid": os.getpid(),
            "created": time.time(), "session": self.session, "state": "prepared",
            "entries": [{k: e[k] for k in ("path", "op", "sha_before", "sha_after")}
                        for e in self.entries],
        }
        self._write_journal()

    def _write_journal(self):
        (self.dir / "journal.json").write_text(
            json.dumps(self.journal, ensure_ascii=False, indent=2), encoding="utf-8")

    def commit(self):
        self._prepare()
        written = []
        try:
            for e in self.entries:
                p = self.root / e["path"]
                cur = sha256_file(p)
                if cur != e["sha_before"]:
                    raise Conflict("提交前复检失败，%s 已被其他会话改动" % e["path"])
                atomic_write(p, e["content"])
                written.append(e)
            self.journal["state"] = "committed"
            self._write_journal()
            self._committed = True
        except Exception:
            for e in written:
                backup = self.dir / "backup" / e["path"]
                if backup.exists():
                    atomic_write(self.root / e["path"], read_text(backup))
            self.journal["state"] = "rolled_back"
            try:
                self._write_journal()
            except Exception:
                pass
            raise
        finally:
            if self._committed:
                shutil.rmtree(self.dir, ignore_errors=True)
        return [{k: e[k] for k in ("path", "op", "sha_before", "sha_after")}
                for e in self.entries]


def pending_transactions(root):
    d = Path(root) / TXN_DIR
    out = []
    if not d.is_dir():
        return out
    for sub in sorted(d.iterdir()):
        j = sub / "journal.json"
        if not j.is_file():
            continue
        try:
            data = json.loads(j.read_text(encoding="utf-8"))
        except Exception:
            data = {"state": "unreadable", "entries": []}
        data["_dir"] = str(sub)
        out.append(data)
    return out


def recover(root, apply: bool = False):
    """检查未完成事务，逐文件判定：已写入 / 未写入 / 被他人改动。"""
    root = Path(root).resolve()
    reports = []
    for txn in pending_transactions(root):
        tdir = Path(txn["_dir"])
        entries = []
        conflicts = 0
        done = incomplete = 0
        for e in txn.get("entries", []):
            p = root / e["path"]
            cur = sha256_file(p) if p.is_file() else ""
            if cur and cur == e.get("sha_after"):
                state = "written"
                done += 1
            elif cur and cur == e.get("sha_before"):
                state = "untouched"
                incomplete += 1
            else:
                state = "changed-by-others"
                conflicts += 1
            entries.append({"path": e["path"], "state": state,
                            "sha_now": cur, "sha_before": e.get("sha_before"),
                            "sha_after": e.get("sha_after")})
        report = {"id": txn.get("id"), "state": txn.get("state"),
                  "session": txn.get("session"), "entries": entries,
                  "conflicts": conflicts, "written": done, "untouched": incomplete}
        if apply:
            if conflicts:
                report["action"] = "kept（有文件被他人改动，拒绝自动恢复）"
            elif done == len(entries):
                shutil.rmtree(tdir, ignore_errors=True)
                report["action"] = "cleaned（全部写入已完成，仅清日志）"
            elif done == 0:
                shutil.rmtree(tdir, ignore_errors=True)
                report["action"] = "cleaned（未写入任何文件）"
            else:
                for e in entries:
                    if e["state"] == "written":
                        backup = tdir / "backup" / e["path"]
                        if backup.exists():
                            atomic_write(root / e["path"], read_text(backup))
                shutil.rmtree(tdir, ignore_errors=True)
                report["action"] = "rolled-back（部分写入已回滚到备份）"
        else:
            report["action"] = "plan"
        reports.append(report)
    return reports
