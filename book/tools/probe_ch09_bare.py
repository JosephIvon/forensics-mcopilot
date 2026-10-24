#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_ch09_bare.py —— 精确定位 ch09 残留的"（`:N" 匹配片段。"""
import io
import re

P = r"%WORKSPACE%\forensics-learning-book\chapters-vol2a\ch09-文档即代码.md"
text = io.open(P, encoding="utf-8").read()
for i, line in enumerate(text.splitlines(), 1):
    for m in re.finditer(r"（`:\d+", line):
        a = max(0, m.start() - 46)
        print(f"  :{i}  …{line[a:m.start()]}【{m.group(0)}】")
