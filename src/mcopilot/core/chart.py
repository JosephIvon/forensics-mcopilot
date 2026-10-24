"""图表输出。matplotlib 缺失时降级为「不画图但报告照出」，不阻断主流程。

中文字体：Windows 上优先用 Microsoft YaHei；找不到就退英文标签，
避免出现方块乱码把报告搞得更难看。
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Sequence

HAS_MPL = True
try:  # pragma: no cover - 环境相关
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
except Exception:  # pragma: no cover
    HAS_MPL = False
    plt = None  # type: ignore

_CN_FONTS = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "PingFang SC"]
_CN_OK = False


def _setup_font() -> bool:
    """尝试启用中文字体，返回是否可用。"""
    global _CN_OK
    if not HAS_MPL:
        return False
    if _CN_OK:
        return True
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in _CN_FONTS:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name]
            plt.rcParams["axes.unicode_minus"] = False
            _CN_OK = True
            return True
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return False


def _t(zh: str, en: str) -> str:
    return zh if _setup_font() else en


def save_profile_chart(path: Path, t: Sequence[float], x: Sequence[float], v: Sequence[float],
                       a: Sequence[float], title: str) -> Path | None:
    """位置/速度/加速度三联图。"""
    if not HAS_MPL:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fig, axes = plt.subplots(3, 1, figsize=(9, 8.5), sharex=True)
        axes[0].plot(t, x, lw=1.6, color="#2f6feb")
        axes[0].set_ylabel(_t("位置 (mm)", "Position (mm)"))
        axes[1].plot(t, v, lw=1.6, color="#1a7f37")
        axes[1].set_ylabel(_t("速度 (mm/s)", "Velocity (mm/s)"))
        axes[2].plot(t, a, lw=1.6, color="#bc4c00")
        axes[2].set_ylabel(_t("加速度 (mm/s²)", "Accel (mm/s^2)"))
        axes[2].set_xlabel(_t("时间 (s)", "Time (s)"))
        fig.suptitle(title)
        fig.tight_layout()
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=130)
        plt.close(fig)
    return path


def save_servo_chart(path: Path, t: Sequence[float], fb: Sequence[float],
                     err: Sequence[float], target: float | None,
                     title: str) -> Path | None:
    """伺服阶跃响应：上=位置（含目标线），下=跟随误差。"""
    if not HAS_MPL:
        return None
    # 长度不一致要在这里显式炸掉。matplotlib 会抛
    # "x and y must have same first dimension"，看不出是哪一路数据短了；
    # 而"误差序列比时间轴短"是真实的波形契约违约（交叉验证里抓到过），
    # 不该被静默截断或补零。
    if not (len(t) == len(fb) == len(err)):
        raise ValueError(
            "save_servo_chart: 长度不一致 t=%d fb=%d err=%d —— "
            "误差序列必须与时间轴逐点对齐，不允许截断或补零" % (len(t), len(fb), len(err))
        )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fig, axes = plt.subplots(2, 1, figsize=(9, 5.6), sharex=True)
        axes[0].plot(t, fb, lw=1.6, color="#2f6feb")
        if target is not None:
            axes[0].axhline(target, color="#2f9e44", lw=1.0, ls="--",
                            label=_t("目标值", "target"))
            axes[0].legend(loc="lower right", fontsize=8)
        axes[0].set_ylabel(_t("反馈位置 (mm)", "Feedback (mm)"))
        axes[1].plot(t, err, lw=1.4, color="#bc4c00")
        axes[1].axhline(0, color="#656d76", lw=0.8)
        axes[1].set_ylabel(_t("跟随误差 (mm)", "Following error (mm)"))
        axes[1].set_xlabel(_t("时间 (s)", "Time (s)"))
        fig.suptitle(title)
        fig.tight_layout()
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=130)
        plt.close(fig)
    return path


def save_cam_chart(path: Path, master: Sequence[float], slave: Sequence[float],
                   slopes: Sequence[float], title: str) -> Path | None:
    """电子凸轮表：上=从轴位置随主轴坐标变化，下=各段斜率（断点处的高度差就是速度阶跃）。"""
    if not HAS_MPL:
        return None
    if not (len(master) == len(slave)) or len(slopes) != len(master) - 1:
        raise ValueError(
            "save_cam_chart: 长度不一致 master=%d slave=%d slopes=%d —— "
            "master/slave 必须逐点等长，slopes 是**按段**的斜率（应为点数-1），"
            "不允许静默截断"
            % (len(master), len(slave), len(slopes))
        )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fig, axes = plt.subplots(2, 1, figsize=(9, 6.4), sharex=True)
        axes[0].plot(master, slave, marker="o", ms=4, lw=1.5, color="#2f6feb")
        axes[0].set_ylabel(_t("从轴位置 (mm)", "Slave (mm)"))
        axes[0].set_title(_t("凸轮曲线", "Cam curve"))
        # 斜率画成台阶：每段一根竖线，高度=该段斜率
        mid: list[float] = []
        val: list[float] = []
        for i, k in enumerate(slopes):
            if i + 1 < len(master):
                mid.append(0.5 * (master[i] + master[i + 1]))
                val.append(k)
        if mid:
            axes[1].bar(mid, val, width=[max(1e-9, abs(master[i + 1] - master[i])) * 0.9
                                         for i in range(len(val))], color="#8250df", alpha=0.75)
        axes[1].axhline(0, color="#656d76", lw=0.8)
        axes[1].set_ylabel(_t("段斜率 k", "Slope k"))
        axes[1].set_xlabel(_t("主轴坐标", "Master"))
        axes[1].set_title(_t("各段斜率（相邻高度差 = 速度阶跃的来源）",
                             "Segment slopes"))
        fig.suptitle(title)
        fig.tight_layout()
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=130)
        plt.close(fig)
    return path


def save_control_chart(path: Path, x: Sequence[float], cl: float, ucl: float, lcl: float,
                        title: str, xlabel: str = "样本序号") -> Path | None:
    """I 图（个体值控制图）。"""
    if not HAS_MPL:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fig, ax = plt.subplots(figsize=(10, 4.4))
        idx = list(range(1, len(x) + 1))
        ax.plot(idx, x, marker="o", ms=3.5, lw=1.0, color="#2f6feb", label=_t("实测值", "value"))
        ax.axhline(cl, color="#1a7f37", lw=1.1, label="CL")
        ax.axhline(ucl, color="#d64545", lw=1.0, ls="--", label="UCL")
        ax.axhline(lcl, color="#d64545", lw=1.0, ls="--", label="LCL")
        ooc = [(i, v) for i, v in zip(idx, x) if v > ucl or v < lcl]
        if ooc:
            ax.scatter([i for i, _ in ooc], [v for _, v in ooc], s=58, facecolors="none",
                       edgecolors="#d64545", zorder=5, label=_t("超限点", "OOC"))
        ax.set_title(title)
        ax.set_xlabel(xlabel)
        ax.legend(loc="upper right", fontsize=8)
        fig.tight_layout()
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=130)
        plt.close(fig)
    return path


def save_mr_chart(path: Path, mr: Sequence[float], cl: float, ucl: float, title: str) -> Path | None:
    if not HAS_MPL:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fig, ax = plt.subplots(figsize=(10, 3.6))
        idx = list(range(1, len(mr) + 1))
        ax.plot(idx, mr, marker="o", ms=3.5, lw=1.0, color="#8250df")
        ax.axhline(cl, color="#1a7f37", lw=1.1, label="CL")
        ax.axhline(ucl, color="#d64545", lw=1.0, ls="--", label="UCL")
        ax.set_title(title)
        ax.set_xlabel(_t("样本序号", "Index"))
        ax.legend(loc="upper right", fontsize=8)
        fig.tight_layout()
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=130)
        plt.close(fig)
    return path


def save_bar_chart(path: Path, labels: Sequence[str], values: Sequence[float], title: str,
                   ylabel: str = "", color: str = "#2f6feb", horizontal: bool = False) -> Path | None:
    if not HAS_MPL:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fig, ax = plt.subplots(figsize=(max(6, len(labels) * 0.85), 4.2))
        if horizontal:
            ax.barh(labels, values, color=color)
            ax.set_xlabel(ylabel)
        else:
            ax.bar(labels, values, color=color)
            ax.set_ylabel(ylabel)
        ax.set_title(title)
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right", fontsize=8)
        fig.tight_layout()
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=130)
        plt.close(fig)
    return path


def save_trend_chart(path: Path, labels: Sequence[str], values: Sequence[float], title: str,
                     ylabel: str = "", threshold: float | None = None) -> Path | None:
    if not HAS_MPL:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fig, ax = plt.subplots(figsize=(10, 4.0))
        idx = list(range(1, len(values) + 1))
        ax.plot(idx, values, marker="o", ms=4, lw=1.4, color="#bc4c00")
        if threshold is not None:
            ax.axhline(threshold, color="#d64545", lw=1.0, ls="--", label=_t("阈值", "threshold"))
            ax.legend(fontsize=8)
        ax.set_xticks(idx)
        ax.set_xticklabels(labels, rotation=40, ha="right", fontsize=7)
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        fig.tight_layout()
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=130)
        plt.close(fig)
    return path
