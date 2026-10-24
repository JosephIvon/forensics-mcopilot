#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_batch_b_doc_gaps.py —— 批 B：mcopilot 文档↔HEAD 不一致的定点清偿（2026-10-22）。

处置原则（作者定的"能核验优先"）：
  · 文档声称存在而仓里没有 → **改文档指到真东西**，或明写"未入库、当前不可自动复核"；
  · 反例引用（文档明说该文件被删/不存在）→ **不动**；
  · 记录性引用（校验报告里的历史 path 字段）→ **不动**；
  · 相对路径（相对所在目录解析）→ **不动**。

纪律：全部按"精确字符串 + 命中次数"替换，次数不符即报错退出——不静默改坏文件。
"""
import io
import os
import sys

MC = r"%WORKSPACE%\mcopilot"

# (文件, 旧串, 新串, 期望命中次数)
FIXES = [
    # ── 1. 覆盖账本：接缝 0 的三处"已落地"其实指向不存在的工件 ─────────────────────
    (r"knowledge\coverage_ledger.json",
     "scripts/annotate_provenance.py",
     "scripts/verify_traekb_citations.py", 1),
    (r"knowledge\coverage_ledger.json",
     "tests/test_sdk_provenance.py 14 项",
     "tests/test_trae_truth_bridge.py（4 项，HEAD 实测）+ scripts/verify_traekb_citations.py", 1),
    (r"knowledge\coverage_ledger.json",
     "+ docs/JointEval.md",
     "+ trae_factory@954c210 out/mc_all/docs/JointEval.md", 1),
    (r"knowledge\coverage_ledger.json",
     "落在 shared_eval.json 的断言上",
     "落在 trae_factory@954c210 gen/core.js 的接缝3 行为断言上（BEH-01/03/04/07/09/14/15 内置自检）", 1),
    (r"knowledge\coverage_ledger.json",
     "工厂 gen/truth_kb.js",
     "工厂 trae_factory@954c210 gen/truth_kb.js", 1),
    (r"knowledge\coverage_ledger.json",
     "docs/TruthChain.md 进每套件",
     "trae_factory@954c210 out/mc_all/docs/TruthChain.md 进每套件", 1),
    (r"knowledge\coverage_ledger.json",
     "src/mcopilot/core/c1_sample.py（契约加载器 19 测试）+ scripts/c1_from_servo_sample.py（转换器）"
     "+ agents/servo_c1.py（Waveform 桥 4 测试）",
     "knowledge/contracts/comm_log_contract.json（契约本体）+ scripts/validate_comm_log.py --selftest"
     "（裁判自检）；原计划的三件（src/mcopilot/core/c1_sample.py、scripts/c1_from_servo_sample.py、"
     "agents/servo_c1.py）未入库（2026-10-22 按 git ls-files 复核），"
     "故「19 测试 / 4 测试」一类计数当前无仓内载体", 1),
    (r"knowledge\coverage_ledger.json",
     "knowledge/shared_eval.json（19 条行为断言 + 3 条合法差异，唯一数据源）+ 工厂生成 docs/JointEval.md"
     " + mcopilot scripts/joint_eval.py 真跑两边出对照矩阵（out/joint_eval.md）",
     "trae_factory@954c210 gen/core.js（接缝3 行为断言 BEH-01/03/04/07/09/14/15 内置自检；断言不单独成文件）"
     "+ 工厂生成 trae_factory@954c210 out/mc_all/docs/JointEval.md；原计划的 knowledge/shared_eval.json 与 "
     "mcopilot scripts/joint_eval.py 未入库（2026-10-22 按 git ls-files 复核），"
     "故对照矩阵 out/joint_eval.md 当前无仓内载体", 1),
    (r"knowledge\coverage_ledger.json",
     '"status": "已落地（本轮，整改清单清零 + SPC 机器比对闭环）"',
     '"status": "已落地（行为断言在生成器代码内）；SPC 机器比对的对照脚本未入库，该项当前不可自动复核"', 1),

    # ── 2. 样本溯源表：5 个复算脚本名，仓里只有 1 个是真的 ─────────────────────────
    (r"samples\servo\PROVENANCE.md",
     "`scripts/verify_darus3252_servo.py`（不 import mcopilot）",
     "复算脚本未入库（2026-10-22 按 git ls-files 复核：HEAD 无此文件）；当日一次性独立复算，数值不可自动复核", 1),
    (r"samples\servo\PROVENANCE.md",
     "`scripts/verify_darus6114_servo.py`",
     "复算脚本未入库（2026-10-22 按 git ls-files 复核：HEAD 无此文件）；当日一次性独立复算，数值不可自动复核", 1),
    (r"samples\servo\PROVENANCE.md",
     "`scripts/verify_darus6114_sweep.py`",
     "复算脚本未入库（2026-10-22 按 git ls-files 复核：HEAD 无此文件）；当日一次性独立复算，数值不可自动复核", 1),
    (r"samples\servo\PROVENANCE.md",
     "`scripts/verify_klipper_resonance.py`（Welch+Kaiser 与自写 H1/FFT 两路线互证）",
     "Welch+Kaiser 与自写 H1/FFT 两路线互证（复算脚本未入库，2026-10-22 按 git ls-files 复核：HEAD 无此文件；"
     "当日一次性独立复算）", 1),
    (r"samples\servo\PROVENANCE.md",
     "`scripts/verify_export10_truth.py`",
     "`scripts/verify_servo_spectrum.py`（HEAD 实存；独立复算频域口径，不 import mcopilot）", 1),
    (r"samples\servo\PROVENANCE.md",
     "`.github/workflows/ci.yml` 跑的是 `scripts/run_gates.py`，其中 **5 条门禁读这些文件**："
     "`units`、`darus3252`、`darus6114`、`darus6114sweep`、`klipper`。",
     "**CI 与门禁入口的实况（2026-10-22 按 git ls-files 复核）**：本仓 HEAD **无 `.github/` 目录**，"
     "**无 `scripts/run_gates.py`**——本文早前版本声称二者存在，已按 `.self-improving/lessons.md` "
     "同日登记的教训条目更正。当前可跑的门禁是 `scripts/` 下 7 支"
     "（`gate_anchors.py`、`gate_corpus.ps1`、`gate_docsync.ps1`、`gate_farm.ps1`、`gate_negative.ps1`、"
     "`gate_onboard.ps1`、`gate_protocol.ps1`，门名 G1–G12 以 `Add-Gate` 注册），"
     "**不存在**名为 `units`/`darus3252`/`darus6114`/`darus6114sweep`/`klipper` 的独立门禁脚本"
     "（那 5 个名字是早期设计稿里的，未入库）。", 1),

    # ── 3. 四份真值文件：声称由不存在的脚本独立复算 ───────────────────────────────
    (r"samples\servo\darus3252_prbs_pos_ppi.truth.json",
     "由 scripts/verify_darus3252_servo.py 独立复算",
     "由当日一次性独立复算（**复算脚本未入库**，2026-10-22 按 git ls-files 复核；"
     "见 samples/servo/PROVENANCE.md 的复算说明）", 1),
    (r"samples\servo\darus6114_x_prbs.truth.json",
     "由 scripts/verify_darus6114_servo.py 独立复算",
     "由当日一次性独立复算（**复算脚本未入库**，2026-10-22 按 git ls-files 复核；"
     "见 samples/servo/PROVENANCE.md 的复算说明）", 1),
    (r"samples\servo\darus6114_x_velsweep.truth.json",
     "由 scripts/verify_darus6114_sweep.py 独立复算",
     "由当日一次性独立复算（**复算脚本未入库**，2026-10-22 按 git ls-files 复核；"
     "见 samples/servo/PROVENANCE.md 的复算说明）", 1),
    (r"samples\servo\klipper_resonance_x.truth.json",
     "由 scripts/verify_klipper_resonance.py 独立复算",
     "由当日一次性独立复算（**复算脚本未入库**，2026-10-22 按 git ls-files 复核；"
     "见 samples/servo/PROVENANCE.md 的复算说明）", 1),
    (r"samples\servo\twincat_export10.truth.json",
     "scripts/verify_export10_truth.py 从规范 CSV 独立复算",
     "scripts/verify_servo_spectrum.py 从规范 CSV 独立复算", 1),

    # ── 4. out/ 生成物：仓里没有是**设计如此**，但文档要说明白 ──────────────────────
    (r"knowledge\protocols\focas.json",
     "out/_protocols_focas/FOCAS2_Ethernet_Linux_en.txt（15 个 ===== [PAGE n] ===== 页标记）",
     "out/_protocols_focas/FOCAS2_Ethernet_Linux_en.txt（15 个 ===== [PAGE n] ===== 页标记；"
     "**本地提取产物，不入库**，sha256 与提取命令见 knowledge/protocols/anchors.json）", 1),
    (r"knowledge\protocols\focas.json",
     "out/_protocols_focas/FOCAS_function_list.txt（17 个页标记）",
     "out/_protocols_focas/FOCAS_function_list.txt（17 个页标记；**本地提取产物，不入库**，"
     "sha256 与提取命令见 knowledge/protocols/anchors.json）", 1),
    (r"knowledge\protocols\failure_signatures.json",
     "旧产物 DLL（out/_protocols_csharp/ModbusClients.dll）",
     "旧产物 DLL（out/_protocols_csharp/ModbusClients.dll；**本地构建产物，不入库**）", 1),
    (r"knowledge\protocols\failure_signatures.json",
     "/r: 引用 out/_protocols_csharp/ModbusClients.dll",
     "/r: 引用 out/_protocols_csharp/ModbusClients.dll（本地构建产物，不入库）", 1),
    (r"knowledge\templates\protocol\README.md",
     "全绿出《接入报告》`out/onboard_loop/onboard_report.md`。",
     "全绿出《接入报告》`out/onboard_loop/onboard_report.md`（**运行产物，out/ 不入库**）。", 1),
    (r"README.md",
     "mcopilot motion vectors --file out/golden_vectors.json",
     "mcopilot motion vectors --file out/golden_vectors.json    # 输出路径；out/ 是本地生成区，不入库", 1),
]


def main():
    cache = {}
    applied, failed = 0, []
    for rel, old, new, cnt in FIXES:
        path = os.path.join(MC, rel)
        if path not in cache:
            cache[path] = io.open(path, encoding="utf-8", newline="").read()
        txt = cache[path]
        got = txt.count(old)
        if got != cnt:
            failed.append((rel, old[:60], got, cnt))
            continue
        cache[path] = txt.replace(old, new)
        applied += 1
    if failed:
        print("✗ 有替换未达期望命中数，未写盘：")
        for rel, old, got, cnt in failed:
            print(f"    {rel}  期望 {cnt} 实得 {got}  ← {old}")
        sys.exit(1)
    for path, txt in cache.items():
        io.open(path, "w", encoding="utf-8", newline="").write(txt)
        print(f"  ✓ 写入 {os.path.relpath(path, MC)}")
    print(f"\n共 {applied} 处定点清偿已落盘（{len(cache)} 个文件）")


if __name__ == "__main__":
    main()
