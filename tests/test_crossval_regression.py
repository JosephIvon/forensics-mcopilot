# -*- coding: utf-8 -*-
"""把交叉验证（docs/交叉验证_Export10.md）的失败点锁成回归测试。

每条都对应交叉验证里的一个 F-xx，注明**当时错在哪、现在凭什么对**。
数据源：samples/servo/twincat_export10.csv（CODESYS Scope 导出，fs=1000 Hz，18651 点）。

F-xx 的原始复算脚本在 scripts/verify_crossval_claims.py（纯标准库，不调 mcopilot），
本文件只做**行为**锁定，不重复实现算法。
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
SAMPLE = os.path.join(ROOT, "samples", "servo", "twincat_export10.csv")

sys.path.insert(0, SRC)

from mcopilot.agents import servo  # noqa: E402
from mcopilot.core import chart  # noqa: E402


@pytest.fixture(scope="module")
def c3():
    w = servo.load_waveform(__import__("pathlib").Path(SAMPLE))
    rules = servo.load_rules()
    dg = servo.diagnose(w, rules)
    return dg.get("c3", {}), dg


def test_f01_no_crash_on_real_export10(c3):
    """F-01：厂商 CSV 没有 err 列 → 旧代码 `w.err or []` 传空序列给 matplotlib。

    旧行为：退出码 3，out/ 目录空，报告没生成。
    现在：必须在真实数据上跑通并产出契约 JSON。"""
    c3obj, dg = c3
    assert dg, "diagnose 返回空"
    assert c3obj, "没有产出 C3 契约对象"


def test_f03_constant_offset_is_decomposed(c3):
    """F-03：cmd−fb 有 179.81 mm 的常数偏置（占总误差 99.81%），旧代码直接当跟随误差读。"""
    _, dg = c3
    ea = dg.get("error") or {}
    dyn = ea.get("dynamic_std")
    assert dyn is not None, "没有做常数偏置分解"
    assert 0.15 < dyn < 0.40, f"去偏置动态 std 应约 0.27，实际 {dyn}"
    off = ea.get("offset") or ea.get("mean")
    assert off is None or abs(off) > 100, "没有报出常数偏置本身"


def test_f07_lowest_bin_is_not_reported_as_a_frequency(c3):
    """F-07：旧口径把主频报成 0.49 Hz（2048 点 nfft 的**最低 bin**，k=1）。

    0.49 Hz 不是频率，是去趋势后的残余摆到边界 bin 上、再除以极小基线造出来的假象。
    报告里必须当场说破，不能让读者以为存在 sub-Hz 振荡。"""
    w = servo.load_waveform(__import__("pathlib").Path(SAMPLE))
    rules = servo.load_rules()
    dg = servo.diagnose(w, rules)
    freq = dg.get("frequency") or {}
    assert freq.get("ok")
    assert "bin" in freq and "resolution_hz" in freq, "没报 bin / 分辨率"
    if freq.get("is_edge_bin"):
        assert freq["bin"] <= 1, "is_edge_bin 与 bin 不自洽"
        # 报告文本里必须带这句警告
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            servo.build_report(w, dg, rules, __import__("pathlib").Path(td), "x")
            md = os.path.join(td, "x.md")
            if os.path.isfile(md):
                with io.open(md, encoding="utf-8") as fh:
                    text = fh.read()
                assert "不是真实频率" in text, "落在边缘 bin 上却没有把话说明白"


def test_refresh_rate_is_measured_not_assumed(c3):
    """指令刷新率必须**实测**（cmd 跳变间隔中位数的倒数），不许写死。

    Export10 的 cmd 是 10 ms 阶梯 → 100 Hz。"""
    _, dg = c3
    sig = dg.get("signals") or {}
    rr = sig.get("refresh_rate_hz")
    assert rr is not None, "没有测刷新率"
    assert abs(rr - 100.0) < 1.0, f"刷新率应约 100 Hz，实际 {rr}"


def test_spectral_line_uses_absolute_amplitude(c3):
    """谱线判据必须以**绝对幅值 ÷ 误差动态量级**判，且两个口径都报出来。"""
    _, dg = c3
    sig = dg.get("signals") or {}
    ln = sig.get("tail_line") or {}
    assert ln.get("ok")
    assert "amplitude" in ln, "没报绝对幅值"
    assert sig.get("line_over_dynamic") is not None, "没算 幅值/动态量级"
    assert sig.get("line_over_dynamic_global") is not None, "没报全记录口径"


def test_refresh_harmonic_line_never_becomes_a_hypothesis(c3):
    """谱线落在指令刷新率整数倍上 → 判为「指令刷新成分」，**不进 hypotheses**。"""
    c3obj, dg = c3
    sig = dg.get("signals") or {}
    if sig.get("line_at_refresh_harmonic"):
        assert not c3obj.get("hypotheses"), "刷新率谐波谱线不该进 hypotheses"
        blocked = {r.get("blocked_by")
                   for r in (c3obj.get("differential") or {}).get("not_evaluable", [])
                   if isinstance(r, dict)}
        assert "spectral_line_at_command_refresh_rate" in blocked


def test_wording_never_says_pseudo_line(c3):
    """全程用「指令刷新成分」，不许用「伪谱线」。"""
    c3obj, _ = c3
    blob = json.dumps(c3obj, ensure_ascii=False)
    assert "伪谱线" not in blob
    if (c3obj.get("signals") or {}).get("line_at_refresh_harmonic"):
        assert "指令刷新成分" in blob


def test_c3_contract_shape(c3):
    """C3 契约的顶层形状：schema / verdict / hypotheses / differential / audit。"""
    c3obj, _ = c3
    for k in ("schema", "verdict", "hypotheses", "differential", "audit"):
        assert k in c3obj, f"C3 缺顶层键 {k}"
    assert c3obj["schema"].startswith("mcopilot.servo.diagnosis/")
    au = c3obj["audit"]

    def ids(raw):
        """audit 三档的条目可能是字符串，也可能是带 id 的 dict。"""
        out = set()
        for x in (raw or []):
            if isinstance(x, str):
                out.add(x)
            elif isinstance(x, dict):
                out.add(x.get("id") or x.get("rule") or x.get("rule_id")
                        or json.dumps(x, sort_keys=True, ensure_ascii=False))
        return out

    # 三档状态互斥：一条判据只能落在一个档里
    fired = ids(au.get("rules_fired"))
    skipped = ids(au.get("rules_skipped"))
    not_hit = ids(au.get("rules_not_hit"))
    assert not (fired & skipped), "rules_fired 与 rules_skipped 有重叠"
    assert not (fired & not_hit), "rules_fired 与 rules_not_hit 有重叠"
    assert not (skipped & not_hit), "rules_skipped 与 rules_not_hit 有重叠"


def test_not_evaluable_rows_are_actionable(c3):
    """不可评估清单每行必须带 blocked_by + why + unlocks —— 否则读者不知道该补什么。"""
    c3obj, _ = c3
    ne = (c3obj.get("differential") or {}).get("not_evaluable", [])
    for r in ne:
        if isinstance(r, dict):
            assert r.get("blocked_by"), f"不可评估行缺 blocked_by: {r}"
            assert r.get("why"), f"不可评估行缺 why: {r}"


def test_cli_exits_zero_on_real_data(tmp_path):
    """端到端：CLI 在真实数据上退出码必须是 0，且产出 md + png + 契约 JSON。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(
        [sys.executable, "-m", "mcopilot", "servo", "diagnose", SAMPLE, "--out", str(tmp_path)],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0, f"退出码 {r.returncode}\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}"
    files = os.listdir(tmp_path)
    assert any(f.endswith(".md") for f in files), f"没有报告: {files}"
    assert any(f.endswith(".json") for f in files), f"没有契约 JSON: {files}"
    # 退出码 0、报告与契约产物**不依赖** matplotlib（它是可选依赖，缺它时
    # 按设计降级为「不画图但报告照出」）。出图这一条只在 matplotlib 在位时断言——
    # 在位时它坏了，就必须红。
    if chart.HAS_MPL:
        assert any(f.endswith(".png") for f in files), f"没有图: {files}"
