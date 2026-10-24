#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump_gap_lines.py —— 把批 B 待清偿的行的**完整原文**打出来（2026-10-22）。"""
import io

SPECS = [
    (r"%WORKSPACE%\mcopilot\knowledge\coverage_ledger.json", [89, 92, 118, 119, 358, 359, 361]),
    (r"%WORKSPACE%\mcopilot\samples\servo\PROVENANCE.md", [15, 16, 17, 18, 19, 69]),
    (r"%WORKSPACE%\mcopilot\samples\servo\darus3252_prbs_pos_ppi.truth.json", [9]),
    (r"%WORKSPACE%\mcopilot\samples\servo\darus6114_x_prbs.truth.json", [9]),
    (r"%WORKSPACE%\mcopilot\samples\servo\darus6114_x_velsweep.truth.json", [9]),
    (r"%WORKSPACE%\mcopilot\samples\servo\klipper_resonance_x.truth.json", [7]),
    (r"%WORKSPACE%\mcopilot\samples\servo\twincat_export10.truth.json", [9, 10]),
    (r"%WORKSPACE%\mcopilot\knowledge\protocols\focas.json", [24, 34]),
    (r"%WORKSPACE%\mcopilot\knowledge\protocols\failure_signatures.json", [15, 20]),
    (r"%WORKSPACE%\mcopilot\knowledge\templates\protocol\README.md", [236]),
    (r"%WORKSPACE%\mcopilot\README.md", [435, 436, 437, 438]),
    (r"%WORKSPACE%\axiscope\docs\kb\KB0-conventions.md", [500, 522, 524, 532, 546]),
    (r"%WORKSPACE%\axiscope\data\validate_vendor.json", [434, 843]),
    (r"%WORKSPACE%\trae_factory\out_v_unique\mc_all\README.md", [34, 37]),
]

for path, lines_wanted in SPECS:
    print("=" * 100)
    print(f"【{path}】")
    print("=" * 100)
    lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
    for n in lines_wanted:
        if n <= len(lines):
            print(f"  L{n}: {lines[n-1]}")
    print()
