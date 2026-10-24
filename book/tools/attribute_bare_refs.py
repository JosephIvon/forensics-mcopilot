#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""attribute_bare_refs.py —— 裸行号归属器：把每处"`N`"挂到它最近的、同一行或上一行的文件锚上（2026-10-22）。

书里的写法是"文件名单独出现 + 行号成组"（如 `KB2-waveform-formats.md`（`:786`–`:795`））。
本脚本对每处裸行号，找它**前面最近的**文件锚：
  · 行内锚：反引号包裹的路径（含扩展名）或别名（KB0-KB8 / C1-C7）
  · 跨行锚：本行没有时取上一行的行内锚
输出建议归属，人工确认后由修补脚本落盘。
"""
import io
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = []
for d in ("chapters",):
    for fn in sorted(os.listdir(os.path.join(REPO, d))):
        if fn.endswith(".md"):
            FILES.append((d + "/" + fn, os.path.join(REPO, d, fn)))
for fn in ("前言.md", "尾声.md"):
    FILES.append((fn, os.path.join(REPO, fn)))

BARE = re.compile(r"`:\d+(?:-\d+)?`")
ANCHOR = re.compile(
    r"`([A-Za-z0-9_\-一-鿿\./]+\.(?:md|py|js|cs|txt|json|jsonl|sha256|csv|ps1))`"
    r"|`((?:KB[0-8]|C[1-7]))[:：]?\d"
)


def anchors_of(line):
    out = []
    for m in ANCHOR.finditer(line):
        if m.group(1):
            out.append((m.start(), m.group(1)))
        else:
            out.append((m.start(), m.group(2)))
    return out


total = 0
for label, path in FILES:
    lines = io.open(path, encoding="utf-8").read().splitlines()
    hits = []
    for i, line in enumerate(lines, 1):
        for m in BARE.finditer(line):
            cand = [a for a in anchors_of(line) if a[0] < m.start()]
            src = "本行"
            anchor = cand[-1][1] if cand else None
            if anchor is None and i > 1:
                prev = [a for a in anchors_of(lines[i - 1])]
                if prev:
                    anchor = prev[-1][1]
                    src = "上一行"
            hits.append((i, m.group(0), anchor, src))
    if hits:
        print(f"== {label}（{len(hits)} 处）")
        for i, ref, anchor, src in hits:
            print(f"  :{i}  {ref:<12} ← {anchor or '【无锚，需人工判定】'}（{src}）")
        total += len(hits)
print(f"\n合计 {total} 处")
