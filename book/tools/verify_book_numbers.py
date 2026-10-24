#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_book_numbers.py —— 核书里「带文件名的数字」是不是真的。

纪律：书里凡是**指着某个文件说它有多少行 / 多少条 / 多少个锚点**的地方，
那个数字必须与读者打开该文件时数出来的**一致**。

为什么要有这道门禁（2026-10-24 实测出来的）：
  · 坐标门禁 `audit_vol2_coords.py` 只查「行号**在不在范围内**」——
    文件长到 171 行，书里还写着「132 行」「14 锚点」，它照样判 OK。
    **范围合法 ≠ 指向正确**，这是最坏的一种假绿。
  · 实测抓到 8 处过期数字：第 2 章的 anchors.json 行数与 4 类 role 区间
    （文件长过、行号没跟着走），第 3 章两支门禁脚本行数，第 4 章
    validate_comm_log.py 行数，第 7 章 MANIFEST 落点。
  · 书的论点就是「每条主张都能被读者当场核」——**自己书里的数字过不了这一关，
    论点就自破**。

判据：扫书里的 `` `路径`（N 行/文件/条/锚点） `` 形态，取 N，
按仓内路径解出那个文件，数出实际值，与 N 比。不等 = 失败。

刻意不做的：
  · **不核聚合数**（如「契约 7 件 2943 行」）——那些是**别个仓**的数或
    **带日期的历史实跑数**（"2026-10-22 本机实跑转录"），改了就是篡改历史。
  · **不核解不出来的**——路径写错或指向仓外原件时只计数、只喊出来，不判失败。

用法：
    python book/tools/verify_book_numbers.py
退出码：0 = 全部一致（可能含"解不出、只计数"的条目）；1 = 有对不上的数字。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from pathlib import Path
# 本脚本要往 stdout 打中文。控制台编码不是 UTF-8 时，`print` 会抛
# UnicodeEncodeError —— 脚本于是**崩在打印上**，而不是给出判定。
# 2026-10-24 在 GitHub Actions runner 上实测：那边控制台是 cp1252，
# 本机是 UTF-8 —— 于是本机绿、runner 红。处置与本仓其他脚本一致
# （见 scripts/verify_doc_refs.py、scripts/fault_farm.py）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - 环境相关
    pass

BOOK = Path(__file__).resolve().parents[1]
REPO = BOOK.parent

# 书里正文 + 证据层（不含 tools/、decision-lists/——那些是过程产物不是正文）
SCAN_DIRS = [BOOK / "chapters", BOOK]
SCAN_FILES = [BOOK / "前言.md", BOOK / "尾声.md", BOOK / "ASSETS.md",
              BOOK / "OUTLINE.md", BOOK / "README.md"]

# `路径`（N 行） / 路径（N 条）  —— 路径可带反引号
CLAIM = re.compile(
    r"(?P<path>`[^`]+`|[^\s（(，、；;]+?)\s*[（(]\s*(?P<n>\d+)\s*"
    r"(?P<unit>行|文件|条|锚点|项|支|处|份|件)\s*[）)]")

# 只有这些后缀的路径才当"文件"处理（否则「9 章 + 1 份导读」这类聚合数会被误抓）
FILE_EXT = (".py", ".json", ".md", ".ps1", ".toml", ".csv", ".txt", ".yaml", ".yml")


def _count_files(p: Path) -> int:
    return len([f for f in os.listdir(p) if (p / f).is_file()])


def _count_json_entries(p: Path, unit: str):
    """JSON 的"条"按数组长度数（signatures / anchors）；数不出就回 None。"""
    try:
        data = json.loads(io.open(p, encoding="utf-8").read())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    for key in ("signatures", "anchors"):
        if key in data and isinstance(data[key], list):
            return len(data[key])
    return None


def _actual(p: Path, unit: str):
    if unit == "文件":
        return _count_files(p) if p.is_dir() else None
    if unit in ("条", "锚点", "项"):
        n = _count_json_entries(p, unit)
        if n is not None:
            return n
    if p.is_file():
        return len(io.open(p, encoding="utf-8", errors="replace").read().splitlines())
    return None


def _resolve(rel: str):
    """按 仓根 → 书根 → 章目录 → 全仓同名 的顺序找那个文件。"""
    rel = rel.strip("`").replace("/", os.sep)
    for base in (REPO, BOOK, BOOK / "chapters"):
        p = base / rel
        if p.is_file():
            return p
    if os.sep not in rel:
        for dirpath, dirs, files in os.walk(REPO):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "out", "build")]
            if rel in files:
                return Path(dirpath) / rel
    return None


ROLE_CLAIM = re.compile(r"\b([a-z_]+)=(\d+)\b")


def check_role_breakdown(targets) -> tuple[int, int]:
    """核对书里「按 role 分账：spec_pdf=7、source_snapshot=1、…」这类**自由文本** ✓。

    为什么单列一条 ✓
    ---------------
    上面那套 `CLAIM` 只认 `` `路径`（N 行/锚点） `` 形态 ✓ ——
    role 分账写成 `spec_pdf=7、…` 时它看不见 ✓，
    于是锚点表一改、分账数字就静默过期（2026-10-25 实测踩到：
    补一个 `vendor_csharp_binding` 锚点后 `vendor_csharp_binding=1` 就错了 ✓，
    而门禁一声不响 ✓）。
    这条把它一起盯上：凡出现 `xxx=N` 且 xxx 是 anchors.json 里真实存在的 role，
    就必须等于实际条数 ✓。

    returns: (核对数, 失败数)
    """
    p = REPO / "knowledge" / "protocols" / "anchors.json"
    if not p.is_file():
        return 0, 0
    data = json.loads(io.open(p, encoding="utf-8").read())
    roles: dict[str, int] = {}
    for a in data.get("anchors", []):
        r = a.get("role")
        if r:
            roles[r] = roles.get(r, 0) + 1
    if not roles:
        return 0, 0
    checked = bad = 0
    for t in targets:
        if not t.is_file():
            continue
        for no, line in enumerate(io.open(t, encoding="utf-8").read().splitlines(), 1):
            for m in ROLE_CLAIM.finditer(line):
                role, n = m.group(1), int(m.group(2))
                if role not in roles:
                    continue
                checked += 1
                if roles[role] != n:
                    print(f"  !! {t.relative_to(REPO)} L{no}  role `{role}={n}`"
                          f" → 实际 {roles[role]}")
                    print(f"     anchors.json 里 {role} 实际 {roles[role]} 条；"
                          f"书里写的 {n} 已过期")
                    bad += 1
    return checked, bad


def main() -> int:
    targets = []
    for d in SCAN_DIRS:
        if d.is_dir():
            targets += [p for p in sorted(d.glob("*.md")) if p.parent == d or d == BOOK / "chapters"]
    targets += [p for p in SCAN_FILES if p.is_file()]

    seen = set()
    bad = 0
    checked = 0
    unresolved = 0
    for t in targets:
        if not t.is_file():
            continue
        for no, line in enumerate(io.open(t, encoding="utf-8").read().splitlines(), 1):
            for m in CLAIM.finditer(line):
                rel = m.group("path")
                n = int(m.group("n"))
                unit = m.group("unit")
                if not rel.endswith(FILE_EXT) and "/" not in rel and os.sep not in rel:
                    continue
                key = (str(t), no, m.group(0))
                if key in seen:
                    continue
                seen.add(key)
                p = _resolve(rel)
                if p is None:
                    unresolved += 1
                    continue
                actual = _actual(p, unit)
                if actual is None:
                    unresolved += 1
                    continue
                checked += 1
                if actual != n:
                    print(f"  !! {t.relative_to(REPO)} L{no}  `{rel}`（{n} {unit}）"
                          f" → 实际 {actual}")
                    print(f"     {rel} 实际 {actual} {unit}；书里写的 {n} {unit} 已过期")
                    bad += 1
    role_checked, role_bad = check_role_breakdown(targets)
    bad += role_bad
    if bad:
        print(f"  数字对不上 {bad} 处 —— 读者按书里的数字去数，数不出来。")
        return 1
    print(f"  已核 {checked} 处带文件名的数字" +
          (f"、{role_checked} 处 role 分账" if role_checked else "") + "，全部一致"
          + (f"（另有 {unresolved} 处解不出，只计数不判失败）" if unresolved else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
