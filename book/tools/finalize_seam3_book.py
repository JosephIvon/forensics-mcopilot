#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""finalize_seam3_book.py —— 接缝 3 闭合入册（2026-10-23 傍晚）。

闭合的到底是什么 ✓
------------------
接缝 3 = **共享行为评测集** ✓。原来它是「计划过但没落地」：
工厂侧的断言内置在 trae_factory 的 gen/core.js 里活着 ✓，
而 mcopilot 侧的评测集文件与对照脚本**从未入库** ✓ ——
所以工厂端到端 PASS 里的每一步都指不回一条登记在案的断言 ✓，
2026-10-20 那份矩阵里工厂侧对 6 条断言的「实测命中」还是**粗粒度匹配** ✗
（只看 GlueDemo 整体 RESULT: PASS ✓，没逐条对上 ✓ ✗）。

闭合的标志是三样东西**同时在仓里** ✓：
  ① knowledge/shared_eval.json —— 唯一数据源（19 条行为断言 + 3 条合法差异 ✓）
  ② scripts/joint_eval.py —— 真跑两边的对照脚本 ✓（逐条按 BEH 编号对齐 ✓）
  ③ scripts/gate_joint_eval.py —— 门禁 G13 ✓（静态标签双向对齐 + 动态逐条对齐 ✓）
外加两侧都打上了 BEH 编号 ✓（mcopilot 侧 15 条 ✓、工厂侧 14 条 ✓）✓。

账要改的地方 ✓
--------------
  · mcopilot `knowledge/coverage_ledger.json` 的「接缝3」条 ✓ —— 原文写着
    「评测集与对照脚本未入库……当前无仓内载体」✓ → 现在过期了 ✓，必须改 ✓。
  · 书仓 `ASSETS.md` ✓ —— 登记闭合 ✓，并把「接缝 3 未闭合」从挂账里划掉 ✓。
  · 第 5 份决策清单 ✓ —— 结转表 ✓。
  · 台账 ✓ —— 补一条：粗粒度匹配不算逐条对齐 ✓。
"""
import io
import os
import sys

BOOK = r"%WORKSPACE%\forensics-learning-book"
MC = r"%WORKSPACE%\mcopilot"
DL = os.path.join(BOOK, "decision-lists", "release-hardening-20261022.md")
AS = os.path.join(BOOK, "ASSETS.md")
LEDGER = r"%USERPROFILE%\self-improving\ledger.md"


def read(p):
    return io.open(p, encoding="utf-8", newline="").read()


def write(p, t):
    io.open(p, "w", encoding="utf-8", newline="").write(t)


def sub(txt, old, new, what):
    eol = "\r\n" if "\r\n" in txt else "\n"
    o, n = old.replace("\n", eol), new.replace("\n", eol)
    if txt.count(o) != 1:
        print("✗ %s：命中 %d 处（应为 1）" % (what, txt.count(o)))
        sys.exit(1)
    return txt.replace(o, n)


# ── 1. mcopilot 覆盖账：接缝3 那条改成现在的实话 ──────────────────────
p = os.path.join(MC, "knowledge", "coverage_ledger.json")
txt = read(p)
txt = sub(txt,
    '"status": "已落地（行为断言在生成器代码内）；SPC 机器比对的对照脚本未入库，该项当前不可自动复核"',
    '"status": "已闭合（2026-10-23）：评测集与对照脚本均已入库，逐条对照可自动复核"',
    "覆盖账 status")
txt = sub(txt,
    "原计划的 knowledge/shared_eval.json 与 mcopilot scripts/joint_eval.py 未入库（2026-10-22 按 git ls-files 复核），"
    "故对照矩阵 out/joint_eval.md 当前无仓内载体：双方都验 11、工厂独有已验 1、合法差异 7、空白清零。",
    "**2026-10-23 接缝 3 闭合**：三样东西同时在仓里了——"
    "①knowledge/shared_eval.json（唯一数据源：19 条行为断言 + 3 条合法差异，逐条给域/两侧验证点；"
    "5 条 n/a 逐条写明工厂接口确无此概念，不是嘴上说说）"
    "②scripts/joint_eval.py（真跑两边：mcopilot 侧编译并跑仿真器自检，工厂侧编译并跑 GlueDemo 工艺流程，"
    "逐条按 BEH 编号对齐；BEH-19 另做 SPC 机器比对——从工厂 glue_report.csv 原始样本独立重算 Cpk 再与工厂打印值比）"
    "③scripts/gate_joint_eval.py（门禁 G13：静态核对两侧 BEH 标签与评测集**双向**对齐 + 动态真跑逐条对齐；"
    "缺环境记 SKIP 不记 PASS）。两侧各自打上了 BEH 编号（mcopilot 侧 15 条在 knowledge/templates/SelfCheck.cs.tmpl，"
    "工厂侧 14 条在 gen/core.js）——此前工厂侧对 BEH-12/13/16/17/18/19 的『命中』是**粗粒度匹配**"
    "（只看 GlueDemo 整体 RESULT: PASS），现已逐条可核。"
    "实测：双方都验 11 · 工厂独有已验 1 · 单边/合法差异 7 · 空白清零 · 共 19 条。"
    "工厂生成的 out/mc_all/docs/JointEval.md 现给出 mcopilot 侧验证点（数据源实时读取，非复制）。",
    "覆盖账 evidence")
# Cpk 那句：数值随本次运行的虚拟信号采样而变，比对的是同一次运行的两个实现
txt = sub(txt,
    "（含 SPC 机器比对：mcopilot 独立重算 Cpk 8.572 = 工厂同值）",
    "（含 SPC 机器比对：mcopilot 独立重算 Cpk 与工厂打印值同值——数值随本次运行的虚拟信号采样而变，"
    "比对的是**同一次运行**的两个独立实现，不拿历史数字充数）",
    "覆盖账 Cpk 口径")
write(p, txt)
print("  ✓ mcopilot knowledge/coverage_ledger.json：接缝3 条改为现在的实话 ✓")

# ── 2. 书仓 ASSETS ────────────────────────────────────────────────────
txt = read(AS)
anchor = ("  仍挂账的（不许抹掉 ✓）：真机层未验证 ✓、接缝 3 未闭合 ✓、\n"
          "  mcopilot 早期提交仍是自动化署名 ✓、协议标准原件外置 ✓（干净克隆时相关门禁记 SKIP ✓）。\n")
if anchor not in txt:
    print("✗ ASSETS 挂账锚点未命中")
    sys.exit(1)
new_anchor = ("  仍挂账的（不许抹掉 ✓）：真机层未验证 ✓、\n"
              "  mcopilot 早期提交仍是自动化署名 ✓、协议标准原件外置 ✓（干净克隆时相关门禁记 SKIP ✓）。\n")
entry = """- [2026-10-23 傍晚·**接缝 3 已闭合**] 共享行为评测集落地 ✓：
  接缝 3 原来是「计划过但没落地」——工厂侧断言内置在 `trae_factory` 的 `gen/core.js` 里活着 ✓，
  而 mcopilot 侧的评测集文件与对照脚本**从未入库** ✓ → 工厂端到端 PASS 里的每一步
  都指不回一条登记在案的断言 ✓；2026-10-20 那份矩阵里工厂侧对 6 条断言的「实测命中」
  还是**粗粒度匹配** ✗（只看 GlueDemo 整体 `RESULT: PASS` ✓，没逐条对上 ✓）。
  闭合的标志是三样东西**同时在仓里** ✓：
  ① `mcopilot knowledge/shared_eval.json` ✓ —— **唯一数据源** ✓：
     19 条行为断言（BEH-01…BEH-19 ✓）+ 3 条合法差异（DIV-01/02/03 ✓）✓，
     逐条给域 ✓、工厂侧验证点 ✓、mcopilot 侧验证点 ✓；
     5 条 `n/a` 逐条写明「工厂接口无此概念」✓（`HasRealFeedback` / `StopReason` /
     比较点与锁存端口在工厂 `IMotionController` 里确实没有 ✓ —— 不是嘴上说说 ✓）；
     `scope` 字段把「工厂独有」（BEH-16 ✓）与「单边」（BEH-17/18 ✓）分开 ✓
     ——**分类由数据说，脚本不猜** ✓。
  ② `mcopilot scripts/joint_eval.py` ✓ —— **真跑两边** ✓ 的对照脚本 ✓：
     侧 A 编译并跑 mcopilot 仿真器自检 ✓；侧 B 编译并跑工厂 GlueDemo 工艺流程 ✓；
     逐条按 BEH 编号对齐 ✓；BEH-19 另做 **SPC 机器比对** ✓ ——
     从工厂 `glue_report.csv` 的原始样本**独立重算** Cpk ✓ 再与工厂打印值比 ✓
     （不是抄工厂的数字 ✓）；`verdict` 只认本次实测 ✓；
     缺环境一律记 SKIP 并喊「当前不可自动复核」✓，不算通过 ✓。
  ③ `mcopilot scripts/gate_joint_eval.py` ✓ —— **门禁 G13**（域 22 ✓）：
     静态截（任何环境都能跑 ✓）核对两侧的 BEH 标签与评测集**双向**对齐 ✓
     （不许有没登记的标签 ✓，也不许登记了却没标签 ✓）；
     动态截真跑两侧逐条对齐 ✓；缺编译器或缺工厂兄弟仓 ⟹ 动态截 SKIP ✓，**不许记 PASS** ✓。
  外加两侧都打上了 BEH 编号 ✓（mcopilot 侧 15 条在 `knowledge/templates/SelfCheck.cs.tmpl` ✓，
  工厂侧 14 条在 `gen/core.js` ✓ —— 其中 6 条是**代码本来就在、只是没打编号** ✓，
  本轮补齐 ✓，行为逻辑一行未改 ✓）；工厂生成的 `out/mc_all/docs/JointEval.md`
  现给出 mcopilot 侧验证点 ✓（数据源实时读取 ✓，非复制 ✓）✓。
  实测：双方都验 11 ✓ · 工厂独有 1 ✓ · 单边/合法差异 7 ✓ · 空白清零 ✓ · 共 19 条 ✓。
  **干净克隆里可复核** ✓：三仓克隆到同一目录后，G13 真跑通过 ✓（不是 SKIP ✓）✓。
  清理克隆实测还抓到第 6 个隐式依赖 ✓：`compile_check.ps1` 要三个适配器都在才肯编译 ✓，
  而对照脚本只生成了一个 ✓ → 自检被 skip ✓ → 已改成按 `knowledge/sdks/` 清单全生成 ✓ ✓。
  坐标锚点**未动** ✓（`b53ac62` / `b95ffb2` / `954c210` ✓）：书中坐标按锚点 commit 读源文件 ✓，
  锚点之后的变更在本文件登记 ✓ —— 697 个坐标一个没受影响 ✓。
"""
txt = txt.replace(anchor, new_anchor + entry, 1)
# 索引仓那行里的「接缝 3 未闭合」也该改成已闭合（它是当时的快照，另加一句说明）
txt = txt.replace(
    "以及**还没接上的**（真机层未验证 ✓、接缝 3 未闭合 ✓、早期提交仍是自动化署名 ✓）。",
    "以及**还没接上的**（真机层未验证 ✓、接缝 3 未闭合 ✓、早期提交仍是自动化署名 ✓）"
    "——其中接缝 3 已于 2026-10-23 傍晚闭合 ✓（见下条 ✓）。", 1)
write(AS, txt)
print("  ✓ 书仓 ASSETS.md：接缝 3 闭合登记 ✓，挂账里划掉 ✓")

# ── 3. 第 5 份决策清单：结转表 ───────────────────────────────────────
txt = read(DL)
old = "| GitHub 三个独立仓 + 索引仓的**实际推送** | 批 D |"
idx = txt.find(old)
if idx < 0:
    print("✗ 结转表锚点未命中")
    sys.exit(1)
line_end = txt.find("\n", idx)
line = txt[idx:line_end]
if "接缝 3" not in line:
    # 结转表没提接缝 3 → 追加一行
    txt = (txt[:line_end + 1]
           + "| **接缝 3（共享行为评测集）闭合** | 批 D 续 | **已闭合** ✓："
             "评测集（`knowledge/shared_eval.json`，19 条 + 3 条合法差异 ✓）与对照脚本"
             "（`scripts/joint_eval.py`，真跑两边 ✓）均已入库 ✓，"
             "两侧都打上 BEH 编号 ✓，门禁 G13 逐条对齐 ✓（干净克隆里真跑通过 ✓）|"
             + txt[line_end + 1:])
else:
    print("  · 结转表已提到接缝 3，未改动 ✓")
write(DL, txt)
print("  ✓ 第 5 份决策清单：结转表补一行 ✓")

# ── 4. 台账 ─────────────────────────────────────────────────────────
old = io.open(LEDGER, encoding="utf-8").read()
entry2 = (
    "- [2026-10-23 傍晚] 命中 **粗粒度匹配不算逐条对齐**（接缝 3 复核时）：\n"
    "  2026-10-20 的共享评测矩阵里，工厂侧对 6 条断言写的是「实测命中」✓，\n"
    "  实际只看了 GlueDemo 整体 `RESULT: PASS` ✗ —— 没逐条对上 ✓。\n"
    "  看着有证据，其实证据只覆盖到「整体跑通了」这一层 ✗。\n"
    "  新规：①要声称「第 N 条断言通过」✓，就必须有**这一条**的编号或标记 ✓，\n"
    "  整体 PASS 不能拆成逐条 PASS ✓；②两侧的编号必须来自**同一份登记** ✓\n"
    "  （评测集是唯一数据源 ✓，工厂生成时实时读取 ✓，不另设副本 ✓）；\n"
    "  ③再加一道门禁把两侧编号与登记**双向**对齐 ✓ ——\n"
    "  不许有没登记的标签 ✓，也不许登记了却没标签 ✓。\n"
    "  另：干净克隆复验又抓到第 6 个隐式依赖 ✓ —— 脚本里硬写了一个 sdk 名 ✓，\n"
    "  而编译自检要三个都在 ✓ → 克隆里自检被 skip ✓ → 静默地少测了一半 ✓。\n"
    "  改成按仓内清单全生成 ✓（生成什么由数据说了算 ✓）。\n"
)
if not old.endswith("\n"):
    old += "\n"
io.open(LEDGER, "w", encoding="utf-8").write(old + entry2)
print("  ✓ 台账：补 1 条（粗粒度匹配不算逐条对齐）✓")
