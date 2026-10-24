#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refresh_out_v_unique.py —— 把 out_v_unique/ 里与 out/ 重名的陈旧副本刷新到最新（2026-10-22）。

背景：out/ 重新生成后（外置路径改写 + 时间戳 + 生成器修复），out_v_unique/ 里
14+6 个**重名副本**仍停在旧版本 —— 两处内容对不上，读者一比就发现不一致。

处置：
  · 重名副本 → 按 out/ 的最新内容刷新（去重件的"唯一性"不变 ✓）；
  · out_v_unique 独有的件（NativeLoader.cs / Units.cs / tech-debt.md /
    glue_report.csv / bin/GlueDemo.exe）→ **保留不删**：
    当前生成器已不产出它们（gen/ 里查无对应 ✓），但"曾经有过"是事实，
    删记录比留着不匹配更糟 —— 只在刷新报告里如实标出"生成器已不产出" ✓。
"""
import filecmp
import os
import shutil

REPO = r"%WORKSPACE%\trae_factory"


def refresh(unique_dir: str, out_dir: str) -> tuple[int, int, list]:
    same = diff = 0
    extras = []
    for root, _dirs, files in os.walk(unique_dir):
        for fn in files:
            up = os.path.join(root, fn)
            rel = os.path.relpath(up, unique_dir)
            op = os.path.join(out_dir, rel)
            if not os.path.isfile(op):
                extras.append(rel)
                continue
            if filecmp.cmp(up, op, shallow=False):
                same += 1
                continue
            shutil.copy2(op, up)
            diff += 1
    return same, diff, extras


total_same = total_diff = 0
for brand in sorted(os.listdir(os.path.join(REPO, "out_v_unique"))):
    u = os.path.join(REPO, "out_v_unique", brand)
    o = os.path.join(REPO, "out", brand)
    if not os.path.isdir(u) or not os.path.isdir(o):
        continue
    same, diff, extras = refresh(u, o)
    total_same += same
    total_diff += diff
    print(f"  {brand}: 相同 {same} ｜ 已刷新 {diff}")
    if extras:
        print(f"    独有件（保留，生成器已不产出）：{', '.join(sorted(extras))}")
print(f"\n合计：相同 {total_same} ｜ 刷新 {total_diff}")
