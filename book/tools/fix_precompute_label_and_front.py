#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_precompute_label_and_front.py —— ①precompute 的 docs 口径标签订正 ②前言数字按最终实跑更新（2026-10-22）。

① docs md 20 件 = 主体 19 + 收尾文档 1 + wiki 0（锚点处无 wiki），原标签把 20 全算成"主体"。
② 前言里的两个数是本轮中途值：工具脚本 22 → 32 支；坐标引用 619 → 697（全部可解析）。
"""
import io
import sys

REPO = r"%WORKSPACE%\forensics-learning-book"
JOBS = [
    (r"%WORKSPACE%\forensics-learning-book\tools\precompute_frontback_facts.py",
     '''print(f"  docs md: {len(docs_all)} 件（锚点处实存；主体 {len([d for d in docs_all if '/wiki/' not in d])} 件"
      f" + wiki {len([d for d in docs_all if '/wiki/' in d])} 件）")''',
     '''_主体 = len([d for d in docs_all if "/wiki/" not in d and "收尾" not in d])
_收尾 = len([d for d in docs_all if "收尾" in d])
_wiki = len([d for d in docs_all if "/wiki/" in d])
print(f"  docs md: {len(docs_all)} 件（锚点处实存 = 主体 {_主体} + 收尾文档 {_收尾} + wiki {_wiki}）")'''),
    (r"%WORKSPACE%\forensics-learning-book\前言.md",
     "| 坐标引用 | **619 处，可解析 619，失败 0** |",
     "| 坐标引用 | **697 处，可解析 697，失败 0** |"),
    (r"%WORKSPACE%\forensics-learning-book\前言.md",
     "| 工具脚本 | 22 支 | 本书仓 `tools/` |",
     "| 工具脚本 | 32 支 | 本书仓 `tools/` |"),
    (r"%WORKSPACE%\forensics-learning-book\尾声.md",
     "| 三个仓库在各自锚点上的坐标可被第三方逐条复核 | 全书（22 章 + 前言 + 尾声）坐标 619 处，可解析 619、失败 0 |",
     "| 三个仓库在各自锚点上的坐标可被第三方逐条复核 | 全书（22 章 + 前言 + 尾声）坐标 697 处，可解析 697、失败 0 |"),
    (r"%WORKSPACE%\forensics-learning-book\尾声.md",
     "规模数（全书 619 引用 619 可解析 0 失败 /",
     "规模数（全书 697 引用 697 可解析 0 失败 /"),
]

fail = 0
cache = {}
for path, old, new in JOBS:
    if path not in cache:
        cache[path] = io.open(path, encoding="utf-8").read()
    t = cache[path]
    n = t.count(old)
    if n != 1:
        print(f"[SKIP 命中 {n} 次] {path}: {old[:60]!r}")
        fail += 1
        continue
    cache[path] = t.replace(old, new)
    print(f"[OK] {path.split(chr(92))[-1]}: {old[:50]!r}")
for path, t in cache.items():
    io.open(path, "w", encoding="utf-8", newline="\n").write(t)
print("失败条数：", fail)
sys.exit(1 if fail else 0)
