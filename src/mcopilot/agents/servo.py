"""伺服波形离线诊断器（servo）：**逆向**的那半条链。

motion_lab 做的是正向：由参数算误差（e ≈ a/ωn²）。
本模块做的是逆向：由**实测波形**反推伺服状态与根因。

    实测波形 → 等效二阶参数(ωn, ζ) → 超调/整定时间/振荡频率
            → 跟随误差与速度的相关性 → 候选根因 + 验证方法

三个必须说清楚的前提（否则结论会被误用）：

1. **等效二阶近似**：真实伺服是位置环 PVT（三阶，含机械谐振模式），
   本模块用二阶模型做等效拟合，估出来的是**位置环闭环带宽的等效参数**，
   不是被控对象的物理固有频率。做共振判断时必须再用频响/扫频确认。
2. **跟随误差公式的前提**：e ≈ a/ωn² 成立于 **type-2**（位置环 + 速度前馈）。
   若实测跟随误差与速度近似成正比（斜坡型），说明是 **type-1（无速度前馈）**，
   此时误差随速度线性增长、不收敛 —— 公式不适用，必须改用前馈缺失的判据。
3. **本模块不替代示波器与伺服手册**。它给出的是「该怀疑什么、去测什么」，
   不是「该把增益调到多少」。
"""

from __future__ import annotations

import cmath
import csv
import io
import itertools
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from ..core import chart
from ..core.report import Report, callout, kv_block
from ..core.util import (fmt, knowledge_path, mean, median, percentile, read_json,
                        stdev, write_json)

# ------------------------------------------------------------------ 证据分级
# 「这条波形上的结论算不算数」取决于**波形从哪来**，不取决于工具跑得多认真。
# 仓库自带的 3 个样例是**按物理模型合成的**，真值(.truth.json)与波形**同源**——
# 诊断结果与真值相符只说明「自洽」(同义反复)，**不构成有效性证据**。
# 真实记录(TwinCAT Export10)才是外部证据，但必须配一份**独立基线**才算「已核对」。
# 标签写在 CSV 头(`# provenance: …`)与 .truth.json 里，报告顶部据此标注依据类型。
PROVENANCE_KINDS = {
    "synthetic_fixture": "自造回归夹具（波形与真值同源合成）",
    "synthetic_model_truth": "合成波形 + 解析真值（真值由模型参数算出）",
    "real_record": "真机记录",
    "unknown": "未标注来源",
}
PROVENANCE_EVIDENCE = {
    "synthetic_fixture": "自洽性验证",
    "synthetic_model_truth": "自洽性验证",
    "real_record": "外部证据",
    "unknown": "未知",
}
# 报告顶部横幅：把「依据类型」摆到读者眼前，别让人把夹具上的相符读成准确率。
PROVENANCE_BANNER = {
    "synthetic_fixture":
        "⚠ **本波形是自造回归夹具**：波形与 `.truth.json` 的真值由同一组模型参数生成，"
        "「诊断结果与真值相符」属**自洽性验证（同义反复）**，**不构成有效性证据**。"
        "外部证据请看真实记录（`samples/servo/twincat_export10.csv`）与其独立基线。",
    "synthetic_model_truth":
        "⚠ **本波形是合成数据**：真值由模型参数解析算出，与波形同源 → "
        "「诊断结果与真值相符」属**自洽性验证**，**不构成有效性证据**。",
    "real_record":
        "✅ **本波形是真机记录** → 本报告结论属**外部证据**。"
        "其独立基线（厂商元数据 + 不经本工具的复算）见 `samples/servo/twincat_export10.truth.json`。",
    "unknown":
        "ℹ **本波形未标注来源** → 无法判断依据类型。"
        "若来自真机，请补上独立基线再据此下结论；若来自仿真，请注意真值可能与波形同源。",
}

# 列名别名（中英文都认）
COL_ALIASES = {
    "time": ["time_ms", "t_ms", "time", "t", "timestamp", "时间", "时间戳"],
    "cmd": ["cmd_pos", "cmd", "command", "position_cmd", "指令位置", "指令", "目标位置", "target"],
    "fb": ["fb_pos", "fb", "feedback", "position_fb", "actual", "反馈位置", "反馈", "实际位置"],
    "err": ["err", "error", "follow_err", "following_error", "跟随误差", "误差", "偏差"],
    "vel": ["vel", "velocity", "speed", "速度", "指令速度"],
    "torque": ["torque", "current", "i", "转矩", "电流"],
    "temp": ["temp", "temperature", "motor_temp", "temp_c", "温度", "电机温度"],
}


# ------------------------------------------------------------------ 数据载入


@dataclass
class Waveform:
    t: list[float]                      # 秒
    cmd: list[float] | None
    fb: list[float] | None
    err: list[float] | None
    vel: list[float] | None
    torque: list[float] | None
    source: str = ""
    columns: dict[str, str] = field(default_factory=dict)
    time_unit: str = "s"                # 原始时间列的单位（s / ms / us）
    provenance: str = "unknown"          # 证据来源（见 PROVENANCE_KINDS）
    provenance_detail: dict[str, str] = field(default_factory=dict)  # CSV 头里的其它标注
    # --- 事件层（C6 machine-context：sample/events.jsonl，可选）---
    # 事件流不是波形的一部分，但和它同属一个「样本包」：C6 明确 events.jsonl
    # 放在 C1 样本包内。放这里只是当载体，判据仍按 requires=['events'] 走。
    events: list[dict] | None = None
    events_problems: list[str] = field(default_factory=list)   # 载入时发现的问题
    events_sync: dict | None = None     # verify_events_sync 的产物（C2 event_context.sync）
    # --- 轴铭牌侧车（sample/axis.json，可选）---
    # cpr / pole_pairs / screw_pitch_mm：把谱线频率换算成阶次（每转 k× 或
    # k× 电频率）。这是 C1 样本包里的一份侧车文件，不是 C6 机器上下文对象
    # —— C6 全文没有 cpr 字段（只有 counts_per_mm 且标 L3 待确认），
    # 所以走文件入口，等上游契约版本化后再收编。
    axis: dict | None = None
    axis_problems: list[str] = field(default_factory=list)
    # --- 温度通道（CSV 里多一列 temp，可选）---
    # 与 t 同长度。热漂移判据（SRV-21/22）要的是「慢趋势」，单段记录给出
    # 误差-温度相关与每 K 漂移率；冷/热机配对仍要两段波形，判据里注明。
    temp: list[float] | None = None
    # --- 驱动器参数侧车（sample/drive_params.json，可选）---
    # current_loop_bandwidth_hz 消费；velocity_loop_gain_hz / notch_hz 只登记。
    # C6 契约没有 drive_params 对象，走文件入口（数据来自驱动器手册/调试软件
    # 导出），等上游把 axis.drive_params 版本化后再收编。
    drive_params: dict | None = None
    drive_params_problems: list[str] = field(default_factory=list)
    # --- 扫频（从 cmd 派生，不是新输入文件）---
    # _present_inputs 的 derived_sweep 分支检测 cmd 是否为扫频/chirp 激励，
    # 结果暂存在这里（freqs/coherence/bandwidth 在 compute_signals 里算）。
    sweep: dict | None = None

    @property
    def n(self) -> int:
        return len(self.t)

    @property
    def fs(self) -> float:
        if self.n < 2:
            return 0.0
        dt = [self.t[i + 1] - self.t[i] for i in range(self.n - 1)]
        dt = [d for d in dt if d > 0]
        return 1.0 / mean(dt) if dt else 0.0

    def error_signal(self) -> list[float]:
        """跟随误差 = 指令 - 反馈（约定正号表示「还没追上」）。"""
        if self.err:
            return list(self.err)
        if self.cmd and self.fb:
            return [c - f for c, f in zip(self.cmd, self.fb)]
        return []


def _match_column(fieldnames: Sequence[str], key: str) -> str | None:
    low = {f.strip().lower(): f for f in fieldnames if f}
    for alias in COL_ALIASES[key]:
        if alias.lower() in low:
            return low[alias.lower()]
    # 退而求其次：包含关系
    # ⚠ 只用长度 ≥ 2 的别名做子串匹配：单字母别名（"i"=电流、"t"=时间）
    #   会命中任何含该字母的列名（"time_ms" 里就有 "i" 和 "t"）——
    #   实测踩过：Export10 的 time_ms 被当成了电流通道，于是「缺电流通道」
    #   这件事被判成「有」，F-09 那一族「不可评估」直接失效。
    for alias in COL_ALIASES[key]:
        if len(alias) < 2:
            continue
        for lf, orig in low.items():
            if alias.lower() in lf:
                return orig
    return None


def _time_scale(name: str, raw: Sequence[float], override: str = "auto") -> tuple[float, str]:
    """判定时间列单位，返回 (换算系数, 单位名)。系数乘到原始值上得到秒。

    ⚠ 这里曾经埋过一个 1000 倍的坑：早先只按「数值 > 1e5 就是毫秒」判断，
      而一段 0.8 s 的记录在毫秒口径下最大值只有 800 → 被当成秒 →
      **拟合出的 ωn 直接差 1000 倍**，而报告看上去一切正常。
      所以判定顺序必须是：列名 > 数量级，列名最可靠。

    判定顺序：
      1. 显式指定（CLI --time-unit）优先；
      2. 列名含 ms/毫秒 → 毫秒；含 us/微秒 → 微秒；
      3. 数量级：> 1e11 认为是 epoch 毫秒，> 1e4 认为是毫秒；
      4. 其余按秒。
    """
    if override in ("s", "ms", "us"):
        return {"s": 1.0, "ms": 1e-3, "us": 1e-6}[override], override
    low = (name or "").lower()
    if "us" in low or "µs" in low or "μs" in low or "微秒" in low:
        return 1e-6, "us"
    if "ms" in low or "毫秒" in low:
        return 1e-3, "ms"
    vals = [abs(x) for x in raw if not math.isnan(x)]
    m = max(vals) if vals else 0.0
    if m > 1e11:
        return 1e-3, "ms"      # epoch 毫秒
    if m > 1e4:
        return 1e-3, "ms"
    return 1.0, "s"


def load_waveform(path: Path, time_unit: str = "auto") -> Waveform:
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        # 前导 `#` 注释行是**证据标注**（provenance / 来源 / 用途边界），不是数据。
        # 用 readline 而不是 for 循环：for 循环会预读，break 后第一行数据已经被吃掉。
        prov: dict[str, str] = {}
        first_data: str | None = None
        while True:
            raw = fh.readline()
            if not raw:
                break
            if raw.startswith("#"):
                k, _, v = raw[1:].partition(":")
                prov[k.strip().lower()] = v.strip()
                continue
            first_data = raw
            break
        if first_data is None:
            raise SystemExit("CSV 为空")
        reader = csv.DictReader(itertools.chain([first_data], fh))
        rows = [dict(r) for r in reader]
    if not rows:
        raise SystemExit("CSV 为空")
    names = list(rows[0].keys())
    picked = {k: _match_column(names, k) for k in COL_ALIASES}
    if not picked["time"]:
        raise SystemExit(f"找不到时间列。可用列：{names}；"
                         f"支持的名字：{COL_ALIASES['time']}")

    def series(col: str | None) -> list[float] | None:
        if not col:
            return None
        out = []
        for r in rows:
            try:
                out.append(float(r[col]))
            except (TypeError, ValueError):
                out.append(float("nan"))
        return out

    t_raw = series(picked["time"]) or []
    scale, unit = _time_scale(picked["time"], t_raw, time_unit)
    t = [x * scale for x in t_raw]
    base = t[0] if t else 0.0
    t = [x - base for x in t]

    prov_kind = (prov.get("provenance") or "unknown").strip().lower()
    if prov_kind not in PROVENANCE_KINDS:
        prov_kind = "unknown"

    return Waveform(t=t, cmd=series(picked["cmd"]), fb=series(picked["fb"]),
                    err=series(picked["err"]), vel=series(picked["vel"]),
                    torque=series(picked["torque"]),
                    temp=series(picked["temp"]), source=str(path),
                    time_unit=unit,
                    provenance=prov_kind,
                    provenance_detail={k: v for k, v in prov.items() if k != "provenance"},
                    columns={k: v for k, v in picked.items() if v})


# ------------------------------------------------------------------ 事件层（C6）


EVENT_SOURCES = {"motion", "drive", "interp", "network", "host", "vision",
                 "process", "recipe"}


def load_events(path: Path) -> tuple[list[dict], list[str]]:
    """读 events.jsonl（C6 machine-context §1 的格式）。

    一行一事件，必填 ``t``（秒，**波形时间轴**）/ ``source`` / ``code``；
    可选 ``level`` / ``axis`` / ``detail``（对象）/ ``raw``。

    坏行**不静默丢弃**：计数、取样例、原样带出去 —— 沉默会让报告看起来
    比实际更有把握（C6 对 not_evaluable 的同一条纪律）。

    Returns:
        (事件列表[按 t 升序], 问题清单)
    """
    problems: list[str] = []
    events: list[dict] = []
    n_line = 0
    with io.open(path, encoding="utf-8-sig", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            n_line += 1
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                problems.append(f"L{n_line}: 不是合法 JSON（{exc.msg}）")
                continue
            if not isinstance(obj, dict):
                problems.append(f"L{n_line}: 不是对象")
                continue
            t = obj.get("t")
            if not isinstance(t, (int, float)) or isinstance(t, bool) \
                    or not math.isfinite(float(t)):
                problems.append(f"L{n_line}: t 缺失或不是有限数（code="
                                f"{obj.get('code')!r}）")
                continue
            if not obj.get("source"):
                problems.append(f"L{n_line}: source 缺失（t={t}）")
                continue
            if obj["source"] not in EVENT_SOURCES:
                problems.append(f"L{n_line}: source={obj['source']!r} 不在 C6 "
                                f"枚举里（仍保留该事件，但不参与 source 统计）")
            if not obj.get("code"):
                problems.append(f"L{n_line}: code 缺失（t={t}，"
                                f"source={obj['source']!r}）")
                continue
            detail = obj.get("detail")
            if detail is not None and not isinstance(detail, dict):
                problems.append(f"L{n_line}: detail 不是对象，已忽略")
                detail = None
            events.append({"t": float(t), "level": obj.get("level") or "info",
                           "source": obj["source"], "code": obj["code"],
                           "axis": obj.get("axis"),
                           "detail": detail or {},
                           "line": n_line})
    events.sort(key=lambda e: e["t"])
    if not events:
        problems.append("文件里没有一个可解析的事件")
    return events, problems


def _load_json_sidecar(path, fields: list[str]) -> tuple[dict, list[str]]:
    """侧车 JSON 通用载入（axis.json / drive_params.json 共用）。

    与事件流同一个纪律：**坏字段不静默丢弃**。数值字段必须 > 0 且有限，
    否则记问题并置 0（⟹ 依赖它的判据自动缺位，而不是拿坏值硬算）；
    未知字段保留但不消费。
    """
    problems: list[str] = []
    try:
        with io.open(path, encoding="utf-8-sig") as fh:
            obj = json.load(fh)
    except json.JSONDecodeError as exc:
        return {}, [f"不是合法 JSON（{exc.msg}）"]
    if not isinstance(obj, dict):
        return {}, ["顶层不是对象"]
    out: dict = {}
    for key in fields:
        v = obj.get(key)
        if v is None:
            problems.append(f"{key} 缺失（依赖它的判据将不可用）")
            out[key] = 0.0
            continue
        if isinstance(v, list):
            out[key] = v          # 列表字段（如陷波表）原样保留
            continue
        if not isinstance(v, (int, float)) or isinstance(v, bool) \
                or not math.isfinite(float(v)) or float(v) <= 0:
            problems.append(f"{key}={v!r} 不是正的有限数，已置 0")
            out[key] = 0.0
            continue
        out[key] = float(v)
    for k in obj:
        if k not in fields:
            out.setdefault(k, obj[k])   # 未知字段保留（登记用），不消费
    return out, problems


def load_axis(path) -> tuple[dict, list[str]]:
    """载入轴铭牌侧车（axis.json：cpr / pole_pairs / screw_pitch_mm）。"""
    return _load_json_sidecar(path, ["cpr", "pole_pairs", "screw_pitch_mm"])


def load_drive_params(path) -> tuple[dict, list[str]]:
    """载入驱动器参数侧车（drive_params.json）。

    消费 current_loop_bandwidth_hz（SRV-18 的谐振-带宽比用）；
    velocity_loop_gain_hz / notch_hz 只登记不消费。
    """
    return _load_json_sidecar(
        path, ["current_loop_bandwidth_hz", "velocity_loop_gain_hz", "notch_hz"])


def verify_events_sync(w: Waveform, events: list[dict],
                       th: dict) -> dict:
    """把事件时钟对到波形时间轴上，产出 C2 ``event_context.sync``。

    因果纪律（C2 规则 8 / KB0 A-82）：
    ``causal_claims_permitted`` 当且仅当 ``verified`` 且
    ``alignment_residual_ms ≤ uncertainty_ms``。残差缺键或算不出来 ⟹ 视同
    不成立 —— **「没算出残差」不是「残差合格」，缺证据一侧永远落在禁用侧**。

    方法（anchor_matching）：波形侧取**指令跳变时刻**（阶梯指令每次刷新的跳变，
    每簇第一个跳变 = 起动沿），事件侧取 source=motion 的 move_started。
    配对的中位 |Δt| 就是 ``alignment_residual_ms``（A-82：它是
    「对齐得好不好」，越**小**越好）。
    """
    unc = float(th.get("sync_uncertainty_ms", 5.0))
    win = float(th.get("sync_match_window_ms", 50.0))
    min_pairs = int(th.get("sync_min_anchor_pairs", 3))
    sync: dict[str, Any] = {"method": "anchor_matching", "verified": False,
                            "uncertainty_ms": unc,
                            "alignment_residual_ms": None,
                            "n_anchor_pairs": 0,
                            "causal_claims_permitted": False}

    # 锚点：波形侧 = **指令跳变时刻**（阶梯指令的每次刷新跳变）。
    # 不用指令速度的阈值穿越做锚点 —— 那是居中差分，天生带 ±半窗的超前，
    # 加上阶梯刷新的颗粒度，残差轻松超过时钟预算；跳变时刻本身就是 onset，
    # 精确到一个采样。
    starts = [e["t"] for e in events
              if e["source"] == "motion" and e["code"] == "move_started"]
    if not starts:
        sync["why"] = "事件流里没有 source=motion 的 move_started，无从配对"
        return sync
    cmd = w.cmd
    if not cmd or w.n < 10:
        sync["why"] = "波形太短或无指令列，提不出跳变锚点"
        return sync
    vals = [x for x in cmd if isinstance(x, (int, float)) and math.isfinite(x)]
    if len(vals) < 8:
        sync["why"] = "指令通道有效样本不足"
        return sync
    span = max(vals) - min(vals)
    thr_jump = th.get("cmd_jump_min_ratio", 1e-6) * (span if span > 0 else 1.0)
    jumps: list[float] = []
    for i in range(1, w.n):
        if isinstance(cmd[i], (int, float)) and isinstance(cmd[i - 1], (int, float)) \
                and math.isfinite(cmd[i]) and math.isfinite(cmd[i - 1]) \
                and abs(cmd[i] - cmd[i - 1]) > thr_jump:
            jumps.append(w.t[i])
    if len(jumps) < 3:
        sync["why"] = "指令跳变次数不足，提不出锚点"
        return sync
    # 聚簇：间隔 > 簇间隔的跳变属于下一段运动；每簇的第一个跳变 = 起动沿
    gap = float(th.get("sync_cluster_gap_s", 0.1))
    onsets: list[float] = []
    prev = None
    for t_j in jumps:
        if prev is None or (t_j - prev) > gap:
            onsets.append(t_j)
        prev = t_j
    if not onsets:
        sync["why"] = "波形里提不出起动沿"
        return sync

    residuals: list[float] = []
    # 系统性滞后补偿：move_started 在运动真正开始**之前**发出，而指令阶梯的
    # 第一个可见跳变最早也要等下一次刷新 —— 锚点天然滞后至多一个刷新周期。
    # 这个滞后是方法颗粒度，不是时钟质量：按实测刷新率扣掉，残差才反映
    # 事件时钟与波形时钟的真实错位。
    lead = 0.0
    rf = command_refresh_rate(w, {"cmd_jump_min_ratio": th.get("cmd_jump_min_ratio", 1e-6),
                                  "refresh_max_rate_ratio": th.get("refresh_max_rate_ratio", 0.5)})
    if rf.get("ok"):
        lead = 1.0 / rf["rate_hz"] if rf["rate_hz"] > 0 else 0.0
        if lead > float(th.get("sync_max_lead_s", 0.05)):
            lead = 0.0
    for st in starts:
        cand = [o for o in onsets if -1e-9 <= (o - lead) - st <= win / 1000.0]
        if cand:
            best = min(cand, key=lambda o: abs((o - lead) - st))
            residuals.append(abs((best - lead) - st) * 1000.0)
    sync["n_anchor_pairs"] = len(residuals)
    sync["n_event_anchors"] = len(starts)
    sync["n_wave_anchors"] = len(onsets)
    if len(residuals) < min_pairs:
        sync["why"] = (f"配对成功的锚点只有 {len(residuals)} 对"
                       f"（<{min_pairs}），残差中位数不可信")
        return sync
    residuals.sort()

    def _median(xs: list[float]) -> float:
        n = len(xs)
        return xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])

    med = _median(residuals)
    sync["alignment_residual_ms"] = round(med, 3)
    sync["verified"] = bool(med <= unc)
    sync["causal_claims_permitted"] = bool(sync["verified"] and med <= unc)
    if not sync["verified"]:
        sync["why"] = (f"对齐残差中位数 {med:.1f} ms 超出时钟不确定度预算 "
                       f"{unc:.1f} ms —— 事件与波形不能逐拍对上，"
                       f"因果归因关闭（事件侧统计仍然可用）")
    return sync


# ------------------------------------------------------------------ 信号处理


def dominant_frequency(signal: Sequence[float], fs: float, fmin: float = 0.5,
                       fmax: float | None = None, nfft: int = 512) -> dict:
    """去趋势 + Hann 窗 + DFT，找主频。用纯标准库实现（cmath）。"""
    clean = [x for x in signal if not math.isnan(x)]
    if len(clean) < 32 or fs <= 0:
        return {"ok": False, "reason": "样本不足"}
    n = min(nfft, len(clean))
    seg = clean[:n]
    m = mean(seg)
    # 线性去趋势
    n1 = len(seg)
    xs = list(range(n1))
    mx = mean(xs)
    my = m
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((xs[i] - mx) * (seg[i] - my) for i in range(n1))
    slope = (sxy / sxx) if sxx else 0.0
    intercept = my - slope * mx
    detr = [seg[i] - (intercept + slope * xs[i]) for i in range(n1)]
    amp = max(abs(d) for d in detr) or 1.0
    win = [0.5 - 0.5 * math.cos(2 * math.pi * i / (n1 - 1)) for i in range(n1)]
    xw = [detr[i] * win[i] for i in range(n1)]

    hi = fmax if fmax is not None else min(fs / 2.0, 400.0)
    kmax = min(n1 // 2 - 1, int(hi * n1 / fs))
    kmin = max(1, int(fmin * n1 / fs))
    if kmax <= kmin:
        return {"ok": False, "reason": "频率范围无效"}

    best_k, best_mag = kmin, -1.0
    mags = []
    for k in range(kmin, kmax + 1):
        w = 2.0 * math.pi * k / n1
        acc = 0j
        for i in range(n1):
            acc += xw[i] * cmath.exp(-1j * w * i)
        mag = abs(acc) / n1 * 2.0
        mags.append((k * fs / n1, mag))
        if mag > best_mag:
            best_mag, best_k = mag, k
    peak_hz = best_k * fs / n1
    # 峰值突出度：主频幅值 / 其余幅值中位数
    others = sorted(m for _, m in mags if abs(_ - peak_hz) > 2 * fs / n1)
    med_other = median(others) if others else 0.0
    prominence = (best_mag / med_other) if med_other > 0 else float("inf")
    return {"ok": True, "freq_hz": peak_hz, "amplitude": best_mag,
            "prominence": prominence, "spectrum_top": sorted(mags, key=lambda x: -x[1])[:5],
            "signal_peak": amp,
            # bin 号与分辨率：用来判「报出的主频是不是落在了最低/最高 bin」。
            # 交叉验证 §F-07 就是这么翻车的 —— 2048 点 nfft 下最低 bin 是 0.4883 Hz，
            # 旧口径把去趋势后的残余摆到那里，再除以极小的基线，造出「0.49 Hz / 突出度 238」。
            # 那个数字是**残留**，不是频率。
            "bin": best_k, "resolution_hz": fs / n1,
            "is_edge_bin": bool(best_k <= kmin or best_k >= kmax)}


def zero_crossing_frequency(signal: Sequence[float], fs: float) -> dict:
    """过零法测振铃频率：比峰值法对衰减振荡稳健得多。

    适用对象是**围绕目标值振荡的偏差信号**（fb - target），
    不是跟随误差 err（err 在阶跃瞬间有个大台阶，会污染统计）。
    """
    clean = [x for x in signal if not math.isnan(x)]
    if len(clean) < 32 or fs <= 0:
        return {"ok": False, "reason": "样本不足"}
    crossings = 0
    first = None
    last = None
    prev = clean[0]
    for i in range(1, len(clean)):
        if prev == 0:
            prev = clean[i]
            continue
        if (prev < 0) != (clean[i] < 0):
            crossings += 1
            if first is None:
                first = i
            last = i
        prev = clean[i]
    if crossings < 2 or last is None or first is None:
        return {"ok": False, "reason": "过零点不足（无明显振铃）"}
    # 用尾部若干个过零间隔的中位数，避免起始瞬态的干扰
    dur = (last - first) / fs
    f = (crossings - 1) / (2.0 * dur) if dur > 0 else float("nan")
    return {"ok": True, "freq_hz": f, "crossings": crossings,
            "amplitude": max(clean) - min(clean)}


def _second_order_bandwidth_hz(wn: float, zeta: float) -> float:
    """二阶系统闭环 -3dB 带宽（对任意 ζ 都有定义）。

    ωbw = ωn·√(1−2ζ²+√(4ζ⁴−4ζ²+2))

    旧写法在 ζ>0.707 时退化成 ωn/(2π)（那是自然频率，不是带宽），
    会把「过阻尼但带宽不低」的工况误判成带宽低一半。
    """
    z2 = zeta * zeta
    inner = 4 * z2 * z2 - 4 * z2 + 2
    if inner < 0:
        return wn / (2 * math.pi)
    return wn * math.sqrt(max(0.0, 1.0 - 2 * z2 + math.sqrt(inner))) / (2 * math.pi)


def _model_response(tau: float, wn: float, zeta: float, start: float, target: float) -> float:
    """二阶系统的单位阶跃响应（相对 start→target 归一化）。"""
    if tau <= 0:
        return 0.0
    if zeta < 1.0:
        wd = wn * math.sqrt(1.0 - zeta ** 2)
        y = 1.0 - math.exp(-zeta * wn * tau) * (
            math.cos(wd * tau) + (zeta / math.sqrt(1.0 - zeta ** 2)) * math.sin(wd * tau))
    else:
        y = 1.0 - math.exp(-zeta * wn * tau) * (1.0 + wn * tau)
    return start + (target - start) * y


def fit_second_order(t: Sequence[float], y: Sequence[float], start: float, target: float,
                     t_step: float = 0.0, max_samples: int = 220) -> dict:
    """**最小二乘拟合等效二阶模型**。

    为什么要它：超调法（ζ=−ln(OS)/√(π²+ln²OS)）只在**欠阻尼**响应上成立。
    真实伺服常常是「过阻尼 + 机械谐振模式」，超调接近 0，超调法直接失效。
    拟合法对任何响应形状都能给出「最佳等效二阶参数」。

    ⚠ 拟合出的是**等效**参数，不等于被控对象的物理参数；
       对含谐振模式的系统，等效带宽与真实 -3dB 带宽会有偏差（需实测确认）。
    """
    idx = [i for i in range(len(y)) if t[i] >= t_step]
    if len(idx) < 20:
        return {"ok": False, "reason": "阶跃后样本不足"}
    if len(idx) > max_samples:
        step = len(idx) / max_samples
        idx = [idx[int(i * step)] for i in range(max_samples)]
    taus = [t[i] - t_step for i in idx]
    ys = [y[i] for i in idx]

    span = abs(target - start) or 1.0

    def sse(wn: float, zeta: float) -> float:
        acc = 0.0
        for tau, yv in zip(taus, ys):
            d = _model_response(tau, wn, zeta, start, target) - yv
            acc += d * d
        return acc / span ** 2

    best = (float("inf"), 0.0, 0.0)
    # 粗搜：ωn 对数网格，ζ 线性网格
    wn_lo, wn_hi = 1.0, 2000.0
    for i in range(60):
        wn = wn_lo * (wn_hi / wn_lo) ** (i / 59.0)
        for j in range(25):
            zeta = 0.02 + (1.45 - 0.02) * j / 24.0
            e = sse(wn, zeta)
            if e < best[0]:
                best = (e, wn, zeta)
    # 局部细化
    _, wn0, z0 = best
    for _ in range(3):
        bw, bz = wn0 * 0.12, 0.06
        for i in range(-4, 5):
            wn = wn0 + bw * i / 4.0
            if wn <= 0:
                continue
            for j in range(-4, 5):
                zeta = z0 + bz * j / 4.0
                if zeta <= 0.01 or zeta > 1.6:
                    continue
                e = sse(wn, zeta)
                if e < best[0]:
                    best = (e, wn, zeta)
        _, wn0, z0 = best
    rmse = math.sqrt(best[0]) * span
    wn, zeta = best[1], best[2]
    return {"ok": True, "wn": wn, "zeta": zeta, "rmse": rmse,
            "rel_rmse": math.sqrt(best[0]),
            "bandwidth_hz": _second_order_bandwidth_hz(wn, zeta),
            "theoretical_settle_s": 4.0 / (zeta * wn) if zeta > 0 else float("inf"),
            "freq_hz": wn / (2 * math.pi)}


def peak_spacing_frequency(signal: Sequence[float], fs: float,
                           min_prominence: float = 0.02) -> dict:
    """峰值间距法测振铃频率。

    阶跃响应是**瞬态**，DFT 的能量会被指数衰减包络压到低频；
    而"振铃频率"关心的是相邻波峰之间的周期，用峰值间距更准。
    """
    clean = [x for x in signal if not math.isnan(x)]
    if len(clean) < 16 or fs <= 0:
        return {"ok": False, "reason": "样本不足"}
    m = mean(clean)
    amp = max(abs(x - m) for x in clean) or 1.0
    # 局部极大值
    peaks = []
    for i in range(1, len(clean) - 1):
        if clean[i] >= clean[i - 1] and clean[i] > clean[i + 1]:
            prom = min(clean[i] - clean[i - 1], clean[i] - clean[i + 1])
            if prom / amp >= min_prominence:
                peaks.append(i)
    if len(peaks) < 2:
        return {"ok": False, "reason": "未找到足够波峰（非振铃响应）"}
    # 相邻波峰间隔的中位数（对个别漏检鲁棒）
    gaps = [peaks[i + 1] - peaks[i] for i in range(len(peaks) - 1)]
    gaps.sort()
    mid = gaps[len(gaps) // 2]
    if mid <= 0:
        return {"ok": False, "reason": "波峰间隔为零"}
    return {"ok": True, "freq_hz": fs / mid, "peak_count": len(peaks),
            "amplitude": max(clean[i] for i in peaks) - min(clean[i] for i in peaks)}


def step_metrics(w: Waveform) -> dict:
    """从反馈（或指令）位置提取阶跃响应指标。

    关键：起点必须是**阶跃前一刻**的值。
    早先用「前 10% 样本的中位数」当起点，在响应还没起来时会把起点算到中间，
    导致超调量被放大数倍（实测 25% 被算成 72%）。
    """
    sig = w.fb or w.cmd
    if not sig or w.n < 20:
        return {"ok": False, "reason": "缺少位置通道或样本不足"}
    clean = [x for x in sig if not math.isnan(x)]
    if len(clean) < 20:
        return {"ok": False, "reason": "有效样本不足"}

    k = max(2, len(clean) // 10)
    target = median(clean[-k:])

    # 阶跃起点：指令的最大跳变时刻（若有），否则第一点
    step_t = w.t[0]
    moving_samples = 0
    if w.cmd:
        jumps = [(abs(w.cmd[i] - w.cmd[i - 1]), w.t[i]) for i in range(1, w.n)
                 if not math.isnan(w.cmd[i]) and not math.isnan(w.cmd[i - 1])]
        if jumps:
            # 必须按幅度取最大；直接 max(jumps) 在幅度全为 0（cmd 为常量）时会取到最后一个，
            # 把阶跃点错认成序列末尾，后续分析全部失效。
            best_jump = max(jumps, key=lambda j: j[0])
            if best_jump[0] > 0:
                step_t = best_jump[1]
                # moving 只数阶跃响应窗口内（step 前 50ms ~ 后 500ms）。
                # 全记录计数会把「阶跃 + 之后别的激励」（比如阶跃标定 + 扫频段）
                # 一律打成非阶跃 —— 扫频记录里的阶跃段就没法给 ωn 当参考了。
                # 旧的楼梯刷新记录窗口里全是刷新 tick，行为不变（仍判非阶跃）。
                moving_samples = sum(1 for j, tt in jumps
                                     if j > 1e-9
                                     and step_t - 0.05 <= tt <= step_t + 0.5)

    # 起点 = 阶跃前 20ms 窗口内的中位数（阶跃发生在序列开头时退化为首值）
    pre = [clean[i] for i in range(min(w.n, len(clean)))
           if w.t[i] < step_t and w.t[i] >= step_t - 0.02]
    start = median(pre) if pre else clean[0]
    span = abs(target - start)
    if span < 1e-9:
        return {"ok": False, "reason": "信号没有明显阶跃（首尾差≈0）"}

    peak_i = max(range(len(clean)), key=lambda i: clean[i])
    peak_v = clean[peak_i]
    overshoot = (peak_v - target) / span if peak_v > target else 0.0
    tp = max(0.0, w.t[min(peak_i, w.n - 1)] - step_t)

    band = 0.02 * span
    settle_t = 0.0
    for i in range(len(clean) - 1, -1, -1):
        if abs(clean[i] - target) > band:
            settle_t = (w.t[min(i, w.n - 1)] - step_t)
            break

    # 10%→90% 上升时间（与幅值无关，对任何响应形状都有定义）
    lo_thr = start + 0.1 * (target - start)
    hi_thr = start + 0.9 * (target - start)
    t10 = t90 = None
    for i in range(len(clean)):
        if t10 is None and (clean[i] - start) * (target - start) >= 0:
            if (clean[i] - lo_thr) * (target - start) >= 0:
                t10 = w.t[min(i, w.n - 1)] - step_t
        if t10 is not None and (clean[i] - hi_thr) * (target - start) >= 0:
            t90 = w.t[min(i, w.n - 1)] - step_t
            break
    rise_t = (t90 - t10) if (t10 is not None and t90 is not None) else 0.0

    return {"ok": True, "start": start, "target": target, "span": span,
            "step_time_s": step_t, "peak_value": peak_v, "overshoot_frac": overshoot,
            "peak_time_s": tp, "settle_time_s": settle_t, "rise_time_s": rise_t,
            "t10_s": t10, "t90_s": t90,
            # 指令持续变化的样本数：>2 说明是斜坡/连续运动，不是单次阶跃。
            # 对连续运动套二阶阶跃模型会得到没有物理意义的 ωn，必须挡住。
            "is_step": moving_samples <= 2, "moving_samples": moving_samples}


def estimate_second_order(m: dict) -> dict:
    """由超调与峰值时间反推等效二阶参数 ωn、ζ。

    超调法：OS = exp(-πζ/√(1-ζ²))  ⇒  ζ = -ln(OS)/√(π²+ln²(OS))
    峰值时间：tp = π/(ωn√(1-ζ²))  ⇒  ωn = π/(tp√(1-ζ²))
    """
    out: dict[str, Any] = {"ok": False}
    os_frac = m.get("overshoot_frac", 0.0)
    tp = m.get("peak_time_s", 0.0)
    if os_frac <= 1e-4 or tp <= 0:
        out["reason"] = "超调过小或无明显峰值，参数不可辨识（系统接近临界阻尼）"
        return out
    ln_os = math.log(os_frac)
    zeta = -ln_os / math.sqrt(math.pi ** 2 + ln_os ** 2)
    if not (0.0 < zeta < 1.0):
        out["reason"] = f"由超调 {os_frac:.1%} 反推的阻尼比越界（{zeta:.3f}）"
        return out
    wn = math.pi / (tp * math.sqrt(1.0 - zeta ** 2))
    out.update({"ok": True, "zeta": zeta, "wn": wn,
                "freq_hz": wn / (2 * math.pi),
                "bandwidth_hz": _second_order_bandwidth_hz(wn, zeta),
                "theoretical_settle_s": 4.0 / (zeta * wn) if zeta > 0 else float("inf"),
                "theoretical_overshoot_pct": os_frac * 100.0})
    return out


def constant_accel_window(t: Sequence[float], vel: Sequence[float],
                          cmd_accel: float, tol: float = 0.25) -> tuple[int, int] | None:
    """找出波形里最长的「恒加速度段」。

    为什么必须显式找它：**e ≈ a/ωn² 描述的是恒加速度运动下的稳态跟随误差**。
    阶跃指令的瞬间误差就等于阶跃幅度本身（平凡值），拿它跟 a/ωn² 比毫无意义。
    只有落在恒加速度段里的误差，才可以和这个公式对照。

    判据：实测加速度 a_meas = d(vel)/dt 与 cmd_accel 的偏差在 ±tol 内，
    且实测加速度方向与 cmd_accel 同号。返回最长连续段的 (起, 止) 索引。
    """
    if not vel or len(vel) < 10 or cmd_accel == 0:
        return None
    n = min(len(vel), len(t))
    if n < 10:
        return None
    dt = (t[-1] - t[0]) / (n - 1) if n > 1 else 0.0
    if dt <= 0:
        return None
    acc: list[float] = []
    for i in range(1, n):
        dv = vel[i] - vel[i - 1]
        if math.isnan(dv):
            acc.append(0.0)
        else:
            acc.append(dv / dt)
    if not acc:
        return None
    sign = 1.0 if cmd_accel > 0 else -1.0
    target = abs(cmd_accel)
    best = (0, -1)
    cur_start = None
    for i, a in enumerate(acc):
        ok = (a * sign > 0) and abs(abs(a) - target) <= tol * target
        if ok and cur_start is None:
            cur_start = i
        elif not ok and cur_start is not None:
            if i - cur_start > best[1] - best[0] + 1:
                best = (cur_start, i - 1)
            cur_start = None
    if cur_start is not None and len(acc) - cur_start > best[1] - best[0] + 1:
        best = (cur_start, len(acc) - 1)
    if best[1] < best[0]:
        return None
    return best


def error_analysis(w: Waveform, th: dict | None = None) -> dict:
    """跟随误差统计 + 与速度的相关性（用于判别 type-1 / type-2）。

    另做**常数偏置分解**（mean / std 分离）：
    真实厂商导出的波形里，cmd 与 fb 经常既不是同一根轴、也不是同一个零点，
    于是 cmd−fb 里 99% 是一个**常数偏置**，动态只占 1% —— 直接当跟随误差读，
    会得出「跟随误差 180 mm」这种既无物理意义又极其吓人的数字。
    所以这里把「偏置」和「动态」分开算：偏置单独报出来并标疑，
    判据只用动态部分（详见 docs/交叉验证_Export10.md 的 P0-3）。
    """
    e = w.error_signal()
    if not e:
        return {"ok": False, "reason": "缺少误差通道，且无法由指令/反馈推算"}
    clean = [(w.t[i], e[i]) for i in range(min(len(e), w.n)) if not math.isnan(e[i])]
    vals = [v for _, v in clean]
    peak = max(abs(v) for v in vals)
    rms = math.sqrt(sum(v * v for v in vals) / len(vals))
    mu = mean(vals)
    sd = stdev(vals) if len(vals) > 1 else 0.0

    # 与速度的相关性 + 线性拟合斜率（每 mm/s 产生多少误差）
    vel_corr = None
    slope = None
    vel_ratio_cv = None
    if w.vel and len(w.vel) == w.n:
        pairs = [(w.vel[i], e[i]) for i in range(w.n)
                 if not math.isnan(w.vel[i]) and not math.isnan(e[i])]
        if len(pairs) >= 10:
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            mx, my = mean(xs), mean(ys)
            sxx = sum((x - mx) ** 2 for x in xs)
            sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(len(xs)))
            if sxx > 0:
                slope = sxy / sxx
                syy = sum((y - my) ** 2 for y in ys)
                vel_corr = (sxy / math.sqrt(sxx * syy)) if syy > 0 else None
                # 误差/速度比值的稳定度：真正的 type-1 是 err = k·v（比值恒定）；
                # 机械谐振时误差和速度「一起振荡」，相关系数一样很高，但比值忽大忽小。
                # 只用比值稳定性才能把这两者分开。
                vmax = max(abs(v) for v in xs) or 1.0
                ratios = [e / v for v, e in pairs if abs(v) > 0.5 * vmax]
                if len(ratios) >= 5:
                    rmean = mean(ratios)
                    if abs(rmean) > 1e-12:
                        vel_ratio_cv = stdev(ratios) / abs(rmean)
    # --- 常数偏置分解 -------------------------------------------------
    # 判据（阈值在 knowledge/servo_rules.json）：
    #   · |mean| ≥ 3·std  ⟹ 误差基本是一个常数（偏置主导）
    #   · std ≤ 5%·peak   ⟹ 动态量相对报出的峰值可以忽略
    # 两条同时成立才标「疑似两通道不同轴 / 存在常数偏置」——
    # 只看 std/peak 会把「阶跃瞬间的误差尖峰」误判成偏置（阶跃波形峰值就是阶跃本身）。
    offset_ratio = (sd / peak) if peak > 0 else 0.0
    mean_over_std = (abs(mu) / sd) if sd > 0 else float("inf")
    offset_suspect = False
    if th:
        offset_suspect = bool(
            mean_over_std >= th.get("offset_mean_over_std_min", 3.0)
            and offset_ratio <= th.get("offset_dominant_ratio_max", 0.05))
    # 动态部分（去常数偏置）：判据一律用它，比值类判据才不会被偏置稀释掉
    dyn = [v - mu for v in vals]
    dyn_peak = max(abs(v) for v in dyn) if dyn else 0.0
    dyn_rms = math.sqrt(sum(v * v for v in dyn) / len(dyn)) if dyn else 0.0
    return {"ok": True, "peak": peak, "rms": rms, "mean": mu, "std": sd,
            "offset_ratio": offset_ratio, "mean_over_std": mean_over_std,
            "offset_suspect": offset_suspect,
            "dynamic_peak": dyn_peak, "dynamic_rms": dyn_rms,
            "dynamic_std": sd, "dynamic": dyn,
            "vel_slope": slope, "vel_corr": vel_corr, "vel_ratio_cv": vel_ratio_cv,
            "type2_expected_ratio": None}


# ------------------------------------------------------------------ 诊断规则


def load_rules() -> dict:
    return read_json(knowledge_path("servo_rules.json"))


def diagnose(w: Waveform, rules: dict, cmd_accel: float | None = None) -> dict:
    th = rules["thresholds"]
    # 事件层同步：有事件流就要先做锚点对齐（C2 规则 8 的因果开关）。
    # 放在 diagnose 里而不是入口处 —— 无论从 CLI/MCP/测试哪条路进来都一致。
    if w.events and not w.events_sync:
        w.events_sync = verify_events_sync(w, w.events, th)
        if w.events_problems:
            w.events_sync["load_problems"] = list(w.events_problems)[:20]
            w.events_sync["n_load_problems"] = len(w.events_problems)
    m = step_metrics(w)
    # 只有「单次阶跃」波形才能套二阶阶跃模型；斜坡/连续运动会拟合出没有物理意义的 ωn。
    is_step = bool(m.get("ok")) and m.get("is_step", True)
    so_overshoot = estimate_second_order(m) if (m.get("ok") and is_step) else {
        "ok": False, "reason": "波形不是单次阶跃，超调法不适用"}
    so_fit = {"ok": False, "reason": "缺少位置通道"}
    if m.get("ok") and is_step and w.fb:
        clean_fb = [x for x in w.fb if not math.isnan(x)]
        if len(clean_fb) == w.n:
            so_fit = fit_second_order(w.t, w.fb, m["start"], m["target"], m["step_time_s"])
    # 主用拟合结果；欠阻尼时超调法更准，两者都在报告里列出
    so = so_fit if so_fit.get("ok") else so_overshoot

    ea = error_analysis(w, th)
    fs = w.fs

    # 振铃频率：围绕目标值的偏差信号的过零频率
    ringing = {"ok": False}
    if m.get("ok") and is_step and w.fb and fs > 0:
        dev = [x - m["target"] for x in w.fb]
        ringing = zero_crossing_frequency(dev, fs)
    # 稳态频谱：只看**尾段**的误差。
    # 整段误差是瞬态，DFT 能量会被指数衰减包络压到低频，算出来的「主频」是假的；
    # 只有尾段仍在持续振荡时，频谱峰才是真的持续振荡频率。
    freq: dict = {"ok": False}
    err_sig = w.error_signal()
    if ea.get("ok") and fs > 0 and len(err_sig) >= 64:
        tail = err_sig[len(err_sig) // 2:]
        freq = dominant_frequency(tail, fs, nfft=2048)

    findings: list[dict] = []
    # 既有判据（SRV-01…SRV-07）的实测值：既是结论的量化依据，
    # 也是 C3 契约里 supporting_evidence 的取值来源（值与判定用的是同一批数）。
    legacy_sig: dict[str, Any] = {}
    acc_comparison_done = False
    # 既有判据的状态台账：fired / not_hit / not_evaluable。
    # 契约要求**每条判据都有明确交代** —— 不许让判据悄悄消失
    #（旧实现只记录「命中」和「没执行」，「执行了但没命中」这一档是空的）。
    legacy_status: dict[str, dict] = {}

    def lstate(rid: str, state: str, why: str = "",
               unlocks: list[str] | None = None) -> None:
        legacy_status[rid] = {
            "state": state, "why": why,
            "unlocks": unlocks or ["采一段单次阶跃的波形（指令先保持，再跳变一次）"]}

    def add(fid: str, level: str, title: str, detail: str, impact: str,
            verify: str, requirement: str = "Q-06b") -> None:
        findings.append({"fid": fid, "level": level, "title": title, "detail": detail,
                         "impact": impact, "verify": verify, "requirement": requirement})

    # --- 1) 超调
    # 只报「超调偏大」。超调偏小是整定风格的选择，不是缺陷 —— 报出来只是噪声，
    # 而工具一旦开始报噪声，工程师就不会再看它。真要看阻尼，量化结果表里有 ζ。
    if m.get("ok") and is_step:
        os_pct = m["overshoot_frac"] * 100.0
        if os_pct > th["overshoot_high_pct"]:
            add("SRV-01", "高", "超调量偏大",
                f"超调 {os_pct:.1f}%（阈值 {th['overshoot_high_pct']}%）",
                "整定后仍来回摆动，贴装/点胶的重复精度与节拍都会受影响",
                "看伺服是否处于高增益区；用 mcopilot motion 反推该 ωn 下的跟随误差预算，"
                "再对照实机整定表确认环路增益")
            lstate("SRV-01", "fired")
        else:
            lstate("SRV-01", "not_hit")
    else:
        lstate("SRV-01", "not_evaluable", "波形不是单次阶跃，超调量类判据不适用")

    # --- 2) 振铃频率 → 机械谐振风险
    ring_freq = ringing.get("freq_hz") if ringing.get("ok") else None
    if ring_freq and th["osc_freq_min_hz"] <= ring_freq <= th["osc_freq_max_hz"]:
        add("SRV-02", "高", "位置响应中存在明显周期性振铃",
            f"振铃频率 {ring_freq:.1f} Hz（过零法），落在 "
            f"{th['osc_freq_min_hz']}~{th['osc_freq_max_hz']} Hz 的疑似机械谐振区间",
            "周期性振铃会直接吃掉跟随误差预算，是「偶发定位偏差」的典型根因",
            "在伺服软件里查该频率是否接近某机械传动的固有频率（联轴器/丝杆/皮带）；"
            "做扫频确认；如确认，优先做陷波或降低该频率段的增益")
        lstate("SRV-02", "fired")
    elif m.get("ok") and is_step and ringing.get("ok"):
        lstate("SRV-02", "not_hit")
    else:
        lstate("SRV-02", "not_evaluable", "波形不是单次阶跃，振铃频率类判据不适用")

    # --- 3) 实测跟随误差 vs 理论（type-2 + 恒加速度段 前提）
    # e≈a/ωn² 只在**恒加速度运动**下成立，阶跃瞬间的误差就是阶跃幅度本身，
    # 拿它对比毫无意义。所以必须先在波形里找到恒加速度段，再取该段的误差。
    acc_win = None
    if cmd_accel and w.vel and len(w.vel) == w.n:
        acc_win = constant_accel_window(w.t, w.vel, cmd_accel)
    if so.get("ok") and ea.get("ok") and cmd_accel and acc_win:
        i0, i1 = acc_win
        esig = w.error_signal()
        seg = [abs(esig[i]) for i in range(i0, min(i1 + 1, len(esig)))]
        e_meas = mean(seg) if seg else 0.0
        e_theory = abs(cmd_accel) / (so["wn"] ** 2)
        if e_theory > 0 and e_meas > 0:
            ratio = e_meas / e_theory
            win_ms = (w.t[min(i1 + 1, w.n - 1)] - w.t[i0]) * 1000.0
            legacy_sig["follow_err_ratio"] = ratio
            legacy_sig["accel_window_samples"] = (i1 - i0 + 1)
            acc_comparison_done = True
            if ratio > th["follow_err_ratio_high"]:
                add("SRV-03", "高", "实测跟随误差远大于理论值",
                    f"恒加速度段（{win_ms:.0f} ms）实测均值 {e_meas:.4f} mm，"
                    f"理论 {e_theory:.4f} mm（比值 {ratio:.1f}）",
                    "说明等效模型没覆盖真实行为：前馈补偿不足、惯量比失配或增益整定不准",
                    "核对速度前馈是否开启、前馈系数是否按负载惯量比整定；"
                    "用 mcopilot motion gear 复核脉冲当量与电子齿轮（口径错也会造成偏差）")
                lstate("SRV-03", "fired")
                lstate("SRV-04", "not_hit")
            elif ratio < th["follow_err_ratio_low"]:
                add("SRV-04", "低", "实测跟随误差明显小于理论值",
                    f"恒加速度段（{win_ms:.0f} ms）实测均值 {e_meas:.4f} mm，"
                    f"理论 {e_theory:.4f} mm（比值 {ratio:.2f}）",
                    "说明前馈确实在起作用（type-2 成立），或等效 ωn 估偏大",
                    "以实测为准；用扫频实测带宽校正等效模型，再重算误差预算")
                lstate("SRV-04", "fired")
                lstate("SRV-03", "not_hit")
            else:
                lstate("SRV-03", "not_hit")
                lstate("SRV-04", "not_hit")
        else:
            lstate("SRV-03", "not_hit")
            lstate("SRV-04", "not_hit")
    else:
        if cmd_accel:
            _why = ("给了指令加速度，但波形里找不到恒加速度段（或缺速度通道），"
                    "没有做「实测跟随误差 vs e≈a/ωn²」的对照")
            _unl = ["含匀加速段的轨迹 + CSV 速度列"]
        else:
            _why = "没给指令加速度（--accel），没有做「实测跟随误差 vs e≈a/ωn²」的对照"
            _unl = ["用 --accel 给出指令加速度，并采一段含匀加速段的轨迹 + CSV 速度列"]
        lstate("SRV-03", "not_evaluable", _why, _unl)
        lstate("SRV-04", "not_evaluable", _why, _unl)

    # --- 4) type-1 判据：误差与速度成正比 ⇒ 缺速度前馈
    # 相关系数高只是必要条件；还要求「误差/速度比值恒定」。
    # 机械谐振时误差和速度一起振荡，相关系数一样高，但比值忽大忽小 —— 用比值稳定性分开。
    if (ea.get("ok") and ea.get("vel_corr") is not None
            and ea["vel_corr"] > th["type1_vel_corr_min"]
            and ea.get("vel_ratio_cv") is not None
            and ea["vel_ratio_cv"] < th["type1_vel_ratio_cv_max"]):
        add("SRV-05", "高", "跟随误差与速度高度相关（疑似缺速度前馈）",
            f"err-vel 相关系数 {ea['vel_corr']:.2f}，"
            f"斜率 {ea['vel_slope']:.5f} mm per mm/s"
            f"（误差/速度比值波动 CV={ea['vel_ratio_cv']:.2f}，比值恒定）",
            "误差随速度线性增长，说明是 type-1（位置环无速度前馈）："
            "此时 e≈a/ωn² 不适用，误差不会收敛",
            "确认伺服的速度前馈增益是否开启并按惯量比整定；"
            "开前馈后重采一段波形，用本工具复测（这是可验证的闭环）")
        lstate("SRV-05", "fired")
    elif ea.get("vel_corr") is None or ea.get("vel_ratio_cv") is None:
        lstate("SRV-05", "not_evaluable",
               "缺少速度通道（或误差/速度比值不可算），没做误差-速度相关性判别",
               ["CSV 里的速度列"])
    else:
        lstate("SRV-05", "not_hit")

    # --- 5) 整定时间 vs 理论
    if so_overshoot.get("ok") and m.get("ok") and is_step:
        ts_theory = so_overshoot["theoretical_settle_s"]
        ts_meas = m["settle_time_s"]
        if ts_theory > 0:
            legacy_sig["settle_ratio"] = ts_meas / ts_theory
            legacy_sig["zeta_theory"] = so_overshoot["zeta"]
        if ts_theory > 0 and ts_meas > ts_theory * th["settle_ratio_high"]:
            add("SRV-06", "中", "实际整定时间明显长于二阶模型预测",
                f"实测 {ts_meas * 1000:.0f} ms，理论 {ts_theory * 1000:.0f} ms"
                f"（{ts_meas / ts_theory:.1f} 倍）",
                "实际带宽低于设定值，跟随误差与重复精度都会变差",
                "实测扫频带宽与伺服设定带宽对比；若实测低，优先查机械刚度与惯量辨识")
            lstate("SRV-06", "fired")
        else:
            lstate("SRV-06", "not_hit")
    else:
        lstate("SRV-06", "not_evaluable", "波形不是单次阶跃，整定时间类判据不适用")

    # --- 6) 末段不收敛
    if ea.get("ok") and ringing.get("ok") and m.get("ok") and is_step:
        tail = [x - m["target"] for x in (w.fb or [])][-max(20, w.n // 10):]
        tail_amp = max(abs(v) for v in tail) if tail else 0.0
        if ea["peak"] > 0:
            legacy_sig["tail_ripple_ratio"] = tail_amp / ea["peak"]
            legacy_sig["tail_ripple_freq_hz"] = freq.get("freq_hz") if freq.get("ok") else None
        if ea["peak"] > 0 and tail_amp > ea["peak"] * th["tail_ripple_ratio_min"]:
            add("SRV-07", "中", "到位后跟随误差未收敛（持续波动）",
                f"末段波动幅值 {tail_amp:.4f} mm，占峰值 {tail_amp / ea['peak']:.0%}",
                "定位后仍有余振，重复精度无法保证",
                "检查机械谐振与编码器安装刚性；必要时做陷波或降低该频段增益")
            lstate("SRV-07", "fired")
        else:
            lstate("SRV-07", "not_hit")
    else:
        lstate("SRV-07", "not_evaluable", "波形不是单次阶跃，末段不收敛类判据不适用")

    # ------------------------------------------------------------ 契约层
    # 既有判据的实测值（供 C3 的 supporting_evidence 用；值与判定同源）
    present = _present_inputs(w, rules)
    dg_core = {"metrics": m, "error": ea, "ringing": ringing,
               "second_order_overshoot": so_overshoot}
    signals = compute_signals(w, dg_core, rules, legacy_sig)
    outcomes = evaluate_rules(w, dg_core, rules, signals, present)

    # 既有结论挂上证据（值从 signals 取，与判定用的是同一批数）
    for f in findings:
        meta = rules.get("legacy_rules", {}).get(f["fid"], {}) or {}
        ev: list[dict] = []
        for c in meta.get("evidence", []):
            val = signals.get(c["signal"])
            if val is None:
                continue
            ev.append({"feature": c.get("feature", c["signal"]), "value": val,
                       "operator": c["op"],
                       "threshold": _thr(rules, c["threshold_key"]),
                       "rule_id": f["fid"], "signal": c["signal"],
                       "n_ref": int(c.get("n_ref", meta.get("min_samples", 32))),
                       "source": (f"knowledge/servo_rules.json#legacy_rules.{f['fid']} "
                                  f"(axiscope {'/'.join(meta.get('ax_rules', []))})"),
                       "note": c.get("note", ""),
                       "band_check": bool(c.get("band_check", False))})
        f["evidence"] = ev

    # 新增契约判据（SRV-08…）的命中结论：单列一份，**不改动既有 findings 列表的语义**
    new_findings: list[dict] = []
    for oc in outcomes:
        if oc["state"] != "fired":
            continue
        rule = oc["rule"]
        detail = "；".join(
            f"{e['feature']} = {e['value']:.6g}（判据 {e['operator']} {e['threshold']:.6g}）"
            for e in oc["evidence"])
        new_findings.append({
            "fid": rule["id"], "level": rule.get("severity", "中"),
            "title": rule.get("title", ""), "detail": detail,
            "impact": rule.get("expected_effect", {}).get("direction", ""),
            "verify": "；".join(n.get("ask", "") for n in rule.get("next_data", [])),
            "requirement": "AX " + "/".join(rule.get("ax_rules", [])),
            "fault_mode": rule["fault_mode"], "family": rule.get("family", ""),
            "basis": rule.get("expected_effect", {}).get("basis", "unverified"),
            "evidence": [dict(e) for e in oc["evidence"]],
        })

    # 因前提不满足而**没有执行**的既有判据（F-12：必须显式列出）
    # 「没执行」与「执行了没命中」是两回事，报告里必须分开说。
    skipped: list[dict] = []
    for rid, st in legacy_status.items():
        if st["state"] != "not_evaluable":
            continue
        why = st["why"]
        if not m.get("ok") and "不是单次阶跃" in why:
            why = f"波形里找不到单次阶跃（{m.get('reason', '首尾差≈0')}），{why.split('，', 1)[-1]}"
        skipped.append({"rule_id": rid, "why": why, "unlocks": st["unlocks"]})
    # 新判据里因前提不满足而没执行的，也必须进这张台账（F-12）：
    # 契约要求**每条判据**都有明确交代，不能只在 differential 里留个影子。
    for oc in outcomes:
        if oc["state"] != "not_evaluable":
            continue
        skipped.append({
            "rule_id": oc["id"],
            "why": oc.get("why", "") or oc.get("blocked_by", ""),
            "blocked_by": oc.get("blocked_by", ""),
            "unlocks": list(oc.get("unlocks") or [oc["id"]]),
        })
    legacy_fired = [rid for rid, st in legacy_status.items() if st["state"] == "fired"]
    legacy_not_hit = [rid for rid, st in legacy_status.items() if st["state"] == "not_hit"]

    dg = {"metrics": m, "second_order": so, "second_order_overshoot": so_overshoot,
          "fit": so_fit, "ringing": ringing, "error": ea, "frequency": freq,
          "is_step": is_step, "acc_window": acc_win, "cmd_accel": cmd_accel,
          "findings": findings, "new_findings": new_findings,
          "signals": signals, "rule_outcomes": outcomes,
          "rules_skipped": skipped,
          "legacy_status": legacy_status,
          "rules_not_hit": (legacy_not_hit
                            + [oc["id"] for oc in outcomes if oc["state"] == "not_hit"]),
          "acc_comparison_done": acc_comparison_done,
          "present_inputs": present}
    dg["c3"] = build_c3(w, dg, rules)
    return dg


# ------------------------------------------------------------------ 契约层（axiscope C3 落地）
#
# 分工（照 axiscope 的 C1/C2/C3 划分）：
#   · 信号层（本段前半）：只回答「实测是多少」——相当于 C2；
#   · 本段后半：只回答「按知识库里的判据，这些数字意味着什么」——相当于 C3；
#   · 阈值、判据、fault_mode slug 全部来自 knowledge/servo_rules.json，
#     代码里不写死任何判据数字。
#
# 契约要点（AX C3 不可协商规则）：
#   1  每条结论 ≥2 条 supporting_evidence，不满足的降级到 differential.considered；
#   2  contradicting_evidence 必须显式给（可以为空数组，但字段必须在）；
#   3  differential.not_evaluable 不得为空（除非真的全部可评估）；
#   4  expected_effect.basis 三值；mcopilot 没有仿真器 ⟹ 只能是 rule_heuristic / unverified；
#   5  置信度 < 0.6 时 next_data_to_collect 不得为空；
#   9  「看不见」只能写成 not_evaluable，不许写成「未发现问题」；
#  16  overall_confidence 的缺席扣减按**独立缺席原因**计，不按 not_evaluable 行数。


def _thr(rules: dict, key: str, dynamic: dict | None = None) -> Any:
    """取阈值。运行期量（可靠频带等）从 dynamic 覆盖，其余一律取自知识库。"""
    if dynamic and key in dynamic:
        return dynamic[key]
    return rules["thresholds"][key]


def _finite_index(xs: Sequence[float], ys: Sequence[float]):
    """只保留同时有限的 (下标, x, y)。"""
    n = min(len(xs), len(ys))
    idx, ax, ay = [], [], []
    for i in range(n):
        x, y = xs[i], ys[i]
        if x is None or y is None:
            continue
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        idx.append(i)
        ax.append(float(x))
        ay.append(float(y))
    return idx, ax, ay


def command_velocity(w: Waveform, win_s: float = 0.02) -> list[float]:
    """指令速度（指令位置差分）。长度与 w.t 相同；没有指令通道时返回空表。

    为什么不直接用 w.vel：CSV 里的速度列来源不确定（可能是指令速度、也可能是
    反馈速度），而**加减速段划分必须基于指令**，否则判据会张冠李戴。

    ⚠ 为什么用**跨样本差分**而不是相邻差分：厂商导出的指令常常是「按固定周期
    刷新的阶梯」（导出一次就保持 10 ms）。相邻差分会把速度算成脉冲串
    （0, 0, …, 14 mm/s），于是「指令到底动没动」「加减速段在哪」全判错 ——
    实测在 Export10 上就是这么错的：整段轨迹被当成「静止」。
    """
    if not w.cmd or w.n < 3:
        return []
    idx, t, c = _finite_index(w.t, w.cmd)
    if len(idx) < 3:
        return []
    fs = w.fs or 0.0
    m = 1
    if fs > 0:
        m = max(1, int(round(win_s * fs / 2.0)))
    v = [0.0] * w.n
    for k in range(len(idx)):
        ka = max(0, k - m)
        kb = min(len(idx) - 1, k + m)
        if kb <= ka:
            continue
        dt = t[kb] - t[ka]
        if dt > 0:
            v[idx[k]] = (c[kb] - c[ka]) / dt
    return v


def _diff_velocity(t: Sequence[float], x: Sequence[float],
                   win_s: float = 0.02) -> list[float]:
    """任意位置通道的跨样本中心差分速度（command_velocity 的同款逻辑）。

    为什么不用相邻差分：位置通道（反馈也一样）是按固定周期刷新的阶梯 ——
    相邻差分输出脉冲串（步进那一拍是满速、其余拍是 0），「平均速度掉下来」
    的失速/爬行形态会被刷新纹波完全淹没。中心窗 ≥ 刷新周期，差出来的才是
    平均速度。
    """
    n = len(x)
    v = [0.0] * n
    if n < 3:
        return v
    idx = [i for i in range(n)
           if isinstance(t[i], (int, float)) and isinstance(x[i], (int, float))
           and math.isfinite(t[i]) and math.isfinite(x[i])]
    if len(idx) < 3:
        return v
    dts = [t[idx[k + 1]] - t[idx[k]] for k in range(len(idx) - 1)
           if t[idx[k + 1]] > t[idx[k]]]
    fs = 1.0 / median(dts) if dts else 0.0
    m = max(1, int(round(win_s * fs / 2.0))) if fs > 0 else 1
    for k in range(len(idx)):
        ka = max(0, k - m)
        kb = min(len(idx) - 1, k + m)
        if kb <= ka:
            continue
        dt = t[idx[kb]] - t[idx[ka]]
        if dt > 0:
            v[idx[k]] = (x[idx[kb]] - x[idx[ka]]) / dt
    return v


def command_acceleration(w: Waveform, v: Sequence[float]) -> list[float]:
    """指令加速度（速度的中心差分）。"""
    if not v or w.n < 3:        return []
    a = [0.0] * w.n
    for i in range(1, w.n - 1):
        dt = w.t[i + 1] - w.t[i - 1]
        if dt > 0:
            a[i] = (v[i + 1] - v[i - 1]) / dt
    return a


def _local_error_std(err: Sequence[float], i0: int, i1: int) -> float:
    seg = [err[i] for i in range(i0, min(i1 + 1, len(err))) if math.isfinite(err[i])]
    if len(seg) < 2:
        return 0.0
    mu = mean(seg)
    return stdev([x - mu for x in seg])


def find_steady_window(w: Waveform, th: dict) -> dict | None:
    """找一段**稳态窗**（指令静止或指令等速），供频谱判据使用。

    为什么必须找：跨运动事件开窗算出来的「主频」是假的 —— 瞬态能量会把低频
    撑成一个假峰（这正是旧实现报出「0.49 Hz / 突出度 238」的机制）。
    频域判据的窗口必须落在稳态段，否则整条判据不适用（降级，不是「没发现」）。

    判据用「**指令在窗内能被一条直线拟合**」：直线拟合的残差小 ⟺ 指令在这段里
    要么不动、要么等速；一旦跨越加减速/启停事件，残差立刻变大。
    这个判据是**比例**（残差 / 窗内幅值），所以不受「这段轨迹跑得快还是慢」影响 ——
    用绝对速度阈值去卡就会出问题：Export10 的慢速斜坡（2 mm/s）会被
    「峰值速度的 10%」这种相对门槛筛掉，而它恰恰是唯一有诊断价值的一段。

    选哪一段：在所有候选稳态窗里挑**信息量最大**的一段（窗内误差动态量最大，
    并列取靠后的一段）。「指令一动不动的空窗」对诊断没有价值 ——
    它的误差谱只有噪声，看着「很干净」，其实什么都没测到。
    """
    cmd = w.cmd
    if not cmd or w.n < 32:
        return None
    fs = w.fs or 0.0
    min_len = int(th.get("steady_window_min_samples", 64))
    L = int(th.get("steady_window_len_s", 0.5) * fs) if fs > 0 else w.n
    L = max(L, min_len)
    if L > w.n:
        L = w.n
    step = max(1, L // 4)
    vals = list(cmd)
    gspan = max(vals) - min(vals)
    ratio = th.get("steady_linear_residual_ratio", 0.05)
    flags: list[tuple[int, int, bool, float]] = []
    err = w.error_signal()
    for s in range(0, max(1, w.n - L + 1), step):
        seg = vals[s:s + L]
        if len(seg) < 2:
            break
        rng = max(seg) - min(seg)
        n1 = len(seg)
        mx = (n1 - 1) / 2.0
        my = mean(seg)
        sxx = sum((i - mx) ** 2 for i in range(n1))
        sxy = sum((i - mx) * (seg[i] - my) for i in range(n1))
        slope = (sxy / sxx) if sxx else 0.0
        inter = my - slope * mx
        resid = math.sqrt(sum((seg[i] - (inter + slope * i)) ** 2
                              for i in range(n1)) / n1)
        lim = ratio * max(rng, 0.01 * gspan)
        flags.append((s, s + n1 - 1, resid <= lim,
                      _local_error_std(err, s, s + n1 - 1) if err else 0.0))
    # 合并连续窗（并保留各窗的误差动态量，最后取中位数）
    runs: list[tuple[int, int, list[float]]] = []
    cur: list[int] | None = None
    cur_sd: list[float] = []
    for (s, e, ok, sd) in flags:
        if ok:
            if cur is None:
                cur = [s, e]
                cur_sd = []
            else:
                cur[1] = e
            cur_sd.append(sd)
        elif cur is not None:
            runs.append((cur[0], cur[1], cur_sd))
            cur = None
    if cur is not None:
        runs.append((cur[0], cur[1], cur_sd))
    if not runs:
        return None
    cands: list[dict] = []
    for (i0, i1, sds) in runs:
        if i1 - i0 + 1 < min_len:
            continue
        seg = vals[i0:i1 + 1]
        n1 = len(seg)
        mx = (n1 - 1) / 2.0
        my = mean(seg)
        sxx = sum((i - mx) ** 2 for i in range(n1))
        sxy = sum((i - mx) * (seg[i] - my) for i in range(n1))
        slope = (sxy / sxx) if sxx else 0.0
        cands.append({"i0": i0, "i1": i1, "v_mean": slope, "n": n1,
                      "err_std": median(sds) if sds else 0.0})
    if not cands:
        return None
    v_scale = max(abs(c["v_mean"]) for c in cands) or 0.0
    for c in cands:
        c["kind"] = ("static" if abs(c["v_mean"]) <= 0.01 * v_scale
                     else "constant_velocity")
    statics = [c for c in cands if c["kind"] == "static"]
    best = None
    best_key = None
    for c in cands:
        key = (c["err_std"], c["i0"])
        if best_key is None or key > best_key:
            best, best_key = c, key
    out = dict(best)
    out["static_window"] = ({"i0": statics[-1]["i0"], "i1": statics[-1]["i1"],
                             "n": statics[-1]["n"], "err_std": statics[-1]["err_std"]}
                            if statics else None)
    if statics:
        out["dwell_samples"] = max(c["n"] for c in statics)
    else:
        out["dwell_samples"] = 0
    return out


def _goertzel_bins(x: Sequence[float], t: Sequence[float],
                   freqs: Sequence[float]) -> list[tuple[float, float]]:
    """任意频率点的单通道复 DFT（Goertzel），扫频 H1 用。

    交叉谱要在 cmd/fb 两条通道的**同 bin** 复系数上做（Sxy = X·conj(Y)），
    _spectrum 只给幅度谱，不够用 —— 各跑一次再配对。去均值不去趋势：
    扫频段没有稳态基线可照顾；窗用 Hann 抑泄漏。
    """
    n = min(len(x), len(t))
    mu = sum(x[:n]) / n if n else 0.0
    out: list[tuple[float, float]] = []
    for f in freqs:
        w = 2.0 * math.pi * f
        xr = xi = 0.0
        for i in range(n):
            win = 0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)) if n > 1 else 1.0
            cw = math.cos(w * t[i]) * win
            sw = math.sin(w * t[i]) * win
            xv = x[i] - mu
            xr += xv * cw
            xi -= xv * sw
        out.append((xr, xi))
    return out


def _spectrum(signal: Sequence[float], fs: float, nfft: int = 1024,
              fmin: float = 0.0, fmax: float | None = None) -> dict:
    """去趋势 + Hann 窗 + DFT（纯标准库），返回幅度谱。

    幅度按 Hann 相干增益（0.5）修正，所以 amplitude 就是**该谱线的绝对幅值**，
    可以直接跟「误差动态量级」比 —— 相对突出度做不到这件事。

    只算 [fmin, fmax] 内的 bin（外扩 2 bin 供局部突出度取邻居）：
    频带外的 bin 对判据毫无用处，算它们只是白烧 CPU。
    """
    clean = [x for x in signal
             if isinstance(x, (int, float)) and math.isfinite(x)]
    if len(clean) < 32 or fs <= 0:
        return {"ok": False, "reason": "样本不足"}
    n = min(nfft, len(clean))
    seg = clean[:n]
    m0 = mean(seg)
    mid = (n - 1) / 2.0
    sxx = sum((i - mid) ** 2 for i in range(n))
    sxy = sum((i - mid) * (seg[i] - m0) for i in range(n))
    slope = (sxy / sxx) if sxx else 0.0
    inter = m0 - slope * mid
    detr = [seg[i] - (inter + slope * i) for i in range(n)]
    win = [0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)) for i in range(n)]
    xw = [detr[i] * win[i] for i in range(n)]
    kmax_all = n // 2 - 1
    hi_hz = fmax if fmax is not None else (fs / 2.0)
    k0 = max(0, int(math.floor(fmin * n / fs)) - 2)
    k1 = min(kmax_all, int(math.ceil(hi_hz * n / fs)) + 2)
    mags = []
    for k in range(k0, k1 + 1):
        w = 2.0 * math.pi * k / n
        step = complex(math.cos(-w), math.sin(-w))
        z = 1.0 + 0.0j
        acc = 0.0 + 0.0j
        for i in range(n):
            acc += xw[i] * z
            z *= step
        mags.append((k * fs / n, abs(acc) / n * 4.0, k))
    return {"ok": True, "mags": mags, "resolution_hz": fs / n, "n_used": n,
            "k_range": (k0, k1), "k_max": kmax_all}


def narrowband_line(spec: dict, fmin: float, fmax: float,
                    min_prominence: float) -> dict:
    """在频带里挑一条**窄带**谱线：局部突出度最大者。

    与 `dominant_frequency` 的分工（这是被交叉验证打过的坑）：
      · `dominant_frequency` 找的是**幅值最大**的 bin，输出无量纲的「突出度」；
        在「误差本身很小」的数据上，它会把一条幅值可忽略、但相对突出的谱线
        吹成主角（交叉验证 §F-07：err 里 99.6 Hz 的幅值只有动态 std 的 0.57%，
        却在带内能量占比里占 63.75%）。
      · 本函数找**局部窄带**线（峰幅 vs 峰两侧 ±2 bin 的中位幅），并一律给出
        **绝对幅值**，让判据拿它跟「误差动态量级」比。
    """
    if not spec.get("ok"):
        return {"ok": False, "reason": spec.get("reason", "频谱不可用")}
    by_k = {k: (f, mag) for (f, mag, k) in spec["mags"]}
    kmax = spec.get("k_max", max(by_k) if by_k else 0)
    best = None
    edge_peak = None
    for k, (f, mag) in by_k.items():
        if f < fmin or f > fmax:
            continue
        if edge_peak is None or mag > edge_peak["amplitude"]:
            edge_peak = {"freq_hz": f, "amplitude": mag, "bin": k}
        if k <= 1 or k >= kmax - 1:
            continue          # 最低/最高 bin 不是可分辨的谱线
        others = [by_k[kk][1] for kk in range(k - 2, k + 3) if kk in by_k and kk != k]
        if not others:
            continue
        base = median(others)
        prom = (mag / base) if base > 1e-15 else float("inf")
        if best is None or prom > best["prominence"]:
            best = {"freq_hz": f, "amplitude": mag, "prominence": prom, "bin": k,
                    "base_amplitude": base, "resolution_hz": spec["resolution_hz"]}
    out = {"ok": best is not None, "resolution_hz": spec.get("resolution_hz"),
           "n_used": spec.get("n_used"),
           "edge_peak": edge_peak,
           "edge_peak_is_edge": bool(edge_peak and
                                     (edge_peak["bin"] <= 1 or edge_peak["bin"] >= kmax - 1))}
    if best is None:
        out["reason"] = "频带内没有可分辨的谱线"
        return out
    out.update(best)
    out["usable"] = best["prominence"] >= min_prominence
    return out


def _strongest_narrowband_line(spec: dict, fmin: float, fmax: float,
                               min_prominence: float) -> dict:
    """频带里**幅值最大**且高出带内噪声地板的窄带线。

    与 `narrowband_line`（按邻 bin 突出度选）的两个分工差异：
      · 突出度是**比值**，一条又小又尖的刷新梳齿线（幅值只有动态量的 2%）会在
        比值上赢过幅值 0.2 mm 的物理正弦 —— 配对/归因要的是「真正最强的物理线」，
        所以以幅值排序；
      · 但 Hann 主瓣宽 ±2 bin，强线的邻 bin 本来就是峰的 ~57%，「邻 bin 中位数」
        当门槛会把所有真线全杀掉。门槛改用**带内幅值中位数（噪声地板）的倍数**：
        纯噪声的谱，峰最多是地板的 2~3 倍，过不了；真线轻松高出一个量级。
    """
    if not spec.get("ok"):
        return {"ok": False, "reason": spec.get("reason", "频谱不可用")}
    mags = [(f, mag, k) for (f, mag, k) in spec["mags"] if fmin <= f <= fmax]
    if len(mags) < 8:
        return {"ok": False, "reason": "带内 bin 不足"}
    floor = median([m for _, m, _ in mags])
    if floor <= 0:
        floor = 1e-15
    best = None
    for f, mag, k in mags:
        if mag >= min_prominence * floor and (best is None or mag > best[1]):
            best = (f, mag, k, mag / floor)
    if best is None:
        return {"ok": False, "reason": "带内没有高出噪声地板的窄带线"}
    return {"ok": True, "freq_hz": best[0], "amplitude": best[1],
            "bin": best[2], "prominence": best[3]}


def _line_is_refresh_harmonic(f: float, sig: dict, th: dict) -> bool:
    """谱线频率 f 是否落在指令刷新线或其谐波上（±5%）。

    刷新成分是「真实存在但属于指令流」的谱线：它同时出现在 cmd/fb/err 三条
    通道里。凡是要拿谱线频率做**物理归因**的场合（谐振配对、阶次结构），
    必须先把这类线排除，否则 47 Hz 的纹波会配到 100 Hz 的刷新线上。
    """
    r = sig.get("refresh_rate_hz")
    if not r or r <= 0 or not f or f <= 0:
        return False
    tol = float(th.get("refresh_harmonic_tol", 0.05))
    n_max = int(f * (1.0 + tol) / r) + 1
    return any(abs(f - k * r) <= tol * k * r for k in range(1, n_max + 1))


def command_refresh_rate(w: Waveform, th: dict, win: dict | None = None) -> dict:
    """指令刷新率：cmd 通道跳变间隔的中位数。

    测量范围是**整段记录**：刷新率是指令流本身的属性，跟当前在不在动无关。
    （早期版本只量稳态窗，结果 Export10 的稳态窗正好落在指令完全静止的空窗里，
      跳变次数为 0、刷新率测不出来 —— 而那恰恰是最容易把刷新线当成对象响应的场景。）

    为什么必须测它：上位机按固定周期刷新指令，cmd 于是带一个固定周期的成分，
    这条线会**真实地**同时出现在 cmd / fb / err 三条通道里（轴跟着指令走）——
    它**不是伪谱线**，但它属于**指令刷新成分**，不是被控对象的响应。
    判据必须把它排除，否则 100 Hz 的刷新线会被当成机械谐振。
    """
    if not w.cmd:
        return {"ok": False, "reason": "缺少指令通道"}
    vals = [x for x in w.cmd if math.isfinite(x)]
    if len(vals) < 8:
        return {"ok": False, "reason": "指令通道有效样本不足"}
    span = max(vals) - min(vals)
    thr = th.get("cmd_jump_min_ratio", 1e-6) * (span if span > 0 else 1.0)
    times = []
    for i in range(1, w.n):
        if not (math.isfinite(w.cmd[i]) and math.isfinite(w.cmd[i - 1])):
            continue
        if abs(w.cmd[i] - w.cmd[i - 1]) > thr:
            times.append(w.t[i])
    if len(times) < 3:
        return {"ok": False, "reason": "指令跳变次数不足（无法测刷新率）"}
    gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)
            if times[i + 1] - times[i] > 0]
    if len(gaps) < 2:
        return {"ok": False, "reason": "跳变间隔不足"}
    med = median(gaps)
    if med <= 0:
        return {"ok": False, "reason": "跳变间隔为零"}
    rate = 1.0 / med
    fs = w.fs or 0.0
    if fs > 0 and rate >= th.get("refresh_max_rate_ratio", 0.5) * fs:
        # 跳变间隔≈采样周期：测到的是「每采一个样动一次」，不是刷新
        return {"ok": False, "reason": "跳变间隔≈采样周期，测到的是采样而不是刷新",
                "rate_hz": rate, "interval_s": med, "n_jumps": len(times)}
    out = {"ok": True, "rate_hz": rate, "interval_s": med, "n_jumps": len(times),
           "jump_threshold": thr}
    if win:
        out["window"] = {"i0": win["i0"], "i1": win["i1"]}
    return out


def _quantization_step(fb: Sequence[float], tol: float) -> float | None:
    """位置反馈的量化台阶（counts）。反馈是连续量时返回 None。

    估法：取所有非零 |Δ| 的低分位作候选 q，再验证「所有 |Δ| 都接近 q 的整数倍」；
    验证不过 ⟹ 反馈是连续的，量化台阶无定义（不是 0）。
    """
    vals = [x for x in fb if isinstance(x, (int, float)) and math.isfinite(x)]
    if len(vals) < 16:
        return None
    deltas = sorted(abs(vals[i + 1] - vals[i]) for i in range(len(vals) - 1)
                    if abs(vals[i + 1] - vals[i]) > 0)
    if len(deltas) < 8:
        return None
    q = deltas[max(0, int(0.1 * len(deltas)) - 1)]
    if q <= 0:
        return None
    bad = 0
    for d in deltas:
        k = d / q
        if abs(k - round(k)) > tol:
            bad += 1
    if bad > 0.02 * len(deltas):
        return None
    return q


def _detect_chirp(w: Waveform, rules: dict) -> dict:
    """检测 cmd 是否为扫频/chirp 激励（SRV-19 的 derived_sweep 门槛）。

    口径：去均值后数过零间隔——相邻过零间距 = 半周期 ⟹ 瞬时频率。
    扫频的判据是**频率跨度**：瞬时频率最小/最大值之差 ≥ 阈值、且覆盖到
    足够高的频段。普通多段运动指令是单调斜坡，过零接近 0，天然不误判。
    """
    out: dict = {"ok": False, "f_lo": None, "f_hi": None, "n_cross": 0}
    if not w.cmd or len(w.cmd) < 512 or w.n < 2:
        out["why"] = "cmd 缺失或太短，不足以检测扫频"
        return out
    fs = w.fs
    # 局部基线：0.5 s 块中位数。扫频激励骑在位置保持值上方（比如在 30 mm 处
    # 摆动），减全局均值永远碰不到零线 —— 基线必须跟着位置走。
    blk = max(8, int(0.5 * fs))
    baselines = []
    for i0 in range(0, w.n, blk):
        seg = sorted(x for x in w.cmd[i0:i0 + blk]
                     if isinstance(x, (int, float)) and math.isfinite(x))
        baselines.append(median(seg) if seg else 0.0)
    x_prev = None
    cross: list[float] = []
    for i in range(w.n):
        c = w.cmd[i]
        if not isinstance(c, (int, float)) or not math.isfinite(c):
            x_prev = None
            continue
        x = c - baselines[min(i // blk, len(baselines) - 1)]
        if x_prev is not None and (x_prev < 0) != (x < 0):
            cross.append(w.t[i])
        x_prev = x
    out["n_cross"] = len(cross)
    if len(cross) < int(rules_th(rules, "sweep_cross_min", 30)):
        out["why"] = f"cmd 过零仅 {len(cross)} 次，不像扫频激励"
        return out
    freqs = [1.0 / (2.0 * (cross[i] - cross[i - 1])) for i in range(1, len(cross))
             if cross[i] > cross[i - 1]]
    # 端点过零间隔受边界效应影响，去掉首尾各 1 个再统计
    core = freqs[1:-1] if len(freqs) > 4 else freqs
    if len(core) < 8:
        out["why"] = "过零样本太少，瞬时频率不可统计"
        return out
    s = sorted(core)
    f_lo = s[int(0.05 * len(s))]           # 5%/95% 分位，抗孤立间隔抖动
    f_hi = s[int(0.95 * len(s))]
    out["f_lo"], out["f_hi"] = f_lo, f_hi
    if f_hi < rules_th(rules, "sweep_f_hi_min_hz", 20.0):
        out["why"] = (f"扫频上端频率 {f_hi:.1f} Hz 低于 "
                      f"{rules_th(rules, 'sweep_f_hi_min_hz', 20.0):.0f} Hz，"
                      f"带宽读数没有说服力")
        return out
    if f_hi - f_lo < rules_th(rules, "sweep_f_span_min_hz", 15.0):
        out["why"] = f"扫频跨度 {f_hi - f_lo:.1f} Hz 太窄，不是有效扫频"
        return out
    # 簇窗口：过零间隔 >0.5 s 视为断开。阶跃边沿是孤立过零，和密集的
    # chirp 过零天然分簇 —— FRF 只吃最长簇的窗口，阶跃段的能量不许混进来
    # （30 mm 阶跃的低频能量会淹没 3 mm chirp 的频响，实测踩过）。
    clusters: list[list[float]] = [[cross[0]]]
    for tc in cross[1:]:
        if tc - clusters[-1][-1] > 0.5:
            clusters.append([tc])
        else:
            clusters[-1].append(tc)
    best = max(clusters, key=len)
    min_win = rules_th(rules, "sweep_window_min_s", 2.0)
    if len(best) < int(rules_th(rules, "sweep_cross_min", 30)) \
            or best[-1] - best[0] < min_win:
        out["why"] = (f"扫频簇太短（{best[-1] - best[0]:.1f} s / "
                      f"{len(best)} 次过零），FRF 没有说服力")
        return out
    out["t0"], out["t1"] = best[0], best[-1]
    # 频率上下限按**时间加权**：瞬时频率先在每个过零点取值，再线性插值到
    # 0.05 s 均匀时间网格上取分位。不能直接对过零样本取分位——每秒过零数
    # ∝ f，高频端被过采样，2 Hz 起步的线性扫频 f_lo 会被抬到 13.5 Hz
    # （实测踩过：bin 网格整个错过通带，带宽读数全是滚降上的垃圾）；
    # 也不能按 0.1 s 槽取——低频段过零间隔比槽还宽，槽是空的。
    fs_pts = [(best[i], 1.0 / (2.0 * (best[i] - best[i - 1])))
              for i in range(1, len(best)) if best[i] > best[i - 1]]
    n_grid = max(16, int((best[-1] - best[0]) / 0.05))
    per_t: list[float] = []
    pt = 0
    for gi in range(n_grid):
        tt = best[0] + (best[-1] - best[0]) * gi / (n_grid - 1)
        while pt < len(fs_pts) - 2 and fs_pts[pt + 1][0] < tt:
            pt += 1
        (ta, fa), (tb, fbq) = fs_pts[pt], fs_pts[min(pt + 1, len(fs_pts) - 1)]
        if tb <= ta:
            per_t.append(fa)
        else:
            wgt = min(1.0, max(0.0, (tt - ta) / (tb - ta)))
            per_t.append(fa + wgt * (fbq - fa))
    per_t.sort()
    if len(per_t) < 8:
        out["why"] = "扫频簇内瞬时频率样本太少"
        return out
    # 2%/98%：要逼近扫频的真实端点——bin 网格的下端必须盖住系统通带，
    # g0（低频平台）才有意义；取 5% 分位会把下端抬进滚降区（实测踩过）
    out["f_lo"] = per_t[max(0, int(0.02 * (len(per_t) - 1)))]
    out["f_hi"] = per_t[min(len(per_t) - 1, int(0.98 * (len(per_t) - 1)))]
    if out["f_hi"] < rules_th(rules, "sweep_f_hi_min_hz", 20.0):
        out["why"] = (f"扫频上端频率 {out['f_hi']:.1f} Hz 低于 "
                      f"{rules_th(rules, 'sweep_f_hi_min_hz', 20.0):.0f} Hz，"
                      f"带宽读数没有说服力")
        return out
    if out["f_hi"] - out["f_lo"] < rules_th(rules, "sweep_f_span_min_hz", 15.0):
        out["why"] = f"扫频跨度 {out['f_hi'] - out['f_lo']:.1f} Hz 太窄，不是有效扫频"
        return out
    out["ok"] = True
    return out


def rules_th(rules: dict, key: str, default: float) -> float:
    """知识库阈值读取的容错包装（_detect_chirp 在 KB 外也能跑）。"""
    try:
        v = _thr(rules, key)
        return float(v)
    except Exception:
        return float(default)


def _present_inputs(w: Waveform, rules: dict) -> dict:
    """哪些输入真的在场（不是「CSV 里有这一列的名字」，而是「这一列有有效数据」）。

    「不在场」是契约里 not_evaluable 的根因，所以口径必须统一：
    有列但整列为 NaN 的，等于不在场。
    """
    spec = rules.get("inputs_present", {}) or {}
    out: dict[str, bool] = {}
    for key, kind in spec.items():
        if kind == "channel_or_derived":
            # err 通常是派生列（cmd−fb）：有 cmd 或 fb 就能算
            out[key] = bool(w.cmd or w.fb)
            continue
        if kind == "events_file":
            # C6 events.jsonl：由 load_events 载入后挂在样本包上。
            # 「在文件里」不等于「可用」：一个事件都没有等于不在场。
            out[key] = bool(w.events)
            continue
        if kind == "derived_fb_velocity":
            # 编码器速度反馈可以从 fb 差分派生（caps.derived_velocity_feedback
            # 会给用它的判据封顶）。CSV 的 vel 列常常是**指令**速度，不能冒充。
            out[key] = bool(w.fb) and sum(
                1 for x in w.fb if isinstance(x, (int, float))
                and math.isfinite(x)) >= 10
            continue
        if kind == "axis_sidecar":
            # axis.json 铭牌：cpr + pole_pairs 都 >0 才够做阶次归因
            ax = w.axis or {}
            out[key] = bool(ax.get("cpr", 0) > 0 and ax.get("pole_pairs", 0) > 0)
            continue
        if kind == "drive_params_sidecar":
            # drive_params.json：至少要电流环带宽才能做谐振-带宽比
            dp = w.drive_params or {}
            out[key] = bool(dp.get("current_loop_bandwidth_hz", 0) > 0)
            continue
        if kind == "events_recipe":
            # recipe 上下文（C6 本来就有：fe_spike_aligned_to_recipe_change、
            # step_labels）：事件流里埋了 recipe_change 事件才算在场
            out[key] = any(e.get("code") == "recipe_change"
                           for e in (w.events or []))
            continue
        if kind == "derived_sweep":
            # 扫频不是新文件：cmd 本身是 chirp/扫频激励即可。
            # 检测结果暂存 w.sweep，compute_signals 的 FRF 段接着用。
            w.sweep = _detect_chirp(w, rules)
            out[key] = bool(w.sweep.get("ok"))
            continue
        if kind != "channel":
            out[key] = False
            continue
        series = getattr(w, key, None)
        out[key] = bool(series) and any(
            isinstance(x, (int, float)) and math.isfinite(x) for x in series)
    return out


def compute_signals(w: Waveform, dg: dict, rules: dict,
                    legacy: dict | None = None) -> dict:
    """信号层：把波形换算成**实测信号量**。判据与阈值不在这里。"""
    th = rules["thresholds"]
    cm = rules["confidence_model"]
    fs = w.fs or 0.0
    sig: dict[str, Any] = {}
    sig.update(legacy or {})

    m = dg.get("metrics", {}) or {}
    ea = dg.get("error", {}) or {}
    ringing = dg.get("ringing", {}) or {}

    # --- 频带（C2 规则 7：可靠频带 = 奈奎斯特 / 1.25）---
    nyq = fs / 2.0 if fs > 0 else 0.0
    rel_band = nyq / th.get("band_reliable_divisor", 1.25) if nyq > 0 else 0.0
    sig["fs_hz"] = fs
    sig["nyquist_hz"] = nyq
    sig["reliable_band_hz"] = rel_band

    # --- 阶跃类 ---
    sig["overshoot_pct"] = (m.get("overshoot_frac", 0.0) * 100.0) if m.get("ok") else None
    os_frac = m.get("overshoot_frac", 0.0) if m.get("ok") else 0.0
    if os_frac > 1e-4:
        ln_os = math.log(os_frac)
        sig["zeta_from_overshoot"] = -ln_os / math.sqrt(math.pi ** 2 + ln_os ** 2)
    else:
        sig["zeta_from_overshoot"] = None
    sig["ringing_freq_hz"] = ringing.get("freq_hz") if ringing.get("ok") else None
    so = dg.get("second_order_overshoot", {}) or {}
    sig["zeta_theory"] = so.get("zeta") if so.get("ok") else None
    sig["settle_band_counts"] = (0.02 * m["span"]) if m.get("ok") else None

    # --- 误差（含常数偏置分解）---
    sig["vel_corr"] = ea.get("vel_corr")
    sig["vel_ratio_cv"] = ea.get("vel_ratio_cv")
    sig["offset_suspect"] = bool(ea.get("offset_suspect"))
    sig["err_offset_mean"] = ea.get("mean")
    sig["err_dynamic_std"] = ea.get("dynamic_std")
    sig["err_offset_ratio"] = ea.get("offset_ratio")

    err = w.error_signal()
    clean_err = [x for x in err if math.isfinite(x)]
    if clean_err:
        mu = mean(clean_err)
        dyn = [x - mu for x in clean_err]
        sd = stdev(dyn) if len(dyn) > 1 else 0.0
        sig["err_dynamic_std"] = sd
        sig["fe_p999"] = percentile([abs(x) for x in dyn], 0.999)
        sig["fe_rms_dynamic"] = math.sqrt(sum(x * x for x in dyn) / len(dyn))
        sig["fe_p999_over_rms"] = (sig["fe_p999"] / sig["fe_rms_dynamic"]
                                   if sig["fe_rms_dynamic"] > 0 else None)
        # 误差符号翻转率（近零乱翻 ⟹ 白噪声型抖动）
        flips = 0
        prev = 0
        for x in dyn:
            s = 1 if x > 0 else (-1 if x < 0 else prev)
            if s != 0 and prev != 0 and s != prev:
                flips += 1
            if s != 0:
                prev = s
        dur = (w.t[-1] - w.t[0]) if w.n > 1 and w.t[-1] > w.t[0] else 0.0
        sig["fe_sign_change_rate_hz"] = (flips / dur) if dur > 0 else None
    else:
        sig["fe_p999"] = None
        sig["fe_rms_dynamic"] = None
        sig["fe_p999_over_rms"] = None
        sig["fe_sign_change_rate_hz"] = None

    # --- 稳态窗 + 频谱 ---
    band_lo = th.get("osc_freq_min_hz", 12.0)
    band_hi = min(th.get("osc_freq_max_hz", 120.0), rel_band) if rel_band > 0 else 0.0
    min_prom = th.get("refresh_min_prominence", 5.0)
    win = find_steady_window(w, th)
    sig["steady_window"] = win
    spec_cmd: dict = {"ok": False}
    spec_err: dict = {"ok": False}
    if win is not None and err:
        i0, i1 = win["i0"], win["i1"]
        seg_err = [err[i] for i in range(i0, min(i1 + 1, len(err)))
                   if math.isfinite(err[i])]
        if len(seg_err) >= 32 and band_hi > band_lo:
            spec_err = _spectrum(seg_err, fs, fmin=band_lo, fmax=band_hi)
        if w.cmd and rel_band > 0:
            seg_cmd = [w.cmd[i] for i in range(i0, min(i1 + 1, len(w.cmd)))
                       if math.isfinite(w.cmd[i])]
            if len(seg_cmd) >= 32 and band_hi > 2.0:
                # 指令刷新成分可能落在哪都行，但低频端（<2 Hz）是斜坡本身，不是刷新
                spec_cmd = _spectrum(seg_cmd, fs, fmin=2.0, fmax=band_hi)
    sig["spectrum_error"] = spec_err
    sig["spectrum_cmd"] = spec_cmd

    line = narrowband_line(spec_err, band_lo, band_hi, min_prom) if band_hi > band_lo else {"ok": False}
    sig["tail_line"] = line
    sig["tail_line_freq_hz"] = line.get("freq_hz") if line.get("ok") else None
    sig["tail_line_amplitude"] = line.get("amplitude") if line.get("ok") else None
    sig["tail_line_bin"] = line.get("bin") if line.get("ok") else None
    sig["tail_resolution_hz"] = line.get("resolution_hz")
    sig["tail_edge_peak"] = line.get("edge_peak")
    sig["tail_edge_peak_is_edge"] = line.get("edge_peak_is_edge")
    dyn_std = sig.get("err_dynamic_std") or 0.0
    # 判据分母用**同一窗内**的误差动态量级：频谱讲的是「这一段里有没有一个
    # 相对误差自身量级不可忽略的窄带成分」，拿全记录的 std 当分母会把
    # 阶跃瞬间那个尖峰算进去（阶跃响应的全记录 std 比稳态大一个量级），
    # 于是真实的 35 Hz 谐振会被判成「幅值可忽略」。两个口径都算、都报。
    win_std = (win or {}).get("err_std") or 0.0
    sig["err_dynamic_std_window"] = win_std
    sig["line_over_dynamic"] = (line["amplitude"] / win_std) if (line.get("ok") and win_std > 0) else None
    sig["line_over_dynamic_global"] = ((line["amplitude"] / dyn_std)
                                        if (line.get("ok") and dyn_std > 0) else None)

    # --- 指令刷新率 + 刷新成分互斥登记 ---
    refresh = command_refresh_rate(w, th, win)
    sig["refresh"] = refresh
    sig["refresh_rate_hz"] = refresh.get("rate_hz") if refresh.get("ok") else None
    at_refresh = False
    harmonic_k = None
    offset = None
    if refresh.get("ok") and line.get("ok"):
        r = refresh["rate_hz"]
        f = line["freq_hz"]
        tol = th.get("refresh_harmonic_tol", 0.05)
        for k in range(1, 40):
            fk = k * r
            if fk <= 0:
                break
            off = abs(f - fk) / fk
            if off <= tol:
                at_refresh = True
                harmonic_k = k
                offset = off
                break
        if not at_refresh:
            offset = min(abs(f - k * r) / (k * r) for k in range(1, 40) if k * r > 0)
    sig["line_at_refresh_harmonic"] = at_refresh
    sig["refresh_harmonic_k"] = harmonic_k
    sig["refresh_harmonic_offset"] = offset

    # --- 频谱门禁 ---
    # 两个门要分开：
    #   spectrum_ok —— 有没有稳态窗（没有 ⟹ 频域判据一律不适用）；
    #   line_ok     —— 这条谱线算不算物理现象（刷新成分 / 幅值可忽略 ⟹ 不算）。
    if win is None:
        spectrum_ok = False
        spectrum_why = ("频谱窗口必须落在稳态段；本波形没有可用的稳态窗，频域判据不适用")
        line_ok = False
        line_why = spectrum_why
        line_blocked_by = "no_steady_segment"
    else:
        spectrum_ok = True
        spectrum_why = ""
        if at_refresh:
            line_ok = False
            line_blocked_by = "spectral_line_at_command_refresh_rate"
            line_why = (f"谱线 {line['freq_hz']:.2f} Hz 与指令刷新率 "
                        f"{refresh['rate_hz']:.2f} Hz（{harmonic_k} 次谐波）重合，"
                        f"属指令刷新成分，非被控对象响应")
        elif (sig.get("line_over_dynamic") is not None
              and sig["line_over_dynamic"] < th.get("spectral_line_over_dynamic_min", 0.05)):
            line_ok = False
            line_blocked_by = "spectral_line_below_dynamic_floor"
            line_why = (f"谱线绝对幅值 {line.get('amplitude', 0.0):.6g} 只占误差动态量级 "
                        f"{sig.get('err_dynamic_std_window', dyn_std):.6g} 的 "
                        f"{sig['line_over_dynamic']:.2%}，"
                        f"低于 {th.get('spectral_line_over_dynamic_min', 0.05):.0%}，"
                        f"不作为物理现象")
        else:
            line_ok = True
            line_blocked_by = None
            line_why = ""
    sig["spectral_gate"] = {
        "ok": spectrum_ok and line_ok,
        "spectrum_ok": spectrum_ok, "spectrum_why": spectrum_why,
        "line_ok": line_ok, "line_blocked_by": line_blocked_by, "line_why": line_why,
        "blocked_by": (None if (spectrum_ok and line_ok)
                       else (line_blocked_by if spectrum_ok else "no_steady_segment")),
        "why": (spectrum_why if not spectrum_ok else line_why),
    }

    # --- 运动学：换向点、失动、冲击散布 ---
    v = command_velocity(w)
    a_cmd = command_acceleration(w, v)
    sig["cmd_velocity"] = v
    sig["cmd_acceleration"] = a_cmd
    rev: list[int] = []
    if v and len(v) > 2:
        vmax = max(abs(x) for x in v) or 0.0
        vthr = th.get("reversal_min_speed_ratio", 0.1) * vmax
        for i in range(1, len(v) - 1):
            if (v[i - 1] * v[i + 1] < 0 and abs(v[i - 1]) > vthr
                    and abs(v[i + 1]) > vthr):
                rev.append(i)
    sig["reversal_count"] = len(rev)
    sig["reversal_indices"] = rev

    backlash_est = None
    backlash_cv = None
    spike_cv = None
    baseline_ratio = None
    if rev and err and fs > 0:
        mu = mean([x for x in err if math.isfinite(x)])
        dyn = [x - mu for x in err]
        win_n = max(3, int(th.get("backlash_window_s", 0.05) * fs))
        rev_idx = set(rev)
        base_vals = [abs(dyn[i]) for i in range(len(dyn))
                     if i not in rev_idx and all(abs(i - r) > win_n for r in rev)]
        base_rms = (math.sqrt(sum(x * x for x in base_vals) / len(base_vals))
                    if base_vals else 0.0)
        plates = []
        spikes = []
        for r in rev:
            j0 = max(0, r - win_n)
            j1 = min(len(dyn) - 1, r + win_n)
            seg = [abs(dyn[i]) for i in range(j0, j1 + 1)]
            if not seg:
                continue
            plates.append(max(seg))
            spikes.append(max(seg))
        if plates:
            backlash_est = mean(plates) - base_rms
            backlash_est = max(0.0, backlash_est)
            backlash_cv = (stdev(plates) / mean(plates)) if len(plates) > 1 and mean(plates) > 0 else 0.0
            spike_cv = (stdev(spikes) / mean(spikes)) if len(spikes) > 1 and mean(spikes) > 0 else 0.0
            baseline_ratio = (base_rms / backlash_est) if backlash_est > 0 else None
    sig["backlash_estimate"] = backlash_est
    sig["backlash_cv"] = backlash_cv
    sig["reversal_spike_cv"] = spike_cv
    sig["backlash_baseline_ratio"] = baseline_ratio
    fe_rms_dyn = sig.get("fe_rms_dynamic") or 0.0
    sig["backlash_over_rms"] = (backlash_est / fe_rms_dyn) if (backlash_est and fe_rms_dyn > 0) else None

    # --- 保持段样本数 ---
    sig["dwell_samples"] = int(win.get("dwell_samples", 0)) if win else 0

    # --- 加/减速段误差不对称（前馈失配）---
    accel_rms = decel_rms = None
    asym = asym_signed = None
    fe_acc_corr = None
    if a_cmd and err and len(err) == w.n:
        amax = max(abs(x) for x in a_cmd) or 0.0
        athr = th.get("ff_accel_min_ratio", 0.05) * amax
        if athr > 0:
            mu = mean([x for x in err if math.isfinite(x)])
            dyn = [x - mu for x in err]
            acc = [abs(dyn[i]) for i in range(w.n) if a_cmd[i] > athr]
            dec = [abs(dyn[i]) for i in range(w.n) if a_cmd[i] < -athr]
            if acc and dec:
                accel_rms = math.sqrt(sum(x * x for x in acc) / len(acc))
                decel_rms = math.sqrt(sum(x * x for x in dec) / len(dec))
                if decel_rms > 0 and accel_rms > 0:
                    asym = accel_rms / decel_rms
                    asym_signed = asym if asym >= 1 else -(1.0 / asym)
                pairs = [(abs(dyn[i]), abs(a_cmd[i])) for i in range(w.n)
                         if abs(a_cmd[i]) > athr]
                if len(pairs) >= 10:
                    xs = [p[0] for p in pairs]
                    ys = [p[1] for p in pairs]
                    mx, my = mean(xs), mean(ys)
                    sxx = sum((x - mx) ** 2 for x in xs)
                    syy = sum((y - my) ** 2 for y in ys)
                    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(len(xs)))
                    if sxx > 0 and syy > 0:
                        fe_acc_corr = sxy / math.sqrt(sxx * syy)
    sig["accel_rms"] = accel_rms
    sig["decel_rms"] = decel_rms
    sig["asymmetry_ratio"] = asym
    sig["asymmetry_signed"] = asym_signed
    sig["fe_vs_accel_corr"] = fe_acc_corr

    # --- 量化台阶 ---
    qstep = _quantization_step(w.fb or [], th.get("quant_integer_tol", 0.05))
    sig["quant_step_counts"] = qstep
    band_counts = sig.get("settle_band_counts")
    sig["quant_step_over_band"] = ((qstep / band_counts)
                                   if (qstep and band_counts and band_counts > 0) else None)

    # --- 极限环（保持段）---
    # 极限环必须在「指令保持不动」的段里量：等速段里的周期波动是跟随误差，不是自激。
    stat = (win or {}).get("static_window")
    stat_line: dict = {"ok": False}
    if stat and err:
        i0, i1 = stat["i0"], stat["i1"]
        seg = [err[i] for i in range(i0, min(i1 + 1, len(err))) if math.isfinite(err[i])]
        if seg:
            # 极限环的幅值要在**保持段稳定下来之后**量（AX R-14：「幅值收敛于极限环」）。
            # 整段量到的是阶跃瞬间那个尖峰：case_b 的衰减振铃会被量成 97 mm 的
            # 「极限环」，于是「位置环增益过高自激」这条判据在**任何**欠阻尼阶跃上都会命中。
            # 所以：幅值取保持段**最后 1/4**（稳态部分），频谱同样只取这一段。
            tail_len = max(32, len(seg) // 4)
            settle = seg[-tail_len:] if len(seg) >= 32 else seg
            mu = mean(settle)          # ⚠ 均值必须取**稳态段**自己的均值
            sig["limit_cycle_amplitude"] = max(abs(x - mu) for x in settle)
            # 「极限环」还必须是**持续**的（AX R-14：「静止时也持续」）：
            # 拿保持段后 1/4 段的幅值比前 1/4 段，衰减得快（比值 ≪ 1）说明它在收敛，
            # 不是在自激。
            if len(seg) >= 64:
                q = max(8, len(seg) // 4)
                a_last = max(abs(x - mu) for x in seg[-q:])
                a_prev = max(abs(x - mu) for x in seg[-2 * q:-q]) if len(seg) >= 2 * q else 0.0
                sig["limit_cycle_sustain_ratio"] = (a_last / a_prev) if a_prev > 0 else None
            if len(settle) >= 32 and band_hi > band_lo:
                spec = _spectrum(settle, fs, fmin=band_lo, fmax=band_hi)
                stat_line = narrowband_line(spec, band_lo, band_hi, min_prom)
    sig.setdefault("limit_cycle_amplitude", None)
    sig.setdefault("limit_cycle_sustain_ratio", None)
    sig["limit_cycle_line"] = stat_line
    sig["limit_cycle_freq_hz"] = (stat_line.get("freq_hz")
                                  if stat_line.get("ok") else None)
    sig["limit_cycle_over_band"] = ((sig["limit_cycle_amplitude"] / band_counts)
                                    if (sig.get("limit_cycle_amplitude") is not None
                                        and band_counts and band_counts > 0) else None)

    # --- 振铃频率与谱线是否一致 ---
    rf = sig.get("ringing_freq_hz")
    lf = sig.get("tail_line_freq_hz")
    sig["line_freq_match"] = (abs(rf - lf) / lf) if (rf and lf) else None

    # --- 速度档位（每转周期误差的 f ∝ v 判据）---
    sig["speed_level_count"] = 0
    sig["freq_speed_rel_err"] = None
    if win is not None and win.get("kind") == "constant_velocity" and err and fs > 0:
        pass    # 单档速度无法判 f∝v，需要多档；见 _speed_levels
    levels = _speed_levels(w, err, th, fs)
    if levels and len(levels) >= 2:
        sig["speed_level_count"] = len(levels)
        (v1, f1), (v2, f2) = levels[0], levels[-1]
        if v1 > 0 and f1 > 0:
            pred = f1 * v2 / v1
            sig["freq_speed_rel_err"] = abs(f2 - pred) / pred if pred > 0 else None

    # --- 转矩/电流通道（cur_q：解锁 SRV-15/16/17/20）---
    # 默认全 None：通道不在场时判据自然落 not_evaluable，不会假装测过。
    # 本工具没有编码器速度直采通道：CSV 的 vel 列常是**指令**速度，
    # 判据用的 vel_fb 一律由 fb 差分派生 —— CAP-10 据此封顶（诚实优先）。
    sig["vel_fb_direct"] = False
    sig["tq_breakaway_ratio"] = None
    sig["tq_cruise_median_abs"] = None
    sig["tq_ripple_freq_hz"] = None
    sig["tq_ripple_over_dynamic"] = None
    sig["ti_res_freq_hz"] = None
    sig["ti_pair_ratio"] = None
    sig["spectrum_torque"] = {"ok": False}
    tq = w.torque
    tq_n = sum(1 for x in (tq or []) if isinstance(x, (int, float)) and math.isfinite(x))
    if tq and tq_n >= int(th.get("min_samples_default", 64)) and fs > 0:
        def tq_abs_seg(i0: int, i1: int) -> list[float]:
            return [abs(tq[i]) for i in range(max(0, i0), min(i1 + 1, len(tq)))
                    if isinstance(tq[i], (int, float)) and math.isfinite(tq[i])]

        def tq_seg(i0: int, i1: int) -> list[float]:
            return [tq[i] for i in range(max(0, i0), min(i1 + 1, len(tq)))
                    if isinstance(tq[i], (int, float)) and math.isfinite(tq[i])]

        v_cmd = command_velocity(w)
        # 用 p99 而不是 max 当速度基准：指令里一条瞬跳（回原点、程序跳段）
        # 就能把 max 抬高几十倍，巡航分段会全军覆没 —— 实测踩过。
        v_ref = percentile([abs(x) for x in v_cmd], 0.99) if v_cmd else 0.0
        if v_ref > 0:
            moving = float(th.get("cruise_moving_ratio", 0.3)) * v_ref
            runs: list[tuple[int, int]] = []
            rstart = None
            for i in range(len(v_cmd)):
                if abs(v_cmd[i]) >= moving:
                    if rstart is None:
                        rstart = i
                elif rstart is not None:
                    runs.append((rstart, i - 1))
                    rstart = None
            if rstart is not None:
                runs.append((rstart, len(v_cmd) - 1))
            min_run = int(th.get("steady_window_min_samples", 64))
            runs = [(a, b) for (a, b) in runs if b - a >= min_run][:8]
            # 1) 突破转矩 / 稳态摩擦（SRV-15）：沿起点前后一个短窗里的 |tq| 峰
            #    ÷ 该段中部稳态 |tq| 中位数
            bw_n = max(2, int(float(th.get("stiction_breakaway_window_s", 0.05)) * fs))
            ratios: list[float] = []
            cruise_meds: list[float] = []
            for (a, b) in runs:
                brk = tq_abs_seg(a - bw_n // 2, a + bw_n)
                mid = tq_abs_seg(a + (b - a) // 3, b - (b - a) // 3)
                if not brk or not mid:
                    continue
                med = median(mid)
                if med > 0:
                    ratios.append(max(brk) / med)
                    cruise_meds.append(med)
            if ratios:
                sig["tq_breakaway_ratio"] = max(ratios)
                sig["tq_cruise_median_abs"] = median(cruise_meds)
            # 2) 转矩纹波（SRV-17）与双惯量谐振（SRV-20 的转矩侧）：
            #    取最长恒速段的中部做转矩谱
            if runs:
                a, b = max(runs, key=lambda r: r[1] - r[0])
                seg = tq_seg(a + (b - a) // 5, b - (b - a) // 5)
                if len(seg) >= 64 and band_hi > band_lo:
                    spec_tq = _spectrum(seg, fs, fmin=band_lo, fmax=band_hi)
                    sig["spectrum_torque"] = spec_tq
                    ln_tq = narrowband_line(spec_tq, band_lo, band_hi, min_prom)
                    mu_t = mean(seg)
                    sd_t = stdev([x - mu_t for x in seg]) if len(seg) > 1 else 0.0
                    if ln_tq.get("ok"):
                        sig["tq_ripple_freq_hz"] = ln_tq.get("freq_hz")
                        sig["tq_ripple_over_dynamic"] = (
                            ln_tq["amplitude"] / sd_t) if sd_t > 0 else None
                        # 阶次归因（SRV-17 的 enrich）：axis.json 侧车给出
                        # pole_pairs + screw_pitch_mm 时，纹波线频率可以换算成
                        # 「k× 电频率」或「k× 每转」——把「有窄带成分」升级成
                        # 「6× 电频率（逆变器/死区特征）」这类可执行结论。
                        # 没有侧车就不算：阶次无从谈起，不拿猜测冒充。
                        ax = getattr(w, "axis", None) or {}
                        pitch = float(ax.get("screw_pitch_mm") or 0)
                        pp = float(ax.get("pole_pairs") or 0)
                        if pitch > 0 and pp > 0 and v_ref > 0:
                            mech_hz = v_ref / pitch          # 每秒转数
                            elec_hz = mech_hz * pp
                            tol_o = float(th.get("order_integer_tol", 0.2))
                            cands = [
                                {"kind": "elec", "ref_hz": elec_hz,
                                 "order": ln_tq["freq_hz"] / elec_hz},
                                {"kind": "mech", "ref_hz": mech_hz,
                                 "order": ln_tq["freq_hz"] / mech_hz},
                            ]
                            for c in cands:
                                c["resid"] = abs(c["order"] - round(c["order"]))
                            best_o = min(cands, key=lambda c: c["resid"])
                            if best_o["resid"] <= tol_o:
                                best_o["order_i"] = int(round(best_o["order"]))
                                best_o["freq_hz"] = ln_tq["freq_hz"]
                                sig["tq_ripple_order_best"] = best_o
                    # 双惯量：转矩谐振峰 × 误差谱峰 配对（反谐振在位置误差上可见）
                    # ⚠ 误差侧用**幅值最大**的窄带线（_strongest_narrowband_line）：
                    #     按突出度选会让小而尖的刷新梳齿线赢过幅值大的物理正弦；
                    # ⚠ 且误差侧谱线必须过刷新线门：若「最强误差线」其实是
                    #     刷新线（或其谐波），配对比值就是拿纹波频率除以刷新频率
                    #     —— 数字看似正常，物理上毫无意义。
                    f_err = None
                    ln_err = _strongest_narrowband_line(
                        spec_err, band_lo, band_hi, min_prom)
                    if ln_err.get("ok"):
                        f_err = ln_err["freq_hz"]
                        if _line_is_refresh_harmonic(f_err, sig, th):
                            f_err = None
                    if ln_tq.get("ok") and f_err:
                        f_res = ln_tq["freq_hz"]
                        sig["ti_res_freq_hz"] = f_res
                        sig["ti_pair_ratio"] = f_res / f_err
            # 3) 低速爬行（SRV-16）：恒速段里 fb 差分速度「掉到近零」的粘滞段。
            #    ⚠ 反馈位置同样是阶梯刷新的 —— 相邻差分会输出脉冲串
            #    （步进那 1 ms 是满速、其余 9 ms 是 0），把刷新纹波数成失速。
            #    必须用与 command_velocity 同款的跨样本中心差分：窗 ≥ 刷新周期，
            #    差出来的才是平均速度。
            if w.fb:
                fbv = _diff_velocity(w.t, w.fb, win_s=max(0.02, 2.0 / fs))
                stall_v = float(th.get("crawl_stall_speed_ratio", 0.2)) * v_ref
                stall_min = int(th.get("crawl_stall_min_samples", 3))
                n_stall = 0
                stall_samples = 0
                cruise_samples = 0
                for (a, b) in runs:
                    b = min(b, w.n - 1)
                    cur = 0
                    for i in range(a, b + 1):
                        cruise_samples += 1
                        if math.isfinite(fbv[i]) and abs(fbv[i]) < stall_v:
                            cur += 1
                            stall_samples += 1
                        else:
                            if cur >= stall_min:
                                n_stall += 1
                            cur = 0
                    if cur >= stall_min:
                        n_stall += 1
                sig["crawl_stall_count"] = n_stall
                sig["crawl_stall_time_ratio"] = (
                    stall_samples / cruise_samples) if cruise_samples > 0 else None

    # --- 事件层（events.jsonl：解锁 SRV-23/24/25/26/28/29）---
    sig["ev_n"] = 0
    sig["ev_sync_verified"] = False
    sig["ev_causal_ok"] = False
    ev = w.events or []
    if ev:
        by: dict[str, int] = {}
        n_alarm = 0
        for e in ev:
            by[e["source"]] = by.get(e["source"], 0) + 1
            if e.get("level") in ("error", "fatal"):
                n_alarm += 1
        sig["ev_n"] = len(ev)
        sig["ev_n_by_source"] = by
        sig["ev_n_alarm"] = n_alarm

        def detail_num(e: dict, key: str) -> float | None:
            d = (e.get("detail") or {}).get(key)
            if isinstance(d, (int, float)) and not isinstance(d, bool) \
                    and math.isfinite(float(d)):
                return float(d)
            return None

        # SRV-23：上位机暂停（时长来自 detail.duration_ms）
        pauses = [e for e in ev
                  if e["source"] == "host" and "pause" in e["code"].lower()]
        durs = [d for d in (detail_num(e, "duration_ms") for e in pauses)
                if d is not None]
        sig["ev_host_pause_count"] = len(pauses)
        sig["ev_host_pause_max_ms"] = max(durs) if durs else None
        # SRV-24：插补欠载；「路径期间」用 motion 事件的 started→done 括号
        # 判定（事件时间轴内部，不需要事件-波形对齐）
        und = [e for e in ev
               if e["source"] == "interp" and "underrun" in e["code"].lower()]
        brackets: list[tuple[float, float]] = []
        open_start: dict[str, float] = {}
        for e in ev:
            if e["source"] != "motion":
                continue
            ax = str(e.get("axis") or "_")
            if e["code"] == "move_started":
                open_start[ax] = e["t"]
            elif e["code"] == "move_done" and ax in open_start:
                brackets.append((open_start.pop(ax), e["t"]))
        sig["ev_underrun_count"] = len(und)
        sig["ev_underrun_during_path"] = sum(
            1 for e in und if any(a <= e["t"] <= b for (a, b) in brackets))
        sig["ev_path_brackets"] = len(brackets)
        la = [d for d in (detail_num(e, "lookahead_ms") for e in und)
              if d is not None]
        sig["ev_lookahead_min_ms"] = min(la) if la else None
        # SRV-25：总线 WKC / 丢周期
        sig["ev_wkc_count"] = sum(
            1 for e in ev if e["source"] == "network"
            and any(k in e["code"].lower() for k in ("wkc", "cycle", "drop")))
        # SRV-26：视觉延迟 p95
        lats = sorted(d for d in (detail_num(e, "latency_ms") for e in ev
                                  if e["source"] == "vision") if d is not None)
        sig["ev_vision_count"] = len(lats)
        sig["ev_vision_latency_p95_ms"] = (
            lats[min(len(lats) - 1, int(0.95 * len(lats)))] if lats else None)
        # SRV-28：move_done → 下一个 move_started 的间隔（工艺在到位后停了多久）
        dones = [e["t"] for e in ev
                 if e["source"] == "motion" and e["code"] == "move_done"]
        starts_t = sorted(e["t"] for e in ev
                          if e["source"] == "motion" and e["code"] == "move_started")
        gaps = []
        for d in dones:
            nxt = [s for s in starts_t if s > d]
            if nxt:
                gaps.append((nxt[0] - d) * 1000.0)
        sig["ev_move_done_count"] = len(dones)
        sig["ev_settle_gap_min_ms"] = min(gaps) if gaps else None
        sig["ev_settle_gap_median_ms"] = median(gaps) if gaps else None
        # SRV-29：motion 事件间隔（轮询周期）及其规整度
        mo = [e["t"] for e in ev if e["source"] == "motion"]
        iv = [(mo[i + 1] - mo[i]) * 1000.0 for i in range(len(mo) - 1)]
        iv = [x for x in iv if x > 0]
        sig["ev_motion_interval_median_ms"] = median(iv) if iv else None
        if len(iv) >= 2:
            mu_iv = mean(iv)
            sig["ev_motion_interval_cv"] = (stdev(iv) / mu_iv) if mu_iv > 0 else None
        else:
            sig["ev_motion_interval_cv"] = None
        # 同步与因果开关（C2 规则 8）
        sync = w.events_sync or {}
        sig["ev_sync_verified"] = bool(sync.get("verified"))
        sig["ev_causal_ok"] = bool(sync.get("causal_claims_permitted"))
        sig["ev_align_residual_ms"] = sync.get("alignment_residual_ms")
        sig["ev_sync_why"] = sync.get("why", "")
        # 因果级信号：只有 causal_claims_permitted 才允许把事件对到误差上
        sig["ev_host_err_aligned_ratio"] = None
        sig["ev_settle_err_ratio"] = None
        if sig["ev_causal_ok"] and err and fs > 0:
            cw = float(th.get("causal_window_ms", 30.0))

            def _idx_in(lo_ms: float, hi_ms: float, t0: float) -> list[int]:
                return [i for i in range(w.n)
                        if lo_ms <= (w.t[i] - t0) * 1000.0 <= hi_ms
                        and i < len(err) and math.isfinite(err[i])]

            # 尖峰基线用**局部环**（±150 ms 里去掉中心窗）的**最大波动**，
            # 不用全局动态 std：全局 std 会被最暴力的那段抬上天；环内中位数
            # 又会被「大部分时间贴零的梳齿纹波」拉低，把刷新纹波的正常尖峰
            # 数成事件尖峰。环内最大值 × 3 回答的是「比附近最大的波动还大 3 倍」。
            ring = float(th.get("causal_ring_ms", 150.0))
            k_spike = float(th.get("host_err_spike_k", 3.0))
            spike_flags: list[float] = []
            for e in pauses:
                win_idx = _idx_in(-cw, cw, e["t"])
                if not win_idx:
                    continue
                ring_idx = [i for i in _idx_in(-ring, ring, e["t"])
                            if i not in set(win_idx)]
                if not ring_idx:
                    continue
                ring_max = max(abs(err[i]) for i in ring_idx)
                if ring_max <= 0:
                    ring_max = 1e-12
                peak = max(abs(err[i]) for i in win_idx)
                spike_flags.append(1.0 if peak >= k_spike * ring_max else 0.0)
            sig["ev_host_err_aligned_ratio"] = (
                mean(spike_flags) if spike_flags else None)
            # 「判到位时还没整定」：各次 done 后窗内平均 |err| 相对**其它 done**
            # 的中位数的倍数，取最大。自参照基线 —— 与全局量级无关，
            # 一次过早的到位自己会亮出来（move_count_min ≥ 3 保证有基线）。
            post = float(th.get("settle_check_window_ms", 40.0))
            posts: list[float] = []
            for d in dones:
                idxs = _idx_in(0.0, post, d)
                if len(idxs) < 4:
                    posts.append(None)
                    continue
                posts.append(mean([abs(err[i]) for i in idxs]))
            valid = [x for x in posts if x is not None]
            ratios: list[float] = []
            if len(valid) >= 2:
                base = median(valid)
                if base > 0:
                    ratios = [x / base for x in valid]
            sig["ev_settle_err_ratio"] = max(ratios) if ratios else None

    # ---------------------------------------------------------------- 温度通道
    # 热时间常数 ≫ 采样周期：按 1 s 块取中位数把控制纹波滤掉，再在块序列上
    # 做温度-误差回归。单段记录能给「相关 + 每 K 漂移率」；冷/热机配对要两段
    # 波形，判据的 next_data 里注明。
    tp = getattr(w, "temp", None)
    sig["temp_span_k"] = None
    sig["temp_rise_k_per_min"] = None
    sig["err_temp_corr"] = None
    sig["err_drift_per_k"] = None
    sig["temp_tq_corr"] = None
    if tp and len(tp) == len(w.t) and fs > 0:
        err_s = w.error_signal()
        tq_s = w.torque
        bt: list[float] = []       # 每块中点时间
        be: list[float] = []       # 块内 err 中位数
        bk: list[float] = []       # 块内 temp 中位数
        bq: list[float] = []       # 块内 |torque| 均方根
        blk_n = max(8, int(fs))    # ~1 s 一块
        for i0 in range(0, len(tp), blk_n):
            i1 = min(i0 + blk_n, len(tp))
            t_seg = [tp[i] for i in range(i0, i1) if math.isfinite(tp[i])]
            if len(t_seg) < blk_n // 2:
                continue
            bt.append(w.t[(i0 + i1) // 2])
            bk.append(median(t_seg))
            if err_s:
                e_seg = [err_s[i] for i in range(i0, i1)
                         if i < len(err_s) and math.isfinite(err_s[i])]
                be.append(median(e_seg) if e_seg else 0.0)
            if tq_s:
                q_seg = [abs(tq_s[i]) for i in range(i0, i1)
                         if i < len(tq_s) and math.isfinite(tq_s[i])]
                bq.append(math.sqrt(sum(q * q for q in q_seg) / len(q_seg))
                          if q_seg else 0.0)
        if len(bk) >= 8:
            kmin, kmax = min(bk), max(bk)
            sig["temp_span_k"] = kmax - kmin
            span_min = (bt[-1] - bt[0]) / 60.0
            if span_min > 0.5:
                mx, my = sum(bt) / len(bt), sum(bk) / len(bk)
                num = sum((x - mx) * (y - my) for x, y in zip(bt, bk))
                den = sum((x - mx) ** 2 for x in bt)
                sig["temp_rise_k_per_min"] = (num / den * 60.0) if den > 0 else None
            if len(be) == len(bk):
                ex, ey = sum(be) / len(be), sum(bk) / len(bk)
                cov = sum((a - ex) * (b - ey) for a, b in zip(be, bk))
                sb = math.sqrt(sum((a - ex) ** 2 for a in be))
                sk = math.sqrt(sum((b - ey) ** 2 for b in bk))
                if sb > 0 and sk > 0:
                    sig["err_temp_corr"] = cov / (sb * sk)
                    sig["err_drift_per_k"] = (cov / (sk * sk)) if sk > 0 else None
            if len(bq) == len(bk):
                qx, kx = sum(bq) / len(bq), sum(bk) / len(bk)
                cov = sum((a - qx) * (b - kx) for a, b in zip(bq, bk))
                sq = math.sqrt(sum((a - qx) ** 2 for a in bq))
                sk2 = math.sqrt(sum((b - kx) ** 2 for b in bk))
                if sq > 0 and sk2 > 0:
                    sig["temp_tq_corr"] = cov / (sq * sk2)

    # ---------------------------------------------------------------- 配方事件
    # C6 本来就有 recipe_change 对齐（fe_spike_aligned_to_recipe_change、
    # step_labels）——mcopilot 之前没实现而已。脉冲当量被改写的判据：
    # 事件边界把记录切段，每段的位移比例 Σ|Δfb|/Σ|Δcmd| 在边界上**跳变**。
    sig["ev_recipe_change_count"] = 0
    sig["recipe_scale_step_ratio_max"] = None
    sig["recipe_scale_drift_within_max"] = None
    rc = [e["t"] for e in (w.events or [])
          if e.get("code") == "recipe_change"
          and e.get("source") in ("recipe", "host")]
    sig["ev_recipe_change_count"] = len(rc)
    if rc and w.cmd and w.fb:
        bounds = sorted(set(rc))
        cuts = [b for b in bounds if w.t[0] < b < w.t[-1]]
        segs = []
        lo = 0
        for b in cuts + [w.t[-1] + 1.0]:
            hi = next((i for i in range(lo, w.n) if w.t[i] >= b), w.n)
            if hi - lo >= max(16, int(fs)):
                segs.append((lo, hi))
            lo = hi
            if lo >= w.n:
                break
        ratios: list[float] = []
        drifts: list[float] = []
        for (i0, i1) in segs:
            def _seg_ratio(a: int, b: int) -> float | None:
                sf = sum(abs(w.fb[i] - w.fb[i - 1]) for i in range(a + 1, b))
                sc = sum(abs(w.cmd[i] - w.cmd[i - 1]) for i in range(a + 1, b))
                return (sf / sc) if sc > 1e-9 else None
            r = _seg_ratio(i0, i1)
            if r is not None:
                ratios.append(r)
                mid = (i0 + i1) // 2
                r1, r2 = _seg_ratio(i0, mid), _seg_ratio(mid, i1)
                if r1 is not None and r2 is not None and min(r1, r2) > 0:
                    drifts.append(abs(r1 - r2) / min(r1, r2))
        if len(ratios) >= 2:
            steps = [abs(ratios[i] - ratios[i + 1]) / min(ratios[i], ratios[i + 1])
                     for i in range(len(ratios) - 1)
                     if min(ratios[i], ratios[i + 1]) > 0]
            sig["recipe_scale_step_ratio_max"] = max(steps) if steps else 0.0
        sig["recipe_scale_drift_within_max"] = max(drifts) if drifts else 0.0

    # ---------------------------------------------------------------- 驱动器参数
    # SRV-18 的判据：转矩-误差配对出的谐振频率相对电流环带宽的位置。
    # 谐振 ≥ 电流环带宽 ⟹ 电流环压不住（带宽限制）；远低于 ⟹ 纯机械谐振，
    # 电流环有裕量，换机械侧修。
    dp = getattr(w, "drive_params", None) or {}
    cl_hz = float(dp.get("current_loop_bandwidth_hz") or 0)
    sig["res_over_curloop_ratio"] = None
    if cl_hz > 0 and sig.get("ti_res_freq_hz"):
        sig["res_over_curloop_ratio"] = sig["ti_res_freq_hz"] / cl_hz

    # ---------------------------------------------------------------- 扫频 FRF
    # _present_inputs 已确认 cmd 是扫频（w.sweep.ok）。相干 H1 估计：
    # G = Sxy/Sxx，相干 γ² 低的 bin 不参与读数；闭环带宽 = |G| 跌破
    # 低频平台 0.707 的最高有效频率。闭环扫频给不了开环相位裕度——
    # 结论只到「带宽实测 + 与 ωn 估计的比值」，不冒充裕度。
    sig["sweep_bw_hz"] = None
    sig["sweep_valid_bins"] = 0
    sig["sweep_dip_ratio"] = None
    sig["sweep_bw_wn_ratio"] = None
    sw = getattr(w, "sweep", None) or {}
    if sw.get("ok") and w.cmd and w.fb and fs > 0:
        so_os = dg.get("second_order_overshoot", {}) or {}
        wn_hz = so_os.get("freq_hz")
        f_hi_cap = min(float(sw["f_hi"]), fs / 2.0 / 1.1)
        f_lo_cap = max(1.0, float(sw["f_lo"]))
        if f_hi_cap > f_lo_cap * 1.5:
            freqs = [f_lo_cap * (f_hi_cap / f_lo_cap) ** (k / 47.0)
                     for k in range(48)]
            # 只吃扫频簇窗口（阶跃段的能量不许混进 FRF）
            i0 = next((i for i in range(w.n) if w.t[i] >= sw["t0"]), 0)
            i1 = next((i for i in range(w.n - 1, i0, -1) if w.t[i] <= sw["t1"]),
                      w.n - 1)
            cs, ce = w.cmd[i0:i1 + 1], w.fb[i0:i1 + 1]
            ts = w.t[i0:i1 + 1]
            X = _goertzel_bins(cs, ts, freqs)
            Y = _goertzel_bins(ce, ts, freqs)
            gmag: list[float] = []
            coh: list[float] = []
            for (xr, xi), (yr, yi) in zip(X, Y):
                sxx = xr * xr + xi * xi
                syy = yr * yr + yi * yi
                sxy_r = xr * yr + xi * yi       # X·conj(Y)
                sxy_i = xi * yr - xr * yi
                sxy = sxy_r * sxy_r + sxy_i * sxy_i
                gmag.append(math.sqrt(sxy) / sxx if sxx > 0 else 0.0)
                coh.append(sxy / (sxx * syy) if sxx > 0 and syy > 0 else 0.0)
            coh_min = th.get("sweep_coh_min", 0.8)
            valid = [k for k in range(len(freqs))
                     if coh[k] >= coh_min and gmag[k] > 0]
            sig["sweep_valid_bins"] = len(valid)
            if len(valid) >= 5:
                low = [gmag[k] for k in valid if freqs[k] <= f_lo_cap * 1.5]
                g0 = median(low[:3]) if low else median(
                    [gmag[k] for k in valid[:3]])
                bw = None
                for k in valid:
                    if gmag[k] >= 0.707 * g0:
                        bw = freqs[k]
                sig["sweep_bw_hz"] = bw
                # 反谐振坑 = 「跌下去又爬回来」：bw 之上有 bin 跌破 0.707×G0
                # 之后又回到 ≥0.707×G0 才算谐振结构；单调滚降是正常低通特性，
                # 不是坑，不碰反证。
                if bw:
                    below = None
                    dip = None
                    for k in valid:
                        if freqs[k] <= bw:
                            continue
                        if gmag[k] < 0.707 * g0:
                            below = min(gmag[k], below) if below else gmag[k]
                        elif below is not None:
                            dip = g0 / below
                            break
                    sig["sweep_dip_ratio"] = dip
                if bw and wn_hz:
                    sig["sweep_bw_wn_ratio"] = bw / float(wn_hz)

    return sig


def _speed_levels(w: Waveform, err: Sequence[float], th: dict,
                  fs: float) -> list[tuple[float, float]]:
    """按恒速档位分组，给出 (平均速度, 该档误差主频)。

    用于 R-07 的可算子集：每转周期误差的频率 f ∝ v，粘滑爬行的 f ≈ 常数。
    """
    v = command_velocity(w)
    if not v or not err or fs <= 0:
        return []
    vmax = max(abs(x) for x in v) or 0.0
    if vmax <= 0:
        return []
    min_n = int(th.get("steady_window_min_samples", 64))
    runs: list[tuple[int, int]] = []
    start = None
    for i in range(len(v)):
        if abs(v[i]) >= 0.1 * vmax:
            if start is None:
                start = i
        elif start is not None:
            if i - start >= min_n:
                runs.append((start, i - 1))
            start = None
    if start is not None and len(v) - start >= min_n:
        runs.append((start, len(v) - 1))
    out: list[tuple[float, float]] = []
    for (i0, i1) in runs[:8]:
        seg = [err[i] for i in range(i0, min(i1 + 1, len(err))) if math.isfinite(err[i])]
        if len(seg) < 32:
            continue
        spec = _spectrum(seg, fs, fmin=th.get("osc_freq_min_hz", 12.0),
                         fmax=min(th.get("osc_freq_max_hz", 120.0),
                                   (fs / 2.0) / th.get("band_reliable_divisor", 1.25)))
        ln = narrowband_line(spec, th.get("osc_freq_min_hz", 12.0),
                             min(th.get("osc_freq_max_hz", 120.0),
                                 (fs / 2.0) / th.get("band_reliable_divisor", 1.25)),
                             th.get("refresh_min_prominence", 5.0))
        if not ln.get("ok"):
            continue
        out.append((mean(v[i0:i1 + 1]), ln["freq_hz"]))
    # 只保留速度差明显的档位（按速度排序后贪心取）
    out.sort(key=lambda p: p[0])
    kept: list[tuple[float, float]] = []
    ratio = th.get("encoder_min_speed_ratio", 0.3)
    for vv, ff in out:
        if kept and abs(vv - kept[-1][0]) < ratio * max(abs(vv), 1e-12):
            continue
        kept.append((vv, ff))
    return kept


# ------------------------------------------------------------------ 规则求值


def _compare(value: Any, op: str, threshold: Any) -> bool:
    """按判据比较。null 一律判 False（null ≠ false ≠ 0）。"""
    if value is None or threshold is None:
        return False
    try:
        if op == ">=":
            return value >= threshold
        if op == ">":
            return value > threshold
        if op == "<=":
            return value <= threshold
        if op == "<":
            return value < threshold
        if op == "==":
            return value == threshold
        if op == "!=":
            return value != threshold
    except TypeError:
        return False
    return False


def _margin(value: float, op: str, threshold: float) -> float:
    """裕度倍数 ρ（KB4 §2.1）。"""
    if op in (">=", ">"):
        if threshold == 0:
            return float("inf") if value > 0 else 0.0
        return value / threshold
    if op in ("<=", "<"):
        if value <= 0:
            return float("inf")
        return threshold / value
    return 1.0


def evaluate_rules(w: Waveform, dg: dict, rules: dict, sig: dict,
                   present: dict) -> list[dict]:
    """按知识库里的判据表逐条求值。

    返回每个规则的状态：fired / not_hit（执行了没命中）/ not_evaluable（没法评）。
    「没命中」与「没法评」必须分开 —— 这是 axiscope 契约最容易被混淆的一处。
    """
    th = rules["thresholds"]
    dynamic = {"reliable_band_hz": sig.get("reliable_band_hz"),
               "nyquist_hz": sig.get("nyquist_hz")}
    out: list[dict] = []
    for rule in rules.get("rules", []):
        rid = rule["id"]
        missing = [k for k in rule.get("requires", []) if not present.get(k, False)]
        if missing:
            # 一条规则可能缺不止一个输入：blocked_by 必须指**真正缺的那个**，
            # 不能拿静态的 blocked_by 糊弄 —— 否则补了电流通道之后，报告还在
            # 说「缺电流通道」（SRV-18 真实踩过：补了 torque 仍报 absent_torque_channel）。
            bmap = rule.get("blocked_by_map", {}) or {}
            blk = bmap.get(missing[0], rule.get("blocked_by", "absent_input"))
            out.append({"id": rid, "state": "not_evaluable", "rule": rule,
                        "blocked_by": blk,
                        "why": rule.get("missing", ""),
                        "input_missing": missing,
                        "unlocks": rule.get("unlocks", [rid])})
            continue
        # 数据质量门 / 频谱门：一条规则可能同时踩到多个门，
        # **每个门都要登记**（只报第一个就等于替其它原因背书）。
        gates: list[tuple[str, str]] = []
        if rule.get("error_dependent", False) and sig.get("offset_suspect"):
            gates.append(("offset_dominated_error",
                          (f"跟随误差被常数偏置主导（mean={sig.get('err_offset_mean')}, "
                           f"std={sig.get('err_dynamic_std')}）：疑似两通道不同轴或存在"
                           f"常数偏置，误差不可作为跟随误差读")))
        gate = sig.get("spectral_gate", {"ok": True, "spectrum_ok": True, "line_ok": True})
        if rule.get("needs_spectrum") and not gate.get("spectrum_ok", True):
            gates.append(("no_steady_segment", gate.get("spectrum_why", "")))
        if rule.get("needs_real_line") and not gate.get("line_ok", True):
            gates.append((gate.get("line_blocked_by"), gate.get("line_why", "")))
        if gates:
            out.append({"id": rid, "state": "not_evaluable", "rule": rule,
                        "blocked_by": gates[0][0], "why": gates[0][1],
                        "gates": gates,
                        "input_missing": [], "unlocks": rule.get("unlocks", [rid])})
            continue
        conds = rule.get("conditions", [])
        if not conds:
            # 没有判据条件的规则是**结构性声明**（缺输入才谈得上），
            # 不是可求值的判据：绝不能因为「条件为空 → 全部成立」就算命中。
            out.append({"id": rid, "state": "not_evaluable", "rule": rule,
                        "blocked_by": rule.get("blocked_by", "absent_criterion"),
                        "why": rule.get("missing", "") or "该判据在本工具里没有可求值条件",
                        "input_missing": [], "unlocks": rule.get("unlocks", [rid])})
            continue
        ev: list[dict] = []
        missing_sig = None
        for c in conds:
            val = sig.get(c["signal"])
            if val is None:
                missing_sig = c
                break
            thr = _thr(rules, c["threshold_key"], dynamic)
            ev.append({"feature": c.get("feature", c["signal"]), "value": val,
                       "operator": c["op"], "threshold": thr,
                       "rule_id": rid, "signal": c["signal"],
                       "source": f"knowledge/servo_rules.json#rules.{rid} "
                                 f"(axiscope {'/'.join(rule.get('ax_rules', []))})",
                       "note": c.get("note", ""),
                       "band_check": bool(c.get("band_check", False)),
                       "any_of": c.get("_any_of")})
        if missing_sig is not None:
            fname = missing_sig["signal"]
            # 某些信号缺了有**专门的**原因（如事件-波形同步未验证），
            # 比笼统的 absent_feature 更接近真相 —— 由知识库逐信号登记。
            fmap = rule.get("feature_blocked_by", {}) or {}
            blk = fmap.get(fname, "absent_feature:" + fname)
            why = (f"判据依赖的信号 {fname} 在本波形上不可得"
                   f"（{missing_sig.get('note', '')}）")
            if blk == "events_sync_unverified" and sig.get("ev_sync_why"):
                why = (f"信号 {fname} 需要事件-波形逐拍对齐，而同步未验证："
                       f"{sig['ev_sync_why']}")
            out.append({"id": rid, "state": "not_evaluable", "rule": rule,
                        "blocked_by": blk,
                        "why": why,
                        "input_missing": [], "unlocks": rule.get("unlocks", [rid])})
            continue
        any_of = rule.get("any_of")
        hits = [_compare(e["value"], e["operator"], e["threshold"]) for e in ev]
        if any_of is not None:
            ok = any(hits[i] for i in any_of)
            # any_of 之外的条件必须全部成立
            ok = ok and all(h for i, h in enumerate(hits) if i not in any_of)
        else:
            ok = all(hits)
        if not ok:
            failed = [e["feature"] for e, h in zip(ev, hits) if not h]
            out.append({"id": rid, "state": "not_hit", "rule": rule,
                        "reason": "判据未满足：" + "、".join(failed),
                        "evidence": ev})
            continue
        out.append({"id": rid, "state": "fired", "rule": rule, "evidence": ev})
    return out


# ------------------------------------------------------------------ 置信度（KB4 §2）


def _strength(value: Any, op: str, threshold: Any, n: int, n_ref: int,
              cm: dict, band_factor: float = 1.0, conf: float = 1.0) -> float:
    """KB4 §2.1：S(e) = g(ρ) × conf(f) × n_factor(n/n_ref) × band_factor(f0)。"""
    if isinstance(value, bool) or isinstance(threshold, bool):
        g = 0.85
    else:
        rho = _margin(float(value), op, float(threshold))
        if rho < 1.0:
            return 0.0
        g = cm.get("g_offset", 0.5) + 0.5 * min(
            1.0, math.log10(max(rho, 1e-12)) / math.log10(cm.get("g_saturation_base", 4.0)))
    nref = max(1, int(n_ref or 1))
    nf = cm.get("n_factor_base", 0.6) + cm.get("n_factor_scale", 0.4) * (
        math.log10(max(n, 1) / nref) / math.log10(cm.get("g_saturation_base", 4.0)))
    nf = max(0.6, min(1.0, nf))
    return max(0.0, min(1.0, g * conf * nf * band_factor))


def _penalty_for(rho: float, cm: dict) -> float:
    """反证扣分 v_j（KB4 §2.4）：按裕度倍数分档。"""
    pen = cm.get("penalties", {"strong": 0.2, "medium": 0.1, "weak": 0.05})
    if rho >= cm.get("penalty_rho_strong", 2.0):
        return pen.get("strong", 0.2)
    if rho >= 1.0:
        return pen.get("medium", 0.1)
    return pen.get("weak", 0.05)


def _dedup_items(items: list) -> list:
    """按内容去重（列表元素可能是 dict，不能直接当 set 键）。

    对带 `ask` 的条目（「还缺什么数据」）按 **ask 文本**去重：
    同一条要数据可能来自不同判据，`why` / `unlocks` 措辞略有差异，
    但读者看到的是同一句话 —— 按整条内容去重会把它们留成两条近乎重复的待办。
    去重时把 `unlocks` 合并，不丢解锁项。

    注意：合并会就地改 unlocks，所以存进表里的是**副本**，不动 knowledge 里的原对象。
    """
    out: list = []
    seen: dict[str, dict] = {}
    for it in items:
        if isinstance(it, dict) and it.get("ask"):
            key = "ask:" + str(it["ask"]).strip()
        else:
            try:
                key = json.dumps(it, ensure_ascii=False, sort_keys=True, default=str)
            except Exception:
                key = repr(it)
        if key in seen:
            prev = seen[key]
            if isinstance(prev, dict) and isinstance(it, dict):
                _u = list(prev.get("unlocks") or [])
                for x in (it.get("unlocks") or []):
                    if x not in _u:
                        _u.append(x)
                if _u:
                    prev["unlocks"] = _u
            continue
        if isinstance(it, dict):
            it = dict(it)
        seen[key] = it if isinstance(it, dict) else {}
        out.append(it)
    return out


def build_c3(w: Waveform, dg: dict, rules: dict) -> dict:
    """按 axiscope C3 的字段口径拼出诊断契约产物。"""
    cm = rules.get("confidence_model", {})
    caps = rules.get("caps", {})
    fm = rules.get("fault_modes", {})
    sig = dg.get("signals", {}) or {}
    present = dg.get("present_inputs", {}) or {}
    outcomes = dg.get("rule_outcomes", []) or []
    legacy_map = rules.get("legacy_rule_slugs", {}) or {}
    rel_band = sig.get("reliable_band_hz") or 0.0
    n_samples = w.n

    def band_factor(ev: dict) -> float:
        if not ev.get("band_check"):
            return 1.0
        f0 = ev.get("value")
        if not isinstance(f0, (int, float)) or rel_band <= 0:
            return 1.0
        if f0 > rel_band:
            return 0.0
        if f0 > 0.5 * rel_band:
            return caps.get("derived_velocity_feedback", 0.7) if False else 0.8
        return 1.0

    hyp: list[dict] = []
    considered: list[str] = []
    not_eval: list[dict] = []
    seen_ne: set[tuple] = set()

    def add_not_evaluable(fault_mode: str, blocked_by: str, why: str,
                           unlocks: list[str], scope: str | None = None,
                           family: str | None = None) -> None:
        key = (family or fault_mode, blocked_by, scope or "")
        if key in seen_ne:
            return
        seen_ne.add(key)
        item: dict[str, Any] = {"blocked_by": blocked_by, "why": why,
                                "unlocks": unlocks or []}
        if family:
            item["family"] = family
        else:
            item["fault_mode"] = fault_mode
        if scope:
            item["scope"] = scope
        not_eval.append(item)

    # --- 频带门禁（R-25）：kHz 级判据在低采样率下物理不可观测 ---
    blocked_ax: list[str] = []
    if sig.get("fs_hz") and rel_band < rules["thresholds"].get("band_gate_floor_hz", 2000.0):
        blocked_ax = ["R-03", "R-04", "R-11#switching_freq"]
        add_not_evaluable(
            "mechanical_resonance", "band_gate_fs_1k",
            f"可靠频带只有 {rel_band:.0f} Hz（奈奎斯特 {sig.get('nyquist_hz', 0):.0f} Hz / 1.25），"
            f"kHz 级结构模态（≥ {rules['thresholds'].get('band_gate_floor_hz', 2000):.0f} Hz）"
            f"在本采样率下物理不可观测 —— 看不见 ≠ 没有",
            ["R-03", "R-04", "R-10-kHz", "R-11#switching_freq"],
            scope="仅 kHz 分支（R-03/R-04）；低频分支已单独评估")

    # --- 新规则的求值结果 ---
    fired_rules: list[dict] = []
    for oc in outcomes:
        rule = oc["rule"]
        rid = oc["id"]
        if oc["state"] == "not_evaluable":
            for (bb, why) in (oc.get("gates")
                              or [(oc.get("blocked_by", "absent_input"), oc.get("why", ""))]):
                add_not_evaluable(rule["fault_mode"], bb, why, oc.get("unlocks", [rid]))
            continue
        if oc["state"] != "fired":
            continue
        fired_rules.append(oc)

    # --- 假设：既有结论（SRV-01…07）+ 新规则命中 ---
    for f in dg.get("findings", []):
        meta = legacy_map.get(f["fid"], {})
        slug = meta.get("primary")
        if slug is None:
            continue
        ev_items = f.get("evidence", [])
        if len(ev_items) < 2:
            # C3 规则 1：证据不足的结论不进 hypotheses，降级到 considered
            considered.append(slug)
            f["c3_demoted"] = "supporting_evidence 不足 2 条，按 C3 规则 1 降级为 considered"
            continue
        n_ref = int(rules.get("legacy_rules", {}).get(f["fid"], {}).get("min_samples", 32))
        sup = []
        for ev in ev_items:
            s = _strength(ev["value"], ev["operator"], ev["threshold"], n_samples, n_ref,
                          cm, band_factor(ev))
            ev2 = dict(ev)
            ev2["strength"] = round(s, 3)
            sup.append(ev2)
        hyp.append({
            "id": "", "fault_mode": slug, "display_name": fm.get(slug, {}).get("display_name", slug),
            "family": fm.get(slug, {}).get("family", "mechanical"),
            "rank": 0, "confidence": 0.0,
            "severity": rules.get("severity_map", {}).get(f.get("level"), 2),
            "rule_ids": [f["fid"]], "ax_rules": rules.get("legacy_rules", {}).get(f["fid"], {}).get("ax_rules", []),
            "supporting_evidence": sup, "contradicting_evidence": [],
            "ruled_out_alternatives": [],
            "expected_effect": dict(
                rules.get("legacy_rules", {}).get(f["fid"], {}).get(
                    "expected_effect",
                    {"basis": "unverified", "direction": "",
                     "note": "本工具没有仿真器，改进量不给数字，只给方向"})),
            "next_data_to_collect": list(
                rules.get("legacy_rules", {}).get(f["fid"], {}).get("next_data", [])),
            "title": f.get("title", ""), "detail": f.get("detail", ""),
            "benign": bool(meta.get("benign", False)),
        })

    for oc in fired_rules:
        rule = oc["rule"]
        rid = oc["id"]
        slug = rule["fault_mode"]
        n_ref = int(rule.get("min_samples", 32))
        sup = []
        for ev in oc["evidence"]:
            s = _strength(ev["value"], ev["operator"], ev["threshold"], n_samples, n_ref,
                          cm, band_factor(ev))
            ev2 = dict(ev)
            ev2["strength"] = round(s, 3)
            sup.append(ev2)
        # 反证
        con: list[dict] = []
        a_con = 0.0
        for c in rule.get("contradictions", []):
            val = sig.get(c["signal"])
            if val is None:
                continue
            thr = _thr(rules, c["threshold_key"], {"reliable_band_hz": rel_band})
            if isinstance(val, bool) or isinstance(thr, bool):
                if val != thr:
                    continue
                rho = 2.0
                pen = cm.get("penalties", {}).get("strong", 0.2)
            else:
                hit = _compare(val, c["op"], thr)
                rho = _margin(float(val), c["op"], float(thr))
                if not hit and c["op"] in (">=", ">"):
                    # 方向未达标：仍然是反证，但只给弱扣分
                    pass
                pen = _penalty_for(rho, cm)
            a_con += pen
            con.append({"feature": c.get("feature", c["signal"]), "value": val,
                        "operator": c["op"], "threshold": thr,
                        "rho_prime": round(rho, 3) if math.isfinite(rho) else None,
                        "penalty": pen, "rule_id": c.get("rule_id", rid),
                        "note": c.get("note", "")})
        a_con = min(cm.get("a_con_cap", 0.5), a_con)
        # 已排除的其它 slug
        ruled: list[dict] = []
        for ex in rule.get("excludes", []):
            val = sig.get(ex["signal"])
            if val is None:
                continue
            thr = _thr(rules, ex["threshold_key"], {"reliable_band_hz": rel_band})
            if _compare(val, ex["op"], thr):
                ruled.append({"fault_mode": ex["slug"], "reason": ex.get("reason", ""),
                              "measured": {"feature": ex["signal"], "value": val,
                                           "operator": ex["op"], "threshold": thr}})
        hyp.append({
            "id": "", "fault_mode": slug, "display_name": fm.get(slug, {}).get("display_name", slug),
            "family": rule.get("family", fm.get(slug, {}).get("family", "")),
            "rank": 0, "confidence": 0.0,
            "severity": rules.get("severity_map", {}).get(rule.get("severity", "中"), 2),
            "rule_ids": [rid], "ax_rules": rule.get("ax_rules", []),
            "supporting_evidence": sup, "contradicting_evidence": con,
            "ruled_out_alternatives": ruled,
            "expected_effect": {"basis": rule.get("basis", "unverified"),
                                "direction": rule.get("expected_effect", {}).get("direction", ""),
                                "note": "本工具没有仿真器，改进量不给数字，只给方向"},
            "next_data_to_collect": list(rule.get("next_data", [])),
            "title": rule.get("title", ""), "detail": "", "benign": False,
        })

    # --- 同一 fault_mode 的多条判据合并成一条假设 ---
    # C3 契约里 hypotheses[] 是「候选故障模式」列表，不是「规则命中列表」：
    # 同一个 slug 被两条判据支持时（比如旧判据按过零频率判谐振、新判据按谱线
    # 判谐振），应该是**一条假设、两条证据**，而不是两条同 slug 的假设。
    merged: dict[str, dict] = {}
    order: list[str] = []
    for h in hyp:
        key = h["fault_mode"]
        if key not in merged:
            merged[key] = h
            order.append(key)
            continue
        m = merged[key]
        seen = {(e.get("feature"), e.get("value"), e.get("rule_id"))
                for e in m["supporting_evidence"]}
        for e in h["supporting_evidence"]:
            k = (e.get("feature"), e.get("value"), e.get("rule_id"))
            if k not in seen:
                m["supporting_evidence"].append(e)
                seen.add(k)
        m["contradicting_evidence"].extend(h["contradicting_evidence"])
        m["ruled_out_alternatives"].extend(h["ruled_out_alternatives"])
        m["rule_ids"] = sorted(set(m["rule_ids"]) | set(h["rule_ids"]))
        m["ax_rules"] = sorted(set(m["ax_rules"]) | set(h["ax_rules"]))
        m["next_data_to_collect"] = _dedup_items(
            list(m["next_data_to_collect"]) + list(h["next_data_to_collect"]))
        m["severity"] = max(m["severity"], h["severity"])
        m["benign"] = bool(m["benign"] and h["benign"])
        if h.get("title") and not m.get("title"):
            m["title"] = h["title"]
    hyp = [merged[k] for k in order]

    # --- 归因栏（axis.json 侧车：cpr/pole_pairs/导程）---
    # KB 里 rule.attribution_signal 指名一个信号；信号在场 ⟹ 假设挂
    # attribution 字段并在 detail 给一行人话。归因**不是新证据**（不动置信
    # 数学），是把「有窄带成分」升级成「6× 电频率」这种可执行结论。
    # 没有侧车就不挂——字段缺位本身就是「没做归因」的诚实记录。
    for h in hyp:
        for oc in fired_rules:
            if oc["rule"]["id"] not in h["rule_ids"]:
                continue
            key = oc["rule"].get("attribution_signal")
            if not key:
                continue
            val = sig.get(key)
            if isinstance(val, dict) and val.get("order_i"):
                h["attribution"] = dict(val)
                kind_txt = ("电频率（逆变器/死区特征典型阶次 1/2/6×）"
                            if val["kind"] == "elec" else "每转（机械周期误差特征）")
                line = (f"阶次归因：{val['order_i']}× {kind_txt}"
                        f"（{val['freq_hz']:.4g} Hz ÷ {val['ref_hz']:.4g} Hz，"
                        f"残差 {val['resid']:.2f}）")
                h["detail"] = (h["detail"] + " " + line) if h.get("detail") else line
            break

    # --- 反事实自检（KB4 §4）---
    # 新规则：按规则里写的竞争解释判据算；
    # 既有规则：竞争解释就是 legacy_rule_slugs 里的 alternates ——
    #   若另一条**已命中**的判据指向同一个竞争 slug，说明两种解释同时成立，
    #   本结论只能给到「未分辨」，不许独占。
    # 合并后的假设取**最保守**的那个反事实结论。
    fired_ids = {rid for h in hyp for rid in h["rule_ids"]}
    # 既有判据里命中但因证据不足被降级为 considered 的，也必须记进审计
    legacy_fired = [rid for rid, st in (dg.get("legacy_status") or {}).items()
                    if st["state"] == "fired"]
    fired_ids |= set(legacy_fired)
    fired_slugs = {h["fault_mode"] for h in hyp}
    for h in hyp:
        cfs: list[dict] = []
        for oc in fired_rules:
            rule = oc["rule"]
            if rule["id"] not in h["rule_ids"]:
                continue
            cf = rule.get("counterfactual")
            if not cf:
                cfs.append({"check": "无成对混淆判据", "competitor": "",
                            "result": "RESOLVED", "note": ""})
                continue
            val = sig.get(cf["signal"])
            thr = _thr(rules, cf["threshold_key"], {"reliable_band_hz": rel_band})
            unresolved = bool(val is not None and _compare(val, cf["op"], thr))
            cfs.append({
                "check": cf.get("check", ""), "competitor": cf.get("competitor", ""),
                "result": "UNRESOLVED" if unresolved else "RESOLVED",
                "note": ("竞争解释的形态同时成立，结论只能给到" + str(cf.get("competitor", ""))
                         if unresolved else "竞争解释的形态不成立")})
        # 既有判据：竞争解释（alternates）里若有另一条已命中的判据指向它
        for rid in h["rule_ids"]:
            meta = legacy_map.get(rid, {}) or {}
            for alt in (meta.get("alternates") or []):
                if alt in fired_slugs and alt != h["fault_mode"]:
                    cfs.append({
                        "check": f"竞争解释 {alt} 的判据同时命中，两种解释形态并存",
                        "competitor": alt, "result": "UNRESOLVED",
                        "note": f"竞争解释 {alt} 同时成立，结论只能给到未分辨"})
        if not cfs:
            cfs = [{"check": "无成对混淆判据", "competitor": "",
                    "result": "RESOLVED", "note": ""}]
        unres = [c for c in cfs if c["result"] == "UNRESOLVED"]
        h["counterfactual"] = unres[0] if unres else cfs[0]

    # --- 置信度 ---
    for h in hyp:
        evs = h["supporting_evidence"]
        s_list = [e.get("strength", 0.0) for e in evs]
        smax = max(s_list) if s_list else 0.0
        srest = mean([s for s in s_list if s is not smax]) if len(s_list) > 1 else smax
        a_sup = cm.get("w_max", 0.55) * smax + cm.get("w_rest", 0.45) * srest
        a_con = min(cm.get("a_con_cap", 0.5),
                    sum(e.get("penalty", 0.0) for e in h["contradicting_evidence"]))
        c_mid = a_sup * (1.0 - a_con)
        ceiling = 1.0
        caps_hit: list[str] = []
        # CAP-1：判据链里用了等效带宽（估计值）⟹ 封顶 0.6
        if any("bandwidth" in e.get("feature", "") or e.get("signal") in
               ("settle_ratio", "follow_err_ratio", "limit_cycle_freq_hz")
               for e in evs):
            ceiling = min(ceiling, caps.get("bandwidth_estimate", 0.6))
            caps_hit.append("CAP-1(等效带宽为估计值)")
        # CAP-3：没有静止段 ⟹ 无法核对「静止时是否仍有峰」⟹ 封顶 0.55
        if h["fault_mode"] in ("mechanical_resonance", "electrical_feedforward_mismatch") \
                and not sig.get("dwell_samples"):
            ceiling = min(ceiling, caps.get("no_static_segment", 0.55))
            caps_hit.append("CAP-3(无静止段，无法核对 present_in_rest)")
        # CAP-9：反事实未解决 ⟹ 封顶 0.6
        if h.get("counterfactual", {}).get("result") == "UNRESOLVED":
            ceiling = min(ceiling, caps.get("counterfactual_unresolved", 0.6))
            caps_hit.append("CAP-9(反事实未解决)")
        # CAP-10：vel_fb 是 fb 差分**派生**的（本工具读不到编码器速度直采通道）
        # ⟹ 粘滑判据封顶。速度派生会平滑掉真实的粘滞瞬间，比值因此偏乐观。
        if h["fault_mode"] == "mechanical_crawling" \
                and not sig.get("vel_fb_direct", True):
            ceiling = min(ceiling, caps.get("derived_velocity_feedback", 0.7))
            caps_hit.append("CAP-10(速度反馈为派生值)")
        h["confidence"] = round(min(c_mid, ceiling), 3)
        h["confidence_parts"] = {"S_list": [round(s, 3) for s in s_list],
                                  "A_sup": round(a_sup, 3), "A_con": round(a_con, 3),
                                  "C_mid": round(c_mid, 3), "ceiling": ceiling,
                                  "caps": caps_hit}

    # 排序：严重度优先、置信次之（KB4 §2.9）
    hyp.sort(key=lambda h: (-h["severity"], -h["confidence"], h["fault_mode"]))
    for i, h in enumerate(hyp):
        h["rank"] = i + 1
        h["id"] = f"H{i + 1}"

    # --- 缺席原因（独立原因去重，不按行数）---
    blocked_by = sorted({n["blocked_by"] for n in not_eval if n.get("blocked_by")})
    # 族级缺席：软件族整族不可评 ⟹ 登记族级条目（A-51：族级标签只出现在 family 键）
    sw_blocked = [n for n in not_eval if n.get("fault_mode", "").startswith("software_induced")]
    if sw_blocked and len(sw_blocked) >= 7:
        add_not_evaluable("", "absent_events_jsonl",
                          "事件层缺席使软件诱导族整族降级为不可评估："
                          "跟随误差尖峰与上位机调度抖动在结构上不可分",
                          ["R-18", "R-19", "R-20", "R-21", "R-22", "R-23", "R-24", "R-28"],
                          family="software_induced_error")

    # --- verdict ---
    primary = hyp[0] if hyp else None
    overall = 0.0
    note_parts = []
    if primary:
        overall = primary["confidence"] * (
            1.0 - cm.get("absence_penalty_per_reason", 0.05)
            * min(cm.get("max_absence_reasons", 4), len(blocked_by)))
        note_parts.append(
            f"主假设 {primary['id']}（{primary['fault_mode']}）置信 {primary['confidence']:.3f}；"
            f"独立缺席原因 {len(blocked_by)} 个（{', '.join(blocked_by) if blocked_by else '无'}），"
            f"按契约扣减 {cm.get('absence_penalty_per_reason', 0.05):.0%}/原因")
        note_parts.append(
            "A_sup = 0.55×Smax + 0.45×Srest = "
            f"{primary['confidence_parts']['A_sup']:.3f}，"
            f"A_con = {primary['confidence_parts']['A_con']:.3f}，"
            f"C = {primary['confidence_parts']['C_mid']:.3f}"
            + (f"，封顶 {primary['confidence_parts']['ceiling']}"
               f"（{'、'.join(primary['confidence_parts']['caps'])}）"
               if primary["confidence_parts"]["caps"] else ""))
    else:
        note_parts.append("本次没有任何判据可评估（见 differential.not_evaluable）—— "
                          "这是「没法评」，不是「没问题」。")
    overall = round(min(max(overall, 0.0), 1.0), 3)

    # next_data：置信 < 0.6 时不得为空
    for h in hyp:
        if h["confidence"] < 0.6 and not h["next_data_to_collect"]:
            for n in not_eval:
                if n.get("fault_mode") == h["fault_mode"]:
                    h["next_data_to_collect"].append(
                        {"ask": f"补齐 {n.get('blocked_by')} 所需的输入",
                         "why": n.get("why", ""), "unlocks": n.get("unlocks", [])})
                    break
            if not h["next_data_to_collect"]:
                h["next_data_to_collect"].append(
                    {"ask": "补一段含静止段与恒速段的完整轨迹（含电流/转矩通道）",
                     "why": "当前证据不足以把结论收敛到可执行的排查动作",
                     "unlocks": [r for r in h["rule_ids"]]})

    considered = sorted(set(considered) | {
        h["fault_mode"] for h in hyp})
    # 结论里出现过的其它族 slug 也登记为 considered（axiscope 口径：考虑过但没进假设）
    for slug in fm:
        if slug not in considered and any(h["fault_mode"] == slug for h in hyp):
            considered.append(slug)

    summary = _c3_summary(w, dg, sig, hyp, not_eval, rules)

    return {
        "schema": rules.get("contract", {}).get("schema", "mcopilot.servo.diagnosis/1"),
        "case_id": Path(w.source).stem if w.source else "unknown",
        "engine_version": str(rules.get("version", "")),
        "inputs": {
            "sample_path": w.source,
            "present_channels": sorted([k for k, v in present.items() if v]),
            "missing_channels": sorted([k for k, v in present.items() if not v]),
            "fs_hz": sig.get("fs_hz"), "n_samples": w.n,
            "freq_limits": {"fs_hz": sig.get("fs_hz"), "nyquist_hz": sig.get("nyquist_hz"),
                            "reliable_band_hz": rel_band, "blocked_rules": blocked_ax},
        },
        "verdict": {
            "primary": primary["id"] if primary else None,
            "summary": summary,
            "overall_confidence": overall,
            "confidence_note": "；".join(note_parts),
            "actionable": bool(primary and primary["confidence"] >= 0.4),
        },
        "hypotheses": hyp,
        "differential": {"considered": sorted(set(considered)), "not_evaluable": not_eval},
        "audit": {
            "rules_fired": sorted({rid for rid in fired_ids}),
            "rules_skipped": dg.get("rules_skipped", []),
            "rules_not_hit": dg.get("rules_not_hit", []),
            "assumptions": dg.get("assumptions", []),
        },
    }


def _c3_summary(w: Waveform, dg: dict, sig: dict, hyp: list[dict],
                not_eval: list[dict], rules: dict) -> str:
    """verdict.summary：一段话讲清「是什么、多严重、依据什么、还缺什么」。"""
    if not hyp:
        reasons = sorted({n.get("blocked_by", "") for n in not_eval if n.get("blocked_by")})
        return ("本次没有可评估的判据：所有结论都因为前提不满足而无法给出"
                f"（缺席原因：{', '.join(reasons) if reasons else '未知'}）。"
                "这是「没法评」，不是「没问题」——请按「还缺什么数据」补采后重测。")
    h = hyp[0]
    ev = h["supporting_evidence"]
    ev_txt = "；".join(f"{e['feature']}={e['value']:.4g}（阈值 {e['threshold']:.4g}）"
                       for e in ev[:3] if isinstance(e.get("value"), (int, float)))
    basis = h["expected_effect"]["basis"]
    basis_txt = {"simulation_validated": "仿真验证", "rule_heuristic": "规则启发式",
                 "unverified": "未验证"}.get(basis, basis)
    return (f"主结论 {h['id']}：{h['display_name']}（fault_mode={h['fault_mode']}，"
            f"严重度 {h['severity']}/3，置信 {h['confidence']:.2f}）。"
            f"主要依据：{ev_txt}。改进方向：{h['expected_effect']['direction']}"
            f"（依据层级：{basis_txt}，本工具无仿真器，不给改进百分比）。"
            f"另有 {len(not_eval)} 项故障模式因数据缺失不可评估。")


# ------------------------------------------------------------------ 波形合成
# 用于两件事：① 给估计器做**自洽性验证**（真值与波形同源，见 run_synth 的说明）；
# ② 给现场做「假设—验证」演练。


def synth_step_2nd_order(wn: float, zeta: float, duration: float = 0.5,
                          fs: float = 2000.0) -> Waveform:
    """标准二阶单位阶跃响应（解析解）。ωn、ζ 为真值。"""
    n = int(duration * fs) + 1
    t = [i / fs for i in range(n)]
    wd = wn * math.sqrt(max(1e-9, 1.0 - zeta ** 2))
    fb = []
    for ti in t:
        if zeta < 1.0:
            y = 1.0 - math.exp(-zeta * wn * ti) * (
                math.cos(wd * ti) + (zeta / math.sqrt(1.0 - zeta ** 2)) * math.sin(wd * ti))
        else:
            y = 1.0 - math.exp(-zeta * wn * ti) * (1.0 + wn * ti)
        fb.append(y * 100.0)          # 目标 100 mm，便于读数
    return Waveform(t=t, cmd=[0.0] + [100.0] * (n - 1), fb=fb,
                    err=[c - f for c, f in zip([0.0] + [100.0] * (n - 1), fb)],
                    vel=None, torque=None, source="synth-2nd-order")


def servo_2inertia_matrices(J1: float, J2: float, wf: float, zf: float,
                            Kt: float, Kp: float, Kv: float = 0.0):
    """双惯量伺服（电机 + 柔性联轴 + 负载）的闭环状态空间。

        J1·θ̈1 = Kt·u - Kf(θ1-θ2) - Bf·θ̇1
        J2·ẍ2 = Kf(θ1-θ2)
        u     = Kp·(r - θ2) + Kv·(ṙ - θ̇1)

    状态 x = [θ1, θ̇1, θ2, ẋ2]，输出 y = θ2（负载位置）。
    这个结构比二阶模型真实得多：它天然带一个机械谐振模式（≈wf），
    正是「跟随误差出现周期性振荡」的物理来源。

    返回 (A, B, C)：ẋ = A·x + B·r，y = C·x。
    """
    Kf = wf * wf
    Bf = 2.0 * zf * wf
    # J1·θ̈1 = Kt·u - Kf(θ1-θ2) - Bf·θ̇1，u = Kp(r-θ2) + Kv(ṙ-θ̇1)
    #   ⇒ θ̈1 = [Kt·Kp·r - Kt·Kp·θ2 - Kf·θ1 + Kf·θ2 - (Kt·Kv+Bf)·θ̇1] / J1
    # 注意 θ2 的系数是 (-Kt·Kp + Kf)，写成 -(Kt·Kp + Kf) 会让耦合变成正反馈、系统发散。
    A = [
        [0.0, 1.0, 0.0, 0.0],
        [-Kf / J1, -(Kt * Kv + Bf) / J1, (-Kt * Kp + Kf) / J1, 0.0],
        [0.0, 0.0, 0.0, 1.0],
        [Kf / J2, 0.0, -Kf / J2, 0.0],
    ]
    B = [[0.0], [Kt * Kp / J1], [0.0], [0.0]]
    C = [[0.0, 0.0, 1.0, 0.0]]
    return A, B, C


def _solve_complex(a: list[list[complex]], b: list[complex]) -> list[complex]:
    """带部分主元的高斯消元（纯 Python，4x4 规模足够）。"""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-18:
            raise ValueError("奇异矩阵")
        m[col], m[piv] = m[piv], m[col]
        pv = m[col][col]
        for r in range(n):
            if r == col:
                continue
            f = m[r][col] / pv
            if f == 0:
                continue
            for c in range(col, n + 1):
                m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def freq_response(A, B, C, w: float) -> complex:
    """H(jω) = C·(jωI - A)⁻¹·B。"""
    n = len(A)
    M = [[complex(A[i][j]) - (1j * w if i == j else 0.0) for j in range(n)] for i in range(n)]
    x = _solve_complex(M, [complex(B[i][0]) for i in range(n)])
    return sum(C[0][i] * x[i] for i in range(n))


def closed_loop_response(A, B, C, fmax: float = 500.0) -> dict:
    """闭环频响特征：-3dB 带宽、谐振峰频率、谐振峰值。

    口径说明（这里曾经踩过坑，务必看清）：
    · **带宽 = 幅频第一次跌到 -3dB 的频率**，这是伺服行业的通行定义。
      之前取「最后一个穿越点」，结果把**谐振峰**当成了带宽：
      柔性双惯量模型 |H| 在 1.49 Hz 处是 1.113（>1，是谐振峰），
      而真正的 -3dB 带宽是 2.79 Hz。两者差近 2 倍，不是模型错，是取错了点。
    · 幅频**不是单调的**（有谐振峰，甚至反谐振凹陷），所以不能二分求解。
      必须扫描。
    · 谐振峰单独输出：它正是「跟随误差出现周期性振荡」的物理来源，
      也是 SRV-02 要判的东西。
    """
    ref = abs(freq_response(A, B, C, 1e-3))
    if ref <= 0:
        return {"ok": False, "reason": "直流增益为 0，模型不可用"}
    target = ref / math.sqrt(2.0)

    def mag(f: float) -> float:
        return abs(freq_response(A, B, C, 2.0 * math.pi * f))

    n = 4000
    lo_f, hi_f = 0.05, fmax
    freqs = [lo_f * (hi_f / lo_f) ** (i / (n - 1)) for i in range(n)]
    mags = [mag(f) for f in freqs]

    # 带宽 = 首个 -3dB 穿越点
    bandwidth = float("nan")
    for i in range(1, n):
        if mags[i - 1] >= target >= mags[i]:
            frac = ((mags[i - 1] - target) / (mags[i - 1] - mags[i])
                    if mags[i - 1] != mags[i] else 0.0)
            bandwidth = freqs[i - 1] + (freqs[i] - freqs[i - 1]) * frac
            break

    # 谐振峰 = 幅频最大点（若最大值就在直流端，则视为无谐振）
    imax = max(range(n), key=lambda i: mags[i])
    peak_hz = freqs[imax]
    peak = mags[imax]
    return {"ok": True, "dc_gain": ref, "bandwidth_hz": bandwidth,
            "resonance_hz": peak_hz, "resonance_peak": peak,
            "has_resonance": bool(peak > ref * 1.01 and peak_hz > freqs[0] * 1.5)}


def closed_loop_bandwidth_hz(A, B, C, fmax: float = 500.0) -> float:
    """闭环 -3dB 带宽（真值来源：模型本身的频响）。"""
    return closed_loop_response(A, B, C, fmax).get("bandwidth_hz", float("nan"))


def synth_step_2inertia(J1: float = 1.0, J2: float = 1.0, wf: float = 300.0,
                        zf: float = 0.05, Kt: float = 1.0, Kp: float = 400.0,
                        Kv: float = 0.0, duration: float = 0.5,
                        fs: float = 2000.0, amplitude: float = 100.0) -> Waveform:
    """双惯量伺服的位置阶跃响应（RK4 积分同一组状态方程）。"""
    A, B, C = servo_2inertia_matrices(J1, J2, wf, zf, Kt, Kp, Kv)
    n = int(duration * fs) + 1
    dt = 1.0 / fs
    x = [0.0, 0.0, 0.0, 0.0]

    def f(state, r):
        return [sum(A[i][j] * state[j] for j in range(4)) + B[i][0] * r for i in range(4)]

    fb: list[float] = []
    for _ in range(n):
        fb.append(x[2])
        k1 = f(x, amplitude)
        k2 = f([x[i] + 0.5 * dt * k1[i] for i in range(4)], amplitude)
        k3 = f([x[i] + 0.5 * dt * k2[i] for i in range(4)], amplitude)
        k4 = f([x[i] + dt * k3[i] for i in range(4)], amplitude)
        x = [x[i] + dt / 6.0 * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]) for i in range(4)]
    if not all(math.isfinite(v) for v in fb) or abs(fb[-1]) > 100 * abs(amplitude):
        raise ValueError("双惯量模型仿真发散：请检查参数（增益/刚度/阻尼）或减小步长")
    cmd = [amplitude] * n
    return Waveform(t=[i / fs for i in range(n)], cmd=cmd, fb=fb,
                    err=[c - f_ for c, f_ in zip(cmd, fb)], vel=None, torque=None,
                    source="synth-2inertia")


# ------------------------------------------------------------------ 报告


def build_report(w: Waveform, dg: dict, rules: dict, out_dir: Path | None,
                 stem: str) -> Report:
    m, so, ea, freq = dg["metrics"], dg["second_order"], dg["error"], dg["frequency"]
    sig = dg.get("signals", {}) or {}
    c3 = dg.get("c3", {}) or {}
    rep = Report(title="伺服波形离线诊断报告",
                 subtitle=f"{w.source}　|　样本 {w.n} 点，采样率 {w.fs:.0f} Hz　|　"
                          f"时间列单位 {w.time_unit}　|　"
                          f"逆向：实测波形 → 等效伺服参数 → 候选根因")
    # --- 证据依据：先说清「这条波形上的结论算不算数」，再谈结论 -----------
    # 夹具上的「与真值相符」是同义反复；不标出来，读者会当成准确率。
    prov = w.provenance or "unknown"
    _prov_rows = [("波形来源类别", PROVENANCE_KINDS.get(prov, prov)),
                  ("依据类型", PROVENANCE_EVIDENCE.get(prov, "未知"))]
    for _k, _v in (w.provenance_detail or {}).items():
        _prov_rows.append((_k, _v))
    rep.add("证据依据", "\n".join([
        callout("提示", PROVENANCE_BANNER.get(prov, PROVENANCE_BANNER["unknown"])),
        "",
        kv_block(_prov_rows),
    ]))
    # --- 结论：先判 is_step，再谈命中（P0-2）------------------------
    # 顺序反了报告就会说谎：波形不是阶跃却只写「未发现异常特征」，
    # 读者会以为所有判据都执行过了 —— 而实际上有一半前提根本没满足。
    is_step = dg.get("is_step", True)
    legacy_map = rules.get("legacy_rule_slugs", {}) or {}
    findings = dg.get("findings", [])
    new_findings = dg.get("new_findings", [])
    all_f = list(findings) + list(new_findings)
    n_not_eval = sum(1 for oc in dg.get("rule_outcomes", [])
                     if oc.get("state") == "not_evaluable")
    # 「没执行」的判据条数按**去重后的判据编号**算：
    # rules_skipped 里已经包含新判据的 not_evaluable 条目，不能再叠加一次。
    n_unexecuted = len({s.get("rule_id") for s in (dg.get("rules_skipped") or [])})

    def slug_of(f: dict) -> str:
        return (f.get("fault_mode")
                or (legacy_map.get(f.get("fid"), {}) or {}).get("primary", ""))

    def basis_of(f: dict) -> str:
        b = f.get("basis") or "rule_heuristic"
        return {"simulation_validated": "仿真验证",
                "rule_heuristic": "规则启发式",
                "unverified": "未验证"}.get(b, b)

    if not is_step:
        body = [
            callout("中", "**本次波形不是单次阶跃（指令在持续变化），"
                          "超调/整定时间/振铃频率这些阶跃类指标不适用。**"),
            "",
            "下面只给出与速度/运动相关的结论。请改采一段**单次阶跃**的波形"
            "（指令先保持不动，再跳变一次）再跑一次，才能拿到等效 ωn/ζ。",
            "",
        ]
        if all_f:
            body.append(f"已执行的判据命中 {len(all_f)} 条：")
            for f in all_f:
                body.append(f"- [{f['level']}] `{f['fid']}` **{slug_of(f)}** —— "
                            f"{f['detail']}（依据：{basis_of(f)}）")
        else:
            body.append(f"**已执行的判据没有命中**；另有 **{n_unexecuted} 条判据因前提不满足未执行**"
                        f"（见「没有执行的判据」与「不可评估清单」）。"
                        f"「没命中」≠「已排除」。")
        rep.add("结论", "\n".join(body))
    elif not all_f:
        rep.add("结论", "\n".join([
            callout("低", "**在已执行的判据中未发现异常特征。** 但请注意：未检出 ≠ 已排除。"),
            "",
            f"另有 **{n_unexecuted} 条判据因前提不满足未执行**"
            f"（见「没有执行的判据」与「不可评估清单」）—— "
            f"这些不是「没问题」，是「没法评」。",
            "若怀疑存在谐振，请用更高采样率重采一段带振动的波形再测。",
        ]))
    else:
        top = all_f[0]
        body = [
            callout(top["level"], f"**最高优先级：{top['title']}** —— {top['detail']}"),
            "",
            f"影响：{top['impact']}",
            "",
            f"怎么验证：{top['verify']}",
            "",
            f"**结论口径**：fault_mode `{slug_of(top)}`，依据层级 {basis_of(top)}"
            f"（本工具无仿真器，不给改进百分比）。",
        ]
        if len(all_f) > 1:
            body.append("")
            body.append("其余结论（每条带 fault_mode slug 与依据层级）：")
            for f in all_f[1:]:
                body.append(f"- [{f['level']}] `{f['fid']}` **{slug_of(f)}** —— "
                            f"{f['detail']}（依据：{basis_of(f)}）")
        if n_unexecuted:
            body.append("")
            body.append(f"另有 **{n_unexecuted} 条判据因前提不满足未执行**"
                        f"（见「没有执行的判据」与「不可评估清单」）—— "
                        f"这些不是「没问题」，是「没法评」。")
        rep.add("结论先行", "\n".join(body))

    rows = []
    if m.get("ok") and is_step:
        rows.append(["阶跃幅度", f"{m['span']:.4f}（起点 {m['start']:.4f} → 目标 {m['target']:.4f}）"])
        rows.append(["超调量", f"{m['overshoot_frac'] * 100:.2f}%"])
        rows.append(["峰值时间", f"{m['peak_time_s'] * 1000:.1f} ms"])
        rows.append(["整定时间(±2%)", f"{m['settle_time_s'] * 1000:.1f} ms"])
    elif m.get("ok"):
        rows.append(["指令类型", f"非单次阶跃（指令变化的样本 {m.get('moving_samples', 0)} 个）"
                              f"—— 阶跃类指标不适用"])
    if so.get("ok"):
        rows.append(["等效阻尼比 ζ", f"{so['zeta']:.4f}"])
        rows.append(["等效自然频率 ωn", f"{so['wn']:.1f} rad/s"])
        rows.append(["等效闭环带宽", f"{so['bandwidth_hz']:.2f} Hz"])
        ts = so.get("theoretical_settle_s")
        rows.append(["二阶理论整定时间", f"{ts * 1000:.1f} ms" if ts else "不可辨识"])
    else:
        rows.append(["等效二阶参数", f"不可辨识（{so.get('reason', '')}）"])
    # 两种估计法并排列出：超调法只在欠阻尼时有效，拟合法对任何形状有效。
    # 两者差得远 = 这段响应不像二阶（多半有高阶/谐振模式），本身就是要报告的结论。
    so_os = dg.get("second_order_overshoot") or {}
    so_fit = dg.get("fit") or {}
    if so_os.get("ok") and so_fit.get("ok"):
        rows.append(["超调法反推 (ζ, ωn)",
                     f"{so_os['zeta']:.4f}, {so_os['wn']:.1f} rad/s"])
        rows.append(["最小二乘拟合 (ζ, ωn)",
                     f"{so_fit['zeta']:.4f}, {so_fit['wn']:.1f} rad/s"])
        rows.append(["拟合残差 RMSE", f"{so_fit.get('rmse', float('nan')):.4f} mm"])
        dwn = abs(so_fit["wn"] - so_os["wn"]) / so_os["wn"] if so_os["wn"] else float("nan")
        rows.append(["两法 ωn 相对差", f"{dwn:.1%}"
                     + ("（差异大：响应不像单一二阶）" if dwn > 0.25 else "")])
    if dg.get("ringing", {}).get("ok"):
        rows.append(["振铃频率（过零法）", f"{dg['ringing']['freq_hz']:.2f} Hz"])
    if ea.get("ok"):
        # --- 常数偏置分解（P0-3）：偏置与动态必须分开报 ---
        rows.append(["跟随误差常数偏置分解",
                     f"mean {ea['mean']:.5f} / std {ea['std']:.5f}"
                     f"（std/peak = {ea.get('offset_ratio', 0.0):.2%}）"])
        if ea.get("offset_suspect"):
            rows.append(["⚠ 跟随误差读数口径",
                         "疑似两通道不同轴或存在常数偏置，**不作为跟随误差读**；"
                         "下面所有误差类指标只反映去偏置后的动态部分，"
                         "依赖误差的判据已降级为不可评估"])
        else:
            rows.append(["跟随误差读数口径", "未见常数偏置主导，按跟随误差读"])
        if is_step:
            rows.append(["跟随误差峰值（含阶跃瞬间）", f"{ea['peak']:.5f} mm"])
            rows.append(["跟随误差 RMS", f"{ea['rms']:.5f} mm"])
        else:
            rows.append(["跟随误差峰值（全程，非阶跃）", f"{ea['peak']:.5f} mm"])
            rows.append(["跟随误差 RMS（全程，非阶跃）", f"{ea['rms']:.5f} mm"])
        rows.append(["误差动态 std（去偏置，全记录口径）",
                     f"{ea.get('dynamic_std', 0.0):.6f} mm"])
        rows.append(["err-vel 相关系数",
                     f"{ea['vel_corr']:.3f}" if ea.get("vel_corr") is not None else "无速度通道"])
        if ea.get("vel_ratio_cv") is not None:
            rows.append(["误差/速度 比值波动 CV",
                         f"{ea['vel_ratio_cv']:.3f}"
                         + ("（比值恒定 → 疑似 type-1）" if ea["vel_ratio_cv"] < 0.25 else
                            "（比值不稳 → 更像谐振而非缺前馈）")])
    if freq.get("ok"):
        _old = (f"{freq['freq_hz']:.2f} Hz（突出度 {freq['prominence']:.0f}）")
        if freq.get("is_edge_bin"):
            # F-07：主频落在最低/最高 bin 时，那个「频率」是分辨率边界上的残留，
            # 不是真实频率。此时突出度再大也没有物理意义，必须当场说破。
            _old += (f"　⚠ **这是最低/最高 bin（k={freq.get('bin')}，"
                     f"分辨率 {freq.get('resolution_hz', 0):.4f} Hz）上的残留，"
                     f"不是真实频率** —— 旧口径把去趋势后的残余摆到边界 bin 上，"
                     f"再除以极小的基线，才造出这个突出度。判定请用下面的绝对幅值口径")
        rows.append(["尾段误差主频（旧口径，相对突出度）", _old])
    # --- 频谱读数（绝对幅值口径；只报「突出度」会误导）---
    ln = sig.get("tail_line") or {}
    win = sig.get("steady_window") or {}
    if ln.get("ok"):
        rows.append(["稳态窗（频谱取样段）",
                     f"{w.t[win['i0']]:.3f}~{w.t[win['i1']]:.3f} s"
                     f"（{win.get('kind')}，{win.get('n')} 点）"
                     if win else "—"])
        rows.append(["稳态误差谱窄带线频率",
                     f"{ln['freq_hz']:.3f} Hz（bin {ln['bin']}，"
                     f"频率分辨率 fs/nfft = {ln['resolution_hz']:.4f} Hz）"])
        rows.append(["该谱线绝对幅值", f"{ln['amplitude']:.6f} mm"])
        rows.append(["误差动态 std（判据分母，同一稳态窗内）",
                     f"{sig.get('err_dynamic_std_window', 0.0):.6f} mm"])
        rows.append(["误差动态 std（去偏置，全记录口径）",
                     f"{sig.get('err_dynamic_std', 0.0):.6f} mm"])
        lod = sig.get("line_over_dynamic")
        if lod is not None:
            lod_g = sig.get("line_over_dynamic_global")
            _bb = (sig.get("spectral_gate") or {}).get("line_blocked_by")
            if _bb == "spectral_line_below_dynamic_floor":
                _tail = "（低于阈值，判为非物理现象，不进结论）"
            elif _bb == "spectral_line_at_command_refresh_rate":
                _tail = "（幅值不算小，但它与指令刷新率重合 → 属指令刷新成分，不进结论）"
            else:
                _tail = "（可作为物理现象）"
            rows.append(["谱线 / 误差动态量级（判据口径，窗内）",
                         f"{lod:.2%}"
                         + (f"（全记录口径 {lod_g:.2%}）" if lod_g is not None else "")
                         + _tail])
        if sig.get("line_at_refresh_harmonic"):
            rows.append(["⚠ 谱线归属",
                         f"与指令刷新率 {sig.get('refresh_rate_hz', 0):.2f} Hz"
                         f"（{sig.get('refresh_harmonic_k')} 次谐波，"
                         f"相对差 {sig.get('refresh_harmonic_offset', 0):.2%}）重合 → "
                         f"**指令刷新成分，非被控对象响应**，不进结论"])
        if sig.get("tail_edge_peak_is_edge"):
            rows.append(["⚠ 频率分辨率提示",
                         f"谱峰落在最低/最高 bin（k=1 即 fs/nfft = {ln['resolution_hz']:.4f} Hz），"
                         f"不是可分辨的谱线，不能作为频点使用"])
    else:
        rows.append(["稳态误差谱", f"不可用（{ln.get('reason', '未找到稳态窗')}）"])
    rf = sig.get("refresh") or {}
    if rf.get("ok"):
        rows.append(["指令刷新率（实测）",
                     f"{rf['rate_hz']:.2f} Hz（跳变间隔中位数 {rf['interval_s'] * 1000:.3f} ms，"
                     f"{rf['n_jumps']} 次跳变）"])
    else:
        rows.append(["指令刷新率（实测）", f"未测得（{rf.get('reason', '无稳态窗或指令无跳变')}）"])
    rep.add("量化结果", "\n".join([f"- {k}：{v}" for k, v in rows]))

    def _finding_block(f: dict) -> str:
        ev = f.get("evidence") or []
        ev_txt = "".join(
            f"  - {e['feature']} = {e['value']:.6g}"
            f"（判据 {e['operator']} {e['threshold']:.6g}）\n"
            for e in ev if isinstance(e.get("value"), (int, float)))
        out = f"### {f['title']}　`{f['fid']}`（{f['level']}）\n"
        out += f"- **fault_mode**：`{slug_of(f)}`\n"
        out += f"- **依据层级**：{basis_of(f)}\n"
        out += f"- **现象**：{f['detail']}\n"
        out += f"- **影响**：{f['impact']}\n"
        out += f"- **怎么验证**：{f['verify']}\n"
        out += f"- **需求对应**：{f['requirement']}\n"
        if ev_txt:
            out += f"- **支撑证据（{len(ev)} 条）**：\n{ev_txt}"
        return out

    rep.add("诊断结论",
            "\n".join([_finding_block(f) for f in all_f]) if all_f else
            ("本次没有成立的结论（执行过的判据都没命中；"
             "另有判据因前提不满足没执行，见下方两节）。"))

    # ------------------------------------------------------------ 不可评估清单
    ne = (c3.get("differential", {}) or {}).get("not_evaluable", []) or []
    if ne:
        body = [callout("提示", "**下面这些不是「没发现问题」，是「没法评」** —— "
                                 "数据或前提不满足时，契约要求登记成不可评估，"
                                 "不许用「未发现」糊过去。"), ""]
        for n in ne:
            who = n.get("fault_mode") or (f"族 `{n.get('family')}`" if n.get("family") else "—")
            body.append(f"- **{who}** ｜ blocked_by `{n.get('blocked_by')}`")
            body.append(f"  - 原因：{n.get('why', '')}")
            if n.get("scope"):
                body.append(f"  - 范围：{n['scope']}")
            body.append(f"  - 补齐后解锁：{', '.join(n.get('unlocks', [])) or '—'}")
        rep.add("不可评估清单", "\n".join(body))
    else:
        rep.add("不可评估清单", callout("提示", "本次列入考虑的全部故障模式都可评估（罕见情况）。"))

    # ------------------------------------------------------------ 反证与已排除
    hyps = c3.get("hypotheses", []) or []
    body = []
    for h in hyps:
        body.append(f"### {h['id']} {h['display_name']}（`{h['fault_mode']}`，"
                    f"置信 {h['confidence']:.2f}）")
        if h.get("attribution"):
            body.append(f"- **阶次归因**（axis.json 侧车）：{h['detail']}")
        elif h.get("detail"):
            body.append(f"- {h['detail']}")
        con = h.get("contradicting_evidence", []) or []
        if con:
            body.append("- **反证**：")
            for c in con:
                body.append(f"  - {c['feature']} = {c['value']:.6g}"
                            f"（{c['operator']} {c['threshold']:.6g}，扣分 {c['penalty']:.2f}）"
                            f" —— {c.get('note', '')}")
        else:
            body.append("- **反证**：无（已逐条检查，没有一条成立；空数组是结论，不是省略）")
        ro = h.get("ruled_out_alternatives", []) or []
        if ro:
            body.append("- **已排除的其它故障模式**：")
            for r in ro:
                body.append(f"  - `{r['fault_mode']}`：{r.get('reason', '')}"
                            f"（{r['measured']['feature']} = {r['measured']['value']:.6g}，"
                            f"判据 {r['measured']['operator']} {r['measured']['threshold']:.6g}）")
        body.append("")
    if not hyps:
        body.append("本次没有成立的结论，因此没有反证与排除记录；"
                    "已考虑但未成立的故障模式见下方「已考虑」清单。")
        body.append("")
    considered = (c3.get("differential", {}) or {}).get("considered", []) or []
    if considered:
        body.append("**已考虑（considered）**：" + ", ".join(f"`{s}`" for s in considered))
    rep.add("反证与已排除", "\n".join(body) if body else "—")

    # ------------------------------------------------------------ 还缺什么数据
    asks: list[str] = []
    for h in hyps:
        nd = h.get("next_data_to_collect", []) or []
        if not nd:
            continue
        flag = "　⚠ 置信 < 0.6，下列数据是**必需项**" if h["confidence"] < 0.6 else ""
        asks.append(f"### {h['id']} {h['display_name']}（置信 {h['confidence']:.2f}）{flag}")
        for n in nd:
            asks.append(f"- **{n.get('ask', '')}**")
            if n.get("why"):
                asks.append(f"  - 为什么需要：{n['why']}")
            if n.get("unlocks"):
                asks.append(f"  - 解锁：{', '.join(n['unlocks'])}")
        asks.append("")
    # 族级/全局：把不可评估变成可评估需要补什么
    ne_asks = rules.get("not_evaluable_asks", {}) or {}
    gseen: list[str] = []
    for n in ne:
        bb = n.get("blocked_by", "")
        a = ne_asks.get(bb)
        if not a or a.get("ask") in gseen:
            continue
        gseen.append(a.get("ask"))
        asks.append(f"- **{a['ask']}**（解锁 {bb}）")
        if a.get("why"):
            asks.append(f"  - 为什么需要：{a['why']}")
    if asks:
        rep.add("还缺什么数据", "\n".join(asks))
    else:
        rep.add("还缺什么数据", callout("提示", "本次没有需要追加采集的项。"))

    # ------------------------------------------------------------ 没有执行的判据（F-12）
    skipped = dg.get("rules_skipped", []) or []
    not_hit = dg.get("rules_not_hit", []) or []
    body = []
    if skipped:
        body.append("以下判据因前提不满足**没有执行**（不是「执行了没命中」）：")
        # 同一个原因（blocked_by）挂多条判据时合成一行，判据编号仍然逐条列出 ——
        # 契约要求「每条判据都有明确交代」，但不该让读者看 21 行重复的话。
        groups: dict[str, list[dict]] = {}
        for s in skipped:
            key = s.get("blocked_by") or s["rule_id"]
            groups.setdefault(key, []).append(s)
        for key, items in groups.items():
            ids = ", ".join(f"`{i['rule_id']}`" for i in items)
            whys = {i.get("why", "") for i in items}
            unlocks: list[str] = []
            for i in items:
                for u in (i.get("unlocks") or []):
                    if u not in unlocks:
                        unlocks.append(u)
            bb = f"（blocked_by `{key}`）" if items[0].get("blocked_by") else ""
            if len(whys) == 1:
                body.append(f"- {ids}{bb}：{items[0].get('why', '')}")
            else:
                # 同因但各自缺的东西不一样时，不许拿第一条的原因冒充整组
                body.append(f"- {ids}{bb}：同一原因导致未执行"
                            f"（各自缺什么见「不可评估清单」）")
            if unlocks:
                body.append(f"  - 补齐后可解锁：{', '.join(unlocks)}")
    if not_hit:
        if body:
            body.append("")
        body.append("以下判据**执行了但未命中**（说明这些形态在本次数据里不成立）：")
        body.append("- " + ", ".join(f"`{r}`" for r in not_hit))
    rep.add("没有执行的判据", "\n".join(body) if body else "本次所有列入考虑的判据都执行了。")

    rep.add("这三条前提必须一起看（否则结论会被误用）", "\n".join([
        "1. **等效二阶 ≈ 闭环带宽，不是机械固有频率。** 真实伺服是位置环 PVT（三阶 + 机械谐振模式），"
        "本工具用二阶模型做等效拟合。判断共振必须再用扫频/频响确认。",
        "2. **e ≈ a/ωn² 成立于 type-2（位置环 + 速度前馈），且只描述恒加速度段。** "
        "若报告里 SRV-05 命中（误差与速度高度相关、且误差/速度比值恒定），说明是无前馈的 type-1，"
        "该公式不适用，误差随速度线性增长且不收敛。"
        "阶跃指令的瞬间误差就等于阶跃幅度本身，工具不会拿它跟公式对照 —— "
        "只有波形里存在恒加速度段时才会做这个比较。",
        "3. **本工具不替代示波器与伺服手册。** 它给的是「该怀疑什么、去测什么」，"
        "不是「增益该调到多少」—— 后者必须结合负载惯量与机械刚度。",
    ]))

    # 给了加速度却没做成对照 → 必须明说，不能让读者以为已经比过了
    # （P0-4：触发条件是「给了 --accel 但这个对照没做成」，
    #   不是「cmd_accel 且没有 acc_window」—— 后者会把「给了加速度但对照做成了」
    #   的情况也报成没做，报告就开始说谎。）
    if dg.get("cmd_accel") and not dg.get("acc_comparison_done"):
        rep.add("未做的对比（原因）", "\n".join([
            f"你给了指令加速度 {dg['cmd_accel']} mm/s²，但**这次没有做成**"
            f"「实测跟随误差 vs e≈a/ωn²」的对照"
            f"（这段波形里找不到恒加速度段、或没有速度通道、或等效二阶参数不可辨识）。",
            "",
            "要拿到这个对照，请采一段**含匀加速段**的轨迹（例如梯形速度规划的加减速段），"
            "并保证 CSV 里有速度列。",
        ]))

    images = []
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        target = m["target"] if m.get("ok") else None
        # P0-1：真实厂商 CSV（CODESYS Scope / TwinCAT）**没有 err 列**，
        # 误差是派生的（cmd−fb）。旧代码用 w.err or [] 传图，err 缺失时
        # 画出来的是长度 0 的序列 → matplotlib 维度不匹配 → 整个诊断退出码 3、
        # out/ 目录里一张图都没有。这里必须用 error_signal()。
        err_series = w.error_signal()
        fb_series = w.fb or []
        # 画图前先断言长度一致（chart.py 里也该有同样的断言，见 docs/kb3_判据抽取.md）
        if len(err_series) != len(w.t) or (fb_series and len(fb_series) != len(w.t)):
            raise ValueError(
                f"绘图数据长度不一致：t={len(w.t)}、fb={len(fb_series)}、err={len(err_series)}"
                f"（{w.source}）")
        p1 = chart.save_servo_chart(out_dir / f"{stem}_wave.png", w.t,
                                    fb_series, err_series, target,
                                    "伺服阶跃响应（反馈位置 / 跟随误差）")
        if p1:
            images.append(p1)
    rep.images = images
    return rep


def run_diagnose(csv_path: Path, out_dir: Path, cmd_accel: float | None = None,
                 stem: str | None = None, time_unit: str = "auto",
                 events_path: Path | None = None,
                 axis_path: Path | None = None,
                 drive_params_path: Path | None = None) -> dict[str, Any]:
    w = load_waveform(csv_path, time_unit)
    if events_path is not None:
        w.events, w.events_problems = load_events(events_path)
        w.columns["events"] = str(events_path)
    if axis_path is not None:
        w.axis, w.axis_problems = load_axis(axis_path)
        w.columns["axis"] = str(axis_path)
    if drive_params_path is not None:
        w.drive_params, w.drive_params_problems = load_drive_params(drive_params_path)
        w.columns["drive_params"] = str(drive_params_path)
    rules = load_rules()
    dg = diagnose(w, rules, cmd_accel)
    stem = stem or f"servo_{csv_path.stem}"
    rep = build_report(w, dg, rules, out_dir, stem)
    c3_path: Path | None = None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        # 机器可读的契约产物：hypotheses / differential / verdict / audit 全部落盘，
        # 方便下游（看板、复测脚本、axiscope 对齐）直接消费。
        c3_path = write_json(out_dir / f"{stem}_diagnosis.json", dg.get("c3", {}))
    return {"report": rep, "diagnosis": dg, "waveform": w, "c3_json": c3_path}


def run_synth(model: str, out_csv: Path, wn: float = 60.0, zeta: float = 0.4,
              j1: float = 1.0, j2: float = 1.0, wf: float = 300.0, zf: float = 0.05,
              kt: float = 1.0, kp: float = 400.0, kv: float = 0.0,
              duration: float = 0.6, fs: float = 2000.0) -> dict[str, Any]:
    """合成已知真值的阶跃波形，供估计器做**自洽性验证**（不是外部证据）。

    model:
      · ``2nd``      —— 解析二阶系统，ωn/ζ 就是真值
      · ``2inertia`` —— 双惯量柔性伺服，真值取自模型自身的频响（-3dB 与谐振峰）

    ⚠ **产出的 .truth.json 与波形同源**（同一组模型参数）→ 拿它核对估计器只能证明
    「估计器能把同一个模型解回去」（**自洽性验证 / 同义反复**），
    **不能**当作「工具在真实机器上准不准」的证据。真机证据看
    ``samples/servo/twincat_export10.csv`` + 其独立基线。
    """
    truth: dict[str, Any]
    if model == "2nd":
        w = synth_step_2nd_order(wn, zeta, duration, fs)
        truth = {"model": model, "wn": wn, "zeta": zeta,
                 "bandwidth_hz": _second_order_bandwidth_hz(wn, zeta)}
    elif model == "2inertia":
        w = synth_step_2inertia(j1, j2, wf, zf, kt, kp, kv, duration, fs)
        A, B, C = servo_2inertia_matrices(j1, j2, wf, zf, kt, kp, kv)
        resp = closed_loop_response(A, B, C)
        truth = {"model": model, "J1": j1, "J2": j2, "wf": wf, "zf": zf,
                 "Kt": kt, "Kp": kp, "Kv": kv,
                 "bandwidth_hz": resp.get("bandwidth_hz"),
                 "resonance_hz": resp.get("resonance_hz"),
                 "resonance_peak": resp.get("resonance_peak")}
    else:
        raise SystemExit("model 只能是 2nd 或 2inertia")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as fh:
        fh.write("# provenance: synthetic_model_truth\n")
        fh.write(f"# source: mcopilot servo synth {model}（按模型参数合成，非真机记录）\n")
        fh.write(f"# truth: {out_csv.stem}.truth.json（与波形同源 → 核对属自洽性验证）\n")
        wr = csv.writer(fh)
        wr.writerow(["time_ms", "cmd_pos", "fb_pos", "err"])
        for i in range(w.n):
            wr.writerow([f"{w.t[i] * 1000:.4f}", f"{w.cmd[i]:.6f}", f"{w.fb[i]:.6f}",
                         f"{w.err[i]:.6f}"])
    truth = {"provenance": "synthetic_model_truth",
             "truth_basis": "真值由模型参数解析算出，与波形同源 → 核对估计器属自洽性验证，"
                            "不构成真机上的有效性证据",
             **truth}
    write_json(out_csv.with_suffix(".truth.json"), truth)
    return {"csv": out_csv, "truth": truth, "waveform": w}
