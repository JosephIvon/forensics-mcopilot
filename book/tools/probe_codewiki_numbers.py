#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_codewiki_numbers.py —— 核 CodeWiki_20261022.md 里的数字与现状（2026-10-22）。

规矩：文档里的计数必须与实跑一致；不一致的要么改文档，要么不入库。
"""
import io
import os
import re
import subprocess

MC = r"%WORKSPACE%\mcopilot"
W = os.path.join(MC, "docs", "CodeWiki_20261022.md")
txt = io.open(W, encoding="utf-8", errors="replace").read()
lines = txt.splitlines()
print(f"CodeWiki 行数 = {len(lines)}")

print("\n== 文中出现的计数类表述（带行号）==")
for i, l in enumerate(lines, 1):
    if re.search(r"\d+\s*(项|个|条|页|支|张|类|件|行|文件|模块|智能体|测试|用例)", l):
        s = l.strip()
        if len(s) > 150:
            s = s[:150] + "…"
        print(f"  :{i} {s}")

print("\n== 实测事实 ==")
tracked = subprocess.run(["git", "-C", MC, "ls-files"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout.splitlines()
print(f"  跟踪文件数 = {len(tracked)}")
print(f"  .py 文件数 = {sum(1 for f in tracked if f.endswith('.py'))}")
print(f"  .md 文件数 = {sum(1 for f in tracked if f.lower().endswith('.md'))}")
print(f"  docs/ 下文件数 = {sum(1 for f in tracked if f.startswith('docs/'))}")
src_py = [f for f in tracked if f.startswith("src/") and f.endswith(".py")]
print(f"  src/ 下 .py = {len(src_py)}")
agents = [f for f in src_py if "/agents/" in f]
print(f"  src/*/agents/ 下 .py = {len(agents)}")
r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q",
                    "--collect-only"], cwd=MC, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
m = re.search(r"(\d+) tests collected", r.stdout)
print(f"  pytest 收集用例数 = {m.group(1) if m else '?'}")
r2 = subprocess.run(["git", "-C", MC, "ls-files", "docs/wiki", "docs/CodeWiki*"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace")
print(f"  已有 wiki 文件 = {len([x for x in r2.stdout.splitlines() if x])}")
