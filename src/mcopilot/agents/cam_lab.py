"""电子凸轮校验器（cam_lab）：在拿到机台之前，把「这张凸轮表能不能用」算清楚。

对应需求：**Q-05「多轴联动控制：插补算法、电子凸轮、位置比较输出、飞拍、跟随误差补偿、
回零与限位策略」** —— 其中「电子凸轮」是唯一没有任何工具承接的一项（其余分别由
`motion_lab` 的插补/比较点、跟随误差预算覆盖）。

为什么值得单独做一件事：
    凸轮表是**上位机离线就能算的东西** —— 主轴走多快、每一段斜率多大、从轴峰值速度多少、
    断点处速度会不会阶跃，全是纯数值。现场调试时这些往往表现为「从轴抖一下就报跟随误差」，
    但根因是一张表里相邻两段斜率差了点几。

物理（本工具的全部判据都从这两行推出来）：
    设凸轮表为 (m_i, s_i) 断点序列，段内斜率 k_i = Δs_i / Δm_i，主轴速度 θ̇、加速度 θ̈：

        从轴速度      v_s = k_i · θ̇                    （段内）
        从轴加速度    a_s = k_i · θ̈                    （段内，斜率恒定）
        断点速度阶跃  Δv = (k_i − k_{i−1}) · θ̇          ← 机械冲击的来源

    所以：斜率差 × 主轴速度 = 从轴在断点处的速度阶跃；这个阶跃要靠一段过渡段消化，
    过渡段最少要多宽，报告里直接给出来。

不做什么：
    不猜厂商的凸轮表点数上限与枚举语义 —— 那些在 `knowledge/cam_rules.json` 里标着
    「必须查手册」。本工具只做几何与运动学，结论对三家都成立。
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from ..core import chart
from ..core.report import Report, callout
from ..core.util import fmt, knowledge_path, md_table, read_json, write_json, write_text

LEVEL_HIGH = "高"
LEVEL_MID = "中"
LEVEL_LOW = "低"


# ------------------------------------------------------------------ 凸轮表


@dataclass
class CamTable:
    """一张凸轮表：主轴坐标序列 + 从轴坐标序列（一一对应）。"""

    master: list[float]
    slave: list[float]
    source: str = ""
    master_unit: str = "主轴单位"
    slave_unit: str = "mm"
    meta: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.master)

    @property
    def slave_travel(self) -> float:
        return (max(self.slave) - min(self.slave)) if self.slave else 0.0

    @property
    def master_travel(self) -> float:
        return abs(self.master[-1] - self.master[0]) if len(self.master) >= 2 else 0.0

    def slopes(self) -> list[float]:
        out = []
        for i in range(len(self.master) - 1):
            dm = self.master[i + 1] - self.master[i]
            out.append((self.slave[i + 1] - self.slave[i]) / dm if dm else float("nan"))
        return out


def _pick_col(header: list[str], keywords: Sequence[str]) -> int | None:
    low = [h.strip().lower() for h in header]
    for kw in keywords:
        for i, h in enumerate(low):
            if kw in h:
                return i
    return None


def load_table(path: str | Path) -> CamTable:
    """读凸轮表。CSV（两列数值，可带表头）或 JSON。"""
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"凸轮表文件不存在：{p}")
    text = p.read_text(encoding="utf-8-sig")
    if p.suffix.lower() == ".json":
        data = json.loads(text)
        return _table_from_json(data, p.name)
    rows = list(csv.reader(text.splitlines()))
    rows = [r for r in rows if r and any(c.strip() for c in r)]
    if not rows:
        raise SystemExit(f"凸轮表文件是空的：{p}")
    header = rows[0]
    mcol = _pick_col(header, ["master", "主轴", "master_pos", "主轴位置"])
    scol = _pick_col(header, ["slave", "从轴", "slave_pos", "从轴位置"])
    body = rows
    if mcol is None or scol is None:
        # 没有表头 —— 第一行就是数据
        mcol, scol = 0, 1
        body = rows
    master: list[float] = []
    slave: list[float] = []
    for r in body:
        if len(r) <= max(mcol, scol):
            continue
        try:
            mv = float(r[mcol].strip())
            sv = float(r[scol].strip())
        except ValueError:
            continue          # 表头行
        master.append(mv)
        slave.append(sv)
    if len(master) < 2:
        raise SystemExit(f"凸轮表至少要 2 个点，实际读到 {len(master)} 个")
    return CamTable(master=master, slave=slave, source=p.name)


def _table_from_json(data: Any, name: str) -> CamTable:
    master: list[float] = []
    slave: list[float] = []
    if isinstance(data, dict):
        m = data.get("master") or data.get("master_pos") or data.get("主轴")
        s = data.get("slave") or data.get("slave_pos") or data.get("从轴")
        if m is not None and s is not None:
            master = [float(x) for x in m]
            slave = [float(x) for x in s]
        else:
            points = data.get("points") or data.get("table") or []
            for pt in points:
                if isinstance(pt, dict):
                    master.append(float(pt.get("master", pt.get("m"))))
                    slave.append(float(pt.get("slave", pt.get("s"))))
                else:
                    master.append(float(pt[0]))
                    slave.append(float(pt[1]))
    else:
        for pt in data:
            if isinstance(pt, dict):
                master.append(float(pt.get("master", pt.get("m"))))
                slave.append(float(pt.get("slave", pt.get("s"))))
            else:
                master.append(float(pt[0]))
                slave.append(float(pt[1]))
    if len(master) < 2:
        raise SystemExit(f"凸轮表至少要 2 个点，实际读到 {len(master)} 个")
    return CamTable(master=master, slave=slave, source=name)


def write_table(table: CamTable, csv_path: Path, json_path: Path) -> dict[str, Path]:
    lines = ["master,slave"]
    lines += [f"{m:.9g},{s:.9g}" for m, s in zip(table.master, table.slave)]
    return {
        "csv": write_text(csv_path, "\n".join(lines) + "\n"),
        "json": write_json(json_path, {
            "master_unit": table.master_unit,
            "slave_unit": table.slave_unit,
            "master": table.master,
            "slave": table.slave,
            "meta": table.meta,
        }),
    }


# ------------------------------------------------------------------ 校验


def analyze(table: CamTable, master_v: float, master_a: float,
             slave_v_max: float, slave_a_max: float,
             slave_travel_limit: float | None = None,
             omega_hz: float | None = None, tol_mm: float | None = None,
             rules: dict | None = None) -> dict[str, Any]:
    """核心校验：把一张凸轮表放到给定的主轴运动与从轴限值下过一遍。"""
    rules = rules or read_json(knowledge_path("cam_rules.json"))
    defaults = rules.get("defaults", {})
    step_ratio = float(defaults.get("velocity_step_ratio", 0.15))   # 仅作上下文，占峰值速度
    limit_ratio = float(defaults.get("velocity_step_limit_ratio", 0.20))
    warn_ratio = float(defaults.get("velocity_step_warn_ratio", 0.05))
    min_points = int(defaults.get("min_table_points", 4))

    findings: list[dict[str, str]] = []

    def add(level: str, cid: str, msg: str) -> None:
        findings.append({"level": level, "check": cid, "msg": msg})

    m, s = table.master, table.slave
    n = len(m)

    # --- CAM-01 主轴坐标严格单调 ---
    inc = all(m[i + 1] > m[i] for i in range(n - 1))
    dec = all(m[i + 1] < m[i] for i in range(n - 1))
    if not (inc or dec):
        add(LEVEL_HIGH, "CAM-01",
            "主轴坐标不是严格单调的 —— 段与段的插值没有唯一解，"
            "厂商实现与你的预期不可能一致。")
    direction = "递增" if inc else ("递减" if dec else "非单调")

    # --- 分段几何 ---
    segs: list[dict[str, Any]] = []
    for i in range(n - 1):
        dm = m[i + 1] - m[i]
        ds = s[i + 1] - s[i]
        k = ds / dm if dm else float("nan")
        segs.append({
            "index": i + 1,
            "m0": m[i], "m1": m[i + 1],
            "s0": s[i], "s1": s[i + 1],
            "dm": dm, "ds": ds, "k": k,
            "v_slave": abs(k) * master_v,
            "a_slave": abs(k) * master_a,
        })

    # --- CAM-02 从轴峰值速度 ---
    v_peak = max((sg["v_slave"] for sg in segs), default=0.0)
    v_seg = max(segs, key=lambda sg: sg["v_slave"]) if segs else None
    if slave_v_max > 0 and v_peak > slave_v_max:
        add(LEVEL_HIGH, "CAM-02",
            f"第 {v_seg['index']} 段从轴峰值速度 {v_peak:.3f} {table.slave_unit}/s "
            f"> 上限 {slave_v_max:.3f}（超出 {(v_peak / slave_v_max - 1) * 100:.1f}%）。"
            f"降主轴转速或拆段可解决。")

    # --- CAM-03 从轴峰值加速度（主轴加减速贡献）---
    a_peak = max((sg["a_slave"] for sg in segs), default=0.0)
    a_seg = max(segs, key=lambda sg: sg["a_slave"]) if segs else None
    if slave_a_max > 0 and a_peak > slave_a_max:
        add(LEVEL_HIGH, "CAM-03",
            f"第 {a_seg['index']} 段从轴加速度 {a_peak:.2f} {table.slave_unit}/s² "
            f"> 上限 {slave_a_max:.2f}。这段在主轴加减速时从轴会被放大同样倍数 —— "
            f"把主轴的加减速段挪到凸轮生效区间之外。")
    elif master_a > 0 and a_peak > 0:
        add(LEVEL_LOW, "CAM-03",
            f"从轴加速度 {a_peak:.2f} {table.slave_unit}/s²（斜率最大段）"
            f"在上限 {slave_a_max:.2f} 以内。")

    # --- CAM-04 段间速度阶跃 ---
    # 严重度按「阶跃速度 / 从轴速度上限」判，不按「/ 峰值速度」——
    # 峰值速度很小时除以它会把折线逼近误差放大成假警报，
    # 而阶跃速度的绝对大小才是「伺服吸不吸收得了」的依据。
    steps: list[dict[str, Any]] = []
    worst_step = 0.0
    worst_step_entry: dict[str, Any] | None = None
    for i in range(1, len(segs)):
        dk = segs[i]["k"] - segs[i - 1]["k"]
        dv = abs(dk) * master_v
        entry = {
            "at": segs[i]["index"],
            "m": segs[i]["m0"],
            "k_prev": segs[i - 1]["k"], "k": segs[i]["k"],
            "dk": dk, "dv": dv,
            "ratio_of_limit": (dv / slave_v_max) if slave_v_max > 0 else float("nan"),
            "ratio_of_peak": (dv / v_peak) if v_peak > 0 else float("nan"),
            "min_master_width": (dv / slave_a_max) if slave_a_max > 0 else float("nan"),
        }
        steps.append(entry)
        if dv > worst_step:
            worst_step = dv
            worst_step_entry = entry
    if worst_step > 0 and worst_step_entry is not None:
        lim_ratio = worst_step_entry["ratio_of_limit"]
        peak_ratio = worst_step_entry["ratio_of_peak"]
        need = worst_step_entry["min_master_width"]
        if lim_ratio != lim_ratio:      # NaN：从轴速度上限为 0，无法判
            add(LEVEL_LOW, "CAM-04",
                f"最大段间速度阶跃 {worst_step:.3f} {table.slave_unit}/s"
                f"（占峰值 {peak_ratio * 100:.0f}%）。未给从轴速度上限，无法判严重度。")
        elif lim_ratio > limit_ratio:
            add(LEVEL_HIGH, "CAM-04",
                f"第 {worst_step_entry['at']} 段断点处从轴速度阶跃 {worst_step:.3f} "
                f"{table.slave_unit}/s（占从轴速度上限 {lim_ratio * 100:.0f}%，"
                f"阈值 {limit_ratio * 100:.0f}%）。这是机械冲击，伺服会报跟随误差过大。"
                + (f"在断点处加一段过渡段，主轴至少要占 {need:.4f} {table.master_unit}。"
                   if need == need else ""))
        elif lim_ratio > warn_ratio:
            add(LEVEL_MID, "CAM-04",
                f"最大段间速度阶跃 {worst_step:.3f} {table.slave_unit}/s"
                f"（占从轴速度上限 {lim_ratio * 100:.0f}%）。多数伺服能吸收，"
                f"但如果现场听到「咔哒」声或看到跟随误差尖峰，先看这里。")
        else:
            add(LEVEL_LOW, "CAM-04",
                f"最大段间速度阶跃 {worst_step:.3f} {table.slave_unit}/s"
                f"（占从轴速度上限 {lim_ratio * 100:.0f}%，占峰值速度 {peak_ratio * 100:.0f}%），"
                f"在容许范围内。")

    # --- CAM-05 从轴总行程 ---
    travel = table.slave_travel
    if slave_travel_limit and travel > slave_travel_limit:
        add(LEVEL_HIGH, "CAM-05",
            f"凸轮表里从轴坐标跨度 {travel:.3f} {table.slave_unit} > 轴行程 "
            f"{slave_travel_limit:.3f} —— 表里有坐标超出轴的行程范围。")
    else:
        add(LEVEL_LOW, "CAM-05",
            f"从轴坐标跨度 {travel:.3f} {table.slave_unit}"
            + (f"（轴行程 {slave_travel_limit:.3f}，在范围内）" if slave_travel_limit else ""))

    # --- CAM-06 跟随误差预算 ---
    follow = None
    if omega_hz and tol_mm:
        wn = 2.0 * math.pi * omega_hz
        e = a_peak / (wn ** 2) if wn > 0 else float("inf")
        follow = {"omega_n": wn, "follow_error_mm": e, "within": e <= tol_mm}
        if e > tol_mm:
            add(LEVEL_MID, "CAM-06",
                f"从轴跟随误差估算 {e:.5f} mm > 容差 {tol_mm:.5f} mm。"
                f"（e ≈ a/ωn²，只在 type-2 位置环+速度前馈下成立）")
        else:
            add(LEVEL_LOW, "CAM-06",
                f"从轴跟随误差估算 {e:.5f} mm，在容差 {tol_mm:.5f} mm 内。")

    # --- CAM-07 点数与分辨率 ---
    if n < min_points:
        add(LEVEL_LOW, "CAM-07",
            f"凸轮表只有 {n} 个点（建议 ≥ {min_points}）。点数少则厂商按折线插值，"
            f"曲线在断点处是尖角。")
    else:
        add(LEVEL_LOW, "CAM-07",
            f"凸轮表 {n} 个点 / {len(segs)} 段。")

    # --- CAM-08 主轴匀速假设 ---
    if master_a > 0:
        add(LEVEL_MID, "CAM-08",
            f"本表按「主轴在段内匀速」设计。主轴加速度 {master_a:.2f} "
            f"{table.master_unit}/s² 会让从轴时序整体偏移 —— "
            f"让主轴在凸轮生效前就进入匀速段。")

    # --- 从轴换向点 ---
    reversals = []
    for i in range(1, len(segs)):
        if segs[i]["k"] * segs[i - 1]["k"] < 0:
            reversals.append(segs[i]["index"])
    if reversals:
        add(LEVEL_MID, "CAM-04",
            f"第 {'、'.join(str(r) for r in reversals)} 段是从轴换向点。"
            f"换向处速度必须过零 —— 确认你的凸轮表在换向前有减速到零的过渡，"
            f"否则从轴会直接反向冲击。")

    levels = {LEVEL_HIGH: 0, LEVEL_MID: 1, LEVEL_LOW: 2}
    order = sorted(findings, key=lambda f: levels.get(f["level"], 3))
    high = [f for f in findings if f["level"] == LEVEL_HIGH]
    mid = [f for f in findings if f["level"] == LEVEL_MID]
    if high:
        verdict = "不通过：有必须先处理的问题"
        verdict_code = "fail"
    elif mid:
        verdict = "通过，但有需要注意的地方"
        verdict_code = "warn"
    else:
        verdict = "通过：未发现超限或阶跃问题"
        verdict_code = "pass"

    return {
        "segments": segs,
        "steps": steps,
        "findings": order,
        "verdict": verdict,
        "verdict_code": verdict_code,
        "metrics": {
            "points": n,
            "segments": len(segs),
            "master_direction": direction,
            "master_travel": table.master_travel,
            "slave_travel": travel,
            "max_slope": max((abs(sg["k"]) for sg in segs), default=0.0),
            "slave_peak_velocity": v_peak,
            "slave_peak_accel": a_peak,
            "worst_velocity_step": worst_step,
            "worst_velocity_step_ratio": (worst_step / slave_v_max) if slave_v_max > 0 else 0.0,
            "worst_velocity_step_ratio_of_peak": (worst_step / v_peak) if v_peak > 0 else 0.0,
            "follow_error": follow,
        },
        "rules": rules,
    }


# ------------------------------------------------------------------ 生成凸轮表


def plan_table(master_travel: float, slave_travel: float, segments: int,
               master_v: float, slave_v_max: float, slave_a_max: float,
               ramp_points: int = 4,
               slave_ratios: Sequence[float] | None = None) -> tuple[CamTable, list[dict]]:
    """按梯形速度剖面生成一张凸轮表。

    每段内从轴做「加速-匀速-减速」的梯形速度，段与段之间**从轴速度归零**，
    因此段接缝处没有速度阶跃（这是生成的表能做到的最好情况；手画的表通常做不到）。

    段内主轴按匀速 θ̇ 处理，凸轮表坐标 = 主轴位置 → 从轴位置。

    段内求解（这是最容易算错的地方，踩过一次）：
        设该段主轴行程 dm、可用时间 T = dm / θ̇、从轴行程 ds，
        梯形剖面里加速段 t_r、匀速段 t_c = T − 2·t_r，峰值速度 v：

            ds = v·(t_c + t_r) = v·(T − t_r)        →  t_r = T − ds/v
            a_actual = v / t_r ≤ a_max

        把 t_r 代入加速度约束 a_actual ≤ a_max 得二次方程

            v² / a_max − T·v + ds = 0              →  v ∈ [v₋, v₊]

        再叠加「匀速段不能为负」→ v ≤ 2ds/T，以及从轴速度上限 v ≤ v_max。
        **v 必须落在这个区间里**；把 v 往小钳会破坏行程方程（从轴走不到位），
        往大钳会让匀速段变成负数（物理上不存在）。

        取 v = min(v₊, v_max, 2ds/T)；若 v < v₋ 则该段无解（时间不够）。
    """
    if segments < 1:
        raise SystemExit("段数至少为 1")
    if master_v <= 0 or slave_a_max <= 0:
        raise SystemExit("主轴速度与从轴最大加速度必须为正")

    ratios = list(slave_ratios) if slave_ratios else [1.0] * segments
    if len(ratios) != segments:
        raise SystemExit(f"从轴分配比例给了 {len(ratios)} 个，段数是 {segments}，对不上")
    total_r = sum(ratios) or 1.0

    master: list[float] = []
    slave: list[float] = []
    seg_info: list[dict] = []
    m_cursor = 0.0
    s_cursor = 0.0
    rp = max(1, int(ramp_points))

    for i in range(segments):
        dm = master_travel / segments
        ds = slave_travel * ratios[i] / total_r
        t_avail = dm / master_v

        disc = t_avail ** 2 - 4.0 * ds / slave_a_max
        if disc < 0:
            max_ds = t_avail ** 2 * slave_a_max / 4.0
            seg_info.append({
                "index": i + 1, "dm": dm, "ds": ds, "ok": False,
                "why": f"时间不够：主轴走 {dm:.4f}（{t_avail * 1000:.2f} ms）里，"
                       f"从轴按加速度上限 {slave_a_max:.1f} 最多只能走 {max_ds:.4f}，"
                       f"但这一段要求走 {ds:.4f}",
            })
            break
        root = math.sqrt(disc)
        v_minus = 0.5 * slave_a_max * (t_avail - root)
        v_plus = 0.5 * slave_a_max * (t_avail + root)
        v_peak = min(v_plus, slave_v_max, 2.0 * ds / t_avail)
        if v_peak < v_minus:
            seg_info.append({
                "index": i + 1, "dm": dm, "ds": ds, "ok": False,
                "why": f"不可行：从轴速度上限 {slave_v_max:.3f} 低于完成这一段"
                       f"所需的最低速度 {v_minus:.3f}（或主轴时间不足）",
            })
            break
        t_ramp = t_avail - ds / v_peak
        t_cruise = 2.0 * ds / v_peak - t_avail
        a_used = v_peak / t_ramp if t_ramp > 0 else float("inf")

        # 采样：从轴位置随主轴位置推进
        pts: list[tuple[float, float]] = []
        for k in range(1, rp + 1):
            t = t_ramp * k / rp
            pts.append((m_cursor + master_v * t,
                        s_cursor + 0.5 * a_used * t ** 2))
        if t_cruise > 1e-12:
            for k in range(1, rp):
                t = t_ramp + t_cruise * k / rp
                pts.append((m_cursor + master_v * t,
                            s_cursor + 0.5 * v_peak * t_ramp + v_peak * (t - t_ramp)))
        s_end = s_cursor + ds
        for k in range(0, rp + 1):
            t = t_avail - t_ramp + t_ramp * k / rp
            pts.append((m_cursor + master_v * t,
                        s_end - 0.5 * a_used * (t_avail - t) ** 2))

        if not master:
            master.append(m_cursor)
            slave.append(s_cursor)
        for pm, ps in pts:
            # 去掉与前一点完全重合的点（匀速段为 0 时，加减速两段会在接缝处重合）
            if master and abs(pm - master[-1]) < 1e-12 and abs(ps - slave[-1]) < 1e-12:
                continue
            master.append(pm)
            slave.append(ps)

        seg_info.append({
            "index": i + 1, "dm": dm, "ds": ds, "ok": True,
            "v_peak": v_peak, "t_avail": t_avail, "t_ramp": t_ramp,
            "t_cruise": t_cruise, "a_used": a_used, "master_v_used": master_v,
        })
        m_cursor += dm
        s_cursor = s_end

    table = CamTable(master=master, slave=slave, source="cam_lab plan",
                     master_unit="主轴单位", slave_unit="mm",
                     meta={"master_v": master_v, "segments": segments,
                           "slave_v_max": slave_v_max, "slave_a_max": slave_a_max})
    return table, seg_info


# ------------------------------------------------------------------ 厂商能力


def vendor_caps() -> dict[str, Any]:
    return read_json(knowledge_path("cam_rules.json"))


# ------------------------------------------------------------------ 报告


def _seg_table(segs: list[dict], table: CamTable) -> str:
    rows = []
    for sg in segs:
        rows.append([
            sg["index"],
            f'{sg["m0"]:.4g} → {sg["m1"]:.4g}',
            f'{sg["s0"]:.4g} → {sg["s1"]:.4g}',
            f'{sg["k"]:.5g}',
            f'{sg["v_slave"]:.3f}',
            f'{sg["a_slave"]:.2f}',
        ])
    return md_table(
        ["段", f"主轴区间 ({table.master_unit})", f"从轴区间 ({table.slave_unit})",
         "斜率 k", f"从轴峰值速度 ({table.slave_unit}/s)",
         f"从轴加速度 ({table.slave_unit}/s²)"],
        rows)


def _findings_md(findings: list[dict]) -> str:
    out = []
    for f in findings:
        out.append(callout(f["level"], f"[{f['check']}] {f['msg']}"))
    return "\n\n".join(out)


def run_check(table: CamTable, master_v: float, master_a: float,
              slave_v_max: float, slave_a_max: float,
              slave_travel_limit: float | None = None,
              omega_hz: float | None = None, tol_mm: float | None = None,
              out_dir: Path | None = None, stem: str = "cam_check",
              master_unit: str | None = None, slave_unit: str | None = None) -> dict[str, Any]:
    if master_unit:
        table.master_unit = master_unit
    if slave_unit:
        table.slave_unit = slave_unit
    res = analyze(table, master_v, master_a, slave_v_max, slave_a_max,
                  slave_travel_limit, omega_hz, tol_mm)
    met = res["metrics"]
    rep = Report(
        title="电子凸轮表可行性校验报告",
        subtitle="需求 Q-05「电子凸轮」　|　离线计算：段间速度阶跃、从轴峰值速度/加速度、跟随误差预算",
        meta={
            "凸轮表": table.source,
            "点数 / 段数": f"{met['points']} / {met['segments']}",
            "主轴坐标方向": met["master_direction"],
            "主轴行程": f"{met['master_travel']:.4f} {table.master_unit}",
            "从轴坐标跨度": f"{met['slave_travel']:.4f} {table.slave_unit}",
            "最大斜率": f"{met['max_slope']:.5g}",
            "从轴峰值速度": f"{met['slave_peak_velocity']:.3f} {table.slave_unit}/s",
            "从轴峰值加速度": f"{met['slave_peak_accel']:.2f} {table.slave_unit}/s²",
            "最大段间速度阶跃": f"{met['worst_velocity_step']:.3f} {table.slave_unit}/s"
                               f"（占从轴速度上限 {met['worst_velocity_step_ratio'] * 100:.0f}%）",
            "结论": res["verdict"],
        },
    )
    rep.add("结论", "\n".join([
        f"**{res['verdict']}**",
        "",
        _findings_md(res["findings"]),
    ]))
    rep.add("分段明细", _seg_table(res["segments"], table))

    if res["steps"]:
        rows = []
        for st in res["steps"]:
            rows.append([
                f'{st["m"]:.4g}',
                st["at"],
                f'{st["k_prev"]:.5g} → {st["k"]:.5g}',
                f'{st["dk"]:+.5g}',
                f'{st["dv"]:.3f}',
                f'{st["ratio_of_limit"] * 100:.1f}%' if st["ratio_of_limit"] == st["ratio_of_limit"] else "—",
                f'{st["min_master_width"]:.4f}' if st["min_master_width"] == st["min_master_width"] else "—",
            ])
        rep.add("段间接缝（机械冲击的来源）", "\n".join([
            "斜率在断点处一变，从轴速度就跳一次。下表列出每一处跳变，"
            "以及**要把它消化掉、过渡段最少得多宽的主轴行程**。",
            "",
            "严重度看「占从轴速度上限」这一列 —— 阶跃速度的绝对大小才是伺服吸不吸收得了的依据。",
            "",
            md_table([f"主轴位置 ({table.master_unit})", "断点(第几段)", "斜率",
                      "斜率差 Δk", f"速度阶跃 Δv ({table.slave_unit}/s)",
                      "占从轴速度上限", f"过渡段最小主轴宽度 ({table.master_unit})"], rows),
        ]))

    rep.add("这个结论的前提（不满足就别拿它放行）", "\n".join([
        "1. **段内线性插值**。三家厂商的凸轮表都是按点线性插值，本报告的斜率/阶跃计算"
        "建立在这个前提上；若某家是样条插值，阶跃会小于这里的估计。",
        "2. **主轴速度取的是峰值**。阶跃与主轴速度成正比，主轴跑得越快冲击越大 —— "
        "降速是成本最低的缓解手段。",
        "3. **跟随误差用 e ≈ a/ωn²**，只在 type-2（位置环+速度前馈）下成立；"
        "ωn 是等效闭环带宽，不是机械固有频率。",
        "4. **本工具不校验厂商的凸轮表点数上限、凸轮表号数量、枚举语义** —— "
        "那些在 `knowledge/cam_rules.json` 里标着「必须查手册」，"
        "本工具不替你猜。",
    ]))

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        img = chart.save_cam_chart(out_dir / f"{stem}.png", table.master, table.slave,
                                   table.slopes(), f"凸轮表：{table.source}")
        if img:
            rep.images = [img]
    return {"report": rep, "result": res}


def run_plan(master_travel: float, slave_travel: float, segments: int,
             master_v: float, slave_v_max: float, slave_a_max: float,
             slave_ratios: Sequence[float] | None = None,
             ramp_points: int = 4,
             out_dir: Path | None = None, stem: str = "cam_plan") -> dict[str, Any]:
    table, seg_info = plan_table(master_travel, slave_travel, segments, master_v,
                                  slave_v_max, slave_a_max, ramp_points, slave_ratios)
    bad = [s for s in seg_info if not s.get("ok")]
    res = analyze(table, master_v, 0.0, slave_v_max, slave_a_max)
    met = res["metrics"]

    rep = Report(
        title="电子凸轮表生成与自检报告",
        subtitle="需求 Q-05「电子凸轮」　|　按梯形速度剖面生成，段接缝处从轴速度归零",
        meta={
            "主轴行程": f"{master_travel:.4f} 主轴单位",
            "从轴行程": f"{slave_travel:.4f} mm",
            "段数": segments,
            "主轴速度": f"{master_v:.3f} 主轴单位/s",
            "从轴速度上限": f"{slave_v_max:.3f} mm/s",
            "从轴加速度上限": f"{slave_a_max:.2f} mm/s²",
            "生成点数": met["points"],
            "自检结论": res["verdict"],
        },
    )

    if bad:
        rep.add("⚠ 有段做不出来", "\n".join(
            callout("高", f"第 {b['index']} 段：{b['why']}") for b in bad))
        rep.add("已生成的部分（供排查）", _seg_table(res["segments"], table))
    else:
        rows = []
        for sg in seg_info:
            rows.append([
                sg["index"],
                f'{sg["dm"]:.4f}',
                f'{sg["ds"]:.4f}',
                f'{sg["v_peak"]:.3f}',
                f'{sg["a_used"]:.2f}',
                f'{sg["t_avail"]:.4f}',
                f'{sg["t_ramp"]:.4f}',
                f'{sg["t_cruise"]:.4f}',
            ])
        rep.add("分段设计", "\n".join([
            md_table(["段", "主轴区间长", "从轴行程", "从轴峰值速度", "实际加速度",
                      "可用时间", "加速段时间", "匀速段时间"], rows),
            "",
            "每段从轴速度都从 0 起到峰值再回 0，**段接缝处速度为 0，因此没有速度阶跃**。",
            "",
            f"「实际加速度」是这一段真正用到的加速度（≤ 从轴加速度上限 {slave_a_max:.2f} mm/s²）。"
            f"主轴给的时间不够时它会低于上限 —— 这不是 bug，是物理："
            f"主轴转得快、这一段短，从轴就来不及用满加速度。",
        ]))
        rep.add("生成结果的自检", "\n".join([
            _findings_md(res["findings"]),
            "",
            "自检里若出现「段间速度阶跃」，多半是**折线逼近误差**而不是设计问题："
            f"加减速段是抛物线，但厂商凸轮表按点线性插值，"
            f"所以每条斜坡上多打点就能把阶跃压下去（当前 `--ramp-points {ramp_points}`）。"
            f"段与段之间不会有阶跃 —— 那里的从轴速度本来就归零。",
        ]))

    rep.add("下发到控制器前必须做的三件事", "\n".join([
        "1. **转成厂商的凸轮表格式。** 本工具输出的是通用的「主轴坐标 / 从轴坐标」两列，"
        "厂商凸轮表的点数上限、坐标单位、是否含首尾点、SrcMode 之类的枚举语义，"
        "**必须按该品牌函数手册转换**（雷赛 `dmc_cam_table_unit`、正运动凸轮表在控制器侧建立）。",
        "2. **主轴进匀速段之后再使能凸轮。** 本表按主轴段内匀速设计；"
        "主轴还在加减速时使能凸轮，从轴时序会整体偏移。",
        "3. **先在慢速下跑一遍看波形。** 离线算清楚的是「理论上不会超限」，"
        "「实际上不抖」要在机台上看。",
    ]))

    written: dict[str, Path] = {}
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        written = write_table(table, out_dir / f"{stem}_table.csv", out_dir / f"{stem}_table.json")
        img = chart.save_cam_chart(out_dir / f"{stem}.png", table.master, table.slave,
                                   table.slopes(), f"生成的凸轮表（{segments} 段）")
        if img:
            rep.images = [img]
    return {"report": rep, "table": table, "segments": seg_info, "written": written,
            "result": res}


def run_caps(out_dir: Path | None = None, stem: str = "cam_caps") -> dict[str, Any]:
    """三家凸轮能力差异（每条都钉在官方绑定 / DLL 导出表上）。"""
    data = vendor_caps()
    vendors = data["vendors"]
    rep = Report(
        title="电子凸轮能力差异（三家）",
        subtitle="需求 R-03/Q-04「沉淀各品牌能力差异」　|　"
                 "结论全部来自官方 C# 绑定与 DLL PE 导出表，可逐条复核",
        meta={
            "原生长凸轮表": "、".join(k for k, v in vendors.items() if v.get("native_cam_table")),
            "非查表式实现": "、".join(k for k, v in vendors.items() if not v.get("native_cam_table")),
            "可从上位机整表下发": "、".join(k for k, v in vendors.items()
                                            if v.get("table_upload_from_host")) or "无",
        },
    )
    rep.add("这张表为什么必须存在", "\n".join([
        "电子凸轮是三家里**实现方式最不一样**的一项：",
        "",
        md_table(["品牌", "有没有凸轮表", "实现方式", "能从上位机整表下发吗"],
                 [[k, "有" if v.get("native_cam_table") else "**没有**",
                   v.get("mechanism", "—"),
                   ("可以：" + v["table_upload_api"]) if v.get("table_upload_from_host")
                   else ("**不能**（表在控制器侧）" if v.get("native_cam_table") else "不适用（无表）")]
                  for k, v in vendors.items()]),
    ]))
    note = data.get("cross_brand_note", "")
    if note:
        # 放在「这张表」之后单独一段，别紧贴着表格重复一遍
        rep.add("结论", callout("高", note))

    for name, v in vendors.items():
        rows = [[f["fn"], f["dll"], f"`{f['proto']}`", f["source"]] for f in v.get("functions", [])]
        blk = [f"**{name}**", "", md_table(["函数", "DLL", "官方原型", "出处"], rows)]
        if v.get("table_upload_note"):
            blk += ["", f"凸轮表下发：{v['table_upload_note']}"]
        extra = v.get("dll_exported_not_in_csharp_binding") or []
        if extra:
            blk += ["", f"⚠ **DLL 导出表里有、但官方 C# 绑定里没有**（{len(extra)} 个）："
                         f"`{'`, `'.join(extra)}`", "",
                   v.get("dll_exported_not_in_csharp_binding_note", "")]
        else:
            blk += ["", v.get("dll_exported_not_in_csharp_binding_note", "")]
        blk += ["", f"- 上限与枚举：{v.get('limits', '—')}"]
        rep.add(f"{name}", "\n".join(blk))

    rep.add("还必须问厂商的（工具不猜）", "\n".join([
        "- 凸轮表最大点数、凸轮表号数量上限",
        "- 坐标单位（主轴是脉冲/角度/长度？）、首尾点是否闭合",
        "- 多从轴同步、凸轮与插补能否同时用",
        "- 固高：TBufFollowEventCross 的字段语义、跟随段数量上限、GEN 产品线是否有凸轮",
    ]))

    written: dict[str, Path] = {}
    if out_dir:
        written = rep.write(out_dir, stem)
    return {"report": rep, "written": written}
