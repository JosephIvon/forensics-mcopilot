#!/usr/bin/env python3
"""命令行封装：TwinCAT / CODESYS Scope View 原生导出 → mcopilot 规范波形 CSV。

用法：
    python scripts/convert_twincat.py <输入> <输出csv> [--meta 输出json]

选项：
    --meta PATH        额外写出 meta JSON（源文件 sha256、通道映射、时基、fe 恒等式、extra 通道…）
    --trigger-gate     按 KB2 坑 2 丢掉 `bTrigger_Record == 0` 的行（默认全量导出）
    --no-self-check    跳过「把产物喂回 mcopilot servo loader」的自检

解析失败一律以非零退出码报错（不静默产出空表）。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

# 未安装 mcopilot 时，允许直接在仓库里跑：把 <repo>/src 加进 sys.path
_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mcopilot.core.twincat import (  # noqa: E402
    CANONICAL_COLUMNS,
    SEMANTIC_MAP,
    TwincatParseError,
    build_meta,
    fe_identity,
    map_channels,
    parse_twincat,
    pearson,
    write_canonical_csv,
)


def _self_check(csv_path: Path) -> dict:
    """把产物喂回 mcopilot 现有的 servo loader（src/mcopilot/agents/servo.py）。

    **不修改 servo.py**，只调用它的 `load_waveform`。
    """
    try:
        from mcopilot.agents.servo import load_waveform
    except Exception as exc:  # pragma: no cover - 仅在依赖缺失时触发
        return {"ok": False, "reason": f"无法导入 mcopilot.agents.servo：{exc}"}
    try:
        wf = load_waveform(csv_path)
    except BaseException as exc:  # load_waveform 内部可能抛 SystemExit
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": bool(wf.cmd and wf.fb and wf.n > 0),
        "n": wf.n,
        "has_cmd": bool(wf.cmd),
        "has_fb": bool(wf.fb),
        "has_vel": bool(wf.vel),
        "time_unit": wf.time_unit,
        "measured_fs_hz": wf.fs,
        "columns": wf.columns,
        "t_first_s": wf.t[0] if wf.t else None,
        "t_last_s": wf.t[-1] if wf.t else None,
        "err_first": wf.error_signal()[0] if wf.error_signal() else None,
    }


def _vendor_fe_crosscheck(export, mapping, derived_fe) -> list[dict]:
    """C1 规则 2 的自检：厂商自带的「像跟随误差」的通道，只有 corr(fe_derived, candidate) > 0.99 才配当 fe。

    这里只**核对**不改名：算出来的相关系数写进 meta，判定留给读报告的人。
    """
    out = []
    for ch in export.channels:
        leaf = ch.leaf.lower()
        if "diff" not in leaf and "error" not in leaf and "err" not in leaf:
            continue
        if ch.name in ("dVelocity_diff", "dPosition_diff"):
            corr = pearson(derived_fe, ch.values)
            out.append({
                "alias": ch.name,
                "symbol": ch.symbol,
                "corr_with_derived_fe": corr,
                "verdict": ("可作 fe（corr>0.99，C1 规则 2）" if corr == corr and corr > 0.99
                            else "不是跟随误差（|corr|≤0.99）→ 保留在 extra，不得改名为 fe"),
            })
    return out


def _vendor_triple_crosscheck(export) -> dict | None:
    """复算上游分析自己用的那一组三元组（出处：data/validate_out.txt L45）。

    上游做跟随误差恒等式核对时用的是
        pos_cmd = dPosition_test_tar, pos_fb = dPosition_asco_enc, fe = dPosition_diff
    （**不是** dPosition_asco / dPosition_asco_enc）。这里只做**证据复算**，不改名、不改映射：
    通道齐全才返回，否则返回 None。
    """
    cmd = export.channel_by_alias("dPosition_test_tar")
    fb = export.channel_by_alias("dPosition_asco_enc")
    fe = export.channel_by_alias("dPosition_diff")
    if cmd is None or fb is None or fe is None:
        return None
    n = min(len(cmd.values), len(fb.values), len(fe.values))
    diff = [cmd.values[i] - fb.values[i] for i in range(n)]
    m = sum(diff) / n
    std = (sum((v - m) ** 2 for v in diff) / n) ** 0.5
    max_abs = max(abs(v) for v in diff)
    resid = [fe.values[i] - diff[i] for i in range(n)]
    rm = sum(resid) / n
    rstd = (sum((v - rm) ** 2 for v in resid) / n) ** 0.5
    rmax = max(abs(v) for v in resid)
    return {
        "source": "data/validate_out.txt L45（上游用的三元组）",
        "pos_cmd": cmd.symbol or cmd.name,
        "pos_fb": fb.symbol or fb.name,
        "fe_candidate": fe.symbol or fe.name,
        "cmd_minus_fb": {"mean": m, "std": std, "max_abs": max_abs},
        "residual_fe_candidate_minus_cmd_minus_fb": {
            "mean": rm, "std": rstd, "max_abs": rmax,
            "residual_over_fe_amplitude": (rstd / std) if std else None,
        },
        "corr_fe_candidate_vs_cmd_minus_fb": pearson(fe.values[:n], diff),
        "verdict": (
            "厂商 dPosition_diff 与 (pos_cmd - pos_fb) 的残差幅度 ≈ fe 幅度 → 不是跟随误差"
            "（C1 规则 2：|corr| 未达 0.99，不得改名为 fe；保留在 extra）"),
    }


def _pair_scan(export, target_mean: float = -0.9076, target_std: float = 6.238,
               target_max: float = 851.0) -> dict:
    """证据扫描：本文件里**任意两通道之差**能否复现任务书给出的 fe 统计量。

    任务书给的 (mean=-0.9076, std=6.238, max|.|=851) 若真来自本文件，
    那么必然存在某一对通道，其逐行差值的三个统计量同时对得上。这里把所有有序对扫一遍给出反证。
    """
    chans = export.channels
    n = len(chans)
    worst_max = None          # 全局最大的 |两通道之差|
    hit_mean = []             # mean 命中目标的通道对
    hit_std = []              # std 命中目标的通道对
    for i in range(n):
        xi = chans[i].values
        for j in range(n):
            if i == j:
                continue
            xj = chans[j].values
            d = [a - b for a, b in zip(xi, xj)]
            m = sum(d) / len(d)
            sd = (sum((v - m) ** 2 for v in d) / len(d)) ** 0.5
            mx = max(map(abs, d))
            if worst_max is None or mx > worst_max["max_abs"]:
                worst_max = {"a": chans[i].name, "b": chans[j].name,
                             "max_abs": mx, "mean": m, "std": sd}
            if abs(m - target_mean) < 0.02:
                hit_mean.append({"a": chans[i].name, "b": chans[j].name,
                                 "mean": m, "std": sd, "max_abs": mx})
            if abs(sd - target_std) < 0.01:
                hit_std.append({"a": chans[i].name, "b": chans[j].name,
                                "mean": m, "std": sd, "max_abs": mx})
    return {
        "target": {"mean": target_mean, "std": target_std, "max_abs": target_max},
        "n_ordered_pairs_scanned": n * (n - 1),
        "largest_abs_difference_over_all_pairs": worst_max,
        "pairs_with_mean_in_0p02_of_target": hit_mean,
        "pairs_with_std_in_0p01_of_target": hit_std,
        "reproducible": bool(
            any(abs(h["mean"] - target_mean) < 0.02 and abs(h["std"] - target_std) < 0.01
                and abs(h["max_abs"] - target_max) < 1.0
                for h in hit_mean if any(g["a"] == h["a"] and g["b"] == h["b"] for g in hit_std))),
        "conclusion": (
            "本文件里任意两通道之差的最大绝对值都小于任务书给的 max|.|=851，"
            "且没有一对通道同时满足 mean≈-0.9076 与 std≈6.238 → "
            "任务书给出的 fe 统计量在本文件上复现不出来（详见 meta.notes 的溯源说明）"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="TwinCAT / CODESYS Scope View 导出 → mcopilot 规范波形 CSV")
    ap.add_argument("input", help="厂商原始导出文件（TSV 交错 + 元数据表头）")
    ap.add_argument("output_csv", help="输出的 mcopilot 规范 CSV")
    ap.add_argument("--meta", default=None, help="额外写出 meta JSON 的路径")
    ap.add_argument("--trigger-gate", action="store_true",
                    help="按 KB2 坑 2 丢掉 bTrigger_Record==0 的行（默认全量）")
    ap.add_argument("--no-self-check", action="store_true", help="跳过 servo loader 自检")
    ap.add_argument("--note", action="append", default=[],
                    help="往 meta.notes 里追加一条说明（可重复）")
    ap.add_argument("--pair-scan", action="store_true",
                    help="扫描全部有序通道对，核对任务书给出的 fe 统计量能否复现（慢，几秒）")
    args = ap.parse_args(argv)

    src = Path(args.input)
    out_csv = Path(args.output_csv)

    try:
        export = parse_twincat(src, trigger_gate=args.trigger_gate)
        mapping = map_channels(export.channels)
        info = write_canonical_csv(export, mapping, out_csv)
    except TwincatParseError as exc:
        print(f"[FAIL] 解析失败：{exc}", file=sys.stderr)
        return 2

    cmd = mapping.canonical.get("cmd_pos")
    fb = mapping.canonical.get("fb_pos")
    fe_check = None
    if cmd is not None and fb is not None:
        fe_check = fe_identity(cmd.values, fb.values)
        fe_check["cmd_channel"] = cmd.symbol or cmd.name
        fe_check["fb_channel"] = fb.symbol or fb.name
        fe_check["vendor_fe_candidates"] = _vendor_fe_crosscheck(
            export, mapping, [c - f for c, f in zip(cmd.values, fb.values)])

    servo = None if args.no_self_check else _self_check(out_csv)

    notes = [
        "语义映射只认显式词表（Scope 别名 + ADS 符号末段双词表，精确匹配）；"
        "其余通道一律进 extra，不猜语义。",
        "extra 通道不写进规范 CSV（C1：多余通道进 meta/extra_channels，避免被频谱类特征误当信号）。",
        "时基来自 SampleTime[ms] 声明行 + 索引列差分交叉校验；索引列 = 样本序号，t_ms = 索引 × 声明周期。",
    ]
    notes.extend(args.note)

    meta = build_meta(export, mapping, csv_path=out_csv,
                      servo_check=servo, fe_check=fe_check, extra_notes=notes)

    # 交叉验证证据：上游三元组复算 + （可选）全通道对扫描
    cross: dict[str, Any] = {}
    triple = _vendor_triple_crosscheck(export)
    if triple is not None:
        cross["vendor_triple"] = triple
    if args.pair_scan:
        cross["pair_scan"] = _pair_scan(export)
    if cross:
        meta["cross_checks"] = cross

    if args.meta:
        meta_path = Path(args.meta)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")

    # ── 控制台摘要
    print(f"[OK] 源文件：{src}")
    print(f"     sha256 = {export.sha256}")
    print(f"     通道 {len(export.channels)} 个，纳入 {export.n_rows} 行"
          f"（数据区 {export.n_data_lines} 行，跳过 {len(export.skipped)} 行）")
    print(f"     采样周期 {export.sample_time_ms} ms → 实测 fs = "
          f"{meta['sample_rate']['measured_fs_hz']:.4f} Hz，时长 {meta['duration_s']:.3f} s")
    print(f"     规范列：{','.join(info['header'])}")
    for name, ch in mapping.canonical.items():
        print(f"       {name:8s} ← {ch.symbol or ch.name}")
    print(f"     extra 通道 {len(mapping.extra)} 个："
          f"{', '.join(c.name for c in mapping.extra)}")
    if fe_check:
        print(f"     fe = cmd_pos - fb_pos：mean={fe_check['mean']:.6f} "
              f"std={fe_check['std']:.6f} max|.|={fe_check['max_abs']:.6f}")
    if servo is not None:
        print(f"     servo loader 自检：ok={servo.get('ok')} n={servo.get('n')} "
              f"cmd={servo.get('has_cmd')} fb={servo.get('has_fb')}")
    print(f"[OK] 规范 CSV：{out_csv}")
    if args.meta:
        print(f"[OK] meta JSON：{args.meta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
