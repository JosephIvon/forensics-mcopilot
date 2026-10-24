#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_ch06_07_03_machine_coords.py —— 三章裸行号坐标机判化（2026-10-22）。

问题：新写的 ch06/ch07/ch03 里还有 18 处"（`:11-12`）"式裸行号（靠上文猜是哪个文件），
机器审计判不了 → 等于这些坐标没被核过。
处置：每处补上自己的文件名（路径或 KB/C 别名），让行号全部进机器判。
纪律：替换前先验命中数，为 0 就报错退出（避免 PowerShell 反引号吃掉标记那类静默失败）。
"""
import io
import os
import sys

REPO = r"%WORKSPACE%\forensics-learning-book"

PAIRS = [
    # ---- ch06 ----
    ("chapters-vol2a/ch06-厂商方言与上下文契约.md",
     "同目录侧车文件声称的采样率（`:11-12`）",
     "同目录侧车文件声称的采样率（`dialects.py:11-12`）"),
    ("chapters-vol2a/ch06-厂商方言与上下文契约.md",
     "且\"汇总数由脚本自数，检查 27\"（`:654-655`）",
     "且\"汇总数由脚本自数，检查 27\"（`KB2-waveform-formats.md:654-655`）"),
    ("chapters-vol2a/ch06-厂商方言与上下文契约.md",
     "（`:15`）。注意第二条纪律",
     "（`registration.py:15`）。注意第二条纪律"),
    # ---- ch07 ----
    ("chapters-vol2a/ch07-没有真机时.md",
     "1. **串级被拍平**（`:15-18`，逐字）",
     "1. **串级被拍平**（`synth/integrator.py:15-18`，逐字）"),
    ("chapters-vol2a/ch07-没有真机时.md",
     "2. **缺参数就编一个**（`:19-21`，逐字）",
     "2. **缺参数就编一个**（`synth/integrator.py:19-21`，逐字）"),
    ("chapters-vol2a/ch07-没有真机时.md",
     "3. **离散搬不动的东西硬搬**（`:22-25`，逐字）",
     "3. **离散搬不动的东西硬搬**（`synth/integrator.py:22-25`，逐字）"),
    ("chapters-vol2a/ch07-没有真机时.md",
     "连\"通过之后能说什么\"都写死了（`:12-13`，逐字）",
     "连\"通过之后能说什么\"都写死了（`synth/integrator.py:12-13`，逐字）"),
    ("chapters-vol2a/ch07-没有真机时.md",
     "每条都挂着 why（`:4`、`:9`）。",
     "每条都挂着 why（`bench/forbidden_patterns.json:4` 与 `bench/forbidden_patterns.json:9`）。"),
    ("chapters-vol2a/ch07-没有真机时.md",
     "*参考*：C5 §2（`:46-48`）",
     "*参考*：C5 §2（`C5:46-48`）"),
    # ---- 册二 ch03 ----
    ("chapters-vol2b/ch03-手册进知识库.md",
     "用的是 Windows 自带的 `Windows.Media.Ocr`（`:3-9`）",
     "用的是 Windows 自带的 `Windows.Media.Ocr`（`ocr.ps1:3-9`）"),
    ("chapters-vol2b/ch03-手册进知识库.md",
     "语言钉死 `zh-CN`（`:20-21`）",
     "语言钉死 `zh-CN`（`ocr.ps1:20-21`）"),
    ("chapters-vol2b/ch03-手册进知识库.md",
     "再取不到就报错退出（`:22-23`）",
     "再取不到就报错退出（`ocr.ps1:22-23`）"),
    ("chapters-vol2b/ch03-手册进知识库.md",
     "最后一行输出识别文本（`:30`）",
     "最后一行输出识别文本（`ocr.ps1:30`）"),
    ("chapters-vol2b/ch03-手册进知识库.md",
     "生成的 P/Invoke 段也把来源挂在代码注释里（`:40`，逐字）",
     "生成的 P/Invoke 段也把来源挂在代码注释里（`gen/adapters_kb.js:40`，逐字）"),
    ("chapters-vol2b/ch03-手册进知识库.md",
     "与 `ok`（是否已核对），例如（`:23-24`）",
     "与 `ok`（是否已核对），例如（`gen/adapters_kb.js:23-24`）"),
    ("chapters-vol2b/ch03-手册进知识库.md",
     "固高适配器里有一条（`:37`，逐字）",
     "固高适配器里有一条（`gen/adapters_kb.js:37`，逐字）"),
    ("chapters-vol2b/ch03-手册进知识库.md",
     "雷赛那边同款（`:337`、`:382`）",
     "雷赛那边同款（`gen/adapters_kb.js:337`、`gen/adapters_kb.js:382`）"),
    ("chapters-vol2b/ch03-手册进知识库.md",
     "第 1 章那批 S 曲线参数就是标准示范（`:196-199`，逐字）",
     "第 1 章那批 S 曲线参数就是标准示范（`gen/adapters_kb.js:196-199`，逐字）"),
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
        print(f"[SKIP 命中 {n} 次] {rel}: {old[:46]}")
        fail += 1
        continue
    cache[path] = t.replace(old, new)
    print(f"[OK] {rel}：{old[:34]}… → {new[:40]}…")
for path, t in cache.items():
    io.open(path, "w", encoding="utf-8", newline="\n").write(t)
print("失败条数：", fail)
sys.exit(1 if fail else 0)
