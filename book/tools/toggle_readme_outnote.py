#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""toggle_readme_outnote.py —— 批 A/B 分笔提交用：开关 README 里那行 out/ 说明（2026-10-22）。

批 A 只收"固高适配器等旧账"，批 B 才收"文档一致性清偿"；两笔都碰 README.md，
所以用这个开关把批 B 的那一行临时摘掉、批 A 提交后再戴回去。
"""
import io
import os
import sys

MC = r"%WORKSPACE%\mcopilot"
P = os.path.join(MC, "README.md")
NEW = "mcopilot motion vectors --file out/golden_vectors.json    # 输出路径；out/ 是本地生成区，不入库"
OLD = "mcopilot motion vectors --file out/golden_vectors.json"

mode = sys.argv[1] if len(sys.argv) > 1 else "off"
txt = io.open(P, encoding="utf-8", newline="").read()
if mode == "off":
    if txt.count(NEW) != 1:
        print(f"✗ 找不到待摘的批 B 行（命中 {txt.count(NEW)}）")
        sys.exit(1)
    txt = txt.replace(NEW, OLD)
elif mode == "on":
    if txt.count(OLD) != 1:
        print(f"✗ 找不到待戴回的原文行（命中 {txt.count(OLD)}）")
        sys.exit(1)
    txt = txt.replace(OLD, NEW)
else:
    print("用法：toggle_readme_outnote.py on|off")
    sys.exit(2)
io.open(P, "w", encoding="utf-8", newline="").write(txt)
print(f"✓ README.md 已切到 [{mode}]")
