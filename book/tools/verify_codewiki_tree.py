#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_codewiki_tree.py —— 逐目录核对 CodeWiki §7.1 知识层地图的行计数（2026-10-22）。"""
import io
import os
import re
import subprocess
from collections import Counter

MC = r"%WORKSPACE%\mcopilot"
tracked = [f for f in subprocess.run(["git", "-C", MC, "ls-files", "knowledge"],
                                     capture_output=True, text=True, encoding="utf-8",
                                     errors="replace").stdout.splitlines() if f]
cnt = Counter(os.path.dirname(f) for f in tracked)
print("== 实际：knowledge/ 各目录文件数 ==")
for d, n in sorted(cnt.items()):
    print(f"  {d:<34} {n}")

w = io.open(os.path.join(MC, "docs", "CodeWiki_20261022.md"), encoding="utf-8").read().splitlines()
print("\n== CodeWiki §7.1 表行（带计数）==")
start = next(i for i, l in enumerate(w) if l.startswith("### 7.1"))
for i in range(start, min(start + 40, len(w))):
    if w[i].startswith("### 7.2"):
        break
    print(f"  :{i+1} {w[i].rstrip()}")
