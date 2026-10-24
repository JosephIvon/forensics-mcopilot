"""SPC 与良率分析智能体（spc）：把「良率波动」从会议室里靠感觉讨论，
变成一条控制图 + 一张 Pareto + 一组相关性 + 一次变点检测。

覆盖需求基线的 R-08（SPC 统计、设备稼动率、生产报表）与 R-07/R-05（良率优化），
也直接支撑 R-09 的「良率波动」根因分析。

口径统一是这里最大的价值：同一个指标，产线、研发、工艺各算各的，
数字对不上就没法讨论。工具先定死口径，剩下才是统计。
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from ..core import chart
from ..core.report import Report, callout
from ..core.util import (capability_indices, cusum, fmt, mean, moving_range,
                         percentile, point_biserial, stdev, write_json)


@dataclass
class Dataset:
    rows: list[dict]
    numeric_cols: list[str]
    result_col: str | None
    ng_col: str | None
    # 每列被丢弃的行数（非数值 / 缺列）。**不记这个数，统计口径就成了假的**：
    # 报告里写「样本 N 条」，控制图却画在 N-k 点上，而没人知道 k>0。
    dropped: dict[str, int] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.rows)

    def col(self, name: str) -> list[float]:
        """取一列的数值。

        非数值 / 缺列的行**被排除**（不是 0，不是原值）——排除数记进 `dropped`，
        报告必须把「行数」和「参与统计的点数」两个口径分开写。
        """
        out = []
        miss = 0
        for r in self.rows:
            try:
                out.append(float(r[name]))
            except (KeyError, ValueError, TypeError):
                miss += 1
        self.dropped[name] = miss
        return out

    def group(self, name: str) -> list[tuple[str, list[dict]]]:
        buckets: dict[str, list[dict]] = {}
        for r in self.rows:
            buckets.setdefault(str(r.get(name, "")), []).append(r)
        return sorted(buckets.items(), key=lambda kv: kv[0])


def load_csv(path: Path, result_col: str | None = None, ng_col: str | None = None) -> Dataset:
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = [dict(r) for r in reader]
    if not rows:
        raise SystemExit("CSV 为空")
    fields = list(rows[0].keys())

    def is_num(v: Any) -> bool:
        try:
            float(v)
            return True
        except (TypeError, ValueError):
            return False

    numeric_cols = [c for c in fields if c and is_num(rows[0].get(c))]

    if result_col is None:
        for cand in ("result", "Result", "RESULT", "judge", "judgement", "结果"):
            if cand in fields:
                result_col = cand
                break
    if ng_col is None:
        for cand in ("ng_code", "ngcode", "NG_CODE", "defect", "缺陷"):
            if cand in fields:
                ng_col = cand
                break
    return Dataset(rows=rows, numeric_cols=numeric_cols, result_col=result_col, ng_col=ng_col)


# ------------------------------------------------------------------ 统计


def i_mr(values: Sequence[float]) -> dict:
    """个体值-移动极差控制图。sigma 由 MR_bar/1.128 估计。"""
    if len(values) < 3:
        return {"ok": False, "reason": "样本不足（<3）"}
    mr = moving_range(values)
    mr_bar = mean(mr)
    sigma = mr_bar / 1.128 if mr_bar > 0 else stdev(values)
    cl = mean(values)
    ucl = cl + 3.0 * sigma
    lcl = cl - 3.0 * sigma
    ooc = [(i + 1, v) for i, v in enumerate(values) if v > ucl or v < lcl]
    # 判异规则：**连续 9 点同侧** / **连续 6 点递增或递减**
    # （注释原先写「7 点」，实现是 9/6——按注释调机的现场工程师会按 7 点排查。）
    side = _run_rules(values, cl, ucl, lcl)
    return {
        "ok": True,
        "cl": cl, "ucl": ucl, "lcl": lcl, "sigma": sigma,
        "mr": mr, "mr_bar": mr_bar, "mr_ucl": 3.267 * mr_bar,
        "ooc": ooc, "ooc_count": len(ooc),
        "runs": side,
        "cp": capability_indices(ucl, lcl, cl, sigma),
    }


def _run_rules(values: Sequence[float], cl: float, ucl: float, lcl: float) -> list[dict]:
    runs: list[dict] = []
    n = len(values)
    # 连续 9 点同侧
    side = 0
    start = 0
    for i in range(n):
        s = 1 if values[i] > cl else (-1 if values[i] < cl else 0)
        if s == 0:
            side = 0
            start = i + 1
            continue
        if side == 0 or s != side:
            side, start = s, i
        else:
            side = s
        if i - start + 1 == 9:
            runs.append({"rule": "连续 9 点在中心线同侧", "index": i + 1})
    # 连续 6 点递增/递减
    for i in range(5, n):
        window = values[i - 5: i + 1]
        if all(window[k + 1] > window[k] for k in range(5)):
            runs.append({"rule": "连续 6 点递增", "index": i + 1})
        elif all(window[k + 1] < window[k] for k in range(5)):
            runs.append({"rule": "连续 6 点递减", "index": i + 1})
    return runs


def pareto(items: Sequence[tuple[str, int]]) -> list[dict]:
    total = sum(v for _, v in items) or 1
    out = []
    cum = 0
    for name, v in sorted(items, key=lambda kv: -kv[1]):
        cum += v
        out.append({"name": name, "count": v, "pct": v / total * 100.0, "cum_pct": cum / total * 100.0})
    return out


def yield_by_group(ds: Dataset, group_col: str) -> list[dict]:
    out = []
    for name, rows in ds.group(group_col):
        if ds.result_col:
            ng = sum(1 for r in rows if str(r.get(ds.result_col, "")).upper() in ("NG", "FAIL", "0", "BAD"))
        else:
            ng = 0
        total = len(rows)
        out.append({"group": name, "total": total, "ng": ng, "ok": total - ng,
                    "yield_pct": (total - ng) / total * 100.0 if total else float("nan")})
    return out


# ------------------------------------------------------------------ 报告


def build_report(ds: Dataset, metric: str, usl: float | None, lsl: float | None,
                 group_col: str, out_dir: Path | None, stem: str) -> Report:
    rep = Report(title="SPC 与良率分析报告",
                 subtitle=f"样本 {ds.n} 条　|　控制指标：{metric}　|　分组：{group_col}")

    values = ds.col(metric)
    if not values:
        raise SystemExit(f"指标列 '{metric}' 不存在或非数值。可选数值列：{ds.numeric_cols}")
    # 口径：行数 ≠ 参与统计的点数。差额必须写出来，否则"样本 N 条"与控制图点数对不上，
    # 而看报告的人不会去数点。
    dropped = ds.dropped.get(metric, 0)
    used = len(values)
    scope_line = (
        f"- 指标 {metric}：**参与统计 {used} 点**（样本 {ds.n} 条，"
        f"其中 {dropped} 条该列非数值或缺列已排除）"
        if dropped else
        f"- 指标 {metric}：**参与统计 {used} 点**（样本 {ds.n} 条，无排除）"
    )

    im = i_mr(values)
    images = []
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        p1 = chart.save_control_chart(out_dir / f"{stem}_I.png", values, im["cl"], im["ucl"], im["lcl"],
                                      f"{metric} 个体值控制图 (I)")
        if p1:
            images.append(p1)
        p2 = chart.save_mr_chart(out_dir / f"{stem}_MR.png", im["mr"], im["mr_bar"], im["mr_ucl"],
                                 f"{metric} 移动极差图 (MR)")
        if p2:
            images.append(p2)

    # 概览
    ng_count = 0
    if ds.result_col:
        ng_count = sum(1 for r in ds.rows if str(r.get(ds.result_col, "")).upper() in ("NG", "FAIL", "0", "BAD"))
    overall = (ds.n - ng_count) / ds.n * 100.0 if ds.n else float("nan")
    rep.add("数据概览", "\n".join([
        f"- 样本数：**{ds.n}**",
        f"- 良率：**{overall:.2f}%**（不良 {ng_count} 条）" if ds.result_col else "- 结果列未指定，跳过良率统计",
        scope_line,
        f"- {metric} 统计量：均值 {fmt(mean(values))}，标准差 {fmt(stdev(values))}，"
        f"最小 {fmt(min(values))}，最大 {fmt(max(values))}，"
        f"P95 {fmt(percentile(values, 0.95))}",
        "",
        (callout("高", f"**{metric} 控制图检出 {im['ooc_count']} 个超限点"
                       f"{'，另有 ' + str(len(im['runs'])) + ' 处判异规则命中' if im['runs'] else ''}。**")
         if im["ooc_count"] or im["runs"] else
         callout("低", f"**{metric} 控制图未检出异常点。**")),
    ]))

    # 控制图分析
    if im["ok"]:
        cap = im["cp"]
        rep.add(f"控制图分析：{metric}", "\n".join([
            "| 项 | 数值 |", "|---|---|",
            f"| 中心线 CL | {fmt(im['cl'])} |",
            f"| 上控制限 UCL | {fmt(im['ucl'])} |",
            f"| 下控制限 LCL | {fmt(im['lcl'])} |",
            f"| 估计标准差 σ (MR̄/1.128) | {fmt(im['sigma'])} |",
            f"| 移动极差均值 MR̄ | {fmt(im['mr_bar'])} |",
            f"| MR 图控制限 (D4=3.267) | {fmt(im['mr_ucl'])} |",
            f"| 过程能力 Cp | {fmt(cap['cp'])} |",
            f"| 过程能力 Cpk | {fmt(cap['cpk'])} |",
            f"| 能力判定 | {cap['verdict']} |",
            "",
            (("**超限点（行号 = 样本序号）**：" + "、".join(f"#{i}({fmt(v)})" for i, v in im["ooc"][:12]))
             if im["ooc"] else "**超限点**：无"),
            (("**判异规则命中**：" + "；".join(f"#{r['index']} {r['rule']}" for r in im["runs"][:8]))
             if im["runs"] else ""),
            "",
            (callout("中", "Cp/Cpk 是基于**控制限**算的能力指数，反映当前过程自身的稳定性；"
                           "若同时存在工程规格（USL/LSL），应优先用工程规格算能力，"
                           "两者差距大说明过程没对准规格中心。")
             if usl is None or lsl is None else
             f"工程规格：USL={usl}，LSL={lsl}。"),
        ]))

    # 良率 Pareto
    if ds.ng_col:
        items = [(str(r.get(ds.ng_col, "") or "未标注"), 1) for r in ds.rows
                 if str(r.get(ds.result_col or "", "")).upper() in ("NG", "FAIL", "0", "BAD")]
        agg: dict[str, int] = {}
        for name, _ in items:
            agg[name] = agg.get(name, 0) + 1
        pr = pareto(list(agg.items()))
        if pr:
            if out_dir:
                p3 = chart.save_bar_chart(out_dir / f"{stem}_pareto.png",
                                          [p["name"] for p in pr], [p["count"] for p in pr],
                                          "不良 Pareto", "件数", "#d64545", horizontal=True)
                if p3:
                    images.append(p3)
            rep.add("不良 Pareto", "\n".join([
                "| 缺陷代码 | 件数 | 占比 | 累计占比 |", "|---|---|---|---|",
                *[f"| {p['name']} | {p['count']} | {p['pct']:.1f}% | {p['cum_pct']:.1f}% |" for p in pr],
                "",
                callout("中", f"**前 {max(1, next((i + 1 for i, p in enumerate(pr) if p['cum_pct'] >= 80), len(pr)))} "
                              f"类缺陷占了 80% 的不良** —— 按 80/20 原则，这几类是优先攻克对象。"),
            ]))

    # 良率趋势 + 变点
    if group_col and group_col in ds.rows[0]:
        gy = yield_by_group(ds, group_col)
        low = [g for g in gy if g["yield_pct"] < min(x["yield_pct"] for x in gy) + 5]
        if out_dir:
            p4 = chart.save_trend_chart(out_dir / f"{stem}_yield.png", [g["group"] for g in gy],
                                        [g["yield_pct"] for g in gy], f"良率趋势（按 {group_col}）", "良率 %")
            if p4:
                images.append(p4)
        marks = cusum([g["yield_pct"] for g in gy], threshold=1.0)
        shifts = [m for m in marks if m["shift"]]
        shift_marks = [f"#{i + 1} {gy[i]['group']}"
                       for i, m in enumerate(marks) if m["shift"]][:6]
        rep.add(f"良率趋势（按 {group_col}）", "\n".join([
            f"共 {len(gy)} 组，良率区间 {fmt(min(g['yield_pct'] for g in gy), 2)}% ~ "
            f"{fmt(max(g['yield_pct'] for g in gy), 2)}%。",
            "",
            "| 分组 | 样本 | 不良 | 良率 |", "|---|---|---|---|",
            *[f"| {g['group']} | {g['total']} | {g['ng']} | {g['yield_pct']:.2f}% |" for g in gy[:40]],
            "",
            (callout("高", f"**CUSUM 变点检测在 {len(shifts)} 个分组处检出均值漂移"
                           f"（{'、'.join(shift_marks)}）** —— "
                           "变点往往对应一次换型、换料、换班或设备状态变化，是排查的切入口。")
             if shifts else
             callout("低", "CUSUM 未检出明显变点，良率波动在统计上可视为随机。")),
        ]))

        # 相关性：数值参数 vs 不良
        if ds.result_col and ds.numeric_cols:
            binary = [1 if str(r.get(ds.result_col, "")).upper() in ("NG", "FAIL", "0", "BAD") else 0
                      for r in ds.rows]
            corr = []
            skipped: list[tuple[str, str]] = []      # 被排除的参数与原因（不写出来就等于没查过）
            for c in ds.numeric_cols:
                vals = []
                miss = 0
                for r, b in zip(ds.rows, binary):
                    try:
                        vals.append((float(r[c]), b))
                    except (KeyError, ValueError, TypeError):
                        miss += 1
                if miss:
                    skipped.append((c, f"{miss} 条该列非数值或缺列，已排除"))
                if len(vals) < 10:
                    skipped.append((c, f"可配对样本仅 {len(vals)} 条（<10），样本量不足"))
                    continue
                xs = [v for v, _ in vals]
                bs = [float(b) for _, b in vals]
                if len(set(bs)) < 2:
                    skipped.append((c, "良/不良在该列上没有差异，相关性无从算起"))
                    continue
                r_pb = point_biserial(bs, xs)
                if math.isnan(r_pb):
                    skipped.append((c, "相关系数算不出来（分母为 0）"))
                    continue
                corr.append((c, r_pb, len(vals)))
            corr.sort(key=lambda e: -abs(e[1]))
            if corr:
                rep.add("参数与不良的相关性（点二列相关）", "\n".join([
                    "| 参数 | 相关系数 r | 样本 | 解读 |", "|---|---|---|---|",
                    *[
                        f"| {c} | {r:+.3f} | {n} | "
                        f"{'不良件该参数显著偏高' if r > 0.15 else ('不良件该参数显著偏低' if r < -0.15 else '无明显关联')}"
                        + ("　⚠ **强相关，优先查**" if abs(r) > 0.3 else "")
                        for c, r, n in corr
                    ],
                    "",
                    callout("中", "**注意：相关不等于因果。** 强相关项应结合工艺机理与分组对比再下结论；"
                                   "但它能告诉你「先去查哪几个参数」，这已经省掉大部分盲目试参数的时间。"),
                ]))
            if skipped:
                rep.add("未纳入相关分析的参数", "\n".join([
                    "下列参数**没有**出相关性结论——原因逐条列出，免得被当成「查过没问题」：",
                    "",
                    *[f"- **{c}**：{why}" for c, why in skipped],
                ]))

    rep.images = images
    return rep


def run(csv_path: Path, metric: str, usl: float | None, lsl: float | None,
        group_col: str, out_dir: Path, result_col: str | None = None,
        ng_col: str | None = None, stem: str | None = None) -> dict[str, Any]:
    ds = load_csv(csv_path, result_col, ng_col)
    stem = stem or f"spc_{csv_path.stem}"
    rep = build_report(ds, metric, usl, lsl, group_col, out_dir, stem)
    return {"report": rep, "dataset": ds}
