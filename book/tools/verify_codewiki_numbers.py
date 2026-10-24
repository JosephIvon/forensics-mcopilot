#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_codewiki_numbers.py —— 核 CodeWiki 里每个计数（2026-10-22）。

规矩：文档里的数字要么本机亲跑得到，要么改。逐条列出**实测值 vs 文中值**。
"""
import io
import json
import os
import tempfile
import re
import subprocess
import time

MC = r"%WORKSPACE%\mcopilot"
PY = sys.executable


def git(*a):
    return subprocess.run(["git", "-C", MC] + list(a), capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


tracked = git("ls-files").splitlines()
py_src = [f for f in tracked if f.startswith("src/") and f.endswith(".py")]
lines_src = sum(len(io.open(os.path.join(MC, f.replace("/", os.sep)), encoding="utf-8",
                            errors="replace").read().splitlines()) for f in py_src)
knowledge = [f for f in tracked if f.startswith("knowledge/")]
agents = [f for f in py_src if "/agents/" in f]
core = [f for f in py_src if "/core/" in f]
samples = [f for f in tracked if f.startswith("samples/")]
pdfs = [f for f in tracked if f.lower().endswith(".pdf")]
csvs = [f for f in tracked if f.lower().endswith(".csv")]

print("【CodeWiki 数字核对】")
rows = [
    ("src/ 下 .py 个数", 20, len(py_src)),
    ("src/ 下 .py 总行数", 10143, lines_src),
    ("knowledge/ 文件数", 85, len(knowledge)),
    ("agents/ 模块数", 10, len(agents)),
    ("core/ 模块数", 4, len(core)),
    ("samples/ 文件数", 24, len(samples)),
    ("跟踪的 PDF 份数", 7, len(pdfs)),
    ("跟踪的 CSV 份数", 21, len(csvs)),
    ("verify_*.py 个数", 5, len([f for f in tracked if f.startswith("scripts/verify_") and f.endswith(".py")])),
]
for label, claimed, actual in rows:
    flag = "✓" if claimed == actual else "✗ 文中值有误"
    print(f"  {flag:<10} {label:<24} 文中 {claimed:>6} ｜ 实测 {actual:>6}")

for rel, claimed in [("src/mcopilot/cli.py", 559), ("src/mcopilot/mcp_server.py", 388),
                     ("src/mcopilot/agents/servo.py", 3999)]:
    p = os.path.join(MC, rel.replace("/", os.sep))
    if not os.path.isfile(p):
        print(f"  ✗ 文件不存在 {rel}")
        continue
    n = len(io.open(p, encoding="utf-8", errors="replace").read().splitlines())
    print(f"  {'✓' if n == claimed else '✗ 文中值有误':<10} {rel:<38} 文中 {claimed:>5} ｜ 实测 {n:>5}")

# anchors.json 条数
aj = os.path.join(MC, "knowledge", "protocols", "anchors.json")
d = json.load(io.open(aj, encoding="utf-8"))
items = d.get("items", d.get("anchors", []))
print(f"  {'✓' if len(items) == 14 else '✗ 文中值有误':<10} {'anchors.json 条数':<38} 文中 {14:>5} ｜ 实测 {len(items):>5}")

# servo_rules.json 规则数
sr = os.path.join(MC, "knowledge", "servo_rules.json")
d2 = json.load(io.open(sr, encoding="utf-8"))
rules = d2.get("rules", [])
print(f"  ?         {'servo_rules.json 规则数':<38} 文中   22 ｜ 实测 {len(rules):>5}")

# 固高待追加测试
gt = os.path.join(MC, "tests", "_gts_tests_append.py")
if os.path.isfile(gt):
    t = io.open(gt, encoding="utf-8", errors="replace").read()
    print(f"  ?         {'_gts_tests_append.py 用例数':<38} 文中   14 ｜ 实测 {len(re.findall(r'def test_', t)):>5}")
else:
    print("  ✗ tests/_gts_tests_append.py 不存在")

# pytest 统计
r = subprocess.run([PY, "-m", "pytest", "tests", "-q"], cwd=MC, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
m = re.search(r"(\d+) failed, (\d+) passed, (\d+) skipped", r.stdout)
if m:
    print(f"  ?         {'pytest 实跑':<38} 文中 385 passed / 2 skipped ｜ 实测 {m.group(2)} passed / {m.group(1)} failed / {m.group(3)} skipped")

# `python -m mcopilot all --out` 跑批
out = os.path.join(tempfile.gettempdir(), "mcopilot_all_probe")
subprocess.run(["cmd", "/c", "rmdir /s /q", out], capture_output=True)
t0 = time.time()
r2 = subprocess.run([PY, "-m", "mcopilot", "all", "--out", out], cwd=MC, capture_output=True,
                    text=True, encoding="utf-8", errors="replace")
dt = time.time() - t0
produced = []
for dp, dns, fns in os.walk(out):
    for fn in fns:
        produced.append(os.path.join(dp, fn))
ext = {}
for p in produced:
    e = os.path.splitext(p)[1].lower()
    ext[e] = ext.get(e, 0) + 1
print(f"  ?         {'mcopilot all 产出':<38} 文中 36 文件 / 3.9 秒 ｜ 实测 {len(produced)} 文件 / {dt:.1f} 秒 / 退出码 {r2.returncode}")
print(f"            扩展名分布: {ext}")
