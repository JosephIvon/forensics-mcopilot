#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_ch08_ch09_machine_coords2.py —— 册一 ch08/ch09 裸行号机判化（第二轮，逐行归属）。

第一轮（fix_ch08_ch09_machine_coords.py）按精确串替换，命中 21/25；
剩余 4 处因引号体例与断行差异未命中。清点后发现实际剩余更多（首轮显示被截断），
本轮改为**按行归属**：逐行指定该行裸行号属于哪个文件，脚本按行批量替换，
并把同别名的连续区间合并成 `别名:起-止`。
归属依据：ch08 全章除侧车两处外均为 KB2；ch09 按上下文分为探针（probe）/KB0/KB2 三类。
"""
import io
import os
import re
import sys

REPO = r"%WORKSPACE%\forensics-learning-book"
CH08 = os.path.join(REPO, "chapters-vol2a", "ch08-署名与脱敏.md")
CH09 = os.path.join(REPO, "chapters-vol2a", "ch09-文档即代码.md")

KB2 = "KB2"
KB0 = "KB0"
PROBE = "data/probe_doc_line_refs.py"
SIDE = "data/raw/Export10_244531.csv.source.txt"

MAP08 = {16: KB2, 47: KB2, 49: KB2, 50: KB2, 55: KB2, 56: KB2, 134: SIDE, 159: KB2}
MAP09 = {
    34: PROBE, 35: PROBE, 36: PROBE, 37: PROBE, 43: PROBE, 45: PROBE,
    60: KB0, 61: KB0, 63: KB0, 67: KB0,
    77: KB2, 90: KB2, 106: KB0, 116: KB0, 145: PROBE, 160: KB2,
}

BARE = re.compile(r"`:(\d+)`")
fail = 0
for path, mp in ((CH08, MAP08), (CH09, MAP09)):
    lines = io.open(path, encoding="utf-8").read().splitlines(keepends=True)
    done = 0
    for idx, line in enumerate(lines, 1):
        if idx not in mp:
            continue
        alias = mp[idx]
        if not BARE.search(line):
            print(f"[MISS] {os.path.basename(path)}:{idx} 该行已无裸行号（可能首轮已处理）")
            continue
        new = BARE.sub(lambda m: f"`{alias}:{m.group(1)}`", line)
        lines[idx - 1] = new
        done += len(BARE.findall(line))
    # 同别名区间合并：`KB2:814`–`KB2:815` → `KB2:814-815`
    text = "".join(lines)
    for alias in set(mp.values()):
        text = re.sub(rf"`{re.escape(alias)}:(\d+)`[–-]`{re.escape(alias)}:(\d+)`",
                      rf"`{alias}:\1-\2`", text)
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)
    print(f"[OK] {os.path.basename(path)}：{len(mp)} 行 / {done} 处裸行号归属并机判化")

# 复查：两章不应再有裸行号
for path in (CH08, CH09):
    rest = [(i, m.group(0)) for i, l in
            enumerate(io.open(path, encoding="utf-8").read().splitlines(), 1)
            for m in BARE.finditer(l)]
    if rest:
        fail += 1
        print(f"[LEFT] {os.path.basename(path)} 仍有裸行号：{rest[:8]}")
    else:
        print(f"[CLEAN] {os.path.basename(path)} 无裸行号")
print("失败条数：", fail)
sys.exit(1 if fail else 0)
