#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_frontback_numbers.py —— 前言/尾声里的数字改为本机实测值（2026-10-22）。

起因：初稿有三个数是估的，不是量的：册一行数（估 1796，实测 1730）、工具脚本数（估 18，实测 22）、
坐标引用数（写 570/569，实测全书 619/619 —— 审计器补了 pending 目录、self-improving、mcopilot-external
三个根目录，并把卷一 9 章与前言尾声一并纳入后，LTDMC.cs:891 这条厂商原件指针也能解析了）。
纪律：书里的数字必须由脚本打印，且带口径。
"""
import io
import os
import sys

REPO = r"%WORKSPACE%\forensics-learning-book"
PAIRS = [
    ("前言.md",
     "| 正文 | 22 章（9 + 9 + 4） | 物理行：卷一 2006 / 册一 1796 / 册二 735 |",
     "| 正文 | 22 章（9 + 9 + 4） | 物理行：卷一 2006 / 册一 1730 / 册二 735 |"),
    ("前言.md",
     "| 坐标引用 | 570 处，可解析 569，**失败 0** | 唯一未解析者：`LTDMC.cs:891` 是厂商原件，故意不入仓 |",
     "| 坐标引用 | **619 处，可解析 619，失败 0** | 全书 22 章 + 前言 + 尾声逐条解析回源文件并打印被引行；\n"
     "厂商原件指针（`LTDMC.cs:891`）也已可解析 |"),
    ("前言.md",
     "| 工具脚本 | 18 支 | 本书仓 `tools/` |",
     "| 工具脚本 | 22 支 | 本书仓 `tools/` |"),
    ("尾声.md",
     "| 三个仓库在各自锚点上的坐标可被第三方逐条复核 | 22 章坐标 570 处，可解析 569、失败 0 |",
     "| 三个仓库在各自锚点上的坐标可被第三方逐条复核 | 全书（22 章 + 前言 + 尾声）坐标 619 处，可解析 619、失败 0 |"),
    ("尾声.md",
     "规模数（22 章 570 引用 569 可解析 0 失败 / 契约 7 件 2943 行",
     "规模数（全书 619 引用 619 可解析 0 失败 / 契约 7 件 2943 行"),
]

fail = 0
cache = {}
for rel, old, new in PAIRS:
    path = os.path.join(REPO, rel)
    if path not in cache:
        cache[path] = io.open(path, encoding="utf-8").read()
    t = cache[path]
    n = t.count(old)
    if n != 1:
        print(f"[SKIP 命中 {n} 次] {rel}: {old[:52]!r}")
        fail += 1
        continue
    cache[path] = t.replace(old, new)
    print(f"[OK] {rel}: {old[:44]!r}")
for path, t in cache.items():
    io.open(path, "w", encoding="utf-8", newline="\n").write(t)
print("失败条数：", fail)
sys.exit(1 if fail else 0)
