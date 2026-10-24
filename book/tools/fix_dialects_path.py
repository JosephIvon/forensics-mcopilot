#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_dialects_path.py —— 册一 ch06:58 的路径前缀订正（2026-10-22）。

机判化时按"scripts/dialects.py"落笔，但锚点处真实落点是 `src/axiscope/dialects.py`
（仓内另有 data/probe_dialects.py 与 tests/test_export_dialects.py）。
审计器报 EXTERNAL-TARGET 即为当场发现：路径写错就查不出来，不改就永远是死链。
"""
import io
import os
import sys

REPO = r"%WORKSPACE%\forensics-learning-book"
PAIRS = [
    ("chapters-vol2a/ch06-厂商方言与上下文契约.md",
     "`scripts/dialects.py:35-36`",
     "`src/axiscope/dialects.py:35-36`"),
]
fail = 0
cache = {}
for rel, old, new in PAIRS:
    path = os.path.join(REPO, rel.replace("/", os.sep))
    if path not in cache:
        cache[path] = io.open(path, encoding="utf-8").read()
    t = cache[path]
    n = t.count(old)
    if n != 1:
        print(f"[SKIP 命中 {n} 次] {rel}: {old!r}")
        fail += 1
        continue
    cache[path] = t.replace(old, new)
    print(f"[OK] {rel}: {old} → {new}")
for path, t in cache.items():
    io.open(path, "w", encoding="utf-8", newline="\n").write(t)
sys.exit(1 if fail else 0)
