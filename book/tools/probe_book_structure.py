#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_book_structure.py —— 对比两种"教学电子书"的编排（2026-10-22）。

作者质疑：本书"没看出递进关系和循序渐进"。本脚本不辩论，只把事实摆出来：
  A. hello-agents（作者自己指定的形制参照）：目录层级、每篇的开头长什么样、有没有"学完你会……"
  B. 本书卷一 9 章：每章的小节序列、开头形态、有没有前置依赖声明
  C. 本书是否有目录/路线图/索引文件
"""
import io
import os
import re

BOOK = r"%WORKSPACE%\forensics-learning-book"
HELLO = r"%WORKSPACE%\hello-agents"


def heads(path, levels=("##",)):
    out = []
    for i, line in enumerate(io.open(path, encoding="utf-8", errors="replace"), 1):
        s = line.rstrip("\n")
        for lv in levels:
            if s.startswith(lv + " "):
                out.append((i, s))
                break
    return out


print("=" * 92)
print("A. hello-agents 形制参照")
print("=" * 92)
if os.path.isdir(HELLO):
    for dp, dn, fn in os.walk(HELLO):
        dn[:] = [d for d in dn if d not in (".git", "node_modules", "__pycache__")]
        rel = os.path.relpath(dp, HELLO)
        mds = sorted(f for f in fn if f.endswith(".md"))
        if mds:
            print(f"  {rel}/  →  {len(mds)} 篇 md：{', '.join(mds[:6])}"
                  + (" …" if len(mds) > 6 else ""))
    # 取主文档看开头形态
    for cand in ("README.md", "docs/README.md", "docs/index.md", "docs/00-index.md"):
        p = os.path.join(HELLO, cand)
        if os.path.isfile(p):
            print(f"\n  -- {cand} 前 28 行 --")
            for i, l in enumerate(io.open(p, encoding="utf-8", errors="replace"), 1):
                if i > 28:
                    break
                print(f"     :{i} {l.rstrip()[:110]}")
            break
else:
    print("  （未找到 hello-agents）")

print()
print("=" * 92)
print("B. 本书卷一 9 章：小节序列与开头形态")
print("=" * 92)
for fn in sorted(os.listdir(os.path.join(BOOK, "chapters"))):
    if not fn.endswith(".md"):
        continue
    p = os.path.join(BOOK, "chapters", fn)
    txt = io.open(p, encoding="utf-8").read()
    lines = txt.splitlines()
    print(f"\n  【{fn}】{len(lines)} 行")
    for i, l in enumerate(lines[:8], 1):
        if i <= 6:
            print(f"     :{i} {l[:112]}")
    secs = [s for _, s in heads(p)]
    print(f"     小节序列（{len(secs)}）: " + " | ".join(s.replace("## ", "") for s in secs[:9]))
    # 习题 / 简历句 / 讲师 是否在
    has = {k: (k in txt) for k in ("习题", "简历句", "讲师", "前置", "先修", "本章你将", "学完")}
    print(f"     要素: " + "  ".join(f"{k}{'✓' if v else '✗'}" for k, v in has.items()))

print()
print("=" * 92)
print("C. 本书顶层是否有目录/路线图/索引")
print("=" * 92)
for fn in sorted(os.listdir(BOOK)):
    if fn.endswith(".md"):
        print(f"  {fn}")
