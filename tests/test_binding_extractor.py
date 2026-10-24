#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抽取器的**检测力**自测：厂商 EntryPoint 笔误必须留得住、看得见（评审 P1-1）。

背景
----
厂商原件 `正运动_ZMotion/SDK_头文件/Zmcaux.cs` L4518-4519：

    [DllImport("zauxdll.dll", EntryPoint = "ZAux_Direct_SetVectorBuffered2")]
    public static extern Int32 ZAux_Direct_GetVectorBuffered2(...)

方法名是 Get，EntryPoint 却写成 **Set**（厂商复制粘贴笔误 ✓）。
旧抽取器的去重键是 `(DLL, 函数名=EntryPoint, 变体)` →
Get 那条与 Set 那条**键相同** → Get 被丢弃 → 表里只剩一条 →
**笔误在表里完全隐形** ✓✓。

本文件用**合成源码**在 CI 上验这件事 ✓
（不依赖仓外厂商原件 ✓ —— 干净检出上原件不在位 ✓，
 靠真原件做断言 = 又一个 CI 盲区 ✓）。
"""
from __future__ import annotations

import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "extract_binding_returns.py")

# 厂商笔误的**缩影**：两条声明共用同一个 EntryPoint ✓
TYPO_SRC = """
[DllImport("zauxdll.dll", EntryPoint = "ZAux_Direct_SetVectorBuffered2",
    CharSet = CharSet.Ansi, CallingConvention = CallingConvention.StdCall)]
public static extern Int32 ZAux_Direct_SetVectorBuffered2(IntPtr handle, int iaxis, float pfValue);

[DllImport("zauxdll.dll", EntryPoint = "ZAux_Direct_SetVectorBuffered2",
    CharSet = CharSet.Ansi, CallingConvention = CallingConvention.StdCall)]
public static extern Int32 ZAux_Direct_GetVectorBuffered2(IntPtr handle, int iaxis, ref float pfValue);
"""


def _load():
    spec = importlib.util.spec_from_file_location("_ebe_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_两条共用同一EntryPoint的声明必须都留下():
    """旧去重键会把 Get 那条吞掉 → 表里只剩 1 条 → 笔误隐形 ✓。"""
    mod = _load()
    got = mod.extract_from(TYPO_SRC, "synthetic.cs", "zauxdll")
    assert len(got) == 2, "两条声明必须都在（旧实现只留 %d 条）" % len(got)
    names = {r["C#方法名"] for r in got}
    assert names == {"ZAux_Direct_SetVectorBuffered2", "ZAux_Direct_GetVectorBuffered2"}


def test_去重必须以C方法名为键():
    """直接验去重函数 ✓ —— 它就是这个 bug 的所在地 ✓。"""
    mod = _load()
    got = mod.extract_from(TYPO_SRC, "synthetic.cs", "zauxdll")
    out = mod.dedupe(got)
    assert len(out) == 2, "按 C# 方法名去重后应剩 2 条，实际 %d 条" % len(out)
    assert all(r["重复次数"] == 1 for r in out)


def test_EntryPoint原文必须单列且看得出不一致():
    """"函数名"仍 = 实际被调用的导出符号 ✓；不一致要能从两列比对出来 ✓。"""
    mod = _load()
    got = mod.extract_from(TYPO_SRC, "synthetic.cs", "zauxdll")
    for r in got:
        assert "EntryPoint" in r, "缺 EntryPoint 列 → 笔误看不见"
    get = next(r for r in got if r["C#方法名"].endswith("GetVectorBuffered2"))
    assert get["EntryPoint"] == "ZAux_Direct_SetVectorBuffered2"
    assert get["函数名"] == "ZAux_Direct_SetVectorBuffered2", \
        "「函数名」= 实际被调用的导出符号（语义不变 ✓）"
    assert get["EntryPoint"] != get["C#方法名"], "不一致必须看得出来"


def test_没有EntryPoint时以方法名为准():
    """没有 EntryPoint 属性的声明 ✓ → 函数名 = C# 方法名 ✓（不能空 ✓）。"""
    mod = _load()
    src = """
[DllImport("LTDMC.dll")]
public static extern Int32 dmc_get_position(UInt16 CardNo, UInt16 axis);
"""
    got = mod.extract_from(src, "synthetic.cs", "LTDMC")
    assert len(got) == 1
    assert got[0]["函数名"] == "dmc_get_position"
    assert got[0]["EntryPoint"] == ""
