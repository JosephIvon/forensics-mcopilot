#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_batch_d_names.py —— 批 D：按作者裁定更新仓名/分支/可见性（2026-10-23 上午）。

作者裁定（2026-10-23）：
  ① 三个工程仓**全部公开** ✓
  ② 默认分支**统一改成 main** ✓（mcopilot / trae_factory 由 master 改名 ✓，axiscope 本就是 main ✓）
  ③ trae_factory 改名 **`forensics-code-factory`** ✓
     ——理由："trae 是专用的 IDE 开发工具，容易歧义" ✓
     本地目录名 **不改** ✓（改了会断掉 mcopilot 脚本的「同级兄弟目录」发现逻辑 ✓，
     也与书里已有的仓名引用对不上 ✓）；只改 GitHub 上的公开仓名 ✓，
     并在仓内 README 写明「内部名 ↔ 公开名」的对应关系 ✓。

另：mcopilot 的 CodeWiki 快照标识写着分支 `master` ✗ → 改为实况并留痕 ✓。
"""
import io
import os
import sys

IDX = r"%WORKSPACE%\forensics-learning-index"
TF = r"%WORKSPACE%\trae_factory"
MC = r"%WORKSPACE%\mcopilot"

# ── 1. 索引仓 README：仓名 + 链接 + 可见性 ─────────────────────────────
p = os.path.join(IDX, "README.md")
txt = io.open(p, encoding="utf-8", newline="").read()
REPL = [
    ("| **[mcopilot](https://github.com/<账号>/mcopilot)** |",
     "| **[mcopilot](https://github.com/<账号>/mcopilot)** |"),
    ("| **[trae_factory](https://github.com/<账号>/trae_factory)** |",
     "| **[forensics-code-factory](https://github.com/<账号>/forensics-code-factory)** |"),
    ("| 仓 | 是什么 | 体量（入库） | 状态 |",
     "| 仓（GitHub 上的公开名） | 是什么 | 体量（入库） | 状态 |"),
    ("> 仓名与链接待作者定稿（GitHub 账号与仓名尚未提供 ✓）——\n"
     "> 本索引里的 `<账号>` 是占位符，推送前必须替换 ✓。",
     "> **可见性**：三个工程仓**全部公开** ✓（作者裁定 2026-10-23 ✓）。\n"
     "> **仓名**：`mcopilot` / `axiscope` / `forensics-code-factory` / 本索引仓 `forensics-learning-index` ✓；\n"
     "> **分支**：三个工程仓统一 `main` ✓（mcopilot 与 trae_factory 由 `master` 改名 ✓）。\n"
     "> **`<账号>` 仍是占位符** ✓——GitHub 账号尚未提供，推送前必须替换 ✓。"),
    ("| 册二《代码工厂与真值链卷》 | trae_factory | `954c210` |",
     "| 册二《代码工厂与真值链卷》 | trae_factory（公开名 `forensics-code-factory`） | `954c210` |"),
    ("git clone https://github.com/<账号>/trae_factory.git",
     "git clone https://github.com/<账号>/forensics-code-factory.git"),
    ("cd trae_factory && node test_gen.js all",
     "cd forensics-code-factory && node test_gen.js all"),
    ("cd axiscope && pip install -e . && python -m pytest -q",
     "cd axiscope && pip install -e . && python -m pytest -q"),
]
for old, new in REPL:
    if new in txt:
        continue          # 幂等：已改过就跳过
    if old not in txt:
        print(f"✗ 索引 README 未命中：{old[:60]}")
        sys.exit(1)
    txt = txt.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="").write(txt)
print("  ✓ 索引 README：仓名/链接/可见性/分支")

# ── 2. 索引仓 PUSH-CHECKLIST：分支与命令 ────────────────────────────────
p = os.path.join(IDX, "PUSH-CHECKLIST.md")
txt = io.open(p, encoding="utf-8", newline="").read()
REPL2 = [
    ("| 2 | 三个仓名（可与本地同名） | 拼仓 URL ✓ |",
     "| 2 | 三个仓名 | 已定：`mcopilot` / `axiscope` / `forensics-code-factory` ✓ |"),
    ("| 3 | 公开 / 私有 | 决定可见性与 CI 触发方式 ✓ |",
     "| 3 | 公开 / 私有 | 已定：**全部公开** ✓（作者裁定 2026-10-23 ✓） |"),
    ("git push -u origin master            # 本仓分支名是 master",
     "git push -u origin main              # 分支已统一为 main"),
    ("git push -u origin main              # 本仓分支名是 main（与 mcopilot 不同！）",
     "git push -u origin main              # 本仓本来就是 main"),
    ("git push -u origin master\n\n# ── 4) 索引仓（本仓）",
     "git push -u origin main\n\n# ── 4) 索引仓（本仓）"),
    ("**分支名不一致**（mcopilot/trae = `master` ✓，axiscope = `main` ✓）——\n"
     "GitHub 新建仓默认分支是 `main` ✓，推送 `master` 会**多出一个分支** ✓。\n"
     "两个选择都行 ✓，但**要在建仓时就定** ✓（推荐：推之前先\n"
     "`git branch -m master main` 统一 ✓，或建仓时选 master ✓）。",
     "**分支名已统一** ✓：三个工程仓都已在本地改为 `main` ✓\n"
     "（mcopilot 与 trae_factory 由 `master` 改名 ✓，axiscope 本就是 `main` ✓）。\n"
     "**改名不改历史、不改任何坐标** ✓——坐标锚的是 commit，不是分支名 ✓。"),
    ("git clone https://github.com/<账号>/<仓名1>.git && cd <仓名1> && python -m pytest -q",
     "git clone https://github.com/<账号>/mcopilot.git && cd mcopilot && python -m pytest -q"),
]
for old, new in REPL2:
    if new in txt:
        continue          # 幂等：已改过就跳过
    if old not in txt:
        print(f"✗ 推送清单未命中：{old[:60]}")
        sys.exit(1)
    txt = txt.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="").write(txt)
print("  ✓ 推送清单：分支与命令按统一 main 改")

# ── 3. trae_factory README：写明内部名 ↔ 公开名 ────────────────────────
p = os.path.join(TF, "README.md")
txt = io.open(p, encoding="utf-8", newline="").read()
old = "# trae_factory —— 上位机代码工厂\n"
new = ("# 上位机代码工厂（公开仓名 `forensics-code-factory`）\n"
       "\n"
       "> **仓名对照** ✓：本仓的**项目内名**仍是 `trae_factory` ✓（mcopilot 脚本按「同级兄弟目录」\n"
       "> 发现它 ✓，书里也已按此名引用 ✓，故不改 ✓）；GitHub 上的**公开仓名**是\n"
       "> `forensics-code-factory` ✓（作者裁定 2026-10-23 ✓）——\n"
       "> 原因是 `trae` 是一款专用 IDE 工具的名字 ✓，用作仓名容易歧义 ✓。\n")
if old in txt:
    txt = txt.replace(old, new, 1)
    io.open(p, "w", encoding="utf-8", newline="").write(txt)
    print("  ✓ trae_factory README：写明内部名 ↔ 公开名")
else:
    print("  ✓ trae_factory README：仓名对照已在（幂等跳过 ✓）")

# ── 4. mcopilot CodeWiki：分支快照标识 ────────────────────────────────
p = os.path.join(MC, "docs", "CodeWiki_20261022.md")
txt = io.open(p, encoding="utf-8", newline="").read()
old = "> **快照标识**：分支 `master` / HEAD `01eb884`（29 次提交）。"
new = "> **快照标识**：分支 `master`（2026-10-22 快照时；发布前统一改为 `main` ✓） / HEAD `01eb884`（29 次提交）。"
if old in txt:
    txt = txt.replace(old, new, 1)
    io.open(p, "w", encoding="utf-8", newline="").write(txt)
    print("  ✓ mcopilot CodeWiki：分支快照标识改到实况")
else:
    print("  ✓ mcopilot CodeWiki：快照标识已是实况（幂等跳过 ✓）")
