#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_vol2_count_koujing.py —— 计数口径更正（2026-10-22）。

问题：卷二正文引用 axiscope 收尾文档 §二的账面（"src 15 个 py / 5,263 行"、
"tests 3,743 行"、"docs md 19 件"），但**未标口径**。主控 2026-10-22 本机复算：
  - src   15 个 py：物理行 6,039、**非空行 5,263** ← 账面 5,263 是非空行
  - tests 18 个 py：物理行 4,836、**非空行 3,743** ← 账面 3,743 是非空行
  - docs  md 27 件 = 契约 7 + 知识库 8 + 审计/裁决 5 + wiki 7；账面 19 件 = 不含 wiki 与收尾文档
  - pytest 实收集 403 项 ✓
读者若按物理行复核会数出 6,039 / 4,836 —— 与 KB0 §6 检查 27「汇总计数须由脚本自数并打印，
文档抄打印行」的要求相抵：抄了打印行，还得抄上打印行的口径。

处置：把口径补进正文与元数据块；数值本身不改。
"""
import os
import sys

REPO = r"%WORKSPACE%\forensics-learning-book"

PAIRS = [
    ("chapters-vol2a/ch02-证据等级.md",
     "> **已验算**：2026-10-22（403 项测试当日两次全绿：24.71s／脱敏后 18.16s；src 15 py 5,263 行、\n"
     "> tests 3,743 行——当日实跑转录，`docs/项目回顾与收尾_20261022.md:26-27`）",
     "> **已验算**：2026-10-22（403 项测试当日两次全绿：24.71s／脱敏后 18.16s；src 15 py **非空行**\n"
     "> 5,263（物理行 6,039）、tests **非空行** 3,743（物理行 4,836）——当日实跑转录，\n"
     "> `docs/项目回顾与收尾_20261022.md:26-27`；口径为主控当日本机复算所加）"),
    ("chapters-vol2a/ch09-文档即代码.md",
     "src 15 个 py 共 5263 行、tests 3743 行 403 项、docs 19 件 md；",
     "src 15 个 py 非空行 5,263（物理行 6,039）、tests 非空行 3,743（物理行 4,836）403 项、\n"
     "docs 19 件 md（契约 7 + 知识库 8 + 审计/裁决 5 + wiki 7 = 实存 27 件）；"),
    ("chapters-vol2b/ch04-双仓收尾实录.md",
     "§二规模账面 15 py/5,263 行、tests 3,743 行/403 项",
     "§二规模账面 15 py/非空行 5,263（物理行 6,039）、tests 非空行 3,743（物理行 4,836）/403 项"),
]

fail = 0
for fn, old, new in PAIRS:
    path = os.path.join(REPO, fn.replace("/", os.sep))
    text = open(path, encoding="utf-8").read()
    n = text.count(old)
    if n != 1:
        print(f"[SKIP 命中 {n} 次] {fn}: {old[:60]!r}")
        fail += 1
        continue
    open(path, "w", encoding="utf-8", newline="\n").write(text.replace(old, new))
    print(f"[OK] {fn} 计数口径已补")
print("失败条数：", fail)
sys.exit(1 if fail else 0)
