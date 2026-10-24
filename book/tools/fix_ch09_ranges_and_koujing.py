#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_ch09_ranges_and_koujing.py —— ch09 区间式裸行号补清 + 体检器纪律名误报修正（2026-10-22）。

① ch09 还剩 7 处裸行号：上轮清点用的正则 "`:\\d+`" 匹配不到区间写法 "`25-26`"，
   于是区间式的 7 处漏网。按行归属补清：
   :44 / :48 / :87 → data/probe_doc_line_refs.py；:72 → tests/test_slice.py；:74 → KB0-conventions.md
② 结构体检把"**禁会话坐标**"（纪律名本身）当成违禁项误报：改为负向前查（禁/不/无 + 会话坐标）。
"""
import io
import os
import re
import sys

REPO = r"%WORKSPACE%\forensics-learning-book"
CH09 = os.path.join(REPO, "chapters-vol2a", "ch09-文档即代码.md")
CHK = os.path.join(REPO, "tools", "check_vol2s_structure.py")

PROBE = "data/probe_doc_line_refs.py"
MAP = {44: PROBE, 48: PROBE, 72: "tests/test_slice.py", 74: "KB0-conventions.md", 87: PROBE}

BARE = re.compile(r"`:(\d+)`")
lines = io.open(CH09, encoding="utf-8").read().splitlines(keepends=True)
done = 0
for idx, line in enumerate(lines, 1):
    if idx not in MAP:
        continue
    alias = MAP[idx]
    if not BARE.search(line):
        print(f"[MISS] ch09:{idx} 该行已无裸行号")
        continue
    lines[idx - 1] = BARE.sub(lambda m: f"`{alias}:{m.group(1)}`", line)
    done += len(BARE.findall(line))
text = "".join(lines)
for alias in set(MAP.values()):
    text = re.sub(rf"`{re.escape(alias)}:(\d+)`[–-]`{re.escape(alias)}:(\d+)`",
                  rf"`{alias}:\1-\2`", text)
io.open(CH09, "w", encoding="utf-8", newline="\n").write(text)
rest = [(i, m.group(0)) for i, l in enumerate(text.splitlines(), 1) for m in BARE.finditer(l)]
print(f"[ch09] 补清 {done} 处；剩余裸行号 {len(rest)} 处 {rest[:5]}")

# ② 体检器：纪律名不算违禁
t = io.open(CHK, encoding="utf-8").read()
old = '(re.compile(r"会话坐标|本轮对话|上文提到|前面说过"), "会话坐标"),'
new = '(re.compile(r"(?<![禁不无])会话坐标|本轮对话|上文提到|前面说过"), "会话坐标"),'
if t.count(old) == 1:
    io.open(CHK, "w", encoding="utf-8", newline="\n").write(t.replace(old, new))
    print("[OK] 体检器已豁免纪律名「禁会话坐标」")
else:
    print(f"[SKIP] 体检器正则命中 {t.count(old)} 次")
    sys.exit(1)
sys.exit(1 if rest else 0)
