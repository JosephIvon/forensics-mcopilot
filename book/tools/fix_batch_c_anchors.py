#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_batch_c_anchors.py —— 批 C 第 3 项：mcopilot 锚点清单随原件外置同步改（2026-10-22）。

原件外置是本仓自己的约定（docs/CodeWiki_20261022.md §外部真值锚点 + 提取脚本默认值
`../mcopilot-external/vendor_docs`），本次只是把**仓内违规存放的部分**挪回约定位置，
并在清单里留下"外置路径 + 原在仓路径"两条线，指针不断。
"""
import io
import json
import os
import sys

P = r"%WORKSPACE%\mcopilot\knowledge\protocols\anchors.json"
EXT = "../mcopilot-external/vendor_docs/protocol_specs"
EXT_ABS = r"%WORKSPACE%\mcopilot-external\vendor_docs\protocol_specs"
MOVED = {
    "Modbus_Application_Protocol_V1_1b3.pdf": "knowledge/protocols/specs/Modbus_Application_Protocol_V1_1b3.pdf",
    "Modbus_Messaging_Implementation_Guide_V1_0b.pdf": "knowledge/protocols/specs/Modbus_Messaging_Implementation_Guide_V1_0b.pdf",
    "Modbus_over_serial_line_V1_02.pdf": "knowledge/protocols/specs/Modbus_over_serial_line_V1_02.pdf",
    "FOCAS_function_list.pdf": "knowledge/protocols/specs/FOCAS_function_list.pdf",
    "FOCAS2_Ethernet_Linux_en.pdf": "knowledge/protocols/specs/FOCAS2_Ethernet_Linux_en.pdf",
    "Snap7-refman.pdf": "knowledge/protocols/specs/Snap7-refman.pdf",
    "FX5_SLMP_JY997D54401.pdf": "knowledge/protocols/slmp_specs/FX5_SLMP_JY997D54401.pdf",
}

txt = io.open(P, encoding="utf-8").read()
doc = json.loads(txt)

changed = []
for a in doc["anchors"]:
    name = a["name"]
    if name in MOVED:
        a["repo_path"] = MOVED[name]
        a["path"] = f"{EXT}/{name}"
        a["storage"] = "external"          # 仓外原件（按本仓约定外置）
        changed.append(name)
    elif a.get("reextract_from"):
        base = a["reextract_from"].replace("\\", "/").split("/")[-1]
        if base in MOVED:
            a["reextract_from"] = f"{EXT}/{base}"
            changed.append(f"{name}(reextract_from)")

# 漏登的一条：三菱 FX5 SLMP 手册原件此前只有 slmp.json 记了指纹，**没进锚点清单**
# → 门禁根本没在核它。外置时一并补齐（指纹取自仓外原件实算，与 slmp.json 在档值一致）。
fx5 = "FX5_SLMP_JY997D54401.pdf"
if not any(a["name"] == fx5 for a in doc["anchors"]):
    p = os.path.join(EXT_ABS, fx5)
    size = os.path.getsize(p)
    import hashlib
    h = hashlib.sha256(open(p, "rb").read()).hexdigest()
    assert h == "6e273720b435e18e5ccf422929cfbc2d1aa1e1ef0317bbde2ff92b14589a65a5", h
    doc["anchors"].append({
        "name": fx5,
        "role": "spec_pdf",
        "spec": ("FX5 User's Manual (SLMP) 手册编号 JY997D54401（114 页，三菱官方手册原文，"
                 "经镜像分发取得；官方下载页为 JS 动态无法直链——来源性质见 slmp.json source_note）"),
        "repo_path": MOVED[fx5],
        "path": f"{EXT}/{fx5}",
        "storage": "external",
        "size": size,
        "sha256": h,
        "source_url": "http://www.atronika.com/Mitsubishi/PLC/MITSUBISHI_manual_plc_fx5_slmp.pdf",
    })
    changed.append(f"{fx5}(补登)")

# 顶层说明：把"非入库区"的判定写进清单本身，门禁与人都看同一份
doc["path_base"] = ("仓库根（相对路径）。以 `out/` 或 `../` 开头的条目属**非入库区**"
                    "（本地运行产物 / 仓外原件）：门禁在位即核指纹，缺位记 SKIP 并说明"
                    "「当前不可自动复核」——不静默当绿。")
doc["storage_policy"] = {
    "in_repo": "本仓跟踪文件，指纹随提交可复核",
    "external": "仓外原件，按 `../mcopilot-external/` 约定存放；仓内只留指针 + size + sha256",
    "not_committed": "本地运行产物（out/），不入库；缺失时门禁 SKIP",
    "moved_on": "2026-10-22 公开前审：厂商/标准 PDF 原件按本仓既有约定外置，仓内指针与指纹不变",
}
if len(changed) != 8:
    print(f"✗ 改动条目数不符：{len(changed)}（期望 8）")
    sys.exit(1)

io.open(P, "w", encoding="utf-8", newline="\n").write(
    json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
print(f"✓ anchors.json 已更新（{len(changed)} 处）：")
for c in changed:
    print(f"    {c}")
