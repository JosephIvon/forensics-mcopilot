#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_batch_c_sop_gaps.py —— 批 C 第 9 项：检查器补跨行分型 + 两处真断链订正（2026-10-22 夜）。

一、检查器：反例/记录性识别要带**上下文行** ✗
`docs/项目回顾与收尾_20261021.md:325` 写「上一路废稿 `scripts/pcap_corpus.py` … 已删除」——
"已删除"在**下一行** ✗，而分型只看本行 ✗ → 被误判成真断链 ✗。
处置：反例分型看**本行 + 下一行** ✓（文档里"说明在下一行"是常态 ✓）。
（上一轮的教训「假阳性来源要先分型」在这里又应验了一次 ✓。）

二、mcopilot 两处真断链
- `docs/协议提取SOP.md:166` 写「（tests/test_gates.py）」——该文件**不存在** ✗
  → 门清单与退出码域实际在 `scripts/gate_protocol.ps1` ✓，
    负向用例在 `scripts/gate_negative.ps1` ✓，改指真东西 ✓。
- `docs/协议提取SOP.md:179` 写 `knowledge/protocols/x.json`——那是**模板占位** ✗（协议 X）
  → 改成 `knowledge/protocols/<协议名>.json` ✓（占位符不再像真路径 ✓）。
"""
import io
import os
import sys

BOOK = r"%WORKSPACE%\forensics-learning-book"
MC = r"%WORKSPACE%\mcopilot"

# ── 一、检查器：分型带上下文行 ──────────────────────────────────────────
p = os.path.join(BOOK, "tools", "check_doc_refs_heads.py")
txt = io.open(p, encoding="utf-8", newline="").read()
old = """        for i, line in enumerate(txt.splitlines(), 1):
            for m in PATH.finditer(line):"""
new = """        lines = txt.splitlines()
        for i, line in enumerate(lines, 1):
            # 分型看**本行 + 下一行**：文档里"说明在下一行"是常态
            # （例：「上一路废稿 `scripts/x.py` … 已删除」——"已删除"在下一行）
            ctx = line + ("\\n" + lines[i] if i < len(lines) else "")
            for m in PATH.finditer(line):"""
if txt.count(old) != 1:
    print("✗ 检查器补丁锚点未命中")
    sys.exit(1)
txt = txt.replace(old, new, 1)
old2 = """                        if COUNTER.search(line):"""
new2 = """                        if COUNTER.search(ctx):"""
if txt.count(old2) != 1:
    print("✗ 检查器分型锚点未命中")
    sys.exit(1)
txt = txt.replace(old2, new2, 1)
io.open(p, "w", encoding="utf-8", newline="").write(txt)
print("  ✓ tools/check_doc_refs_heads.py：反例分型带上下文行")

# ── 二、mcopilot 两处真断链 ─────────────────────────────────────────────
FIXES = [
    ("docs/协议提取SOP.md",
     '自检与"每门必有负向用例"的纪律照走（tests/test_gates.py）。',
     '自检与「每门必有负向用例」的纪律照走（门清单与退出码域在 `scripts/gate_protocol.ps1`，'
     '负向用例在 `scripts/gate_negative.ps1`）。'),
    ("docs/协议提取SOP.md",
     "- **交付清单（协议 X）**：`knowledge/protocols/x.json`（modbus_extract/1 风格 schema）+",
     "- **交付清单（协议 X）**：`knowledge/protocols/<协议名>.json`（modbus_extract/1 风格 schema）+"),
]
cache = {}
applied = 0
for rel, old_t, new_t in FIXES:
    path = os.path.join(MC, rel.replace("/", os.sep))
    if path not in cache:
        cache[path] = io.open(path, encoding="utf-8", newline="").read()
    t = cache[path]
    eol = "\r\n" if "\r\n" in t else "\n"
    got = t.count(old_t.replace("\n", eol))
    if got != 1:
        print(f"✗ {rel} 命中 {got} 处：{old_t[:50]}")
        sys.exit(1)
    cache[path] = t.replace(old_t.replace("\n", eol), new_t.replace("\n", eol), 1)
    applied += 1
for path, t in cache.items():
    io.open(path, "w", encoding="utf-8", newline="").write(t)
    print(f"  ✓ {path.replace(MC, '')}")
print(f"  mcopilot 文档层：{applied} 处")
