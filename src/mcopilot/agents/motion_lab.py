"""运动验证器（motion_lab）：在拿到机台之前，把运动参数算清楚。

回答上位机工程师每天都在问、但往往只能靠上机试出来的四个问题：
  1. 这段 S 曲线到底多久走完？峰值速度多少？有没有匀速段？
  2. 以现在的伺服带宽，指令加速度下的最大跟随误差会不会吃掉我的定位公差？
  3. 急停/减速的制动距离是多少？（决定安全距离和「指令停了轴还没停」的坑）
  4. 电子齿轮/脉冲当量算对了吗？（系统性定位偏差最常见的根因）
外加飞拍/硬件比较输出触发点与曝光窗口计算。

输出可直接变成上位机单测的黄金测试向量 —— 同一份曲线，Python 算一遍，C# 再算一遍，
对不上就是算法实现错了，而不是上机之后才发现。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from ..core import chart
from ..core.report import Report, callout
from ..core.util import fmt, write_json, write_text

# ------------------------------------------------------------------ 曲线构造


@dataclass
class Segment:
    name: str
    jerk: float
    dur: float
    x0: float
    v0: float
    a0: float

    @property
    def a1(self) -> float:
        return self.a0 + self.jerk * self.dur

    @property
    def v1(self) -> float:
        return self.v0 + self.a0 * self.dur + 0.5 * self.jerk * self.dur ** 2

    @property
    def x1(self) -> float:
        return self.x0 + self.v0 * self.dur + 0.5 * self.a0 * self.dur ** 2 + self.jerk * self.dur ** 3 / 6.0


@dataclass
class Profile:
    distance: float
    v_peak: float
    a_peak: float
    j_max: float
    segments: list[Segment] = field(default_factory=list)
    cruise_time: float = 0.0
    cruise_dist: float = 0.0

    @property
    def total_time(self) -> float:
        return sum(s.dur for s in self.segments)

    @property
    def end_x(self) -> float:
        return self.segments[-1].x1 if self.segments else 0.0

    @property
    def end_v(self) -> float:
        return self.segments[-1].v1 if self.segments else 0.0


def _accel_phase(v_peak: float, a_max: float, j_max: float) -> dict | None:
    """从 0 加速到 v_peak 的 jerk 受限段参数（7 段 S 曲线的加速半边）。"""
    if v_peak <= 0 or a_max <= 0 or j_max <= 0:
        return None
    # 峰值加速度受 jerk 限制：v = a²/j ⇒ a ≤ sqrt(v·j)
    a_eff = min(a_max, math.sqrt(v_peak * j_max))
    t1 = a_eff / j_max                       # jerk 上升段
    t3 = t1                                  # jerk 下降段（与 t1 对称）
    v1 = 0.5 * a_eff * t1                    # 第 1 段结束时的速度
    t2 = max(0.0, (v_peak - 2.0 * v1) / a_eff)   # 匀加速段
    x1 = j_max * t1 ** 3 / 6.0
    v2 = v1 + a_eff * t2
    x2 = v1 * t2 + 0.5 * a_eff * t2 ** 2
    v3 = v2 + a_eff * t3 - 0.5 * j_max * t3 ** 2
    x3 = v2 * t3 + 0.5 * a_eff * t3 ** 2 - j_max * t3 ** 3 / 6.0
    return {"a": a_eff, "t1": t1, "t2": t2, "t3": t3, "v1": v1, "v2": v2, "v3": v3,
            "x1": x1, "x2": x2, "x3": x3, "dist": x1 + x2 + x3}


def build_profile(distance: float, v_max: float, a_max: float, j_max: float) -> Profile:
    """构造 7 段 jerk 受限 S 曲线（对称，必要时含匀速段）。

    约定：distance>0 方向为正；velocity/accel 均为带符号量。
    """
    D = abs(float(distance))
    sign = 1.0 if distance >= 0 else -1.0
    if D == 0:
        return Profile(0.0, 0.0, 0.0, j_max, [])

    ap_max = _accel_phase(v_max, a_max, j_max)
    if ap_max is None:
        raise ValueError("v_max / a_max / j_max 必须为正")

    if 2.0 * ap_max["dist"] <= D:
        v_peak = v_max
        ap = ap_max
    else:
        # 行程不够到达 v_max：二分找可达的峰值速度
        lo, hi = 0.0, v_max
        for _ in range(100):
            mid = 0.5 * (lo + hi)
            apm = _accel_phase(mid, a_max, j_max)
            if apm is None or 2.0 * apm["dist"] < D:
                lo = mid
            else:
                hi = mid
        v_peak = 0.5 * (lo + hi)
        ap = _accel_phase(v_peak, a_max, j_max) or ap_max

    a_eff = ap["a"]
    t1, t2, t3 = ap["t1"], ap["t2"], ap["t3"]
    cruise_dist = max(0.0, D - 2.0 * ap["dist"])
    if cruise_dist <= 1e-9 * max(D, 1.0):
        cruise_dist = 0.0          # 二分收敛残差，不值得生成一个零长度匀速段
    cruise_time = cruise_dist / v_peak if v_peak > 0 else 0.0

    segs: list[Segment] = []
    x, v, a = 0.0, 0.0, 0.0
    plan = [
        ("加速-jerk上升", +j_max, t1),
        ("加速-匀加速", 0.0, t2),
        ("加速-jerk下降", -j_max, t3),
        ("匀速", 0.0, cruise_time),
        ("减速-jerk下降", -j_max, t1),
        ("减速-匀减速", 0.0, t2),
        ("减速-jerk上升", +j_max, t3),
    ]
    for name, jerk, dur in plan:
        if dur <= 1e-12:
            continue
        seg = Segment(name, jerk, dur, x, v, a)
        segs.append(seg)
        x, v, a = seg.x1, seg.v1, seg.a1

    if sign < 0:
        for s in segs:
            s.jerk *= -1
            s.x0 *= -1
            s.v0 *= -1
            s.a0 *= -1
        v_peak = -v_peak

    return Profile(distance=D, v_peak=v_peak, a_peak=a_eff, j_max=j_max,
                   segments=segs, cruise_time=cruise_time, cruise_dist=cruise_dist)


def sample(profile: Profile, dt: float = 0.001) -> dict[str, list[float]]:
    """按固定步长采样轨迹。"""
    t: list[float] = []
    x: list[float] = []
    v: list[float] = []
    a: list[float] = []
    now = 0.0
    for seg in profile.segments:
        steps = max(1, int(math.ceil(seg.dur / dt)))
        st = seg.dur / steps
        for i in range(steps + 1):
            tt = i * st
            if t and abs(now + tt - t[-1]) < 1e-12 and i == 0:
                continue
            aa = seg.a0 + seg.jerk * tt
            vv = seg.v0 + seg.a0 * tt + 0.5 * seg.jerk * tt ** 2
            xx = seg.x0 + seg.v0 * tt + 0.5 * seg.a0 * tt ** 2 + seg.jerk * tt ** 3 / 6.0
            t.append(now + tt)
            x.append(xx)
            v.append(vv)
            a.append(aa)
        now += seg.dur
    return {"t": t, "x": x, "v": v, "a": a}


def time_at_position(profile: Profile, target: float, dt: float = 0.0005) -> tuple[float, float] | None:
    """求到达指定位置的 (时刻, 该时刻速度)。位置单调递增时有效。"""
    s = sample(profile, dt)
    for ti, xi, vi in zip(s["t"], s["x"], s["v"]):
        if xi >= target:
            return ti, vi
    return None


# ------------------------------------------------------------------ 伺服/整定估算


def settle_estimate(freq_hz: float, damping: float, accel: float, tol_mm: float) -> dict:
    """给定伺服自然频率与阻尼比，估算最大跟随误差、超调与整定时间。

    稳态加速度输入下的跟随误差 e ≈ a / ωn²（二阶质量-阻尼系统的经典结论）。
    这是「指令加速度给多大才不丢定位精度」的现场判据。

    ⚠ 三条前提（不满足则结果不可用，报告里也会写出来）：
      · **type-2**（位置环 + 速度前馈）：无速度前馈时误差随速度线性增长、不收敛；
      · **a 必须是恒加速度段的加速度**，峰值加速度只作保守上界；
      · **ωn 是等效闭环带宽对应的自然频率**，不是机械固有频率。
    """
    wn = 2.0 * math.pi * freq_hz
    err = accel / (wn ** 2) if wn > 0 else float("inf")
    if damping < 1.0:
        overshoot = math.exp(-damping * math.pi / math.sqrt(1.0 - damping ** 2))
    else:
        overshoot = 0.0
    ts = 4.0 / (damping * wn) if wn > 0 and damping > 0 else float("inf")
    ok = err <= tol_mm
    return {
        "omega_n": wn,
        "follow_error_mm": err,
        "overshoot_pct": overshoot * 100.0,
        "settle_time_s": ts,
        "within_tolerance": ok,
        "max_accel_allowed": tol_mm * wn ** 2,
        "verdict": "跟随误差在容差内" if ok else
                   f"跟随误差 {err:.4f} mm > 容差 {tol_mm:.4f} mm，需把指令加速度降到 "
                   f"{tol_mm * wn ** 2:.1f} mm/s² 以内，或提升伺服带宽",
    }


def stop_distance(v: float, a_max: float, j_max: float) -> float:
    """S 曲线下的制动距离（与加速段对称，精确值）。"""
    ap = _accel_phase(abs(v), a_max, j_max)
    return ap["dist"] if ap else float("inf")


# ------------------------------------------------------------------ 脉冲当量自检


def check_scale(lead_mm: float, encoder_ppr: float, ratio: float, ppr: float,
                configured_ppm: float, travel_mm: float) -> dict:
    """电子齿轮 / 脉冲当量自检。

    lead_mm  丝杆导程 mm/转
    ratio    电机圈数 / 负载圈数
    ppr      电子齿轮设定：电机每转输出的指令脉冲数（如 16384）
    enc_ppr  编码器分辨率 pulse/转
    """
    cmd_ppm = ppr * ratio / lead_mm          # 指令脉冲/mm
    fb_ppm = encoder_ppr * ratio / lead_mm    # 反馈计数/mm
    ppm_err = (configured_ppm - cmd_ppm) / cmd_ppm * 100.0 if cmd_ppm else float("nan")
    pos_err = travel_mm * (1.0 - configured_ppm / cmd_ppm) if cmd_ppm else float("nan")
    return {
        "command_ppm": cmd_ppm,
        "feedback_ppm": fb_ppm,
        "configured_ppm": configured_ppm,
        "scale_error_pct": ppm_err,
        "position_error_at_travel_mm": pos_err,
        "ratio_cmd_to_fb": (cmd_ppm / fb_ppm) if fb_ppm else float("nan"),
        "verdict": ("脉冲当量一致" if abs(ppm_err) < 0.01 else
                    f"脉冲当量偏差 {ppm_err:+.3f}%，在 {travel_mm:.0f} mm 行程上产生 "
                    f"{pos_err:+.4f} mm 定位误差"),
    }


# ------------------------------------------------------------------ 硬件比较输出 / 飞拍


def compare_point(profile: Profile, target_mm: float, counts_per_mm: float,
                  exposure_us: float, max_shift_mm: float = 0.01) -> dict:
    """计算硬件比较输出 / 飞拍触发点，并检查触发质量。"""
    res = time_at_position(profile, target_mm)
    if res is None:
        return {"ok": False, "reason": "目标位置不在本次运动范围内"}
    t_hit, v_hit = res
    # 是否落在匀速段：按段名定位，不依赖分段个数（段数会随参数变化）
    cruise = next((s for s in profile.segments if s.name == "匀速"), None)
    in_cruise = False
    if cruise is not None and cruise.dur > 0:
        t0 = sum(s.dur for s in profile.segments[:profile.segments.index(cruise)])
        t1 = t0 + cruise.dur
        in_cruise = (t0 - 1e-9) <= t_hit <= (t1 + 1e-9)
    shift = abs(v_hit) * (exposure_us * 1e-6)          # 曝光窗口内的位移 mm
    warnings: list[str] = []
    if not in_cruise:
        warnings.append("触发点不在匀速段（加速/减速段触发，位置重复性会显著变差）")
    if shift > max_shift_mm:
        warnings.append(f"曝光窗口内位移 {shift:.4f} mm > 允许 {max_shift_mm} mm，"
                        "应改用编码器触发（飞拍）而非定时/软件触发")
    if abs(v_hit) < 1e-6:
        warnings.append("触发时速度为 0，重复性依赖定位精度而非触发精度")
    return {
        "ok": True,
        "time_s": t_hit,
        "velocity_mm_s": v_hit,
        "in_cruise": in_cruise,
        "compare_counts": target_mm * counts_per_mm,
        "exposure_shift_mm": shift,
        "warnings": warnings,
    }


# ------------------------------------------------------------------ 报告 / CLI 入口


def _profile_report(p: Profile, extra: dict) -> Report:
    rep = Report(title="运动参数验证报告",
                 subtitle="离线计算结果 —— 上机前先把参数算清楚，别用机台当计算器")
    seg_rows = []
    t_acc = 0.0
    for s in p.segments:
        seg_rows.append([s.name, fmt(t_acc, 4), fmt(s.dur, 4), fmt(s.v0, 3),
                         fmt(s.v1, 3), fmt(s.a0, 2), fmt(s.a1, 2)])
        t_acc += s.dur
    rep.add("轨迹分段", "\n".join([
        "距离 {:.4f} mm ｜ 峰值速度 {:.3f} mm/s ｜ 峰值加速度 {:.2f} mm/s² ｜ 峰值 jerk {:.0f} mm/s³".format(
            p.distance, abs(p.v_peak), p.a_peak, p.j_max),
        "",
        "| 段 | 起始时刻(s) | 时长(s) | 起始速度 | 结束速度 | 起始加速度 | 结束加速度 |",
        "|---|---|---|---|---|---|---|",
        *["| {} | {} | {} | {} | {} | {} | {} |".format(*r) for r in seg_rows],
        "",
        f"**总运动时间 {p.total_time:.4f} s**　｜　匀速段 {p.cruise_time:.4f} s"
        f"（{p.cruise_dist:.4f} mm）",
    ]))
    rep.add("关键指标", "\n".join(f"- {k}：{v}" for k, v in extra.items()))
    return rep


def run_plan(distance: float, v_max: float, a_max: float, j_max: float,
             freq_hz: float | None = None, damping: float | None = None,
             tol_mm: float | None = None, out_dir: Path | None = None,
             stem: str = "motion_plan") -> dict[str, Any]:
    p = build_profile(distance, v_max, a_max, j_max)
    s = sample(p, 0.001)

    extra: dict[str, Any] = {
        "总运动时间": f"{p.total_time:.4f} s",
        "峰值速度": f"{abs(p.v_peak):.3f} mm/s",
        "峰值加速度": f"{p.a_peak:.2f} mm/s²",
        "是否达到目标速度": "是" if abs(abs(p.v_peak) - v_max) < 1e-6 else
                          f"否（行程不足，实际峰值 {abs(p.v_peak):.3f} mm/s）",
        "匀速段时间": f"{p.cruise_time:.4f} s",
        "制动距离(S曲线)": f"{stop_distance(abs(p.v_peak), a_max, j_max):.4f} mm",
    }

    warn: list[str] = []
    if freq_hz and damping and tol_mm:
        st = settle_estimate(freq_hz, damping, p.a_peak, tol_mm)
        extra.update({
            "伺服自然频率": f"{freq_hz} Hz",
            "阻尼比": f"{damping}",
            "最大跟随误差": f"{st['follow_error_mm']:.5f} mm",
            "理论超调": f"{st['overshoot_pct']:.1f}%",
            "整定时间(2%)": f"{st['settle_time_s']:.3f} s",
            "允许最大指令加速度": f"{st['max_accel_allowed']:.1f} mm/s²",
        })
        if not st["within_tolerance"]:
            warn.append(st["verdict"])
        extra["跟随误差判定"] = st["verdict"]

    rep = _profile_report(p, extra)
    if freq_hz and damping and tol_mm:
        rep.add("跟随误差估算的前提（不满足就当这份数是错的）", "\n".join([
            "1. **e ≈ a/ωn² 成立于 type-2：位置环 + 速度前馈。** "
            "如果伺服没开速度前馈（type-1），误差会随速度线性增长且**不收敛**，"
            "这个公式不成立 —— 现场表现是「一开机速度就偏、越快偏得越多」。"
            "用 `mcopilot servo diagnose` 看波形：若 SRV-05 命中，说明就是这种情况。",
            "2. **a 指恒加速度段的加速度**，不是峰值加速度。峰值加速度只出现在 S 曲线的"
            "加速段前段（jerk 受限），那几毫秒的瞬态不构成稳态跟随误差。"
            "本报告用峰值加速度算，得到的是**保守上界**。",
            "3. **ωn 必须是等效闭环带宽对应的自然频率**，不是机械固有频率。"
            "直接填伺服手册里的「固有频率」通常偏小 → 算出的跟随误差偏大（偏保守）。",
            "",
            "以上三条不满足时，本节数字只能当量级参考，不能作为放行依据。",
        ]))
    if warn:
        rep.add("⚠ 风险提示", "\n".join(callout("高", w) for w in warn))

    images = []
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        img = chart.save_profile_chart(out_dir / f"{stem}.png", s["t"], s["x"], s["v"], s["a"],
                                       f"S 曲线：{p.distance:.3f} mm")
        if img:
            images.append(img)
    rep.images = images
    return {"profile": p, "report": rep, "warnings": warn}


def run_scale(lead_mm: float, encoder_ppr: float, ratio: float, ppr: float,
              configured_ppm: float, travel_mm: float) -> dict:
    return check_scale(lead_mm, encoder_ppr, ratio, ppr, configured_ppm, travel_mm)


def golden_vectors(cases: Sequence[dict], dt: float = 0.001) -> dict:
    """生成黄金测试向量：同一组参数的轨迹，Python 与 C# 必须一致。"""
    out = []
    for c in cases:
        p = build_profile(c["distance"], c["v"], c["a"], c["j"])
        s = sample(p, dt)
        out.append({
            "case": c.get("name", ""),
            "input": c,
            "expected": {
                "total_time_s": round(p.total_time, 9),
                "peak_velocity_mm_s": round(abs(p.v_peak), 9),
                "peak_accel_mm_s2": round(p.a_peak, 9),
                "cruise_time_s": round(p.cruise_time, 9),
                "end_position_mm": round(p.end_x, 9),
                "end_velocity_mm_s": round(p.end_v, 9),
                "segments": [{"name": sg.name, "jerk": sg.jerk, "duration_s": round(sg.dur, 9),
                              "x0": round(sg.x0, 9), "v0": round(sg.v0, 9), "a0": round(sg.a0, 9)}
                             for sg in p.segments],
            },
            "samples": {"t": [round(v, 9) for v in s["t"]],
                        "x": [round(v, 9) for v in s["x"]],
                        "v": [round(v, 9) for v in s["v"]],
                        "a": [round(v, 9) for v in s["a"]]},
        })
    return {"schema": "mcopilot.golden/1", "dt": dt, "cases": out}
