#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inventory_third_party.py —— 三仓"第三方材料的再分发性"逐件清单（2026-10-22，批 C 用）。

只报**机械可查的事实**：文件多大、是不是第三方的（来自公开数据集/厂商件/社区附件）、
仓里有没有许可文本、有没有署名出处。**法律判断留给作者**——本脚本不替人下结论。
"""
import io
import os
import re
import subprocess

REPOS = {
    "mcopilot": r"%WORKSPACE%\mcopilot",
    "axiscope": r"%WORKSPACE%\axiscope",
    "trae_factory": r"%WORKSPACE%\trae_factory",
}
# 第三方来源的特征目录/文件
THIRD_PARTY = [
    (re.compile(r"knowledge/protocols/specs/.*\.pdf$"), "厂商手册 PDF（Modbus/Snap7/三菱 FX5）"),
    (re.compile(r"knowledge/protocols/slmp_specs/.*\.pdf$"), "厂商手册 PDF（三菱 FX5 SLMP）"),
    (re.compile(r"knowledge/sdks/official_api/.*"), "厂商官方件导出（C# 绑定/头文件/PE 导出表/手册抄录/端子表/PDO 表）"),
    (re.compile(r"knowledge/protocols/pcap_samples/.*"), "Lemay CSET'16 真机 pcap 语料"),
    (re.compile(r"knowledge/protocols/real_corpora/.*"), "真实 GitHub issue 通信故障语料"),
    (re.compile(r"samples/servo/klipper.*"), "Klipper 社区真机数据（GPLv3）"),
    (re.compile(r"samples/servo/darus.*"), "DaRUS 数据集（CC BY 4.0）"),
    (re.compile(r"samples/servo/twincat_export10.*"), "Beckhoff CODESYS 导出记录"),
    (re.compile(r"bench/samples/.*"), "bench 样本波形"),
]
LICENSE_NAMES = {"LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING", "NOTICE", "NOTICE.md",
                 "LICENSE.code", "LICENSES"}


def git(repo, *a):
    return subprocess.run(["git", "-C", repo] + list(a), capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


for name, repo in REPOS.items():
    files = [f for f in git(repo, "ls-files").splitlines() if f]
    print("=" * 98)
    print(f"【{name}】{repo}")
    print("=" * 98)
    # 许可文件
    lic = [f for f in files if os.path.basename(f) in LICENSE_NAMES or f.upper().startswith("LICENSE")]
    print(f"  仓内许可文件：{lic if lic else '**无**'}")
    # 第三方件
    total = 0
    rows = []
    for f in files:
        tag = None
        for pat, label in THIRD_PARTY:
            if pat.search(f):
                tag = label
                break
        if not tag:
            continue
        p = os.path.join(repo, f.replace("/", os.sep))
        size = os.path.getsize(p) if os.path.isfile(p) else 0
        total += size
        rows.append((f, tag, size))
    for f, tag, size in sorted(rows, key=lambda r: -r[2]):
        print(f"  {size/1024/1024:8.2f} MB  [{tag}]  {f}")
    print(f"  第三方件合计 {len(rows)} 件 / {total/1024/1024:.2f} MB")
    # 仓内是否有许可/署名出处
    print("  —— 署名与许可出处（仓内自述）——")
    for f in files:
        if not f.lower().endswith((".md", ".json")):
            continue
        if os.path.splitext(f)[1].lower() in (".pdf",):
            continue
        p = os.path.join(repo, f.replace("/", os.sep))
        if not os.path.isfile(p):
            continue
        try:
            txt = io.open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if re.search(r"CC BY|GPLv3|MIT|BSD|Apache|LICENSE|许可|署名|attribution|许可与署名",
                     txt, re.I):
            hits = len(re.findall(r"CC BY|GPLv3|许可|署名|attribution", txt, re.I))
            print(f"    {f}（命中 {hits} 处许可/署名提法）")
    print()
