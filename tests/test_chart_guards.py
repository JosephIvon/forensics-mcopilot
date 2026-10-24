# -*- coding: utf-8 -*-
"""图表函数的输入契约守卫。

交叉验证真实波形时抓到的失败模式之一是「长度不对的序列照样画图」：
matplotlib 会抛 "x and y must have same first dimension"，
看不出是哪一路数据短了；更糟的是有人为了"让它跑起来"去截断或补零 ——
那等于把契约违约藏起来。本项目要求**显式失败好过错误实现**，
所以这里把长度校验钉成回归测试。
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from mcopilot.core import chart  # noqa: E402


def test_servo_chart_rejects_mismatched_lengths(tmp_path):
    if not chart.HAS_MPL:
        pytest.skip("无 matplotlib")
    with pytest.raises(ValueError) as e:
        chart.save_servo_chart(tmp_path / "x.png", [0.0, 1.0, 2.0],
                               [0.0, 1.0], [0.0, 0.1, 0.2], None, "t")
    assert "长度不一致" in str(e.value)
    # 错误信息要能指出是哪一路短了
    assert "t=3" in str(e.value) and "fb=2" in str(e.value)


def test_servo_chart_accepts_aligned_lengths(tmp_path):
    if not chart.HAS_MPL:
        pytest.skip("无 matplotlib")
    p = chart.save_servo_chart(tmp_path / "ok.png", [0.0, 1.0, 2.0],
                               [0.0, 1.0, 2.0], [0.0, 0.0, 0.0], 2.0, "t")
    assert p is not None and os.path.isfile(p)


def test_cam_chart_rejects_mismatched_lengths(tmp_path):
    if not chart.HAS_MPL:
        pytest.skip("无 matplotlib")
    # slopes 是**按段**的：点数-1。3 个点应有 2 个斜率，给 1 个就是违约
    with pytest.raises(ValueError) as e:
        chart.save_cam_chart(tmp_path / "x.png", [0.0, 1.0, 2.0],
                             [0.0, 1.0, 2.0], [1.0], "t")
    assert "长度不一致" in str(e.value)


def test_cam_chart_accepts_per_segment_slopes(tmp_path):
    if not chart.HAS_MPL:
        pytest.skip("无 matplotlib")
    p = chart.save_cam_chart(tmp_path / "ok.png", [0.0, 1.0, 2.0],
                             [0.0, 0.5, 2.0], [0.5, 1.5], "t")
    assert p is not None and os.path.isfile(p)
