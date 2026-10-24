#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_legacy_lines.py —— 打印待修正行的精确内容（repr），用于对齐引号体例。"""
import io

for path, nums in (
    (r"%WORKSPACE%\forensics-learning-book\chapters-vol2a\ch08-署名与脱敏.md", (134, 135)),
    (r"%WORKSPACE%\forensics-learning-book\chapters-vol2a\ch09-文档即代码.md", (43, 63, 86)),
):
    lines = io.open(path, encoding="utf-8").read().splitlines()
    print("==", path.rsplit("\\", 1)[-1])
    for n in nums:
        print(f"  :{n} {lines[n-1]!r}")
    if "ch09" in path:
        for i, l in enumerate(lines, 1):
            if "跳过（`:37-38`）" in l:
                print(f"  [命中 :{i}] {l!r}")
