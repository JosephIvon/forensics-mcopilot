#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_batch_b_edits.py —— 批 B 落盘后的合法性复验（2026-10-22）。

改文档不能只改对，还要**改不坏**：JSON 要能解析、真值文件字段要齐、行数不许漂移
（真值文件是书里的坐标目标，行号漂移会让书的坐标指向别处）。
"""
import io
import json
import os
import subprocess
import sys

MC = r"%WORKSPACE%\mcopilot"
JSONS = [
    r"knowledge\coverage_ledger.json",
    r"knowledge\protocols\focas.json",
    r"knowledge\protocols\failure_signatures.json",
    r"samples\servo\darus3252_prbs_pos_ppi.truth.json",
    r"samples\servo\darus6114_x_prbs.truth.json",
    r"samples\servo\darus6114_x_velsweep.truth.json",
    r"samples\servo\klipper_resonance_x.truth.json",
    r"samples\servo\twincat_export10.truth.json",
]
ok = True

print("【一】JSON 解析与关键字段")
for rel in JSONS:
    p = os.path.join(MC, rel)
    try:
        d = json.load(io.open(p, encoding="utf-8"))
    except Exception as e:
        print(f"  ✗ {rel} 解析失败：{e}")
        ok = False
        continue
    extra = ""
    if rel.endswith(".truth.json"):
        for k in ("truth_basis", "provenance", "evidence_type"):
            if k not in d:
                extra = f"  **缺字段 {k}**"
                ok = False
    print(f"  ✓ {rel} 解析通过（顶层 {len(d)} 键）{extra}")

print("\n【二】行数对照：HEAD 版 vs 工作树版（真值文件不许行数漂移）")
for rel in JSONS + [r"samples\servo\PROVENANCE.md", r"knowledge\templates\protocol\README.md", r"README.md"]:
    p = os.path.join(MC, rel)
    wt = len(io.open(p, encoding="utf-8", errors="replace").read().splitlines())
    head_txt = subprocess.run(["git", "-C", MC, "show", f"HEAD:{rel.replace(os.sep, '/')}"],
                              capture_output=True).stdout.decode("utf-8", "replace")
    hl = len(head_txt.splitlines())
    flag = "" if hl == wt else "  ← 行数变了（检查书里是否按行号引它）"
    print(f"  {rel:<58} HEAD {hl:>4} → 工作树 {wt:>4}{flag}")

print("\n【三】书里按行号引用的目标文件，行数是否漂移")
BOOK = r"%WORKSPACE%\forensics-learning-book"
CITED = {
    "samples/servo/darus3252_prbs_pos_ppi.truth.json": "chapters/ch02-三态真值.md:209-210",
    "knowledge/protocols/failure_signatures.json": "chapters/ch06-诊断与归因.md:58",
    "samples/servo/PROVENANCE.md": "（书未按行号引）",
}
for rel, where in CITED.items():
    p = os.path.join(MC, rel.replace("/", os.sep))
    wt = len(io.open(p, encoding="utf-8", errors="replace").read().splitlines())
    head_txt = subprocess.run(["git", "-C", MC, "show", f"HEAD:{rel}"],
                              capture_output=True).stdout.decode("utf-8", "replace")
    hl = len(head_txt.splitlines())
    same = "行数未变 ✓ 书的行号坐标仍指向原意" if hl == wt else "**行数变了 → 书的行号坐标需复核**"
    print(f"  {rel:<50} {where:<34} {same}")

sys.exit(0 if ok else 1)
