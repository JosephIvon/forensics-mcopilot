#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_onboard_evidence_test.py —— 单独看 test_evidence_path 为何挂（2026-10-22）。"""
import io
import os
import subprocess
import sys

MC = r"%WORKSPACE%\mcopilot"
print("== 该测试的源码 ==")
p = os.path.join(MC, "tests", "test_onboard_loop.py")
lines = io.open(p, encoding="utf-8", errors="replace").read().splitlines()
for i, l in enumerate(lines, 1):
    if "evidence_path" in l or "def test_evidence" in l:
        for j in range(max(0, i - 12), min(len(lines), i + 22)):
            print(f"  :{j+1} {lines[j]}")
        break

print("\n== 实际跑这一条（工作树）==")
r = subprocess.run([sys.executable, "-m", "pytest",
                    "tests/test_onboard_loop.py::test_evidence_path", "-q"],
                   cwd=MC, capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout[-3000:])
