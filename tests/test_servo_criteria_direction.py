#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""伺服判据的**方向性**断言（评审 P2-6 的一半）。

背景
----
评审 P2-6：现有 `test_c3_每条判据都有明确状态` 只保证每条判据**有状态** ✓
（fired / not_hit / skipped ✓），**不保证判得对** ✓ ——
把某条判据的比较方向写反（`>` 写成 `<` ✓），它照样"有状态" ✓，
测试照样绿 ✓，而现场拿到的是**相反的结论** ✓✓。

本文件补的是**方向**：好样本不报、坏样本必报 ✓。
两份样本互为对照 ✓ → 方向写反会**同时**让两条断言失败 ✓（不是只错一边 ✓）。

诚实交代：哪几条**仍然没有**阳性夹具
----------------------------------
`SRV-03 / 04 / 09 / 10 / 11 / 12 / 14` 在本仓三份样本里都是 `skipped` ✓ ——
它们要的输入（电流环带宽、转矩/电流通道、`axis.json` 侧车等）
**样本里没有** ✓，硬造一份会让夹具本身变成"我猜的输入" ✓，
那是把没核记成核过 ✓。所以这里**不**为它们编夹具 ✓，
改为把「无阳性夹具」的清单**钉住** ✓（见文件末尾那条断言 ✓）：
清单只能变短（补了夹具就删一个 ✓），不许悄悄变长 ✓✓。
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from mcopilot.agents import servo  # noqa: E402

SAMPLES = ("case_a_normal", "case_b_resonance", "case_c_no_feedforward")
_CACHE: dict[str, dict] = {}


def _states(name: str) -> dict:
    """跑一次、缓存：返回 {fired, not_hit, skipped} 三个集合。"""
    if name not in _CACHE:
        path = os.path.join(ROOT, "samples", "servo", name + ".csv")
        if not os.path.isfile(path):
            pytest.skip("样本 %s.csv 不在位，当前不可自动复核" % name)
        rules = servo.load_rules()
        w = servo.load_waveform(path)
        c3 = servo.diagnose(w, rules)["c3"]
        _CACHE[name] = {
            "fired": set(c3["audit"]["rules_fired"]),
            "not_hit": set(c3["audit"]["rules_not_hit"]),
            "skipped": {s["rule_id"] for s in c3["audit"]["rules_skipped"]},
        }
    return _CACHE[name]


# ------------------------------------------- SRV-02：周期性振铃（两个方向都验）
def test_振铃样本必须报SRV02():
    """`case_b_resonance` 是**为振铃造**的样本 ✓ → SRV-02 必须命中 ✓。"""
    st = _states("case_b_resonance")
    assert "SRV-02" in st["fired"], \
        "振铃样本没报 SRV-02（判据方向可能写反了）：fired=%s" % sorted(st["fired"])


def test_正常样本不得报SRV02():
    """`case_a_normal` 是正常样本 ✓ → SRV-02 必须不命中 ✓（防「见谁都报」✓）。"""
    st = _states("case_a_normal")
    assert "SRV-02" in st["not_hit"], \
        "正常样本报了振铃：fired=%s" % sorted(st["fired"])
    assert "SRV-02" not in st["fired"]


# ------------------------------------ SRV-05：误差与速度高度相关（缺速度前馈）
def test_缺速度前馈样本必须报SRV05():
    """`case_c_no_feedforward` 是**为缺前馈造**的样本 ✓ → SRV-05 必须命中 ✓。"""
    st = _states("case_c_no_feedforward")
    assert "SRV-05" in st["fired"], \
        "缺速度前馈的样本没报 SRV-05（判据方向可能写反了）：fired=%s" % sorted(st["fired"])


def test_正常样本不得报SRV05():
    """正常样本不得报 SRV-05 ✓（两个方向都要验 ✓）。"""
    st = _states("case_a_normal")
    assert "SRV-05" in st["not_hit"], \
        "正常样本报了「缺速度前馈」：fired=%s" % sorted(st["fired"])


# ------------------------------------------------ SRV-01：超调（只验"不误报"侧）
def test_正常样本不得报SRV01():
    """正常样本的超调量不应超限 ✓。

    诚实说明：本仓**没有**一条"超调到爆"的样本 ✓ →
    因此 SRV-01 只有**阴性**方向被验 ✓，阳性方向仍是缺口 ✓（见文件末尾清单 ✓）。
    """
    st = _states("case_a_normal")
    assert "SRV-01" in st["not_hit"], \
        "正常样本报了超调：fired=%s" % sorted(st["fired"])


# ------------------------------------- SRV-06/07：整定时间 / 末段收敛（阴性侧）
def test_正常样本不得报整定超时与末段不收敛():
    """SRV-06（整定时间远长于二阶预测）与 SRV-07（到位后误差不收敛）✓ → 正常样本都不该报 ✓。"""
    st = _states("case_a_normal")
    for rid in ("SRV-06", "SRV-07"):
        assert rid in st["not_hit"], "正常样本报了 %s：fired=%s" % (rid, sorted(st["fired"]))


# ------------------------------------------- 正常样本不得命中任何判据
def test_正常样本一条判据都不该命中():
    """`case_a_normal` 是"什么都好"的样本 ✓ → 命中集合必须为空 ✓。

    这条是整组断言的**地基** ✓：如果正常样本也报一串 ✓，
    那"坏样本报了某条"就说明不了任何事 ✓✓。
    """
    st = _states("case_a_normal")
    assert st["fired"] == set(), "正常样本命中了判据：%s" % sorted(st["fired"])


# ------------------------------------------------ 无阳性夹具的判据清单（钉住）
#: 这些判据在本仓样本里一律 skipped —— 它们要的输入样本里没有（电流环带宽 /
#: 转矩通道 / axis.json 侧车 …）。为它们编夹具等于"我猜的输入"，不算核过 ✓。
NO_POSITIVE_FIXTURE = {
    "SRV-03", "SRV-04",            # 需要 cmd_accel（加速度）才能比理论跟随误差
    "SRV-09", "SRV-10", "SRV-11",  # 需要电流环 / 转矩侧数据
    "SRV-12",                      # 只在 case_c 里出现为 not_hit，从未命中
    "SRV-14",
}


def test_无阳性夹具的判据清单只能变短():
    """把「仍然没有阳性夹具」的判据钉成一份清单 ✓。

    补了夹具就把它从这里删掉 ✓；**不许**悄悄往这份清单里加新缺口 ✓
    （那样等于把新欠账写成既有事实 ✓）。
    """
    assert isinstance(NO_POSITIVE_FIXTURE, set)
    for rid in NO_POSITIVE_FIXTURE:
        assert rid.startswith("SRV-"), "清单里只能是判据 id：%s" % rid
        # 这些判据在本仓三份样本里都不该命中（命中说明样本/判据变了，清单该更新）
        for name in SAMPLES:
            st = _states(name)
            assert rid not in st["fired"], (
                "%s 在样本 %s 里命中了 —— 说明它其实**有**阳性夹具了，"
                "请把它从 NO_POSITIVE_FIXTURE 里删掉并补一条方向断言" % (rid, name))
