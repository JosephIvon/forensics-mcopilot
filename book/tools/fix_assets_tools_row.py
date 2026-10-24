#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_assets_tools_row.py —— ASSETS 工具链行更新（v2，按实际行内容精确替换）。"""
import io
import sys

P = r"%WORKSPACE%\forensics-learning-book\ASSETS.md"
old = """| `tools/audit_vol2_coords.py`（坐标审计器：201→321 引用 0 失败；支持 C1–C7 与 KB0–KB8 别名、区间行号、跨仓消歧）、`tools/fix_vol2_anchors.py`（锚点清偿）、`tools/crop_vol2.py`（两册裁剪生成器）、`tools/verify_crops_verbatim.py`（裁剪件逐行"原样"核验）、`tools/check_vol2s_structure.py`（两册结构体检） | 卷二生产工具链 |"""
new = """| `tools/audit_vol2_coords.py`（坐标审计器：**按锚点 commit 读源文件**而非工作树；覆盖 24 个文件（卷一 9 + 册一 9 + 册二 4 + 前言 + 尾声）697 引用 0 失败；支持 C1–C7 与 KB0–KB8 别名、区间行号、跨仓消歧、尾路径匹配）、`tools/fix_vol2_anchors.py`（锚点清偿）、`tools/crop_vol1.py`（卷一裁剪重建）、`tools/crop_vol2.py`（两册裁剪生成器）、`tools/verify_crops_verbatim.py`（**6 件**裁剪件逐行"原样"核验）、`tools/check_vol2s_structure.py`（两册 + 前后记结构体检）、`tools/precompute_frontback_facts.py`（规模数亲跑，**axiscope 段按锚点读**）、`tools/machine_ize_all_bare_refs.py` + `tools/attribute_bare_refs.py`（裸行号机判化与归属核对） | 全书生产工具链 |"""

t = io.open(P, encoding="utf-8").read()
if t.count(old) != 1:
    print(f"[SKIP] 命中 {t.count(old)} 次")
    sys.exit(1)
io.open(P, "w", encoding="utf-8", newline="\n").write(t.replace(old, new))
print("[OK] ASSETS 工具链行已更新")
