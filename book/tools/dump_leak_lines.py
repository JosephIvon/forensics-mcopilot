#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump_leak_lines.py —— 打印泄露点的完整原文行（2026-10-22，批 C 用）。"""
import io
import os
import re

JOBS = [
    (r"%WORKSPACE%\mcopilot", [
        ("scripts/gate_protocol.ps1", [31, 32]),
        ("scripts/gate_corpus.ps1", [25]),
        ("scripts/gate_farm.ps1", [30]),
        ("scripts/gate_negative.ps1", [30]),
        ("scripts/gate_onboard.ps1", [30]),
        ("knowledge/templates/protocol/run_contract.ps1", [31]),
        ("knowledge/templates/protocol/run_rtu_contract.ps1", [29]),
        ("tests/test_fault_mode_slugs.py", [34]),
        ("scripts/verify_trae_pinvoke.py", [56]),
        ("scripts/verify_traekb_citations.py", [49]),
        ("tests/test_trae_truth_bridge.py", [31]),
        ("README.md", [402]),
    ]),
    (r"%WORKSPACE%\axiscope", [
        ("docs/AUDIT-glm-code-factory.md", [4]),
        ("docs/AUDIT-minimax-round3.md", [5]),
        ("docs/kb/KB0-conventions.md", [540, 546]),
        ("docs/kb/KB5-simulation-plant.md", [795]),
        ("data/PROVENANCE-TEMPLATE.md", [53]),
        ("data/VERIFICATION-2026-10-20.md", [14]),
        ("data/research_5171_cdd.md", [295]),
        ("docs/kb/KB2-waveform-formats.md", [51, 788]),
        ("docs/kb/KB7-dataset-da-rus-cat.md", [182]),
        ("README.md", [80]),
    ]),
    (r"%WORKSPACE%\trae_factory", []),
]

for repo, files in JOBS:
    print("#" * 96)
    print(f"# {repo}")
    print("#" * 96)
    for rel, lns in files:
        p = os.path.join(repo, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            print(f"  [缺文件] {rel}")
            continue
        lines = io.open(p, encoding="utf-8", errors="replace").read().splitlines()
        for n in lns:
            if n <= len(lines):
                print(f"  {rel}:{n}")
                print(f"      {lines[n-1].strip()[:300]}")
    print()
