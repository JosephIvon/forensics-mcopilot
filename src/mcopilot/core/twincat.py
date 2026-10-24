"""TwinCAT / CODESYS Scope View 原生导出 → mcopilot 规范波形（纯解析器）。

本模块只做「厂商格式 → mcopilot 规范列」的解析与核对，**不依赖 matplotlib、不依赖 numpy**，
只用 Python 标准库。

────────────────────────────────────────────────────────────────────────────
外部真值（全部可复核，不靠记忆断言）
────────────────────────────────────────────────────────────────────────────
1. 源文件（标本）：
   ``<axiscope 仓>/data/raw/Export10_244531.csv``
   实测结构（用本模块解析器复核）：
     · 第 1~4 行  文件级元数据（Name/Measurement、File、Starttime of export、Endtime of export）
     · 第 5~6 行  空行分隔
     · 第 7 行    通道名行：`Name<TAB>dForce_load<TAB>Name<TAB>dPower_load<TAB>…`（32 通道 = 64 列）
     · 第 8~12 行 每通道元数据行：SampleTime[ms] / SymbolBased / SymbolName / NetID / Port
     · 第 13 行   空行分隔
     · 第 14 行起 数据区：`0<TAB>150.6<TAB>0<TAB>-4<TAB>…`，每通道一组 `(x, value)`
     · 末行       `EOF` 哨兵
2. 结构规格（项目内已核验的逐行解剖）：
   ``docs/kb/KB2-waveform-formats.md`` §一（表格见 L48-L63，§1.1 取列规则 L65-L75，
   §1.4「表头行数不许硬编码」的结构特征定位规则 L102-L129，坑 2/4 见 L167-L223）
3. 规范契约：``docs/contracts/C1-canonical-waveform.md``（通道词表 L33-L46、派生规则 L179-L186）
4. 上游实测报告：``data/validate_out.txt`` L35-L51（Export10 的通道/时基/恒等式结论）
   ``data/validate_raw.py`` L260-L261（记录了「把 `Port 851` 表头行当数据行」的历史坑）

────────────────────────────────────────────────────────────────────────────
设计纪律
────────────────────────────────────────────────────────────────────────────
* 解析失败一律抛 :class:`TwincatParseError`，**绝不静默返回空结果**。
* 表头行数不写死，靠结构特征定位（KB2 §1.4）；通道按**列位置**取数，不靠名字匹配取数。
* 语义映射只认显式词表（双词表：Scope 别名 + ADS 符号末段），**不猜语义**；
  未命中的通道一律进 extra（KB2 §3.6）。
* 行列账目闭合：纳入行 + 跳过行 = 数据区总行数，跳过行逐行记进 meta（KB2 坑 4 断言）。
"""

from __future__ import annotations

import csv
import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

__all__ = [
    "TwincatParseError",
    "Channel",
    "ChannelMapping",
    "TwincatExport",
    "SEMANTIC_MAP",
    "CANONICAL_COLUMNS",
    "LABEL_KEYS",
    "TRIGGER_GATE_LABEL",
    "sha256_file",
    "parse_twincat",
    "map_channels",
    "write_canonical_csv",
    "fe_identity",
    "pearson",
    "build_meta",
]


# ─────────────────────────────────────────────────────────── 常量 / 词表

#: 通道表（metadata block）允许出现的标签集合（KB2 §一 L118）
LABEL_KEYS = frozenset({
    "Name", "SampleTime[ms]", "SymbolBased", "SymbolName", "NetID", "Port", "Data-Type",
})

#: 采样周期标签行
SAMPLE_TIME_LABEL = "SampleTime[ms]"

#: 触发门控旗标（KB2 坑 2：只有 bTrigger_Record != 0 的行才是真正落库的行）
TRIGGER_GATE_LABEL = "bTrigger_Record"

#: 语义映射表：Scope 别名 / ADS 符号末段 → mcopilot 规范列名。
#:
#: 只登记**语义明确**的通道；其余通道一律进 extra（KB2 §3.6「不丢弃、不猜语义」）。
#: 注意 `dPosition_asco` 与 `dPosition_asco_enc` 是两个不同通道，必须**精确匹配**，
#: 绝不能用前缀/子串匹配（否则 `_enc` 会被 `_` 前缀吃掉）。
#:
#: 本表目前只覆盖 `dXxx` 词族（本项目 Export10_244531.csv 实测）。
#: 另一战役的 `x_T` / `f_L` 词族（KB2 §1.2 约定 A 的另一套别名）**故意不登记**：
#: 没有实测确认语义之前一律进 extra，不猜。
SEMANTIC_MAP: dict[str, str] = {
    "dPosition_asco": "cmd_pos",       # ASCO 位置 → 指令位置
    "dPosition_asco_enc": "fb_pos",    # ASCO 编码器位置 → 反馈位置
    "dVelocity_asco": "vel",           # ASCO 速度 → 速度
    "dVelocity_asco_enc": "vel_fb",    # ASCO 编码器速度 → 速度反馈
}

#: 输出 CSV 中规范列的固定顺序（time_ms 固定在第 1 列）
CANONICAL_COLUMNS: tuple[str, ...] = ("cmd_pos", "fb_pos", "vel", "vel_fb")

_NUM_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


# ─────────────────────────────────────────────────────────── 异常

class TwincatParseError(RuntimeError):
    """TwinCAT 导出解析失败（结构不符 / 数据不可解 / 语义冲突）。

    解析器**不会**用空结果代替失败：本异常向上抛，调用方必须显式处理。
    """


# ─────────────────────────────────────────────────────────── 数据结构

@dataclass(frozen=True)
class Channel:
    """一个被解析出来的通道。

    attributes:
        name: Scope 别名（约定 A，第 7 行 `Name` 行奇数列），例 `dPosition_asco`
        symbol: ADS 符号路径（约定 B，`SymbolName` 行），例 `Measurement_Connector.dPosition_asco`；无则 None
        leaf: 符号末段（`symbol` 最后一个 `.` 之后），无 symbol 时等于 `name`
        index: 列位置（0 基），数据区取值列 = 2*index+1
        sample_time_ms: 该通道声明的采样周期（ms）
        values: 采样值序列（坏点为 nan）
    """

    name: str
    symbol: str | None
    leaf: str
    index: int
    sample_time_ms: float
    values: tuple[float, ...]


@dataclass
class ChannelMapping:
    """语义映射结果。"""

    canonical: dict[str, Channel] = field(default_factory=dict)
    extra: list[Channel] = field(default_factory=list)

    def columns(self) -> list[str]:
        """按固定顺序给出实际存在的规范列名。"""
        return [c for c in CANONICAL_COLUMNS if c in self.canonical]


@dataclass
class TwincatExport:
    """一次 TwinCAT 导出的完整解析结果。"""

    path: Path
    sha256: str
    size_bytes: int
    file_meta: dict[str, list[str]]          # 文件级元数据（Name/Measurement、File、Starttime…）
    channels: list[Channel]
    time_ms: list[float]                     # 时间轴（毫秒），严格单调
    sample_time_ms: float                    # 声明的采样周期（ms）
    n_data_lines: int = 0                    # 数据区物理行数（含 EOF 哨兵与空行）
    n_rows: int = 0                          # 纳入的行数
    skipped: list[dict[str, Any]] = field(default_factory=list)   # 账目：被跳过的行
    eof_sentinel: bool = False               # 是否见到 EOF 哨兵
    header_layout: dict[str, Any] = field(default_factory=dict)  # 结构定位结果
    warnings: list[str] = field(default_factory=list)

    def channel_by_alias(self, alias: str) -> Channel | None:
        """按 Scope 别名或符号末段取通道。"""
        for ch in self.channels:
            if ch.name == alias or ch.leaf == alias:
                return ch
        return None


# ─────────────────────────────────────────────────────────── 工具

def sha256_file(path: Path) -> str:
    """文件 sha256（十六进制，小写）。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_number(tok: str) -> bool:
    """是否是纯数字串（用于区分「通道名」与「数值表头行」）。"""
    tok = tok.strip()
    if not tok:
        return False
    if tok in ("nan", "NaN", "NAN", "inf", "-inf", "Infinity"):
        return True
    return bool(_NUM_RE.match(tok))


def _to_float(tok: str) -> float | None:
    """把单元格转 float；空串与 NaN 字面量 → nan（KB2 §1.3）；无法解析 → None。"""
    tok = tok.strip()
    if tok == "" or tok.lower() == "nan":
        return float("nan")
    try:
        return float(tok)
    except ValueError:
        return None


def _fmt(v: float) -> str:
    """浮点 → 字符串：整数值写成整数形式，其余用 repr（最短往返，精度不丢）。"""
    if isinstance(v, float) and math.isnan(v):
        return "nan"
    if float(v).is_integer() and abs(v) < 1e15:
        return str(int(v))
    return repr(float(v))


def pearson(a: Sequence[float], b: Sequence[float]) -> float:
    """Pearson 相关系数；任一侧零方差 → nan。"""
    n = min(len(a), len(b))
    if n < 2:
        return float("nan")
    ma = sum(a[:n]) / n
    mb = sum(b[:n]) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in a[:n]))
    db = math.sqrt(sum((x - mb) ** 2 for x in b[:n]))
    if da == 0.0 or db == 0.0:
        return float("nan")
    return num / (da * db)


def _stats(values: Sequence[float]) -> dict[str, float]:
    """一组值的统计量（总体标准差 ddof=0，与 numpy 默认一致）。"""
    vals = [v for v in values if not math.isnan(v)]
    if not vals:
        return {"n": 0, "min": float("nan"), "max": float("nan"),
                "mean": float("nan"), "std": float("nan")}
    n = len(vals)
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    return {"n": n, "min": min(vals), "max": max(vals),
            "mean": mean, "std": math.sqrt(var)}


# ─────────────────────────────────────────────────────────── 解析

def parse_twincat(path: str | Path, *,
                  sample_time_ms: float | None = None,
                  trigger_gate: bool = False) -> TwincatExport:
    """解析一份 TwinCAT / CODESYS Scope View 原生导出。

    结构定位完全按 KB2 §1.4 的「结构特征定位」规则，不写死表头行数。

    args:
        path: 源文件路径
        sample_time_ms: 覆盖采样周期（None = 从 `SampleTime[ms]` 行读，读不到就报错）
        trigger_gate: True 时按 KB2 坑 2 丢掉 `bTrigger_Record == 0` 的行（默认 False：全量导出）

    returns:
        TwincatExport

    raises:
        TwincatParseError: 任何结构/数据问题（定位不到通道表、数值不可解、时基非单调……）
    """
    p = Path(path)
    if not p.is_file():
        raise TwincatParseError(f"源文件不存在：{p}")
    raw = p.read_bytes()
    digest = sha256_file(p)
    text = raw.decode("utf-8", errors="replace")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # ── 1) 定位通道名行：f[0]=="Name" 且 f[2]=="Name"，且奇数列均为非数字标识符
    header_idx: int | None = None
    header_fields: list[str] = []
    for i, ln in enumerate(lines):
        f = ln.split("\t")
        if len(f) < 4 or len(f) % 2 != 0:
            continue
        if f[0].strip() != "Name" or f[2].strip() != "Name":
            continue
        names = [f[k].strip() for k in range(1, len(f), 2)]
        if all(n and not _is_number(n) for n in names):
            header_idx = i
            header_fields = f
            break
    if header_idx is None:
        raise TwincatParseError(
            f"{p.name}：找不到通道名行（期望形如 Name<TAB>xxx<TAB>Name<TAB>xxx 的偶数列同键行）")

    names = [header_fields[k].strip() for k in range(1, len(header_fields), 2)]
    n_ch = len(names)
    width = 2 * n_ch

    # ── 2) 通道表（元数据块）：紧跟通道名行、偶数列全部落在已知标签集里的连续行
    meta_rows: list[tuple[int, str, list[str]]] = []   # (行号, 标签, 每通道的值)
    j = header_idx + 1
    while j < len(lines):
        f = lines[j].split("\t")
        if len(f) != width:
            break
        labels = [x.strip() for x in f[0::2]]
        if not all(lab in LABEL_KEYS for lab in labels):
            break
        values = [f[k].strip() for k in range(1, len(f), 2)]
        meta_rows.append((j + 1, labels[0], values))
        j += 1
    block_end = j - 1

    # 通道级属性
    alias_of = list(names)
    symbol_of: list[str | None] = [None] * n_ch
    sample_time_of: list[float | None] = [None] * n_ch
    for line_no, label, values in meta_rows:
        if label == "SymbolName":
            symbol_of = [v or None for v in values]
        elif label == SAMPLE_TIME_LABEL:
            parsed = []
            for v in values:
                fv = _to_float(v)
                if fv is None:
                    raise TwincatParseError(
                        f"{p.name} 第 {line_no} 行：{SAMPLE_TIME_LABEL} 的值 {v!r} 不是数字")
                parsed.append(fv)
            sample_time_of = parsed
        elif label == "Name":
            alias_of = [v or names[k] for k, v in enumerate(values)]

    # 采样周期
    if sample_time_of and any(v is not None for v in sample_time_of):
        uniq = sorted({v for v in sample_time_of if v is not None})
        if len(uniq) != 1:
            raise TwincatParseError(
                f"{p.name}：各通道声明的采样周期不一致 {uniq}，无法确定时基")
        dt_ms = float(uniq[0])
        if dt_ms <= 0:
            raise TwincatParseError(f"{p.name}：采样周期非法 {dt_ms}")
        declared_source = f"声明（{SAMPLE_TIME_LABEL} 行）"
    elif sample_time_ms is not None:
        dt_ms = float(sample_time_ms)
        declared_source = "调用方覆盖"
    else:
        raise TwincatParseError(
            f"{p.name}：找不到 {SAMPLE_TIME_LABEL} 行，也未提供 sample_time_ms 覆盖值，"
            "拒绝猜测时基")

    # ── 3) 文件级元数据块（通道表之前、且不是通道名行的键值行）
    file_meta: dict[str, list[str]] = {}
    for i in range(header_idx):
        f = lines[i].split("\t")
        if len(f) < 2:
            continue
        key = f[0].strip()
        if not key or key in LABEL_KEYS:
            continue
        vals = [x.strip() for x in f[1:] if x.strip()]
        if vals:
            file_meta.setdefault(key, []).extend(vals)

    # ── 4) 数据区
    data_lines: list[tuple[int, str]] = []
    k = block_end + 1
    eof = False
    while k < len(lines):
        ln = lines[k]
        s = ln.strip()
        if s == "":
            k += 1
            continue
        if s.upper() == "EOF":
            eof = True
            k += 1
            continue
        data_lines.append((k + 1, ln))
        k += 1

    if not data_lines:
        raise TwincatParseError(f"{p.name}：数据区为空（表头行定位到第 {header_idx + 1} 行之后没有数据）")

    xs: list[float] = []
    channels_data: list[list[float]] = [[] for _ in range(n_ch)]
    skipped: list[dict[str, Any]] = []
    for line_no, ln in data_lines:
        f = ln.split("\t")
        if len(f) < width:
            skipped.append({"line": line_no, "reason": f"列数 {len(f)} < 2N={width}",
                            "skipped_rows": 1})
            continue
        # 时间列：每通道一组 (x, value)，同一行所有 x 必须相等（KB2 §1.1）
        try:
            x_vals = [float(f[2 * i]) for i in range(n_ch)]
        except ValueError:
            skipped.append({"line": line_no, "reason": "时间列含非数字", "skipped_rows": 1})
            continue
        if max(x_vals) != min(x_vals):
            raise TwincatParseError(
                f"{p.name} 第 {line_no} 行：各通道时间列不一致 {sorted(set(x_vals))[:4]}，"
                "无法确定统一时基")
        row_vals: list[float] = []
        bad = False
        for i in range(n_ch):
            v = _to_float(f[2 * i + 1])
            if v is None:
                bad = True
                break
            row_vals.append(v)
        if bad:
            skipped.append({"line": line_no, "reason": "值列含不可解析的数值", "skipped_rows": 1})
            continue
        xs.append(x_vals[0])
        for i in range(n_ch):
            channels_data[i].append(row_vals[i])

    if not xs:
        raise TwincatParseError(f"{p.name}：数据区没有任何可解析的行（跳过 {len(skipped)} 行）")
    skip_ratio = len(skipped) / float(len(data_lines))
    if skip_ratio > 0.01:
        raise TwincatParseError(
            f"{p.name}：数据区跳过行占比 {skip_ratio:.3%}（{len(skipped)}/{len(data_lines)}）"
            "超过 1% 阈值，判定文件损坏，拒绝静默丢行")

    # ── 5) 时基校验：严格单调递增
    dts = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    if any(d <= 0 for d in dts):
        bad = next(i for i, d in enumerate(dts) if d <= 0)
        raise TwincatParseError(
            f"{p.name}：时间列非严格单调（第 {bad + 2} 个数据行起 x 不再递增）")

    # ── 6) 触发门控（KB2 坑 2，可选）
    gate_info: dict[str, Any] = {"applied": bool(trigger_gate), "label": TRIGGER_GATE_LABEL}
    keep = list(range(len(xs)))
    gate_ch = None
    for ch_idx, ch in enumerate(alias_of):
        if ch == TRIGGER_GATE_LABEL:
            gate_ch = ch_idx
            break
    if gate_ch is not None:
        truth = sum(1 for v in channels_data[gate_ch] if not math.isnan(v) and v != 0)
        gate_info["flag_true_ratio"] = truth / float(len(xs))
        gate_info["flag_true_rows"] = truth
    if trigger_gate:
        if gate_ch is None:
            raise TwincatParseError(
                f"{p.name}：请求触发门控，但找不到 {TRIGGER_GATE_LABEL} 通道")
        keep = [i for i in range(len(xs))
                if not math.isnan(channels_data[gate_ch][i]) and channels_data[gate_ch][i] != 0]
        gate_info["dropped_rows"] = len(xs) - len(keep)
        gate_info["retained_rows"] = len(keep)
        if not keep:
            raise TwincatParseError(f"{p.name}：触发门控后没有任何有效行")

    time_ms = [xs[i] * dt_ms for i in keep]
    channels: list[Channel] = []
    for i in range(n_ch):
        sym = symbol_of[i]
        leaf = sym.rsplit(".", 1)[-1] if sym else alias_of[i]
        st = sample_time_of[i] if i < len(sample_time_of) and sample_time_of[i] is not None else dt_ms
        channels.append(Channel(
            name=alias_of[i],
            symbol=sym,
            leaf=leaf,
            index=i,
            sample_time_ms=float(st),
            values=tuple(channels_data[i][j] for j in keep),
        ))

    # ── 7) 时基自检：声明周期 vs 实测索引差分
    warnings: list[str] = []
    inferred_dt = (dts[len(dts) // 2] if dts else 0.0) * dt_ms
    if dts:
        uniq_d = sorted(set(dts))
        if len(uniq_d) != 1:
            warnings.append(f"索引列步长不唯一：{uniq_d[:5]}（声明周期 {dt_ms} ms）")
    if abs(inferred_dt - dt_ms) > 1e-9:
        warnings.append(
            f"声明采样周期 {dt_ms} ms 与索引差分推得的 {inferred_dt} ms 不一致，"
            "按时轴 = 索引 × 声明周期 计算，差异已记录")

    span_s = (time_ms[-1] - time_ms[0]) / 1000.0 if len(time_ms) > 1 else 0.0
    header_layout = {
        "n_channels": n_ch,
        "n_columns": width,
        "channel_name_row": header_idx + 1,
        "channel_table_rows": [{"line": ln, "label": lab} for ln, lab, _ in meta_rows],
        "data_start_line": data_lines[0][0],
        "data_end_line": data_lines[-1][0],
        "eof_sentinel": eof,
        "file_meta_lines": len(file_meta),
    }

    return TwincatExport(
        path=p,
        sha256=digest,
        size_bytes=len(raw),
        file_meta=file_meta,
        channels=channels,
        time_ms=time_ms,
        sample_time_ms=dt_ms,
        n_data_lines=len(data_lines),
        n_rows=len(time_ms),
        skipped=skipped,
        eof_sentinel=eof,
        header_layout=header_layout,
        warnings=warnings,
    )


# ─────────────────────────────────────────────────────────── 语义映射

def map_channels(channels: Iterable[Channel]) -> ChannelMapping:
    """按语义词表把通道映射到 mcopilot 规范列；未命中的进 extra。

    匹配用**双词表**（KB2 §1.2）：Scope 别名 与 ADS 符号末段，任一命中即可；
    必须**精确相等**，不做前缀/子串匹配（`dPosition_asco` 与 `dPosition_asco_enc` 是两个通道）。
    """
    mapping = ChannelMapping()
    for ch in channels:
        target = SEMANTIC_MAP.get(ch.leaf) or SEMANTIC_MAP.get(ch.name)
        if target is None:
            mapping.extra.append(ch)
            continue
        if target in mapping.canonical:
            other = mapping.canonical[target]
            raise TwincatParseError(
                f"语义冲突：{other.symbol or other.name} 与 {ch.symbol or ch.name} "
                f"都映射到规范列 {target}，拒绝猜测")
        mapping.canonical[target] = ch
    return mapping


# ─────────────────────────────────────────────────────────── 输出

def write_canonical_csv(export: TwincatExport, mapping: ChannelMapping,
                        out_path: str | Path) -> dict[str, Any]:
    """写出 mcopilot 规范 CSV（time_ms + 规范列）。

    表头固定为 `time_ms,cmd_pos,fb_pos[,vel[,vel_fb]]`（按实际存在的规范列）。
    extra 通道**不写进规范表**（C1：多出来的通道进 meta/extra_channels，避免被频谱类特征误当信号），
    它们的信息记录在 meta 里。
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cols = mapping.columns()
    if "cmd_pos" not in cols or "fb_pos" not in cols:
        raise TwincatParseError(
            f"规范列不完整：cmd_pos={'cmd_pos' in cols} fb_pos={'fb_pos' in cols}；"
            f"已映射 {list(mapping.canonical)}，未映射 {[c.name for c in mapping.extra]}")
    header = ["time_ms"] + cols
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        for i in range(export.n_rows):
            row = [_fmt(export.time_ms[i])]
            for name in cols:
                row.append(_fmt(mapping.canonical[name].values[i]))
            w.writerow(row)
    return {"path": str(out), "header": header, "rows": export.n_rows}


# ─────────────────────────────────────────────────────────── 恒等式核对

def fe_identity(cmd: Sequence[float], fb: Sequence[float]) -> dict[str, Any]:
    """跟随误差恒等式核对：fe := cmd - fb（mcopilot servo.error_signal 约定：正号=尚未追上）。

    返回 mean/std(ddof=0)/max_abs/符号判定；并说明「恒等式成立」的含义边界。
    """
    n = min(len(cmd), len(fb))
    if n == 0:
        raise TwincatParseError("fe 恒等式核对：cmd/fb 为空")
    fe = [cmd[i] - fb[i] for i in range(n)]
    st = _stats(fe)
    pos = sum(1 for v in fe if v > 0)
    neg = sum(1 for v in fe if v < 0)
    zero = n - pos - neg
    if pos and not neg:
        sign = "fe = cmd - fb，恒为正（cmd_pos > fb_pos，尚未追上）"
    elif neg and not pos:
        sign = "fe = cmd - fb，恒为负（cmd_pos < fb_pos，约定下应判为符号相反，需复核映射）"
    elif pos and neg:
        sign = f"fe = cmd - fb，符号不一致（正 {pos} / 负 {neg} / 零 {zero}）"
    else:
        sign = "fe = cmd - fb，恒为 0"
    return {
        "definition": "fe = cmd_pos - fb_pos",
        "n": n,
        "mean": st["mean"],
        "std": st["std"],
        "std_kind": "population(ddof=0)",
        "max_abs": max(abs(v) for v in fe),
        "min": st["min"],
        "max": st["max"],
        "sign_verdict": sign,
        "identity_holds": True,
        "identity_note": (
            "恒等式按定义成立（fe 就是 cmd_pos - fb_pos 派生）。"
            "但要注意残差是否被常数偏置主导：std / max_abs 才是「动态误差」的量级。"),
        "dynamic_to_total_ratio": (st["std"] / max(abs(v) for v in fe)) if max(abs(v) for v in fe) else float("nan"),
    }


# ─────────────────────────────────────────────────────────── meta

def _redact(text: str) -> str:
    """把文件内嵌的本机绝对路径 / ADS NetID 脱敏（KB2 §六：发布前脱敏）。"""
    t = text.replace("\\", "/")
    parts = t.split("/")
    if len(parts) > 2:
        t = ".../" + "/".join(parts[-2:])
    return t


def _redact_netid(text: str) -> str:
    return re.sub(r"\b\d{1,3}(\.\d{1,3}){3}\.\d{1,3}\b", "[NETID]", text)


def build_meta(export: TwincatExport, mapping: ChannelMapping, *,
               csv_path: str | Path | None = None,
               servo_check: dict[str, Any] | None = None,
               fe_check: dict[str, Any] | None = None,
               extra_notes: Sequence[str] = ()) -> dict[str, Any]:
    """汇总成 meta JSON（可复核的事实集合）。"""
    t = export.time_ms
    span_s = (t[-1] - t[0]) / 1000.0 if len(t) > 1 else 0.0
    dts = [t[i + 1] - t[i] for i in range(len(t) - 1)]
    fs_measured = (len(t) - 1) / span_s if span_s > 0 else 0.0
    fs_from_dt = 1000.0 / (sum(dts) / len(dts)) if dts else 0.0
    fs_measured = round(fs_measured, 9)      # 消掉 1e-13 量级的浮点噪声
    fs_from_dt = round(fs_from_dt, 9)

    # 导出墙钟跨度（.NET ticks，100 ns 单位）——与数据跨度互为独立佐证
    wall_s = None
    st_v = export.file_meta.get("Starttime of export") or []
    en_v = export.file_meta.get("Endtime of export") or []
    if st_v and en_v:
        try:
            wall_s = (int(en_v[0]) - int(st_v[0])) / 1e7
        except ValueError:
            wall_s = None

    file_meta_out = {
        k: ([_redact_netid(_redact(v)) for v in vs] if k in ("File", "NetID") else vs)
        for k, vs in export.file_meta.items()
    }

    channel_map: dict[str, Any] = {}
    for name, ch in mapping.canonical.items():
        channel_map[name] = {
            "alias": ch.name,
            "symbol": ch.symbol,
            "leaf": ch.leaf,
            "column_index": ch.index,
            "value_column": 2 * ch.index + 1,
            "sample_time_ms": ch.sample_time_ms,
        }
    extra_list = []
    for ch in mapping.extra:
        st = _stats(ch.values)
        extra_list.append({
            "alias": ch.name,
            "symbol": ch.symbol,
            "leaf": ch.leaf,
            "column_index": ch.index,
            "value_column": 2 * ch.index + 1,
            "sample_time_ms": ch.sample_time_ms,
            "stats": st,
            "reason": "未命中语义词表（KB2 §3.6：不猜语义，保留在 extra）",
        })

    meta: dict[str, Any] = {
        "schema": "mcopilot.crossval.twincat/1",
        "generator": "mcopilot/scripts/convert_twincat.py + mcopilot/core/twincat.py",
        "source": {
            "path": str(export.path),
            "filename": export.path.name,
            "bytes": export.size_bytes,
            "sha256": export.sha256,
            "vendor": "beckhoff",
            "product": "CODESYS Scope View (TwinCAT 3)",
            "export_format": "tsv-interleaved + metadata header",
            "file_meta": file_meta_out,
            "redaction_note": "File 路径与 NetID 已按 KB2 §六 脱敏（只保留 basename / [NETID]）",
        },
        "layout": {
            **export.header_layout,
            "n_data_lines": export.n_data_lines,
            "n_rows_kept": export.n_rows,
            "skipped_rows": len(export.skipped),
            "accounting": {
                "kept_plus_skipped": export.n_rows + len(export.skipped),
                "data_lines": export.n_data_lines,
                "closed": (export.n_rows + len(export.skipped)) == export.n_data_lines,
            },
            "skipped_detail": export.skipped[:20],
        },
        "sample_rate": {
            "declared_sample_time_ms": export.sample_time_ms,
            "declared_source": f"{SAMPLE_TIME_LABEL} 行",
            "measured_fs_hz": fs_measured,
            "measured_fs_from_mean_dt_hz": fs_from_dt,
            "wallclock_span_s": wall_s,
            "wallclock_fs_hz": round((export.n_rows - 1) / wall_s, 9) if wall_s else None,
        },
        "duration_s": span_s,
        "n_samples": export.n_rows,
        "time_axis": {
            "unit": "ms",
            "monotonic_strict": all(d > 0 for d in dts),
            "dt_unique_ms": sorted(set(round(d, 9) for d in dts))[:8],
            "dt_jitter_ratio": 0.0 if len(set(round(d, 9) for d in dts)) == 1 else None,
            "t_first_ms": t[0] if t else None,
            "t_last_ms": t[-1] if t else None,
        },
        "channel_mapping": channel_map,
        "canonical_columns": ["time_ms"] + mapping.columns(),
        "extra_channels": extra_list,
        "extra_channel_names": [c.name for c in mapping.extra],
        "warnings": list(export.warnings),
        "notes": list(extra_notes),
    }
    if csv_path is not None:
        meta["output_csv"] = str(csv_path)
    if fe_check is not None:
        meta["fe_identity"] = fe_check
    if servo_check is not None:
        meta["servo_loader_check"] = servo_check
    return meta
