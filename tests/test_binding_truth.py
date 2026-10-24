# -*- coding: utf-8 -*-
"""守卫「厂商官方 C# 绑定的返回类型 / 变体」这一层外部真值。

为什么单独一个文件
------------------
`knowledge/sdks/official_api/*.csv`（厂商 C# 绑定的原型表）**只给参数、不给返回类型**。
于是「一条 C# 声明的返回类型对不对」只能回头比 C 头文件，而 C 头文件是 C 语言：
Windows(LLP64) 下 C 的 `long` 是 32 位，C# 的 `long` 是 Int64 —— 两边直接比会口径错位。
厂商自己的 C# 绑定才是 C# 声明该对标的那一层
（雷赛 `LTDMC.cs:891` 把 C 的 `long` 映射成 `Int32`）。

`knowledge/sdks/official_api/binding_returns.csv` 由 `scripts/extract_binding_returns.py`
从厂商原始 C# 绑定源码抽出，本文件守住它不腐化：

  1. 表本身可用、字段齐全
  2. mcopilot 自己的 3 个厂商适配器（dmc / zmotion / gts）的每条 P/Invoke
     都能在厂商 C# 绑定里找到，且**返回类型宽度一致**
  3. LLP64 陷阱不会被踩：官方绑定返回 Int32 的函数，任何一处声明成 C# `long` 都要红
  4. 固高单卡/多卡变体的参数表差异是**真实存在**的，且两个变体都被记录
  5. 真值文件与厂商原文**不脱钩**：重跑抽取器必须得到同样的表
"""
from __future__ import annotations

import csv
import io
import os
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SDK_DIR = os.path.join(ROOT, "knowledge", "sdks")
API_DIR = os.path.join(SDK_DIR, "official_api")
BINDING_CSV = os.path.join(API_DIR, "binding_returns.csv")

# C# 返回类型 -> 位宽（C# 这一层没有 LLP64 歧义）
CS_WIDTH = {
    "short": 16, "ushort": 16, "Int16": 16, "UInt16": 16,
    "int": 32, "uint": 32, "Int32": 32, "UInt32": 32,
    "long": 64, "ulong": 64, "Int64": 64, "UInt64": 64,
    "float": 32, "double": 64, "bool": 1, "byte": 8, "sbyte": 8,
}


def _read_rows(path):
    with io.open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def binding_rows():
    if not os.path.isfile(BINDING_CSV):
        pytest.skip("binding_returns.csv 不存在（先跑 scripts/extract_binding_returns.py）")
    return _read_rows(BINDING_CSV)


@pytest.fixture(scope="module")
def binding_index(binding_rows):
    idx = {}
    for r in binding_rows:
        idx.setdefault((r["DLL"].lower(), r["函数名"]), []).append(r)
    return idx


def _sdk_pinvoke(name):
    import json
    path = os.path.join(SDK_DIR, name + ".json")
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------- 1. 表本身
def test_binding_table_shape(binding_rows):
    assert len(binding_rows) > 3000, "表条目太少，抽取器可能没跑到厂商源文件"
    for col in ("DLL", "函数名", "C#方法名", "返回类型", "参数表", "变体", "源文件"):
        assert col in binding_rows[0], f"缺列 {col}"
    assert {r["DLL"] for r in binding_rows} >= {"LTDMC.dll", "gts.dll", "zauxdll.dll"}


def test_binding_table_has_no_empty_return(binding_rows):
    bad = [r for r in binding_rows if not (r["返回类型"] or "").strip()]
    assert not bad, f"有条目缺返回类型：{bad[:3]}"


# --------------------------------------------- 2. mcopilot 自己的 P/Invoke
@pytest.mark.parametrize("sdk_name", ["dmc", "zmotion", "gts"])
def test_own_pinvoke_return_matches_vendor_binding(sdk_name, binding_index):
    sdk = _sdk_pinvoke(sdk_name)
    dll = sdk["dll"].lower()
    missing, mismatch = [], []
    for p in sdk.get("pinvoke", []):
        # 占位条目（skip_emit）本来就不生成 P/Invoke，不参与比对
        if p.get("skip_emit") or "..." in (p.get("fn") or ""):
            continue
        rows = binding_index.get((dll, p["fn"]))
        if not rows:
            missing.append(p["fn"])
            continue
        ret = (p.get("ret") or "").strip()
        want = CS_WIDTH.get(ret)
        got = {CS_WIDTH.get((r["返回类型"] or "").strip()) for r in rows}
        if want is None:
            continue
        if want not in got:
            mismatch.append((p["fn"], ret, sorted({r["返回类型"] for r in rows})))
    assert not missing, f"{sdk_name}: 这些函数在厂商 C# 绑定里查不到：{missing}"
    assert not mismatch, f"{sdk_name}: 返回类型与厂商 C# 绑定不一致：{mismatch}"


# ------------------------------------------------ 3. LLP64 陷阱不许踩
@pytest.mark.parametrize("sdk_name", ["dmc", "zmotion", "gts"])
def test_no_csharp_long_where_vendor_binding_says_int32(sdk_name, binding_index):
    """厂商把 C 的 long 映射成 Int32；C# 这边声明成 long 就会读 RAX 高 32 位垃圾。"""
    sdk = _sdk_pinvoke(sdk_name)
    dll = sdk["dll"].lower()
    offenders = []
    for p in sdk.get("pinvoke", []):
        if (p.get("ret") or "").strip().lower() != "long":
            continue
        rows = binding_index.get((dll, p["fn"]))
        if rows and any((r["返回类型"] or "").strip() in ("Int32", "int") for r in rows):
            offenders.append(p["fn"])
    assert not offenders, f"{sdk_name}: 这些声明用了 C# long，但厂商绑定是 Int32：{offenders}"


# ------------------------------- 4. 固高单卡/多卡变体差异必须被记录
def test_gts_variant_signature_divergence_is_recorded(binding_index):
    rows = binding_index[("gts.dll", "GT_Open")]
    params = {r["参数表"] for r in rows}
    assert len(params) > 1, "固高单卡/多卡的 GT_Open 参数表应该不同，说明变体没被分开记录"
    joined = " ".join(params)
    assert "cardNum" in joined, "多卡变体的 cardNum 首参没被记录"
    variants = {r["变体"] for r in rows}
    assert any("multi_card" in v for v in variants), "缺多卡变体"
    assert any("single_card" in v for v in variants), "缺单卡变体"


# --------------------------------- 5. 真值文件与厂商原文不得脱钩
def test_extractor_is_reproducible():
    """重跑抽取器必须得到与入库文件一致的表——防止真值悄悄腐化。"""
    script = os.path.join(ROOT, "scripts", "extract_binding_returns.py")
    if not os.path.isfile(script):
        pytest.skip("抽取器不存在")
    if not os.path.isfile(BINDING_CSV):
        pytest.skip("binding_returns.csv 不存在")
    # 厂商原件按本仓约定外置在仓外；干净克隆里不在位 → 跳过并写明当前不可自动复核
    vendor = os.path.join(os.path.dirname(ROOT), "mcopilot-external", "vendor_docs")
    if not os.path.isdir(vendor):
        pytest.skip("厂商原件按约定外置到 %s，本机未就位："
                    "在档指纹自洽，但**当前不可自动复核**" % vendor)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "again.csv")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        r = subprocess.run(
            [sys.executable, script, "--out", out],
            cwd=ROOT, capture_output=True, text=True, timeout=600,
            encoding="utf-8", errors="replace", env=env,
        )
        assert r.returncode == 0, f"抽取器退出码 {r.returncode}: {r.stderr[-800:]}"
        again = _read_rows(out)
        old = _read_rows(BINDING_CSV)
        assert len(again) == len(old), (
            f"重跑得到 {len(again)} 条，入库是 {len(old)} 条——真值与厂商原文脱钩了"
        )
        key = lambda rs: sorted((r["DLL"], r["函数名"], r["返回类型"], r["参数表"]) for r in rs)
        assert key(again) == key(old), "重跑内容与入库文件不一致"
