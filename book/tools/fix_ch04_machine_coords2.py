#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_ch04_machine_coords2.py —— 收掉 ch04 最后两处裸行号（2026-10-22）。

注意：上一版用 PowerShell 内联 python 时被反引号吃掉（markdown 反引号是 PS 转义符），
替换命中 0 处；本版用脚本文件，落盘前先打印命中数，不为 0 就报错退出。
"""
import io
import sys

P = r"%WORKSPACE%\forensics-learning-book\chapters-vol2a\ch04-契约七层与验证门控.md"

PAIRS = [
    ("A-89 两点收窄（`" + ":40-49`）", "A-89 两点收窄（`C4" + ":40-49`）"),
    ("硬门禁那几行（`" + ":76-78`）", "硬门禁那几行（`C5" + ":76-78`）"),
]

t = io.open(P, encoding="utf-8").read()
total = 0
for old, new in PAIRS:
    n = t.count(old)
    print(f"命中 {n} 次: {new}")
    if n == 0:
        continue
    t = t.replace(old, new)
    total += n
io.open(P, "w", encoding="utf-8", newline="\n").write(t)
left = [ln.strip()[:110] for ln in t.splitlines() if "（`:" in ln]
print(f"共替换 {total} 处；剩余裸行号行 {len(left)}")
for ln in left:
    print("  残留:", ln)
sys.exit(0 if not left else 1)
