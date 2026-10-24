#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""独立复算 servo 报告里的**频域口径**数值 —— 不用 mcopilot 的任何函数。

为什么要这个脚本
----------------
servo 报告在导出 10 上会印出一组频域数字（谱线频率 / 绝对幅值 / 两个口径的动态 std /
谱线占比 / 与刷新率的相对差）。这些数字直接决定「这条谱线进不进结论」，
必须可独立复算。

**审的对象不能用被审的代码去验** —— 拿 `mcopilot.agents.servo` 复算 servo 的结论，
就是 axiscope 审计里说的"同源自证"。所以本脚本只读 CSV、只用标准库重算，
并按 servo.py 的算法口径（去趋势 + Hann 窗 + `|acc|/n*4` 的相干增益修正）逐步对齐。

口径陷阱（踩过一次，值得写在这里）
----------------------------------
1. **nfft 是 1024，且只取稳态窗的前 1024 点**。若把 8500 点的窗按 1024 的 bin 频率映射去算，
   查的其实是 12 Hz 而不是 99.6 Hz —— 结论会差 10 倍。
2. 频谱窗口必须落在**真稳态段**，否则整条判据不适用。
3. 判据分母用**同一稳态窗内**的去偏置误差 std；全记录口径同时报出（两者差别很大：
   Export10 窗内 ~80% vs 全记录 ~2%）。全记录口径会把真实谐振压到可忽略。

用法
----
    python scripts/verify_servo_spectrum.py
    python scripts/verify_servo_spectrum.py --csv samples/servo/twincat_export10.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_CSV = os.path.join(ROOT, "samples", "servo", "twincat_export10.csv")

NFFT = 1024
BAND_LO, BAND_HI = 12.0, 120.0
# 稳态窗（等速段）：由 servo 的稳态窗选择逻辑给出，这里固定下来便于复算
WIN_I0, WIN_N = 10125, 8500


def load(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    t = [float(r["time_ms"]) / 1000.0 for r in rows]
    cmd = [float(r["cmd_pos"]) for r in rows]
    fb = [float(r["fb_pos"]) for r in rows]
    return t, cmd, fb


def demean_std(xs):
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def hann_dft(seg, k):
    """去趋势 + Hann 窗后的第 k 个 bin 的幅度（相干增益修正 ×4）。"""
    n = len(seg)
    m0 = sum(seg) / n
    mid = (n - 1) / 2.0
    sxx = sum((i - mid) ** 2 for i in range(n))
    sxy = sum((i - mid) * (seg[i] - m0) for i in range(n))
    slope = (sxy / sxx) if sxx else 0.0
    inter = m0 - slope * mid
    win = [0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)) for i in range(n)]
    acc = 0j
    for i in range(n):
        v = (seg[i] - (inter + slope * i)) * win[i]
        ang = -2 * math.pi * k * i / n
        acc += v * complex(math.cos(ang), math.sin(ang))
    return abs(acc) / n * 4.0


def median(v):
    s = sorted(v)
    L = len(s)
    return s[L // 2] if L % 2 else (s[L // 2 - 1] + s[L // 2]) / 2


def refresh_rate(t, cmd):
    jumps = [i for i in range(1, len(cmd)) if abs(cmd[i] - cmd[i - 1]) > 1e-9]
    iv = sorted(t[jumps[i]] - t[jumps[i - 1]] for i in range(1, len(jumps)))
    med = iv[len(iv) // 2]
    return 1.0 / med, med, len(jumps)


def main(argv=None):
    ap = argparse.ArgumentParser(description="独立复算 servo 报告的频域口径数值")
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--i0", type=int, default=WIN_I0, help="稳态窗起始样本")
    ap.add_argument("--win", type=int, default=WIN_N, help="稳态窗长度（样本）")
    args = ap.parse_args(argv)

    t, cmd, fb = load(args.csv)
    err = [c - f for c, f in zip(cmd, fb)]
    fs = 1000.0
    i0, n_win = args.i0, args.win
    win_err = err[i0:i0 + n_win]

    print("CSV           : %s" % args.csv)
    print("样本          : %d 点, fs = %.0f Hz" % (len(t), fs))
    print("稳态窗        : [%d, %d)  t = %.3f~%.3f s"
          % (i0, i0 + n_win, t[i0], t[i0 + n_win - 1]))
    print("")

    rr, rr_med, n_jump = refresh_rate(t, cmd)
    sd_win = demean_std(win_err)
    sd_all = demean_std(err)

    # ---- 频谱：只取稳态窗前 NFFT 点 ----
    seg = win_err[:NFFT]
    kmax = NFFT // 2 - 1
    mags = {k: (k * fs / NFFT, hann_dft(seg, k)) for k in range(0, kmax + 1)}
    res = fs / NFFT

    # 局部突出度最大的窄带线（复刻 servo.narrowband_line）
    best = None
    for k in range(2, kmax - 1):
        f, mag = mags[k]
        if not (BAND_LO <= f <= BAND_HI):
            continue
        others = [mags[kk][1] for kk in range(k - 2, k + 3) if kk in mags and kk != k]
        if not others:
            continue
        base = median(others)
        prom = mag / base if base > 1e-15 else float("inf")
        if best is None or prom > best["prom"]:
            best = {"k": k, "f": f, "amp": mag, "prom": prom, "base": base}

    mx = max(((mags[k][1], mags[k][0], k) for k in range(2, kmax - 1)
              if BAND_LO <= mags[k][0] <= BAND_HI))

    print("指令刷新率    : %.2f Hz  (跳变间隔中位数 %.3f ms, %d 次跳变)"
          % (rr, rr_med * 1000, n_jump))
    print("频率分辨率    : fs/nfft = %.6f Hz  (nfft=%d, 只取稳态窗前 %d 点)"
          % (res, NFFT, NFFT))
    print("窗内去偏置std : %.6f mm   (判据分母口径)" % sd_win)
    print("全记录去偏置std: %.6f mm" % sd_all)
    print("")
    print("窄带线(局部突出度最大) : bin %d  f=%.3f Hz  幅值=%.6f mm  突出度=%.1f  基线=%.6f"
          % (best["k"], best["f"], best["amp"], best["prom"], best["base"]))
    print("幅值最大的线          : bin %d  f=%.3f Hz  幅值=%.6f mm" % (mx[2], mx[1], mx[0]))
    print("")
    print("谱线 / 窗内动态量级   : %.2f%%   (判据口径)" % (best["amp"] / sd_win * 100))
    print("谱线 / 全记录动态量级 : %.2f%%" % (best["amp"] / sd_all * 100))
    print("与刷新率的相对差      : %.2f%%  (1 次谐波)" % (abs(best["f"] - rr) / rr * 100))
    print("")

    # 与 servo 报告的预期值对照
    EXP = {
        "窄带线频率": (best["f"], 99.609, 0.01),
        "窄带线绝对幅值": (best["amp"], 0.005838, 1e-5),
        "与刷新率相对差%": (abs(best["f"] - rr) / rr * 100, 0.39, 0.05),
        "全记录口径占比%": (best["amp"] / sd_all * 100, 2.16, 0.05),
    }
    ok = True
    print("与 servo 报告的预期值对照:")
    for name, (got, exp, tol) in EXP.items():
        good = abs(got - exp) <= tol
        ok = ok and good
        print("  %s %-18s 复算=%-12s 报告=%-10s 容差=%s"
              % ("OK " if good else "!! ", name, ("%.6f" % got) if got < 1 else ("%.3f" % got),
                 exp, tol))
    print("")
    print("结论: %s" % ("全部吻合" if ok else "存在偏差，见上表"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
