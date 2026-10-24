#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_hello_layout.py —— hello-agents 教学编排（作者指定的形制参照）实读（2026-10-22）。

只看 docs/ 教学区：目录页、侧栏（学习路径）、前言、以及各章的开头形态与内部结构，
用于和本书卷一做**事实层面**的编排对比（不辩论，只摆事实）。
"""
import io
import os

H = r"%WORKSPACE%\hello-agents\docs"


def show(path, n, label):
    if not os.path.isfile(path):
        print(f"  （缺 {label}）")
        return
    print(f"\n  -- {label} 前 {n} 行 --")
    for i, l in enumerate(io.open(path, encoding="utf-8", errors="replace"), 1):
        if i > n:
            break
        print(f"     :{i} {l.rstrip()[:118]}")


print("=" * 92)
print("A. 侧栏 = 学习路径（hello-agents 的编排骨架）")
print("=" * 92)
show(os.path.join(H, "_sidebar.md"), 46, "docs/_sidebar.md")

print()
print("=" * 92)
print("B. 前言（编排说明与读者承诺）")
print("=" * 92)
show(os.path.join(H, "前言.md"), 40, "docs/前言.md")

print()
print("=" * 92)
print("C. 各章开头形态（chapter1 / 5 / 10 / 16）")
print("=" * 92)
for c in ("chapter1", "chapter5", "chapter10", "chapter16"):
    d = os.path.join(H, c)
    if not os.path.isdir(d):
        continue
    files = sorted(f for f in os.listdir(d) if f.endswith(".md"))
    print(f"\n  【{c}】{len(files)} 篇 md：{', '.join(files[:8])}"
          + (" …" if len(files) > 8 else ""))
    if files:
        show(os.path.join(d, files[0]), 26, f"{c}/{files[0]}")

print()
print("=" * 92)
print("D. chapter1 内部小节序列（看是否有递进）")
print("=" * 92)
d = os.path.join(H, "chapter1")
for f in sorted(x for x in os.listdir(d) if x.endswith(".md")):
    p = os.path.join(d, f)
    secs = [l.strip() for l in io.open(p, encoding="utf-8", errors="replace")
            if l.startswith("## ")]
    print(f"  {f}: {len(secs)} 节 → " + " | ".join(s[:22] for s in secs[:8]))
