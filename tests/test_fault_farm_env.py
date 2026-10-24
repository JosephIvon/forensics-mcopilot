# -*- coding: utf-8 -*-
"""故障注入农场：**环境缺席**必须记 SKIP，不能把农场带崩。

2026-10-24 在 GitHub Actions runner 上实测出来的：
  runner 机器上只有 COM2，没有 com0com 的 COM3/COM4 对。
  农场的 RTU 前置探测 `rtu_available()` 里，`Win32SerialPort.open()`
  打不开串口时抛的是 **`SystemExit`**（fixture 拿它报"环境没到位"），
  而 `SystemExit` 继承自 `BaseException`——`except Exception` **接不住**。
  于是：探测本该返回 False（→ 整路记 SKIP），实际却把整个农场进程带崩，
  进程以退出码 1 死掉，门禁判「农场场景失败」→ CI 红了。

  这条测试把 runner 的条件**在本地复现**：把串口层的 `open()` 换成
  「一开口就抛 SystemExit」，然后要求
    ① `rtu_available()` 返回 False，**不抛异常**；
    ② 农场整条跑下来，RTU 两场景记 SKIP、**退出码 0**（缺席不算败）。

纪律：环境缺席是**环境事实**，不是场景失败；门禁对它的态度是
「当前不可自动复核」，不是「红」。但**崩溃更糟**——崩溃会让整条门禁失去意义。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests" / "fixtures" / "modbus"))

import fault_farm  # noqa: E402


class _PortAbsent:
    """模拟"这个串口不存在"：open() 抛 SystemExit，与 fixture 真实行为一致。"""

    def __init__(self, name, baud):
        self.name = name

    def open(self):
        raise SystemExit(f"[从站] 打开串口 {self.name} 失败: CreateFileW 错误码 2")

    def close(self):
        raise SystemExit("close on unopened handle")


@pytest.fixture
def 无串口(monkeypatch):
    """把串口层换成"一开口就 SystemExit"，复现 runner 上的 COM3/COM4 缺席。"""
    mod = fault_farm._rtu_mod()
    assert mod is not None, "串口层模块必须能导入，否则本测试的前提不成立"
    monkeypatch.setattr(mod, "Win32SerialPort", _PortAbsent)
    return mod


def test_口缺席时探测返回False而不是抛异常(无串口):
    """探测的职责是"回答在不在场"，不是"把异常往上抛"。"""
    assert fault_farm.rtu_available() is False


def test_口缺席时农场整路记SKIP且退出码为0(无串口, tmp_path):
    """缺席 = 环境事实 = 记 SKIP；农场必须正常收尾（退出码 0），不是崩。"""
    out = tmp_path / "farm"
    code = fault_farm.main(["--out", str(out), "--python-exe", sys.executable])
    assert code == 0, f"口缺席时农场不该失败，退出码 {code}"

    index = json.loads((out / "scenario_index.json").read_text(encoding="utf-8"))
    rtu = [s for s in index if s["channel"] == "rtu"]
    assert rtu, "RTU 场景应当仍在场景表里（记 SKIP，不是消失）"
    for s in rtu:
        assert s["status"] == "SKIP", f"{s['scenario']} 应记 SKIP，实得 {s['status']}"
        assert "COM3/COM4" in (s.get("detail") or ""), f"{s['scenario']} 的 SKIP 理由要说清是口缺席"


def test_缺依赖时也只记SKIP(monkeypatch, tmp_path):
    """连串口层都导不进来时（非 Windows / 缺依赖），同样只记 SKIP。"""
    monkeypatch.setattr(fault_farm, "_rtu_mod", lambda: None)
    assert fault_farm.rtu_available() is False
    out = tmp_path / "farm"
    code = fault_farm.main(["--out", str(out), "--python-exe", sys.executable])
    assert code == 0, f"串口层不可用时农场不该失败，退出码 {code}"
    index = json.loads((out / "scenario_index.json").read_text(encoding="utf-8"))
    assert all(s["status"] == "SKIP" for s in index if s["channel"] == "rtu")
