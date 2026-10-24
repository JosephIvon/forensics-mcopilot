#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""finalize_batch_c_book.py —— 批 C 的书侧收尾：索引仓登记 + 清单结转 + 台账补一条（2026-10-22 夜）。

三件事：
  1. ASSETS.md 登记索引仓（批 D 的产物：三仓 + 索引）✓
  2. 第 5 份决策清单的结转表更新（批 D 的现状：索引已备，推送待作者给账号）✓
  3. 台账补一条：**工具的"假 0"比没有工具更坏** ✓
"""
import io
import os

BOOK = r"%WORKSPACE%\forensics-learning-book"
LEDGER = r"%USERPROFILE%\self-improving\ledger.md"

# ── 1. ASSETS.md ─────────────────────────────────────────────────────────
p = os.path.join(BOOK, "ASSETS.md")
txt = io.open(p, encoding="utf-8", newline="").read()
anchor = "  决策清单：`decision-lists/release-hardening-20261022.md`（第 5 份 ✓）。\n"
if anchor not in txt:
    raise SystemExit("✗ ASSETS 锚点未命中")
add = (
    "- [2026-10-22 本轮·批 D 发布准备] **索引仓已备，推送待作者给账号**：\n"
    "  新建 `%WORKSPACE%\\forensics-learning-index`（`README.md` 索引 + `PUSH-CHECKLIST.md` 清单 +\n"
    "  `LICENSE` ✓，3 件 ✓，首次提交 `df75d7d` ✓）。索引里写清三仓的接缝图、\n"
    "  真值链三根轴与各品牌 P/Invoke 实数（58 = 钉扎 49 + 降级 9 ✓）、\n"
    "  以及**还没接上的**（真机层未验证 ✓、接缝 3 未闭合 ✓、早期提交仍是自动化署名 ✓）。\n"
    "  推送清单逐项列出**推送前必须自己过的 10 项检查**（本地已跑过一遍 ✓，数字全部实测 ✓）\n"
    "  与**推完之后的验证**（含「在干净克隆里跑一遍主命令」✓ ——\n"
    "  干净克隆与本机工作树的差异，正是公开后读者实际拿到的东西 ✓）。\n"
    "  **未推送** ✓：需要作者的 GitHub 账号、三个仓名与公开/私有决定 ✓。\n"
)
txt = txt.replace(anchor, anchor + add, 1)
io.open(p, "w", encoding="utf-8", newline="").write(txt)
print("  ✓ ASSETS.md：索引仓登记")

# ── 2. 决策清单结转表 ───────────────────────────────────────────────────
p = os.path.join(BOOK, "decision-lists", "release-hardening-20261022.md")
txt = io.open(p, encoding="utf-8", newline="").read()
old = ("| GitHub 三个独立仓 + 索引仓的实际创建与推送 | 批 D | **未开始**；需作者提供账号/仓名/公开或私有 ✓ |")
new = ("| GitHub 三个独立仓 + 索引仓的实际创建与推送 | 批 D | **索引仓已备**（`forensics-learning-index` ✓，3 件 ✓）；"
       "**推送未执行** ✓——需作者提供账号/仓名/公开或私有 ✓ |")
if old not in txt:
    raise SystemExit("✗ 决策清单结转锚点未命中")
txt = txt.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="").write(txt)
print("  ✓ decision-lists/release-hardening-20261022.md：结转表更新")

# ── 3. 台账补一条 ───────────────────────────────────────────────────────
entry = (
    "- [2026-10-22 夜] 命中 **工具的「假 0」比没有工具更坏**（新类，代价最实）：绝对路径扫描器报"
    "「家目录 0 处」✓，我据此判「清账完成」✓——**其实整批中文名文件从未被扫过** ✗。\n"
    "  根因：`git ls-files` 对非 ASCII 路径默认加引号并转义（形如 \"docs/jd_\\350\\257\\201...\"）✗，\n"
    "  按该列表拼路径必然 isfile 失败 → mcopilot 的 **29 个**中文名文件被静默跳过 ✗。\n"
    "  是另一个工具（发布体检）用工作树遍历而查出了 7 处真泄露 ✗ 才暴露。\n"
    "  新规：①凡用 `git ls-files` 的工具，一律改 `-z`（NUL 分隔、不加引号）✓；\n"
    "  ②**检查器的「0」必须自己复核**——至少用另一种实现方式（工作树遍历）交叉验一次 ✓；\n"
    "  ③交叉验的差额本身就是缺陷线索（本次差额 = 漏检的那批 ✓）。\n"
    "  附带一条同族教训：同一处泄露常常有**第二个落点**——axiscope 那次脱敏覆盖了 data/raw ✓，\n"
    "  却漏了 data/sidecar_in/ 的侧车来源记录 ✗（那里逐字引用了上游文件自报的路径 ✓）。\n"
)
old_ledger = io.open(LEDGER, encoding="utf-8").read()
if not old_ledger.endswith("\n"):
    old_ledger += "\n"
io.open(LEDGER, "w", encoding="utf-8").write(old_ledger + entry)
print("  ✓ 台账：补 1 条（工具的假 0 + 同族第二落点）")
