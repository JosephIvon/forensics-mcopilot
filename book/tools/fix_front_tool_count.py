#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_front_tool_count.py —— 前言工具脚本数定稿（2026-10-22，38 支）。

数会随本轮新增工具变动，因此定稿前最后一次按实数校准；此后本轮不再新增工具脚本。
"""
import io
import os
import sys

REPO = r"%WORKSPACE%\forensics-learning-book"
n = len([f for f in os.listdir(os.path.join(REPO, "tools")) if f.endswith(".py")])
p = os.path.join(REPO, "前言.md")
t = io.open(p, encoding="utf-8").read()
import re
t2, cnt = re.subn(r"\| 工具脚本 \| \d+ 支 \|", f"| 工具脚本 | {n} 支 |", t)
if cnt != 1:
    print(f"[SKIP] 命中 {cnt} 次")
    sys.exit(1)
io.open(p, "w", encoding="utf-8", newline="\n").write(t2)
print(f"[OK] 前言工具脚本数 = {n}")
