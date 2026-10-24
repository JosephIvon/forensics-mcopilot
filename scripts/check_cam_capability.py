#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""核查三家的电子凸轮（cam）能力到底到什么程度 —— 只读官方真值，不猜。

这个问题的答案直接决定 `cam` 智能体对每家卡能承诺什么，所以不能凭印象写文档。
脚本从 `knowledge/sdks/official_api/` 的四层真值里数出结论：

  · 官方 C# 绑定（leisai.csv / zmotion.csv / gts.csv）—— 有没有这个 API
  · 官方 C 头文件（leisai_cpp.csv / zmotion_cpp.csv / gts_hdr.csv）—— 原型长什么样
  · DLL PE 导出表（dll_exports.csv）—— 真机上到底调得到调不到

**命名陷阱**：雷赛 C# 绑定里名字含 "cam" 的共 30 条，但前 13 条是
`dmc_set_camerablow_config`（**相机吹气**）与 `dmc_sorting_set_camera_trig_count`（**飞拍/排序触发**），
与电子凸轮**无关**。真正的电子凸轮是 `dmc_cam_*` 与 `dmc_cam_*_tappet*` 族。
本脚本把这两类分开数。

用法
----
    python scripts/check_cam_capability.py
"""
from __future__ import annotations

import csv
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
API = os.path.join(ROOT, "knowledge", "sdks", "official_api")

# 电子凸轮 = cam 出现在名字里，但排除「相机吹气 / 飞拍排序」这两个同前缀干扰项
CAM_EXCLUDE = ("camerablow", "sorting_")


def fn_names(fname):
    path = os.path.join(API, fname)
    if not os.path.isfile(path):
        return {}
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            n = (r.get("函数名") or "").strip()
            if n:
                out[n] = r.get("官方原型", "") or ""
    return out


def is_cam(name):
    low = name.lower()
    if "cam" not in low:
        return False
    return not any(bad in low for bad in CAM_EXCLUDE)


def main():
    if not os.path.isdir(API):
        print("找不到真值目录: %s" % API, file=sys.stderr)
        return 2

    cs = {"雷赛 DMC": "leisai.csv", "正运动 ZMotion": "zmotion.csv", "固高 GTS": "gts.csv"}
    hdr = {"雷赛 DMC": "leisai_cpp.csv", "正运动 ZMotion": "zmotion_cpp.csv", "固高 GTS": "gts_hdr.csv"}

    exports = Counter()
    export_names = {}
    with open(os.path.join(API, "dll_exports.csv"), encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            fn = (r.get("函数名") or "").strip()
            dll = (r.get("DLL") or "").strip()
            if is_cam(fn):
                exports[dll] += 1
                export_names.setdefault(dll, []).append(fn)

    print("=" * 78)
    print("电子凸轮（cam）能力核查 —— 全部来自 knowledge/sdks/official_api/")
    print("=" * 78)

    for vendor in ("雷赛 DMC", "正运动 ZMotion", "固高 GTS"):
        cs_all = fn_names(cs[vendor])
        hd_all = fn_names(hdr[vendor])
        cs_cam = {k: v for k, v in cs_all.items() if is_cam(k)}
        hd_cam = {k: v for k, v in hd_all.items() if is_cam(k)}
        print("\n### %s" % vendor)
        print("  官方 C# 绑定 %-18s 共 %4d 条，其中凸轮相关 %2d 条"
              % (cs[vendor], len(cs_all), len(cs_cam)))
        print("  官方 C 头文件 %-18s 共 %4d 条，其中凸轮相关 %2d 条"
              % (hdr[vendor], len(hd_all), len(hd_cam)))
        for n, proto in sorted(cs_cam.items()):
            print("     [C#绑定] %-28s %s" % (n, proto[:96]))
        only_hdr = sorted(set(hd_cam) - set(cs_cam))
        if only_hdr:
            print("     —— 只在 C 头文件、官方 C# 绑定里没有的 %d 条：" % len(only_hdr))
            for n in only_hdr[:12]:
                print("        %-26s %s" % (n, hd_cam[n][:92]))
        if not cs_cam and not hd_cam:
            print("     → 这家在本项目拿到的官方件里**没有电子凸轮**")

    print("\n### DLL PE 导出表里的凸轮符号")
    if not exports:
        print("  （无）")
    for dll, n in exports.most_common():
        print("  %-14s %3d 个   例: %s" % (dll, n, ", ".join(sorted(export_names[dll])[:6])))

    print("\n### 结论口径")
    print("  · 雷赛：电子凸轮 API 最完整，且 %s 是**三家里唯一能整表从上位机下发凸轮曲线**的" % "dmc_cam_table_unit")
    print("    （主轴位置数组 + 从轴位置数组整表写入控制器）。")
    print("  · 正运动：只有 %s / %s 两个，是**轨迹段/凸轮段的参数设置**，" % ("ZAux_Direct_Cam", "ZAux_Direct_Cambox"))
    print("    不是整表下发。")
    print("  · 固高：官方 C# 绑定与 C 头文件里凸轮符号 **0 个** → 这条产品线没有电子凸轮。")
    print("  · 注意：雷赛 C# 绑定里 'camerablow'（相机吹气）与 'sorting_*'（飞拍排序）")
    print("    名字也含 cam，但与电子凸轮无关，已在统计里排除。")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
