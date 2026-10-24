"""mcopilot 回归测试。

原则：测的是「算得对不对」和「检得出检不出」，
不是测「跑不跑得起来」—— 后者由 `mcopilot all` 的实跑覆盖。
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcopilot.agents import adapter_gen, forensics, motion_lab, requirements, review, servo, spc  # noqa: E402
from mcopilot.core import chart, util  # noqa: E402


# ------------------------------------------------------------------ 运动

def test_profile_端点精确():
    p = motion_lab.build_profile(500.0, 200.0, 1000.0, 5000.0)
    assert abs(p.end_x - 500.0) < 1e-6
    assert abs(p.end_v) < 1e-9
    assert abs(abs(p.v_peak) - 200.0) < 1e-9


def test_profile_短行程不产生匀速段():
    p = motion_lab.build_profile(1.0, 200.0, 1000.0, 5000.0)
    assert p.cruise_time == 0.0
    assert abs(p.end_x - 1.0) < 1e-9
    assert abs(p.v_peak) < 200.0


def test_profile_加速度与jerk不超限():
    p = motion_lab.build_profile(123.4, 180.0, 900.0, 4000.0)
    s = motion_lab.sample(p, 0.0005)
    assert max(abs(a) for a in s["a"]) <= 900.0 + 1e-6
    assert max(abs(v) for v in s["v"]) <= 180.0 + 1e-6


def test_profile_加速度时间对称():
    p = motion_lab.build_profile(300.0, 150.0, 800.0, 3000.0)
    acc = sum(s.dur for s in p.segments if s.name.startswith("加速"))
    dec = sum(s.dur for s in p.segments if s.name.startswith("减速"))
    assert abs(acc - dec) < 1e-9


def test_profile_负方向():
    p = motion_lab.build_profile(-100.0, 50.0, 500.0, 2000.0)
    assert abs(p.end_x + 100.0) < 1e-9
    assert p.v_peak < 0


def test_profile_速度连续():
    p = motion_lab.build_profile(200.0, 120.0, 600.0, 2500.0)
    dt = 0.0002
    s = motion_lab.sample(p, dt)
    dv = max(abs(s["v"][i + 1] - s["v"][i]) for i in range(len(s["v"]) - 1))
    assert dv <= 600.0 * dt * 1.02


def test_stop_distance_等于加速段距离():
    d = motion_lab.stop_distance(200.0, 1000.0, 5000.0)
    ap = motion_lab._accel_phase(200.0, 1000.0, 5000.0)
    assert abs(d - ap["dist"]) < 1e-9


def test_settle_跟随误差随带宽上升而下降():
    lo = motion_lab.settle_estimate(30.0, 0.7, 1000.0, 0.01)
    hi = motion_lab.settle_estimate(60.0, 0.7, 1000.0, 0.01)
    assert hi["follow_error_mm"] < lo["follow_error_mm"]
    assert not lo["within_tolerance"]
    assert hi["max_accel_allowed"] > lo["max_accel_allowed"]


def test_gear_一致与偏差():
    ok = motion_lab.check_scale(10.0, 131072, 1.0, 16384, 1638.4, 200.0)
    assert abs(ok["scale_error_pct"]) < 0.01
    bad = motion_lab.check_scale(10.0, 131072, 1.0, 16384, 1600.0, 200.0)
    assert abs(bad["scale_error_pct"]) > 1.0
    assert abs(bad["position_error_at_travel_mm"]) > 3.0


def test_compare_匀速段内与段外判定():
    p = motion_lab.build_profile(500.0, 200.0, 1000.0, 5000.0)
    inside = motion_lab.compare_point(p, 250.0, 13107.2, 50.0, 0.01)
    outside = motion_lab.compare_point(p, 5.0, 13107.2, 50.0, 0.01)
    assert inside["in_cruise"] is True
    assert outside["in_cruise"] is False
    assert outside["warnings"]


def test_golden_vectors_可序列化且端点正确():
    data = motion_lab.golden_vectors([{"name": "c", "distance": 100.0, "v": 100.0,
                                       "a": 500.0, "j": 2000.0}])
    json.dumps(data)  # 不能有不可序列化对象
    assert data["cases"][0]["expected"]["end_position_mm"] == 100.0


# ------------------------------------------------------------------ 需求基线

def test_requirements_每条都有判定与承接():
    data = requirements.analyze()
    assert len(data["items"]) == 20
    for it in data["items"]:
        assert it["verdict"] in ("高替代", "增强", "人主导")
        assert 0.0 <= it["ai_share"] <= 1.0
        assert "human_only" in it


def test_requirements_伺服条目已拆分为在线与离线():
    """Q-06 必须拆开：现场闭环整定留人，波形离线诊断交给 AI。"""
    data = requirements.analyze()
    items = {i["id"]: i for i in data["items"]}
    assert "Q-06a" in items and "Q-06b" in items
    assert items["Q-06a"]["verdict"] == "人主导", "在线自整定不应被判为可替代"
    assert items["Q-06b"]["verdict"] in ("增强", "高替代"), "离线波形诊断应判为可自动化"
    assert "servo" in items["Q-06b"]["agents"]
    assert "motion_lab" in items["Q-06a"]["agents"]


def test_requirements_高替代条目均有工具承接():
    data = requirements.analyze()
    for it in data["items"]:
        if it["verdict"] == "高替代":
            assert it["agents"], f"{it['id']} 判定为高替代却没有承接工具"


def test_requirements_覆盖审计无孤儿():
    """有 AI 承担度却没有工具承接的条目，必须为 0。"""
    data = requirements.analyze()
    cov = requirements.coverage(data)
    for i in cov["orphan_items"]:
        item = next(x for x in data["items"] if x["id"] == i)
        assert item["ai_share"] == 0.0, f"{i} 有 AI 承担度却没有工具承接"


# ------------------------------------------------------------------ 取证

@pytest.fixture(scope="module")
def sample_findings():
    log = ROOT / "samples" / "logs" / "machine_a.log"
    rules = forensics._load_rules()
    fmt = forensics._load_format()
    lines, _ = forensics.parse_log(log, fmt, rules)
    return lines, forensics.detect(lines, rules)


def test_forensics_解析出全部行():
    log = ROOT / "samples" / "logs" / "machine_a.log"
    rules = forensics._load_rules()
    fmt = forensics._load_format()
    lines, skipped = forensics.parse_log(log, fmt, rules)
    assert len(lines) > 1000
    assert skipped == 0


def test_forensics_检出植入的全部缺陷类型(sample_findings):
    _, findings = sample_findings
    ids = {f.fid for f in findings}
    for expected in ("position_deviation", "param_conflict", "concurrent_command",
                     "comm_gap", "cycle_jitter", "timeout_burst", "calib_drift",
                     "heartbeat_gap", "vision_ng_rate"):
        assert expected in ids, f"未检出 {expected}；实际检出 {sorted(ids)}"


def test_forensics_证据可指回原始行号(sample_findings):
    _, findings = sample_findings
    for f in findings:
        for no, text in f.evidence:
            assert no > 0
            assert text.strip()


def test_forensics_根因候选带验证方法():
    rules = forensics._load_rules()
    findings = [forensics.Finding("position_deviation", "高", "t", "d", "i", "s", count=2)]
    roots = forensics.rank_root_causes(findings, rules)
    assert roots
    assert roots[0]["verify"]
    assert roots[0]["score"] > 0


def test_forensics_植入清单与检测器命中一一对应():
    """样例里植入的每一组缺陷，都必须被对应检测器命中 —— 且清单本身可核对行号。

    ⚠ 这仍然不是「对你们的日志有效」的证明：样例与规则同源。
       它能证明的是「检测逻辑自洽 + 植入清单与检出结果不脱节」。
    """
    manifest = json.loads((ROOT / "samples" / "logs" / "planted_defects.json").read_text(encoding="utf-8"))
    assert manifest["planted_groups"] == len(manifest["defects"])

    rules = forensics._load_rules()
    fmt = forensics._load_format()
    lines, _ = forensics.parse_log(ROOT / "samples" / "logs" / manifest["log"], fmt, rules)
    findings = forensics.detect(lines, rules)
    ids = {f.fid for f in findings}

    for d in manifest["defects"]:
        assert d["line_no"], f"植入缺陷 {d['id']} 的锚点在日志里找不到：{d['anchor']!r}"
        for exp in d["expects"]:
            assert exp in ids, \
                f"植入缺陷 {d['id']}({d['name']}) 期望命中 {exp}；实际命中 {sorted(ids)}"

    # 清单声明的期望类型集合必须与实际一致，不能多也不能少
    assert set(manifest["expected_detector_types"]) == set(
        e for d in manifest["defects"] for e in d["expects"])


def test_forensics_根因排序_严重度优先于次数():
    """高频低信号项不应压过低频高危项。"""
    rules = forensics._load_rules()
    findings = [
        forensics.Finding("cycle_jitter", "中", "t", "d", "i", "s", count=120),
        forensics.Finding("position_deviation", "高", "t", "d", "i", "s", count=2),
    ]
    roots = forensics.rank_root_causes(findings, rules)
    top = roots[0]
    assert "position_deviation" in " ".join(top["from"]), \
        f"高危项应排在前面，实际首位来自 {top['from']}"


# ------------------------------------------------------------------ 格式体检（probe）

def test_forensics_probe_内置样例判定为可直接分析():
    pr = forensics.probe(ROOT / "samples" / "logs" / "machine_a.log")
    assert pr["verdict"] == "可直接分析"
    assert pr["match_rate"] > 0.95
    assert pr["events_needing_fix"] == 0
    assert pr["blocked_by_format"] == 0


def test_forensics_probe_异构行格式只影响行格式层():
    """vendor_b 只是行布局不同、键名相同 → 事件正则一行都不用改。"""
    pr = forensics.probe(ROOT / "samples" / "logs" / "vendor_b.log")
    assert pr["verdict"] == "需适配"
    assert pr["match_rate"] < 0.5, "行格式应当对不上"
    assert pr["events_needing_fix"] == 0, "键名相同，事件正则不该需要改"
    assert pr["blocked_by_format"] == 0, "改 line_regex 即可，不该有检测器被格式卡死"
    assert pr["suggested_line_regex"], "应给出可用的 line_regex 起点"


def test_forensics_probe_字段名不同会被逐条指出():
    pr = forensics.probe(ROOT / "samples" / "logs" / "legacy_c.log")
    ev = {e["type"]: e for e in pr["events"]}
    assert ev["MOVE_CMD"]["status"] == "缺字段"
    sug = ev["MOVE_CMD"]["suggestion"]
    assert "pos" in sug and "spd" in sug, f"应指出字段名对应关系，实际：{sug}"
    assert pr["blocked_by_format"] > 0, "字段名不同会卡掉依赖它的检测器"


def test_forensics_probe_区分格式阻塞与无埋点():
    """这两种「跑不了」性质完全不同，不能混成一个数字。"""
    pr = forensics.probe(ROOT / "samples" / "logs" / "legacy_c.log")
    assert pr["blocked_no_data"] > 0
    for d in pr["detectors"]:
        assert not (d["blocked_by_format"] and d["no_data"]), \
            "同一个检测器不应同时被格式和缺埋点挡住"


def test_forensics_probe_不把同前缀事件误判成缺埋点():
    """回归：'App Stop' 不是 STOP 事件，'ParamWrite' 不是 IO Write 事件。

    早期版本用子串匹配特征词，把这两类都误判成「日志里有、正则对不上」。
    """
    pr = forensics.probe(ROOT / "samples" / "logs" / "machine_a.log")
    ev = {e["type"]: e for e in pr["events"]}
    for t in ("STOP", "IO_WRITE", "IO_EDGE", "JOG_CMD", "MOVE_REL_CMD"):
        assert ev[t]["status"] == "未出现", f"{t} 应判为「未出现」，实际 {ev[t]['status']}"


def test_forensics_probe_三种样例的耦合成本有明确区分():
    a = forensics.probe(ROOT / "samples" / "logs" / "machine_a.log")
    b = forensics.probe(ROOT / "samples" / "logs" / "vendor_b.log")
    c = forensics.probe(ROOT / "samples" / "logs" / "legacy_c.log")
    assert a["adapt_cost"] == 0.0
    assert b["adapt_cost"] == 0.0, "只换行格式不应计入事件正则的适配成本"
    assert c["adapt_cost"] > 0.0, "字段名不同必须计入适配成本"


def test_forensics_probe_三份样例的报告都能出():
    """回归：报告里「改法示例」那段曾因 join 嵌套列表而崩掉。

    只有真正存在「需改正则/缺字段」事件的日志才会走到那段，
    所以 `mcopilot all` 跑 vendor_b 时发现不了 —— 必须单独盯住 legacy_c。
    """
    for name in ("machine_a", "vendor_b", "legacy_c"):
        pr = forensics.probe(ROOT / "samples" / "logs" / f"{name}.log")
        md = forensics.build_probe_report(pr).to_markdown()
        assert len(md) > 500, f"{name} 的体检报告内容异常短"
        assert "第 1 层" in md and "第 2 层" in md


# ------------------------------------------------------------------ SPC

def test_spc_控制图统计量正确():
    ds = spc.load_csv(ROOT / "samples" / "process" / "line1_lot.csv")
    assert ds.n == 1200
    values = ds.col("place_x_mm")
    im = spc.i_mr(values)
    assert im["ok"]
    assert im["lcl"] < im["cl"] < im["ucl"]
    assert im["mr_ucl"] > im["mr_bar"]


def test_spc_检出漂移批次的超限点():
    ds = spc.load_csv(ROOT / "samples" / "process" / "line1_lot.csv")
    im = spc.i_mr(ds.col("place_x_mm"))
    assert im["ooc_count"] > 0, "漂移批次应当产生超限点"


def test_spc_良率趋势与变点():
    ds = spc.load_csv(ROOT / "samples" / "process" / "line1_lot.csv")
    gy = spc.yield_by_group(ds, "lot")
    assert len(gy) == 40
    marks = util.cusum([g["yield_pct"] for g in gy], threshold=1.0)
    assert any(m["shift"] for m in marks)


def test_spc_参数相关性抓到漂移因子():
    ds = spc.load_csv(ROOT / "samples" / "process" / "line1_lot.csv")
    binary = [1 if str(r.get("result", "")).upper() == "NG" else 0 for r in ds.rows]
    xs = ds.col("place_x_mm")
    r = util.point_biserial(binary, xs)
    assert r > 0.1, f"place_x 与不良的相关性应显著为正，实际 {r}"


def test_spc_pareto_累计占比单调():
    pr = spc.pareto([("A", 5), ("B", 3), ("C", 2)])
    assert pr[0]["cum_pct"] <= pr[1]["cum_pct"] <= pr[2]["cum_pct"]
    assert abs(pr[-1]["cum_pct"] - 100.0) < 1e-6
    assert pr[0]["name"] == "A", "应按数量降序排列"


def test_spc_非数值行被排除时_报告必须写出两个口径(tmp_path):
    """口径纪律：报告里写「样本 N 条」，控制图却画在 N-k 点上，而没人知道 k>0。

    这是本仓的硬纪律第 4 条（凡计数必标口径）在本模块的落点——
    排除多少行必须出现在报告里，否则"样本数"与"参与统计的点数"就是两个同名不同义的数。
    """
    csv_path = tmp_path / "mixed.csv"
    rows = ["metric,result"]
    for i in range(40):
        # 前 40 条有数值，后 10 条该列是脏值
        v = f"{0.1 * i:.3f}" if i < 30 else "N/A"
        rows.append(f"{v},{'NG' if i % 7 == 0 else 'OK'}")
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    ds = spc.load_csv(csv_path, result_col="result")
    assert ds.n == 40
    values = ds.col("metric")
    assert len(values) == 30, "脏值行应被排除"
    assert ds.dropped["metric"] == 10, "排除数必须被记账"

    rep = spc.build_report(ds, "metric", None, None, "result", None, "t")
    body = "\n".join(
        s[1] if isinstance(s, tuple) else str(s) for s in rep.sections
    )
    assert "参与统计 30 点" in body, f"报告必须写明参与统计的点数：\n{body[:800]}"
    assert "10 条" in body, f"报告必须写明被排除的行数：\n{body[:800]}"
    assert "样本 40 条" in body, f"报告必须同时保留样本行数口径：\n{body[:800]}"


# ------------------------------------------------------------------ 评审

def test_review_检出样例代码中的问题():
    src = ROOT / "samples" / "code"
    res = review.scan([src], src)
    ids = {i.rule_id for i in res["issues"] if not i.is_positive}
    for expected in ("RT-001", "RT-002", "RT-003", "RT-004", "RT-005", "RT-007"):
        assert expected in ids, f"未检出 {expected}；实际 {sorted(ids)}"


def test_review_不误报已做换算的行(tmp_path):
    f = tmp_path / "ok.cs"
    f.write_text(
        "var pulses = (int)Math.Round(posMm * PulsePerMm);\n"
        "var err = DmcBoard.dmc_pmove(card, axis, pulses, 1);\n",
        encoding="utf-8")
    res = review.scan([f], tmp_path)
    ids = {i.rule_id for i in res["issues"]}
    assert "RT-004" not in ids


def test_review_注释行不报(tmp_path):
    f = tmp_path / "c.cs"
    f.write_text("// Thread.Sleep(100);\n/* lock(x) { */\n", encoding="utf-8")
    res = review.scan([f], tmp_path)
    assert not [i for i in res["issues"] if not i.is_positive]


# ------------------------------------------------------------------ 适配层

def test_adapter_生成的CSharp不含未替换占位符():
    sdk = json.loads((util.KNOWLEDGE_DIR / "sdks" / "dmc.json").read_text(encoding="utf-8"))
    sdk["sdk_file"] = "dmc.json"
    code = adapter_gen.render_adapter(sdk)
    assert "{{" not in code, "存在未替换的占位符"
    assert "public sealed class DmcMotionController" in code
    assert "IMotionController" in code


def test_adapter_正运动版本含UNITS换算():
    sdk = json.loads((util.KNOWLEDGE_DIR / "sdks" / "zmotion.json").read_text(encoding="utf-8"))
    sdk["sdk_file"] = "zmotion.json"
    code = adapter_gen.render_adapter(sdk)
    assert "UNITS" in code
    assert "ZAux_OpenEth" in code


def test_adapter_接口模板含关键方法():
    iface = adapter_gen.render_interface()
    for m in ("MoveAbs", "MoveLinear", "GetPositionMm", "GetFeedbackMm", "GetStopReason",
              "SetPulsePerMm", "SetCompareOutput"):
        assert f"{m}(" in iface


def test_adapter_契约测试含单位一致性用例():
    t = adapter_gen.render_contract_tests()
    assert "单位一致" in t
    assert "NotSupportedException" in t


def test_adapter_能力矩阵含跨品牌差异():
    from mcopilot.core.util import knowledge_path
    data = json.loads(knowledge_path("cards.json").read_text(encoding="utf-8"))
    assert len(data["cross_brand_diffs"]) >= 5
    assert all("how_to_avoid" in d for d in data["cross_brand_diffs"])


# ------------------------------------------------------------------ C# 结构自检
# 目的：生成器改坏了要立刻发现。不依赖 C# 编译器（CI 上未必有 .NET SDK），
# 真正编译验证用仓库根的 scripts/compile_check.ps1（本机已验证 exit 0）。

def _interface_members() -> list[str]:
    import re
    iface = adapter_gen.render_interface()
    body = iface.split("public interface IMotionController", 1)[1]
    # 按接口内的缩进（8 空格）匹配方法声明；
    # 不能按 "}" 截断 —— `string Vendor { get; }` 这类属性会提前截断。
    return sorted(set(re.findall(
        r"^\s{8}(?:void|bool|int|double|string|AxisState)\s+(\w+)\s*\(", body, re.M)))


def _brace_balance(code: str) -> int:
    depth = 0
    for ch in code:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    return depth


def test_adapter_实现接口全部成员():
    members = _interface_members()
    assert len(members) >= 20, f"接口成员提取异常：{members}"
    for sdk_name in ("dmc", "zmotion", "gts"):
        sdk = json.loads((util.KNOWLEDGE_DIR / "sdks" / f"{sdk_name}.json").read_text(encoding="utf-8"))
        sdk["sdk_file"] = f"{sdk_name}.json"
        code = adapter_gen.render_adapter(sdk)
        for m in members:
            assert re.search(rf"\bpublic\s+[\w\.<>\[\]]+\s+{m}\s*\(", code), \
                f"{sdk_name} 适配器未实现接口成员 {m}"
        assert _brace_balance(code) == 0, f"{sdk_name} 适配器花括号不配对"


def test_adapter_仿真器实现接口全部成员():
    import re
    members = _interface_members()
    code = adapter_gen.render_simulator()
    for m in members:
        assert re.search(rf"\bpublic\s+[\w\.<>\[\]]+\s+{m}\s*\(", code), f"仿真器未实现 {m}"
    assert _brace_balance(code) == 0


def test_adapter_生成代码括号配对且无占位符():
    for sdk_name in ("dmc", "zmotion", "gts"):
        sdk = json.loads((util.KNOWLEDGE_DIR / "sdks" / f"{sdk_name}.json").read_text(encoding="utf-8"))
        sdk["sdk_file"] = f"{sdk_name}.json"
        code = adapter_gen.render_adapter(sdk)
        assert _brace_balance(code) == 0
        assert "{{" not in code
        assert code.count("public static extern") >= 10, "P/Invoke 声明数量异常"


def test_adapter_雷赛与正运动的关键差异被正确表达():
    dmc = json.loads((util.KNOWLEDGE_DIR / "sdks" / "dmc.json").read_text(encoding="utf-8"))
    zm = json.loads((util.KNOWLEDGE_DIR / "sdks" / "zmotion.json").read_text(encoding="utf-8"))
    dmc["sdk_file"] = "dmc.json"
    zm["sdk_file"] = "zmotion.json"
    dmc_code = adapter_gen.render_adapter(dmc)
    zm_code = adapter_gen.render_adapter(zm)
    # 雷赛用脉冲（需显式换算），正运动用 UNITS（官方换算）
    assert "GetPulsePerMm(axis)" in dmc_code and "pulses" in dmc_code
    assert "UNITS" in zm_code
    # 正运动单轴/多轴是两套符号：单轴 Single_*，多轴 4 参 MoveAbs（轴列表式）
    assert "ZAux_Direct_Single_MoveAbs" in zm_code
    assert "ZAux_Direct_MoveAbs" in zm_code
    assert "MoveAbsGroup" not in zm_code, "旧的 MoveAbsGroup（同 EntryPoint 不同参数）绑定已废弃"
    # 正运动的反馈必须读 MPOS，不能拿 DPOS 顶替
    assert "ZAux_Direct_GetMpos" in zm_code and "ZAux_Direct_GetDpos" in zm_code


def test_adapter_关键PInvoke签名不回退():
    """P/Invoke 签名写错 = 栈错位或连不上，比缺实现更危险。

    下面每一条都对着厂商官方手册原文核对过；任何一条回退都要立刻被发现。
    """
    zm = json.loads((util.KNOWLEDGE_DIR / "sdks" / "zmotion.json").read_text(encoding="utf-8"))
    z = {f["fn"]: f for f in zm["pinvoke"]}
    assert [a["name"] for a in z["ZAux_OpenEth"]["args"]] == ["ip", "handle"], \
        "ZAux_OpenEth 只有 (IP, 句柄) 两个参数"
    assert len(z["ZAux_Direct_HwPswitch2"]["args"]) == 9, "HwPswitch2 是 9 参数"
    assert len(z["ZAux_Direct_MoveAbs"]["args"]) == 4, "多轴 MoveAbs 是 4 参数（轴数+轴列表+目标列表）"
    assert len(z["ZAux_Direct_Regist"]["args"]) == 3, "Regist 是 3 参数（句柄+轴+锁存方式）"
    assert z["ZAux_Direct_GetMpos"]["args"][-1].get("is_ref") is True

    dmc = json.loads((util.KNOWLEDGE_DIR / "sdks" / "dmc.json").read_text(encoding="utf-8"))
    d = {f["fn"]: f for f in dmc["pinvoke"]}
    assert d["dmc_board_init"]["args"] == [], "dmc_board_init 无参数，返回在线卡数"
    assert d["dmc_board_close"]["args"] == [], "dmc_board_close 无参数"
    assert d["dmc_get_position"]["ret"] == "int", "dmc_get_position 直接返回 Int32 脉冲数"
    assert len(d["dmc_set_ltc_mode"]["args"]) == 5, "dmc_set_ltc_mode 是 5 参数（含滤波时间）"
    assert len(d["dmc_compare_add_point"]["args"]) == 6, "dmc_compare_add_point 是 6 参数"
    assert len(d["dmc_hcmp_set_config"]["args"]) == 6
    assert len(d["dmc_set_homemode"]["args"]) == 6, "dmc_set_homemode 是 6 参数"


def _official_api(vendor: str) -> dict[str, str]:
    """官方 C# 绑定导出的真值清单：函数名 → 所在 DLL。

    来源是厂商随包下发的官方绑定（正运动 Zmcaux.cs / 雷赛 LTDMC.cs），
    已导出为 knowledge/sdks/official_api/*.csv 存在仓库里 —— 这就是「外部真值」，
    不是我们自己造的样例（习惯 3，2026-10-19）。
    """
    import csv
    p = util.KNOWLEDGE_DIR / "sdks" / "official_api" / f"{vendor}.csv"
    rows = list(csv.DictReader(p.read_text(encoding="utf-8").splitlines()))
    return {r["函数名"]: r["DLL"] for r in rows}


def _official_proto(vendor: str) -> dict[str, str]:
    import csv
    p = util.KNOWLEDGE_DIR / "sdks" / "official_api" / f"{vendor}.csv"
    rows = list(csv.DictReader(p.read_text(encoding="utf-8").splitlines()))
    # 官方绑定里可能有同名重载（雷赛有 3 个）→ 取第一条，避免字典被后面的行覆盖
    out = {}
    for r in rows:
        out.setdefault(r["函数名"], r["官方原型"])
    return out


def _official_protos(vendor: str) -> dict[str, list[str]]:
    """函数名 → 官方全部原型（同名重载时不止一个）。"""
    import csv
    p = util.KNOWLEDGE_DIR / "sdks" / "official_api" / f"{vendor}.csv"
    rows = list(csv.DictReader(p.read_text(encoding="utf-8").splitlines()))
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["函数名"], []).append(r["官方原型"])
    return out


def _arg_count(proto: str) -> int:
    inner = proto[proto.index("(") + 1: proto.rindex(")")]
    if not inner.strip():
        return 0
    depth, count = 0, 1
    for ch in inner:
        if ch in "(<[":
            depth += 1
        elif ch in ")>]":
            depth -= 1
        elif ch == "," and depth == 0:
            count += 1
    return count


def test_多行文档注释每行都必须带三斜杠():
    """XML 文档注释的续行漏掉 `///` → 那行会被当成代码 → 生成的 C# 编译不过。

    踩过两次（正运动 ATYPE 注释、雷赛停止原因注释）：症状是 csc 报一堆
    CS1519/CS1056 的看不懂的错，而错在 knowledge/sdks/*.json 里。
    """
    import re
    open_tag = re.compile(r"^\s*///\s*<(summary|remarks|param|returns)\b")
    close_in_line = re.compile(r"</(summary|remarks|param|returns)>")
    for name in ("dmc", "zmotion", "gts"):
        sdk = json.loads((util.KNOWLEDGE_DIR / "sdks" / f"{name}.json").read_text(encoding="utf-8"))
        code = adapter_gen.render_adapter(sdk)
        in_doc = False
        for i, ln in enumerate(code.splitlines(), 1):
            if in_doc and ln.strip() and not ln.strip().startswith("///"):
                raise AssertionError(f"{name}.json 渲染后第 {i} 行在文档注释块里却没有 /// 前缀：{ln.strip()[:60]}")
            if open_tag.search(ln) and not close_in_line.search(ln):
                in_doc = True
            elif close_in_line.search(ln):
                in_doc = False


def test_每条PInvoke必须在官方绑定里存在且DLL名一致():
    """绑一个官方不存在的函数 = 真机 EntryPointNotFound（建连即崩），比缺实现更危险。

    这条测试把「声明过的每个函数」都钉在厂商官方绑定上：
    函数名不存在、或 DLL 名对不上，立刻红。
    """
    for sdk_name, vendor in (("dmc", "leisai"), ("zmotion", "zmotion"), ("gts", "gts")):
        official = _official_api(vendor)
        sdk = json.loads((util.KNOWLEDGE_DIR / "sdks" / f"{sdk_name}.json").read_text(encoding="utf-8"))
        for fn in sdk["pinvoke"]:
            if fn.get("skip_emit"):
                continue
            assert fn["fn"] in official, \
                f"{sdk_name}.{fn['fn']} 不在官方 {vendor} 绑定里 —— 真机会 EntryPointNotFound"
            assert official[fn["fn"]].lower() == sdk["dll"].lower(), \
                f"{sdk_name}.{fn['fn']} 官方在 {official[fn['fn']]} 里，本仓库 dll 字段却是 {sdk['dll']}"


def test_PInvoke参数个数必须与官方一致():
    """参数个数对不上 = 栈错位。官方原型的参数个数是硬证据。"""
    for sdk_name, vendor in (("dmc", "leisai"), ("zmotion", "zmotion"), ("gts", "gts")):
        proto = _official_proto(vendor)
        sdk = json.loads((util.KNOWLEDGE_DIR / "sdks" / f"{sdk_name}.json").read_text(encoding="utf-8"))
        for fn in sdk["pinvoke"]:
            if fn.get("skip_emit") or fn["fn"] not in proto:
                continue
            n_mine = len(fn.get("args", []))
            n_off = _arg_count(proto[fn["fn"]])
            assert n_mine == n_off, \
                f"{sdk_name}.{fn['fn']} 本仓库 {n_mine} 参，官方 {n_off} 参：{proto[fn['fn']]}"


def _dll_exports() -> dict:
    """厂商 DLL 的 PE 导出表 —— 「这个函数能不能真的被 P/Invoke 到」的最终真值。

    官方 C# 绑定里声明了、官方 C 头文件里也声明了，随包 DLL 却**没导出**的函数，
    照抄一样 EntryPointNotFound。实测案例：正运动 `ZAux_Direct_GetNtype`
    （官方 Zmcaux.cs 有、zauxdll2.h 有，但 64 位 zauxdll.dll 导出表里没有）。
    所以「与官方绑定逐行校验」不够，必须再钉一层导出表。
    """
    import csv
    p = util.KNOWLEDGE_DIR / "sdks" / "official_api" / "dll_exports.csv"
    rows = list(csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()))
    return {(r["DLL"].lower(), int(r["位数"]), r.get("变体", ""), r["函数名"]): int(r["已导出"]) for r in rows}


def test_每条PInvoke必须被对应DLL真正导出():
    """官方件声明 ≠ DLL 导出。这条是「真机即崩」的最后一道闸。

    位数：同一 DLL 的 32/64 位导出集合**并不相同**（雷赛 LTDMC.dll 32 位少 8 个函数），
    而现场目标进程位数还没定 → 保守要求：**手上有哪个位数就必须在哪个位数里导得出**。

    变体：同一个 DLL 名可能对应好几个不同的文件（固高 gts.dll 有 4 个 SDK 变体 +
    MCT2008 工具目录里那份旧的），「变体」列区分它们。**只对依赖的变体做断言**，
    否则会把「工具目录那份旧 DLL 少 214 个导出」误判成我们的绑定有问题。
    """
    exports = _dll_exports()
    assert exports, "导出表真值不能为空"
    known_bad = {n for (_, _, _, n), v in exports.items() if v == 0}
    assert known_bad, "导出表里应记录「官方声明但 DLL 未导出」的雷区函数，否则真值文件本身可能没生成对"

    for sdk_name in ("dmc", "zmotion", "gts"):
        sdk = json.loads((util.KNOWLEDGE_DIR / "sdks" / f"{sdk_name}.json").read_text(encoding="utf-8"))
        dll = sdk["dll"].lower()
        variants = sdk.get("dll_variants") or [""]
        pairs = sorted({(b, var) for (d, b, var, _) in exports if d == dll and var in variants})
        assert pairs, f"{dll} 没有导出表真值 —— 补 dll_exports.csv"
        for fn in sdk["pinvoke"]:
            if fn.get("skip_emit"):
                continue
            for b, var in pairs:
                st = exports.get((dll, b, var, fn["fn"]))
                assert st == 1, (
                    f"{sdk_name}.{fn['fn']} 在 {dll} {b}-位[{var}] 里没有导出（已导出={st}）"
                    f"→ 真机 EntryPointNotFound")
                bad = {n for (d, bb, v, n), val in exports.items()
                       if d == dll and bb == b and v == var and val == 0}
                assert fn["fn"] not in bad, f"{sdk_name}.{fn['fn']} 是 {dll} {b}-位[{var}] 的已知雷区函数"


def test_正运动必须用zauxdll而不是zmotion():
    """官方 C# 绑定里 399 处 ZAux_* 全部指向 zauxdll.dll；zmotion.dll 是低层 ZMC_* 库。

    DLL 名写错 = 真机一建连就 EntryPointNotFound。
    """
    official = _official_api("zmotion")
    zaux = [n for n in official if n.startswith("ZAux_")]
    assert len(zaux) > 300, "官方清单不对，ZAux_ 函数数异常"
    assert all(official[n].lower() == "zauxdll.dll" for n in zaux), \
        "官方绑定里 ZAux_* 应全部在 zauxdll.dll"
    zm = json.loads((util.KNOWLEDGE_DIR / "sdks" / "zmotion.json").read_text(encoding="utf-8"))
    assert zm["dll"] == "zauxdll.dll"


def test_雷赛必须用LTDMC():
    """官方 LTDMC.cs 里 1463 个函数名（1466 条声明）全部指向 LTDMC.dll。"""
    official = _official_api("leisai")
    assert all(d.lower() == "ltdmc.dll" for d in official.values()), \
        "官方雷赛绑定的 DLL 应统一是 LTDMC.dll"
    dmc = json.loads((util.KNOWLEDGE_DIR / "sdks" / "dmc.json").read_text(encoding="utf-8"))
    assert dmc["dll"] == "LTDMC.dll"


def test_正运动轴参数必须用专用函数():
    """官方绑定里**没有** ZAux_Direct_SetAxisParam/GetAxisParam —— 正运动是一参一函数。

    踩过：照博客写了 SetAxisParam(handle, axis, "UNITS", v)，
    真机建连第一步就 EntryPointNotFound（适配器直接起不来）。
    """
    zm = json.loads((util.KNOWLEDGE_DIR / "sdks" / "zmotion.json").read_text(encoding="utf-8"))
    code = adapter_gen.render_adapter(zm)
    assert "ZAux_Direct_SetAxisParam" not in code, "正运动没有 SetAxisParam 这个函数"
    assert "ZAux_Direct_GetAxisParam" not in code, "正运动没有 GetAxisParam 这个函数"
    for fn in ("ZAux_Direct_SetUnits", "ZAux_Direct_SetSpeed", "ZAux_Direct_SetAccel",
               "ZAux_Direct_SetDecel", "ZAux_Direct_SetSramp", "ZAux_Direct_SetCreep"):
        assert fn in code, f"缺少官方轴参数函数 {fn}"
    assert "ZAux_Direct_GetAxisStatus" in code, "AXISSTATUS 应用专用函数读"
    assert "ZAux_Direct_GetAxisStopReason" in code, "停止原因应用官方专用函数读"


def test_官方回零mode表与EZ_count语义已落地():
    """官方手册 8.3：mode 0~12 全表；**ez_count 是保留参数，固定值 0**。

    网上流传的「ez_count 0=锁存指令位置/1=锁存编码器位置」是错的。
    """
    dmc = json.loads((util.KNOWLEDGE_DIR / "sdks" / "dmc.json").read_text(encoding="utf-8"))
    code = adapter_gen.render_adapter(dmc)
    for t in ("一次回零加回找", "二次回零", "原点锁存", "一次限位回零", "二次限位回零"):
        assert t in code, f"回零 mode 表缺「{t}」（官方手册 8.3）"
    assert "保留参数" in code, "ez_count 是保留参数固定 0，注释必须写对"
    assert "锁存编码器位置" not in code, "ez_count 的错误说法（锁存编码器位置）必须删掉"


def test_停止原因与错误码必须分开且有可读文本():
    """错误码=「调用失败没有」；停止原因=「运动为什么停的」，只有 0 是正常停止。"""
    dmc = json.loads((util.KNOWLEDGE_DIR / "sdks" / "dmc.json").read_text(encoding="utf-8"))
    code = adapter_gen.render_adapter(dmc)
    assert "LeisaiErrorText" in code and "LeisaiStopReasonText" in code, "两套码必须有各自的翻译"
    assert "正硬限位立即停止" in code, "停止原因表要有可读文本"
    assert "只有 **0 是正常停止**" in code, "必须写明只有 0 是正常停止"
    iface = adapter_gen.render_interface()
    assert "GetStopReasonText" in iface, "接口要暴露停止原因文本，业务层才能不按品牌分支"


def test_圆弧插补必须用官方入口且方向编码正确():
    """官方 ZAux_Direct_MoveCircAbs：先终点后圆心，0=逆时针 1=顺时针。"""
    zm = json.loads((util.KNOWLEDGE_DIR / "sdks" / "zmotion.json").read_text(encoding="utf-8"))
    code = adapter_gen.render_adapter(zm)
    assert "ZAux_Direct_MoveCircAbs" in code, "圆弧插补要用官方入口"
    assert "counterClockwise ? 0 : 1" in code, "方向编码必须是 0=逆时针 1=顺时针"
    body = "\n".join(zm["bodies"]["MoveArc"])
    assert body.index("endXMm") < body.index("centerXMm"), "官方参数顺序是先终点后圆心"


def test_adapter_雷赛读IO不得把电平当错误码():
    """dmc_read_inbit 返回的就是 IO 电平（0/1），当成错误码会把高电平判成「读失败」。"""
    dmc = json.loads((util.KNOWLEDGE_DIR / "sdks" / "dmc.json").read_text(encoding="utf-8"))
    body = "\n".join(dmc["bodies"]["ReadInput"])
    assert "dmc_read_inbit" in body
    assert "level != 0" in body
    assert "err != 0" not in body, "读输入口的返回值是电平，不能按错误码判"


def test_adapter_雷赛位置读取不得二次换算():
    """dmc_get_position 返回原始脉冲；dmc_get_position_unit 返回的已经是物理单位(mm)。"""
    dmc = json.loads((util.KNOWLEDGE_DIR / "sdks" / "dmc.json").read_text(encoding="utf-8"))
    body = "\n".join(dmc["bodies"]["GetPositionMm"])
    assert "Native.dmc_get_position(" in body
    assert "Native.dmc_get_position_unit(" not in body, \
        "_unit 版已是物理单位(mm)，再除一次脉冲当量就差 1000 倍"


def test_adapter_待核对函数在调用处必须留标记():
    """needs-manual-check 的函数一旦被 body 调用，代码里必须同时留 TODO 标记。

    矩阵里的 TODO 清单来自绑定；这条保证**代码里也看得见**，
    避免「清单说要核对、代码里却已经当成事实用」。
    """
    import re
    for sdk_name in ("dmc", "zmotion"):
        sdk = json.loads((util.KNOWLEDGE_DIR / "sdks" / f"{sdk_name}.json").read_text(encoding="utf-8"))
        need = {f["fn"] for f in sdk.get("pinvoke", []) if f.get("verified") == "needs-manual-check"}
        for op, lines in sdk.get("bodies", {}).items():
            text = "\n".join(lines)
            for fn in need:
                if re.search(rf"\b{re.escape(fn)}\s*\(", text):
                    assert "TODO[需核对厂商手册]" in text, \
                        f"{sdk_name}.{op} 调用了待核对函数 {fn}，代码里却没有 TODO[需核对厂商手册] 标记"


def test_adapter_参数名是CSharp关键字时必须报错而不是生成坏代码():
    """厂商手册里的参数名（in / out / ref …）直接搬进 C# 会编不过。

    踩过：ZAux_Direct_SetDatumIn 的参数名 in → `int in` 语法错误。
    宁可生成时报错，也不要产出一份编不过的适配器。
    """
    sdk = {
        "vendor": "测试厂", "dll": "x.dll", "namespace": "N", "class_name": "C",
        "pinvoke": [{"fn": "f", "ret": "int",
                     "args": [{"name": "in", "type": "int"}]}],
    }
    try:
        adapter_gen.render_pinvoke(sdk)
    except ValueError as e:
        assert "关键字" in str(e)
    else:
        raise AssertionError("参数名用了 C# 关键字却没有报错")


def test_生成的CSharp源码必须带UTF8BOM():
    """csc/MSBuild 对无 BOM 的源文件按系统 ANSI(GBK) 读，中文会被解码坏 → 编不过。"""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        adapter_gen.run_gen("zmotion", out)
        for f in out.glob("*.cs"):
            raw = f.read_bytes()
            assert raw.startswith(b"\xef\xbb\xbf"), f"{f.name} 缺少 UTF-8 BOM"
            raw.decode("utf-8-sig")  # 必须能按 UTF-8 解码


def test_点动方向必须被验证():
    """方向是厂商 API 里最容易写反、后果最重的一处映射（雷赛 0/1、正运动 -1/1）。

    写反了不报错、没日志，轴直接往反方向跑。
    仿真器必须建模点动，自检与契约测试都必须有方向用例，否则没人会发现。
    """
    sim = adapter_gen.render_simulator()
    assert "Jogging" in sim, "仿真器没有建模点动，方向无从验证"
    sc = adapter_gen.render_self_check()
    assert "点动方向" in sc, "仿真器自检没有点动方向用例"
    ct = adapter_gen.render_contract_tests()
    assert "点动方向" in ct, "契约测试没有点动方向用例（只有真机能抓适配器写反）"


def test_比较点与锁存端口越界必须被拦():
    """端口号错了 = 打到别的端子 = 飞拍误触发 / 锁存永不触发。

    真机上这类错不报错、不写日志，只在产线上炸 —— 所以仿真器必须先把它拦住。
    """
    sim = adapter_gen.render_simulator()
    assert "outPort < 0 || outPort >=" in sim, "比较输出端口未做范围校验"
    assert "inPort < 0 || inPort >=" in sim, "锁存输入端口未做范围校验"
    sc = adapter_gen.render_self_check()
    assert "比较点端口越界必须抛异常" in sc, "自检必须验证比较点端口越界会抛异常"
    assert "锁存端口越界必须抛异常" in sc, "自检必须验证锁存端口越界会抛异常"


def test_插补与回零必须离线就验():
    """上机时失败面越小越好：插补终点、圆弧显式失败、相对定位、回零归零。"""
    sc = adapter_gen.render_self_check()
    for case in ("直线插补必须各轴到达目标", "圆弧插补不支持时必须显式失败",
                 "相对定位必须增量正确", "回零后位置归零"):
        assert case in sc, f"仿真器自检缺少用例：{case}"
    ct = adapter_gen.render_contract_tests()
    assert "回零后_位置归零" in ct, "契约测试必须验回零后位置归零（工件坐标基准）"
    assert "直线插补_各轴到达目标" in ct, "契约测试必须验多轴插补终点"


def test_MCP工具数与README一致():
    """文档写「暴露 N 个工具」，代码就得真的是 N 个 —— 防文档漂移。"""
    from mcopilot import mcp_server
    names = [t["name"] for t in mcp_server.TOOLS]
    assert len(names) == len(set(names)), "MCP 工具名重复"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"暴露 (\d+) 个工具", readme)
    assert m, "README 里应写明 MCP 工具数量"
    assert int(m.group(1)) == len(names), \
        f"README 说 {m.group(1)} 个工具，代码里是 {len(names)} 个"


def test_锁存与比较通道映射按公开手册落地():
    """雷赛：锁存通道**由轴号决定**（LTC0→0~3 轴、LTC1→4~7 轴），triger_chunnel 是保留参数固定 0；
    通用输入口号 0~15，LTC0 = IN14、LTC1 = IN15（手册 8.14 表 8.3 / 8.17）。

    ⚠ 这里曾经写着「锁存器 0~3 → 硬件 IN4~IN7」——那是**错的**，官方手册表 8.3 明写
    bit14 = IN14/LTC0、bit15 = IN15/LTC1。改正见 .self-improving/lessons.md。
    正运动：imode 3/14 = R0/R1 上升沿（ZBasic REGIST 表）。"""
    dmc = json.loads((util.KNOWLEDGE_DIR / "sdks" / "dmc.json").read_text(encoding="utf-8"))
    dcode = adapter_gen.render_adapter(dmc)
    assert "LatchTriggerChannelFor" not in dcode, \
        "雷赛锁存通道由轴号决定，不得再用输入口号反推通道号（手册 8.17）"
    assert "case 4: return 0;" not in dcode, \
        "雷赛锁存触发通道不得再映射成 IN4~IN7 → 0~3（手册 8.14 表 8.3：LTC0=IN14、LTC1=IN15）"
    assert "dmc_set_latch_mode" in dcode
    # 保留参数必须传 0：ltc_mode / filter / triger_chunnel
    assert "dmc_set_ltc_mode(card, (ushort)axis, (ushort)LatchLogic, 0, 0)" in dcode, \
        "雷赛 dmc_set_ltc_mode 的 ltc_mode/filter 是保留参数（固定值 0），不得传自造值"
    assert "dmc_set_latch_mode(card, (ushort)axis, (ushort)LatchMode, (ushort)LatchSource, 0)" in dcode, \
        "雷赛 dmc_set_latch_mode 的 triger_chunnel 是保留参数（固定值 0）"
    # 通用输入口号是 0~15
    assert "inPort < 0 || inPort > 15" in dcode, "雷赛通用输入口号 0~15 的越界校验缺失"

    zm = json.loads((util.KNOWLEDGE_DIR / "sdks" / "zmotion.json").read_text(encoding="utf-8"))
    zcode = adapter_gen.render_adapter(zm)
    assert "case 0: return 3;" in zcode and "case 1: return 14;" in zcode, \
        "正运动 R0/R1 上升沿的 imode 应为 3/14"
    # 脉冲轴用 R2/R3（imode 18~21 未公开）→ 必须由调用方显式指定，不能猜
    assert "default: return -1;" in zcode


def test_已知错误码必须带可读含义():
    """错误码 10 = 发送数据失败/数据传输错误（查 PCI 槽位）。只丢一个数字给操作员没有用。"""
    dmc = json.loads((util.KNOWLEDGE_DIR / "sdks" / "dmc.json").read_text(encoding="utf-8"))
    code = adapter_gen.render_adapter(dmc)
    assert "发送数据失败" in code, "错误码 10 的含义应写进代码（官方手册 表 8.7）"
    assert "LeisaiErrorText(err)" in code, "错误消息应带上已知含义"
    assert "动态库层参数错误" in code, "错误码 2 的官方含义"


def test_正运动回零后MPOS清零有显式入口():
    """ATYPE=4 的轴回零后不保证清 MPOS → 必须有手动清零的方法。"""
    zm = json.loads((util.KNOWLEDGE_DIR / "sdks" / "zmotion.json").read_text(encoding="utf-8"))
    code = adapter_gen.render_adapter(zm)
    assert "ZAux_Direct_SetMpos" in code, "缺少 SetMpos 绑定"
    assert "ClearFeedbackPosition" in code, "缺少回零后手动清零的入口"


def test_厂商待确认项的提问不得互相重复():
    """同一家厂商的两条待确认项如果问的是同一件事，说明复制粘贴错了。

    厂商只会回答一遍 —— 另一条就一直悬着，现场以为「已经问过了」，其实那一条还是空的。
    """
    from mcopilot.core.util import knowledge_path
    data = json.loads(knowledge_path("cards.json").read_text(encoding="utf-8"))
    seen = {}
    for m in data["pending_manual_items"]:
        key = (m["brand"], m.get("ask", "").strip())
        assert key not in seen, (
            f"{m['brand']} 的两条待确认项问的是同一件事：「{m['item']}」与「{seen[key]}」")
        seen[key] = m["item"]


def test_厂商清单按公开资料精简过():
    """公开资料能定死的就别拿去问厂商 —— 问得越少，拿到答复越快。"""
    from mcopilot.core.util import knowledge_path
    data = json.loads(knowledge_path("cards.json").read_text(encoding="utf-8"))
    items = data["pending_manual_items"]
    must = [i for i in items if i.get("level") == "必须"]
    assert len(must) <= 6, f"必须问厂商的有 {len(must)} 项，太多了"
    for i in items:
        assert i.get("known"), f"{i['item']} 必须写清我方已查到的公开依据"
        assert i.get("blocks"), f"{i['item']} 必须写清卡住什么"


def test_契约测试含跟随误差非零断言():
    """这条断言抓的是「反馈位置是假数据」。没有它，GetFeedbackMm 写成返回指令位置也没人会发现。"""
    t = adapter_gen.render_contract_tests()
    assert "跟随误差必须非零" in t
    assert "maxErr > 0.001" in t
    assert "WaitSettled" in t


def test_开环轴上跟随误差断言必须自动不适用():
    """脉冲轴（正运动 ATYPE=1/7）上 MPOS 只是 DPOS 的副本 —— 跟随误差必然恒为 0。

    不分流就会在真机脉冲轴上误报「反馈是假数据」，逼人去改本来正确的代码。
    """
    t = adapter_gen.render_contract_tests()
    assert "HasRealFeedback" in t, "契约测试必须先问适配器该轴有没有真反馈"
    assert "本用例不适用" in t, "无真反馈的轴要明说不适用，而不是静默通过"
    # 断言位置必须在真正比较 cmd/fb 之前
    assert t.index("HasRealFeedback") < t.index("maxErr > 0.001")


def test_正运动ATYPE决定MPOS真伪():
    """ATYPE=1/7 的脉冲轴上 MPOS 是 DPOS 副本（假反馈），判错就会误报/漏报。"""
    zm = json.loads((util.KNOWLEDGE_DIR / "sdks" / "zmotion.json").read_text(encoding="utf-8"))
    code = adapter_gen.render_adapter(zm)
    assert "AxisHasRealFeedback" in code, "缺少按 ATYPE 判定反馈真伪的入口"
    for atype in ("Pulse = 1", "PulseWithEncoder = 4", "Virtual7 = 7",
                  "RtexBus = 50", "Csp = 65"):
        assert atype in code, f"ATYPE 表缺 {atype}"
    # 脉冲轴（1）与 7 判为假反馈，总线轴（65）与带编码器脉冲轴（4）判为真反馈
    assert "case ZMotionAxisType.PulseWithEncoder:" in code
    assert "case ZMotionAxisType.Csp:" in code
    assert "case ZMotionAxisType.Pulse:" not in code, "脉冲轴 ATYPE=1 必须是假反馈"


def test_正运动SDO入口与CiA402对象表已落地():
    """第四轮材料核实过的 SDO 入口与 CiA402 对象号要落在代码里，不能只停在嘴上。"""
    zm = json.loads((util.KNOWLEDGE_DIR / "sdks" / "zmotion.json").read_text(encoding="utf-8"))
    code = adapter_gen.render_adapter(zm)
    assert "ZAux_BusCmd_SDORead" in code and "ZAux_BusCmd_SDOWrite" in code
    for obj in ("0x6040", "0x6041", "0x6064", "0x60F4"):
        assert obj in code, f"CiA402 对象号 {obj} 未落地"
    assert "ReadBusAxisObject" in code, "缺少按轴读总线对象的入口（L1 验证 MPOS 真伪要用）"
    assert "ZAux_BusCmd_SDOReadAxis" in code, "官方按轴版 SDO 入口"


def test_总线轴使能必须保持显式失败():
    """CiA402 是标准不等于「主机可以自己写控制字」—— 使能归属没定死就不能写。"""
    zm = json.loads((util.KNOWLEDGE_DIR / "sdks" / "zmotion.json").read_text(encoding="utf-8"))
    code = adapter_gen.render_adapter(zm)
    body = zm["bodies"]["Enable"]
    assert any("NotSupportedException" in ln for ln in body), "使能必须显式失败"
    assert not any("Native.ZAux_BusCmd_SDOWrite" in ln for ln in body), \
        "使能归属未确认前不得写总线控制字"
    # 声明了写入口也不等于开放了写封装
    assert "WriteBusObject" not in code, "当前不提供公开的写总线对象封装"


def test_雷赛反馈真伪必须由接线配置决定():
    """dmc_get_encoder 没接线时恒为 0 —— 真伪只能由现场接线声明，不能靠代码猜。"""
    dmc = json.loads((util.KNOWLEDGE_DIR / "sdks" / "dmc.json").read_text(encoding="utf-8"))
    code = adapter_gen.render_adapter(dmc)
    assert "EncoderFeedbackWired" in code, "缺少编码器接线配置项"
    assert "return EncoderFeedbackWired;" in code


def test_雷赛回零方向未配置时必须抛异常():
    """方向猜错就是朝机构外跑 —— 没有安全默认方向，必须显式配置。"""
    dmc = json.loads((util.KNOWLEDGE_DIR / "sdks" / "dmc.json").read_text(encoding="utf-8"))
    code = adapter_gen.render_adapter(dmc)
    assert "HomeDir.Unconfigured" in code, "回零方向必须有未配置哨兵值"
    assert "HomeDirection == HomeDir.Unconfigured" in code, "回零前必须检查方向是否配置"
    assert "HomeDir.Unconfigured;" in code, "默认方向必须是 Unconfigured 而不是猜一个"


def test_仿真器必须能表达假反馈轴():
    """离线就得能验「开环轴被如实报告为无真反馈」，否则这条分流逻辑没人验过。"""
    code = adapter_gen.render_simulator()
    assert "realFeedback" in code
    assert "HasRealFeedback" in code
    assert "if (!_realFeedback) return cmd;" in code, "假反馈轴的反馈必须是指令位置的副本"


def test_自检必须覆盖假反馈轴():
    code = adapter_gen.render_self_check()
    assert "开环轴报告无真实反馈" in code, "自检必须覆盖开环/假反馈轴这条路径"


def test_仿真器必须能产生非零跟随误差():
    """仿真器若让反馈位置恒等于指令位置，「跟随误差非零」这条断言就永远抓不到东西。"""
    code = adapter_gen.render_simulator()
    assert "VelocityAt" in code
    assert "_followingErrorTauS" in code


def test_自检程序可生成且能跑():
    """adapter gen 必须产出可运行的仿真器自检：编译后能跑出通过/失败。"""
    code = adapter_gen.render_self_check()
    assert "跟随误差必须非零" in code
    assert "public static int Main()" in code


def test_能力矩阵含待FAE清单且可直接转发():
    from mcopilot.core.util import knowledge_path
    data = json.loads(knowledge_path("cards.json").read_text(encoding="utf-8"))
    items = data["pending_manual_items"]
    assert len(items) >= 8, "待厂商确认的项不能少"
    for it in items:
        assert it["brand"] and it["item"] and it["ask"] and it["why"], \
            "清单每一条都要能直接转发给厂商：品牌/事项/原因/怎么问"
        assert "blocks" in it, "每条要写清卡住什么，否则清单会变成泛泛的抱怨"
    rep = adapter_gen.build_matrix_report(knowledge_path(".").parent)
    md = rep.to_markdown()
    assert "必须问厂商" in md
    assert "PDO 映射" in md


# ------------------------------------------------------------------ 产品形态与驱动模型
# 形态（插卡 / 独立整机 / 软主站）决定驱动模型（板卡驱动 P/Invoke / 通信库），
# 选错不是「参数没配好」，而是整个实现路线作废。

FORM_FACTORS = {"plug_in_card", "standalone_controller", "soft_master"}


def test_每张卡都必须声明产品形态与驱动模型():
    from mcopilot.core.util import knowledge_path
    data = json.loads(knowledge_path("cards.json").read_text(encoding="utf-8"))
    for c in data["cards"]:
        assert c.get("form_factor") in FORM_FACTORS, f"{c['brand']} 的 form_factor 缺失或取值非法"
        assert c.get("driver_model"), f"{c['brand']} 必须写明驱动模型，否则没法判断该走哪条实现路线"


def test_能力矩阵里产品形态排在第一行():
    from mcopilot.core.util import knowledge_path
    md = adapter_gen.build_matrix_report(knowledge_path(".").parent).to_markdown()
    assert "产品形态" in md
    assert "插卡" in md and "独立式控制器" in md


def test_知识库不得再出现DMC_EC错误说法():
    """DMC-E 是 DMC 系列的 EtherCAT 插卡版（与 DMC 同头文件、同 DLL），不是「另一条产品线」。"""
    from mcopilot.core.util import knowledge_path
    kdir = knowledge_path(".")
    for root in (kdir, kdir.parent / "docs", kdir.parent / "src"):
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in {".json", ".md", ".cs", ".py", ".tmpl"}:
                assert "DMC-EC" not in p.read_text(encoding="utf-8", errors="ignore"), \
                    f"{p.name} 仍写着「DMC-EC 是另一个产品线」"


def test_待录品牌必须写明形态对实现路线的影响():
    from mcopilot.core.util import knowledge_path
    data = json.loads(knowledge_path("cards.json").read_text(encoding="utf-8"))
    acs = next(p for p in data["pending_brands"] if p["brand"] == "ACS")
    assert acs["form_factor"] == "standalone_controller"
    assert "P/Invoke" in acs["modeling_hint"], "ACS 走不通 P/Invoke 路线，必须写在建模提示里"


def test_形态确认是厂商清单的第零项():
    """形态定不下来，后面的型号/端子问题全都白问。"""
    from mcopilot.core.util import knowledge_path
    doc = (knowledge_path(".").parent / "docs" / "厂商手册索取清单.md").read_text(encoding="utf-8")
    assert "### 0. 现场产品的**形态**" in doc
    data = json.loads(knowledge_path("cards.json").read_text(encoding="utf-8"))
    first = data["pending_manual_items"][0]
    assert "形态" in first["item"], "形态确认必须排在待确认清单第一条"


# ------------------------------------------------------------------ 伺服（逆向诊断）
# 这一节的测试都是「有独立真值」的：真值来自解析解或物理模型，
# 不是工具自己的输出。断言的是「估计值能还原真值」。

def test_servo_二阶拟合能还原解析真值():
    """由解析二阶阶跃响应反推的 ωn/ζ，必须回到真值附近。"""
    for wn_true, z_true in [(20.0, 0.3), (40.0, 0.5), (80.0, 0.7), (120.0, 0.2), (60.0, 1.0)]:
        w = servo.synth_step_2nd_order(wn_true, z_true, 0.8, 2000.0)
        m = servo.step_metrics(w)
        fit = servo.fit_second_order(w.t, w.fb, m["start"], m["target"], m["step_time_s"])
        assert fit["ok"], f"拟合失败：{fit.get('reason')}"
        assert abs(fit["wn"] - wn_true) / wn_true < 0.05, \
            f"ωn 还原偏差过大：真值 {wn_true}，拟合 {fit['wn']:.2f}"
        assert abs(fit["zeta"] - z_true) < 0.05, \
            f"ζ 还原偏差过大：真值 {z_true}，拟合 {fit['zeta']:.4f}"


def test_servo_超调法与最小二乘都能还原真值():
    """两条独立算法都要能还原真值；欠阻尼时超调法应更准。"""
    w = servo.synth_step_2nd_order(40.0, 0.3, 0.8, 2000.0)
    m = servo.step_metrics(w)
    os = servo.estimate_second_order(m)
    assert os["ok"]
    assert abs(os["zeta"] - 0.3) < 0.02, f"超调法 ζ 偏差过大：{os['zeta']}"
    assert abs(os["wn"] - 40.0) / 40.0 < 0.05, f"超调法 ωn 偏差过大：{os['wn']}"


def test_servo_超调量与解析值一致():
    w = servo.synth_step_2nd_order(40.0, 0.7, 0.8, 2000.0)
    m = servo.step_metrics(w)
    analytic = 100.0 * math.exp(-math.pi * 0.7 / math.sqrt(1 - 0.7 ** 2))
    assert abs(m["overshoot_frac"] * 100.0 - analytic) < 0.5, \
        f"超调实测 {m['overshoot_frac'] * 100:.2f}% vs 解析 {analytic:.2f}%"


def test_servo_过零法测振铃频率():
    for wn_true, z_true, f_true in [(20.0, 0.2, 3.03), (40.0, 0.2, 5.89),
                                    (120.0, 0.15, 15.3)]:
        w = servo.synth_step_2nd_order(wn_true, z_true, 1.2, 4000.0)
        m = servo.step_metrics(w)
        dev = [x - m["target"] for x in w.fb]
        r = servo.zero_crossing_frequency(dev, w.fs)
        assert r["ok"]
        wd = wn_true * math.sqrt(1 - z_true ** 2) / (2 * math.pi)
        assert abs(r["freq_hz"] - wd) / wd < 0.08, \
            f"过零频率 {r['freq_hz']:.2f} Hz vs 解析 {wd:.2f} Hz"


def test_servo_双惯量模型带宽与刚体极限解析解一致():
    """柔性双惯量模型的 -3dB 带宽，必须等于 Kf→∞ 时的刚体解析带宽。

    这是一条**独立**的交叉验证：一边是 4×4 状态空间的频响数值解，
    另一边是二阶刚体系统的解析公式。两者对上，说明状态方程和频响实现都对。
    """
    J1 = J2 = 1.0
    wf, zf, Kt, Kp = 300.0, 0.05, 1.0, 400.0
    A, B, C = servo.servo_2inertia_matrices(J1, J2, wf, zf, Kt, Kp, 0.0)
    resp = servo.closed_loop_response(A, B, C)
    assert resp["ok"]
    Jtot, Bf = J1 + J2, 2 * zf * wf
    wn = math.sqrt(Kt * Kp / Jtot)
    zeta = Bf / (2 * math.sqrt(Kt * Kp * Jtot))
    z2 = zeta ** 2
    w_bw = wn * math.sqrt(1 - 2 * z2 + math.sqrt(4 * z2 ** 2 - 4 * z2 + 2))
    rigid_hz = w_bw / (2 * math.pi)
    assert abs(resp["bandwidth_hz"] - rigid_hz) / rigid_hz < 0.01, \
        f"模型带宽 {resp['bandwidth_hz']:.4f} Hz vs 刚体解析 {rigid_hz:.4f} Hz"


def test_servo_谐振峰与带宽是两个不同的数():
    """回归测试：曾把**谐振峰**当成 -3dB 带宽，两者差了近一倍。

    带宽必须是幅频**第一次**跌到 -3dB 的频率；谐振峰（|H|>1）要单独报。
    """
    A, B, C = servo.servo_2inertia_matrices(1.0, 1.0, 300.0, 0.05, 1.0, 400.0, 0.0)
    resp = servo.closed_loop_response(A, B, C)
    assert resp["has_resonance"], "该模型应当存在谐振峰"
    assert resp["resonance_peak"] > 1.0, "谐振峰幅值应大于直流增益"
    assert abs(resp["resonance_hz"] - resp["bandwidth_hz"]) / resp["bandwidth_hz"] > 0.2, \
        "谐振峰频率与 -3dB 带宽明显不同；曾被混为一谈"
    # 在谐振峰处幅值确实 > -3dB 线，说明它不可能是带宽
    target = resp["dc_gain"] / math.sqrt(2)
    assert resp["resonance_peak"] > target


def test_servo_二阶带宽公式对过阻尼同样成立():
    """旧公式在 ζ>0.707 时退化成 ωn/2π（那是自然频率，不是带宽），必须修正。

    物理上：欠阻尼有谐振峰，-3dB 带宽**大于**自然频率；
    过阻尼没有谐振峰，带宽**小于**自然频率。
    """
    fn = 100.0 / (2 * math.pi)
    # 欠阻尼：带宽 > 自然频率
    assert servo._second_order_bandwidth_hz(100.0, 0.3) > fn
    # 过阻尼：带宽严格小于自然频率，且不能等于（等于是旧公式的退化值）
    for zeta in (0.9, 1.0, 1.2):
        bw = servo._second_order_bandwidth_hz(100.0, zeta)
        assert 0.0 < bw < fn, f"ζ={zeta} 时带宽应严格小于自然频率，实际 {bw:.3f} vs {fn:.3f}"


def test_servo_时间列单位识别():
    """毫秒列必须被识别成毫秒 —— 搞错就是 ωn 差 1000 倍。"""
    assert servo._time_scale("time_ms", [0.0, 1.0])[1] == "ms"
    assert servo._time_scale("t_ms", [0.0, 1.0])[1] == "ms"
    assert servo._time_scale("time", [0.0, 0.001])[1] == "s"
    assert servo._time_scale("time_us", [0.0, 1.0])[1] == "us"
    # 显式指定优先于列名
    assert servo._time_scale("time_ms", [0.0, 1.0], "s")[1] == "s"


def test_servo_样例波形的检出结果与真值一致():
    """三份样例波形的 .truth.json 写明了期望命中什么，实际检出必须完全一致。

    这三份波形的真值是按物理模型算出来的（ωn/ζ/谐振频率/误差斜率），
    所以这里是**有外部真值**的核对 —— 不是「我造的数据我自己的规则读」。
    """
    base = ROOT / "samples" / "servo"
    rules = servo.load_rules()
    for name in ("case_a_normal", "case_b_resonance", "case_c_no_feedforward"):
        truth = json.loads((base / f"{name}.truth.json").read_text(encoding="utf-8"))
        w = servo.load_waveform(base / f"{name}.csv")
        dg = servo.diagnose(w, rules)
        got = sorted(f["fid"] for f in dg["findings"])
        assert got == sorted(truth["expect_findings"]), \
            f"{name} 期望 {sorted(truth['expect_findings'])}，实际 {got}"


def test_servo_谐振样例的振铃频率接近真值():
    base = ROOT / "samples" / "servo"
    truth = json.loads((base / "case_b_resonance.truth.json").read_text(encoding="utf-8"))
    w = servo.load_waveform(base / "case_b_resonance.csv")
    dg = servo.diagnose(w, servo.load_rules())
    got = dg["ringing"]["freq_hz"]
    assert abs(got - truth["ringing_hz"]) / truth["ringing_hz"] < 0.06, \
        f"测得振铃频率 {got:.2f} Hz vs 真值 {truth['ringing_hz']} Hz"


def test_servo_缺前馈样例的误差斜率等于真值():
    base = ROOT / "samples" / "servo"
    truth = json.loads((base / "case_c_no_feedforward.truth.json").read_text(encoding="utf-8"))
    w = servo.load_waveform(base / "case_c_no_feedforward.csv")
    dg = servo.diagnose(w, servo.load_rules())
    ea = dg["error"]
    assert abs(ea["vel_slope"] - truth["err_per_vel_s"]) < 1e-6, \
        f"误差斜率 {ea['vel_slope']} vs 真值 {truth['err_per_vel_s']}"


def test_servo_非阶跃波形不报阶跃类结论():
    """匀速段套二阶阶跃模型会得到没有物理意义的 ωn，必须挡住。"""
    w = servo.load_waveform(ROOT / "samples" / "servo" / "case_c_no_feedforward.csv")
    dg = servo.diagnose(w, servo.load_rules())
    assert dg["is_step"] is False
    ids = {f["fid"] for f in dg["findings"]}
    assert "SRV-01" not in ids and "SRV-02" not in ids


def test_servo_恒加速度段能被定位():
    """e≈a/ωn² 只对恒加速度段有意义，工具必须能在波形里找到它。"""
    fs = 2000.0
    n = 1200
    t = [i / fs for i in range(n)]
    # 0~0.2s 匀加速 500 mm/s²，0.2~0.4s 匀速，之后匀减速
    vel, a = [], 500.0
    for ti in t:
        if ti < 0.2:
            vel.append(a * ti)
        elif ti < 0.4:
            vel.append(a * 0.2)
        else:
            vel.append(max(0.0, a * 0.2 - a * (ti - 0.4)))
    win = servo.constant_accel_window(t, vel, 500.0)
    assert win is not None, "应能找到恒加速度段"
    i0, i1 = win
    assert t[i0] < 0.2 and t[i1] < 0.21, f"窗口应落在匀加速段，实际 {t[i0]:.3f}~{t[i1]:.3f}s"
    # 匀速段不该被误判成恒加速段
    # 恒真断言（`X is None or True`）等于没有断言：上一行注释说「匀速段不该被误判成
    # 恒加速段」，那就要真的判它是 None，而不是写个永远成立的式子。
    assert servo.constant_accel_window(t, vel, 50.0) is None


def test_servo_非恒加速度波形不硬凑窗口():
    """纯阶跃响应里没有恒加速度段，必须返回 None 而不是硬凑一个。"""
    w = servo.synth_step_2nd_order(40.0, 0.3, 0.8, 2000.0)
    assert servo.constant_accel_window(w.t, w.vel or [0.0] * w.n, 1000.0) is None


def test_servo_报告包含三条前提声明():
    """前提不写出来，结论会被误用 —— 这是硬性要求。"""
    w = servo.synth_step_2nd_order(40.0, 0.3, 0.8, 2000.0)
    rules = servo.load_rules()
    dg = servo.diagnose(w, rules)
    md = servo.build_report(w, dg, rules, None, "t").to_markdown()
    assert "type-2" in md
    assert "e ≈ a/ωn²" in md
    assert "不替代示波器" in md
    assert "等效二阶" in md


def test_servo_合成器写出的真值文件与模型一致():
    """servo synth 产出的 .truth.json 必须能用来核对估计器。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "w.csv"
        res = servo.run_synth("2nd", csv_path, wn=40.0, zeta=0.3)
        truth = json.loads(csv_path.with_suffix(".truth.json").read_text(encoding="utf-8"))
        assert abs(truth["wn"] - 40.0) < 1e-9
        assert abs(truth["zeta"] - 0.3) < 1e-9
        # 真值文件里的带宽要和估计器算出来的一致
        w = servo.load_waveform(csv_path)
        m = servo.step_metrics(w)
        fit = servo.fit_second_order(w.t, w.fb, m["start"], m["target"], m["step_time_s"])
        assert abs(fit["bandwidth_hz"] - truth["bandwidth_hz"]) / truth["bandwidth_hz"] < 0.05
        assert res["csv"].exists()


# ------------------------------------------------------------------ 阈值灵敏度与误报边界

def test_阈值扫描能定位结论翻转点():
    """翻转点必须被二分**精确定位**，不能停在粗网格上。

    只做粗网格会把「当前值离翻转点只有 30%」显示成「稳」——
    现场照着「稳」去标定，就会把脆阈值当成不用管。
    """
    from mcopilot.agents import threshold_lab
    log = ROOT / "samples" / "logs" / "machine_a.log"
    rules = forensics._load_rules()
    lines, _ = forensics.parse_log(log, forensics._load_format(), rules)
    res = threshold_lab.analyze(log)
    scans = {s["name"]: s for s in res["scans"]}
    assert scans, "一条阈值都没扫到"
    tol = scans["position_tolerance_mm"]
    assert tol["flip_low"] is not None, "定位偏差阈值应能扫到下侧翻转点"
    flip = tol["flip_low"][0]
    assert flip < tol["current"], "翻转点应在当前值下方"
    assert flip > 0, "翻转点必须是正数"
    # 真正的判据：翻转点上结论已经变了，再往上一点就回到当前结论
    n_at = threshold_lab._counts(lines, rules, "position_tolerance_mm", flip, tol["detectors"])
    n_above = threshold_lab._counts(lines, rules, "position_tolerance_mm",
                                    flip + (flip * 0.01), tol["detectors"])
    assert n_at != tol["base"], "翻转点上的命中数应与当前值不同"
    assert n_above == tol["base"], "翻转点之上应回到当前结论"
    for s in res["scans"]:
        assert s["verdict"] in ("脆", "偏脆", "较稳", "稳健", "偏严", "无数据")


def test_配置与代码不一致必须被抓出来():
    """死阈值（配了不读）与硬编码兜底（代码在读但配置没有）都要报出来。

    这两条不报出来，现场调阈值就是白调 —— 而且调的人不会发现。
    """
    from mcopilot.agents import threshold_lab
    rules = forensics._load_rules()
    rules = json.loads(json.dumps(rules))          # 深拷贝，不污染知识库
    rules["thresholds"]["我编的一个不存在的阈值"] = 1
    cons = threshold_lab._static_consistency(rules)
    assert "我编的一个不存在的阈值" in cons["dead"], "配了但代码不读的阈值应被列为死阈值"
    assert cons["read"], "应能解析出代码实际读取的阈值名"


def test_检测器误报边界表必须覆盖全部检测器():
    """每个检测器都要写清：误报源、内置防护、怎么人工复核。

    工具只说「触发了」，不说「该不该信」—— 这一栏空着，报告就会变成狼来了。
    """
    from mcopilot.core.util import knowledge_path
    meta = json.loads(knowledge_path("detector_meta.json").read_text(encoding="utf-8"))["detectors"]
    rules = json.loads(knowledge_path("log_rules.json").read_text(encoding="utf-8"))
    for det in rules["detector_requires"]:
        assert det in meta, f"检测器 {det} 没有误报边界说明"
        m = meta[det]
        assert m.get("false_positive_sources"), f"{det} 没写误报源"
        assert m.get("builtin_guard"), f"{det} 没写内置防护"
        assert m.get("how_to_verify"), f"{det} 没写怎么人工复核"


def test_阈值报告可直接转发():
    from mcopilot.agents import threshold_lab
    rep = threshold_lab.run(ROOT / "samples" / "logs" / "machine_a.log").get("report")
    md = rep.to_markdown()
    assert "阈值灵敏度" in md
    assert "检测器误报边界表" in md
    assert "配置与实现" in md, "配置与实现不一致必须显式成节，不能藏在别处"
    for det in ("position_deviation", "param_conflict", "heartbeat_gap"):
        assert det in md, f"误报边界表里应有 {det}"


# ------------------------------------------------------------------ 通用

def test_util_分位数与统计():
    xs = [1, 2, 3, 4, 5]
    assert util.percentile(xs, 0.5) == 3
    assert util.percentile(xs, 0.0) == 1
    assert util.percentile(xs, 1.0) == 5
    assert abs(util.mean(xs) - 3.0) < 1e-12


def test_util_能力指数判定():
    r = util.capability_indices(10.0, 0.0, 5.0, 1.0)
    assert abs(r["cp"] - 10.0 / 6.0) < 1e-9
    assert abs(r["cpk"] - 5.0 / 3.0) < 1e-9
    assert "合格" in r["verdict"]
    r2 = util.capability_indices(10.0, 0.0, 5.0, 5.0)
    assert "不合格" in r2["verdict"]

# ------------------------------------------------------------------ 固高 GTS（手册级真值）

def _gts() -> dict:
    return json.loads((util.KNOWLEDGE_DIR / "sdks" / "gts.json").read_text(encoding="utf-8"))


def _gts_index() -> dict[str, int]:
    """官方手册第 14 章《指令索引》的全部 167 条指令 → 手册页码。

    这是固高侧唯一的「外部真值」：绑定里出现的每个函数都必须能在这张表里找到，
    找不到 = 手册里压根没这个函数 = 真机 EntryPointNotFound。
    """
    import csv
    p = util.KNOWLEDGE_DIR / "sdks" / "official_api" / "gts_manual_index.csv"
    rows = list(csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()))
    return {r["函数名"]: int(r["手册页码"]) for r in rows}


def test_固高手册指令索引必须完整():
    import csv
    idx = _gts_index()
    assert len(idx) == 167, f"固高 GTS 单卡库指令应为 167 条，实得 {len(idx)}"
    protos = list(csv.DictReader(
        (util.KNOWLEDGE_DIR / "sdks" / "official_api" / "gts_prototypes.csv")
        .read_text(encoding="utf-8-sig").splitlines()))
    for r in protos:
        assert r["函数名"] in idx, f"{r['函数名']} 不在手册指令索引里"
        assert r["PDF页码"].strip(), f"{r['函数名']} 缺 PDF 页码（结论必须可回查）"


def test_固高每条PInvoke必须能在官方手册指令索引里找到():
    idx = _gts_index()
    for f in _gts()["pinvoke"]:
        assert f["fn"] in idx, (
            f"固高 {f['fn']} 不在官方手册的 167 条指令索引里 —— "
            "手册里没有这个函数，真机必然 EntryPointNotFound")


def test_固高不得绑定手册里不存在的当量函数():
    """固高**没有** SetPulsePerMm / GetPulsePerMm。

    当量是 GT_ProfileScale(axis, alpha, beta) 的分数比，而手册没给变换公式与
    alpha/beta 方向 —— 谁要是「按脉冲当量猜一个 alpha/beta 调下去」，
    位置会整体偏一个未知比例且不报错。所以这两条不许出现在绑定里。
    """
    idx = _gts_index()
    bound = {f["fn"] for f in _gts()["pinvoke"]}
    for fake in ("GT_SetPulsePerMm", "GT_GetPulsePerMm"):
        assert fake not in idx, f"{fake} 其实存在于手册里，请重新核对结论"
        assert fake not in bound, f"固高 {fake} 是不存在的函数，绑上去真机直接崩"


def test_固高PInvoke参数个数必须与手册原型一致():
    """参数个数对不上 = 栈错位。手册 PDF 的原型是硬证据。"""
    def arg_count(proto: str) -> int:
        inner = proto[proto.index("(") + 1: proto.rindex(")")]
        return 0 if not inner.strip() else len(inner.split(","))

    for f in _gts()["pinvoke"]:
        assert "proto" in f and "page" in f, f"{f['fn']} 缺 proto / page（无法回查手册）"
        n_mine = len(f.get("args", []))
        n_doc = arg_count(f["proto"])
        assert n_mine == n_doc, f"{f['fn']} 本仓库 {n_mine} 参，手册原型 {n_doc} 参：{f['proto']}"


def test_固高结构体字段必须与手册布局逐字一致():
    """THomePrm 的 pad 数组有实际含义（pad1[0]、pad2[1]），顺序错了回零行为就变了。"""
    code = adapter_gen.render_adapter({**_gts(), "sdk_file": "gts.json"})
    expect = [
        "public double acc;", "public double dec;", "public double velStart;", "public short smoothTime;",
        "public short mode;", "public short moveDir;", "public short indexDir;", "public short edge;",
        "public double velHigh;", "public double velLow;",
        "public int homeOffset;", "public int searchHomeDistance;",
        "public int searchIndexDistance;", "public int escapeStep;",
    ]
    for line in expect:
        assert line in code, f"固高结构体缺字段 {line}（与手册 PDF p222/p227/p204 逐字不一致）"
    # 顺序也要对：acc 在 velStart 前面，velStart 在 smoothTime 前面
    assert code.index("public double velStart;") < code.index("public short smoothTime;")
    assert code.index("public double velHigh;") < code.index("public double velLow;")
    assert code.index("public int homeOffset;") < code.index("public int searchHomeDistance;")


def test_固高轴号必须做1基换算():
    """手册的 axis / profile 参数全是 1 基正整数，适配器对外是 0 基 → 内部必须 +1。"""
    code = adapter_gen.render_adapter({**_gts(), "sdk_file": "gts.json"})
    assert "(short)(axis + 1)" in code, "固高适配器没有做轴号 1 基换算"
    # 位掩码同样是 bit0=轴1
    assert "1 << axis" in code, "固高点动/停止的轴掩码没有按 bit0=轴1 构造"


def test_固高速度单位必须按pulse每毫秒换算():
    """固高速度单位是 pulse/ms（不是 pulse/s）。差 1000 倍且不报错。"""
    code = adapter_gen.render_adapter({**_gts(), "sdk_file": "gts.json"})
    assert "mmPerSec * ppm / 1000.0" in code, "固高速度换算没有除以 1000（pulse/ms）"
    assert "mmPerSec2 * ppm / 1000000.0" in code, "固高加速度换算没有除以 1e6（pulse/ms²）"


def test_固高停止原因码必须声明是本工具自定义():
    """固高没有厂商停止原因码 —— 把自定义编码说成厂商码就是在骗现场。"""
    notes = "\n".join(_gts()["notes"])
    assert "没有厂商停止原因码" in notes, "固高 notes 必须写明「没有厂商停止原因码」"
    assert "自定义" in notes, "固高 notes 必须写明停止原因是本工具自定义编码"
    code = adapter_gen.render_adapter({**_gts(), "sdk_file": "gts.json"})
    assert "本工具按状态字位推导的自定义编码" in code, "生成的代码里没有标出停止原因是自定义编码"


def test_固高不得下发当量变换指令():
    """手册没给 alpha/beta 的变换公式与方向 → 谁调谁错，且不报错。"""
    code = adapter_gen.render_adapter({**_gts(), "sdk_file": "gts.json"})
    assert "Native.GT_ProfileScale" not in code, "固高适配器不允许下发 GT_ProfileScale（当量公式未确认）"
    assert "Native.GT_EncScale" not in code, "固高适配器不允许下发 GT_EncScale（当量公式未确认）"


def test_固高IO必须按类型位图映射且端口越界要抛异常():
    """固高 IO 是「类型 + 位图」模型，通用口只有 1~16。"""
    code = adapter_gen.render_adapter({**_gts(), "sdk_file": "gts.json"})
    assert "DiTypeGpi = 4" in code and "DoTypeGpo = 12" in code, "固高 IO 类型常量缺失"
    assert "port < 1 || port > 16" in code, "固高通用口 1~16 的越界校验缺失"


def test_固高未实现的能力必须显式失败():
    """插补的坐标系映射是站点配置，猜错会让轴走到错误坐标 → 必须显式抛异常。"""
    code = adapter_gen.render_adapter({**_gts(), "sdk_file": "gts.json"})
    for op in ("MoveLinear", "MoveArc"):
        seg = code[code.index(f"public void {op}("):]
        seg = seg[:seg.index("\n        }")]
        assert "NotSupportedException" in seg, f"固高 {op} 必须显式抛 NotSupportedException"


def test_固高回零方向未配置时必须抛异常():
    """方向猜错 = 朝机构外跑。没有安全默认方向。"""
    gts = _gts()
    assert any("HomeDirection" in l for l in gts["bodies"]["Home"]), "固高 Home 必须显式检查 HomeDirection"
    code = adapter_gen.render_adapter({**gts, "sdk_file": "gts.json"})
    assert "GtsHomeDir.Unconfigured" in code, "固高回零方向未配置时必须抛异常"


def test_固高已进能力矩阵且从待录入清单移除():
    data = json.loads((util.KNOWLEDGE_DIR / "cards.json").read_text(encoding="utf-8"))
    brands = [c["brand"] for c in data["cards"]]
    assert "固高" in brands, "固高未进能力矩阵"
    assert "固高" not in [p["brand"] for p in data["pending_brands"]], "固高还在待录入清单里"
    g = next(c for c in data["cards"] if c["brand"] == "固高")
    assert g["form_factor"] == "plug_in_card"
    assert "gts.dll" in g["interface"]
    assert "pulse/ms" in g["velocity_unit"], "固高速度单位必须写成 pulse/ms（不是 pulse/s）"
    # 跨品牌差异表必须三家都有列
    for d in data["cross_brand_diffs"]:
        assert d.get("googol"), f"跨品牌差异「{d['topic']}」缺固高那一列"
    # 固高必须有向厂商确认的条目（调用约定 / 当量公式 / 现场型号）
    items = [m for m in data["pending_manual_items"] if m["brand"] == "固高"]
    assert len(items) >= 3, "固高的厂商待确认项不足"
    blob = " ".join(m["item"] + m["why"] + m.get("ask", "") for m in items)
    assert "当量" in blob, "固高仍要问当量变换公式（手册没给）"
    # 已经从官方 SDK / 手册查到的东西不能再问厂商（问了显得我们没看资料）
    for done in ("gts.cs", "调用约定", "端子表"):
        assert done not in blob, f"「{done}」已经在官方 SDK / 手册里查到了，不能再列为待确认项"


def _official_hdr(vendor: str) -> dict[str, str]:
    """官方 C 头文件导出的真值（gts_hdr.csv）：函数名 → C 原型。"""
    import csv
    p = util.KNOWLEDGE_DIR / "sdks" / "official_api" / f"{vendor}_hdr.csv"
    rows = list(csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()))
    return {r["函数名"]: r["官方原型"] for r in rows}


def _official_structs(vendor: str) -> dict:
    """官方 C# 绑定的结构体布局真值（gts_structs.csv）：结构体 → [(字段名, 类型, 偏移)]、总字节。"""
    import csv
    p = util.KNOWLEDGE_DIR / "sdks" / "official_api" / f"{vendor}_structs.csv"
    rows = list(csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()))
    out = {}
    for r in rows:
        out.setdefault(r["结构体"], {"fields": [], "size": int(r["结构体总字节"])})
        out[r["结构体"]]["fields"].append((r["字段名"], r["类型"], int(r["字节偏移"])))
    return out


def _cs_layout(fields):
    """C# struct 默认 Sequential 布局的 [(字段名, 类型, 偏移)] 与总字节（独立于导出脚本再算一遍）。"""
    size_map = {"short": 2, "int": 4, "double": 8, "byte": 1, "long": 8, "float": 4}
    off, align, out = 0, 1, []
    for typ, name in fields:
        a = size_map.get(typ, 8)
        align = max(align, a)
        off = (off + a - 1) // a * a
        out.append((name, typ, off))
        off += a
    return out, (off + align - 1) // align * align


# 官方 C# 绑定 → 本仓绑定的**已论证差异**（不在此表里的任何差异一律红）
# 每条都要写清「为什么 ABI 仍然安全」；差异没登记 = 没人论证过 = 可能就是栈错位
GTS_SIG_DIFFS = {
    ("GT_GetSts", 3): "官方 out uint pClock（4 字节指针，C 原型默认 NULL）→ 本仓 IntPtr 传 IntPtr.Zero，等价于不读控制器时钟",
    ("GT_GetPrfMode", 3): "同上",
    ("GT_GetPrfPos", 3): "同上",
    ("GT_GetAxisPrfPos", 3): "同上",
    ("GT_GetAxisEncPos", 3): "同上",
    ("GT_GetAxisError", 3): "同上",
    ("GT_GetCaptureStatus", 4): "同上",
    ("GT_CompareData", 5): "官方 int[] pBuf1（CLR 每次调用要拷贝整条曲线）→ 本仓 IntPtr 指向适配器持有的原生缓冲（int 4 字节，与 C 原型 long* 一致）",
    ("GT_CompareData", 7): "官方 int[] pBuf2 → 同上",
    ("GT_GetVersion", 0): "官方 out string pVersion（CLR 托管字符串）→ 本仓 ref IntPtr + Marshal.PtrToStringAnsi（厂商返回的是控制器内部字符串，不能 free）",
}


def _split_official_args(proto: str):
    """官方 C# 原型 'GT_x(类型 参数, ref 类型 参数)' → [(类型, 是否 by-ref)]。"""
    inner = proto[proto.index("(") + 1: proto.rindex(")")]
    if not inner.strip():
        return []
    out = []
    for a in inner.split(","):
        a = a.strip()
        byref = a.startswith(("ref ", "out "))
        if byref:
            a = a.split(None, 1)[1].strip()
        parts = a.split()
        typ = " ".join(parts[:-1]) if len(parts) > 1 else parts[0]
        out.append((typ, byref))
    return out


def test_固高GEN的GTN函数不在GTS的SDK包里():
    """官方 SDK 包到手后的定论：**GTN_ 一个都没有**。

    证据（全部来自固高官网 SDK 包，2026-10-20 取得）：
    官方 gts.h 535 条声明、官方 gts.cs 473 条声明、4 个 SDK 的 gts.dll（各 782 个导出）、
    MCT2008 工具目录的 gts.dll（569 个导出）—— 没有任何一个 GTN_ 符号。
    GEN 是独立产品线（自带《GEN 系列运动控制器用户手册》《GEN 系列运动控制器编程手册之基本功能》
    《GEN 扩展功能》），它例程里的 `#include "gts.h"` 只是**同名文件**，不能当共用 DLL 的证据。

    教训还是那句「前缀不同 ≠ 库不同」—— 但这次不是靠前缀猜，是靠导出表数出来的。
    """
    official = _official_api("gts")
    assert not [n for n in official if n.startswith("GTN_")], "官方 gts.cs 里不该有 GTN_（GTN_ 属于 GEN 自己的 SDK）"
    hdr = _official_hdr("gts")
    assert not [n for n in hdr if n.startswith("GTN_")], "官方 gts.h 里不该有 GTN_"
    exports = _dll_exports()
    gts_syms = [n for (d, _, _, n) in exports if d == "gts.dll"]
    assert gts_syms, "gts.dll 的导出表真值缺失"
    assert not [n for n in gts_syms if n.startswith("GTN_")], "gts.dll 导出表里不该有 GTN_"
    notes = "\n".join(_gts()["notes"])
    assert "GTN_" in notes and "SDK 包" in notes, "固高 notes 必须写明 GEN 的 GTN_ 不在这个 SDK 包里"


def test_固高绑定必须与官方CSharp绑定逐条一致():
    """34 条绑定逐条对官方 gts.cs：函数名、DLL、参数个数、by-ref 修饰、类型。

    gts.cs 是厂商发给 C# 用户的官方绑定 —— 我们写的 P/Invoke 必须与它 ABI 等价，
    否则不是栈错位就是按错结构体。**允许有差异，但差异必须逐条论证并登记在
    GTS_SIG_DIFFS 里**（没登记的差异一律红）。
    """
    gts = _gts()
    official = _official_proto("gts")
    dlls = _official_api("gts")
    assert len(official) >= 470, f"官方 gts.cs 的函数数异常：{len(official)}"
    for f in gts["pinvoke"]:
        assert f["verified"] == "official-binding", \
            f"{f['fn']} 应标成 official-binding（官方 gts.cs 已取得并逐条核对过）"
        assert f["fn"] in official, f"{f['fn']} 不在官方 gts.cs 里 —— 真机会 EntryPointNotFound"
        assert dlls[f["fn"]].lower() == gts["dll"].lower(), f"{f['fn']} 的 DLL 名与官方不一致"
        mine = f.get("args", [])
        off = _split_official_args(official[f["fn"]])
        assert len(mine) == len(off), \
            f"{f['fn']} 本仓 {len(mine)} 参，官方 {len(off)} 参：{official[f['fn']]}"
        for idx, (m, o) in enumerate(zip(mine, off)):
            o_type, o_ref = o
            m_type, m_ref = m["type"], bool(m.get("is_ref"))
            if (f["fn"], idx) in GTS_SIG_DIFFS:
                assert GTS_SIG_DIFFS[(f["fn"], idx)], \
                    f"{f['fn']} 第 {idx + 1} 参的差异必须写清为什么 ABI 仍然安全"
                continue
            assert o_ref == m_ref, \
                f"{f['fn']} 第 {idx + 1} 参的 ref/out 修饰与官方不一致：官方 {official[f['fn']]}"
            same = (m_type == o_type) or (m_type.startswith("Gts") and o_type == "T" + m_type[3:])
            assert same, \
                f"{f['fn']} 第 {idx + 1} 参类型 {m_type} 与官方 {o_type} 不一致（未登记的差异）"


def test_固高绑定函数名必须与官方C头文件一致且参数个数相同():
    """官方 gts.h 是 C 侧真值：函数名 + C 原型的参数个数。"""
    hdr = _official_hdr("gts")
    assert len(hdr) >= 500, f"官方 gts.h 的声明数异常：{len(hdr)}"
    for f in _gts()["pinvoke"]:
        assert f["fn"] in hdr, f"{f['fn']} 不在官方 gts.h 里 —— 真机会 EntryPointNotFound"
        inner = hdr[f["fn"]][hdr[f["fn"]].index("(") + 1:hdr[f["fn"]].rindex(")")]
        n_off = 0 if not inner.strip() or inner.strip() == "void" else len(inner.split(","))
        assert len(f.get("args", [])) == n_off, \
            f"{f['fn']} 本仓 {len(f.get('args', []))} 参，官方 gts.h 原型 {n_off} 参：{hdr[f['fn']]}"


def test_固高结构体必须与官方CSharp绑定同布局():
    """GtsTrapPrm / GtsJogPrm / GtsHomePrm 的字段个数、类型、字节偏移、总长度
    必须与官方 gts.cs 的 TTrapPrm / TJogPrm / THomePrm 一致。

    这条是本轮抓到的真 bug 的守门员：原来 GtsHomePrm 只有 22 个字段（80 字节），
    官方 THomePrm 是 23 个字段（88 字节）—— GT_GetHomePrm 会把 88 字节写进我们
    80 字节的结构体 = **内存越界写**。
    """
    import re as _re
    off = _official_structs("gts")
    code = adapter_gen.render_adapter({**_gts(), "sdk_file": "gts.json"})
    for mine_name, off_name in (("GtsTrapPrm", "TTrapPrm"), ("GtsJogPrm", "TJogPrm"),
                                ("GtsHomePrm", "THomePrm")):
        m = _re.search(r"public struct " + mine_name + r"\s*\{(.*?)\n\s*\}", code, _re.S)
        assert m, f"生成的代码里没有 {mine_name}"
        fields = [(fm.group(1), fm.group(2))
                  for fm in _re.finditer(r"public\s+([\w\[\]]+)\s+(\w+)\s*;", m.group(1))]
        lay, size = _cs_layout(fields)
        exp = off[off_name]["fields"]
        assert len(lay) == len(exp), (
            f"{mine_name} 有 {len(lay)} 个字段，官方 {off_name} 有 {len(exp)} 个 —— "
            f"结构体大小不一致（官方 {off[off_name]['size']} 字节），GT_*Prm 的读回就是越界写")
        assert size == off[off_name]["size"], \
            f"{mine_name} 总字节 {size} ≠ 官方 {off_name} {off[off_name]['size']}"
        for (mn, mt, mo), (on, ot, oo) in zip(lay, exp):
            assert mt == ot, f"{mine_name} 偏移 {mo} 处类型 {mt} ≠ 官方 {off_name}.{on} {ot}"
            assert mo == oo, f"{mine_name}.{mn} 偏移 {mo} ≠ 官方 {off_name}.{on} {oo}"


def test_固高枚举值必须与官方头文件宏一致():
    """IO 类型、捕获源、回零模式的数值必须等于官方 gts.h 里的宏。

    官方 gts.h 头部 200 个 #define 就是这些常量的真值（MC_GPI=4、CAPTURE_PROBE=3、
    HOME_MODE_LIMIT=10 …）。枚举值写错 = 读写错误的 IO 位图或用错回零模式，而且不报错。
    """
    import csv
    import re as _re
    p = util.KNOWLEDGE_DIR / "sdks" / "official_api" / "gts_hdr_macros.csv"
    macros = {r["宏名"]: r["值"] for r in csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines())}
    # 调用约定也从同一条证据来：#define GT_API extern "C" short __stdcall
    assert "stdcall" in macros.get("GT_API", ""), \
        f"官方 gts.h 的 GT_API 宏应含 stdcall，实际 {macros.get('GT_API')!r}"
    assert _gts()["calling_convention"] == "StdCall", "固高调用约定应与官方 gts.h 的 GT_API 宏一致"
    code = adapter_gen.render_adapter({**_gts(), "sdk_file": "gts.json"})
    mapping = {
        "GtsHomeMode.Limit": "HOME_MODE_LIMIT", "GtsHomeMode.LimitHome": "HOME_MODE_LIMIT_HOME",
        "GtsHomeMode.LimitIndex": "HOME_MODE_LIMIT_INDEX", "GtsHomeMode.LimitHomeIndex": "HOME_MODE_LIMIT_HOME_INDEX",
        "GtsHomeMode.Home": "HOME_MODE_HOME", "GtsHomeMode.HomeIndex": "HOME_MODE_HOME_INDEX",
        "GtsHomeMode.Index": "HOME_MODE_INDEX", "GtsHomeMode.ForcedHome": "HOME_MODE_FORCED_HOME",
        "GtsHomeMode.ForcedHomeIndex": "HOME_MODE_FORCED_HOME_INDEX",
        "GtsCaptureMode.Home": "CAPTURE_HOME", "GtsCaptureMode.Index": "CAPTURE_INDEX",
        "GtsCaptureMode.Probe": "CAPTURE_PROBE", "GtsCaptureMode.Hsio0": "CAPTURE_HSIO0",
        "GtsCaptureMode.Hsio1": "CAPTURE_HSIO1",
    }
    for member, macro in mapping.items():
        enum, name = member.split(".")
        m = _re.search(r"public enum " + enum + r"[^\{]*\{(.*?)\}", code, _re.S)
        assert m, f"生成的代码里没有枚举 {enum}"
        mm = _re.search(r"\b" + name + r"\s*=\s*(-?\d+)", m.group(1))
        assert mm, f"枚举 {enum} 里找不到成员 {name}"
        assert macros.get(macro) is not None, f"官方 gts.h 里没有宏 {macro}"
        assert int(mm.group(1)) == int(macros[macro]), \
            f"{member} = {mm.group(1)}，官方宏 {macro} = {macros[macro]}"
    # IO 类型常量
    assert f"DiTypeGpi = {macros['MC_GPI']}" in code, "DiTypeGpi 必须等于官方 MC_GPI"
    assert f"DoTypeGpo = {macros['MC_GPO']}" in code, "DoTypeGpo 必须等于官方 MC_GPO"


def test_固高IO端子表必须与官方手册一致():
    """端子表是从《GTS-400-PCIe 用户手册 R1.0》第 3 章抄出来的 121 行 —— 现场接线全靠它。

    这里钉住几个关键事实：16 路通用输入/输出、4 轴原点、8 对限位、位置比较只有 2 个
    差分通道、EXI0 兼作探针、辅助编码器不能用捕获。
    """
    import csv
    p = util.KNOWLEDGE_DIR / "sdks" / "official_api" / "gts_io_terminals.csv"
    rows = list(csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()))
    assert len(rows) >= 120, f"端子表行数异常：{len(rows)}"
    sig = [r["信号"] for r in rows]
    for i in range(16):
        assert f"EXI{i}" in sig, f"端子表缺通用输入 EXI{i}"
        assert f"EXO{i}" in sig, f"端子表缺通用输出 EXO{i}"
    for i in range(4):
        assert f"HOME{i}" in sig, f"端子表缺原点输入 HOME{i}"
        assert f"LIMIT{i}+" in sig and f"LIMIT{i}-" in sig, f"端子表缺 {i+1} 轴正负限位"
    assert "HSIO_A+" in sig and "HSIO_B+" in sig, "端子表缺位置比较输出通道"
    assert not [s for s in sig if s.startswith("HSIO_C")], "位置比较只有 2 个通道"
    probe = [r for r in rows if r["信号"] == "EXI0"]
    assert probe and "探针" in probe[0]["说明"], "EXI0 必须标注兼作探针输入"
    notes = "\n".join(_gts()["notes"])
    assert "EXI0" in notes, "固高 notes 必须写明探针接 EXI0（现场接线要用）"


def test_固高必须警告不要拷MCT2008目录的gts_dll():
    """SDK 包里有 5 个 gts.dll：4 个 SDK 的（导出表相同，各 782 个）+
    03_Demo工具_MCT2008/ 里那份旧的（只有 569 个导出，少 214 个）。
    拷错不会立刻崩，但会缺一整套功能 —— 所以 notes 里必须写明。"""
    exports = _dll_exports()
    variants = {v for (d, _, v, _) in exports if d == "gts.dll"}
    assert {"64bit_single_card", "32bit_single_card", "MCT2008工具"} <= variants, \
        f"gts.dll 的变体真值不全：{variants}"
    sdk_syms = {n for (d, b, v, n), val in exports.items()
                if d == "gts.dll" and v == "64bit_single_card" and val == 1}
    mct_syms = {n for (d, b, v, n), val in exports.items()
                if d == "gts.dll" and v == "MCT2008工具" and val == 1}
    assert len(sdk_syms) == 782, f"SDK 版 gts.dll 导出数异常：{len(sdk_syms)}"
    assert len(mct_syms) == 569, f"MCT2008 版 gts.dll 导出数异常：{len(mct_syms)}"
    missing = sdk_syms - mct_syms
    assert len(missing) == 214, f"MCT2008 那份少导出 {len(missing)} 个（与实测 214 不符）"
    notes = "\n".join(_gts()["notes"])
    assert "MCT2008" in notes, "固高 notes 必须写明 MCT2008 目录里的 gts.dll 不能拷"


def test_固高官方绑定里声明但DLL没导出的函数不得被绑定():
    """GT_GantryHoming：官方 gts.cs 声明了，随包 gts.dll 的导出表里却没有 → 照抄官方绑定就会崩。

    这类「官方件声明了、DLL 却导不出」的函数，单看官方 C# 绑定或官方 C 头文件都发现不了
    （正运动的 ZAux_Direct_GetNtype 是同一类）。所以第三层导出表真值不能省。
    """
    exports = _dll_exports()
    for var in ("64bit_single_card", "32bit_single_card"):
        bad = {n for (d, b, v, n), val in exports.items()
               if d == "gts.dll" and v == var and val == 0}
        assert "GT_GantryHoming" in bad, f"{var} 变体里 GT_GantryHoming 应被记为未导出"
    bound = {f["fn"] for f in _gts()["pinvoke"]}
    bad_all = {n for (d, b, v, n), val in exports.items() if d == "gts.dll" and val == 0}
    assert not (bound & bad_all), f"绑定了 DLL 导不出的函数：{sorted(bound & bad_all)}"


def test_固高绑定必须与官方绑定一致且不再有needs_manual_check():
    """gts.cs 已到手 → 34 条绑定全部升级为 official-binding，能力矩阵的待核对清零。"""
    gts = _gts()
    for f in gts["pinvoke"]:
        assert f["verified"] == "official-binding", \
            f"{f['fn']} 不该再标成 needs-manual-check（官方 gts.cs 已取得）"
    assert gts["dll"] == "gts.dll", "固高库名必须是 gts.dll（手册 PDF p15 原文）"
    assert gts["calling_convention"] == "StdCall"
    assert gts.get("dll_variant") == "64bit_single_card", "固高必须写明本仓绑定的是哪个 gts.dll 变体"

# ------------------------------------------------------------------ 雷赛 DMC（手册级真值）

def _dmc() -> dict:
    return json.loads((util.KNOWLEDGE_DIR / "sdks" / "dmc.json").read_text(encoding="utf-8"))


def _leisai_cpp() -> dict[str, str]:
    """官方 C 头文件导出的真值（leisai_cpp.csv）：函数名 → C 原型（含真实返回类型）。"""
    import csv
    p = util.KNOWLEDGE_DIR / "sdks" / "official_api" / "leisai_cpp.csv"
    rows = list(csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()))
    return {r["函数名"]: r["官方原型"] for r in rows}


# 官方 C# 绑定里的 .NET 类型名 → 本仓 P/Invoke 用的类型
_LEISAI_TYPE = {"UInt16": "ushort", "UInt32": "uint", "Int32": "int", "Int16": "short",
                "Double": "double", "Single": "float", "Byte": "byte", "String": "string",
                "Boolean": "bool"}


def test_雷赛绑定必须与官方CSharp绑定逐条一致():
    """37 条绑定逐条对官方 LTDMC.cs：函数名、DLL、参数个数、by-ref 修饰、参数类型。

    官方 LTDMC.cs 是厂商发给 C# 用户的官方绑定 —— P/Invoke 必须与它 ABI 等价。
    官方绑定里**有 3 个函数名带重载**（同名两个原型）→ 命中**任一原型**即可。
    """
    dmc = _dmc()
    official = _official_protos("leisai")
    dlls = _official_api("leisai")
    assert len(official) >= 1450, f"官方 LTDMC.cs 的函数数异常：{len(official)}"
    for f in dmc["pinvoke"]:
        if f.get("skip_emit"):
            continue
        assert f["fn"] in official, f"{f['fn']} 不在官方 LTDMC.cs 里 —— 真机会 EntryPointNotFound"
        assert dlls[f["fn"]].lower() == dmc["dll"].lower(), f"{f['fn']} 的 DLL 名与官方不一致"
        mine = f.get("args", [])
        # 逐个官方原型试：命中任意一个即算一致
        matched = False
        for proto in official[f["fn"]]:
            off = _split_official_args(proto)
            if len(mine) != len(off):
                continue
            if all(o_ref == bool(m.get("is_ref")) and m["type"] == _LEISAI_TYPE.get(o_type, o_type)
                   for m, (o_type, o_ref) in zip(mine, off)):
                matched = True
                break
        assert matched, \
            f"{f['fn']} 本仓签名与官方任一原型都不一致：{official[f['fn']]}"


def test_雷赛绑定函数名必须与官方C头文件一致且参数个数相同():
    """官方 LTDMC.h 是 C 侧真值：函数名 + 参数个数（`void` 不算参数）。"""
    cpp = _leisai_cpp()
    assert len(cpp) >= 1500, f"官方 LTDMC.h 的声明数异常：{len(cpp)}"

    def c_arg_count(proto: str) -> int:
        inner = proto[proto.index("(") + 1: proto.rindex(")")]
        if inner.strip() in ("", "void"):
            return 0
        return _arg_count(proto)

    for f in _dmc()["pinvoke"]:
        if f.get("skip_emit"):
            continue
        assert f["fn"] in cpp, f"{f['fn']} 不在官方 LTDMC.h 里"
        assert len(f.get("args", [])) == c_arg_count(cpp[f["fn"]]), \
            f"{f['fn']} 本仓 {len(f.get('args', []))} 参，C 头文件 {c_arg_count(cpp[f['fn']])} 参：{cpp[f['fn']]}"


def test_雷赛C头文件真值必须保留真实返回类型():
    """leisai_cpp.csv 曾把所有原型都写成 `short` —— 那是「真值文件自己撒谎」。

    官方 LTDMC.h 里返回类型是 long(15) / DWORD(11) / double(2) / short(1485)，
    写错的话，跨语言调用会按错的宽度读返回值。
    """
    cpp = _leisai_cpp()
    rets = {}
    for proto in cpp.values():
        rets[proto.split()[0]] = rets.get(proto.split()[0], 0) + 1
    assert rets.get("short", 0) > 1400, f"short 原型数异常：{rets}"
    assert rets.get("long", 0) == 15, f"long 原型数应�� 15：{rets}"
    assert rets.get("DWORD", 0) == 11, f"DWORD 原型数应为 11：{rets}"
    assert rets.get("double", 0) == 2, f"double 原型数应为 2：{rets}"
    assert cpp["dmc_read_inport"].startswith("DWORD "), "dmc_read_inport 返回 DWORD，不是 short"
    assert cpp["dmc_get_latch_value"].startswith("long "), "dmc_get_latch_value 返回 long，不是 short"


def test_雷赛不得使用厂商标注内部保留的函数():
    """官方 LTDMC.cs 把 dmc_get_sevon_enable / dmc_set_sevon_enable 标在「//内部使用（保留）」下。

    返回值语义未公开 → 拿来判断伺服使能状态就是在猜（猜错 = 安全信号反了）。
    """
    bound = {f["fn"] for f in _dmc()["pinvoke"]}
    for forbidden in ("dmc_get_sevon_enable", "dmc_set_sevon_enable"):
        assert forbidden not in bound, f"{forbidden} 是厂商标注「内部使用（保留）」的函数，不得绑定"
    notes = "\n".join(_dmc()["notes"])
    assert "内部使用（保留）" in notes, "雷赛 notes 必须写明哪些函数是厂商保留函数"


def test_雷赛伺服使能状态必须用手册语义的SEVON电平():
    """手册 8.13：dmc_read_sevon_pin 返回**端子电平 0/1**（不是错误码），按**轴号**读写。

    SEVON 有效电平取决于驱动器接法 → 必须显式可配（ServoOnActiveLevel），不许写死。
    """
    dmc = _dmc()
    code = adapter_gen.render_adapter(dmc)
    assert "dmc_read_sevon_pin" in code, "IsEnabled 必须用 dmc_read_sevon_pin 读 SEVON 端子电平"
    assert "ServoOnActiveLevel" in code, "SEVON 有效电平必须显式可配（驱动器接法常闭/常开会反）"
    assert "dmc_read_sevon_pin" in dmc["bodies"]["IsEnabled"][2] or \
        any("dmc_read_sevon_pin" in l for l in dmc["bodies"]["IsEnabled"]), \
        "IsEnabled 必须调用 dmc_read_sevon_pin"
    assert "ServoOnActiveLevel" in "\n".join(dmc["helpers"]["LeisaiHardwareConfig"]), \
        "ServoOnActiveLevel 必须落在硬件配置里"


def test_雷赛轴状态不得调用总线轴状态机():
    """脉冲卡（DMC3000 系列）**没有**轴状态机函数。

    官方绑定里唯一的 nmc_get_axis_state_machine 是 EtherCAT 总线轴专用，
    脉冲卡上调用只会失败或给出总线轴语义 → GetState 必须用 8.7 的 dmc_axis_io_status 位图。
    """
    dmc = _dmc()
    code = adapter_gen.render_adapter(dmc)
    assert "dmc_axis_io_status" in code, "雷赛 GetState 必须用 dmc_axis_io_status（手册 8.7 表 8.2）"
    assert "Native.nmc_get_axis_state_machine" not in code, \
        "雷赛适配器不得调用总线轴专用的 nmc_get_axis_state_machine（脉冲卡没有轴状态机）"
    f = next(x for x in dmc["pinvoke"] if x["fn"] == "nmc_get_axis_state_machine")
    assert f.get("skip_emit") is True, "nmc_get_axis_state_machine 不得生成 P/Invoke（总线轴专用）"
    notes = "\n".join(dmc["notes"])
    assert "没有轴状态机函数" in notes, "雷赛 notes 必须写明脉冲卡没有轴状态机函数"


def test_雷赛保留参数必须传0():
    """手册 8.17：ltc_mode / filter / triger_chunnel 全是保留参数，固定值 0。

    all_enable 的合法值只有 0 单次 / 2 连续 / 3 触发延时急停（1 是保留值）。
    """
    dmc = _dmc()
    code = adapter_gen.render_adapter(dmc)
    assert "dmc_set_ltc_mode(card, (ushort)axis, (ushort)LatchLogic, 0, 0)" in code, \
        "ltc_mode / filter 是保留参数，必须传 0"
    assert "dmc_set_latch_mode(card, (ushort)axis, (ushort)LatchMode, (ushort)LatchSource, 0)" in code, \
        "triger_chunnel 是保留参数，必须传 0"
    assert "LatchFilterS" not in code, "LatchFilterS 对应保留参数，配了也不生效 → 死配置必须删"
    assert "LatchMode" in code, "锁存方式必须显式可配（0 单次 / 2 连续 / 3 触发延时急停）"


def test_雷赛IO位图真值必须与手册表8_3一致():
    """手册 8.14 表 8.3：bit14 = IN14/LTC0、bit15 = IN15/LTC1（不是 IN4~IN7）。"""
    import csv
    p = util.KNOWLEDGE_DIR / "sdks" / "official_api" / "leisai_io_bits.csv"
    rows = list(csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()))
    assert len(rows) == 64, f"IO 位图应为 2 组 × 32 位 = 64 行，实得 {len(rows)}"
    g0 = {int(r["位"]): r["名称"] for r in rows if r["IO组"] == "0"}
    g1 = {int(r["位"]): r["名称"] for r in rows if r["IO组"] == "1"}
    assert g0[14] == "IN14/LTC0", f"bit14 必须是 IN14/LTC0，实得 {g0[14]}"
    assert g0[15] == "IN15/LTC1", f"bit15 必须是 IN15/LTC1，实得 {g0[15]}"
    assert g0[0] == "IN0" and g0[16] == "EL0+" and g0[24] == "EL0-"
    assert g1[0] == "ORG0" and g1[8] == "ALM0" and g1[16] == "RDY0" and g1[24] == "INP0"


def test_雷赛接线盒端子表必须与手册附录一致():
    """手册 附录 1（ACC-X400）：CN1~CN4 第 3 脚 = SEVON，CN19 第 15 脚 = IN14/LTC0。"""
    import csv
    p = util.KNOWLEDGE_DIR / "sdks" / "official_api" / "leisai_io_terminals.csv"
    rows = list(csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()))
    assert len(rows) == 88, f"ACC-X400 端子表应为 88 行，实得 {len(rows)}"
    idx = {(r["连接器"], int(r["引脚"])): r["信号"] for r in rows}
    assert idx[("CN1~CN4", 3)] == "SEVON", "CN1~CN4 第 3 脚必须是 SEVON（伺服使能）"
    assert idx[("CN1~CN4", 12)] == "RDY" and idx[("CN1~CN4", 16)] == "INP"
    assert idx[("CN19", 15)] == "IN14/LTC0", "CN19 第 15 脚必须是 IN14/LTC0"
    assert idx[("CN19", 16)] == "IN15/LTC1"
    assert idx[("CN21", 15)] == "OUT14" and idx[("CN21", 16)] == "OUT15"
    assert idx[("CN23", 1)] == "PWM0" and idx[("CN23", 3)] == "PWM1"


def test_雷赛卡与接线盒配套表必须与手册1_4一致():
    """手册 1.4 订货信息 表 1.2~1.11：10 款卡 ↔ 接线盒。"""
    import csv
    p = util.KNOWLEDGE_DIR / "sdks" / "official_api" / "leisai_model_kits.csv"
    rows = list(csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()))
    assert len(rows) == 10, f"配套表应为 10 行，实得 {len(rows)}"
    kits = {r["运动控制卡型号"]: r["配套接线盒"] for r in rows}
    assert kits["DMC3400A"] == "ACC-X400B", "DMC3400A 配套 ACC-X400B（表 1.4）"
    assert kits["DMC3C00S-F"] == "ACC2-XC00 + ACC2-X400B", "DMC3C00S-F 配两个接线盒（表 1.3）"
    assert kits["DMC3800"] == "ACC3800"


def test_雷赛notes必须写明端子表与配套表手册自带():
    """手册附录 1~10 有 10 款接线盒端子表、1.4 有配套表 → 不能再列为「要问厂商」。"""
    notes = "\n".join(_dmc()["notes"])
    assert "附录 1~10" in notes, "雷赛 notes 必须写明手册附录 1~10 自带十款接线盒端子表"
    assert "订货信息" in notes, "雷赛 notes 必须写明 1.4 订货信息自带卡↔接线盒配套表"
    assert "三套同名 LTDMC 库" in notes or "三套" in notes, \
        "雷赛 notes 必须写明存在三套同名 LTDMC 库，部署时不能混版本"


def test_雷赛调用约定必须是StdCall():
    """官方 LTDMC.h：`DMC_API <类型> __stdcall` → stdcall。"""
    dmc = _dmc()
    assert dmc.get("calling_convention", "StdCall") == "StdCall", "雷赛调用约定应为 StdCall"
    cpp = _leisai_cpp()
    assert cpp["dmc_read_sevon_pin"].startswith("short dmc_read_sevon_pin(WORD CardNo,WORD axis)"), \
        "官方 C 原型应与本仓绑定一致"

def _leisai_index() -> dict[str, dict]:
    """官方手册附录 11《运动控制函数索引》导出的真值。"""
    import csv
    p = util.KNOWLEDGE_DIR / "sdks" / "official_api" / "leisai_manual_index.csv"
    rows = list(csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()))
    return {r["函数名"]: r for r in rows}


def test_雷赛每条PInvoke必须在官方手册函数索引里():
    """手册附录 11 是雷赛侧的「手册级真值」：绑定里出现的每个函数都得能在索引里找到。

    找不到 = 手册里压根没这个函数 = 真机 EntryPointNotFound（或压根不是这个系列的 API）。
    """
    idx = _leisai_index()
    assert len(idx) >= 160, f"手册索引条数异常：{len(idx)}"
    missing = [f["fn"] for f in _dmc()["pinvoke"]
               if not f.get("skip_emit") and f["fn"] not in idx]
    # 这两个函数手册 8.7 正文有、但附录 11 索引漏了 —— 厂商手册的疏漏，已写进资料清单
    assert set(missing) <= {"dmc_get_stop_reason", "dmc_clear_stop_reason"}, \
        f"以下绑定不在官方手册索引里：{missing}"
    # 索引的章节必须对得上我们记录的页码
    assert idx["dmc_read_sevon_pin"]["手册章节"] == "8.13 节", "dmc_read_sevon_pin 应在 8.13 节"
    assert idx["dmc_set_ltc_mode"]["手册章节"] == "8.17 节", "dmc_set_ltc_mode 应在 8.17 节"
    assert idx["dmc_hcmp_set_mode"]["手册章节"] == "8.19 节", "dmc_hcmp_set_mode 应在 8.19 节"
    assert idx["dmc_axis_io_status"]["手册章节"] == "8.7 节", "dmc_axis_io_status 应在 8.7 节"


def test_雷赛手册索引漏掉停止原因函数必须被记录():
    """《DMC3000 手册》附录 11 的索引**漏了** dmc_get_stop_reason / dmc_clear_stop_reason。

    这两个函数在 8.7 正文里是有完整说明的（p155~156），只是索引表没列。
    记成测试是为了不丢这个事实 —— 写资料清单时顺手提给厂商，请他们补进索引。
    """
    idx = _leisai_index()
    for fn in ("dmc_get_stop_reason", "dmc_clear_stop_reason"):
        assert fn not in idx, f"{fn} 若已被补进索引，这条测试要改成「厂商已修」"
    bound = {f["fn"] for f in _dmc()["pinvoke"]}
    assert {"dmc_get_stop_reason", "dmc_clear_stop_reason"} <= bound, \
        "停止原因相关函数应已绑定"
    notes = "\n".join(_dmc()["notes"])
    assert "附录 11" in notes and "dmc_get_stop_reason" in notes, \
        "notes 应记录「手册附录 11 索引漏了 dmc_get_stop_reason / dmc_clear_stop_reason」这一事实"

# ------------------------------------------------------------------ 雷赛 总线卡 / 独立控制器（DMC-E / EMC 手册级真值）

def _leisai_csv(name: str) -> list[dict]:
    import csv
    p = util.KNOWLEDGE_DIR / "sdks" / "official_api" / name
    return list(csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()))


def test_雷赛PDO对象表真值必须存在且方向存疑被记录():
    """DMC-E 附录 3 与 EMC 附录 3 的 PDO 对象表逐行相同，共 23 个 CiA402 对象。

    其中 15 行的「PDO 映射」列与 CiA402 惯例相反（6040 控制字标 R_PDO、6041 状态字标 T_PDO…）——
    **我们不按这张表的 T/R 列写代码**，所以这个差异必须留在真值表里，不能被抹平。
    """
    rows = _leisai_csv("leisai_pdo.csv")
    assert len(rows) == 23, f"PDO 对象应为 23 个，实得 {len(rows)}"
    idx = {(r["主索引(HEX)"], r["子索引(HEX)"]): r for r in rows}
    assert idx[("6040", "00")]["对象名称"].startswith("控制字"), "6040 应是控制字"
    assert idx[("6041", "00")]["对象名称"].startswith("状态字"), "6041 应是状态字"
    assert idx[("6064", "00")]["对象名称"].startswith("实际位置"), "6064 应是实际位置"
    diff = [r for r in rows if r["是否一致"] != "是"]
    assert len(diff) == 15, f"PDO 方向与 CiA402 惯例不一致的应为 15 行，实得 {len(diff)}"
    # 走 SDO 的对象不该被标成方向不一致
    for r in rows:
        if r["手册标注的PDO映射"] == "NO":
            assert r["是否一致"] == "是", f"{r['主索引(HEX)']} 是 SDO 对象，不该有方向差异"


def test_雷赛总线卡与独立控制器的函数索引真值必须齐():
    """DMC-E 附录 4（201 条）与 EMC 附录 4（174 条）都是手册级真值。

    索引要能回答两件事：①手册写了哪些函数、属于哪一节；②**手册的拼写与官方导出名是否一致**。
    """
    dmce = _leisai_csv("leisai_dmce_index.csv")
    emc = _leisai_csv("leisai_emc_index.csv")
    assert len(dmce) >= 190, f"DMC-E 索引条数异常：{len(dmce)}"
    assert len(emc) >= 165, f"EMC 索引条数异常：{len(emc)}"
    for rows, label in ((dmce, "DMC-E"), (emc, "EMC")):
        for fn in ("dmc_set_equiv", "dmc_get_equiv", "nmc_set_axis_enable",
                   "nmc_set_axis_disable", "dmc_emg_stop"):
            assert any(r["函数名"] == fn for r in rows), f"{label} 索引里应能查到 {fn}"
    # 当量与使能函数的章节要对得上。
    # 注意：索引的「手册章节」指向**函数详解章**（DMC-E 第 9 章、EMC 第 8 章），不是第 7 章的实现章节。
    d = {r["函数名"]: r for r in dmce}
    e = {r["函数名"]: r for r in emc}
    assert "9.2" in d["dmc_set_equiv"]["手册章节"], "dmc_set_equiv 应在 DMC-E 9.2 节（脉冲当量）"
    assert "9.30" in d["nmc_set_axis_enable"]["手册章节"], "nmc_set_axis_enable 应在 DMC-E 9.30 节（总线使能）"
    assert "8.2" in e["dmc_set_equiv"]["手册章节"], "dmc_set_equiv 应在 EMC 8.2 节（脉冲当量）"
    assert "8.30" in e["nmc_set_axis_enable"]["手册章节"], "nmc_set_axis_enable 应在 EMC 8.30 节（总线使能）"


def test_雷赛EMC手册的函数名笔误必须被识别并记录():
    """EMC 手册把 `dmc_emg_stop` 写成 `dmc_EMG_stop`、`dmc_axis_io_status` 写成 `dmc_axis_IO_status`。

    **PE 导出名大小写敏感** → 照抄手册必然 `EntryPointNotFound`。
    判据是三方一致：EMC 官方 C# 绑定、三个版本的 DLL 导出表，都只有全小写。
    另外 10 处 `position→positIOn` 之类是 **EMC 手册 PDF 文本层的字形伪影**，不是笔误 —— 也不能误报。
    """
    rows = _leisai_csv("leisai_emc_index.csv")
    typo = {r["函数名"] for r in rows if r["判定"].startswith("★")}
    assert typo == {"dmc_emg_stop", "dmc_axis_io_status"}, \
        f"应恰好识别出 EMC 手册的两处整词大写笔误，实得 {typo}"
    # 官方导出名必须存在（否则就是真的不存在）。_dll_exports() 的 key 是**小写** DLL 名。
    exports = _dll_exports()
    exported = {n for (d_, b, v, n), val in exports.items()
                if d_ == "ltdmc.dll" and val == 1}
    for fn in typo:
        assert fn in exported, f"{fn} 必须在 DLL 导出表里"
    # 这两个大写拼写**不在**导出表里 → 照抄手册必炸
    for wrong in ("dmc_EMG_stop", "dmc_axis_IO_status"):
        assert wrong not in exported, f"{wrong} 若已导出，这条测试要改成「厂商已修」"
    notes = "\n".join(_dmc()["notes"])
    assert "dmc_EMG_stop" in notes and "笔误" in notes, "notes 必须记录 EMC 手册的函数名笔误"


def test_雷赛脉冲卡适配器不得调用控制器侧的当量函数():
    """`dmc_set_equiv` 是**总线卡/独立控制器**在控制器里设当量用的。

    DMC3000 脉冲卡**没有**这个函数（脉冲当量在软件侧换算）。
    在脉冲卡适配器里调用它 = 把控制器的当量改掉，位置整体差一个当量倍数。
    """
    dmc = _dmc()
    code = adapter_gen.render_adapter(dmc)
    assert "dmc_set_equiv" not in code, "雷赛脉冲卡适配器不得调用 dmc_set_equiv（那是控制器侧的）"
    assert "dmc_get_equiv" not in code, "雷赛脉冲卡适配器不得调用 dmc_get_equiv"
    notes = "\n".join(dmc["notes"])
    assert "dmc_set_equiv" in notes, "notes 必须写明总线卡/独立控制器的当量是控制器侧的"
    assert "软件侧" in notes, "notes 必须写明脉冲卡是软件侧换算、与总线卡相反"


def test_雷赛总线轴使能不得被擅自实现():
    """`nmc_set_axis_enable` 是总线轴使能入口，但**手册没写使能序列**。

    主机是否写 CiA402 0x6040/0x6041 属于「可能让电机突然动作的机器安全动作」——
    **不替厂商做这个决定**，所以不绑定、不实现，保持显式失败。
    """
    dmc = _dmc()
    bound = {f["fn"] for f in dmc["pinvoke"]}
    assert "nmc_set_axis_enable" not in bound, \
        "总线轴使能序列未公开前不得绑定 nmc_set_axis_enable（安全动作不猜）"
    assert "nmc_set_axis_disable" not in bound
    notes = "\n".join(dmc["notes"])
    assert "nmc_set_axis_enable" in notes, "notes 必须写明总线轴使能入口与「序列未公开」"
    assert "显式失败" in notes, "notes 必须写明总线轴 Enable 保持显式失败"


def test_雷赛DMC_E本地端子表真值必须齐():
    """DMC-E 附录 1：ACC36-IO 接线板（36 脚）+ DMC-E1032 的 CN1（IN0~IN15）与 CN2（OUT0~OUT15）。"""
    rows = _leisai_csv("leisai_dmce_terminals.csv")
    assert len(rows) == 72, f"DMC-E 端子表应为 72 行，实得 {len(rows)}"
    idx = {(r["设备"], r["连接器"], int(r["引脚"])): r["信号"] for r in rows}
    assert idx[("ACC36-IO 接线板", "—", 3)] == "OUT0"
    assert idx[("ACC36-IO 接线板", "—", 20)] == "IN0"
    assert idx[("DMC-E1032", "CN1", 2)] == "IN0"
    assert idx[("DMC-E1032", "CN1", 18)] == "IN15"
    assert idx[("DMC-E1032", "CN2", 2)] == "OUT0"
    assert idx[("DMC-E1032", "CN2", 18)] == "OUT15"


def test_雷赛官方Csharp绑定真值表必须剥过注释():
    """官方 `LTDMC.cs` 的声明有三种形态，正则只吃一种 → 真值表会漏函数。

    ①`[DllImport("LTDMC.dll")] public static extern …`（常规）
    ②**属性与 `extern` 之间夹着中文注释行**（正则 `\\]\\s*public` 匹配不上）
    ③**整条声明被 `//` 注释掉**（死代码，不算官方声明）

    实测：只改正则会漏 ②（3 条）、只「允许夹注释」而不剥注释则会收进 ③。
    真值表必须两种都不沾 → 正确做法是**先剥注释再匹配**。
    """
    rows = _leisai_csv("leisai.csv")
    names = [r["函数名"] for r in rows]
    assert len(rows) == 1466, f"官方 C# 绑定应为 1466 条声明，实得 {len(rows)}"
    assert len(set(names)) == 1463, f"唯一函数名应为 1463，实得 {len(set(names))}"
    # ② 这三条在官方文件里属性与 extern 之间夹着注释行 —— 必须都在表里
    for fn in ("nmc_set_home_profile",
               "dmc_set_leadscrew_comp_2D_config_unit",
               "dmc_set_leadscrew_comp_2D_config_unit_ex"):
        assert fn in names, f"{fn} 是真实官方声明（注释夹在属性与 extern 之间），真值表漏了"
    # ③ 这两条在官方文件里整条被注释掉 —— 必须**不在**表里
    for fn in ("dmc_pdo_buffer_add_data_multi", "nmc_torque_set_delay_cycle"):
        assert fn not in names, f"{fn} 在官方文件里是被注释掉的死代码，不能算官方声明"
    # 前缀分布：emc_ 0 个是「EMC 用的是 dmc_ 命名」的关键依据
    assert sum(1 for n in names if n.startswith("dmc_")) == 1252
    assert sum(1 for n in names if n.startswith("nmc_")) == 214
    assert sum(1 for n in names if n.startswith("emc_")) == 0


def test_雷赛EMC结论不得自相矛盾():
    """知识库曾经同时写着「EMC 与 DMC 共用同一个 LTDMC.dll」和「EMC 有独立的 emc_* 函数库」。

    两条都在同一份 dmc.json / cards.json 里 —— 下游读到哪条全看运气，
    而「拿 DMC 的绑定去套 EMC 会整片调不通」这条错误结论会直接把人带偏。
    **这条错误结论当初就藏在一条 skip_emit 占位绑定的 doc 字段里**，所以要把
    notes / edge_cases / product_line_split / 绑定的 doc 全部纳入检查范围。
    """
    from mcopilot.core.util import knowledge_path
    dmc = _dmc()
    card = next(c for c in json.loads(knowledge_path("cards.json").read_text(encoding="utf-8"))["cards"]
                if c["brand"] == "雷赛")
    hay = "\n".join(dmc["notes"]) + "\n" + "\n".join(card["edge_cases"]) \
        + "\n" + card["product_line_split"] + "\n" + "\n".join(card["boundary"]) \
        + "\n" + "\n".join(f.get("doc", "") for f in dmc["pinvoke"])
    for bad in ("EMC 有独立的 emc_* 函数库", "函数库完全不同", "整片调不通",
                "emc_* 函数库与 DMC 卡完全不同"):
        assert bad not in hay, f"知识库里还留着与实测矛盾的旧结论：{bad}"
    # 正向：必须明确写出「同一个 LTDMC.dll / 同一套 dmc_ 函数名」
    assert "共用同一个 `LTDMC.dll`" in hay
    # 硬依据：官方绑定里 emc_ 前缀 0 个 → EMC 用的就是 dmc_ 命名
    assert not [n for n in _official_api("leisai") if n.startswith("emc_")], \
        "官方绑定里 emc_ 前缀应为 0 个"


def test_首次上机验证清单不得留着旧的锁存口结论():
    """雷赛的锁存通道**由轴号决定**（LTC0 锁 0~3 轴、LTC1 锁 4~7 轴，ACC-X400 上是 IN14/IN15）。

    第七轮已经推翻了「锁存器 0~3 → 硬件 IN4~IN7」这个自造映射并改了代码与知识库，
    **但漏改了这个上机清单** —— 现场照着它接线会接错口。清单是给现场照着做的，必须一起钉住。
    """
    from mcopilot.core.util import ROOT_DIR
    p = ROOT_DIR / "docs" / "首次上机验证清单.md"
    txt = p.read_text(encoding="utf-8")
    assert "对应硬件 IN4~IN7" not in txt, "上机清单里还留着「锁存器 0~3 → IN4~IN7」的错误接线指引"
    assert "LTC0 锁 0~3" in txt, "上机清单必须写明锁存通道由轴号决定（LTC0 锁 0~3 轴、LTC1 锁 4~7 轴）"


def test_雷赛头文件有但DLL没导出的函数不得被绑定():
    """官方 `LTDMC.h` 声明了、V2.5.7.23 的 `LTDMC.dll` 导出表里没有的 6 个函数。

    照抄官方头文件就会 `EntryPointNotFound`（同类：固高 GT_GantryHoming、正运动 ZAux_Direct_GetNtype）。
    """
    cpp = {r["函数名"] for r in _leisai_csv("leisai_cpp.csv")}
    exports = _dll_exports()
    exported = {n for (d_, b, v, n), val in exports.items()
                if d_ == "ltdmc.dll" and b == 64 and val == 1}
    not_exported = sorted(cpp - exported)
    assert len(not_exported) == 6, f"头文件有而 DLL64 没导出的应为 6 个，实得 {not_exported}"
    for fn in ("dmc_arc_move_center_angle_unit", "dmc_cmd_buf_set_line_profile_ext",
               "dmc_conti_da_curve_control", "dmc_get_vector_s_profile_multicoor",
               "dmc_lbs_trace_reset_config_object", "dmc_set_vector_s_profile_multicoor"):
        assert fn in not_exported, f"{fn} 应记为「头文件有但 DLL 没导出」"
    bound = {f["fn"] for f in _dmc()["pinvoke"]}
    assert not (bound & set(not_exported)), \
        f"绑定了 DLL 导不出的函数：{sorted(bound & set(not_exported))}"


# ==================================================================
# C3 输出契约（axiscope 知识体系缝进 servo）—— 判据层回归
# ==================================================================
#
# 契约要点（docs/contracts/C3-diagnosis.md）：
#   · hypotheses[] 每条结论 = fault_mode + ≥2 条支持证据 + 反证 + 已排除
#   · differential.not_evaluable[] 登记「没法评」的判据，写明 blocked_by 与缺什么
#   · verdict.overall_confidence 按 KB4 §2.2 算，缺席按**独立原因**扣减（A-73）
#   · expected_effect.basis 必须是 {simulation_validated, rule_heuristic, unverified}，
#     没有依据就不许给百分比
#   · 置信度 < 0.6 的结论必须写明 next_data_to_collect
#
# 下面这些测试是「不许说谎」的回归：宁可交出「不可评估」，也不许交出
# 「未发现异常特征」这种在前提不成立时根本不成立的结论。

_C3_SAMPLES = ("case_a_normal", "case_b_resonance", "case_c_no_feedforward",
               "twincat_export10")


_C3_CACHE: dict = {}


def _c3_case(name):
    """诊断一次、缓存复用 —— 这组测试要反复看同一批波形。"""
    if name not in _C3_CACHE:
        rules = servo.load_rules()
        w = servo.load_waveform(ROOT / "samples" / "servo" / f"{name}.csv")
        dg = servo.diagnose(w, rules)
        _C3_CACHE[name] = (w, dg, dg["c3"], rules)
    return _C3_CACHE[name]


def _c3_md(name):
    w, dg, c3, rules = _c3_case(name)
    return servo.build_report(w, dg, rules, None, "t").to_markdown()


def test_c3_新判据全部登记且字段齐全():
    """SRV-08…SRV-29 共 22 条，每条都要有 slug、依据层级、严重度、还要补什么。"""
    rules = servo.load_rules()
    ids = [r["id"] for r in rules["rules"]]
    assert ids == [f"SRV-{i:02d}" for i in range(8, 30)], f"新判据编号不齐：{ids}"
    for r in rules["rules"]:
        assert r["fault_mode"] in rules["fault_modes"], f"{r['id']} 的 slug 不在 KB0 里"
        assert r["basis"] in ("simulation_validated", "rule_heuristic", "unverified"), \
            f"{r['id']} 的依据层级非法：{r.get('basis')}"
        assert r["basis"] != "simulation_validated", \
            f"{r['id']} 不能声称仿真验证 —— mcopilot 里没有仿真器"
        assert r.get("severity") in rules["severity_map"], f"{r['id']} 严重度没登记"
        assert r.get("ax_rules"), f"{r['id']} 必须写明对应哪条 axiscope 规则"
        if r.get("conditions"):
            assert r.get("next_data"), f"{r['id']} 会命中，就必须写明还要补什么数据"
        else:
            # 没有可求值条件的规则是「等数据」声明：必须写明缺哪个输入
            assert r.get("missing"), f"{r['id']} 没有条件也没有写明缺什么"
            assert r.get("unlocks"), f"{r['id']} 必须写明补齐后解锁哪条规则"


@pytest.mark.parametrize("name", _C3_SAMPLES)
def test_c3_每条判据都有明确状态(name):
    """判据必须是「命中 / 没命中 / 没执行」三选一，不许悄悄消失。"""
    w, dg, c3, rules = _c3_case(name)
    fired = set(c3["audit"]["rules_fired"])
    skipped = {s["rule_id"] for s in c3["audit"]["rules_skipped"]}
    not_hit = set(c3["audit"]["rules_not_hit"])
    blocked: set[str] = set()
    for e in c3["differential"]["not_evaluable"]:
        for u in (e.get("unlocks") or []):
            if u.startswith("SRV-"):
                blocked.add(u)
    covered = fired | skipped | not_hit | blocked
    every = {r["id"] for r in rules["rules"]} | set(rules["legacy_rules"])
    missing = sorted(every - covered)
    assert not missing, f"{name}：这些判据没有交代状态：{missing}"
    assert not (fired & skipped), "同一判据不能既命中又没执行"
    assert not (fired & not_hit), "同一判据不能既命中又没命中"


@pytest.mark.parametrize("name", _C3_SAMPLES)
def test_c3_故障模式只从KB0的22个slug里取(name):
    """slug 必须逐字来自 KB0，不许自造。"""
    w, dg, c3, rules = _c3_case(name)
    allowed = set(rules["fault_modes"])
    assert len(allowed) == 22, f"KB0 的 slug 是 22 个，实得 {len(allowed)}"
    for h in c3["hypotheses"]:
        assert h["fault_mode"] in allowed, f"自造 slug：{h['fault_mode']}"
        assert h["family"], "结论必须带故障族"
    for e in c3["differential"]["not_evaluable"]:
        fm = e.get("fault_mode")
        if fm is not None:
            assert fm in allowed, f"自造 slug：{fm}"
        else:
            # 族级条目用族级标签（KB0 A-18：software_induced_error 是族级标签，不是 slug）
            assert e.get("family") in rules["family_labels"], \
                f"族级登记用了没登记过的族标签：{e.get('family')}"
    # 族级标签不许出现在 hypotheses[].fault_mode（KB0 明确禁止）
    for h in c3["hypotheses"]:
        assert h["fault_mode"] != "software_induced_error"


@pytest.mark.parametrize("name", _C3_SAMPLES)
def test_c3_缺数据时不可评估清单必须非空且写明缺什么(name):
    """「没法评」必须成条目登记：blocked_by + 原因 + 补齐后解锁什么。"""
    w, dg, c3, rules = _c3_case(name)
    ne = c3["differential"]["not_evaluable"]
    assert ne, f"{name} 缺数据却没有任何不可评估登记"
    for e in ne:
        assert e.get("blocked_by"), f"不可评估条目缺 blocked_by：{e}"
        assert e.get("why"), f"不可评估条目缺原因：{e}"
        assert e.get("unlocks"), f"不可评估条目缺「补齐后解锁什么」：{e}"


@pytest.mark.parametrize("name", _C3_SAMPLES)
def test_c3_没有依据的改进百分比不许出现(name):
    """mcopilot 没有仿真器，改进量只能给方向；basis 不许是 simulation_validated。"""
    w, dg, c3, rules = _c3_case(name)
    for h in c3["hypotheses"]:
        ee = h["expected_effect"]
        assert ee["basis"] in ("simulation_validated", "rule_heuristic", "unverified")
        assert ee["basis"] != "simulation_validated"
        assert "%" not in json.dumps(ee, ensure_ascii=False), \
            f"{h['id']} 的 expected_effect 不许出现百分比：{ee}"


@pytest.mark.parametrize("name", _C3_SAMPLES)
def test_c3_结论的结构必须完整(name):
    """每条结论：≥2 条支持证据、反证字段恒在、已排除列表在、置信度合法。"""
    w, dg, c3, rules = _c3_case(name)
    for h in c3["hypotheses"]:
        assert len(h["supporting_evidence"]) >= 2, \
            f"{h['id']} 只有 {len(h['supporting_evidence'])} 条支持证据，不许进假设"
        assert isinstance(h["contradicting_evidence"], list), "反证字段必须恒在"
        assert isinstance(h["ruled_out_alternatives"], list)
        assert 0.0 <= h["confidence"] <= 1.0
        assert h.get("counterfactual"), "结论必须做反事实自检"
        assert h["counterfactual"]["result"] in ("RESOLVED", "UNRESOLVED")
        if h["confidence"] < 0.6:
            assert h["next_data_to_collect"], \
                f"{h['id']} 置信度 {h['confidence']:.2f} < 0.6，必须写明还缺什么数据"


def test_c3_缺席扣减按去重后的独立原因数():
    """A-73：缺席扣减按**独立缺席原因**数，不按 not_evaluable 行数。"""
    w, dg, c3, rules = _c3_case("twincat_export10")
    note = c3["verdict"]["confidence_note"]
    # 同一个原因挂多个 slug 时只能算一次
    reasons = {e["blocked_by"] for e in c3["differential"]["not_evaluable"]}
    assert len(reasons) >= 4, "本样例缺的原因应当不少"
    # 没有可评估判据 ⟹ 不许给结论
    assert c3["verdict"]["primary"] is None
    assert c3["verdict"]["overall_confidence"] == 0.0
    assert "不可评估" in note or "没法评" in note


def test_c3_缺席扣减按原因数而不是行数():
    """有主结论时，扣减说明必须写明「独立缺席原因」及其个数。"""
    w, dg, c3, rules = _c3_case("case_b_resonance")
    note = c3["verdict"]["confidence_note"]
    assert "独立缺席原因" in note
    hyps = {h["id"]: h for h in c3["hypotheses"]}
    primary = hyps[c3["verdict"]["primary"]]
    assert c3["verdict"]["overall_confidence"] <= primary["confidence"] + 1e-9, \
        "缺席扣减后整体置信度不许高于主假设本身的置信度"


def test_c3_整体置信度不高于主假设置信度():
    w, dg, c3, rules = _c3_case("case_b_resonance")
    v = c3["verdict"]
    assert v["primary"]
    hyps = {h["id"]: h for h in c3["hypotheses"]}
    assert v["overall_confidence"] <= hyps[v["primary"]]["confidence"] + 1e-9


def test_c3_指令刷新率被实测且刷新谱线不进结论():
    """上位机按固定周期刷新指令 ⟹ cmd/fb/err 上都会出现同一条谱线。

    这条线是**真实**的，但它属于「指令刷新成分」，不是被控对象的响应：
    ���许把它当谐振，也**不许**说它是「伪谱线」。判据必须把它登记成不可评估。
    """
    w, dg, c3, rules = _c3_case("twincat_export10")
    sig = dg["signals"]
    assert sig.get("refresh_rate_hz"), "指令刷新率必须被实测出来"
    assert abs(sig["refresh_rate_hz"] - 100.0) < 1.0, \
        f"实测刷新率 {sig.get('refresh_rate_hz')} Hz，应为 100 Hz"
    assert sig.get("line_at_refresh_harmonic") is True, \
        "99.6 Hz 的谱线应被判为与刷新率重合"
    assert sig.get("refresh_harmonic_k") == 1
    # 谱线要报绝对幅值与动态量级，不许只报「突出度」
    assert sig["tail_line"]["amplitude"] > 0
    assert sig.get("line_over_dynamic"), "必须给出谱线/误差动态量级"
    assert sig["tail_line"].get("resolution_hz"), "必须给出频率分辨率 fs/nfft"
    # 刷新成分不许进假设
    for h in c3["hypotheses"]:
        assert h["fault_mode"] != "mechanical_resonance", "刷新成分不是机械谐振"
    bbs = {e["blocked_by"] for e in c3["differential"]["not_evaluable"]}
    assert "spectral_line_at_command_refresh_rate" in bbs, \
        "刷新成分必须登记成不可评估"
    md = _c3_md("twincat_export10")
    assert "指令刷新成分" in md
    assert "伪谱线" not in md, "这条线是真实的，不许叫伪谱线"


def test_c3_刷新率是知识库里的可复用信号而不是写死的数():
    rules = servo.load_rules()
    assert "refresh_rate_hz" in rules["signals"]
    for key in ("spectral_line_over_dynamic_min", "cmd_jump_min_ratio",
                "refresh_harmonic_tol", "steady_window_min_samples",
                "band_reliable_divisor"):
        assert key in rules["thresholds"], f"阈值 {key} 必须写在知识库里"
    sig = rules["signals"]["refresh_rate_hz"]
    assert sig.get("unit") and sig.get("how") and sig.get("why")


def test_c3_常数偏置主导时按偏置分解读且误差类判据降级():
    """cmd−fb 差一大截常数时，那不是跟随误差（常见于跨轴错配）。"""
    w, dg, c3, rules = _c3_case("twincat_export10")
    ea = dg["error"]
    assert ea["offset_suspect"] is True, "常数偏置主导必须被识别出来"
    assert abs(ea["mean"] - 179.81) < 0.5, f"偏置均值 {ea['mean']}"
    assert ea["std"] < 1.0, f"偏置标准差 {ea['std']}"
    bbs = {e["blocked_by"] for e in c3["differential"]["not_evaluable"]}
    assert "offset_dominated_error" in bbs, "依赖误差的判据必须降级为不可评估"
    md = _c3_md("twincat_export10")
    assert "常数偏置分解" in md
    assert "不作为跟随误差读" in md


def test_c3_结论先判阶跃再谈命中():
    """P0-2：非阶跃波形上不许写「未发现异常特征」—— 阶跃类判据根本没执行。"""
    md = _c3_md("twincat_export10")
    assert "不是单次阶跃" in md
    assert "未发现异常特征" not in md
    assert "条判据因前提不满足未执行" in md
    # 真的是阶跃、且所有判据都执行了，才可以说「未发现异常特征」，
    # 但仍必须说清楚有多少判据没执行。
    md_a = _c3_md("case_a_normal")
    assert "未发现异常特征" in md_a
    assert "条判据因前提不满足未执行" in md_a


def test_servo_厂商波形没有err列也要出图出报告出契约产物(tmp_path):
    """P0-1：真实厂商 CSV 没有 err 列，旧代码直接把诊断跑崩（退出码 3、out/ 空）。"""
    csv_path = ROOT / "samples" / "servo" / "twincat_export10.csv"
    res = servo.run_diagnose(csv_path, tmp_path, stem="export10")
    res["report"].write(tmp_path, "export10")
    assert (tmp_path / "export10.md").exists()
    assert res["c3_json"] and res["c3_json"].exists(), "必须落盘 C3 契约产物"
    c3 = json.loads(res["c3_json"].read_text(encoding="utf-8"))
    assert c3["hypotheses"] is not None and "verdict" in c3 and "differential" in c3
    # 「出图」这一条**挂在 matplotlib 在位的前提上**：matplotlib 是可选依赖
    # （pyproject 的 charts extra），缺它时按设计降级为「不画图但报告照出」
    # （core/chart.py 的降级契约）。所以"没有 err 列也必须出图"只能在
    # matplotlib 在位时断言——**在位时它坏了，就必须红**。
    if chart.HAS_MPL:
        assert list(tmp_path.glob("*.png")), "有 matplotlib 却没出图"


def test_servo_时间列不得被当成电流列():
    """time_ms 里含字母 i —— 单字母别名做子串匹配会把时间列认成电流通道。"""
    w = servo.load_waveform(ROOT / "samples" / "servo" / "twincat_export10.csv")
    assert w.torque is None, "time_ms 被当成了电流通道"
    assert w.columns.get("torque") is None
    assert w.columns.get("time") == "time_ms"
    # 没有电流通道 ⟹ 电流类判据整族不可评估
    w2, dg, c3, rules = _c3_case("twincat_export10")
    bbs = {e["blocked_by"] for e in c3["differential"]["not_evaluable"]}
    assert "absent_torque_channel" in bbs


def test_servo_给了加速度但对照没做成时要明说():
    """P0-4：触发条件是「给了 --accel 但对照没做成」，不是「没找到恒加速度段」。"""
    w = servo.load_waveform(ROOT / "samples" / "servo" / "case_c_no_feedforward.csv")
    rules = servo.load_rules()
    dg = servo.diagnose(w, rules, cmd_accel=500.0)
    md = servo.build_report(w, dg, rules, None, "t").to_markdown()
    if dg.get("acc_comparison_done"):
        assert "未做的对比" not in md
    else:
        assert "未做的对比" in md
    dg2 = servo.diagnose(w, rules)
    md2 = servo.build_report(w, dg2, rules, None, "t").to_markdown()
    assert "未做的对比" not in md2, "没给加速度就不许提这个对比"


def test_c3_报告必须有契约要求的四段():
    for name in _C3_SAMPLES:
        md = _c3_md(name)
        for sec in ("## 不可评估清单", "## 反证与已排除", "## 还缺什么数据",
                    "## 没有执行的判据"):
            assert sec in md, f"{name} 的报告缺「{sec}」"


def test_c3_没有条件的判据不许因为空条件而命中():
    """空条件 ⟹ 全部条件成立 ⟹ 曾经的实现会把它算成命中（空集真值陷阱）。"""
    w, dg, c3, rules = _c3_case("twincat_export10")
    fired = set(c3["audit"]["rules_fired"])
    for r in rules["rules"]:
        if not r.get("conditions"):
            assert r["id"] not in fired, f"{r['id']} 没有判据条件却命中了"


def test_c3_频谱判据必须落在稳态段():
    """跨运动事件开窗算出来的主频是假的 —— 判据必须降级，不许硬报。"""
    w, dg, c3, rules = _c3_case("twincat_export10")
    win = dg["signals"].get("steady_window")
    assert win, "必须有稳态窗"
    assert win["i1"] > win["i0"]
    # 稳态窗内指令应当是「不动」或「等速」两种之一
    assert win["kind"] in ("static", "constant_velocity")
    # 指令在动的那一段不能被当成阶跃
    assert dg["is_step"] is False


def test_c3_衰减振铃不许被当成位置环自激():
    """AX R-14 的极限环要求「静止时也持续、幅值收敛于极限环」。

    欠阻尼阶跃的振铃是**衰减**的：拿整段保持段去量幅值，量到的是阶跃瞬间的尖峰，
    于是「位置环增益过高自激」会在任何欠阻尼阶跃上误命中。
    """
    w, dg, c3, rules = _c3_case("case_b_resonance")
    sig = dg["signals"]
    assert sig.get("limit_cycle_sustain_ratio") is not None
    assert sig["limit_cycle_sustain_ratio"] < 0.7, \
        "衰减振铃的持续比必须 < 0.7（说明它在收敛，不是在自激）"
    assert "SRV-13" not in c3["audit"]["rules_fired"], \
        "衰减振铃不许触发「位置环增益过高自激」"
    # 真正的谐振结论仍然要给出来（SRV-02 旧判据 + SRV-08 新判据，合并成一条假设）
    hyp = {h["fault_mode"]: h for h in c3["hypotheses"]}
    assert "mechanical_resonance" in hyp
    assert set(hyp["mechanical_resonance"]["rule_ids"]) == {"SRV-02", "SRV-08"}
