# -*- coding: utf-8 -*-
"""cur_q（转矩/电流）通道 + events.jsonl 事件流的端到端测试。

夹具全部合成（每个症状都是**手工注入、位置已知**的，所以断言能落到实处）：

``tev_full``   —— 症状齐全：起动突破峰、低速爬行、47 Hz 纹波（转矩+误差）、
                  host 暂停误差尖峰（只在安静段）、插补欠载（路径内）、
                  丢周期、视觉迟到、25 ms 规整轮询、与波形**同刻**的事件流。
``tev_nosync`` —— 同一波形，事件整体 +0.4 s：锚点配不上 ⟹ 因果门禁必须拒答。
``tev_clean``  —— 无爬行无尖峰、误差纹波显著、4 次正常到位：
                  双惯量配对能成立、因果判据评过但不误报。
``bad events`` —— 混入坏行：问题要上报，不能悄悄吞。

关键纪律的回归断言：
* 事件侧判据（SRV-24/25/26/29）**不需要**同步就能评；
* 因果判据（SRV-23/28）同步未验证时**整条拒答**（blocked_by=events_sync_unverified），
  且不触发软件族整族缺席（族级缺席只在「事件流整个没有」时出现）；
* 无新输入时 11 条新判据全部不可评，原因逐条对得上；
* CAP-9/CAP-10 的封顶真的落到了置信度上；
* 谱线物理归因必须先过刷新线门（47 Hz 的纹波不许配到 100 Hz 的刷新线上）。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from mcopilot.agents import servo

ROOT = Path(__file__).resolve().parents[1]

FS = 1000.0
T_END = 4.6
N = int(T_END * FS)
MOVES = [(0.5, 1.4), (1.5, 2.4), (2.5, 3.4), (3.5, 4.4)]
# ⚠ V 的选型：刷新梳齿的误差峰值 ≈ V×刷新周期（20×10 ms = 0.2 mm）。
#   V=100 时梳齿峰值 1 mm，和 host 尖峰同量级 —— 尖峰判据拒答是**对的**。
#   V=20 让梳齿(0.2) ≪ 纹波(0.2 峰) 与尖峰(1.2)，量级分离后断言才立得住。
V = 20.0
RIPPLE_HZ = 47.0
CRAWL_SPAN = (1.55, 2.35)
HOST_SPIKE_T = 3.0


def _build_wave(include_crawl: bool = True, include_spike: bool = True,
                ripple_amp: float = 0.2) -> str:
    """合成波形 CSV（time_ms, cmd, fb, torque），返回路径。

    ripple_amp 默认 0.2 mm ⟹ 误差里 47 Hz 纹波的谱线（幅值 0.2）压过刷新
    梳齿的基波（≈ 步进 0.2 mm 的脉冲串基波 ≈ 0.06），谱线归因才轮得到
    物理成分 —— 否则「最强误差线」永远是 100 Hz 刷新线，配对判据只能拒答。
    """
    t = [i / FS for i in range(N)]
    # 指令：100 Hz 刷新的阶梯；方向交替、位置连续
    start_pos = 0.0
    move_of = {}
    for k, (a, b) in enumerate(MOVES):
        dirn = -1 if k % 2 else 1
        move_of[a] = (start_pos, V * dirn)
        start_pos += V * dirn * (b - a)

    def pos_target(ti: float) -> float:
        for (a, b) in MOVES:
            if a <= ti < b:
                p0, vv = move_of[a]
                return p0 + (ti - a) * vv
        for (a, b) in reversed(MOVES):
            if ti >= b:
                p0, vv = move_of[a]
                return p0 + (b - a) * vv
        return 0.0

    tau = 0.001
    cmd, fb = [0.0] * N, [0.0] * N
    cur, hold = 0.0, 0.0
    for i in range(N):
        ti = t[i]
        if i % 10 == 0:
            hold = pos_target(ti)
        cmd[i] = hold
        cur += (hold - cur) * (1.0 - math.exp(-1.0 / (tau * FS)))
        fb[i] = cur
    # 47 Hz 纹波：进 fb（⟹ 误差里有）也进转矩
    for i in range(N):
        ti = t[i]
        if any(a + 0.1 <= ti < b - 0.1 for (a, b) in MOVES):
            fb[i] += ripple_amp * math.sin(2 * math.pi * RIPPLE_HZ * ti)
    # 爬行：cruise2 里 fb 速度做粘滑交替（20 ms 全速 / 15 ms 0.1×V）
    if include_crawl:
        crawled = [0.0] * N
        vel = 0.0
        for i in range(1, N):
            ti = t[i]
            if CRAWL_SPAN[0] <= ti < CRAWL_SPAN[1]:
                phase = int((ti - CRAWL_SPAN[0]) / 0.035) % 2
                v_true = 0.1 * V if phase else V
            else:
                v_true = (cmd[i] - cmd[i - 1]) * FS
            vel += (v_true - vel) * (1.0 - math.exp(-1.0 / (0.003 * FS)))
            crawled[i] = crawled[i - 1] + vel / FS
        for i in range(N):
            if CRAWL_SPAN[0] <= t[i] < CRAWL_SPAN[1]:
                fb[i] = crawled[i] + (fb[i] - crawled[0])
    # host 暂停尖峰：只在安静巡航段（1.2 mm ≫ 3× 环内最大波动 ≈ 0.6）
    if include_spike:
        for i in range(N):
            if abs(t[i] - HOST_SPIKE_T) * 1000.0 <= 2.5:
                fb[i] -= 1.2
    torque = [0.0] * N
    for i in range(N):
        ti = t[i]
        q = 0.0
        if any(a <= ti < b for (a, b) in MOVES):
            q = 1.5 + 0.4 * math.sin(2 * math.pi * RIPPLE_HZ * ti)
            for (a, b) in MOVES:
                if a <= ti < a + 0.04:
                    q += 8.0 * math.exp(-(ti - a) / 0.008)
        torque[i] = q

    p = str(ROOT / "out" / "_test_tev" / f"wave_{include_crawl}_{include_spike}.csv")
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write("time_ms,cmd,fb,torque\n")
        for i in range(N):
            fh.write(f"{t[i]*1000.0:.3f},{cmd[i]:.6f},{fb[i]:.6f},{torque[i]:.6f}\n")
    return p


def _build_events(path: str, t_offset: float = 0.0,
                  early_done: bool = True) -> str:
    """合成 C6 事件流。t_offset≠0 ⟹ 同步必然配不上；early_done=False ⟹ 全部正常到位。"""
    ev = []
    for (a, b) in MOVES:
        ev.append({"t": a + t_offset, "level": "info", "source": "motion",
                   "code": "move_started", "axis": "X1",
                   "detail": {"target": (b - a) * V}})
    done_ts = [1.4, 2.4, 3.4, 4.4]
    if early_done:
        done_ts[2] = 3.3          # 早判：move3 实际 3.4 才完，3.3 就报到位
    for dt in done_ts:
        ev.append({"t": dt + t_offset, "level": "info", "source": "motion",
                   "code": "move_done", "axis": "X1", "detail": {"settled": True}})
    ev += [
        # host 暂停 ×2：t=2.0 在爬行段（无尖峰，不该算对齐），t=3.0 在安静段
        {"t": 2.0 + t_offset, "level": "warn", "source": "host", "code": "gc_pause",
         "axis": None, "detail": {"duration_ms": 41.2}},
        {"t": 3.0 + t_offset, "level": "warn", "source": "host", "code": "gc_pause",
         "axis": None, "detail": {"duration_ms": 12.0}},
        # 插补欠载 ×2，都在路径期间
        {"t": 0.8 + t_offset, "level": "warn", "source": "interp",
         "code": "buffer_underrun", "axis": None,
         "detail": {"buffer_level": 0, "lookahead_ms": 12}},
        {"t": 2.9 + t_offset, "level": "warn", "source": "interp",
         "code": "buffer_underrun", "axis": None,
         "detail": {"buffer_level": 1, "lookahead_ms": 9}},
        # 总线丢周期
        {"t": 0.9 + t_offset, "level": "error", "source": "network",
         "code": "wkc_error", "axis": None, "detail": {"expected": 6, "actual": 5}},
    ]
    # 视觉迟到（p95 = 88 ms ≥ 50）
    for k, lat in enumerate([31, 33, 35, 38, 41, 52, 61, 88]):
        ev.append({"t": round(0.6 + k * 0.35 + t_offset, 3), "level": "info",
                   "source": "vision", "code": "result", "axis": None,
                   "detail": {"latency_ms": lat}})
    # 25 ms 规整轮询（⟹ SRV-29）
    tt = 0.0 + t_offset
    while tt <= 4.5 + t_offset:
        ev.append({"t": round(tt, 3), "level": "debug", "source": "motion",
                   "code": "status_poll", "axis": None, "detail": {}})
        tt += 0.025
    ev.sort(key=lambda e: e["t"])
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for e in ev:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return path


_CACHED: dict[str, tuple] = {}


def _case(name: str):
    """跑完一整套诊断并缓存。name ∈ full / nosync / clean。"""
    if name in _CACHED:
        return _CACHED[name]
    rules = servo.load_rules()
    outdir = ROOT / "out" / "_test_tev"
    if name == "full":
        csv_p = _build_wave(include_crawl=True, include_spike=True)
        ev_p = _build_events(str(outdir / "events_full.jsonl"), early_done=True)
    elif name == "nosync":
        csv_p = _build_wave(include_crawl=True, include_spike=True)
        ev_p = _build_events(str(outdir / "events_nosync.jsonl"), t_offset=0.4,
                             early_done=True)
    else:
        csv_p = _build_wave(include_crawl=False, include_spike=False)
        ev_p = _build_events(str(outdir / "events_clean.jsonl"), early_done=False)
    res = servo.run_diagnose(Path(csv_p), None, events_path=Path(ev_p))
    w, dg = res["waveform"], res["diagnosis"]
    _CACHED[name] = (w, dg, dg["c3"], rules)
    return _CACHED[name]


def _audit(c3):
    a = c3["audit"]
    fired = [r["rule_id"] if isinstance(r, dict) else r for r in a["rules_fired"]]
    not_hit = set(a["rules_not_hit"])
    skipped = {s["rule_id"]: s for s in a["rules_skipped"]}
    return fired, not_hit, skipped


def _hyp_by_mode(c3, mode):
    return [h for h in c3["hypotheses"] if h["fault_mode"] == mode]


# ---------------------------------------------------------------- 转矩判据

def test_torque_症状齐全_三条转矩判据命中():
    w, dg, c3, rules = _case("full")
    fired, not_hit, skipped = _audit(c3)
    assert "SRV-15" in fired, "起动突破峰（8× 稳态转矩）必须点亮静摩擦"
    assert "SRV-16" in fired, "粘滑交替（0.1×V 的失速段）必须点亮爬行"
    assert "SRV-17" in fired, "47 Hz 窄带转矩线必须点亮转矩纹波"
    sig = dg["signals"]
    assert sig["tq_breakaway_ratio"] >= 2.0
    assert sig["crawl_stall_count"] >= 3
    assert sig["crawl_stall_time_ratio"] >= 0.02
    assert sig["tq_ripple_freq_hz"] == pytest.approx(RIPPLE_HZ, abs=1.5)
    assert sig["tq_ripple_over_dynamic"] >= 0.05


def test_torque_双惯量_干净夹具命中_爬行污染夹具诚实拒答():
    """爬行段主导误差谱时，47 Hz 配不上对 —— 拒答是**对的**，不是缺陷。"""
    w, dg, c3, rules = _case("full")
    fired, not_hit, skipped = _audit(c3)
    assert "SRV-20" in not_hit
    assert dg["signals"]["ti_pair_ratio"] is not None
    assert not (0.8 <= dg["signals"]["ti_pair_ratio"] <= 1.25), \
        "爬行污染的误差谱线上不该配出对"
    # 干净夹具：误差谱线回到 47 Hz，配对成立
    w2, dg2, c32, _ = _case("clean")
    fired2, _, _ = _audit(c32)
    assert "SRV-20" in fired2
    assert dg2["signals"]["ti_res_freq_hz"] == pytest.approx(RIPPLE_HZ, abs=2.0)
    assert 0.8 <= dg2["signals"]["ti_pair_ratio"] <= 1.25


def test_torque_配对拒绝刷新线_误差线是刷新梳齿时不给比值():
    """误差「最强线」是 100 Hz 刷新线时，配对比值必须缺位 ——
    拿纹波频率除以刷新频率的数字看似正常，物理上毫无意义。"""
    rules = servo.load_rules()
    # 小纹波 ⟹ 刷新梳齿主导误差谱 ⟹ tail_line 落在刷新线上
    csv_p = _build_wave(include_crawl=False, include_spike=False, ripple_amp=0.0005)
    ev_p = _build_events(str(ROOT / "out" / "_test_tev" / "events_refresh.jsonl"),
                         early_done=False)
    res = servo.run_diagnose(Path(csv_p), None, events_path=Path(ev_p))
    sig = res["diagnosis"]["signals"]
    assert sig["refresh_rate_hz"] == pytest.approx(100.0, abs=5.0)
    assert sig.get("tail_line_freq_hz") == pytest.approx(100.0, abs=5.0), \
        "夹具本身要先证实：最强误差线确实是刷新线"
    assert sig.get("ti_pair_ratio") is None, \
        "误差线是刷新线时，配对比值必须缺位而不是硬算"


def test_torque_SRV18_没有驱动器参数时拒答原因要指名():
    w, dg, c3, rules = _case("full")
    _, _, skipped = _audit(c3)
    s = skipped["SRV-18"]
    assert s["blocked_by"] == "absent_drive_params", \
        f"转矩有了就该指向缺的 drive_params，而不是 {s['blocked_by']}"
    assert "驱动器" in s["why"] or "电流环" in s["why"]


# ---------------------------------------------------------------- 事件判据

def test_events_事件侧四条_不需要同步就命中():
    w, dg, c3, rules = _case("full")
    fired, not_hit, skipped = _audit(c3)
    for rid in ("SRV-24", "SRV-25", "SRV-26", "SRV-29"):
        assert rid in fired, f"{rid} 是纯事件侧判据，不应等同步"
    sig = dg["signals"]
    assert sig["ev_n"] > 100
    assert sig["ev_underrun_count"] == 2
    assert sig["ev_underrun_during_path"] == 2, "两次欠载都在 move 括号内"
    assert sig["ev_wkc_count"] == 1
    assert sig["ev_vision_latency_p95_ms"] == pytest.approx(88.0)
    assert sig["ev_motion_interval_median_ms"] == pytest.approx(25.0, abs=1.0)
    assert sig["ev_motion_interval_cv"] < 0.35


def test_events_同步验证_因果判据才命中():
    w, dg, c3, rules = _case("full")
    fired, not_hit, skipped = _audit(c3)
    sync = w.events_sync
    assert sync["method"] == "anchor_matching"
    assert sync["verified"] is True
    assert sync["causal_claims_permitted"] is True
    assert sync["alignment_residual_ms"] <= sync["uncertainty_ms"]
    assert sync["n_anchor_pairs"] >= 3
    assert "SRV-23" in fired, "安静段那次暂停对上了误差尖峰，因果判据应点亮"
    assert "SRV-28" in fired, "3.3 s 那次早判的 move_done 应点亮窗口过短"
    sig = dg["signals"]
    assert sig["ev_host_err_aligned_ratio"] == pytest.approx(0.5), \
        "两个暂停里只有安静段那个算对齐（爬行段的基线太高，正确地不算）"
    assert sig["ev_settle_err_ratio"] >= 3.0


def test_events_同步未验证_因果判据整条拒答_事件侧照常():
    w, dg, c3, rules = _case("nosync")
    fired, not_hit, skipped = _audit(c3)
    sync = w.events_sync
    assert sync["verified"] is False
    assert sync["causal_claims_permitted"] is False
    assert sync.get("why")
    for rid in ("SRV-23", "SRV-28"):
        s = skipped[rid]
        assert s["blocked_by"] == "events_sync_unverified", \
            f"{rid} 是因果判据，同步未验证必须整条拒答"
        assert "同步" in s["why"]
    # 事件侧统计照常可评
    for rid in ("SRV-24", "SRV-25", "SRV-26", "SRV-29"):
        assert rid in fired
    sig = dg["signals"]
    assert sig["ev_host_err_aligned_ratio"] is None
    assert sig["ev_settle_err_ratio"] is None
    assert sig["ev_causal_ok"] is False


def test_events_因果干净_两条因果判据不误报():
    """没有尖峰、没有早判 ⟹ SRV-23/28 应该是「评了但没命中」，不是拒答。

    这条同时守着刷新梳齿不误报：干净夹具里误差被 100 Hz 梳齿支配，
    暂停窗内的「梳齿尖峰」不许被当成事件对齐的误差尖峰。
    """
    w, dg, c3, rules = _case("clean")
    fired, not_hit, skipped = _audit(c3)
    for rid in ("SRV-23", "SRV-28"):
        assert rid in not_hit, f"{rid} 在干净夹具上应评过且没命中"
        assert rid not in skipped


def test_events_事件流缺席_软件族整族缺席还在():
    """事件流整个没有时：软件族 ≥7 条全不可评 ⟹ 族级 absent_events_jsonl 登记。"""
    rules = servo.load_rules()
    w = servo.load_waveform(ROOT / "samples" / "servo" / "case_a_normal.csv")
    dg = servo.diagnose(w, rules)
    c3 = dg["c3"]
    _, _, skipped = _audit(c3)
    for rid in ("SRV-15", "SRV-16", "SRV-17", "SRV-20"):
        assert skipped[rid]["blocked_by"] == "absent_torque_channel"
    assert skipped["SRV-18"]["blocked_by"] == "absent_torque_channel"
    for rid in ("SRV-23", "SRV-24", "SRV-25", "SRV-26", "SRV-28", "SRV-29"):
        assert skipped[rid]["blocked_by"] == "absent_events_jsonl"
    fam = [n for n in c3["differential"]["not_evaluable"]
           if n.get("family") == "software_induced_error"]
    assert fam, "软件族整族不可评时必须有族级登记"


def test_events_同步未验证_不触发族级缺席():
    """拒答 ≠ 缺席：同步未验证只挂 3 条，族级 absent_events_jsonl 不应出现。"""
    w, dg, c3, rules = _case("nosync")
    fam = [n for n in c3["differential"]["not_evaluable"]
           if n.get("family") == "software_induced_error"]
    assert not fam, "事件流明明在场，不能报「整族缺席」"


# ---------------------------------------------------------------- 坏行与接线

def test_events_坏行要上报不能吞():
    ev_p = _build_events(str(ROOT / "out" / "_test_tev" / "events_bad.jsonl"))
    with open(ev_p, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("{not json at all}\n")
        fh.write(json.dumps({"t": 1.0, "source": "ghost_source", "code": "x"}) + "\n")
        fh.write(json.dumps({"t": None, "source": "host", "code": "x"}) + "\n")
    events, problems = servo.load_events(Path(ev_p))
    assert events, "好行要继续解析"
    assert len(problems) >= 3, f"三条坏行都要上报：{problems}"
    assert any("JSON" in p or "解析" in p for p in problems)
    assert any("source" in p for p in problems), "未知 source 要点名"
    assert any("t" in p for p in problems), "缺时间戳要点名"


def test_wiring_run_diagnose_事件进了波形包():
    w, dg, c3, rules = _case("full")
    assert w.events and len(w.events) > 100
    assert w.events_problems == []
    assert w.columns.get("events"), "事件文件要登记进样本包清单"
    assert w.events_sync is not None


def test_wiring_cli_接受events参数():
    from mcopilot import cli
    parser = cli.build_parser()
    argv = parser.parse_args(["servo", "diagnose", "x.csv", "--events", "ev.jsonl"])
    assert argv.events == "ev.jsonl"
    argv2 = parser.parse_args(["servo", "diagnose", "x.csv"])
    assert argv2.events is None
    argv3 = parser.parse_args(["servo", "diagnose", "x.csv", "--axis", "axis.json"])
    assert argv3.axis == "axis.json"


# ---------------------------------------------------------------- axis.json 铭牌侧车

def _build_axis(path: str, pitch: float = 5.0, pp: float = 2.0,
                cpr: float = 10000.0, omit: str | None = None) -> str:
    """合成轴铭牌侧车。V=20 mm/s ÷ 5 mm/rev = 4 rev/s；×2 pp = 8 Hz 电频率；
    47 Hz 纹波线 ÷ 8 ≈ 5.93 ≈ 6× 电频率（残差 0.07 ≤ 0.2）。"""
    obj = {"cpr": cpr, "pole_pairs": pp, "screw_pitch_mm": pitch}
    if omit:
        obj.pop(omit)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    return path


def test_axis_侧车解锁阶次归因_纹波线归到6乘电频率():
    csv_p = _build_wave(include_crawl=False, include_spike=False)
    ev_p = _build_events(str(ROOT / "out" / "_test_tev" / "events_clean.jsonl"),
                         early_done=False)
    ax_p = _build_axis(str(ROOT / "out" / "_test_tev" / "axis.json"))
    res = servo.run_diagnose(Path(csv_p), None, events_path=Path(ev_p),
                             axis_path=Path(ax_p))
    w, dg, c3 = res["waveform"], res["diagnosis"], res["diagnosis"]["c3"]
    assert w.columns.get("axis")
    assert w.axis_problems == []
    attr = [h.get("attribution") for h in c3["hypotheses"]
            if h["fault_mode"] == "electrical_torque_ripple"]
    assert attr and attr[0], "有侧车时转矩纹波假设必须带阶次归因"
    a = attr[0]
    assert a["kind"] == "elec" and a["order_i"] == 6, \
        f"47 Hz ÷ 8 Hz 电频率应归到 6×（实际 {a}）"
    assert a["resid"] <= 0.2
    assert "6× 电频率" in (dg["c3"]["hypotheses"][0]["detail"] or "") or any(
        "6× 电频率" in (h.get("detail") or "") for h in c3["hypotheses"])


def test_axis_无侧车_归因缺位而非猜测():
    w, dg, c3, rules = _case("clean")
    hs = [h for h in c3["hypotheses"] if h["fault_mode"] == "electrical_torque_ripple"]
    if hs:
        assert "attribution" not in hs[0], \
            "没有侧车时不许给阶次归因——缺位就是「未做归因」"
    assert "tq_ripple_order_best" not in dg["signals"]


def test_axis_坏字段上报_依赖它的归因自动缺位():
    ax_p = _build_axis(str(ROOT / "out" / "_test_tev" / "axis_bad.json"),
                       omit="pole_pairs")
    with open(ax_p, "a", encoding="utf-8") as fh:
        fh.write(', "screw_pitch_mm": "abc"}')      # 故意弄成坏 JSON
    ax, problems = servo.load_axis(Path(ax_p))
    assert problems, "坏 JSON 必须上报"
    assert ax == {}
    # 单独缺 pole_pairs（合法 JSON）：归因不可用，但载入成功且字段点名
    ax2_p = _build_axis(str(ROOT / "out" / "_test_tev" / "axis_nopp.json"),
                        omit="pole_pairs")
    ax2, problems2 = servo.load_axis(Path(ax2_p))
    assert ax2.get("pole_pairs") == 0.0
    assert any("pole_pairs" in p for p in problems2), "缺失字段要点名"


def test_axis_铭牌在场的inputs_present():
    csv_p = _build_wave(include_crawl=False, include_spike=False)
    w = servo.load_waveform(Path(csv_p))
    rules = servo.load_rules()
    assert servo._present_inputs(w, rules)["axis_nameplate"] is False
    w.axis, _ = servo.load_axis(Path(_build_axis(
        str(ROOT / "out" / "_test_tev" / "axis2.json"))))
    assert servo._present_inputs(w, rules)["axis_nameplate"] is True


# ---------------------------------------------------------------- 置信度封顶

def test_CAP10_爬行因速度为派生值封顶():
    w, dg, c3, rules = _case("full")
    hs = _hyp_by_mode(c3, "mechanical_crawling")
    assert hs, "症状齐全夹具里爬行假设必须存在"
    h = hs[0]
    assert h["confidence"] <= rules["caps"]["derived_velocity_feedback"]
    assert any("CAP-10" in c for c in h["confidence_parts"]["caps"]), \
        "封顶原因要写进 confidence_parts.caps"
    assert dg["signals"].get("vel_fb_direct") is False


def test_CAP9_反事实未解决封顶():
    """欠载与 host 抖动的混淆形态并存（host 暂停 41 ms 在场）⟹ 封顶 0.6。"""
    w, dg, c3, rules = _case("full")
    hs = _hyp_by_mode(c3, "software_induced_interp_buffer_underrun")
    assert hs
    h = hs[0]
    cf = h["counterfactual"]
    assert cf["result"] == "UNRESOLVED"
    assert "host_thread_jitter" in cf["competitor"]
    assert h["confidence"] <= rules["caps"]["counterfactual_unresolved"]


# ---------------------------------------------------------------- 输出形状

def test_c3_形状与审计互斥在三个夹具上都成立():
    for name in ("full", "nosync", "clean"):
        w, dg, c3, rules = _case(name)
        a = c3["audit"]
        fired = {r["rule_id"] if isinstance(r, dict) else r for r in a["rules_fired"]}
        not_hit = set(a["rules_not_hit"])
        skipped = {s["rule_id"] for s in a["rules_skipped"]}
        assert not (fired & not_hit) and not (fired & skipped) and not (not_hit & skipped)
        for h in c3["hypotheses"]:
            assert h["rule_ids"] and h["supporting_evidence"]
            assert 0.0 <= h["confidence"] <= 1.0
            if h["confidence"] > rules["caps"]["counterfactual_unresolved"]:
                assert h["counterfactual"]["result"] == "RESOLVED", \
                    "置信高于反事实封顶的假设，反事实必须是已解决的"
        for s in a["rules_skipped"]:
            rid = s["rule_id"]
            if rid >= "SRV-15":        # 新判据必须给结构化拒答原因
                assert s.get("blocked_by"), f"{rid} 拒答必须给原因"
            else:                      # 旧判据只有 why/unlocks，也必须说人话
                assert s.get("why") or s.get("blocked_by"), f"{rid} 拒答必须给原因"


# ================================================================= KB v5
# 搁置判据批次 A1（温度）/A3（配方事件）/B1（驱动器参数侧车）/B2（扫频）

def _write_csv(path: str, header: str, rows: list[str]) -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(header + "\n")
        for r in rows:
            fh.write(r + "\n")
    return path


def _build_wave_thermal(path: str | None = None) -> str:
    """温度通道夹具（SRV-21/22）：60 s，温度 25→29.5 K 线性爬升，
    误差慢趋势 = 5 µm/K × (T−25)（真热漂移），转矩 RMS 随温度同涨（电机发热）。"""
    path = path or str(ROOT / "out" / "_test_tev" / "wave_thermal.csv")
    n = int(60.0 * FS)
    t = [i / FS for i in range(n)]
    temp = [25.0 + 4.5 * ti / 60.0 for ti in t]
    # 缓慢多段运动（每 10 s 走 20 mm，方向交替；过零约 12 次 < 30，
    # 不会误触扫频检测）
    cmd, fb = [0.0] * n, [0.0] * n
    cur = 0.0
    seg_start_pos = 0.0
    last_seg = -1
    for i in range(n):
        ti = t[i]
        seg = int(ti // 10)
        dirn = -1.0 if seg % 2 else 1.0
        if seg != last_seg:
            seg_start_pos = cmd[i - 1] if i > 0 else 0.0
            last_seg = seg
        cmd[i] = seg_start_pos + (ti - seg * 10.0) * (V * dirn / 10.0)
        cur += (cmd[i] - cur) * (1.0 - math.exp(-1.0 / (0.002 * FS)))
        fb[i] = cur - 0.005 * (temp[i] - 25.0)
    torque = [1.2 + 0.8 * (ti / 60.0) for ti in t]
    return _write_csv(path, "time_ms,cmd,fb,torque,temp",
                      [f"{t[i]*1000.0:.3f},{cmd[i]:.6f},{fb[i]:.6f},"
                       f"{torque[i]:.6f},{temp[i]:.4f}" for i in range(n)])


def _build_wave_recipe(path: str | None = None, scale: float = 1.08,
                       boundary: float = 3.0) -> tuple[str, str]:
    """配方夹具（SRV-27）：t=3.0 配方切换，之后反馈位置整体 ×1.08
    （脉冲当量被改写的直接症状：位移比例在边界跳变 ≥5%）。返回 (csv, events)。"""
    path = path or str(ROOT / "out" / "_test_tev" / "wave_recipe.csv")
    t_end = 6.0
    n = int(t_end * FS)
    t = [i / FS for i in range(n)]
    moves = [(0.5, 1.5), (2.0, 3.0), (3.5, 4.5)]

    def pos_target(ti):
        p = 0.0
        for k, (a, b) in enumerate(moves):
            dirn = -1.0 if k % 2 else 1.0
            if a <= ti < b:
                return p + (ti - a) * V * dirn
            if ti >= a:
                p += (b - a) * V * dirn
        return p

    cmd, fb = [0.0] * n, [0.0] * n
    cur = 0.0
    for i in range(n):
        ti = t[i]
        if i % 10 == 0:
            cmd[i] = pos_target(ti)
        else:
            cmd[i] = cmd[i - 1]
        cur += (cmd[i] - cur) * (1.0 - math.exp(-1.0 / (0.002 * FS)))
        s = scale if ti >= boundary else 1.0
        fb[i] = cur * s
    csv_p = _write_csv(path, "time_ms,cmd,fb",
                       [f"{t[i]*1000.0:.3f},{cmd[i]:.6f},{fb[i]:.6f}"
                        for i in range(n)])
    ev_p = str(ROOT / "out" / "_test_tev" / "events_recipe.jsonl")
    Path(ev_p).parent.mkdir(parents=True, exist_ok=True)
    with open(ev_p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"t": boundary, "level": "info", "source": "recipe",
                             "code": "recipe_change", "axis": None,
                             "detail": {"recipe": "B-2007"}}, ensure_ascii=False) + "\n")
    return csv_p, ev_p


def _build_wave_sweep(path: str | None = None) -> str:
    """扫频夹具（SRV-19）：[1,7] s chirp 2→60 Hz（dynamics wn≈4 Hz ζ=0.7，
    =「投运后增益被调低」的失整定机器），[7.5] s 一个**真单拍**阶跃 0→30 mm
    （dynamics wn≈12 Hz ζ=0.5，= 投运时的整定）。ωn 估计来自阶跃段（≈12 Hz），
    实测闭环带宽来自扫频段（≈4 Hz）⟹ 比值 ≈0.3 ≤ 0.5 判失整定。"""
    path = path or str(ROOT / "out" / "_test_tev" / "wave_sweep.csv")
    t_end = 10.0
    n = int(t_end * FS)
    t = [i / FS for i in range(n)]
    dt = 1.0 / FS
    wn_a, zt_a = 2 * math.pi * 12.0, 0.5      # 阶跃段（整定良好）
    wn_b, zt_b = 2 * math.pi * 4.0, 0.7       # 扫频段（失整定）
    cmd, fb = [0.0] * n, [0.0] * n
    x, xv = 0.0, 0.0
    phi = 0.0
    for i in range(n):
        ti = t[i]
        if ti < 1.0:
            cmd[i] = 0.0
            wn, zt = wn_b, zt_b
        elif ti < 7.0:
            f = 2.0 + (60.0 - 2.0) * (ti - 1.0) / 6.0
            phi += 2 * math.pi * f * dt
            cmd[i] = 3.0 * math.sin(phi)
            wn, zt = wn_b, zt_b
        elif ti < 7.5:
            cmd[i] = 0.0
            wn, zt = wn_b, zt_b
        else:
            # 真单拍阶跃（不做刷新阶梯——is_step 数的是阶跃窗口内的动样本）
            cmd[i] = 30.0
            wn, zt = wn_a, zt_a
        acc = wn * wn * (cmd[i] - x) - 2 * zt * wn * xv
        xv += acc * dt
        x += xv * dt
        fb[i] = x
    return _write_csv(path, "time_ms,cmd,fb",
                      [f"{t[i]*1000.0:.3f},{cmd[i]:.6f},{fb[i]:.6f}"
                       for i in range(n)])


def _build_drive_params(path: str | None = None,
                        curloop_hz: float = 20.0) -> str:
    path = path or str(ROOT / "out" / "_test_tev" / "drive_params.json")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"current_loop_bandwidth_hz": curloop_hz,
                   "velocity_loop_gain_hz": 45.0,
                   "notch_hz": []}, fh, ensure_ascii=False)
    return path


_SW: dict[str, tuple] = {}


def _case_v5(name: str):
    if name in _SW:
        return _SW[name]
    rules = servo.load_rules()
    outdir = ROOT / "out" / "_test_tev"
    if name == "thermal":
        res = servo.run_diagnose(Path(_build_wave_thermal()), None)
    elif name == "recipe":
        csv_p, ev_p = _build_wave_recipe()
        res = servo.run_diagnose(Path(csv_p), None, events_path=Path(ev_p))
    elif name == "drivep":
        csv_p = _build_wave(include_crawl=False, include_spike=False)
        dp = _build_drive_params()
        res = servo.run_diagnose(Path(csv_p), None, drive_params_path=Path(dp))
    else:  # sweep
        res = servo.run_diagnose(Path(_build_wave_sweep()), None)
    w, dg = res["waveform"], res["diagnosis"]
    _SW[name] = (w, dg, dg["c3"], rules)
    return _SW[name]


def _skipped(c3, rid: str) -> dict | None:
    for s in c3["audit"]["rules_skipped"]:
        if s["rule_id"] == rid:
            return s
    return None


# ---------------------------------------------------------------- 温度

def test_温度通道解锁SRV21_热漂移():
    w, dg, c3, rules = _case_v5("thermal")
    sig = dg["signals"]
    assert sig["temp_span_k"] > 4.0, "60 s 内温度应爬升 4.5 K"
    # 交替方向运动的跟踪误差会稀释块级相关；0.6 正是规则自己的门
    assert sig["err_temp_corr"] > 0.6, "误差慢趋势应与温度正相关（≥规则门）"
    assert 0.004 < sig["err_drift_per_k"] < 0.006, "回归斜率应落在注入值 5 µm/K 附近"
    hs = _hyp_by_mode(c3, "mechanical_thermal_drift")
    assert hs, "温度+误差相关达标 ⟹ SRV-21 必须可评"
    assert hs[0]["confidence"] > 0.5


def test_温度通道解锁SRV22_电机发热():
    w, dg, c3, rules = _case_v5("thermal")
    sig = dg["signals"]
    assert sig["temp_rise_k_per_min"] > 0.3, "升温速率 4.5 K/min"
    assert sig["temp_tq_corr"] > 0.5, "温度跟着转矩 RMS 走（夹具同涨）"
    hs = _hyp_by_mode(c3, "electrical_motor_heating")
    assert hs, "温升+负载相关达标 ⟹ SRV-22 必须可评"


def test_无温度列_两条热判据点名absent_temp_channel():
    w, dg, c3, rules = _case("clean")
    for rid in ("SRV-21", "SRV-22"):
        s = _skipped(c3, rid)
        assert s and s["blocked_by"] == "absent_temp_channel", \
            f"{rid} 应拒答于 absent_temp_channel（实际 {s and s['blocked_by']}）"


# ---------------------------------------------------------------- 配方

def test_配方事件解锁SRV27_当量改写():
    w, dg, c3, rules = _case_v5("recipe")
    sig = dg["signals"]
    assert sig["ev_recipe_change_count"] == 1
    assert sig["recipe_scale_step_ratio_max"] >= 0.05, \
        "边界后 fb×1.08 ⟹ 段间位移比例跳变 ≥5%"
    assert sig["recipe_scale_drift_within_max"] < 0.05, "段内应平稳（阶跃不是漂移）"
    hs = _hyp_by_mode(c3, "software_induced_pulse_eq_overwritten")
    assert hs, "配方边界+比例跳变 ⟹ SRV-27 必须可评"


def test_无配方事件_SRVP27拒答并点名():
    w, dg, c3, rules = _case("clean")
    s = _skipped(c3, "SRV-27")
    assert s and s["blocked_by"] == "absent_recipe_events"


# ---------------------------------------------------------------- 驱动器参数

def test_驱动器参数解锁SRV18_谐振超出电流环带宽():
    w, dg, c3, rules = _case_v5("drivep")
    sig = dg["signals"]
    assert sig["res_over_curloop_ratio"] >= 1.0, "47 Hz 谐振 ÷ 20 Hz 电流环 ≈ 2.35"
    hs = _hyp_by_mode(c3, "electrical_current_loop_bandwidth")
    assert hs, "有侧车+谐振超带宽 ⟹ SRV-18 必须可评"
    h = hs[0]
    assert any(e["feature"] == "servo.drive.res_over_curloop"
               for e in h["supporting_evidence"])


def test_无驱动器参数_SRVP18仍拒答于absent_drive_params():
    w, dg, c3, rules = _case("clean")
    s = _skipped(c3, "SRV-18")
    assert s and s["blocked_by"] == "absent_drive_params"


def test_侧车坏字段上报():
    dp = _build_drive_params(str(ROOT / "out" / "_test_tev" / "dp_bad.json"))
    with open(dp, "w", encoding="utf-8") as fh:
        fh.write('{"current_loop_bandwidth_hz": "fast"}')
    obj, problems = servo.load_drive_params(Path(dp))
    assert obj.get("current_loop_bandwidth_hz") == 0.0
    assert any("current_loop_bandwidth_hz" in p for p in problems)


# ---------------------------------------------------------------- 扫频

def test_扫频解锁SRV19_实测带宽远低于wn估计():
    w, dg, c3, rules = _case_v5("sweep")
    sig = dg["signals"]
    assert w.sweep and w.sweep["ok"], "chirp 必须被检测到"
    assert sig["sweep_valid_bins"] >= 5, "无噪夹具相干性应全过"
    assert sig["sweep_bw_hz"] and 2.0 < sig["sweep_bw_hz"] < 8.0, \
        f"wn=4 Hz 二阶的闭环带宽应落在个位数（实际 {sig['sweep_bw_hz']}）"
    assert sig["sweep_bw_wn_ratio"] <= rules["thresholds"]["sweep_bw_wn_ratio_max"], \
        "阶跃段 wn≈12 Hz vs 实测 ≈4 Hz ⟹ 比值 ≤0.5"
    assert sig["sweep_dip_ratio"] is None, "单调滚降不是谐振坑，不许碰反证"
    hs = _hyp_by_mode(c3, "electrical_velocity_pi_detune")
    assert hs, "带宽/ωn 比值达标 ⟹ SRV-19 必须可评"


def test_普通多段运动不误判为扫频():
    w, dg, c3, rules = _case("clean")
    assert not (w.sweep or {}).get("ok")
    s = _skipped(c3, "SRV-19")
    assert s and s["blocked_by"] == "absent_sweep_recording"


# ---------------------------------------------------------------- KB 契约

def test_kb_v5_契约_反事实竞争必须在fault_modes枚举里():
    """v5 修的 bug：SRV-23 的竞争 slug 曾写成 mechanical_loose_mechanical
    （枚举里没有），错 slug 的反事实永远不会命中，等于没做自检。"""
    kb = json.load(open(ROOT / "knowledge" / "servo_rules.json", encoding="utf-8"))
    modes = set(kb["fault_modes"].keys())
    for r in kb["rules"]:
        cf = r.get("counterfactual")
        if not cf:
            continue
        assert cf.get("competitor") in modes, \
            f"{r['id']} 反事实竞争 {cf.get('competitor')!r} 不在 fault_modes 枚举里"


def test_kb_v5_契约_inputs_present的kind都有实现():
    kb = json.load(open(ROOT / "knowledge" / "servo_rules.json", encoding="utf-8"))
    implemented = {"channel", "channel_or_derived", "events_file",
                   "derived_fb_velocity", "axis_sidecar", "drive_params_sidecar",
                   "events_recipe", "derived_sweep"}
    for key, kind in kb["inputs_present"].items():
        assert kind in implemented, \
            f"inputs_present.{key}={kind!r} 没有对应实现，永远 False 还占着名额"


def test_kb_v5_契约_带条件的规则必须有next_data和反事实():
    kb = json.load(open(ROOT / "knowledge" / "servo_rules.json", encoding="utf-8"))
    for r in kb["rules"]:
        if not r.get("conditions"):
            continue
        assert r.get("next_data"), f"{r['id']} 有条件却没写 next_data"
        assert r.get("counterfactual"), f"{r['id']} 有条件却没写反事实"
