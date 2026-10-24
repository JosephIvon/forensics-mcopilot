#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SPC 控制图参数必须是**算出来的**，不是「看起来合理」（评审 P2-5）。

背景
----
评审逐行比对 `spc.py` 与全部 SPC 断言，确认**无任何一处出现绝对值** ✓：

    assert im["lcl"] < im["cl"] < im["ucl"]
    assert im["mr_ucl"] > im["mr_bar"]

只验序关系 ✗ → 把 `MR̄/1.128` 写成 `1.13`、`D4=3.267` 写成 `3.2`、
`CL±3σ` 改成 `±2.5σ`，**全部测试照样绿** ✓，
而每一张控制图、每一个 Cp/Cpk 全错 ✓✓。

本文件用**解析可算**的序列钉死这些常数 ✓
--------------------------------------
序列 `[1..10]`：
    移动极差 mr   = [1]*9            （相邻差恒为 1）
    MR̄            = 1                 （精确）
    σ             = 1 / 1.128        （I-MR 的经典估计式）
    CL            = 5.5              （1..10 的均值，精确）
    UCL / LCL     = CL ± 3σ
    MR 上控制限   = D4 · MR̄ = 3.267 · 1
这些数**不需要跑厂商软件就能手算** ✓ → 任何一个常数被改动都会当场红 ✓✓。

另钉「σ 双轨」与「判异规则点数」两处评审点 ✓。
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from mcopilot.agents import spc  # noqa: E402

SERIES = [float(i) for i in range(1, 11)]   # 1..10


@pytest.fixture(scope="module")
def im():
    chart = spc.i_mr(SERIES)
    assert chart["ok"] is True
    return chart


# --------------------------------------------------- 1. 常数必须是算出来的
def test_i_mr_中心线与sigma的绝对值(im):
    """`[1..10]` 的 I 图：CL=5.5，σ=1/1.128 —— 必须是这两个数 ✓。"""
    assert im["cl"] == pytest.approx(5.5), "CL 应为 5.5（1..10 的均值）"
    assert im["mr_bar"] == pytest.approx(1.0), "MR̄ 应为 1.0（相邻差恒为 1）"
    assert im["sigma"] == pytest.approx(1.0 / 1.128), \
        "σ 应为 MR̄/1.128；写成 1.13 或别的分母立刻红"


def test_i_mr_控制限等于CL加减三倍sigma(im):
    """UCL/LCL = CL ± **3**σ —— 系数 3 被改成 2.5 会当场红 ✓。"""
    assert im["ucl"] == pytest.approx(im["cl"] + 3.0 * im["sigma"])
    assert im["lcl"] == pytest.approx(im["cl"] - 3.0 * im["sigma"])
    # 具体数值（便于人眼核对，不依赖上一条的自洽）
    assert im["ucl"] == pytest.approx(5.5 + 3.0 / 1.128)
    assert im["lcl"] == pytest.approx(5.5 - 3.0 / 1.128)


def test_i_mr_移动极差上控制限用D4系数(im):
    """MR 图上控制限 = **D4**·MR̄ = 3.267·MR̄ —— 3.267 写成 3.2 会当场红 ✓。"""
    assert im["mr_ucl"] == pytest.approx(3.267 * im["mr_bar"])
    assert im["mr_ucl"] == pytest.approx(3.267)


def test_i_mr_移动极差序列本身(im):
    """`[1..10]` 的移动极差就是 `[1]*9` ✓ —— 差分的边界（不跨首尾）也要对 ✓。"""
    assert im["mr"] == pytest.approx([1.0] * 9), "移动极差应为 9 个 1.0"


def test_i_mr_能力指数用同一套sigma(im):
    """Cp/Cpk 必须与 I 图用**同一个** σ ✓（两套口径会让「图看着好、能力指数难看」）。"""
    cp = im["cp"]
    assert cp["cp"] == pytest.approx((im["ucl"] - im["lcl"]) / (6.0 * im["sigma"]))


# --------------------------------------------------- 2. σ 的兜底分支
def test_mr_bar为零时sigma走样本标准差且不得崩():
    """MR̄ = 0（序列全等）时 σ 走 `stdev(values)` 兜底 ✓ —— 该分支此前零测试 ✓。

    这条同时钉住兜底分支的口径 ✓：**样本标准差（n-1）**，不是 MR̄/1.128 ✓。
    序列恒定时两者都是 0 ✓ → 这里至少保证「不崩、且 σ=0、控制限退化为一条线」✓。
    """
    chart = spc.i_mr([5.0, 5.0, 5.0, 5.0])
    assert chart["ok"] is True
    assert chart["mr_bar"] == pytest.approx(0.0)
    assert chart["sigma"] == pytest.approx(0.0)
    assert chart["ucl"] == pytest.approx(5.0)
    assert chart["lcl"] == pytest.approx(5.0)
    assert chart["ooc_count"] == 0


# --------------------------------------------------- 3. 判异规则的点数（9 / 6）
def test_连续9点同侧才报_8点不报():
    """实现是 **9 点同侧** ✓（注释曾写 7 点 ✓）。8 点不得报、9 点必须报 ✓✓。"""
    # 9 个低位点 + 1 个高位点把 CL 抬到它们之上 → 前 9 点全在中心线同侧
    nine = [1.0] * 9 + [100.0]
    rules = [r["rule"] for r in spc.i_mr(nine)["runs"]]
    assert any("9 点" in r for r in rules), "9 点同侧却没报：%s" % rules

    eight = [1.0] * 8 + [100.0, 100.0]
    rules8 = [r["rule"] for r in spc.i_mr(eight)["runs"]]
    assert not any("9 点" in r for r in rules8), "8 点同侧却报了 9 点判异：%s" % rules8


def test_连续6点递增才报_5点不报():
    """实现是 **6 点递增/递减** ✓（注释曾写 7 点 ✓）。"""
    six = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 6.0, 6.0, 6.0, 6.0]
    rules = [r["rule"] for r in spc.i_mr(six)["runs"]]
    assert any("6 点递增" in r for r in rules), "6 点递增却没报：%s" % rules

    five = [1.0, 2.0, 3.0, 4.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0]
    rules5 = [r["rule"] for r in spc.i_mr(five)["runs"]]
    assert not any("6 点递增" in r for r in rules5), "只有 5 点递增却报了 6 点：%s" % rules5


def test_样本不足三条时明确返回不ok():
    """<3 条 = **无结论** ✓（不返回一张全是 None 的图 ✓）。"""
    assert spc.i_mr([1.0, 2.0])["ok"] is False
