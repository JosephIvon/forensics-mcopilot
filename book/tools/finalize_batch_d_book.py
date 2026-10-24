#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""finalize_batch_d_book.py —— 批 D 的书侧登记：作者的三条裁定入册（2026-10-23 上午）。

作者裁定（2026-10-23 上午，问卷答复 ✓）：
  ① 三个工程仓**全部公开** ✓
  ② 默认分支**统一改成 main** ✓
  ③ trae_factory 的公开仓名改 **`forensics-code-factory`** ✓
     ——理由："trae 是专用的 IDE 开发工具，容易歧义" ✓

这三条进第 5 份决策清单（V 否决 / B 边界两处 + 结转表）✓ 与 ASSETS ✓。
"""
import io
import os
import sys

BOOK = r"%WORKSPACE%\forensics-learning-book"
DL = os.path.join(BOOK, "decision-lists", "release-hardening-20261022.md")
AS = os.path.join(BOOK, "ASSETS.md")

# ── 1. 决策清单：补 V14 / B13 / B14，并更新结转表 ──────────────────────
txt = io.open(DL, encoding="utf-8", newline="").read()

old_v = "- **V13 把三仓合成一个 GitHub 仓**——锚点语义破"
new_v = """- **V14 保留 `trae` 公开仓名**——作者裁定：「trae 是专用的 IDE 开发工具，容易歧义」✓。
  → 公开仓名改为 **`forensics-code-factory`** ✓。
  但**项目内名 `trae_factory` 不改** ✓：mcopilot 的脚本按「同级兄弟目录」发现它 ✓，
  书里也已按此名引用 ✓ —— 改目录名会断掉发现逻辑、也会让书与仓对不上 ✓。
  只改 GitHub 上的公开名 ✓，并在仓内 README 写明**内部名 ↔ 公开名**的对应 ✓。
- **V13 把三仓合成一个 GitHub 仓**——锚点语义破"""
if old_v not in txt:
    print("✗ V13 锚点未命中")
    sys.exit(1)
txt = txt.replace(old_v, new_v, 1)

old_b = "- **B12 第三方材料只登记不替权利人决定**"
new_b = """- **B13 可见性：三个工程仓全部公开**（作者裁定 2026-10-23 ✓）——
  与三仓的 MIT + 逐件署名义务一致 ✓；README/NOTICE 的写法本来就是按公开写的 ✓。
- **B14 分支统一 `main`**（作者裁定 ✓）：mcopilot 与 trae_factory 由 `master` 改名 ✓。
  **改名不改历史、不改任何坐标** ✓——坐标锚的是 commit，不是分支名 ✓。
- **B12 第三方材料只登记不替权利人决定**"""
if old_b not in txt:
    print("✗ B12 锚点未命中")
    sys.exit(1)
txt = txt.replace(old_b, new_b, 1)

old_t = "| GitHub 三个独立仓 + 索引仓的实际创建与推送 | 批 D | **索引仓已备**（`forensics-learning-index` ✓，3 件 ✓）；**推送未执行** ✓——需作者提供账号/仓名/公开或私有 ✓ |"
new_t = ("| GitHub 三个独立仓 + 索引仓的**实际推送** | 批 D | **四仓内容与命令均已备** ✓"
         "（`mcopilot` / `axiscope` / `forensics-code-factory` / `forensics-learning-index` ✓，"
         "分支统一 `main` ✓，可见性全部公开 ✓）；**推送未执行** ✓——"
         "本机无 `gh`、且 GitHub 账号未提供 ✓，由作者本机执行 ✓（命令见索引仓 `PUSH-CHECKLIST.md` ✓） |")
if old_t not in txt:
    print("✗ 结转表锚点未命中")
    sys.exit(1)
txt = txt.replace(old_t, new_t, 1)
io.open(DL, "w", encoding="utf-8", newline="").write(txt)
print("  ✓ decision-lists/release-hardening-20261022.md：V14 / B13 / B14 / 结转表")

# ── 2. ASSETS.md：批 D 的裁定登记 ──────────────────────────────────────
txt = io.open(AS, encoding="utf-8", newline="").read()
old = "  **未推送** ✓：需要作者的 GitHub 账号、三个仓名与公开/私有决定 ✓。\n"
new = ("  **未推送** ✓：本机无 `gh` ✓、GitHub 账号未提供 ✓ → 由作者本机执行 ✓。\n"
       "- [2026-10-23 上午·作者发布裁定] **可见性 / 分支 / 仓名三条落定**：\n"
       "  ① 三个工程仓**全部公开** ✓；② 默认分支**统一 `main`** ✓\n"
       "  （mcopilot `master`→`main` ✓、trae_factory `master`→`main` ✓、axiscope 本就是 `main` ✓；\n"
       "  **改名不改历史、不改任何坐标** ✓——坐标锚的是 commit 而非分支名 ✓）；\n"
       "  ③ trae_factory 的公开仓名改 **`forensics-code-factory`** ✓\n"
       "  （作者原话：「trae 是专用的 IDE 开发工具，容易歧义」✓）。\n"
       "  **项目内名 `trae_factory` 不改** ✓：mcopilot 脚本按「同级兄弟目录」发现它 ✓、\n"
       "  书里也已按此名引用 ✓ → 改目录名会断发现逻辑、也会让书与仓对不上 ✓；\n"
       "  只改 GitHub 公开名 ✓，并在仓内 README 写明**内部名 ↔ 公开名**的对应 ✓。\n")
if old not in txt:
    print("✗ ASSETS 锚点未命中")
    sys.exit(1)
txt = txt.replace(old, new, 1)
io.open(AS, "w", encoding="utf-8", newline="").write(txt)
print("  ✓ ASSETS.md：发布裁定登记")
