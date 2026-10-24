#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从厂商官方 C# 绑定源码抽取「函数名 → C# 返回类型」真值表。

为什么需要它
------------
`knowledge/sdks/official_api/{gts,leisai,zmotion}.csv` 的「官方原型」列
**只有参数、没有返回类型**（例：`dmc_get_position(UInt16 CardNo, UInt16 axis)`）。
于是「一条 C# 声明的返回类型对不对」只能回头去比 C 头文件，而 C 头文件是 C 语言，
它的 `long` 在 Windows(LLP64) 是 32 位，与 C# 的 `long`(=Int64) 不是一个东西——
两边直接比会产生口径错位。

厂商自己的 C# 绑定才是 C# 声明该对标的那一层：
  雷赛 EMC系列开发头文件/C#/LTDMC.cs
      L891: public static extern Int32 dmc_get_position(UInt16 CardNo, UInt16 axis);
      L859: public static extern Int32 dmc_get_encoder(UInt16 CardNo, UInt16 axis);
  厂商把 C 的 `long` 映射成 C# `Int32`，这才是权威口径。

本脚本把这一层抽成 CSV，供 scripts/verify_trae_pinvoke.py 做返回类型比对。

用法
----
    python scripts/extract_binding_returns.py
    python scripts/extract_binding_returns.py --vendor <vendor_docs 目录> --out <csv>
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys

# 厂商 C# 绑定源文件：(相对 vendor_docs 的路径, 期望编码, 说明, 变体标识)
#
# 固高有 4 个 C# 封装变体，**同名 DLL(gts.dll)、同名导出符号，但签名不同**：
# 多卡库多一个 cardNum 首参。手册 PDF p15（SDK 按 VC/C# × 32/64 位 × single/multi_card 分目录）
# 明确记载这一点，所以这里把 4 个变体全抽进来，用「变体」列区分，
# 避免"某一变体的签名"被当成唯一真相。
SOURCES = [
    (r"正运动_ZMotion\SDK_头文件\Zmcaux.cs", "utf-8", "正运动官方 C# 绑定", "zauxdll"),
    (r"gts_sdk\固高GTS资料\02_CSharp封装\64bit_single_card\gts.cs", "utf-8", "固高 C# 绑定 64位单卡", "64bit_single_card"),
    (r"gts_sdk\固高GTS资料\02_CSharp封装\64bit_multi_card\gts.cs", "utf-8", "固高 C# 绑定 64位多卡", "64bit_multi_card"),
    (r"gts_sdk\固高GTS资料\02_CSharp封装\32bit_single_card\gts.cs", "utf-8", "固高 C# 绑定 32位单卡", "32bit_single_card"),
    (r"gts_sdk\固高GTS资料\02_CSharp封装\32bit_multi_card\gts.cs", "utf-8", "固高 C# 绑定 32位多卡", "32bit_multi_card"),
    (r"EMC系列开发头文件\C#\LTDMC.cs", "gbk", "雷赛官方 C# 绑定(EMC系列开发头文件)", "LTDMC"),
]

# [DllImport("LTDMC.dll", EntryPoint = "dmc_x", ...)]
DLLIMPORT_RE = re.compile(
    r'\[DllImport\(\s*"(?P<dll>[^"]+)"(?P<attrs>[^\]]*)\)\]'
)
EXTERN_RE = re.compile(
    r'\b(?:public|internal|private)?\s*(?:static\s+)?extern\s+'
    r'(?P<ret>[A-Za-z_][A-Za-z0-9_<>\[\]\.]*)\s+'
    r'(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*'
    r'\((?P<args>[^;]*?)\)\s*;'
)
ENTRYPOINT_RE = re.compile(r'EntryPoint\s*=\s*"(?P<ep>[^"]+)"')


def decode(path: str) -> str:
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_from(text: str, source_rel: str, variant: str) -> list[dict]:
    """扫出所有 [DllImport] + extern 配对。"""
    out = []
    for m in DLLIMPORT_RE.finditer(text):
        dll = m.group("dll").strip()
        attrs = m.group("attrs") or ""
        ep = ENTRYPOINT_RE.search(attrs)
        # 紧跟其后（允许中间有换行/注释）的那条 extern
        tail = text[m.end(): m.end() + 600]
        em = EXTERN_RE.search(tail)
        if not em:
            continue
        cs_name = em.group("name")
        symbol = ep.group("ep") if ep else cs_name
        out.append({
            "DLL": dll,
            "函数名": symbol,
            "C#方法名": cs_name,
            "返回类型": em.group("ret").strip(),
            "参数表": " ".join(em.group("args").split()),
            "源文件": source_rel,
            "变体": variant,
        })
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="抽取厂商官方 C# 绑定的返回类型真值表")
    ap.add_argument("--vendor", default=None, help="vendor_docs 目录（默认按相对位置推断）")
    ap.add_argument("--out", default=None, help="输出 CSV（默认写进 knowledge/sdks/official_api/）")
    args = ap.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)                      # mcopilot/
    vendor = args.vendor or os.path.join(os.path.dirname(root), "mcopilot-external", "vendor_docs")
    out_csv = args.out or os.path.join(root, "knowledge", "sdks", "official_api", "binding_returns.csv")

    if not os.path.isdir(vendor):
        print(f"找不到 vendor_docs：{vendor}", file=sys.stderr)
        return 2

    rows = []
    seen = {}
    for rel, enc, note, variant in SOURCES:
        path = os.path.join(vendor, rel)
        if not os.path.isfile(path):
            print(f"  [跳过] 源文件不存在：{rel}", file=sys.stderr)
            continue
        text = decode(path)
        got = extract_from(text, rel.replace("\\", "/"), variant)
        print(f"  {note:28s} {len(got):4d} 条  ({rel})")
        for r in got:
            key = (r["DLL"].lower(), r["函数名"], r["变体"])
            if key in seen:
                seen[key]["重复次数"] += 1
                continue
            r["重复次数"] = 1
            seen[key] = r
            rows.append(r)

    rows.sort(key=lambda r: (r["DLL"].lower(), r["函数名"], r["变体"]))
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with io.open(out_csv, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["DLL", "函数名", "C#方法名", "返回类型", "参数表", "变体", "源文件", "重复次数"],
        )
        w.writeheader()
        for r in rows:
            w.writerow(r)

    dlls = sorted({r["DLL"] for r in rows})
    variants = sorted({r["变体"] for r in rows})
    print(f"\n写出 {out_csv}")
    print(f"  函数条目 {len(rows)} 条，覆盖 DLL {dlls}")
    print(f"  变体 {variants}")
    from collections import Counter
    ret = Counter(r["返回类型"] for r in rows)
    print(f"  返回类型分布：{dict(ret.most_common())}")

    # 变体间签名是否一致（同名同导出符号但参数不同 = 部署陷阱，必须报出来）
    byfn = {}
    for r in rows:
        byfn.setdefault((r["DLL"].lower(), r["函数名"]), set()).add(r["参数表"])
    conflict = {k: v for k, v in byfn.items() if len(v) > 1}
    if conflict:
        print(f"\n  ⚠ 变体间参数表不一致的函数 {len(conflict)} 个（同名 DLL + 同名导出符号，"
              f"混用会导致参数错位）：")
        for (dll, fn), vs in list(conflict.items())[:5]:
            print(f"     {dll}!{fn}:")
            for v in sorted(vs):
                print(f"        - {v}")
    else:
        print("\n  ✓ 各变体参数表一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
