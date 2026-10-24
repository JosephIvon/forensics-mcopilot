#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_front_numbers_final.py —— 《前言》账面数字定稿（2026-10-22 编排改造后）。

纪律：凡写进书的数字必须由本机实跑得出，且带口径。
本脚本是本轮**最后一支新增工具**：它自己计入工具总数，所以运行后不再新增 .py。
"""
import io
import os
import re
import sys

REPO = r"%WORKSPACE%\forensics-learning-book"
VOLS = [("卷一", "chapters"), ("册一", "chapters-vol2a"), ("册二", "chapters-vol2b")]


def lines_of(p):
    return io.open(p, encoding="utf-8").read().splitlines()


# ── 实跑：章行数 / 导读行数 / 工具数 ────────────────────────────────────
parts, chap_tot, guide_tot = [], 0, 0
for name, d in VOLS:
    base = os.path.join(REPO, d)
    chs = sorted(f for f in os.listdir(base) if f.endswith(".md") and f != "00-导读.md")
    cp = sum(len(lines_of(os.path.join(base, f))) for f in chs)
    gp = len(lines_of(os.path.join(base, "00-导读.md"))) if os.path.isfile(os.path.join(base, "00-导读.md")) else 0
    chap_tot += cp
    guide_tot += gp
    parts.append(f"{name} {cp} + {gp}")
tools = len([f for f in os.listdir(os.path.join(REPO, "tools")) if f.endswith(".py")])
dl_dir = os.path.join(REPO, "decision-lists")
dls = sorted(f for f in os.listdir(dl_dir) if f.endswith(".md"))
print(f"  正文物理行：{' / '.join(parts)}   （章合计 {chap_tot} + 导读合计 {guide_tot} = {chap_tot + guide_tot}）")
print(f"  工具脚本：{tools} 支 py")
print(f"  决策清单：{len(dls)} 份（{', '.join(dls)}）")

# ── 改写《前言》────────────────────────────────────────────────────────
p = os.path.join(REPO, "前言.md")
t = io.open(p, encoding="utf-8").read()
subs = [
    (r"\| 正文 \| 22 章（9 \+ 9 \+ 4）\+ 3 份卷首导读 \| 物理行：[^|]*\|",
     f"| 正文 | 22 章（9 + 9 + 4）+ 3 份卷首导读 | 物理行：{' / '.join(parts)}"
     f"（章合计 {chap_tot} + 导读合计 {guide_tot} = {chap_tot + guide_tot}） |"),
    (r"\| 工具脚本 \| \d+ 支 \|",
     f"| 工具脚本 | {tools} 支 |"),
    (r"6 件裁剪 / \d+ 支工具 / \d+ 份决策清单",
     f"6 件裁剪 / {tools} 支工具 / {len(dls)} 份决策清单"),
]
fail = 0
for pat, rep in subs:
    t2, n = re.subn(pat, rep, t)
    if n != 1:
        print(f"[SKIP] {pat[:40]!r} 命中 {n} 次")
        fail += 1
        continue
    t = t2
    print(f"[OK] {pat[:36]!r}")
if fail:
    sys.exit(1)
io.open(p, "w", encoding="utf-8", newline="\n").write(t)
print("《前言》账面数字已定稿。")
