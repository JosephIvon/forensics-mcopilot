"""阈值灵敏度分析 + 检测器误报边界表。

要回答两个问题（都是现场标定时绕不开的）：

1. **这条阈值脆不脆？** —— 阈值离「结论翻转点」越近，现场标定时越容易翻车。
   做法：把每条阈值单独拿出来扫（改一个值 → 重跑一次 detect() → 看该检测器的命中数怎么变），
   命中数开始变的那一点就是**翻转边界**。边界离当前值越近 = 越脆。
   网格只用来**圈定区间**，翻转点用**二分法**精确定位 —— 粗网格会让人误以为「都很稳」。

2. **这条检测器什么输入会误报？** —— 工具只说「触发了」，不说「该不该信」。
   误报源写在 knowledge/detector_meta.json（知识与代码分开），数据侧给出「低到多少就会开始命中」。

只做离线分析，不改任何阈值 —— 阈值怎么定是现场的事，这里只回答「定错了会有多危险」。
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from ..core.report import Report, callout
from ..core.util import knowledge_path, md_table, read_json
from . import forensics

# 每条阈值影响哪些检测器（一个阈值可能同时影响多个判定分支）
THRESHOLD_DETECTORS: dict[str, list[str]] = {
    "reached_latency_ms": ["reached_latency"],
    "position_tolerance_mm": ["position_deviation"],
    "concurrent_command_ms": ["concurrent_command"],
    "param_conflict_window_ms": ["param_conflict"],
    "comm_gap_allowed": ["comm_gap"],
    "comm_gap_max_loss": ["comm_gap"],
    "calib_residual_um": ["calib_drift"],
    "cycle_jitter_ratio": ["cycle_jitter"],
    "cycle_jitter_cv": ["cycle_jitter"],
    "cycle_slow_ratio": ["cycle_jitter"],
    "timeout_burst_count": ["timeout_burst"],
    "heartbeat_gap_ms": ["heartbeat_gap"],
    "vision_ng_rate": ["vision_ng_rate"],
    "vision_ng_ratio": ["vision_ng_rate"],
}

# 扫描网格：相对当前值的倍数。1.0 是当前值，其余只用来圈定区间。
_GRID = (0.02, 0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 0.85, 1.0, 1.15, 1.3, 1.5, 2.0, 3.0, 5.0, 10.0)

# 整数型阈值（不能用小数扫描）
_INT_THRESHOLDS = {"timeout_burst_count", "comm_gap_allowed"}

# 取证代码里读取阈值的方式：th["x"] 或 th.get("x", 默认值)
_THRESH_USE_RE = re.compile(r'th\[\s*"(\w+)"\s*\]|th\.get\(\s*"(\w+)"\s*(?:,\s*([\d.]+))?\s*\)')


def _fmt_num(v: float) -> str:
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return f"{v:g}"


def _rel_gaps(cur: float, *flips) -> list[float]:
    """翻转点相对当前值的距离（比例）。翻转为 None 的忽略。"""
    out = []
    for f in flips:
        if not f:
            continue
        v = f[0]
        if cur:
            out.append(abs(v - cur) / abs(cur))
    return out


def _counts(lines, rules: dict, threshold: str, value, detectors: list[str]) -> int:
    """把某个阈值换成 value，重跑检测，返回相关检测器的总命中数。"""
    r2 = copy.deepcopy(rules)
    r2["thresholds"][threshold] = value
    total = 0
    for f in forensics.detect(lines, r2):
        if f.fid in detectors:
            total += f.count
    return total


def _refine(lines, rules: dict, name: str, detectors: list[str],
            cur: float, bound: float, base: int, upward: bool):
    """在 cur 与 bound 之间精确定位结论翻转点。

    网格只告诉我们「翻转发生在这一段里」，翻转点具体在哪要靠二分。
    没有这一步，粗网格会把「当前值离翻转点只有 5%」显示成「稳」。

    约定：
      下侧（upward=False）：bound < cur，命中数在 bound 处与当前值不同、cur 处相同
        → 翻转点 = 仍与当前值不同的**最大**取值（再往上就回到当前结论）
      上侧（upward=True）：bound > cur，同理
        → 翻转点 = 已与当前值不同的**最小**取值
    """
    if name in _INT_THRESHOLDS:
        lo, hi = int(cur), int(bound)
        if upward:
            for v in range(lo + 1, hi + 1):
                if _counts(lines, rules, name, v, detectors) != base:
                    return (v, _counts(lines, rules, name, v, detectors))
        else:
            for v in range(lo - 1, hi - 1, -1):
                if _counts(lines, rules, name, v, detectors) != base:
                    return (v, _counts(lines, rules, name, v, detectors))
        return None

    if upward:
        lo, hi = float(cur), float(bound)      # f(lo) == base, f(hi) != base
    else:
        lo, hi = float(bound), float(cur)      # f(lo) != base, f(hi) == base
    for _ in range(30):
        if abs(hi - lo) < 1e-12:
            break
        mid = (lo + hi) / 2.0
        if _counts(lines, rules, name, mid, detectors) == base:
            if upward:
                lo = mid
            else:
                hi = mid
        else:
            if upward:
                hi = mid
            else:
                lo = mid
    v = hi if upward else lo
    return (v, _counts(lines, rules, name, v, detectors))


def _scan_one(lines, rules: dict, name: str, detectors: list[str]) -> dict:
    cur = rules["thresholds"][name]
    base = _counts(lines, rules, name, cur, detectors)
    points: list[tuple[float, int]] = []
    for g in _GRID:
        v = cur * g
        if name in _INT_THRESHOLDS:
            v = int(round(v))
        if v < 0:
            v = 0
        if v == cur:
            continue
        points.append((v, _counts(lines, rules, name, v, detectors)))
    points.sort(key=lambda p: p[0])

    # 找最近的翻转（先用网格圈定区间，再二分精确定位）
    flip_low = flip_high = None
    for v, n in points:
        if v < cur and n != base and flip_low is None:
            flip_low = _refine(lines, rules, name, detectors, cur, v, base, upward=False)
    for v, n in sorted(points, key=lambda p: p[0], reverse=True):
        if v > cur and n != base and flip_high is None:
            flip_high = _refine(lines, rules, name, detectors, cur, v, base, upward=True)

    # 任何取值下命中数都 >0 的最小取值（误报侧边界）
    first_hit = None
    for v, n in sorted(points, key=lambda p: p[0]):
        if n > 0:
            first_hit = (v, n)
            break

    if flip_low is None and flip_high is None:
        sensitive = "无"
    elif flip_low is not None and flip_high is not None:
        sensitive = "双向"
    elif flip_low is not None:
        sensitive = "降低更敏感"
    else:
        sensitive = "升高更敏感"

    gaps = _rel_gaps(cur, flip_low, flip_high)
    nearest = min(gaps) if gaps else None
    if base == 0:
        verdict = "偏严" if first_hit is not None else "无数据"
    elif nearest is None:
        verdict = "稳健"
    elif nearest < 0.2:
        verdict = "脆"
    elif nearest < 0.5:
        verdict = "偏脆"
    else:
        verdict = "较稳"

    return {
        "name": name,
        "current": cur,
        "base": base,
        "detectors": detectors,
        "flip_low": flip_low,
        "flip_high": flip_high,
        "verdict": verdict,
        "sensitive": sensitive,
        "nearest": nearest,
        "points": points,
        "first_hit": first_hit,
    }


def _static_consistency(rules: dict) -> dict:
    """配置里的阈值与代码实际读取的阈值是否一致。

    死阈值：knowledge/log_rules.json 里配了，但取证代码根本不读 → 现场调它没有任何效果。
    硬编码兜底：代码用 th.get("x", 默认值) 读，但配置里没有 x → 想改只能改代码。
    """
    src = Path(forensics.__file__).read_text(encoding="utf-8")
    read_keys: set[str] = set()
    defaults: dict[str, str] = {}
    for m in _THRESH_USE_RE.finditer(src):
        if m.group(1):
            read_keys.add(m.group(1))
        else:
            read_keys.add(m.group(2))
            if m.group(3) is not None:
                defaults[m.group(2)] = m.group(3)
    config = set(rules.get("thresholds", {}))
    return {
        "dead": sorted(config - read_keys),
        "hardcoded": {k: v for k, v in sorted(defaults.items()) if k not in config},
        "read": sorted(read_keys),
    }


def analyze(path: Path, rules: dict | None = None, fmt: dict | None = None) -> dict[str, Any]:
    rules = rules or forensics._load_rules()
    fmt = fmt or forensics._load_format()
    lines, skipped = forensics.parse_log(path, fmt, rules)

    scans: list[dict] = []
    for name in rules.get("thresholds", {}):
        detectors = THRESHOLD_DETECTORS.get(name, [])
        if not detectors:
            continue
        scans.append(_scan_one(lines, rules, name, detectors))
    order = {"脆": 0, "偏脆": 1, "偏严": 2, "无数据": 3, "较稳": 4, "稳健": 5}
    scans.sort(key=lambda s: (order.get(s["verdict"], 9), -(s["nearest"] or 0)))

    meta = read_json(knowledge_path("detector_meta.json"))
    return {
        "file": str(path),
        "lines": len(lines),
        "skipped": skipped,
        "scans": scans,
        "consistency": _static_consistency(rules),
        "detector_meta": meta.get("detectors", {}),
        "detector_requires": rules.get("detector_requires", {}),
    }


def _flip_text(flip) -> str:
    if not flip:
        return "—（范围内不变）"
    v, n = flip
    return f"{_fmt_num(v)}（命中 {n}）"


def build_report(res: dict) -> Report:
    scans = res["scans"]
    cons = res["consistency"]
    meta = res["detector_meta"]
    req = res["detector_requires"]

    rep = Report(
        title="阈值灵敏度与误报边界报告",
        subtitle=f"日志：{Path(res['file']).name}　|　解析 {res['lines']} 行"
                 f"（未匹配 {res['skipped']} 行）　|　"
                 "口径：每条阈值单独扫 + 二分精确定位结论翻转点",
        meta={
            "扫描的阈值条数": len(scans),
            "脆 / 偏脆": sum(1 for s in scans if s["verdict"] in ("脆", "偏脆")),
            "偏严（当前值永不命中）": sum(1 for s in scans if s["verdict"] == "偏严"),
            "无数据（该类事件不存在）": sum(1 for s in scans if s["verdict"] == "无数据"),
            "配置与实现不一致": (len(cons["dead"]) + len(cons["hardcoded"])) or "无",
        },
    )

    rep.add("这张表解决什么问题", "\n".join([
        "`knowledge/log_rules.json` 里的阈值是**通用起点**，不是你们设备的真值。",
        "现场标定最怕的不是「阈值不准」，而是**「差一点点就翻车」**——阈值离结论翻转点太近，",
        "现场换一个批次、换一台机，结论就变了，而你以为是数据不同。",
        "",
        "所以这里扫的是：**每条阈值在什么取值上，检测结论会翻转**，并用二分法把翻转点**精确定位**",
        "（只做粗网格会漏掉「当前值离翻转点只有 5%」这种情况，看上去全稳，实际全是雷）。",
        "",
        "**离线能做的部分就在这张表里**（哪些脆、哪些偏严、哪些配置根本没生效）；"
        "**必须现场/真实数据的部分**是「阈值最终定在哪个数」——那需要你们的故障分布，本工具给不出来。",
    ]))

    rows = []
    for s in scans:
        cur = s["current"]
        rows.append([
            f"`{s['name']}`",
            _fmt_num(cur),
            s["base"],
            s["sensitive"],
            _flip_text(s["flip_low"]),
            _flip_text(s["flip_high"]),
            f"{s['nearest']:.0%}" if s["nearest"] is not None else "—",
            s["verdict"],
        ])
    rep.add("阈值灵敏度", "\n".join([
        md_table(["阈值", "当前值", "当前命中", "敏感方向", "下侧翻转点", "上侧翻转点", "最近翻转距离", "判定"], rows),
        "",
        callout("高", "**「偏严」= 当前阈值卡在数据分布之外，永远不会报**："
                      "它不是「没问题」的证据，是「这条检测在这份数据上是哑的」。"
                      "现场遇到「工具不报」时先看这里。"),
    ]))

    if cons["dead"] or cons["hardcoded"]:
        items = []
        for k in cons["dead"]:
            items.append(f"- **死阈值**：`{k}` —— `knowledge/log_rules.json` 里配了，"
                         f"但取证代码**根本没读它**。现场调它不会有任何效果（改配置像是改了，其实没改）。")
        for k, v in cons["hardcoded"].items():
            items.append(f"- **硬编码兜底**：`{k}` —— 代码用 `th.get(\"{k}\", {v})` 读，"
                         f"但配置里**没有这一项**，所以生效的是代码里的默认值 {v}。"
                         f"要标定它只能改代码。")
        rep.add("配置与实现不一致（这两条不修，现场调阈值是白调）", "\n".join(items))
    else:
        rep.add("配置与实现一致", "所有配置的阈值都被取证代码实际读取，没有死阈值，也没有硬编码兜底。")

    # 误报侧边界：按检测器聚合（一个检测器可能有多条阈值，取最紧的那条）
    #   flip_low = 阈值再往下降就**开始多报**（误报侧）
    #   flip_high = 阈值再往上升就**开始漏报**（漏报侧）
    rows2 = []
    for det, m in meta.items():
        src = m.get("false_positive_sources", [])
        guard = m.get("builtin_guard", "—")
        related = [s for s in scans if det in s["detectors"]]
        tight = None      # 最紧的误报侧边界
        loose = None      # 最松的漏报侧边界
        for s in related:
            if s["flip_low"] and (tight is None or s["flip_low"][0] < tight[0]):
                tight = (s["flip_low"][0], s["name"])
            if s["flip_high"] and (loose is None or s["flip_high"][0] > loose[0]):
                loose = (s["flip_high"][0], s["name"])
        rows2.append([
            f"`{det}`",
            "、".join(req.get(det, m.get("events", []))) or "—",
            "；".join(src) if src else "—",
            guard,
            f"{_fmt_num(tight[0])}（`{tight[1]}`）" if tight else "降低不增加命中",
            f"{_fmt_num(loose[0])}（`{loose[1]}`）" if loose else "升高不减少命中",
            m.get("how_to_verify", "—"),
        ])
    rep.add("检测器误报边界表", "\n".join([
        md_table(["检测器", "依赖事件", "什么输入会误报", "工具内置的防护",
                  "误报侧边界（低于此值开始多报）", "漏报侧边界（高于此值开始漏报）", "怎么人工复核"], rows2),
        "",
        callout("提示", "**误报侧边界**是现场标定时**不能低于**的那个数 —— 再低正常波动也会被算成故障。"
                         "**漏报侧边界**是**不能高于**的那个数 —— 再高真实问题就检不出来了。"
                         "两个边界之间的区间，就是这条检测器在你们产线上的可用标定范围。"),
    ]))

    fragile = [s for s in scans if s["verdict"] in ("脆", "偏脆")]
    strict = [s for s in scans if s["verdict"] == "偏严"]
    nodata = [s for s in scans if s["verdict"] == "无数据"]
    todo = []
    for s in fragile[:3]:
        todo.append(f"`{s['name']}`（当前 {_fmt_num(s['current'])}，"
                    f"翻转点 {_flip_text(s['flip_low'] or s['flip_high'])}，"
                    f"距 {s['nearest']:.0%}）")
    rep.add("下一步怎么标定（按这个顺序）", "\n".join([
        "1. **先修配置与实现不一致**（死阈值/硬编码兜底）—— 不修的话，现场调这些阈值是白调。",
        "2. **再标定脆阈值**，优先顺序：" + ("、".join(todo) if todo else "本次扫描没发现脆阈值"),
        "3. **处理偏严阈值**（当前值永不命中）——"
        + ("、".join(f"`{s['name']}`" for s in strict) if strict else "无")
        + "。这些不是「没问题」，是「检测器在这份数据上是哑的」，先确认是缺埋点还是阈值卡太死。",
        "4. **最后才动稳健阈值** —— 它们离翻转点远，标定容差大。",
        "5. 每标定一条，重跑本报告确认「判定」变化符合预期。",
        "",
        "**标定要用什么数据**：一段**已知原因**的故障日志（要能检出）+ 一段**正常**日志（要零误报）。"
        "只拿正常日志标不出阈值 —— 阈值越松越「安全」，但那样就没人需要这个工具了。",
        "",
        (f"⚠ 本次有 {len(nodata)} 条阈值**在这份日志里无数据**（"
         + "、".join(f"`{s['name']}`" for s in nodata)
         + "）：该类事件在日志里根本不存在，通常是**缺埋点**，不是「没问题」。") if nodata else "",
    ]))

    return rep


def run(path: Path, out_dir: Path | None = None, stem: str | None = None) -> dict[str, Any]:
    res = analyze(path)
    rep = build_report(res)
    stem = stem or f"threshold_{path.stem}"
    written: dict[str, Path] = {}
    if out_dir is not None:
        written = rep.write(out_dir, stem)
    return {"report": rep, "analysis": res, "written": written}
