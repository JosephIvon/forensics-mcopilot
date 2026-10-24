#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_codewiki_numbers.py —— 按实跑结果订正 CodeWiki_20261022.md 的过期数字（2026-10-22）。

每一个数都写明**口径**（跟踪文件数 / 本机实跑数），数字全部由本机亲跑转录。
"""
import io
import os
import sys

MC = r"%WORKSPACE%\mcopilot"
W = os.path.join(MC, "docs", "CodeWiki_20261022.md")

FIXES = [
    # 1) 知识层文件数：跟踪文件口径 = 75（9 根 + 9 protocols + 7 specs + 1 slmp_specs
    #    + 3 pcap_samples + 2 real_corpora + 3 sdks + 21 official_api + 1 contracts
    #    + 5 templates + 14 templates/protocol）
    ("| 核心资产 | `knowledge/` **85 个文件**（规则/协议提取/厂商一手件/契约） | 【实测】 |",
     "| 核心资产 | `knowledge/` **75 个跟踪文件**（规则/协议提取/厂商一手件/契约） | 【实测】 |", 1),
    ("knowledge/  唯一事实来源（85 文件）",   # 注意这里是**两个**空格（对齐表格）
     "knowledge/  唯一事实来源（75 文件）", 1),
    ("### 7.1 知识层目录地图（85 个文件）",
     "### 7.1 知识层目录地图（75 个跟踪文件）", 1),
    ("| `knowledge/protocols/` | 12 + 4 子目录 |",
     "| `knowledge/protocols/` | 9 + 4 子目录 |", 1),
    ("| `knowledge/templates/` | 5 + 21 |",
     "| `knowledge/templates/` | 5 + 14 |", 1),
    # 2) 样本资产：跟踪文件口径 = 21
    ("### 7.3 样本资产（24 个文件）",
     "### 7.3 样本资产（21 个跟踪文件）", 1),
    # 3) pytest 实跑：本机 383 passed / 2 failed / 2 skipped；
    #    2 项失败是 Windows 控制台下子进程 stdout 编码所致，HEAD 基线同样失败
    ("pytest **387 项**（本机实跑 385 passed / 2 skipped）",
     "pytest **387 项**（本机实跑 383 passed / 2 failed / 2 skipped；"
     "2 项失败为 Windows 控制台子进程 stdout 编码所致，HEAD 基线同样失败）", 1),
    # 4) `mcopilot all` 跑批：PYTHONPATH=src 下本机 3.8 秒 / 34 个文件
    ("**3.9 秒完成，退出码 0，产出 36 个文件**（含 4 张 PNG、6 个 C# 源、8 组 md+html 报告）",
     "**本机 3.8 秒完成，退出码 0，产出 34 个文件**（含 6 张 PNG、7 个 C# 源、10 组 md+html 报告）", 1),
]

txt = io.open(W, encoding="utf-8", newline="").read()
failed = []
for old, new, cnt in FIXES:
    got = txt.count(old)
    if got != cnt:
        failed.append((old[:70], got, cnt))
        continue
    txt = txt.replace(old, new)
if failed:
    print("✗ 未达期望命中数，未写盘：")
    for old, got, cnt in failed:
        print(f"    期望 {cnt} 实得 {got}  ← {old}")
    sys.exit(1)
io.open(W, "w", encoding="utf-8", newline="").write(txt)
print(f"✓ {len(FIXES)} 处数字已按实跑结果订正（CodeWiki 仍为未入库状态，入库前最后一道）")
