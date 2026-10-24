#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_ch09_ranges_and_koujing2.py —— ch09 区间式裸行号补清（v2，正则修正）。

v1 的盲区：裸行号正则写作 "`:(\\d+)`"（数字后必须紧跟反引号），
于是**区间式** "`25-26`" 匹配不到 —— 清点脚本与修补脚本同时漏网，7 处幸存。
v2 改用 "`:\\d+(?:-\\d+)?`"，并同步修正 tools/list_legacy_bare_refs.py 的同一盲区。
"""
import io
import os
import re
import sys

REPO = r"%WORKSPACE%\forensics-learning-book"
CH09 = os.path.join(REPO, "chapters-vol2a", "ch09-文档即代码.md")
LISTER = os.path.join(REPO, "tools", "list_legacy_bare_refs.py")

PROBE = "data/probe_doc_line_refs.py"
MAP = {44: PROBE, 48: PROBE, 72: "tests/test_slice.py", 74: "KB0-conventions.md", 87: PROBE}

BARE = re.compile(r"`:\d+(?:-\d+)?`")
lines = io.open(CH09, encoding="utf-8").read().splitlines(keepends=True)
done = 0
for idx, line in enumerate(lines, 1):
    if idx not in MAP:
        continue
    alias = MAP[idx]
    hits = BARE.findall(line)
    if not hits:
        print(f"[MISS] ch09:{idx} 该行已无裸行号")
        continue
    lines[idx - 1] = BARE.sub(lambda m: f"`{alias}:{m.group(0)[2:-1]}`", line)
    done += len(hits)
text = "".join(lines)
for alias in set(MAP.values()):
    text = re.sub(rf"`{re.escape(alias)}:(\d+)`[–-]`{re.escape(alias)}:(\d+)`",
                  rf"`{alias}:\1-\2`", text)
io.open(CH09, "w", encoding="utf-8", newline="\n").write(text)
rest = [(i, m.group(0)) for i, l in enumerate(text.splitlines(), 1) for m in BARE.finditer(l)]
print(f"[ch09] 补清 {done} 处；剩余裸行号 {len(rest)} 处 {rest[:6]}")

# 同步修正清点脚本的同一盲区
t = io.open(LISTER, encoding="utf-8").read()
old = 'PAT = re.compile(r"`:\\d+`")'
new = 'PAT = re.compile(r"`:\\d+(?:-\\d+)?`")  # v2：区间式也算（v1 漏掉 "`25-26`" 这种写法）'
if t.count(old) == 1:
    io.open(LISTER, "w", encoding="utf-8", newline="\n").write(t.replace(old, new))
    print("[OK] list_legacy_bare_refs.py 的盲区已修")
else:
    print(f"[SKIP] 清点脚本正则命中 {t.count(old)} 次")
sys.exit(1 if rest else 0)
