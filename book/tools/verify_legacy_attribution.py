#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_legacy_attribution.py —— 卷一三章裸行号的归属核对（2026-10-22）。

按上下文给出候选文件后，把**锚点处**的候选行打出来逐条人眼核对
（机器判"指得对不对"，人判"说的是不是那件事"）。
"""
import subprocess

MCO = r"%WORKSPACE%\mcopilot"
REV = "b53ac62"

CANDIDATES = {
    "knowledge/protocols/anchors.json": [(57, 63), (64, 65), (65, 95), (97, 122)],
    "scripts/fault_farm.py": [(395, 404)],
    "knowledge/contracts/comm_log_contract.json": [
        (2, 5), (5, 5), (8, 8), (12, 13), (20, 20), (31, 31), (36, 36), (44, 44),
        (71, 71), (89, 99), (101, 103), (105, 109), (128, 133)],
    "scripts/validate_comm_log.py": [(10, 13), (130, 131)],
    "src/mcopilot/agents/forensics_comm.py": [(12, 17), (63, 63), (100, 111)],
    "knowledge/protocols/failure_signatures.json": [(5, 10), (11, 20)],
    "scripts/onboard_loop.py": [(11, 12), (16, 34)],
    "scripts/eval_forensics.py": [(13, 16), (32, 32), (38, 40)],
}

for path, ranges in CANDIDATES.items():
    r = subprocess.run(["git", "-C", MCO, "show", f"{REV}:{path}"], capture_output=True)
    if r.returncode:
        print(f"!! 取不到 {path}")
        continue
    lines = r.stdout.decode("utf-8", "replace").splitlines()
    print(f"== {path}（{len(lines)} 行）")
    for a, b in ranges:
        seg = " / ".join(x.strip()[:96] for x in lines[a - 1:b])
        print(f"   :{a}-{b}  {seg}")
