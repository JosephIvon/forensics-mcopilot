#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_section_ranges.py —— 搬章后章内区间指针的定点清偿（2026-10-22）。

成因：书内区间有两种写法——"§4.4-4.5"（前缀只写一次）与"§2.5-2.6"。
搬章重编只把显式前缀改了，后半截沿用旧章号，成断链（如 §1.4-4.5）。
本脚本只修**章内自指区间**，外部文档引用（KB5 §4.1-4.2 等）一律不动。
"""
import os
import sys

REPO = r"%WORKSPACE%\forensics-learning-book"

PAIRS = [
    ("chapters-vol2b/ch01-代码工厂.md", "§1.4-4.5 接缝与 Virtual 层", "§1.4-1.5 接缝与 Virtual 层"),
    ("chapters-vol2b/ch02-真值链.md", "§2.5-5.6 死路径债与账本分类学", "§2.5-2.6 死路径债与账本分类学"),
    ("chapters-vol2a/ch08-署名与脱敏.md", "§8.3-7.4 门判据与计数口径", "§8.3-8.4 门判据与计数口径"),
]

fail = 0
for rel, old, new in PAIRS:
    path = os.path.join(REPO, rel.replace("/", os.sep))
    text = open(path, encoding="utf-8").read()
    n = text.count(old)
    if n != 1:
        print(f"[SKIP 命中 {n} 次] {rel}: {old}")
        fail += 1
        continue
    open(path, "w", encoding="utf-8", newline="\n").write(text.replace(old, new))
    print(f"[OK] {rel}: {old} → {new}")
print("失败条数：", fail)
sys.exit(1 if fail else 0)
