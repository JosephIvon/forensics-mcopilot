#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_batch_d_negative_tail.py —— 负向门禁的收尾话不许自相矛盾（2026-10-23）。

干净克隆实测输出：
    SKIP 1 条（**没跑**，不是没通过；当前不可自动复核）：…
    总退出码 0：已跑的用例全绿；SKIP 的用例**没跑**…，不算检测力已证明。
    总退出码 0：每个注入都让对应门变红，阳性对照全绿——检测力已证明。   ← 自相矛盾

有 SKIP 时最后那句「检测力已证明」是**假的**：那条用例根本没跑，
它的检测力既没证明也没否证。处置：有 SKIP 就不许说「已证明」✓。
"""
import io
import os
import sys

P = r"%WORKSPACE%\mcopilot\scripts\gate_negative.ps1"
txt = io.open(P, encoding="utf-8", newline="").read()
eol = "\r\n" if "\r\n" in txt else "\n"

old = ('if ($skipCount -gt 0) { Write-Output "总退出码 0：已跑的用例全绿；'
       'SKIP 的用例**没跑**（当前不可自动复核），不算检测力已证明。" }\n'
       'Write-Output "总退出码 0：每个注入都让对应门变红，阳性对照全绿——检测力已证明。"\n'
       'exit 0').replace("\n", eol)
new = ('if ($skipCount -gt 0) {\n'
       '    Write-Output "总退出码 0：已跑的用例全绿；SKIP 的用例**没跑**'
       '（当前不可自动复核），不算检测力已证明。"\n'
       '} else {\n'
       '    Write-Output "总退出码 0：每个注入都让对应门变红，阳性对照全绿——检测力已证明。"\n'
       '}\n'
       'exit 0').replace("\n", eol)

if txt.count(old) != 1:
    print(f"✗ 收尾话锚点命中 {txt.count(old)} 处")
    sys.exit(1)
txt = txt.replace(old, new, 1)
io.open(P, "w", encoding="utf-8", newline="").write(txt)
print("  ✓ scripts/gate_negative.ps1：有 SKIP 时不许说「检测力已证明」")
