#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_scale_counts_at_anchor.py —— 按锚点 commit 复核书里引用的规模数（2026-10-22）。

起因：axiscope 在锚点 `b95ffb2` 之后有提交（KB0 +7/-3、新增 7 篇 wiki），
书里"知识库 8 件 8142 行""docs 19 件（实存 27）"这类数字必须与**锚点处**一致。
本脚本在锚点 commit 上重数：KB 8 件总物理行、docs md 件数、契约件数与行数、
src/tests 件数与非空行、synth/bench 行数；并与工作树（HEAD）对照，列出差异。
"""
import io
import os
import subprocess
import sys
from _localenv import expand

AXI = expand(r"%WORKSPACE%\axiscope")
TRAE = expand(r"%WORKSPACE%\trae_factory")
ANCHOR = "b95ffb2"
HEAD = "a57e67b"

KBS = ["KB0-conventions.md", "KB2-waveform-formats.md", "KB3-tuning-rules.md",
       "KB4-attribution-model.md", "KB5-simulation-plant.md",
       "KB6-coupling-and-calibration.md", "KB7-dataset-da-rus-cat.md",
       "KB8-benchmark-cases.md"]


def at(rev, path):
    r = subprocess.run(["git", "-C", AXI, "show", f"{rev}:{path}"], capture_output=True)
    return None if r.returncode else r.stdout.decode("utf-8", "replace").splitlines()


def tree_md(rev):
    r = subprocess.run(["git", "-C", AXI, "ls-tree", "-r", "--name-only", rev, "docs/"],
                       capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l.endswith(".md")]


def tree_files(rev, d, ext):
    r = subprocess.run(["git", "-C", AXI, "ls-tree", "-r", "--name-only", rev, d],
                       capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l.endswith(ext)]


print(f"=== axiscope @{ANCHOR}（书中锚点）===")
tot = 0
for f in KBS:
    lines = at(ANCHOR, f"docs/kb/{f}")
    tot += len(lines)
    print(f"  docs/kb/{f}: {len(lines)} 行")
print(f"  KB 8 件合计物理行 = {tot}")
cs = tree_files(ANCHOR, "docs/contracts", ".md")
cl = sum(len(at(ANCHOR, p) or []) for p in cs)
print(f"  契约 {len(cs)} 件 / {cl} 行")
md = tree_md(ANCHOR)
wiki = [p for p in md if "/wiki/" in p]
closed = [p for p in md if "收尾" in p]
print(f"  docs md 实存 {len(md)} 件 = 主体 {len(md)-len(wiki)-len(closed)} + wiki {len(wiki)} + 收尾 {len(closed)}")
print(f"    wiki: {wiki}")
print(f"    收尾: {closed}")
for d, ext in (("src/axiscope", ".py"), ("tests", ".py"), ("synth", ".py")):
    fs = tree_files(ANCHOR, d, ext)
    phys = sum(len(at(ANCHOR, p) or []) for p in fs)
    ne = sum(sum(1 for l in (at(ANCHOR, p) or []) if l.strip()) for p in fs)
    print(f"  {d}: {len(fs)} 件 / 物理 {phys} / 非空 {ne}")
bench = tree_files(ANCHOR, "bench", "")  # bench 顶层文件
top = [p for p in bench if p.count("/") == 1]
bl = sum(len(at(ANCHOR, p) or []) for p in top)
print(f"  bench 顶层 {len(top)} 件 / {bl} 行")

print(f"\n=== 对照：工作树 HEAD（{HEAD}）===")
wt_kb = sum(len(io.open(os.path.join(AXI, "docs", "kb", f), encoding="utf-8",
                          errors="replace").read().splitlines()) for f in KBS)
wt_md = []
for dp, _dn, fn in os.walk(os.path.join(AXI, "docs")):
    wt_md += [f for f in fn if f.endswith(".md")]
print(f"  KB 8 件合计物理行 = {wt_kb}")
print(f"  docs md 实存 {len(wt_md)} 件")
print("\n（书中现值：知识库 8 件 8142 行 / docs 19 件（实存 27）——需按锚点订正）")
