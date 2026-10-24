#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""独立复算交叉验证报告里的数据结论 —— 不用 mcopilot 的任何函数。

为什么要这个脚本
----------------
`docs/交叉验证_Export10.md` 是对 servo 分支的交叉验证报告，`docs/交叉验证_Export10_数据复算.md`
是对那份报告的独立复算与更正。两者都声称一些具体数值。

**审的对象不能用被审的代码去验** —— 拿 `mcopilot.agents.servo` 复算 servo 的结论，
就是 axiscope 审计里说的"同源自证"。所以本脚本只读 CSV、只用标准库重算。

用法
----
    python scripts/verify_crossval_claims.py
    python scripts/verify_crossval_claims.py --csv samples/servo/twincat_export10.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_CSV = os.path.join(ROOT, "samples", "servo", "twincat_export10.csv")

# 频谱分析参数
NFFT = 2048
BAND_LO, BAND_HI = 12.0, 120.0        # servo_rules.json 的怀疑频带（Hz）


def load(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    t = [float(r["time_ms"]) / 1000.0 for r in rows]
    cmd = [float(r["cmd_pos"]) for r in rows]
    fb = [float(r["fb_pos"]) for r in rows]
    return t, cmd, fb


def dft(x, off, nfft=NFFT, fs=1000.0):
    """返回 (单边幅值数组, 频率数组, 总功率)。"""
    seg = x[off:off + nfft]
    n = len(seg)
    m = sum(seg) / n
    seg = [v - m for v in seg]
    amp = [0.0] * (n // 2 + 1)
    power = 0.0
    for k in range(1, n // 2 + 1):
        re = im = 0.0
        for i, v in enumerate(seg):
            ang = 2 * math.pi * k * i / n
            re += v * math.cos(ang)
            im -= v * math.sin(ang)
        a = 2.0 * math.hypot(re, im) / n
        amp[k] = a
        power += a * a
    freq = [k * fs / n for k in range(n // 2 + 1)]
    return amp, freq, power, n


def band_ratio(x, off, lo=BAND_LO, hi=BAND_HI, fs=1000.0):
    amp, freq, power, n = dft(x, off, fs=fs)
    band = sum(amp[k] ** 2 for k in range(1, len(amp)) if lo <= freq[k] <= hi)
    peaks = sorted(((amp[k], freq[k]) for k in range(1, len(amp)) if lo <= freq[k] <= hi),
                   reverse=True)
    return (band / power if power else 0.0), peaks, freq


def main(argv=None):
    ap = argparse.ArgumentParser(description="独立复算交叉验证报告的数据结论")
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--fs", type=float, default=1000.0)
    args = ap.parse_args(argv)

    if not os.path.isfile(args.csv):
        print("找不到 CSV: %s" % args.csv, file=sys.stderr)
        return 2
    t, cmd, fb = load(args.csv)
    n = len(t)
    fs = (n - 1) / (t[-1] - t[0]) if n > 1 else args.fs
    err = [c - f for c, f in zip(cmd, fb)]

    print("=" * 72)
    print("交叉验证数据独立复算 —— %s" % os.path.basename(args.csv))
    print("=" * 72)
    print("样本数 n = %d   时长 = %.3f s   实测 fs = %.3f Hz   Nyquist = %.1f Hz"
          % (n, t[-1], fs, fs / 2))

    # ---- 跟随误差的常数偏置分解
    mean = sum(err) / n
    sd = math.sqrt(sum((e - mean) ** 2 for e in err) / n)
    peak = max(abs(e) for e in err)
    print("\n[F-03] 跟随误差 cmd-fb: mean=%+.6f  std=%.6f  max|e|=%.6f"
          % (mean, sd, peak))
    print("       动态/总量比 std/peak = %.6f  → 误差的 %.2f%% 是常数偏置"
          % (sd / peak, mean / peak * 100))
    print("       去偏置后动态峰 = %.6f" % max(abs(e - mean) for e in err))

    # ---- 指令刷新率（跳变间隔中位数）
    jumps = [i for i in range(1, n) if abs(cmd[i] - cmd[i - 1]) > 1e-9]
    if len(jumps) > 1:
        iv = sorted(t[jumps[i]] - t[jumps[i - 1]] for i in range(1, len(jumps)))
        med = iv[len(iv) // 2]
        big = max(jumps, key=lambda i: abs(cmd[i] - cmd[i - 1]))
        print("\n[F-05] 指令跳变 %d 次；跳变间隔中位数 = %.1f ms → 指令刷新率 ≈ %.1f Hz"
              % (len(jumps), med * 1000, 1 / med))
        print("       最大单次跳变 = %.4f mm @ t = %.3f s"
              % (abs(cmd[big] - cmd[big - 1]), t[big]))

    # ---- 找斜坡起点（第一个大幅跳变之后）
    i_ramp = next((i for i in range(1, n) if abs(cmd[i] - cmd[i - 1]) > 0.2 and t[i] > 5), 0)
    i_tail = max(0, n - NFFT)

    # ---- 频率分辨率
    print("\n[F-07] DFT 分辨率 fs/nfft = %.6f Hz  ← 主频若落最低 bin 就是这个值"
          % (fs / NFFT))

    # ---- 逐通道 100 Hz / 200 Hz 谱线幅值
    k100 = int(100.0 * NFFT / fs)
    k200 = int(200.0 * NFFT / fs)
    print("\n[F-08] 100 Hz 落在 bin %d(%.2f Hz)，200 Hz 落在 bin %d(%.2f Hz)"
          % (k100, k100 * fs / NFFT, k200, k200 * fs / NFFT))
    for wname, off in (("斜坡段 t=%.3f~%.3f s" % (t[i_ramp], t[i_ramp] + NFFT / fs), i_ramp),
                       ("静止尾段 t=%.3f~%.3f s" % (t[i_tail], t[-1]), i_tail)):
        print("  --- %s ---" % wname)
        for cname, sig in (("cmd", cmd), ("fb", fb), ("err", err)):
            amp, freq, power, nn = dft(sig, off, fs=fs)
            rms = math.sqrt(power / 2.0) if power else 0.0
            a100 = amp[k100]
            print("    %-4s %.2fHz幅值=%.6f  %.2fHz幅值=%.6f  窗口RMS=%.6f  a100/RMS=%.3f%%"
                  % (cname, freq[k100], a100, freq[k200], amp[k200], rms,
                     a100 / rms * 100 if rms else 0))
        # 带内能量占比
        for cname, sig in (("cmd", cmd), ("fb", fb), ("err", err)):
            ratio, peaks, _ = band_ratio(sig, off, fs=fs)
            top = ", ".join("%.1fHz" % f for _, f in peaks[:4])
            print("    %-4s %.0f~%.0f Hz 带内能量占比 = %.2f%%   带内谱峰: %s"
                  % (cname, BAND_LO, BAND_HI, ratio * 100, top))

    print("\n" + "=" * 72)
    print("判读要点：")
    print("  · 100 Hz 这条线在 cmd / fb / err 里**物理都存在**（指令刷新阶梯透传到轴），")
    print("    所以它不是「伪谱线」；但它在 err 里的**绝对幅值**相对误差动态量级极小。")
    print("  · 频率类判据必须用**绝对幅值 / 误差动态 std**，")
    print("    不能用带内能量占比或相对突出度——否则会被这条真实但微弱的刷新线带偏。")
    print("  · 报告里要同时给：谱线绝对幅值、误差动态 std、两者比值、频率分辨率 fs/nfft。")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
