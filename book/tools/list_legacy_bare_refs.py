#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""list_legacy_bare_refs.py —— 清点两章剩余裸行号（含上下文，供逐处归属）。"""
import io
import re

PAT = re.compile(r"`:\d+(?:-\d+)?`")  # v2：区间式也算（v1 漏掉 "`25-26`" 这种写法）
for path in (
    r"%WORKSPACE%\forensics-learning-book\chapters-vol2a\ch08-署名与脱敏.md",
    r"%WORKSPACE%\forensics-learning-book\chapters-vol2a\ch09-文档即代码.md",
):
    print("==", path.rsplit("\\", 1)[-1])
    for i, line in enumerate(io.open(path, encoding="utf-8").read().splitlines(), 1):
        for m in PAT.finditer(line):
            a = max(0, m.start() - 34)
            print(f"  :{i}  {m.group(0):<7} ← …{line[a:m.start()]}【{m.group(0)}】")
