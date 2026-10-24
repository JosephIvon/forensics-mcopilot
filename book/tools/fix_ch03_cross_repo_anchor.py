#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_ch03_cross_repo_anchor.py —— ch03 官方物证落点的定点更正（2026-10-22）。

成因：初稿写"五份官方 CSV 不在仓内、仓外读者当场验不了"。实读证伪：
这五份官方件在 **mcopilot 仓** `knowledge/sdks/official_api/`（gts.csv 474 行 /
gts_hdr.csv 536 行 / gts_structs.csv 218 行 / gts_hdr_macros.csv 201 行 /
dll_exports.csv 12074 行），trae_factory 仓内 csv 只有 glue_report.csv 两份。
正确说法是**跨仓锚**（锚回上游仓官方原件，58 条逐条可当场打开核对），
不是"仓外验不了"。另修一处卷内指代笔误（"第 7 册" → 册一第 7 章）。
"""
import io
import sys

P = r"%WORKSPACE%\forensics-learning-book\chapters-vol2b\ch03-手册进知识库.md"

OLD1 = """**这里有一笔必须如实记的账**：这五份 CSV **不在仓内**。2026-10-22 本机实读确认，
`trae_factory` 仓内的 csv 只有 `glue_report.csv`（36 行）与其迁居副本。
所以 `chk` 里的坐标指向**外部原件**——仓外读者当场验不了，只能凭"我手上有这套官方件"复现。
这与本卷坐标审计里那条例外是同一类（"仓外原件指针，非断链"）。诚实记账的做法是：
**把它标成外部原件指针，而不是伪装成仓内可验**。钉扎的验收因此不靠生成器自述——
`mcopilot@01eb884 scripts/verify_trae_pinvoke.py` 当日实跑退出码 0，58 条 P/Invoke 逐条
`[OK] ← <厂商>.csv:行号`（`decision-lists/trae_factory-2da4559.md:30-31`）。"""

NEW1 = """**这里有一笔必须如实记的账**：这五份官方件**不在 trae_factory 仓内**。2026-10-22 本机实读确认：
trae_factory 仓内的 csv 只有 `glue_report.csv`（36 行）与其迁居副本；官方件真身在
**mcopilot 仓**的 `knowledge/sdks/official_api/`——`gts.csv`（474 行）、`gts_hdr.csv`（536 行）、
`gts_structs.csv`（218 行）、`gts_hdr_macros.csv`（201 行）、`dll_exports.csv`（12074 行）。
所以工厂条目里那串 `chk` 坐标是**跨仓锚**：它指回上游仓的官方原件。这正是第 2 章真值链
"锚点 = 仓库@commit + 路径"那套办法在跨仓场景下的样子——因此钉扎的验收不靠生成器自述：
`mcopilot@01eb884 scripts/verify_trae_pinvoke.py` 当日实跑退出码 0，58 条 P/Invoke 逐条
`[OK] ← <厂商>.csv:行号`（`decision-lists/trae_factory-2da4559.md:30-31`），
每条都能当场打开官方件核对。"""

OLD2 = """   *参考*：算**仓外原件指针**，不是断链；仓内五份 CSV 实存 0 份（2026-10-22 实读）。
   正确记法是显式标注外部原件 + 把裁决权交给外部 runner
   （`scripts/verify_trae_pinvoke.py`，58 条逐条 `[OK] ← <厂商>.csv:行号`），
   而不是伪装成仓内可验。"""

NEW2 = """   *参考*：不算断链，但**不是本仓可验**——五份官方件在 mcopilot 仓
   `knowledge/sdks/official_api/`（trae_factory 仓内 csv 只有 `glue_report.csv` 两份，
   2026-10-22 实读）。正确记法是标成**跨仓锚**（仓库@commit + 路径），并把裁决权交给
   上游仓的 runner（`scripts/verify_trae_pinvoke.py`，58 条逐条 `[OK] ← <厂商>.csv:行号`），
   而不是拿生成器自述当验收。"""

OLD3 = """   **代价**：生成的适配器在真机上会"跑得动但形状不对"，而且错得自洽——
   这正是第 7 册（册一 ch07）说的"造得诚实"要防的那种不可见的假信号。"""

NEW3 = """   **代价**：生成的适配器在真机上会"跑得动但形状不对"，而且错得自洽——
   这正是册一第 7 章《没有真机时》说的"造得诚实"要防的那种不可见的假信号。"""

OLD4 = """每条 API 带 `chk` 核对说明与外部行号锚、
> 钉扎验收由外部 runner 完成（58 条 P/Invoke 逐条 `[OK] ← 厂商.csv:行号`，其中知识库钉扎 49 /"""

NEW4 = """每条 API 带 `chk` 核对说明与**跨仓行号锚**
> （锚回 mcopilot 仓 `knowledge/sdks/official_api/` 的官方件）、
> 钉扎验收由上游仓 runner 完成（58 条 P/Invoke 逐条 `[OK] ← 厂商.csv:行号`，其中知识库钉扎 49 /"""

OLD5 = """`mcopilot@01eb884 scripts/verify_trae_pinvoke.py`（58 条 P/Invoke 逐条 `[OK]`，退出码 0）；
规模数（gen/ 7 件 3322 行；ocr.ps1 30 行；adapters_kb.js 875 行；index.js 152 行；modbus.js 570 行；
truth_kb.js 318 行）与"仓内 CSV 仅 glue_report.csv 两份"为 2026-10-22 本机实读转录；"""

NEW5 = """`mcopilot@01eb884 scripts/verify_trae_pinvoke.py`（58 条 P/Invoke 逐条 `[OK]`，退出码 0）、
`knowledge/sdks/official_api/`（gts.csv 474 行 / gts_hdr.csv 536 行 / gts_structs.csv 218 行 /
gts_hdr_macros.csv 201 行 / dll_exports.csv 12074 行）；规模数（gen/ 7 件 3322 行；ocr.ps1 30 行；
adapters_kb.js 875 行；index.js 152 行；modbus.js 570 行；truth_kb.js 318 行）与
"trae_factory 仓内 csv 仅 glue_report.csv 两份"为 2026-10-22 本机实读转录；"""

PAIRS = [(OLD1, NEW1), (OLD2, NEW2), (OLD3, NEW3), (OLD4, NEW4), (OLD5, NEW5)]

t = io.open(P, encoding="utf-8").read()
fail = 0
for old, new in PAIRS:
    n = t.count(old)
    if n != 1:
        print(f"[SKIP 命中 {n} 次] {old[:56]}")
        fail += 1
        continue
    t = t.replace(old, new)
    print(f"[OK] 已更正：{old[:40]}…")
io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("失败条数：", fail)
sys.exit(1 if fail else 0)
