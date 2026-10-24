#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_chapter_theses.py —— 提取 22 章的"主张句 + 习题题面"，供承接段贴章撰写（2026-10-22）。"""
import io
import os
import re

REPO = r"%WORKSPACE%\forensics-learning-book"
VOLS = [("卷一", "chapters"), ("册一", "chapters-vol2a"), ("册二", "chapters-vol2b")]

for name, d in VOLS:
    print(f"\n########## {name} ##########")
    for fn in sorted(f for f in os.listdir(os.path.join(REPO, d)) if f.endswith(".md")):
        lines = io.open(os.path.join(REPO, d, fn), encoding="utf-8").read().splitlines()
        title = lines[0].lstrip("# ").strip()
        print(f"\n  ── {fn}")
        print(f"     标题：{title}")
        # 第一个 §x.1 之后的主张引用块
        thesis = []
        seen = False
        for l in lines:
            if re.match(r"^##\s*\d+\.\d+\s", l):
                seen = True
                continue
            if seen and l.startswith("> **"):
                thesis.append(l.strip())
                if len(thesis) >= 1:
                    break
        if thesis:
            print("     主张：" + thesis[0][:150])
        # 动手小节标题
        hands = [l.strip() for l in lines if re.match(r"^##\s*\d+\.\d+\s*(动手|实战|战例|验算)", l)]
        print("     动手/实战节：" + (" / ".join(h[:40] for h in hands[:4]) or "（无独立动手节）"))
        # 习题题目
        q = []
        inq = False
        for l in lines:
            if re.match(r"^##\s*\d+\.\d+\s*习题", l):
                inq = True
                continue
            if inq and re.match(r"^##\s", l):
                break
            if inq and re.match(r"^\s*\d+\.\s", l):
                q.append(l.strip()[:78])
        print("     习题题面：" + " ｜ ".join(q[:5]))
