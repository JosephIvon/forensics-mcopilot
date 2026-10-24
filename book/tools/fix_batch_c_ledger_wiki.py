#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_batch_c_ledger_wiki.py —— 批 C 第 6 项：账本路径与"本仓无 CI"类过期说法（2026-10-22）。

三处过期，都由本轮改动造成（或早前就漂移、这轮被本机路径清查带出来）：
  1. knowledge/coverage_ledger.json 的 meta.projects[].path 写死本机 %WORKSPACE%\\*
     → 改为同级兄弟相对路径（../trae_factory / . / ../axiscope）✓
     该字段只用于 JD 报告里**展示**（jd.py 不做文件系统解析 ✓），改它零风险 ✓
  2. CodeWiki §9.4/§9.7 登记的"本仓无 .github/"、README 目录树列不存在的脚本
     → 补上真实状态（CI 已补；README 树早前已修 ✓）
  3. samples/servo/PROVENANCE.md:69 的"本仓 HEAD 无 .github/ 目录" → 已补 CI ✓

纪律：CodeWiki 是**活文档**（前几轮已订正过它的过期数字 ✓），不是冻结快照 ✓，
所以事实变了就改；改的时候**把"曾经如此"留在原处并标注** ✓，不抹掉历史 ✓。
"""
import io
import json
import os
import sys

MC = r"%WORKSPACE%\mcopilot"


def read(p):
    return io.open(p, encoding="utf-8", newline="").read()


def write(p, s):
    io.open(p, "w", encoding="utf-8", newline="").write(s)


# ── 1. 账本：三处本机路径 → 同级兄弟相对路径 ────────────────────────────────
lp = os.path.join(MC, "knowledge", "coverage_ledger.json")
led = json.loads(read(lp))
meta = led["meta"]
NEW_PATH = {"trae_factory": "../trae_factory", "mcopilot": ".", "axiscope": "../axiscope"}
for k, v in NEW_PATH.items():
    meta["projects"][k]["path"] = v
meta["path_base"] = "相对本仓根目录（knowledge/coverage_ledger.json 所在仓的根）——同级兄弟工程"
write(lp, json.dumps(led, ensure_ascii=False, indent=2) + "\n")
print("  ✓ knowledge/coverage_ledger.json：三处 path 改相对 + 加 path_base 说明")

# ── 2. CodeWiki 的四处说法 ───────────────────────────────────────────────
WIKI = os.path.join(MC, "docs", "CodeWiki_20261022.md")
FIX_WIKI = [
    (
        "| 兄弟工程 | `knowledge/coverage_ledger.json` 的 `meta.projects[].path` 指向 `%WORKSPACE%\\*` 三个项目 | **本机专用路径**，换机需改（见 §9.4） |",
        "| 兄弟工程 | `knowledge/coverage_ledger.json` 的 `meta.projects[].path` 指向**同级兄弟目录**（`../trae_factory` / `../axiscope`，本仓自身为 `.`） | 相对路径，**换机不用改**：三仓平级摆放即可 |",
    ),
    (
        "- `samples/servo/PROVENANCE.md:69` 写「`.github/workflows/ci.yml` 跑的是 `scripts/run_gates.py`」——**这两个文件在仓库里都不存在**（`git ls-files` 确认未跟踪）。",
        "- `samples/servo/PROVENANCE.md:69` 早前版本写「`.github/workflows/ci.yml` 跑的是 `scripts/run_gates.py`」——**这两个文件当时在仓库里都不存在**（`git ls-files` 确认未跟踪）。**2026-10-22 公开前硬化已补 `.github/workflows/gates.yml`**（CI 真实存在 ✓；但**仍无** `scripts/run_gates.py` ✓——CI 调的是 `scripts/gate_*.ps1` 各门 ✓）。",
    ),
    (
        "- `README.md` 目录树引用 `scripts/verify_export10_truth.py` —— 不存在。",
        "- `README.md` 目录树曾引用 `scripts/verify_export10_truth.py` —— 不存在；**已在本轮一并修正**（见 §9.6 ✓）。",
    ),
    (
        "**即：「统一 Python 门禁入口 + CI + 真机样本校验脚本」这一整套不在 HEAD。** 入库的负向测试只有 PowerShell 版 `scripts/gate_negative.ps1`。",
        "**即：「统一 Python 门禁入口 + CI + 真机样本校验脚本」这一整套不在 HEAD。** 入库的负向测试只有 PowerShell 版 `scripts/gate_negative.ps1`。\n"
        "**2026-10-22 公开前硬化后**：**CI 已补**（`.github/workflows/gates.yml` ✓，windows-latest + pytest + G1–G12 + 其余六门 ✓）；\n"
        "但**「统一 Python 门禁入口」与「真机样本校验脚本」仍不在仓** ✓（`scripts/run_gates.py` 无 ✓，那五个真机脚本无 ✓）。",
    ),
    (
        "- `knowledge/coverage_ledger.json` 的 `meta.projects[].path` 写死本机 `%WORKSPACE%\\*` 三个路径。",
        "- ~~`knowledge/coverage_ledger.json` 的 `meta.projects[].path` 写死本机 `%WORKSPACE%\\*` 三个路径~~ —— **2026-10-22 已改**：改为同级兄弟相对路径（`../trae_factory` / `.` / `../axiscope`）✓，并在 `meta.path_base` 写明基准 ✓。",
    ),
    (
        "- `knowledge/templates/protocol/ModbusRtuContractRunner.exe` 是**被 git 跟踪的编译产物**，且当前工作树有未提交修改。",
        "- `knowledge/templates/protocol/ModbusRtuContractRunner.exe` 是**被 git 跟踪的编译产物**——门禁每次跑都会重编译它，按「同源重建非代码变更」**退回**（不进提交 ✓）。",
    ),
]
txt = read(WIKI)
missed = []
for old, new in FIX_WIKI:
    if txt.count(old) != 1:
        missed.append(old[:70])
        continue
    txt = txt.replace(old, new)
if missed:
    print("✗ CodeWiki 有替换未命中（未写盘）：")
    for m in missed:
        print("   ", m)
    sys.exit(1)
write(WIKI, txt)
print(f"  ✓ docs/CodeWiki_20261022.md：{len(FIX_WIKI)} 处说法改到实况")

# ── 3. PROVENANCE.md 的"无 .github/" ─────────────────────────────────────
PROV = os.path.join(MC, "samples", "servo", "PROVENANCE.md")
old = "**CI 与门禁入口的实况（2026-10-22 按 git ls-files 复核）**：本仓 HEAD **无 `.github/` 目录**，**无 `scripts/run_gates.py`**"
new = ("**CI 与门禁入口的实况（2026-10-22 按 git ls-files 复核；公开前硬化后补记）**："
       "本仓**已有 `.github/workflows/gates.yml`**（windows-latest + pytest + G1–G12 + 其余六门 ✓），"
       "**仍无 `scripts/run_gates.py`**")
txt = read(PROV)
if txt.count(old) != 1:
    print("✗ PROVENANCE.md 替换未命中，未写盘")
    sys.exit(1)
write(PROV, txt.replace(old, new))
print("  ✓ samples/servo/PROVENANCE.md:69：CI 状态改到实况")
