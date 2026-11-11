#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路径与事务的越界防护（P0）。

原则：**不靠字符串前缀判断归属**、**不信任 is_dir()/is_file()**。
每个用例都构造「看起来在库里、实际上在库外」的现场，
断言的是「拒绝 + 保留现场 + 给出诊断」，不是「没崩就行」。

链接类用例：Windows 上普通用户可能没有 symlink 权限，
单个用例会 skip 并写明原因；不依赖链接的用例（前缀混淆、路径穿越、
root_id 不匹配、备份越界、重复恢复）在所有平台都会跑。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import same_path, write_txn  # noqa: E402
from lib import safeio, scope  # noqa: E402


def link_dir(target, link) -> str:
    """建目录链接，返回实际用的方式：symlink / junction。做不到抛 OSError。"""
    link = Path(link)
    if link.exists():
        return "exists"
    if os.name != "nt":
        os.symlink(str(target), str(link), target_is_directory=True)
        return "symlink"
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return "symlink"
    except OSError:
        pass
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise OSError("无法创建目录链接：%s" % (r.stdout + r.stderr).strip())
    return "junction"


def link_file(target, link) -> str:
    link = Path(link)
    if os.name == "nt":
        os.symlink(str(target), str(link))
        return "symlink"
    os.symlink(str(target), str(link))
    return "symlink"


class PathSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kbpath-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "proj"
        self.root.mkdir()
        self.outside = self.tmp / "outside"
        self.outside.mkdir()

    def touch(self, base: Path, rel: str, text="x\n") -> Path:
        p = Path(base) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    # -- 前缀混淆：不需要任何链接 -------------------------------------- #
    def test_sibling_prefix_is_not_inside(self):
        """C:\\proj-backup 不属于 C:\\proj —— 前缀判断会在这里出错。"""
        sib = self.tmp / "proj-backup"
        sib.mkdir()
        f = self.touch(sib, "00_基线.md")
        self.assertFalse(scope.is_within(self.root, f),
                         "同名前缀的兄弟目录必须被判为库外")
        with self.assertRaises(scope.ScopeError):
            scope.check_rel_path(self.root, "../proj-backup/00_基线.md")
        self.assertEqual(scope.real_rel(self.root, f), "")

    def test_walk_does_not_escape_into_sibling(self):
        self.touch(self.root, "05_进度仪表盘.md")
        sib = self.tmp / "proj-backup"
        sib.mkdir()
        self.touch(sib, "秘密.md")
        got = [p.name for p, reason in scope.iter_text_files(self.root) if not reason]
        self.assertIn("05_进度仪表盘.md", got)
        self.assertNotIn("秘密.md", got)

    # -- 文件级链接 ---------------------------------------------------- #
    def test_file_symlink_outside_is_refused(self):
        victim = self.touch(self.outside, "secret.md", "# 库外机密\n")
        try:
            link_file(victim, self.root / "10_固件.md")
        except (OSError, NotImplementedError) as exc:
            self.skipTest("本机无法创建文件符号链接：%s" % exc)
        audit = []
        roles = scope.role_files(self.root, loose=True, audit=audit)
        self.assertNotIn("fact", roles, "越界的 10_*.md 不能冒充事实分册")
        self.assertTrue(any(r == "file-outside" for _, r, _ in audit), audit)
        rows = list(scope.iter_text_files(self.root))
        self.assertTrue(any(r == "symlink-outside" for _, r in rows), rows)
        # 内容绝不能被读到装配链路里
        self.assertNotIn("# 库外机密", "".join(
            p.read_text(encoding="utf-8", errors="replace")
            for p, reason in rows if not reason and scope.is_within(self.root, p)))

    def test_internal_symlink_is_allowed(self):
        real = self.touch(self.root, "10_固件.md", "# 10\n")
        try:
            link_file(real, self.root / "11_运行态.md")
        except (OSError, NotImplementedError) as exc:
            self.skipTest("本机无法创建文件符号链接：%s" % exc)
        roles = scope.role_files(self.root, loose=True)
        names = sorted(p.name for p in roles.get("fact", []))
        self.assertIn("11_运行态.md", names, "库内真实指向的链接应当可用")

    # -- 目录级链接 ---------------------------------------------------- #
    def test_dir_junction_outside_is_pruned(self):
        self.touch(self.outside, "外部.md", "# 不该被读到\n")
        self.touch(self.root, "05_进度仪表盘.md")
        try:
            how = link_dir(self.outside, self.root / "转发目录")
        except (OSError, NotImplementedError) as exc:
            self.skipTest("本机无法创建目录链接（需要 symlink 权限或 mklink）：%s" % exc)
        audit = []
        rows = list(scope.iter_text_files(self.root, audit=audit))
        self.assertTrue(any(r == "dir-outside" for _, r in rows),
                        "越界目录必须产出诊断：%r（方式=%s）" % (rows, how))
        got = [p.name for p, reason in rows if not reason]
        self.assertNotIn("外部.md", got, "越界目录里的文件不得被扫描")

    def test_archive_dir_outside_is_pruned(self):
        self.touch(self.outside, "旧结论.md", "# 库外归档\n")
        try:
            link_dir(self.outside, self.root / "归档")
        except (OSError, NotImplementedError) as exc:
            self.skipTest("本机无法创建目录链接：%s" % exc)
        rows = list(scope.iter_text_files(self.root, include_archive=True))
        self.assertNotIn("旧结论.md", [p.name for p, r in rows if not r])

    def test_shard_dir_outside_is_excluded(self):
        self.touch(self.outside, "2026-11.md", "# 库外流水\n")
        try:
            link_dir(self.outside, self.root / "06_流水")
        except (OSError, NotImplementedError) as exc:
            self.skipTest("本机无法创建目录链接：%s" % exc)
        audit = []
        self.assertEqual(scope.shards(self.root, audit=audit), [],
                         "越界的 06_流水 不能进入分片列表")
        self.assertTrue(any(r == "dir-outside" for _, r, _ in audit), audit)


class TxnSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kbtxnsec-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "proj"
        self.root.mkdir()
        self.outside = self.tmp / "outside"
        self.outside.mkdir()

    def f(self, rel, text="A0\n"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
        return p

    def sha(self, rel):
        return safeio.sha256_file(self.root / rel)

    # -- .kb-txn 越界 --------------------------------------------------- #
    def test_txn_dir_link_outside_blocks_transaction(self):
        self.f("a.md")
        try:
            link_dir(self.outside, self.root / safeio.TXN_DIR)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("本机无法创建目录链接：%s" % exc)
        t = safeio.Transaction(self.root, session="t")
        t.stage("a.md", self.sha("a.md"), "A1\n")
        with self.assertRaises(safeio.SafeIOError) as ctx:
            t.commit()
        self.assertIn("工作区外", str(ctx.exception))
        self.assertEqual(list(self.outside.iterdir()), [],
                         "越界的事务目录里一个字节都不能写")

    def test_recover_refuses_when_txn_dir_escapes(self):
        self.f("a.md")
        write_txn(self.root, "t1", [])
        shutil.rmtree(self.root / safeio.TXN_DIR)
        try:
            link_dir(self.outside, self.root / safeio.TXN_DIR)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("本机无法创建目录链接：%s" % exc)
        marker = self.outside / "keep.txt"
        marker.write_text("外面还有东西\n", encoding="utf-8")
        reports = safeio.recover(self.root, mode="apply")
        self.assertTrue(reports and reports[0]["manual"], reports)
        self.assertIn("工作区外", reports[0]["error"] or reports[0].get("message", ""))
        self.assertTrue(marker.is_file(), "拒绝恢复时不得清理任何外部内容")
        self.assertTrue((self.root / safeio.TXN_DIR).exists(),
                        "越界链接本身也不能被删（那是用户的目录）")

    # -- journal / backup 越界 ------------------------------------------ #
    def test_backup_symlink_outside_is_refused(self):
        """backup/a.md 是指向库外的符号链接 → 读之前就拒，不写回。"""
        a = self.f("a.md", "A0\n")
        d = write_txn(self.root, "t2", [{"path": "a.md", "sha_before": "0" * 64,
                                        "sha_after": self.sha("a.md"),
                                        "backup_bytes": b"Fake\n"}])
        secret = self.outside / "passwd"
        secret.write_bytes(b"root:x:0:0\n")
        (d / "backup" / "a.md").unlink()
        try:
            link_file(secret, d / "backup" / "a.md")
        except (OSError, NotImplementedError) as exc:
            self.skipTest("本机无法创建文件符号链接：%s" % exc)
        reports = safeio.recover(self.root, mode="apply")
        self.assertTrue(reports[0]["manual"], reports)
        self.assertEqual(a.read_bytes(), b"A0\n", "库外内容不得被写进库里")
        self.assertTrue((d / "journal.json").is_file(), "有问题时保留现场")

    # -- 身份与状态 ----------------------------------------------------- #
    def test_root_id_mismatch_refuses_and_keeps_files(self):
        a = self.f("a.md", "A0\n")
        d = write_txn(self.root, "t3",
                      [{"path": "a.md", "sha_before": self.sha("a.md"),
                        "sha_after": "f" * 64, "backup_bytes": b"A0\n"}],
                      state=safeio.S_APPLYING, root_id="moved-elsewhere")
        reports = safeio.recover(self.root, mode="apply")
        self.assertTrue(reports[0]["manual"], reports)
        self.assertIn("root_id", reports[0]["message"])
        self.assertEqual(a.read_bytes(), b"A0\n")
        self.assertTrue((d / "journal.json").is_file(), "身份不符时保留现场")
        self.assertTrue((d / "backup" / "a.md").is_file(), "备份不得删除")

    def test_second_sha_check_stops_overwrite(self):
        """分类时是 written，写回前被改掉 → 必须报 conflict 且不覆盖。

        三个条目：a/b 已写、c 未动 —— 这样才不会走「全部已写入 → 直接清理」分支，
        回滚循环真的会跑起来，第二个 SHA 校验才有机会被发现。
        """
        a = self.f("a.md", "A1\n")
        b = self.f("b.md", "B1\n")
        c = self.f("c.md", "C0\n")
        d = write_txn(self.root, "t4", [
            {"path": "a.md", "sha_before": "a" * 64, "sha_after": self.sha("a.md"),
             "backup_bytes": b"A0\n"},
            {"path": "b.md", "sha_before": "b" * 64, "sha_after": self.sha("b.md"),
             "backup_bytes": b"B0\n"},
            {"path": "c.md", "sha_before": self.sha("c.md"), "sha_after": "c" * 64,
             "backup_bytes": b"C0\n"},
        ], state=safeio.S_APPLYING)
        real = safeio.atomic_write_bytes

        def tamper(path, data, mode_from=None):
            real(path, data, mode_from)
            if same_path(path, a):
                b.write_bytes(b"B-third\n")     # 恢复第一个文件的瞬间改动第二个

        with mock.patch.object(safeio, "atomic_write_bytes", tamper):
            reports = safeio.recover(self.root, mode="apply")
        self.assertIn("conflict", reports[0]["action"], reports)
        self.assertTrue(reports[0]["manual"], "冲突必须标记为需人工介入")
        self.assertEqual(b.read_bytes(), b"B-third\n", "第三方改动不得被覆盖")
        self.assertTrue((d / "journal.json").is_file(), "冲突时保留现场")

    def test_recover_is_idempotent_after_clean(self):
        a = self.f("a.md", "A1\n")
        self.f("b.md", "B0\n")                      # b 未动 → 不是「全部已写入」
        d = write_txn(self.root, "t5", [
            {"path": "a.md", "sha_before": "a" * 64,
             "sha_after": self.sha("a.md"), "backup_bytes": b"A0\n"},
            {"path": "b.md", "sha_before": self.sha("b.md"),
             "sha_after": "b" * 64, "backup_bytes": b"B0\n"},
        ], state=safeio.S_APPLYING)
        first = safeio.recover(self.root, mode="apply")
        self.assertIn("rolled-back", first[0]["action"])
        self.assertFalse(d.exists(), "成功后清理事务目录")
        self.assertEqual(a.read_bytes(), b"A0\n")
        second = safeio.recover(self.root, mode="apply")
        self.assertEqual(second, [], "没有事务时返回空列表，不报错")

    def test_corrupt_journal_keeps_backup(self):
        a = self.f("a.md", "A1\n")
        d = write_txn(self.root, "t6",
                      [{"path": "a.md", "sha_before": "a" * 64,
                        "sha_after": self.sha("a.md"), "backup_bytes": b"A0\n"}])
        j = d / "journal.json"
        data = json.loads(j.read_text(encoding="utf-8"))
        data["entries"][0]["sha_after"] = "e" * 64      # 改内容但不改 checksum
        j.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        reports = safeio.recover(self.root, mode="apply")
        self.assertTrue(reports[0]["manual"])
        self.assertIn("checksum", reports[0]["message"])
        self.assertTrue((d / "backup" / "a.md").is_file(), "损坏时不得删备份")
        self.assertEqual(a.read_bytes(), b"A1\n")

    def test_old_schema_is_not_touched(self):
        self.f("a.md", "A1\n")
        d = write_txn(self.root, "t7",
                      [{"path": "a.md", "sha_before": "a" * 64,
                        "sha_after": "b" * 64}], schema=1)
        reports = safeio.recover(self.root, mode="apply")
        self.assertTrue(reports[0]["manual"])
        self.assertTrue(d.exists(), "不支持的 schema 必须原样保留")


if __name__ == "__main__":
    unittest.main()
