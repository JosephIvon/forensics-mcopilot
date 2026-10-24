"""生成样例数据：设备日志、工艺 CSV、待评审的 C# 源码。

⚠ 关于这个样例的效力（重要，别误用）：
   本脚本生成的日志与 knowledge/log_rules.json 的解析规则是**同源**的
   （格式由我定、事件正则也由我按同一套约定写）。因此：

   · 它能证明的是「检测逻辑（指令-到位配对、竞态窗口、分段扫描…）自洽且正确」；
   · 它**不能**证明「这套规则对你们公司的日志有效」—— 那是阶段 0 校准要解决的问题，
     用 `mcopilot forensics probe <你们的日志>` 量化即可。

   因此这里把每一组植入缺陷写成**可核对的清单**（samples/logs/planted_defects.json），
   每条都锚定到具体日志行号与期望命中的检测器，测试据此断言「每组植入都有对应命中」。
   这样「全检出」就不再是我的一句话，而是可复算的对照表。

   植入缺陷组数 = 8（下面 A~H），期望命中的检测器类型 = 9
   （A 组同时触发 param_conflict 与 position_deviation；D 组同时触发 timeout_burst 与 heartbeat_gap；
     另有 H 组单独触发 cycle_jitter）。
   两者不是同一个数：组数按「一次埋点」算，检测器类型按「命中了哪几类规则」算。
"""
from __future__ import annotations

import json
import random
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
random.seed(20261019)

LOG_DIR = ROOT / "samples" / "logs"
CSV_DIR = ROOT / "samples" / "process"
CODE_DIR = ROOT / "samples" / "code"
SERVO_DIR = ROOT / "samples" / "servo"
for d in (LOG_DIR, CSV_DIR, CODE_DIR, SERVO_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------ 日志
# 事件先收集，最后统一按时间排序并插入「状态采集心跳」。
# 心跳走 2 秒固定栅格（贴近真实设备的周期性状态轮询），
# 其中挖出一段 9 秒断流，作为植入的「采集线程被阻塞」缺陷。
events: list[tuple[datetime, str, str, str]] = []
t0 = datetime(2026, 10, 18, 8, 30, 0)
heartbeat_gap: tuple[datetime, datetime] | None = None

# 植入缺陷清单：id / 说明 / 期望命中的检测器 / 锚点消息片段
planted: list[dict] = []


def emit(dt: datetime, level: str, src: str, msg: str) -> None:
    events.append((dt, level, src, msg))


# 1) 开机与回零
emit(t0, "INFO", "System", "App Start version=3.4.1")
emit(t0 + timedelta(seconds=1), "INFO", "Motion", "Enable axis=0 on=1")
emit(t0 + timedelta(seconds=1), "INFO", "Motion", "Enable axis=1 on=1")
emit(t0 + timedelta(seconds=2), "INFO", "Motion", "CMD Home axis=0")
emit(t0 + timedelta(seconds=3), "INFO", "Motion", "HomeDone axis=0 pos=0.000")
emit(t0 + timedelta(seconds=3), "INFO", "Motion", "CMD Home axis=1")
emit(t0 + timedelta(seconds=4), "INFO", "Motion", "HomeDone axis=1 pos=0.000")
emit(t0 + timedelta(seconds=5), "INFO", "Recipe", "Recipe Load name=COUPLE_A ver=3")
emit(t0 + timedelta(seconds=5), "INFO", "Motion", "ParamWrite axis=0 key=pulse_per_mm value=13107.20")
emit(t0 + timedelta(seconds=5), "INFO", "Motion", "ParamWrite axis=1 key=pulse_per_mm value=13107.20")
emit(t0 + timedelta(seconds=6), "INFO", "Comm", "Comm Seq axis=0 seq=1")
emit(t0 + timedelta(seconds=6), "INFO", "Comm", "Comm Seq axis=1 seq=1")
emit(t0 + timedelta(seconds=7), "INFO", "Vision", "Calib residual=1.20 um")

# 2) 正常生产循环
t = t0 + timedelta(seconds=10)
seq = 1
lot_no = 0
for i in range(120):
    lot_no += 1
    lot = f"L{20261018 + (lot_no - 1) // 40:04d}"
    ct_base = 42.0 + random.gauss(0, 0.8)
    if lot_no in (37, 38, 39, 76, 77, 78):      # 节拍抖动批次
        ct_base += random.uniform(9, 16)
    ct = max(20.0, ct_base)

    emit(t, "INFO", "Process", f"Cycle Start lot={lot} device=EQP-01")
    emit(t + timedelta(seconds=0.2), "INFO", "Comm", f"Comm Seq axis=0 seq={seq}")
    emit(t + timedelta(seconds=0.2), "INFO", "Comm", f"Comm Seq axis=1 seq={seq}")
    seq += 1

    # 贴装运动
    for axis, target, speed in ((0, 120.0 + (i % 7) * 0.3, 200.0), (1, 45.0 + (i % 5) * 0.2, 150.0)):
        emit(t + timedelta(seconds=0.5), "INFO", "Motion",
             f"CMD MoveAbs axis={axis} target={target:.3f} speed={speed:.3f}")
        lat = 0.45 + random.gauss(0, 0.05)
        emit(t + timedelta(seconds=0.5 + lat), "INFO", "Motion",
             f"Reached axis={axis} pos={target + random.gauss(0, 0.004):.3f}")

    # 视觉
    vres = "OK"
    if random.random() < 0.05:
        vres = "NG"
    emit(t + timedelta(seconds=1.2), "INFO", "Vision",
         f"Vision result={vres} dx={random.gauss(0, 0.004):.4f} dy={random.gauss(0, 0.004):.4f}")

    # 工艺量
    emit(t + timedelta(seconds=1.3), "INFO", "Process", f"Temp zone=COUPLE value={random.gauss(175, 1.2):.2f}")
    emit(t + timedelta(seconds=1.4), "INFO", "Process", f"Press value={random.gauss(12.5, 0.4):.3f}")
    emit(t + timedelta(seconds=1.5), "INFO", "Process", f"Power value={random.gauss(-3.2, 0.2):.3f}")

    ok = vres == "OK" and random.random() > 0.06
    cycle_end_msg = f"Cycle End lot={lot} result={'OK' if ok else 'NG'} ct={ct:.2f}"
    emit(t + timedelta(seconds=ct), "INFO", "Process", cycle_end_msg)
    if lot_no in (37, 38, 39, 76, 77, 78):
        jitter_anchor = cycle_end_msg
    t = t + timedelta(seconds=ct + 0.3)

planted.append({
    "id": "H", "name": "部分节拍明显劣化（节拍抖动）",
    "expects": ["cycle_jitter"],
    "anchor": jitter_anchor,
    "why": "第 37/38/39/76/77/78 拍比中位数慢 9~16 秒，占比 5%，"
           "P95/中位数与 CV 都被稀释，靠「慢拍占比」才抓得到",
})

# 3) 埋缺陷 A：换型时参数被覆盖（定位偏差根因）
tb = t + timedelta(seconds=30)
emit(tb, "INFO", "Recipe", "Recipe Load name=COUPLE_B ver=4")
emit(tb + timedelta(seconds=1), "INFO", "Motion", "ParamWrite axis=0 key=pulse_per_mm value=13107.20")
emit(tb + timedelta(seconds=1), "INFO", "Motion", "ParamWrite axis=1 key=pulse_per_mm value=13107.20")
emit(tb + timedelta(seconds=2), "INFO", "Motion", "ParamWrite axis=0 key=pulse_per_mm value=12930.00")
emit(tb + timedelta(seconds=2), "INFO", "Motion", "ParamWrite axis=1 key=pulse_per_mm value=13107.20")
emit(tb + timedelta(seconds=3), "INFO", "Motion", "CMD MoveAbs axis=0 target=120.000 speed=200.000")
emit(tb + timedelta(seconds=3.5), "INFO", "Motion", "Reached axis=0 pos=121.910")
emit(tb + timedelta(seconds=4), "INFO", "Motion", "CMD MoveAbs axis=1 target=45.000 speed=150.000")
emit(tb + timedelta(seconds=4.5), "INFO", "Motion", "Reached axis=1 pos=45.012")
t = tb + timedelta(seconds=6)
planted.append({
    "id": "A", "name": "换型时轴参数被覆盖（定位偏差根因）",
    "expects": ["param_conflict", "position_deviation"],
    "anchor": "value=12930.00",
    "why": "换型流程在写 pulse_per_mm 时与轴参数初始化存在竞态，后写入者覆盖前者；"
           "覆盖率约 1.37% 的偏差直接造成定位超差",
})

# 4) 埋缺陷 B：同一轴未到位又下发新指令（时序竞争）
emit(t, "INFO", "Motion", "CMD MoveAbs axis=0 target=300.000 speed=200.000")
emit(t + timedelta(seconds=0.2), "INFO", "Motion", "CMD MoveAbs axis=0 target=150.000 speed=200.000")
emit(t + timedelta(seconds=1.4), "INFO", "Motion", "Reached axis=0 pos=151.220")
t = t + timedelta(seconds=2)
planted.append({
    "id": "B", "name": "同一轴未到位即下发新指令（时序竞争）",
    "expects": ["concurrent_command"],
    "anchor": "CMD MoveAbs axis=0 target=150.000",
    "why": "流程调度与手动干预抢同一轴，后发指令打断前一指令，造成半程位置偏差",
})

# 5) 埋缺陷 C：通信丢包
base = seq
emit(t, "INFO", "Comm", f"Comm Seq axis=0 seq={base}")
emit(t + timedelta(seconds=0.1), "INFO", "Comm", f"Comm Seq axis=0 seq={base + 1}")
emit(t + timedelta(seconds=0.2), "INFO", "Comm", f"Comm Seq axis=0 seq={base + 5}")
emit(t + timedelta(seconds=0.3), "INFO", "Comm", f"Comm Seq axis=0 seq={base + 6}")
t = t + timedelta(seconds=1)
planted.append({
    "id": "C", "name": "通信序号跳变（丢包）",
    "expects": ["comm_gap"],
    "anchor": f"seq={base + 5}",
    "why": "序号从 base+1 跳到 base+5，中间 3 帧未收到",
})

# 6) 埋缺陷 D：超时聚集 + 心跳断流
for k in range(4):
    emit(t + timedelta(seconds=k * 0.2), "ERROR", "Motion",
         f"Timeout what=axis0_reached waited={3.5 + k * 0.4:.1f}")
t = t + timedelta(seconds=2)
planted.append({
    "id": "D", "name": "超时事件聚集",
    "expects": ["timeout_burst"],
    "anchor": "Timeout what=axis0_reached waited=3.5",
    "why": "连续 4 次等待轴 0 到位超时，指向该轴确实没到位而不是记录问题",
})
# 埋缺陷 G：状态采集线程被阻塞 9 秒 —— 期间完全没有心跳/日志产出
heartbeat_gap = (t, t + timedelta(seconds=9))
t = t + timedelta(seconds=10)
planted.append({
    "id": "E", "name": "状态采集线程被阻塞 9 秒（心跳断流）",
    "expects": ["heartbeat_gap"],
    "anchor": "Calib residual=1.40 um",
    "why": "锚点是断流恢复后的第一条日志；断流期间现场状态完全不可见",
})

# 7) 埋缺陷 E：标定残差持续上升（机械松动）
for k in range(6):
    emit(t + timedelta(seconds=k * 5), "INFO", "Vision", f"Calib residual={1.4 + k * 0.75:.2f} um")
t = t + timedelta(seconds=32)
planted.append({
    "id": "F", "name": "标定残差单调上升（机械松动/温漂）",
    "expects": ["calib_drift"],
    "anchor": "Calib residual=5.15 um",
    "why": "残差从 1.40 μm 单调升到 5.15 μm，属典型的「慢慢变坏」型问题",
})

# 8) 埋缺陷 G：视觉不良率上升
vision_anchor = ""
for k in range(16):
    vres = "NG" if k % 2 == 0 else "OK"
    vision_anchor = f"Vision result={vres} dx={random.gauss(0.02, 0.01):.4f} dy={random.gauss(0, 0.01):.4f}"
    emit(t + timedelta(seconds=k * 0.4), "INFO", "Vision", vision_anchor)
t = t + timedelta(seconds=7)
planted.append({
    "id": "G", "name": "视觉判定不良率在末段集中升高",
    "expects": ["vision_ng_rate"],
    "anchor": vision_anchor,
    "why": "末段 16 次判定中 8 次 NG，全程平均被稀释，只有分段扫描才能看出来",
})

emit(t, "INFO", "System", "App Stop")

# 插入状态采集心跳：2 秒固定栅格，跳过「被阻塞」的那一段
if events:
    span_end = events[-1][0]
    hb_seq = 0
    cur = t0
    while cur <= span_end:
        if heartbeat_gap is None or not (heartbeat_gap[0] <= cur < heartbeat_gap[1]):
            hb_seq += 1
            events.append((cur, "INFO", "System", f"Heartbeat seq={hb_seq}"))
        cur = cur + timedelta(seconds=2)

events.sort(key=lambda e: e[0])
lines = [f"{dt.strftime('%Y-%m-%d %H:%M:%S.')}{dt.microsecond // 1000:03d} "
         f"[{level:<5}] [{src}] {msg}" for dt, level, src, msg in events]

# 给每个植入缺陷标出它在日志里的行号，测试据此断言「每组植入都有对应检测器命中」
for item in planted:
    anchor = item["anchor"]
    hit = [i + 1 for i, ln in enumerate(lines) if anchor in ln]
    item["line_no"] = hit[0] if hit else None
    item["occurrences"] = len(hit)

manifest = {
    "note": "样例日志中植入的缺陷清单。用于核对检出完整性 —— "
            "但请注意：样例与解析规则同源，只能证明检测逻辑自洽，"
            "不能证明对其他团队的日志有效（用 `mcopilot forensics probe` 量化）。",
    "log": "machine_a.log",
    "log_lines": len(lines),
    "planted_groups": len(planted),
    "expected_detector_types": sorted({e for it in planted for e in it["expects"]}),
    "defects": planted,
}
(LOG_DIR / "planted_defects.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

(LOG_DIR / "machine_a.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"日志: {len(lines)} 行（含 {hb_seq} 次心跳，栅格 2s） -> {LOG_DIR / 'machine_a.log'}")
print(f"植入缺陷: {len(planted)} 组 / 期望命中 {len(manifest['expected_detector_types'])} 类检测器"
      f" -> {LOG_DIR / 'planted_defects.json'}")

# ------------------------------------------------------------------ 工艺 CSV
rows = ["lot,device,ts,place_x_mm,place_y_mm,temp_c,press_force_n,glue_ul,power_mw,result,ng_code"]
ng_codes = ["MISS_PLACE", "OFFSET", "VOID", "CRACK"]
for lot_i in range(40):
    lot = f"LOT{lot_i + 1:04d}"
    for n in range(30):
        # 设备老化：place_x 随批次缓慢漂移（第 20~28 批明显偏）
        drift = 0.0
        if 20 <= lot_i <= 27:
            drift = 0.012 * (lot_i - 19)
        x = random.gauss(120.0 + drift, 0.008)
        y = random.gauss(45.0, 0.010)
        temp = random.gauss(175.0, 1.1)
        press = random.gauss(12.5, 0.35)
        glue = random.gauss(8.0, 0.25)
        power = random.gauss(-3.2, 0.18)
        # 不良概率随 x 偏离目标而升高 —— 这样「参数与不良的相关性」才是真的
        dev = abs(x - 120.0)
        p_ng = 0.015 + min(0.30, dev * 2.4)
        if 20 <= lot_i <= 27:
            p_ng += 0.03
        ng = random.random() < p_ng
        code = ""
        if ng:
            # 漂移批次里不良更可能是 OFFSET
            if 20 <= lot_i <= 27 and random.random() < 0.6:
                code = "OFFSET"
            else:
                code = random.choice(ng_codes)
        hh = (lot_i * 30 + n) // 60 % 24
        mm = (lot_i * 30 + n) % 60
        rows.append(f"{lot},EQP-01,2026-10-{18 + lot_i // 20:02d}T{hh:02d}:{mm:02d}:00,"
                     f"{x:.4f},{y:.4f},{temp:.2f},{press:.3f},"
                     f"{glue:.3f},{power:.3f},{'NG' if ng else 'OK'},{code}")
(CSV_DIR / "line1_lot.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
print(f"CSV: {len(rows) - 1} 行 -> {CSV_DIR / 'line1_lot.csv'}")

# ------------------------------------------------------------------ 异构格式日志
# 目的：给 `mcopilot forensics probe` 提供可核对的输入。
# 这两份日志**故意**与内置 log_format.json 不同：
#   · vendor_b.log —— 行布局不同（竖线分隔 + 斜杠日期 + 模块在前），但**键名相同**
#     → 适配成本 = 改 1 个 line_regex
#   · legacy_c.log —— 行布局不同，且**键名也不同**（pos 代替 target、spd 代替 speed），
#     还缺少 seq/result/ct/waited/residual 等埋点
#     → 适配成本 = 改 line_regex + 改事件正则 + 有些检测器直接跑不了
# 有了这两份，probe 的输出就不是自说自话，而是可复算的。

from datetime import datetime as _dt, timedelta as _td  # noqa: E402

_base = _dt(2026, 10, 18, 8, 30, 0)


def _hetero_rows() -> list[tuple[str, str, str]]:
    """(时间, 模块, 消息) —— 三份格式共用的语义内容。"""
    out: list[tuple[str, str, str]] = []
    t = _base
    for i in range(12):
        out.append((t, "Motion", f"CMD MoveAbs axis=0 target={100 + i * 1.5:.3f} speed=200.000"))
        out.append((t + _td(milliseconds=520), "Motion", f"Reached axis=0 pos={100 + i * 1.5:.3f}"))
        out.append((t + _td(milliseconds=600), "Comm", f"Comm Seq axis=0 seq={i + 1}"))
        out.append((t + _td(milliseconds=700), "Process",
                    f"Cycle End lot=L2026{i:03d} result={'OK' if i % 5 else 'NG'} ct={40 + i * 0.3:.2f}"))
        out.append((t + _td(milliseconds=900), "Vision",
                    f"Vision result={'OK' if i % 5 else 'NG'} dx=0.0012 dy=-0.0008"))
        t = t + _td(seconds=41.0)
    return out


# vendor_b：竖线分隔、斜杠日期、模块在前、级别在中间
_vb: list[str] = []
for _t, _m, _msg in _hetero_rows():
    _vb.append(f"{_t.strftime('%Y/%m/%d %H:%M:%S.')}{_t.microsecond // 1000:03d}|{_m}|INFO|{_msg}")
(LOG_DIR / "vendor_b.log").write_text("\n".join(_vb) + "\n", encoding="utf-8")
print(f"异构日志: vendor_b.log  {len(_vb)} 行（行布局不同，键名相同）")

# legacy_c：无级别、无模块、键名不同、缺一批埋点
_lc: list[str] = []
for _t, _m, _msg in _hetero_rows():
    _msg2 = (_msg.replace("target=", "pos=").replace("speed=", "spd=")
             .replace("Cycle End lot=", "lot=")
             .replace("result=", "res=")
             .replace(" ct=", " cycle_ms="))                # 节拍字段名不同、且不是 ct
    _msg2 = re.sub(r"\s+seq=\d+", "", _msg2)               # 通信序号：字段直接不埋
    _lc.append(f"{_t.strftime('%Y-%m-%d %H:%M:%S.')}{_t.microsecond // 1000:03d} {_msg2}")
(LOG_DIR / "legacy_c.log").write_text("\n".join(_lc) + "\n", encoding="utf-8")
print(f"异构日志: legacy_c.log  {len(_lc)} 行（键名不同 + 缺埋点）")

# ------------------------------------------------------------------ 伺服波形 CSV
# ⚠ 效力说明：这三份波形的**真值是本脚本按物理模型算出来的**（ωn/ζ/谐振频率/误差斜率），
#   所以「诊断结果 vs .truth.json」是**有外部真值**的核对，不是自证。
#   但它们仍是仿真波形，不能代表你们机器的真实波形。

import math  # noqa: E402

FS = 2000.0


def _write_servo(name: str, t: list[float], cmd: list[float], fb: list[float],
                 err: list[float], vel: list[float], truth: dict) -> None:
    lines = ["time_ms,cmd_pos,fb_pos,err,vel"]
    for i in range(len(t)):
        lines.append(f"{t[i] * 1000:.4f},{cmd[i]:.6f},{fb[i]:.6f},{err[i]:.6f},{vel[i]:.6f}")
    (SERVO_DIR / f"{name}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (SERVO_DIR / f"{name}.truth.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"伺服波形: {name}.csv  {len(t)} 点 -> {SERVO_DIR / (name + '.csv')}")


# A) 正常：阻尼充足的二阶伺服（ωn=40 rad/s, ζ=0.7），超调约 4.6%
_a_wn, _a_z, _a_amp = 40.0, 0.7, 100.0
_a_n = int(0.8 * FS) + 1
_a_t = [i / FS for i in range(_a_n)]
_a_wd = _a_wn * math.sqrt(1 - _a_z ** 2)
_a_cmd = [_a_amp] * _a_n
_a_fb = []
for _ti in _a_t:
    _y = 1 - math.exp(-_a_z * _a_wn * _ti) * (
        math.cos(_a_wd * _ti) + (_a_z / math.sqrt(1 - _a_z ** 2)) * math.sin(_a_wd * _ti))
    _a_fb.append(_y * _a_amp)
_a_err = [_a_cmd[i] - _a_fb[i] for i in range(_a_n)]
_a_vel = [(_a_fb[min(i + 1, _a_n - 1)] - _a_fb[i]) * FS for i in range(_a_n)]
_write_servo("case_a_normal", _a_t, _a_cmd, _a_fb, _a_err, _a_vel,
             {"case": "正常二阶伺服", "wn_rad_s": _a_wn, "zeta": _a_z,
              "overshoot_pct": 100 * math.exp(-math.pi * _a_z / math.sqrt(1 - _a_z ** 2)),
              "expect_findings": [], "note": "阻尼充足，无谐振；不应报出高危项"})

# B) 机械谐振：位置环本身阻尼充足（ζ=0.8），叠加一个 35 Hz 的柔性传动模态（2.0 mm，指数衰减）
_b_wn, _b_z, _b_amp = 100.0, 0.8, 100.0
_b_fr, _b_fa, _b_fs = 35.0, 2.0, 8.0
_b_n = int(0.8 * FS) + 1
_b_t = [i / FS for i in range(_b_n)]
_b_wd = _b_wn * math.sqrt(1 - _b_z ** 2)
_b_cmd = [_b_amp] * _b_n
_b_fb = []
for _ti in _b_t:
    _y = 1 - math.exp(-_b_z * _b_wn * _ti) * (
        math.cos(_b_wd * _ti) + (_b_z / math.sqrt(1 - _b_z ** 2)) * math.sin(_b_wd * _ti))
    _b_fb.append(_y * _b_amp + _b_fa * math.exp(-_b_fs * _ti) * math.sin(2 * math.pi * _b_fr * _ti))
_b_err = [_b_cmd[i] - _b_fb[i] for i in range(_b_n)]
_b_vel = [(_b_fb[min(i + 1, _b_n - 1)] - _b_fb[i]) * FS for i in range(_b_n)]
_write_servo("case_b_resonance", _b_t, _b_cmd, _b_fb, _b_err, _b_vel,
             {"case": "柔性传动谐振", "loop_wn_rad_s": _b_wn, "loop_zeta": _b_z,
              "ringing_hz": _b_fr, "ringing_amp_mm": _b_fa, "ringing_decay_per_s": _b_fs,
              "expect_findings": ["SRV-02"],
              "note": "机械谐振模态 35 Hz 落在 12~120 Hz 疑似区间，SRV-02 应命中"})

# C) type-1：位置环无速度前馈 —— 匀速段跟随误差与速度严格成正比（不收敛）
_c_vmax, _c_k = 200.0, 0.002          # 误差 = 0.002 s × 速度
_c_t_acc, _c_t_cruise, _c_t_dec = 0.05, 0.40, 0.05
_c_n = int(0.8 * FS) + 1
_c_t = [i / FS for i in range(_c_n)]
_c_vel = []
_c_cmd = []
_x = 0.0
for _ti in _c_t:
    if _ti < _c_t_acc:
        _v = _c_vmax * _ti / _c_t_acc
    elif _ti < _c_t_acc + _c_t_cruise:
        _v = _c_vmax
    elif _ti < _c_t_acc + _c_t_cruise + _c_t_dec:
        _v = _c_vmax * (1 - (_ti - _c_t_acc - _c_t_cruise) / _c_t_dec)
    else:
        _v = 0.0
    _c_vel.append(_v)
    _cmd_i = _x + _v / FS
    _c_cmd.append(_cmd_i)
    _x = _cmd_i
_c_err = [_c_k * _c_vel[i] for i in range(_c_n)]
_c_fb = [_c_cmd[i] - _c_err[i] for i in range(_c_n)]
_write_servo("case_c_no_feedforward", _c_t, _c_cmd, _c_fb, _c_err, _c_vel,
             {"case": "type-1 无速度前馈（匀速段）", "err_per_vel_s": _c_k,
              "max_velocity_mm_s": _c_vmax, "expect_findings": ["SRV-05"],
              "note": "误差与速度严格成正比（相关系数=1），SRV-05 应命中；"
                      "且指令在持续变化 → 阶跃类指标不适用"})

