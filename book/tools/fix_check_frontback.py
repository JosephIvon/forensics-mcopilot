#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_check_frontback.py —— 结构体检脚本补上前言/尾声的检查项（2026-10-22）。

书级前后言也进体检：必备件（标题 / 主张块 / 尾注坐标）+ 违禁项（会话坐标、裸行号坐标）。
"""
import io
import sys

P = r"%WORKSPACE%\forensics-learning-book\tools\check_vol2s_structure.py"
old = """print("问题章数：", bad)
sys.exit(1 if bad else 0)"""
new = """# ---- 书级前后言体检 ----
for fn in ("前言.md", "尾声.md"):
    path = os.path.join(REPO, fn)
    if not os.path.isfile(path):
        print(f"  ❌ {fn}：文件不存在")
        bad += 1
        continue
    text = io.open(path, encoding="utf-8").read()
    need = {
        "标题": text.startswith("# "),
        "主张块": "> **" in text,
        "尾注坐标": "事实性句子坐标" in text,
    }
    miss = [k for k, v in need.items() if not v]
    hits = []
    for pat, label in BAD_PATTERNS:
        for m in pat.finditer(text):
            hits.append(f"{label}@L{text[:m.start()].count(chr(10)) + 1}")
    if miss or hits:
        bad += 1
        print(f"  ❌ {fn}：缺 {miss or '无'}{' ｜ ' + ', '.join(hits) if hits else ''}")
    else:
        print(f"  ✅ {fn}（{len(text.splitlines())} 行）")

print("问题章数：", bad)
sys.exit(1 if bad else 0)"""

t = io.open(P, encoding="utf-8").read()
n = t.count(old)
if n != 1:
    print(f"[SKIP] 命中 {n} 次")
    sys.exit(1)
io.open(P, "w", encoding="utf-8", newline="\n").write(t.replace(old, new))
print("[OK] 结构体检已覆盖前言/尾声")
