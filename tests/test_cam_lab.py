"""电子凸轮校验器（cam_lab）回归测试。

重点测两件事：
  1. **算得对不对** —— 斜率、速度阶跃、行程方程；
  2. **每条厂商结论都钉在外部真值上** —— cam_rules.json 里写的每个官方函数，
     必须同时出现在官方 C# 绑定和 DLL 导出表里（这是本仓库的硬规则）。
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcopilot.agents import cam_lab  # noqa: E402
from mcopilot.core.util import knowledge_path, read_json  # noqa: E402

API = ROOT / "knowledge" / "sdks" / "official_api"


def _load_csv(name: str) -> list[dict]:
    with open(API / name, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


# ------------------------------------------------------------------ 几何与运动学


def test_斜率与速度加速度关系():
    """从轴速度 = 斜率 × 主轴速度；从轴加速度 = 斜率 × 主轴加速度。"""
    t = cam_lab.CamTable(master=[0.0, 10.0], slave=[0.0, 5.0])
    res = cam_lab.analyze(t, master_v=100.0, master_a=20.0,
                          slave_v_max=1000.0, slave_a_max=1000.0)
    seg = res["segments"][0]
    assert seg["k"] == pytest.approx(0.5)
    assert seg["v_slave"] == pytest.approx(50.0)      # 0.5 × 100
    assert seg["a_slave"] == pytest.approx(10.0)      # 0.5 × 20


def test_断点速度阶跃等于斜率差乘主轴速度():
    t = cam_lab.CamTable(master=[0.0, 10.0, 20.0], slave=[0.0, 5.0, 5.0])
    res = cam_lab.analyze(t, master_v=100.0, master_a=0.0,
                          slave_v_max=1000.0, slave_a_max=1000.0)
    # 第 1 段斜率 0.5，第 2 段斜率 0 → 阶跃 = |0 − 0.5| × 100 = 50
    assert res["steps"][0]["dv"] == pytest.approx(50.0)
    assert res["steps"][0]["ratio_of_limit"] == pytest.approx(0.05)


def test_主轴非单调报高危():
    t = cam_lab.CamTable(master=[0.0, 10.0, 5.0], slave=[0.0, 5.0, 2.0])
    res = cam_lab.analyze(t, master_v=100.0, master_a=0.0,
                          slave_v_max=1000.0, slave_a_max=1000.0)
    assert res["verdict_code"] == "fail"
    assert any(f["check"] == "CAM-01" for f in res["findings"])


def test_从轴速度超限报高危():
    t = cam_lab.CamTable(master=[0.0, 10.0], slave=[0.0, 50.0])
    res = cam_lab.analyze(t, master_v=100.0, master_a=0.0,
                          slave_v_max=100.0, slave_a_max=10000.0)
    assert any(f["check"] == "CAM-02" and f["level"] == "高" for f in res["findings"])


def test_从轴行程超限报高危():
    t = cam_lab.CamTable(master=[0.0, 10.0], slave=[0.0, 50.0])
    res = cam_lab.analyze(t, master_v=10.0, master_a=0.0,
                          slave_v_max=10000.0, slave_a_max=10000.0,
                          slave_travel_limit=20.0)
    assert any(f["check"] == "CAM-05" and f["level"] == "高" for f in res["findings"])


def test_样例凸轮表能检出速度阶跃():
    """样例表是手画的：第 7 段接缝处从 0 斜率跳到 0.2 → 72 mm/s 阶跃。"""
    table = cam_lab.load_table(ROOT / "samples" / "cam" / "pick_place_cam.csv")
    res = cam_lab.analyze(table, master_v=360.0, master_a=200.0,
                          slave_v_max=300.0, slave_a_max=2000.0,
                          slave_travel_limit=120.0)
    assert res["verdict_code"] == "fail"
    assert res["metrics"]["worst_velocity_step"] == pytest.approx(72.0, rel=1e-6)
    assert res["metrics"]["worst_velocity_step_ratio"] == pytest.approx(0.24, rel=1e-3)


def test_跟随误差超容差报中危():
    t = cam_lab.CamTable(master=[0.0, 10.0], slave=[0.0, 5.0])
    res = cam_lab.analyze(t, master_v=100.0, master_a=100.0,
                          slave_v_max=1e6, slave_a_max=1e6,
                          omega_hz=5.0, tol_mm=0.0001)
    assert any(f["check"] == "CAM-06" and f["level"] == "中" for f in res["findings"])


# ------------------------------------------------------------------ 凸轮表生成


def test_生成表的从轴行程精确等于请求值():
    """踩过的坑：把峰值速度往小钳会破坏行程方程（8 mm 走成 35.25 mm）。"""
    table, info = cam_lab.plan_table(
        master_travel=360.0, slave_travel=8.0, segments=4,
        master_v=360.0, slave_v_max=300.0, slave_a_max=2000.0)
    assert table.slave_travel == pytest.approx(8.0, rel=1e-6)
    assert all(s["ok"] for s in info)
    assert table.slave[-1] == pytest.approx(8.0, rel=1e-6)
    assert table.slave[0] == pytest.approx(0.0, abs=1e-9)


def test_生成表主轴严格单调():
    table, _ = cam_lab.plan_table(360.0, 8.0, 4, 360.0, 300.0, 2000.0)
    for i in range(len(table.master) - 1):
        assert table.master[i + 1] > table.master[i]


def test_生成表段接缝处没有速度阶跃():
    """梯形剖面：每段都从 0 起到峰值再回 0 → 接缝处两侧速度都是 0。

    注意断言的是**接缝两侧的折线斜率相等**（速度连续），
    不是「斜率为 0」—— 抛物线加减速段被折线逼近后，斜坡末端的斜率不为 0，
    但只要左右两段斜率相同，从轴速度就是连续的。
    """
    table, _ = cam_lab.plan_table(360.0, 8.0, 4, 360.0, 300.0, 2000.0)
    slopes = table.slopes()
    for seam in (90.0, 180.0, 270.0):
        idx = [i for i, m in enumerate(table.master) if abs(m - seam) < 1e-6]
        assert idx, f"主轴 {seam} 处应有断点"
        i = idx[0]
        assert slopes[i - 1] == pytest.approx(slopes[i], abs=1e-9), (
            f"接缝 {seam} 处两侧斜率不等 → 从轴速度会阶跃："
            f"{slopes[i - 1]:.6g} vs {slopes[i]:.6g}")


def test_生成表的最大阶跃不出现在接缝上():
    """接缝处速度连续，阶跃只可能来自加减速斜坡内部的折线逼近误差。"""
    table, _ = cam_lab.plan_table(360.0, 8.0, 4, 360.0, 300.0, 2000.0)
    res = cam_lab.analyze(table, master_v=360.0, master_a=0.0,
                          slave_v_max=300.0, slave_a_max=2000.0)
    seam_steps = []
    for st in res["steps"]:
        # 接缝点：主轴坐标正好是 90/180/270（各段边界）
        if any(abs(st["m"] - seam) < 1e-6 for seam in (90.0, 180.0, 270.0)):
            seam_steps.append(st["dv"])
    assert len(seam_steps) == 3, f"应找到 3 个接缝，实际 {len(seam_steps)}"
    for dv in seam_steps:
        assert dv == pytest.approx(0.0, abs=1e-9)


def test_生成表自检不报高危():
    table, _ = cam_lab.plan_table(360.0, 8.0, 4, 360.0, 300.0, 2000.0)
    res = cam_lab.analyze(table, master_v=360.0, master_a=0.0,
                          slave_v_max=300.0, slave_a_max=2000.0)
    assert res["verdict_code"] in ("pass", "warn")


def test_时间不够时报不可行而不是给假结果():
    # 0.1 s 内要走 100 mm，加速度上限 100 mm/s² —— 物理上做不到
    table, info = cam_lab.plan_table(1.0, 100.0, 1, master_v=10.0,
                                     slave_v_max=1000.0, slave_a_max=100.0)
    assert info and not info[0]["ok"]
    assert "时间不够" in info[0]["why"] or "不可行" in info[0]["why"]


def test_从轴速度上限过低时报不可行():
    table, info = cam_lab.plan_table(360.0, 8.0, 4, master_v=360.0,
                                     slave_v_max=0.001, slave_a_max=2000.0)
    assert info and not info[0]["ok"]


def test_段比例分配改变各段从轴行程():
    table, info = cam_lab.plan_table(360.0, 12.0, 3, 360.0, 300.0, 2000.0,
                                     slave_ratios=[1.0, 2.0, 1.0])
    assert table.slave_travel == pytest.approx(12.0, rel=1e-6)
    assert info[0]["ds"] == pytest.approx(3.0, rel=1e-6)
    assert info[1]["ds"] == pytest.approx(6.0, rel=1e-6)


# ------------------------------------------------------------------ 读表


def test_读带表头的CSV(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("master,slave\n0,0\n10,5\n20,10\n", encoding="utf-8")
    t = cam_lab.load_table(p)
    assert t.master == [0.0, 10.0, 20.0]
    assert t.slave == [0.0, 5.0, 10.0]


def test_读不带表头的CSV(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("0,0\n10,5\n20,10\n", encoding="utf-8")
    t = cam_lab.load_table(p)
    assert t.master == [0.0, 10.0, 20.0]


def test_读中文表头CSV(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("主轴位置,从轴位置\n0,0\n10,5\n", encoding="utf-8")
    t = cam_lab.load_table(p)
    assert t.master == [0.0, 10.0]
    assert t.slave == [0.0, 5.0]


def test_读JSON点表(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"master": [0, 10, 20], "slave": [0, 5, 10]}), encoding="utf-8")
    t = cam_lab.load_table(p)
    assert t.slave[-1] == 10.0


def test_往返_生成后写出再读回结果一致(tmp_path):
    table, _ = cam_lab.plan_table(360.0, 8.0, 4, 360.0, 300.0, 2000.0)
    paths = cam_lab.write_table(table, tmp_path / "t.csv", tmp_path / "t.json")
    back = cam_lab.load_table(paths["csv"])
    assert back.master == pytest.approx(table.master)
    assert back.slave == pytest.approx(table.slave)


# ------------------------------------------------------------------ 厂商结论的外部真值校验


def test_cam_rules里每个官方函数都在官方绑定里():
    """硬规则：知识层写的每条厂商结论，都必须能在官方 C# 绑定里找到。"""
    rules = read_json(knowledge_path("cam_rules.json"))
    truth = {
        "雷赛": {r["函数名"] for r in _load_csv("leisai.csv")},
        "正运动": {r["函数名"] for r in _load_csv("zmotion.csv")},
        "固高": {r["函数名"] for r in _load_csv("gts.csv")},
    }
    for vendor, fns in rules["vendors"].items():
        for f in fns.get("functions", []):
            assert f["fn"] in truth[vendor], (
                f"{vendor}.{f['fn']} 不在官方 C# 绑定里 —— "
                f"知识层不能写官方绑定没有的函数")


def test_cam_rules里每个官方函数DLL都导得出():
    """第三层真值：函数必须在 PE 导出表里存在，否则上机 EntryPointNotFound。"""
    rules = read_json(knowledge_path("cam_rules.json"))
    exports: dict[str, set[str]] = {}
    for r in _load_csv("dll_exports.csv"):
        exports.setdefault(r["DLL"], set()).add(r["函数名"].strip())
    for vendor, fns in rules["vendors"].items():
        for f in fns.get("functions", []):
            assert f["fn"] in exports.get(f["dll"], set()), (
                f"{vendor}.{f['fn']} 在 {f['dll']} 的导出表里找不到")


def test_固高确实没有凸轮表函数():
    """「固高没有凸轮」是本工具最反直觉的一条结论，必须钉死。"""
    gts = {r["函数名"] for r in _load_csv("gts.csv")}
    assert not [n for n in gts if "cam" in n.lower() and "camera" not in n.lower()]
    exports = {r["函数名"].strip() for r in _load_csv("dll_exports.csv")
               if r["DLL"] == "gts.dll"}
    assert not [n for n in exports if "cam" in n.lower() and "camera" not in n.lower()]


def test_雷赛能整表下发凸轮_正运动不能():
    rules = read_json(knowledge_path("cam_rules.json"))
    assert rules["vendors"]["雷赛"]["table_upload_from_host"] is True
    assert rules["vendors"]["雷赛"]["table_upload_api"] == "dmc_cam_table_unit"
    assert rules["vendors"]["正运动"]["table_upload_from_host"] is False
    assert rules["vendors"]["固高"]["native_cam_table"] is False


def test_厂商能力报告能生成():
    res = cam_lab.run_caps(None, "cam_caps")
    md = res["report"].to_markdown()
    assert "雷赛" in md and "正运动" in md and "固高" in md
    assert "dmc_cam_table_unit" in md
    assert "ZAux_Direct_Cam" in md
