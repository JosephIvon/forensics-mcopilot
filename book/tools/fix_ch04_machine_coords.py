#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_ch04_machine_coords.py —— 样章 ch04 的坐标"机判化"（2026-10-22）。

问题：章内表格与正文里大量写成"（`:6-8`）"（裸行号，靠上文语境猜是哪个文件），
机器审计判不了 → 等于这些坐标没被核过。
处置：全部改成"（`C4:6-8`）"式（审计器已扩展 C1–C7 别名），让每个行号都进机器判。
"""
import os
import sys

REPO = r"%WORKSPACE%\forensics-learning-book"
PATH = os.path.join(REPO, "chapters-vol2a", "ch04-契约七层与验证门控.md")

PAIRS = [
    ("A-43 例外（`:6-8`）", "A-43 例外（`C4:6-8`）"),
    ("复现校验（`:16-17`）", "复现校验（`C4:16-17`）"),
    ("拟合残差（`:30-31`）", "拟合残差（`C4:30-31`）"),
    ("A-87 约定真值（`:32-39`）", "A-87 约定真值（`C4:32-39`）"),
    ("A-89 两点收窄（`:40-49`）", "A-89 两点收窄（`C4:40-49`）"),
    ("A-90 环境层级（`:50-56`）", "A-90 环境层级（`C4:50-56`）"),
    ("最坏值 <10% 标 `fragile`，`:63-64`）", "最坏值 <10% 标 `fragile`，`C4:63-64`）"),
    ("**必须否决该建议**（`:69-70`）", "**必须否决该建议**（`C4:69-70`）"),
    ("`rule_heuristic`（`:84-87`）", "`rule_heuristic`（`C4:84-87`）"),
    ("（`:38-39`）", "（`C5:38-39`）"),
    ("（`:42`）", "（`C5:42`）"),
    ("（`:46-48`）", "（`C5:46-48`）"),
    ("（`:90-92`）", "（`C5:90-92`）"),
    ("（`:65-66`）", "（`C5:65-66`）"),
    ("（`:86-88`）", "（`C5:86-88`）"),
    ("（`:107-114`）", "（`C5:107-114`）"),
    ("A-89 两点收窄（`:40-49`）。", "A-89 两点收窄（`C4:40-49`）。"),
    ("（`:12`）", "（`docs/DECISION-2026-10-19-方向裁决.md:12`）"),
]

fail = 0
already = 0
text = open(PATH, encoding="utf-8").read()
for old, new in PAIRS:
    n = text.count(old)
    if n == 0:
        already += 1
        continue
    if n != 1:
        print(f"[SKIP 命中 {n} 次] {old}")
        fail += 1
        continue
    text = text.replace(old, new)
open(PATH, "w", encoding="utf-8", newline="\n").write(text)
left = [ln for ln in text.splitlines() if "（`:" in ln or "（`:" in ln]
print(f"改毕；失败 {fail} ｜ 已生效 {already} ｜ 剩余裸行号行 {len(left)}")
for ln in left:
    print("  残留:", ln.strip()[:110])
sys.exit(1 if fail else 0)
