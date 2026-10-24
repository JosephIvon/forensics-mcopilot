"""设备日志取证智能体（forensics）：把「偶发定位偏差 / 时序竞争 / 通信丢包 / 良率波动」
从「现场靠人翻日志」变成「机器重建时间轴 + 规则检出 + 带证据的根因候选」。

设计原则：
  · 每条结论都必须能指回原始日志的**行号**，人可复核、可反驳；
  · 阈值全部来自 log_rules.json，改阈值不改代码；
  · 换日志格式只改 log_format.json；
  · 宁可少报也不误报 —— 误报会让工程师不再信任工具。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..core.report import Report, callout
from ..core.util import (fmt, knowledge_path, md_table, percentile, read_json, stdev,
                         write_text)


@dataclass
class Line:
    no: int
    ts: datetime | None
    level: str
    src: str
    msg: str
    raw: str
    events: list[dict] = field(default_factory=list)

    def get(self, etype: str) -> dict | None:
        for e in self.events:
            if e["type"] == etype:
                return e
        return None


@dataclass
class Finding:
    fid: str
    level: str
    title: str
    detail: str
    impact: str
    suggestion: str
    count: int = 1
    evidence: list[tuple[int, str]] = field(default_factory=list)


# ------------------------------------------------------------------ 解析


def _load_rules() -> dict:
    return read_json(knowledge_path("log_rules.json"))


def _load_format(fmt_name: str | None = None) -> dict:
    f = read_json(knowledge_path("log_format.json"))
    if fmt_name and fmt_name != f.get("name"):
        raise SystemExit(f"未找到日志格式 '{fmt_name}'，当前仅内置：{f.get('name')}")
    return f


def parse_log(path: Path, fmt: dict, rules: dict) -> tuple[list[Line], int]:
    line_re = re.compile(fmt["line_regex"])
    event_res = [(e["type"], re.compile(e["regex"])) for e in rules["events"]]
    ts_fmt = fmt.get("timestamp_format", "%Y-%m-%d %H:%M:%S.%f")
    lines: list[Line] = []
    skipped = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for no, raw in enumerate(fh, 1):
            raw = raw.rstrip("\n")
            if not raw.strip():
                continue
            m = line_re.match(raw)
            if not m:
                skipped += 1
                continue
            g = m.groupdict()
            try:
                ts = datetime.strptime(g[fmt["timestamp_field"]], ts_fmt)
            except (ValueError, KeyError):
                ts = None
            line = Line(no=no, ts=ts, level=(g.get("level") or "").upper(),
                        src=g.get("src") or "", msg=g.get("msg") or "", raw=raw)
            for etype, rx in event_res:
                em = rx.search(line.msg)
                if em:
                    ev = {"type": etype, "fields": em.groupdict()}
                    line.events.append(ev)
            lines.append(line)
    return lines, skipped


# ------------------------------------------------------------------ 检测器


def _ms(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() * 1000.0


def detect(lines: list[Line], rules: dict) -> list[Finding]:
    th = rules["thresholds"]
    sev = rules.get("severity", {})
    findings: list[Finding] = []

    def add(fid: str, title: str, detail: str, impact: str, suggestion: str,
            evidence: Iterable[tuple[int, str]] = (), count: int = 1) -> None:
        findings.append(Finding(fid=fid, level=sev.get(fid, "中"), title=title, detail=detail,
                                impact=impact, suggestion=suggestion, count=count,
                                evidence=list(evidence)[:8]))

    # 1) 指令 → 到位：时延超限 / 位置偏差 / 并发指令
    pending: dict[int, tuple[datetime | None, float, Line]] = {}
    latency_hits: list[tuple[int, str, float]] = []
    dev_hits: list[tuple[int, str, float]] = []
    concur_hits: list[tuple[int, str, int]] = []

    for ln in lines:
        mc = ln.get("MOVE_CMD")
        if mc:
            axis = int(mc["fields"].get("axis", -1))
            if axis in pending and pending[axis][0] is not None and ln.ts is not None:
                gap = _ms(pending[axis][0], ln.ts)
                concur_hits.append((ln.no, ln.raw, axis))
            pending[axis] = (ln.ts, float(mc["fields"].get("target", 0.0)), ln)
            continue
        rc = ln.get("REACHED")
        if rc:
            axis = int(rc["fields"].get("axis", -1))
            if axis in pending:
                cmd_ts, target, cmd_line = pending.pop(axis)
                pos = float(rc["fields"].get("pos", 0.0))
                if cmd_ts and ln.ts:
                    lat = _ms(cmd_ts, ln.ts)
                    if lat > th["reached_latency_ms"]:
                        latency_hits.append((ln.no, ln.raw, lat))
                dev = abs(pos - target)
                if dev > th["position_tolerance_mm"]:
                    dev_hits.append((ln.no, ln.raw, dev))

    if latency_hits:
        worst = max(latency_hits, key=lambda h: h[2])
        add("reached_latency",
            f"指令到到位时延超限（阈值 {th['reached_latency_ms']} ms）",
            f"共 {len(latency_hits)} 次超出阈值，最长 {worst[2]:.0f} ms",
            "节拍被拉长；到位判定若靠轮询，误差还会叠加到定位公差",
            "用 `mcopilot motion plan` 算理论到位时间对比；若理论远小于实测，查状态轮询周期与减速段设置",
            [(h[0], h[1]) for h in latency_hits], count=len(latency_hits))
    if dev_hits:
        worst = max(dev_hits, key=lambda h: h[2])
        add("position_deviation",
            f"指令位置与回读位置偏差超差（阈值 {th['position_tolerance_mm']} mm）",
            f"共 {len(dev_hits)} 次超差，最大偏差 {worst[2]:.4f} mm",
            "直接表现为「偶发定位偏差」，是漏检率与贴装精度问题的常见根因",
            "优先核对 pulse_per_mm 等轴参数是否被换型流程覆盖；再用 `mcopilot motion gear` 复核换算",
            [(h[0], h[1]) for h in dev_hits], count=len(dev_hits))
    if concur_hits:
        add("concurrent_command",
            "同一轴存在未完成即下发新指令（时序竞争）",
            f"共 {len(concur_hits)} 处",
            "后发指令会打断前一指令，造成半程位置偏差；也可能是重复触发",
            "在流程调度器里给轴加互斥与「运动中拒绝下发」；排查 UI 手动操作与流程任务抢占",
            [(c[0], c[1]) for c in concur_hits], count=len(concur_hits))

    # 2) 轴参数写入冲突（换型竞态 / 多处写同一参数）
    last_write: dict[tuple[int, str], tuple[datetime | None, float, Line]] = {}
    conflict_hits: list[tuple[int, str, int, float]] = []
    for ln in lines:
        pw = ln.get("PARAM_WRITE")
        if not pw:
            continue
        axis = int(pw["fields"].get("axis", -1))
        key = pw["fields"].get("key", "")
        val = float(pw["fields"].get("value", 0.0))
        k = (axis, key)
        prev = last_write.get(k)
        if prev and prev[0] and ln.ts:
            dt = _ms(prev[0], ln.ts)
            if dt <= th["param_conflict_window_ms"] and abs(prev[1] - val) > 1e-9:
                conflict_hits.append((ln.no, ln.raw, axis, val))
        last_write[k] = (ln.ts, val, ln)
    if conflict_hits:
        add("param_conflict",
            "轴参数在短时间内被写入不同值（换型竞态）",
            f"共 {len(conflict_hits)} 处冲突",
            "参数被后写入者覆盖，会造成「同样的配方在不同班次结果不同」的偶发性问题",
            "统一参数写入口并加版本号；配方下发与轴初始化串行化；写入后回读校验",
            [(c[0], c[1]) for c in conflict_hits], count=len(conflict_hits))

    # 3) 通信序号跳变（丢包）—— 大跨度跳变多半是计数器重置，不是丢包，分开报
    seq_last: dict[int, int] = {}
    gap_hits: list[tuple[int, str, int]] = []
    reset_hits: list[tuple[int, str, int]] = []
    max_loss = th.get("comm_gap_max_loss", 200)
    for ln in lines:
        cs = ln.get("COMM_SEQ")
        if not cs:
            continue
        axis = int(cs["fields"].get("axis", -1))
        seq = int(cs["fields"].get("seq", 0))
        if axis in seq_last:
            miss = seq - seq_last[axis] - 1
            if miss > th["comm_gap_allowed"] - 1:
                (reset_hits if miss > max_loss else gap_hits).append((ln.no, ln.raw, miss))
        seq_last[axis] = seq
    if gap_hits:
        total_miss = sum(g[2] for g in gap_hits)
        add("comm_gap",
            "通信序号跳变（丢包或重发）",
            f"共 {len(gap_hits)} 处跳变，累计丢失 {total_miss} 帧",
            "丢包会触发重试与超时，进而表现为定位偏差或节拍抖动",
            "检查交换机端口缓冲与网络负载；上位机侧对同一轴的命令做串行化，避免并发发送",
            [(g[0], g[1]) for g in gap_hits], count=len(gap_hits))
    if reset_hits:
        add("comm_gap",
            "通信序号出现大跨度跳变（疑似计数器重置或长时间未通信）",
            f"共 {len(reset_hits)} 处，跨度最大 {max(r[2] for r in reset_hits)} 帧",
            "本身不一定是故障，但会让「丢包」统计失真，也会掩盖真实问题",
            "确认对端是否在空闲后重置了序号；若是，检查通信线程是否被长时间阻塞",
            [(r[0], r[1]) for r in reset_hits], count=len(reset_hits))

    # 4) 标定残差漂移
    cal: list[tuple[int, str, float]] = []
    for ln in lines:
        c = ln.get("CALIB")
        if c:
            cal.append((ln.no, ln.raw, float(c["fields"].get("residual", 0.0))))
    if cal:
        over = [c for c in cal if c[2] > th["calib_residual_um"]]
        if over:
            add("calib_drift",
                f"标定残差超阈值（{th['calib_residual_um']} μm）",
                f"共 {len(over)}/{len(cal)} 次超差，最大 {max(c[2] for c in over):.1f} μm",
                "视觉引导对位精度下降，贴装/耦合位置随之漂移",
                "重标定并复测；检查相机镜头支架紧固与温漂",
                [(c[0], c[1]) for c in over], count=len(over))
        elif len(cal) >= 6:
            half = len(cal) // 2
            first = sum(c[2] for c in cal[:half]) / half
            second = sum(c[2] for c in cal[half:]) / (len(cal) - half)
            if second > first * 1.5 and second - first > 0.5:
                add("calib_drift",
                    "标定残差呈上升趋势（机械松动或温漂）",
                    f"前半段均值 {first:.2f} μm → 后半段均值 {second:.2f} μm",
                    "精度会持续劣化，属于典型的「慢慢变坏」型问题",
                    "排查相机/镜头支架与标定板工装；加入残差趋势监控告警",
                    [(c[0], c[1]) for c in cal[-4:]], count=1)

    # 5) 节拍抖动
    cts = [float(ln.get("CYCLE_END")["fields"].get("ct", 0.0)) for ln in lines if ln.get("CYCLE_END")]
    if len(cts) >= 8:
        med = percentile(cts, 0.5)
        p95 = percentile(cts, 0.95)
        ratio = (p95 - med) / med if med else 0.0
        cv = stdev(cts) / med if med else 0.0        # 「少数几拍很慢」是节拍不稳最常见的形态，
        # 而 P95/中位数 与 CV 都会把这种尾部劣化稀释掉。
        # 所以再加一个直指标记：慢拍占比（中位数 1.15 倍以上）。
        slow = sum(1 for c in cts if c > med * 1.15)
        slow_ratio = slow / len(cts)
        if (ratio > th["cycle_jitter_ratio"] or cv > th.get("cycle_jitter_cv", 0.08)
                or slow_ratio > th.get("cycle_slow_ratio", 0.02)):
            add("cycle_jitter",
                "节拍抖动超阈值",
                f"中位数 {med:.1f} s，P95 {p95:.1f} s，波动 {(p95 - med) / med:.0%}，"
                f"变异系数 {cv:.1%}，慢拍（>1.15×中位数）占比 {slow_ratio:.0%}（{slow}/{len(cts)}）",
                "节拍不稳会挤占产能缓冲，也常伴随通信/IO 抖动",
                "对齐抖动最大的批次与超时/丢包事件；检查关键路径上的无界等待与重试",
                [(ln.no, ln.raw) for ln in lines if ln.get("CYCLE_END")][:6], count=max(slow, 1))

    # 6) 超时聚集
    tos = [(ln.no, ln.raw, float(ln.get("TIMEOUT")["fields"].get("waited", 0.0)))
           for ln in lines if ln.get("TIMEOUT")]
    if len(tos) >= th["timeout_burst_count"]:
        add("timeout_burst",
            f"超时事件聚集（{len(tos)} 次）",
            f"最长等待 {max(t[2] for t in tos):.1f} s",
            "超时+重试会放大节拍抖动，并可能掩盖真正的失败原因",
            "区分「设备真的慢」与「代码等错条件」；给等待加明确超时与原因分类",
            [(t[0], t[1]) for t in tos], count=len(tos))

    # 7) 心跳/日志断流（设备卡死或掉线）
    hb = [(ln.no, ln.ts) for ln in lines if ln.get("HEARTBEAT")]
    hb_gaps: list[tuple[int, str, float]] = []
    for i in range(1, len(hb)):
        if hb[i][1] and hb[i - 1][1]:
            gap = _ms(hb[i - 1][1], hb[i][1])
            if gap > th["heartbeat_gap_ms"]:
                hb_gaps.append((hb[i][0], f"心跳间隔 {gap:.0f} ms（行 {hb[i-1][0]} → {hb[i][0]}）", gap))
    if hb_gaps:
        add("heartbeat_gap",
            f"心跳/日志断流（>{th['heartbeat_gap_ms']} ms）",
            f"共 {len(hb_gaps)} 处，最大 {max(g[2] for g in hb_gaps):.0f} ms",
            "期间的状态完全不可见，故障后无法还原现场",
            "检查上位机采集线程是否被阻塞；关键状态改走独立线程并落盘",
            [(g[0], g[1]) for g in hb_gaps], count=len(hb_gaps))

    # 8) 视觉不良率（分段看，避免全程平均把「某段时间变差」稀释掉）
    vis = [(ln.no, ln.raw) for ln in lines if ln.get("VISION")]
    if len(vis) >= 10:
        overall = sum(1 for _, raw in vis if "result=NG" in raw) / len(vis)
        n_win = min(10, len(vis) // 5)
        size = max(1, len(vis) // n_win)
        bad_window = None
        for w in range(n_win):
            chunk = vis[w * size: (w + 1) * size]
            if not chunk:
                continue
            ng = sum(1 for _, raw in chunk if "result=NG" in raw)
            rate = ng / len(chunk)
            limit = max(th["vision_ng_rate"], overall * th.get("vision_ng_ratio", 3.0))
            if rate > limit:
                bad_window = (w, chunk, rate, limit)
                break
        if bad_window:
            w, chunk, rate, limit = bad_window
            ng_in_window = sum(1 for _, raw in chunk if "result=NG" in raw)
            add("vision_ng_rate",
                "视觉判定不良率在某一区段显著升高",
                f"全程不良率 {overall:.0%}，第 {w + 1} 区段升至 {rate:.0%}"
                f"（{len(chunk)} 次判定），触发线 {limit:.0%}",
                "视觉引导是定位精度闭环，不良率上升通常伴随标定或工艺漂移",
                "先看 dx/dy 是否有方向性偏移，再看标定残差与该区段的换型/换料记录",
                [(c[0], c[1]) for c in chunk][:6], count=ng_in_window)

    return findings


# ------------------------------------------------------------------ 根因候选


def rank_root_causes(findings: list[Finding], rules: dict) -> list[dict]:
    """根因候选排序。

    排序口径：**严重度优先，次数次之**（字典序）。
    否则「高频但低信号」的发现（比如统计了 120 个节拍）会把
    「低频但高危」的发现（比如 2 次定位偏差）压下去 —— 而后者才是该先查的。
    """
    rcm = rules.get("root_cause_map", {})
    weight = {"高": 3.0, "中": 2.0, "低": 1.0}
    scores: dict[str, dict] = {}
    for f in findings:
        for cand in rcm.get(f.fid, []):
            key = cand["cause"]
            ent = scores.setdefault(key, {"cause": key, "severity": 0.0, "count": 0, "from": [],
                                          "verify": cand.get("verify", ""), "requirement": cand.get("requirement", "")})
            w = weight.get(f.level, 1.0)
            ent["severity"] = max(ent["severity"], w)
            ent["count"] += f.count
            ent["from"].append(f"{f.fid}({f.level})")
    for ent in scores.values():
        ent["score"] = round(ent["severity"] * 10 + ent["count"], 2)
    return sorted(scores.values(), key=lambda e: (-e["severity"], -e["count"]))


# ------------------------------------------------------------------ 格式体检（probe）
# 目的：把「这套工具对你们的日志有多少耦合」变成**可量化的数字**，而不是一句
# 「改 log_format.json 就行」。
#
# 关键认识：forensics 与样例日志是**同源**的（样例由 make_samples.py 按同一套约定生成），
# 所以「样例全检出」不能证明它对你们的日志有效。probe 就是用来回答
# 「换成你们的日志，要改多少东西、哪些检测器会直接瘫掉」的。

_TS_RE = re.compile(
    r"(\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?)"
    r"|(\d{4}[-/]\d{2}[-/]\d{2}(?:[ T]\d{2}:\d{2}:\d{2})?)"
    r"|(\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?)")

_KV_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*([^\s,;\]|\)]+)")
_LEVEL_RE = re.compile(
    r"\b(TRACE|DEBUG|INFO|INFORMATION|WARN|WARNING|ERROR|ERR|FATAL|CRITICAL|NOTICE)\b", re.I)
_BRACKET_RE = re.compile(r"\[([^\]]{1,40})\]")

_TS_FORMATS = [
    ("%Y-%m-%d %H:%M:%S.%f", "到毫秒"), ("%Y-%m-%d %H:%M:%S", "到秒"),
    ("%Y/%m/%d %H:%M:%S.%f", "到毫秒"), ("%Y/%m/%d %H:%M:%S", "到秒"),
    ("%Y-%m-%dT%H:%M:%S.%f", "到毫秒"), ("%Y-%m-%dT%H:%M:%S", "到秒"),
    ("%Y.%m.%d %H:%M:%S.%f", "到毫秒"), ("%Y.%m.%d %H:%M:%S", "到秒"),
    ("%H:%M:%S.%f", "仅时分秒"), ("%H:%M:%S", "仅时分秒"),
]


def _literal_words(rx: str) -> list[str]:
    """从事件正则里拆出「固定文字」与「键名」。

    例如 `CMD MoveAbs\\s+axis=(?P<axis>\\d+)` → 固定文字 ["CMD","MoveAbs"]，键名 ["axis"]。
    """
    s = re.sub(r"\(\?P<\w+>[^)]*\)", " ", rx)
    s = re.sub(r"\\[dwsWDS]", " ", s)
    s = re.sub(r"[\\^$.|?*+()\[\]{}]", " ", s)
    words, keys = [], []
    for tok in s.split():
        tok = tok.strip()
        if not tok:
            continue
        if tok.endswith("="):
            keys.append(tok[:-1])
        elif re.search(r"[A-Za-z]", tok):
            words.append(tok)
    return words, keys


def _event_specs(rules: dict) -> list[dict]:
    specs = []
    for e in rules["events"]:
        named = re.findall(r"\(\?P<(\w+)>", e["regex"])
        words, keys = _literal_words(e["regex"])
        specs.append({"type": e["type"], "regex": e["regex"], "named": named,
                      "words": words, "keys": keys})
    # 区分「特征词」与「通用词」：
    #   CMD / Cycle 这类词被多个事件共用，不能用来判断「这类事件在不在这份日志里」；
    #   MoveAbs / Jog / HomeDone 这种只属于一个事件的词才能。
    # 早期版本用全部字面词判断，导致 JOG_CMD 因为 MoveAbs 行里也有 axis= 和 speed=
    # 而被误判成「需改正则」—— 实际那份日志里根本没有 Jog 点动。
    counter: dict[str, int] = {}
    for sp in specs:
        for w in set(sp["words"]):
            counter[w] = counter.get(w, 0) + 1
    for sp in specs:
        sp["distinctive"] = [w for w in sp["words"] if counter[w] <= 1]
        sp["generic"] = [w for w in sp["words"] if counter[w] > 1]
    return specs


def _word_hit(line: str, word: str) -> bool:
    """整词匹配：'Write' 不该命中 'ParamWrite'，'Stop' 不该命中 'Stopper'。"""
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", line, re.I) is not None


def _near_miss_keys(marker_line: str, keys: list[str]) -> dict[str, str]:
    """缺字段时，猜「你可能是想写什么」。

    按**出现顺序对齐**来配对：正则要求 target/speed，日志写的是 pos/spd，
    就应该给出 target→pos、speed→spd，而不是按出现频次乱配。
    """
    line_keys = [k for k, _ in _KV_RE.findall(marker_line)]
    out: dict[str, str] = {}
    li = 0
    for k in keys:
        if k in line_keys and k not in out:
            # 跳过日志里对应位置之前的其他键
            idx = line_keys.index(k)
            li = max(li, idx + 1)
            continue
        while li < len(line_keys):
            cand = line_keys[li]
            li += 1
            if cand not in keys and cand not in out:
                out[k] = cand
                break
    return out


def _detect_timestamp(sample: str) -> dict:
    m = _TS_RE.search(sample)
    if not m:
        return {"found": False, "example": None, "format": None, "precision": None}
    raw = next(g for g in m.groups() if g)
    raw = raw.replace("/", "-").replace(",", ".")
    for fmt, prec in _TS_FORMATS:
        try:
            datetime.strptime(raw, fmt)
            return {"found": True, "example": raw, "format": fmt, "precision": prec}
        except ValueError:
            continue
    return {"found": True, "example": raw, "format": None, "precision": None}


def _suggest_line_regex(ts: dict, level_hits: int, bracket_groups: int) -> str:
    """根据探测到的结构，给一个可用的 line_regex 起点。"""
    parts = []
    if ts["found"]:
        if ts["precision"] == "到毫秒":
            parts.append(r"(?P<ts>\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2}[.,]\d{1,6})")
        elif ts["precision"] == "到秒":
            parts.append(r"(?P<ts>\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2})")
        else:
            parts.append(r"(?P<ts>.+?)")
    else:
        parts.append(r"(?P<ts>.+?)")
    if level_hits:
        parts.append(r"\[(?P<level>[A-Za-z]+)\s*\]")
    if bracket_groups >= 2:
        parts.append(r"\[(?P<src>[^\]]+)\]")
    parts.append(r"(?P<msg>.*)$")
    return " ".join(parts)


def probe(path: Path, rules: dict | None = None, fmt: dict | None = None) -> dict:
    """对任意日志做格式体检，量化「适配成本」与「哪些检测器会瘫掉」。

    返回结构里最关键的两个数字：
      · ``match_rate``     —— 现有格式能直接解析的行占比
      · ``adapt_cost``     —— 需要改正则的事件类型占比（格式耦合成本）
      · ``blocked_detectors`` —— 因缺字段而完全跑不了的检测器
    """
    rules = rules or _load_rules()
    fmt = fmt or _load_format()

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        raw_lines = [ln.rstrip("\n") for ln in fh]
    non_empty = [ln for ln in raw_lines if ln.strip()]

    # 1) 现有格式能吃下多少
    lines, skipped = parse_log(path, fmt, rules)
    match_rate = len(lines) / len(non_empty) if non_empty else 0.0

    # 2) 结构探测（与具体格式无关）
    ts = _detect_timestamp(non_empty[0] if non_empty else "")
    key_counts: dict[str, int] = {}
    key_example: dict[str, str] = {}
    level_hits = 0
    shapes: dict[tuple, dict] = {}
    for ln in non_empty:
        if _LEVEL_RE.search(ln):
            level_hits += 1
        keys = []
        for k, v in _KV_RE.findall(ln):
            keys.append(k)
            key_counts[k] = key_counts.get(k, 0) + 1
            key_example.setdefault(k, v)
        sig = tuple(sorted(set(keys)))
        entry = shapes.setdefault(sig, {"count": 0, "example": ln.strip(), "keys": list(sig)})
        entry["count"] += 1

    # 3) 逐个事件类型评估 —— 这一层只看「事件正则认不认得日志里的内容」，
    #    与行格式无关。行格式是另一层（见 match_rate）。
    specs = _event_specs(rules)
    events: list[dict] = []
    for sp in specs:
        keys = sp["keys"] or sp["named"]
        rx = re.compile(sp["regex"])
        marker_lines: list[str] = []
        key_lines: list[str] = []
        regex_hit = 0
        for ln in non_empty:
            if rx.search(ln):
                regex_hit += 1
            # 特征词命中 = 这类事件确实出现在这份日志里。
            # 三个条件缺一不可，否则会大量误判：
            #   ① 特征词整词匹配（ParamWrite 不算 IO Write）；
            #   ② 必须同时出现至少一个必填字段（'App Stop' 不算 STOP 事件）；
            #   ③ 必填字段不全（缺字段）时才叫「需改正则」。
            if (sp["distinctive"]
                    and all(_word_hit(ln, w) for w in sp["distinctive"])
                    and any(_word_hit(ln, k) for k in keys)):
                marker_lines.append(ln)
            present = {k for k, _ in _KV_RE.findall(ln)}
            if keys and all(k in present for k in keys):
                key_lines.append(ln)

        missing = [k for k in keys if key_counts.get(k, 0) == 0]
        if regex_hit > 0:
            status = "已支持"
            suggestion = ""
        elif marker_lines:
            # 这类事件确实在日志里，但正则没认出来 → 要改正则（或改键名）
            near = _near_miss_keys(marker_lines[0], keys) if missing else {}
            near = {k: v for k, v in near.items() if k in missing}
            if near:
                status = "缺字段"
                pairs = "、".join(f"{k}→可能是 {v}" for k, v in near.items())
                suggestion = (f"日志里有 {len(marker_lines)} 行这类事件，但字段名不同：{pairs}。"
                              f"把 log_rules.json 里该条正则的字段名换成日志里的写法即可。")
            else:
                status = "需改正则"
                suggestion = (f"日志里有 {len(marker_lines)} 行这类事件（特征词 "
                              f"{'、'.join(sp['distinctive'])}），但现有正则没匹配上。"
                              f"多半是空格/顺序/分隔符不同，照着样例行改正则即可。")
        else:
            status = "未出现"
            suggestion = (f"这份日志里没有这类事件（特征词 {'、'.join(sp['distinctive']) or '—'} "
                          f"一次都没出现）。**不是格式问题，是没有埋点** —— "
                          f"对应检测器在这份日志上无数据可跑。")
        events.append({
            "type": sp["type"], "status": status, "required_keys": keys,
            "key_counts": {k: key_counts.get(k, 0) for k in keys},
            "distinctive_words": sp["distinctive"],
            "marker_lines": len(marker_lines), "key_lines": len(key_lines),
            "regex_hit": regex_hit,
            "examples": [c.strip() for c in marker_lines[:2]] or
                        ([non_empty[0].strip()] if non_empty else []),
            "suggestion": suggestion,
        })

    # 4) 检测器覆盖：分成两种「跑不了」，性质完全不同，不能混为一谈
    req = rules.get("detector_requires", {})
    ev_status = {e["type"]: e["status"] for e in events}
    detectors: list[dict] = []
    for det, need in req.items():
        bad = [n for n in need if ev_status.get(n) != "已支持"]
        by_format = [n for n in bad if ev_status.get(n) in ("需改正则", "缺字段")]
        by_nodata = [n for n in bad if ev_status.get(n) == "未出现"]
        detectors.append({"detector": det, "needs": need,
                          "blocked_by_format": by_format, "no_data": by_nodata,
                          "runnable": not bad})

    n_events = len(events)
    n_fix = sum(1 for e in events if e["status"] in ("需改正则", "缺字段"))
    n_absent = sum(1 for e in events if e["status"] == "未出现")
    n_det = len(detectors)
    n_blocked_fmt = sum(1 for d in detectors if d["blocked_by_format"])
    n_blocked_data = sum(1 for d in detectors if d["no_data"])
    bracket_groups = len(_BRACKET_RE.findall(non_empty[0])) if non_empty else 0

    if match_rate > 0.95 and n_fix == 0:
        verdict = "可直接分析"
    elif ts["found"] and key_counts:
        # 日志结构认得出来，只是格式/正则对不上 —— 改配置即可，不用改代码
        verdict = "需适配"
    else:
        verdict = "暂不适用"

    return {
        "file": str(path),
        "total_lines": len(non_empty),
        "parsed_lines": len(lines),
        "unparsed_lines": skipped,
        "match_rate": match_rate,
        "line_format_ok": match_rate > 0.95,
        "timestamp": ts,
        "level_lines": level_hits,
        "keys": dict(sorted(key_counts.items(), key=lambda kv: -kv[1])),
        "shapes": sorted(shapes.values(), key=lambda s: -s["count"])[:8],
        "events": events,
        "detectors": detectors,
        "adapt_cost": (n_fix / n_events) if n_events else 0.0,
        "events_needing_fix": n_fix,
        "events_absent": n_absent,
        "blocked_by_format": n_blocked_fmt,
        "blocked_no_data": n_blocked_data,
        "detector_total": n_det,
        "suggested_line_regex": _suggest_line_regex(ts, level_hits, bracket_groups),
        "verdict": verdict,
    }


def run_probe(path: Path, out_dir: Path | None = None, stem: str | None = None) -> dict[str, Any]:
    pr = probe(path)
    rep = build_probe_report(pr)
    stem = stem or f"probe_{path.stem}"
    written: dict[str, Path] = {}
    if out_dir:
        written = rep.write(out_dir, stem)
    return {"report": rep, "probe": pr, "written": written}


def build_probe_report(pr: dict) -> Report:
    rep = Report(title="日志格式体检报告",
                 subtitle=f"{Path(pr['file']).name}　|　"
                          f"行格式匹配 {pr['match_rate']:.0%}　|　"
                          f"事件正则要改 {pr['events_needing_fix']}/{len(pr['events'])} 类"
                          f"（适配成本 {pr['adapt_cost']:.0%}）　|　"
                          f"因格式跑不了的检测器 {pr['blocked_by_format']}/{pr['detector_total']}")
    if pr["verdict"] == "可直接分析":
        rep.add("结论", callout("低", "**现有格式就能直接分析。** "
                                      "但请注意：本工具的样例与规则同源，"
                                      "「能解析」只说明格式对得上，不说明规则对你们的业务语义正确 —— "
                                      "请用真实故障案例复核一遍阈值。"))
    else:
        problems = []
        if not pr["line_format_ok"]:
            problems.append(f"**行格式**只匹配 {pr['match_rate']:.0%} 的行 —— "
                            f"日志切不开，事件正则再对也没用（下面第 1 层给了可用的 `line_regex` 起点）")
        if pr["events_needing_fix"]:
            problems.append(f"**{pr['events_needing_fix']} 类事件**的写法与现有正则对不上，"
                            f"会让 {pr['blocked_by_format']} 个检测器跑不了（下面第 2 层逐条列了怎么改）")
        if not problems:
            problems.append("结构认得出来，只是有细节对不上")
        rep.add("结论", "\n".join([
            callout("中" if pr["verdict"] == "需适配" else "高",
                    f"**{pr['verdict']}**：" + "；".join(problems) + "。"),
            "",
            "**这是「格式耦合成本」的量化结果**，不是「工具不好用」。"
            "适配不需要改代码 —— 改 `knowledge/log_format.json` 的行格式 + "
            "`knowledge/log_rules.json` 里的事件正则即可。",
        ]))

    # --- 第 1 层：行格式 ---
    rep.add("第 1 层：行格式（能不能把「时间戳/级别/模块/消息」切开）", "\n".join([
        f"- **匹配率**：{pr['parsed_lines']}/{pr['total_lines']} 行"
        f"（{pr['match_rate']:.0%}）"
        + ("　→ 行格式没问题。" if pr["line_format_ok"] else
           "　→ **行格式对不上，日志根本切不开，后面所有事件正则都无从谈起。先改这一层。**"),
        f"- **时间戳**：{'识别为 ' + str(pr['timestamp']['example']) + '（' + str(pr['timestamp']['precision']) + '）' if pr['timestamp']['found'] else '未识别到时间戳'}",
        f"- **级别字段**：{pr['level_lines']}/{pr['total_lines']} 行含级别关键字",
        f"- **可用的 key=value 字段**（按出现次数）：" +
        "、".join(f"`{k}`×{v}" for k, v in list(pr["keys"].items())[:14]),
        "",
        "**建议的 line_regex 起点**（人工确认后再写进 log_format.json）：",
        "",
        "```",
        pr["suggested_line_regex"],
        "```",
    ]))

    # --- 第 2 层：事件正则 ---
    rep.add("第 2 层：事件正则（切出消息后，认不认得各类事件）", "\n".join([
        "状态含义：",
        "",
        "- **已支持** —— 现有正则能直接匹配到日志里的行，不用改。",
        "- **需改正则 / 缺字段** —— 这类事件**确实在日志里**，但写法跟正则对不上，"
        "要改 `log_rules.json`（这是格式问题）。",
        "- **未出现** —— 这份日志里**没有这类事件的埋点**。这不是格式问题，"
        "对应检测器在这份日志上就是无数据可跑（要跑就得先加埋点）。",
        "",
        "这两类「跑不了」性质完全不同，不能混为一谈：一个改配置就能解决，另一个得改你们的埋点。",
    ]))
    rep.add("逐类事件", md_table(
        ["事件类型", "状态", "必填字段（出现次数）", "要做什么"],
        [[e["type"], e["status"],
          "、".join(f"{k}({c})" for k, c in e["key_counts"].items()),
          e["suggestion"] or "无需改动"] for e in pr["events"]]))

    rep.add("日志的几种消息形态", md_table(
        ["出现次数", "字段组合", "样例"],
        [[s["count"], "、".join(s["keys"]) or "（无 key=value）", s["example"][:110]]
         for s in pr["shapes"]]))

    # --- 检测器可用性 ---
    rep.add("检测器可用性", md_table(
        ["检测器", "需要的事件", "能否运行", "被格式挡住", "无埋点（无数据）"],
        [[d["detector"], "、".join(d["needs"]), "能" if d["runnable"] else "**不能**",
          "、".join(d["blocked_by_format"]) or "—",
          "、".join(d["no_data"]) or "—"] for d in pr["detectors"]]))

    need = [e for e in pr["events"] if e["status"] in ("需改正则", "缺字段")]
    if need:
        blocks = []
        for e in need:
            blocks.append("\n".join([
                f"**{e['type']}**　你的日志长这样：", "", "```",
                e["examples"][0] if e["examples"] else "—", "```", "",
                e["suggestion"], ""]))
        rep.add("改法示例（拿这几行日志直接改正则）", "\n".join(blocks))
    return rep


# ------------------------------------------------------------------ 报告


def build_report(path: Path, lines: list[Line], skipped: int,
                 findings: list[Finding], roots: list[dict], rules: dict) -> Report:
    rep = Report(title="设备日志取证报告",
                 subtitle=f"日志：{path.name}　|　解析 {len(lines)} 行（未匹配格式 {skipped} 行）　|　"
                          f"检出缺陷 {len(findings)} 类")
    order = {"高": 0, "中": 1, "低": 2}
    findings = sorted(findings, key=lambda f: (order.get(f.level, 9), -f.count))

    if not findings:
        rep.add("结论", callout("低", "**在当前阈值下未检出异常。**"
                                      "若现场确认有问题，请调低 log_rules.json 的阈值后重跑，"
                                      "或补齐日志埋点（当前日志缺少必要字段时，工具无法凭空发现）。"))
        return rep

    top = findings[0]
    rep.add("结论先行", "\n".join([
        callout(top.level, f"**最高优先级问题：{top.title}** —— {top.detail}"),
        "",
        f"影响：{top.impact}",
        "",
        f"建议动作：{top.suggestion}",
        "",
        (f"**最可能的根因（按证据强度排序）**：{roots[0]['cause']}"
         if roots else "无匹配根因规则，建议人工判读"),
    ]))

    def _req_refs(fid: str) -> str:
        refs = sorted({c.get("requirement", "") for c in rules.get("root_cause_map", {}).get(fid, [])
                       if c.get("requirement")})
        return "、".join(refs) or "—"

    rep.add("缺陷清单", md_table(
        ["等级", "编号", "问题", "次数", "影响", "需求对应"],
        [[f.level, f.fid, f.title, f.count, f.impact, _req_refs(f.fid)]
         for f in findings]))

    detail = []
    for f in findings:
        detail.append(f"### {f.title}　`{f.fid}`（{f.level}）")
        detail.append(f"- **现象**：{f.detail}")
        detail.append(f"- **影响**：{f.impact}")
        detail.append(f"- **建议**：{f.suggestion}")
        if f.evidence:
            detail.append("- **证据（原始日志行）**：")
            for no, text in f.evidence:
                detail.append(f"  - `L{no}` {text}")
        detail.append("")
    rep.add("详细证据", "\n".join(detail))

    if roots:
        rep.add("根因候选排序", md_table(
            ["排序", "候选根因", "证据强度分", "支撑发现", "怎么验证", "需求"],
            [[i + 1, r["cause"], round(r["score"], 1), "、".join(r["from"]), r["verify"], r["requirement"]]
             for i, r in enumerate(roots[:8])]))
        rep.add("怎么用这份报告", "\n".join([
            "1. **先看结论先行的最高优先级问题**，它按「等级 × 次数」排序，不是按发现顺序。",
            "2. **拿证据行号去复现**：每条结论都指回了原始日志行，人可以直接核对，不必相信工具。",
            "3. **按「怎么验证」列逐条证伪**：根因候选是假设，不是结论；验证不成立就换下一条。",
            "4. **证伪后把结论固化成代码规范**：把复发预防项转成 `mcopilot review` 的规则，"
            "让下一次提交时自动拦住。",
        ]))
    return rep


def run(path: Path, out_dir: Path, stem: str | None = None) -> dict[str, Any]:
    rules = _load_rules()
    fmt = _load_format()
    lines, skipped = parse_log(path, fmt, rules)
    findings = detect(lines, rules)
    roots = rank_root_causes(findings, rules)
    rep = build_report(path, lines, skipped, findings, roots, rules)
    stem = stem or f"forensics_{path.stem}"
    return {"report": rep, "findings": findings, "roots": roots, "lines": len(lines)}
