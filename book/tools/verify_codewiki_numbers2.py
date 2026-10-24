#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_codewiki_numbers2.py —— 按正确口径复核 CodeWiki 数字（2026-10-22）。"""
import io
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


tracked = [f for f in git("ls-files").splitlines() if f]

agents = [f for f in tracked if f.startswith("src/mcopilot/agents/") and f.endswith(".py")
          and not f.endswith("__init__.py")]
core = [f for f in tracked if f.startswith("src/mcopilot/core/") and f.endswith(".py")
        and not f.endswith("__init__.py")]
know = [f for f in tracked if f.startswith("knowledge/")]
samples = [f for f in tracked if f.startswith("samples/")]
off_csv = [f for f in tracked if "official_api" in f and f.lower().endswith(".csv")]
know_dirs = sorted({os.path.dirname(f) for f in know})

print("  agents/ 模块（不含 __init__） =", len(agents), "→", [os.path.basename(f) for f in agents])
print("  core/ 模块（不含 __init__）   =", len(core), "→", [os.path.basename(f) for f in core])
print("  knowledge/ 文件数            =", len(know), "｜ 目录数 =", len(know_dirs))
print("  official_api CSV 数          =", len(off_csv))
print("  samples/ 文件数              =", len(samples))
for f in sorted(samples):
    print("      ", f)

out = os.path.join(tempfile.gettempdir(), "mcopilot_all_probe2")
subprocess.run(["cmd", "/c", "rmdir /s /q", out], capture_output=True)
env = dict(os.environ, PYTHONPATH=os.path.join(MC, "src"))
t0 = time.time()
r = subprocess.run([PY, "-m", "mcopilot", "all", "--out", out], cwd=MC, capture_output=True,
                   text=True, encoding="utf-8", errors="replace", env=env)
dt = time.time() - t0
produced = []
for dp, dns, fns in os.walk(out):
    for fn in fns:
        produced.append(os.path.join(dp, fn))
ext = {}
for p in produced:
    e = os.path.splitext(p)[1].lower()
    ext[e] = ext.get(e, 0) + 1
print(f"\n  mcopilot all（PYTHONPATH=src）: 退出码 {r.returncode} ｜ {dt:.1f} 秒 ｜ 产出 {len(produced)} 个文件")
print("    扩展名分布:", ext)
if r.returncode != 0:
    print("    stderr 尾:", (r.stderr or "")[-300:])
    print("    stdout 尾:", (r.stdout or "")[-300:])
