#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_batch_d_cleanclone.py —— 批 D：让**干净克隆**真的能跑（2026-10-23）。

背景：公开仓的验收标准不是"本机工作树绿"，而是**读者克隆下来能跑** ✓。
本轮实测（本地路径克隆 = GitHub 将提供的同一份内容 ✓）：
  mcopilot 干净克隆：14 failed + 2 errors → 修 .gitignore 后剩 3 failed ✓
  axiscope 干净克隆：19 failed + 68 errors（全部因 data/raw、data/incoming 不入库 ✓）

mcopilot 的 3 条残留：都是**厂商原件外置**导致 ✓——
原件按本仓约定放在 `../mcopilot-external/` ✓，干净克隆里当然没有 ✓。
处置与门禁同一口径 ✓：**不在位就 SKIP，并写明"当前不可自动复核"** ✓，
不许红着装作"已核过" ✓，也不许无条件 skip ✓（在位时照跑照红 ✓）。
"""
import io
import os
import sys

MC = r"%WORKSPACE%\mcopilot"

FIXES = [
    # ── mcopilot/tests/test_binding_truth.py：抽取器要厂商原件 ──────────
    ("tests/test_binding_truth.py",
     '''    script = os.path.join(ROOT, "scripts", "extract_binding_returns.py")
    if not os.path.isfile(script):
        pytest.skip("抽取器不存在")
    if not os.path.isfile(BINDING_CSV):
        pytest.skip("binding_returns.csv 不存在")''',
     '''    script = os.path.join(ROOT, "scripts", "extract_binding_returns.py")
    if not os.path.isfile(script):
        pytest.skip("抽取器不存在")
    if not os.path.isfile(BINDING_CSV):
        pytest.skip("binding_returns.csv 不存在")
    # 厂商原件按本仓约定外置在仓外；干净克隆里不在位 → 跳过并写明当前不可自动复核
    vendor = os.path.join(os.path.dirname(ROOT), "mcopilot-external", "vendor_docs")
    if not os.path.isdir(vendor):
        pytest.skip("厂商原件按约定外置到 %s，本机未就位："
                    "在档指纹自洽，但**当前不可自动复核**" % vendor)''', 1),

    # ── mcopilot/tests/test_protocol_modbus.py：quote 反查要 Modbus 原件 ──
    ("tests/test_protocol_modbus.py",
     '''def test_quote反查_全量同源复核():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_modbus_quotes.py")],''',
     '''def test_quote反查_全量同源复核():
    ext = ROOT.parent / "mcopilot-external" / "vendor_docs" / "protocol_specs"
    if not ext.is_dir():
        pytest.skip("协议标准原件按约定外置到 %s，本机未就位："
                    "在档指纹自洽，但**当前不可自动复核**" % ext)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_modbus_quotes.py")],''', 1),

    # ── mcopilot/tests/test_protocol_slmp.py：quote 反查要 FX5 原件 ─────
    ("tests/test_protocol_slmp.py",
     '''def test_quote反查_同源复核():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "extract_slmp.py"), "--check"],''',
     '''def test_quote反查_同源复核():
    ext = ROOT.parent / "mcopilot-external" / "vendor_docs" / "protocol_specs"
    if not ext.is_dir():
        pytest.skip("协议标准原件按约定外置到 %s，本机未就位："
                    "在档指纹自洽，但**当前不可自动复核**" % ext)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "extract_slmp.py"), "--check"],''', 1),
]


def main():
    cache = {}
    applied, failed = 0, []
    for rel, old, new, cnt in FIXES:
        path = os.path.join(MC, rel.replace("/", os.sep))
        if path not in cache:
            cache[path] = io.open(path, encoding="utf-8", newline="").read()
        txt = cache[path]
        eol = "\r\n" if "\r\n" in txt else "\n"
        old_e, new_e = old.replace("\n", eol), new.replace("\n", eol)
        got = txt.count(old_e)
        if got != cnt:
            failed.append((rel, old[:70], got, cnt))
            continue
        cache[path] = txt.replace(old_e, new_e)
        applied += 1
    if failed:
        print("✗ 有替换未达期望命中数，未写盘：")
        for rel, old, got, cnt in failed:
            print(f"    {rel}  期望 {cnt} 实得 {got}  ← {old}")
        sys.exit(1)
    for path, txt in cache.items():
        io.open(path, "w", encoding="utf-8", newline="").write(txt)
        print(f"  ✓ {path[len(MC)+1:]}")
    print(f"\n共 {applied} 处落盘（{len(cache)} 个文件）")


if __name__ == "__main__":
    main()
