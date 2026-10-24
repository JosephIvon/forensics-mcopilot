#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_counter_regex.py —— 单独验反例计数器的正则行为（PowerShell -c 传中文会被编码坑，改用文件）。"""
import io
import re
import sys

sys.path.insert(0, r"%WORKSPACE%\forensics-learning-book\tools")
src = io.open(r"%WORKSPACE%\forensics-learning-book\tools\check_doc_refs_heads.py", encoding="utf-8").read()
m = re.search(r"COUNTER = re\.compile\((.*?)\)\n", src, re.S)
print("检查器里的定义原文：")
print("  ", m.group(1)[:200] if m else "**没找到**")
ns = {}
exec("import re\nCOUNTER = re.compile(" + (m.group(1) if m else "r''") + ")", ns)
C = ns["COUNTER"]
print("\n编译后 pattern：", C.pattern[:200])

lines = io.open(r"%WORKSPACE%\mcopilot\knowledge\coverage_ledger.json", encoding="utf-8").read().splitlines()
for n in (359, 361):
    l = lines[n - 1]
    hit = C.search(l)
    print(f"  L{n} 命中={bool(hit)} 匹配到={hit.group(0) if hit else None!r}")
    for probe in ("未入库", "未进", "不入库", "本地生成区", "运行产物"):
        print(f"      探针 {probe!r} 在行内 = {probe in l}")
