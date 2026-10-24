#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取证检测器的**行为**夹具（2026-10-25 独立第三方评审后补）。

背景
----
评审 P2-3：`reached_latency` 是 10 个取证检测器里**唯一零覆盖**的那个 ✓
（`tests/` 里 `reached_latency` / `concurrent_command_ms` 各 **0 次**引用 ✓）。
阈值 `reached_latency_ms: 1500` 从未被任何测试触碰 ✓ ——
单位写错、配对错轴、比较方向写反（`>` 写成 `<`）都会一直坏着而无人发现 ✓。

为什么这条检测器值得单独钉 ✓
--------------------------
它产出的是「**节拍被拉长**」这类取证核心结论 ✓，
而且它的输入是**两条**日志行（MOVE_CMD → REACHED）的配对 ✓ ——
配对逻辑错（比如拿 REACHED 行自己的时间戳两两相减 ✓）不会崩 ✓，
只会**静默不报**或**静默错报** ✓✓。

口径
----
* 1600 ms > 1500 ms 阈值 → **必须报** ✓，且证据行号指向 **REACHED** 那一行 ✓
  （人拿到证据要能直接回查「这次到位用了多久」✓ —— 指向 MOVE_CMD 行就回查不到 ✓）。
* 1400 ms < 1500 ms → **必须不报** ✓（这是防止「见谁都报」的阳性对照 ✓）。
* 两条夹具**只差 200 ms** ✓ → 阈值方向写反、单位错（秒/毫秒）都会当场红 ✓✓。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from mcopilot.agents import forensics as F  # noqa: E402


def _line(no: int, ts: datetime, etype: str, fields: dict, raw: str) -> F.Line:
    return F.Line(no=no, ts=ts, level="INFO", src="motion", msg=raw, raw=raw,
                  events=[{"type": etype, "fields": fields}])


def _pair(gap_ms: int) -> list[F.Line]:
    """一条 MOVE_CMD 与 1600/1400 ms 之后的 REACHED（同轴、位置到齐 ✓）。"""
    t0 = datetime(2026, 10, 25, 10, 0, 0)
    return [
        _line(7, t0, "MOVE_CMD", {"axis": 3, "target": 100.0},
              "MOVE axis=3 target=100.000"),
        _line(8, t0 + timedelta(milliseconds=gap_ms), "REACHED",
              {"axis": 3, "pos": 100.0}, "REACHED axis=3 pos=100.000"),
    ]


@pytest.fixture(scope="module")
def rules():
    return F._load_rules()


def _find(findings, fid):
    for f in findings:
        if f.fid == fid:
            return f
    return None


def test_时延1600ms超过阈值必须报出():
    """1600 ms > 阈值 1500 ms → 必须报 `reached_latency` ✓，证据指向 REACHED 行 ✓。"""
    rules = F._load_rules()
    assert rules["thresholds"]["reached_latency_ms"] == 1500, \
        "夹具的前提是阈值 1500 ms；阈值改了请同步这条断言"
    findings = F.detect(_pair(1600), rules)
    f = _find(findings, "reached_latency")
    assert f is not None, "1600 ms > 1500 ms 却没报 reached_latency（检测器失效）"
    assert f.count == 1
    # 证据行号必须指向 **REACHED** 那一行（第 8 行），否则回查不到这次到位
    assert [ev[0] for ev in f.evidence] == [8], \
        "证据应指向 REACHED 行（L8），实际 %s" % [ev[0] for ev in f.evidence]
    assert "1600" in f.detail, "明细里应写出实际时延（便于现场复核），实际：%s" % f.detail


def test_时延1400ms未超阈值必须不报():
    """1400 ms < 1500 ms → 必须**不**报 ✓（阳性对照，防「见谁都报」✓）。"""
    rules = F._load_rules()
    findings = F.detect(_pair(1400), rules)
    assert _find(findings, "reached_latency") is None, \
        "1400 ms 没超 1500 ms 却报了 reached_latency（误报）"


def test_位置到齐时不得连带报出位置偏差():
    """两条夹具都位置到齐 ✓ → 不该连带刷出 `position_deviation` ✓。"""
    rules = F._load_rules()
    for gap in (1400, 1600):
        findings = F.detect(_pair(gap), rules)
        assert _find(findings, "position_deviation") is None, \
            "位置已到齐（target=pos=100.0）却报了位置偏差"


def test_单条MOVE_CMD没有REACHED时不得报时延():
    """没有到位事件 = **无结论** ✓，不是「时延为 0」也不是「时延超限」✓。"""
    rules = F._load_rules()
    t0 = datetime(2026, 10, 25, 10, 0, 0)
    only_cmd = [_line(7, t0, "MOVE_CMD", {"axis": 3, "target": 100.0},
                      "MOVE axis=3 target=100.000")]
    findings = F.detect(only_cmd, rules)
    assert _find(findings, "reached_latency") is None, \
        "只有指令没有到位，不能判时延超限（那是无结论，不是超限）"


# ------------------------------------------------ 阈值必须真的被读（P2-2 的回归）
def test_阈值表里没有死阈值也没有硬编码兜底():
    """`threshold_lab._static_consistency` 的两条结论必须保持干净 ✓。

    评审 P2-2：`concurrent_command_ms` 配了却没人读（死阈值 ✓），
    `cycle_slow_ratio` 干脆没进配置、代码里硬编码 0.02 兜底 ✓。
    两处都已改成读配置 ✓ —— 这条断言防它们**悄悄退回去** ✓✓。
    """
    from mcopilot.agents import threshold_lab
    cons = threshold_lab._static_consistency(F._load_rules())
    assert cons["dead"] == [], "有配了却没人读的阈值：%s" % cons["dead"]
    assert cons["hardcoded"] == {}, "有硬编码兜底的阈值：%s" % cons["hardcoded"]
