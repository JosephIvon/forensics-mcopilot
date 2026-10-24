#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_gap_windows.py —— 打印每个断链路径在原文里前后各 110 字的窗口（2026-10-22）。"""
import io
import os
import re

JOBS = [
    (r"%WORKSPACE%\mcopilot\src\mcopilot\agents", "servo_c1.py"),
    (r"%WORKSPACE%\mcopilot\samples\servo\twincat_export10.truth.json", "verify_export10_truth"),
    (r"%WORKSPACE%\mcopilot\samples\servo\twincat_export10.truth.json", "truth_basis"),
    (r"%WORKSPACE%\axiscope\docs\kb\KB0-conventions.md", "c3_example_h1h2.json"),
    (r"%WORKSPACE%\axiscope\docs\kb\KB0-conventions.md", "_tmp_tablecheck.py"),
    (r"%WORKSPACE%\axiscope\docs\kb\KB0-conventions.md", "probe_out.txt"),
    (r"%WORKSPACE%\axiscope\data\validate_vendor.json", "C1_periodic.csv"),
    (r"%WORKSPACE%\axiscope\data\validate_vendor.json", "C1_p2p.csv"),
    (r"%WORKSPACE%\mcopilot\samples\servo\PROVENANCE.md", "out/"),
]

for path, needle in JOBS:
    if os.path.isdir(path):
        print(f"== 目录 {path}：含 '{needle}' 的文件 ==")
        for dp, dns, fns in os.walk(path):
            for fn in fns:
                if needle in fn:
                    print("   ", os.path.join(dp, fn))
        print()
        continue
    print("=" * 96)
    print(f"【{os.path.basename(path)}】关键词：{needle}")
    print("=" * 96)
    txt = io.open(path, encoding="utf-8", errors="replace").read()
    for m in re.finditer(re.escape(needle), txt):
        s = max(0, m.start() - 110)
        e = min(len(txt), m.end() + 110)
        line_no = txt.count("\n", 0, m.start()) + 1
        ctx = txt[s:e].replace("\n", " ⏎ ")
        print(f"  L{line_no}: …{ctx}…")
    print()
