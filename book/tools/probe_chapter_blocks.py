#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_chapter_blocks.py —— 编排改造前的三项勘察（2026-10-22）。

① 各章开头块的形态（素材坐标/已验算/指针行）与行数范围是否统一；
② 各章末尾是否都有「--- + 尾注坐标」结构；
③ **书内自引**：有没有坐标指向本书自己的行号（坐标块下沉会改变行号 → 必须先查清）。
"""
import io
import os
import re

REPO = r"%WORKSPACE%\forensics-learning-book"
VOLS = [("卷一", "chapters"), ("册一", "chapters-vol2a"), ("册二", "chapters-vol2b")]
CITE = re.compile(r"`([^`\s]+\.(?:md|py|js|ps1|json|jsonl|csv|txt|sha256)):(\d+)(?:-(\d+))?`")

for name, d in VOLS:
    print(f"\n===== {name}（{d}）=====")
    for fn in sorted(f for f in os.listdir(os.path.join(REPO, d)) if f.endswith(".md")):
        p = os.path.join(REPO, d, fn)
        lines = io.open(p, encoding="utf-8").read().splitlines()
        # ① 开头块：标题之后到第一个 '---' 之前的引用行
        head_block = []
        i = 1
        while i < len(lines) and not lines[i].startswith("---"):
            if lines[i].startswith(">"):
                head_block.append((i + 1, lines[i]))
            i += 1
        kinds = []
        for _, l in head_block:
            for k in ("素材坐标", "已验算", "简历句", "讲师", "前置", "本章"):
                if k in l:
                    kinds.append(k)
        tail_note = any(l.startswith("*本章事实性句子坐标") for l in lines[-8:])
        last_sep = max((n for n, l in enumerate(lines, 1) if l.strip() == "---"), default=0)
        # ③ 书内自引（坐标指向本书文件）
        self_ref = [(n, m.group(1)) for n, l in enumerate(lines, 1)
                    for m in CITE.finditer(l)
                    if m.group(1).startswith(("chapters", "crops", "前言", "尾声", "decision-lists"))
                    or "/" in m.group(1) and m.group(1).startswith(("ch", "crops"))]
        print(f"  {fn:<34} {len(lines):>4} 行 ｜ 开头块 {len(head_block)} 行 {sorted(set(kinds))}"
              f" ｜ 尾注{'✓' if tail_note else '✗'} ｜ 末分隔行 {last_sep}/{len(lines)}"
              f" ｜ 书内自引 {len(self_ref)} 处 {self_ref[:3]}")
