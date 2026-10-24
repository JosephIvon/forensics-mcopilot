#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TwinCAT Scope 导出解析器：**失败分支**必须有夹具（评审 P2-6）。

背景
----
评审 P2-6：`src/mcopilot/core/twincat.py`（630 行）的
`parse_twincat` / `map_channels` / `write_canonical_csv` 只被
`scripts/convert_twincat.py` 引用 ✓，而该脚本**不被任何测试引用** ✓
→ 整个模块**一条行为断言都没有** ✓✓。

而这个模块恰恰处处是「**宁可显式失败**」✓：
跳过行占比 1% 阈值、时基严格单调校验、语义冲突拒绝、触发门控、
绝对路径/NetID 脱敏 ✓ —— 全是「一旦判错就会静默产出一份错数据」的地方 ✓。
厂商 Scope 导出格式一变，解析器只会在**现场**炸 ✓✓。

口径
----
先把**一份最小合法导出**跑通 ✓（阳性对照 —— 没有它，
三条失败断言可能因为「夹具本身不合法」而假绿 ✓），
再逐条把某一处弄坏，断言它**报的是那一条错** ✓（不是别的错、也不是静默通过 ✓）。
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from mcopilot.core import twincat as T  # noqa: E402

TAB = "\t"


def _meta(label: str, values) -> str:
    """通道表的一行：偶数列是标签，奇数列是每通道的值。"""
    cells = []
    for v in values:
        cells += [label, str(v)]
    return TAB.join(cells)


def _rows(rows) -> str:
    return "\n".join(TAB.join(str(c) for c in row) for row in rows)


def _export(names, dt_ms=1.0, n=50, *, x_of=None, extra_lines=()):
    """拼一份最小合法导出：通道名行 + 通道表 + 数据区。"""
    head = [_meta("Name", names), _meta(T.SAMPLE_TIME_LABEL, [dt_ms] * len(names))]
    data = []
    for i in range(n):
        x = x_of(i) if x_of else i
        row = []
        for k in range(len(names)):
            row += [x, float(i)]
        data.append(row)
    return "\n".join(head + list(extra_lines) + [_rows(data)]) + "\n"


def _write(tmp_path, text, name="scope.txt"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ------------------------------------------------------------- 阳性对照
def test_最小合法导出必须解析成功(tmp_path):
    """阳性对照 ✓：两通道 → cmd_pos/fb_pos → 规范 CSV 表头正确 ✓。

    没有这条，下面三条失败断言都可能因为「夹具根本不合法」而假绿 ✓✓。
    """
    p = _write(tmp_path, _export(["dPosition_asco", "dPosition_asco_enc"]))
    exp = T.parse_twincat(p)
    assert len(exp.channels) == 2
    assert exp.n_rows == 50
    assert len(exp.skipped) == 0
    mapping = T.map_channels(exp.channels)
    assert mapping.canonical["cmd_pos"].name == "dPosition_asco"
    assert mapping.canonical["fb_pos"].name == "dPosition_asco_enc"
    out = tmp_path / "canonical.csv"
    info = T.write_canonical_csv(exp, mapping, out)
    assert info["header"] == ["time_ms", "cmd_pos", "fb_pos"]
    first = out.read_text(encoding="utf-8").splitlines()[1].split(",")
    assert first[0] == "0" and first[1] == "0" and first[2] == "0"


# --------------------------------------------------- 失败分支 1：跳过行 > 1%
def test_跳过行占比超过百分之一必须报错(tmp_path):
    """坏行 > 1% → 必须**拒绝**，不得静默丢行 ✓（评审点名的第一条 ✓）。"""
    lines = _export(["dPosition_asco", "dPosition_asco_enc"], n=50).splitlines()
    # 表头 2 行 + 数据 50 行；弄坏 2 行 → 2/50 = 4% > 1%
    lines[2] = "0"            # 列数不足
    lines[3] = "1"            # 列数不足
    p = _write(tmp_path, "\n".join(lines) + "\n")
    with pytest.raises(T.TwincatParseError) as ei:
        T.parse_twincat(p)
    msg = str(ei.value)
    assert "超过 1%" in msg or "1%" in msg, "必须指出超过 1% 阈值：%s" % msg
    assert "拒绝静默丢行" in msg, "必须说明「拒绝静默丢行」：%s" % msg


def test_少量坏行在阈值内是丢弃并记录而不是报错(tmp_path):
    """阈值**以内**的坏行：丢弃 + 记进 skipped ✓（不是崩，也不是静默无痕 ✓）。"""
    lines = _export(["dPosition_asco", "dPosition_asco_enc"], n=400).splitlines()
    lines[2] = "0"            # 1/400 = 0.25% ≤ 1%
    p = _write(tmp_path, "\n".join(lines) + "\n")
    exp = T.parse_twincat(p)
    assert len(exp.skipped) == 1, "坏行应被记录为 1 条跳过"
    assert exp.n_rows == 399


# ------------------------------------------------- 失败分支 2：时基非单调
def test_时间列非严格单调必须报错(tmp_path):
    """时间倒退/持平 → 必须报错 ✓（否则频谱、微分全在错时基上算 ✓）。"""
    p = _write(tmp_path, _export(["dPosition_asco", "dPosition_asco_enc"],
                                  n=10, x_of=lambda i: [0, 1, 2, 2, 4, 5, 6, 7, 8, 9][i]))
    with pytest.raises(T.TwincatParseError) as ei:
        T.parse_twincat(p)
    assert "非严格单调" in str(ei.value), "必须指出时基非严格单调：%s" % ei.value


# --------------------------------------------- 失败分支 3：语义冲突
def test_两个通道映射到同一规范列必须报语义冲突(tmp_path):
    """两个通道都映射到 cmd_pos → 必须**拒绝猜测** ✓（评审点名的第三条 ✓）。"""
    p = _write(tmp_path, _export(["dPosition_asco", "dPosition_asco"]))
    exp = T.parse_twincat(p)
    with pytest.raises(T.TwincatParseError) as ei:
        T.map_channels(exp.channels)
    msg = str(ei.value)
    assert "语义冲突" in msg, "必须报「语义冲突」：%s" % msg
    assert "cmd_pos" in msg, "必须指出冲突的规范列：%s" % msg


# --------------------------------------------- 失败分支 4：缺时基不猜
def test_缺SampleTime行且未覆盖时必须拒绝猜测时基(tmp_path):
    """没有 `SampleTime[ms]` 行、调用方也没给 → **拒绝猜** ✓（不得默认 1ms ✓）。"""
    text = _meta("Name", ["dPosition_asco", "dPosition_asco_enc"]) + "\n" + \
        _rows([[i, float(i), i, float(i)] for i in range(10)]) + "\n"
    p = _write(tmp_path, text)
    with pytest.raises(T.TwincatParseError) as ei:
        T.parse_twincat(p)
    assert "时基" in str(ei.value), "必须说明拒绝猜测时基：%s" % ei.value


def test_缺SampleTime行但给了覆盖值时必须能解析(tmp_path):
    """同一份文件，显式给 `sample_time_ms` → 必须能解析 ✓（覆盖路径此前零测试 ✓）。"""
    text = _meta("Name", ["dPosition_asco", "dPosition_asco_enc"]) + "\n" + \
        _rows([[i, float(i), i, float(i)] for i in range(10)]) + "\n"
    p = _write(tmp_path, text)
    exp = T.parse_twincat(p, sample_time_ms=2.0)
    assert exp.n_rows == 10
    assert exp.time_ms[1] == 2.0, "覆盖的采样周期没被用上：%s" % exp.time_ms[:3]


# --------------------------------------------- 失败分支 5：找不到通道名行
def test_找不到通道名行必须报错而不是返回空(tmp_path):
    """结构不符 → 报错 ✓（**不得**返回一份空结果让调用方以为「没有异常」✓）。"""
    p = _write(tmp_path, "随便写点东西\n没有表头\n")
    with pytest.raises(T.TwincatParseError) as ei:
        T.parse_twincat(p)
    assert "通道名行" in str(ei.value), "必须指出找不到通道名行：%s" % ei.value


# --------------------------------------------- 失败分支 6：数据区为空
def test_数据区为空必须报错(tmp_path):
    text = _meta("Name", ["dPosition_asco", "dPosition_asco_enc"]) + "\n" + \
        _meta(T.SAMPLE_TIME_LABEL, ["1.0", "1.0"]) + "\n"
    p = _write(tmp_path, text)
    with pytest.raises(T.TwincatParseError) as ei:
        T.parse_twincat(p)
    assert "数据区为空" in str(ei.value), "必须指出数据区为空：%s" % ei.value


# --------------------------------------------- 脱敏（绝对路径 / NetID）
def test_脱敏必须抹掉绝对路径与NetID():
    """`_redact` / `_redact_netid`：导出里带的绝对路径与 NetID 不得进交付物 ✓。"""
    assert "C:\\Users" not in T._redact("C:\\Users\\admin\\proj\\x.txt")
    assert "1.2.3.4.5.6" not in T._redact_netid("NetId=1.2.3.4.5.6")
