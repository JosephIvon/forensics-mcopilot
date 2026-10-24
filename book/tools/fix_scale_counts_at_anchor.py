#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_scale_counts_at_anchor.py —— 规模数按锚点订正（2026-10-22）。

起因：axiscope 在书中锚点 `b95ffb2` 之后有提交（KB0 +7/-3、新增 7 篇 wiki），
而书里两处规模数是按"另一个状态"写的：
  ① "知识库 8 件 8142 行" —— 锚点处实为 **8141 行**（物理行；8142 是加总笔误）
  ② ch09 的 "docs 19 件 md（… + wiki 7 = 实存 27 件）" —— 锚点处 **没有 wiki**
     （wiki 是锚点后新增），锚点处 docs md 实存 **20 件** = 契约 7 + KB 8 + 审计/裁决 4 + 收尾文档 1
口径统一写作"锚点处物理行 / 件数"。
注：卷一 ch07 的 "knowledge/sdks/ 厂商 SDK 知识 27 件" 是 MANIFEST.txt:6 原文
（未提交快照状态），不在本次订正范围。
"""
import io
import os
import sys

REPO = r"%WORKSPACE%\forensics-learning-book"
PAIRS = [
    ("chapters-vol2a/ch04-契约七层与验证门控.md",
     "而同期入库的是：契约 7 件 2943 行、知识库 8 件 8142 行、",
     "而同期入库的是：契约 7 件 2943 行、知识库 8 件 8141 行（物理行，锚点处实测）、"),
    ("chapters-vol2a/ch04-契约七层与验证门控.md",
     "规模数（契约 7 件 2943 行 / KB 8 件 8142 行 / src 15 py 非空 5,263 行 / tests 18 py 非空 3,743 行 403 项 /",
     "规模数（契约 7 件 2943 行 / KB 8 件 8141 行 / src 15 py 非空 5,263 行（物理 6,039）/ tests 18 py 非空 3,743 行（物理 4,836）403 项 /"),
    ("chapters-vol2a/ch09-文档即代码.md",
     "docs 19 件 md（契约 7 + 知识库 8 + 审计/裁决 5 + wiki 7 = 实存 27 件）",
     "docs 19 件 md（锚点处 docs md 实存 20 件 = 契约 7 + 知识库 8 + 审计/裁决 4 + 收尾文档 1；\n"
     "7 篇 wiki 是锚点之后新增，不属本书被引素材）"),
]

fail = 0
cache = {}
for rel, old, new in PAIRS:
    path = os.path.join(REPO, rel.replace("/", os.sep))
    if path not in cache:
        cache[path] = io.open(path, encoding="utf-8").read()
    t = cache[path]
    n = t.count(old)
    if n != 1:
        print(f"[SKIP 命中 {n} 次] {rel}: {old[:50]!r}")
        fail += 1
        continue
    cache[path] = t.replace(old, new)
    print(f"[OK] {rel}: {old[:46]!r}")
for path, t in cache.items():
    io.open(path, "w", encoding="utf-8", newline="\n").write(t)
print("失败条数：", fail)
sys.exit(1 if fail else 0)
