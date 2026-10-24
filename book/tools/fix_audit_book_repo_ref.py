#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_audit_book_repo_ref.py —— 审计器里 ROOTS[3] 已不是书仓（加了 pending 与 self-improving 根），
把 chapter_roots 的书仓指向改为显式 BOOK_REPO 常量。"""
import io
import sys

P = r"%WORKSPACE%\forensics-learning-book\tools\audit_vol2_coords.py"
old = '("mcopilot", ROOTS[2]), ("forensics-learning-book", ROOTS[3])):'
new = '("mcopilot", ROOTS[2]), ("forensics-learning-book", BOOK_REPO)):'
t = io.open(P, encoding="utf-8").read()
n = t.count(old)
if n != 1:
    print(f"[SKIP] 命中 {n} 次")
    sys.exit(1)
t = t.replace(old, new)
io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("[OK] chapter_roots 的书仓指向已改为 BOOK_REPO")
