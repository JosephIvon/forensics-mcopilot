"""通用工具：路径、统计、格式化。刻意不引入第三方依赖。"""

from __future__ import annotations

import base64
import json
import math
import os
import re
import statistics
from pathlib import Path
from typing import Any, Iterable, Sequence

# ---------------------------------------------------------------- 路径
#
# **数据契约（本仓的架构，不是约定）**
#
# 这个仓是「仓库即交付物」：工具（`src/mcopilot/`）、真值基座（`knowledge/`）、
# 电子书（`book/`）是**同一个可核验单元**——
#   · 真值基座既是运行时数据（工具读它出结论）；
#   · 又是被审证据（`knowledge/protocols/anchors.json` 记着厂商原件的 sha256）；
#   · 还是书里引用的锚点（`book/` 的坐标全部指向它）；
#   · 并且它自己还指向**仓外**的厂商原件（`../mcopilot-external/`）。
# 轮子（wheel）装不下这一层关系，所以**分发单元是仓库，不是 wheel**。
#
# 因此这里**不假定"包在仓库里的哪个固定位置"**，而是按顺序把仓库根找出来：
#   1) 环境变量 `MCOPILOT_ROOT` —— 显式覆盖，优先级最高；
#   2) 从包目录向上找带 `knowledge/` 的祖先 —— 源码签出布局（`src/mcopilot` 的上面两层）；
#   3) 装成 wheel 且真值基座随包分发时，包在 `site-packages/` 下，基座在其同级。
# 找不到就报一条**能照着做**的错，而不是把 `FileNotFoundError` 甩给使用者。

PKG_DIR = Path(__file__).resolve().parents[1]  # .../src/mcopilot

_ROOT_HINT = (
    "找不到真值基座（knowledge/）。本仓的分发单元是**仓库**，不是独立的 wheel——"
    "真值基座与代码同仓、互为证据，且指向仓外的厂商原件，装不进一个 wheel。\n"
    "  照着做（任选其一）：\n"
    "    1) 在仓库里跑：          set PYTHONPATH=src  然后  python -m mcopilot all --out out\n"
    "    2) 装成可编辑安装：      pip install -e .\n"
    "    3) 显式指定仓库根：      set MCOPILOT_ROOT=D:\\path\\to\\forensics-mcopilot"
)


def _looks_like_repo_root(cand: Path) -> bool:
    """仓库根的判据：带真值基座。真值基座是这套架构的锚，不是随包的普通数据。"""
    return (cand / "knowledge").is_dir()


def _resolve_root() -> Path:
    env = os.environ.get("MCOPILOT_ROOT")
    if env:
        p = Path(env).expanduser()
        try:
            p = p.resolve()
        except OSError:  # pragma: no cover - 极端路径
            pass
        if not _looks_like_repo_root(p):
            raise RuntimeError(
                f"MCOPILOT_ROOT 指向的目录没有真值基座：{p}\n  （应当含 knowledge/）"
            )
        return p
    for cand in PKG_DIR.parents:
        if _looks_like_repo_root(cand):
            return cand
    raise RuntimeError(_ROOT_HINT)


ROOT_DIR = _resolve_root()
KNOWLEDGE_DIR = ROOT_DIR / "knowledge"
SAMPLES_DIR = ROOT_DIR / "samples"
DEFAULT_OUT_DIR = ROOT_DIR / "out"


def knowledge_path(name: str) -> Path:
    return KNOWLEDGE_DIR / name


def sample_path(*parts: str) -> Path:
    return SAMPLES_DIR.joinpath(*parts)


def ensure_out_dir(path: str | os.PathLike | None = None) -> Path:
    out = Path(path) if path else DEFAULT_OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    return out


def read_json(path: str | os.PathLike) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: str | os.PathLike, data: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return p


def write_text(path: str | os.PathLike, text: str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return p


def write_cs(path: str | os.PathLike, text: str) -> Path:
    """写 C# 源码：必须带 UTF-8 BOM。

    MSBuild / csc 对**无 BOM** 的源文件按系统 ANSI 码页读（中文 Windows 是 GBK），
    中文注释和字符串会被解码坏 —— 表现为一堆看不懂的语法错误（我们踩过：
    `public string Vendor => "正运动";` 直接编不过）。
    带 BOM 时编译器才认 UTF-8。用户拿 VS / dotnet build 编译时同样受益。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8-sig", newline="\n") as fh:
        fh.write(text)
    return p


# ---------------------------------------------------------------- 统计

def mean(xs: Sequence[float]) -> float:
    return statistics.fmean(xs) if xs else float("nan")


def median(xs: Sequence[float]) -> float:
    return statistics.median(xs) if xs else float("nan")


def stdev(xs: Sequence[float]) -> float:
    return statistics.stdev(xs) if len(xs) > 1 else 0.0


def percentile(xs: Sequence[float], q: float) -> float:
    """线性插值分位数，q 取 0~1。"""
    if not xs:
        return float("nan")
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * min(max(q, 0.0), 1.0)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return s[int(pos)]
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 2:
        return float("nan")
    xs, ys = xs[:n], ys[:n]
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return float("nan")
    return num / (dx * dy)


def point_biserial(binary: Sequence[int], values: Sequence[float]) -> float:
    """二值变量与连续变量的点二列相关（等价于皮尔逊）。"""
    return pearson([float(b) for b in binary], list(values))


def capability_indices(usl: float, lsl: float, xbar: float, sigma: float) -> dict:
    if sigma <= 0:
        return {"cp": float("nan"), "cpk": float("nan"), "verdict": "不可判定"}
    cp = (usl - lsl) / (6.0 * sigma)
    cpk = min(usl - xbar, xbar - lsl) / (3.0 * sigma)
    if cpk < 1.0:
        verdict = "不合格（过程能力不足）"
    elif cpk < 1.33:
        verdict = "待改善（勉强）"
    else:
        verdict = "合格"
    return {"cp": cp, "cpk": cpk, "verdict": verdict}


def moving_range(xs: Sequence[float]) -> list[float]:
    return [abs(xs[i] - xs[i - 1]) for i in range(1, len(xs))]


def cusum(values: Sequence[float], threshold: float = 1.0) -> list[dict]:
    """双侧 CUSUM 变点检测，返回每个点是否触发。"""
    if not values:
        return []
    xbar = mean(values)
    sigma = stdev(values) or 1e-9
    g_hi = g_lo = 0.0
    marks = []
    for v in values:
        g_hi = max(0.0, g_hi + (v - xbar) / sigma - 0.5)
        g_lo = max(0.0, g_lo - (v - xbar) / sigma - 0.5)
        flags = []
        if g_hi > threshold:
            flags.append("上偏")
        if g_lo > threshold:
            flags.append("下偏")
        marks.append({"value": v, "g_hi": g_hi, "g_lo": g_lo, "shift": bool(flags), "direction": "、".join(flags)})
    return marks


# ---------------------------------------------------------------- 格式化

def fmt(x: Any, digits: int = 4) -> str:
    if x is None:
        return "-"
    if isinstance(x, float):
        if math.isnan(x):
            return "NaN"
        if math.isinf(x):
            return "Inf"
        if x == int(x) and abs(x) < 1e15:
            return str(int(x))
        return f"{x:.{digits}f}"
    return str(x)


def slug(text: str) -> str:
    s = re.sub(r"[^\w一-鿿-]+", "-", text).strip("-")
    return s or "item"


def md_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    out = ["| " + " | ".join(str(h) for h in headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def img_b64(path: str | os.PathLike) -> str:
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


HTML_STYLE = """
body{font-family:"Microsoft YaHei","PingFang SC",-apple-system,"Segoe UI",sans-serif;
     line-height:1.65;color:#1f2328;background:#fff;max-width:1180px;margin:0 auto;padding:28px 24px}
h1{border-bottom:2px solid #d0d7de;padding-bottom:.3em}
h2{border-bottom:1px solid #d8dee4;padding-bottom:.2em;margin-top:1.6em}
h3{margin-top:1.3em}
code,pre{background:#f6f8fa;border-radius:6px;font-family:Consolas,"Cascadia Mono",monospace}
code{padding:.15em .35em;font-size:.9em}
pre{padding:12px;overflow:auto}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:.92em}
th,td{border:1px solid #d0d7de;padding:6px 10px;text-align:left;vertical-align:top}
th{background:#f6f8fa}
tr:nth-child(2n){background:#fafbfc}
img{max-width:100%;border:1px solid #d8dee4;border-radius:6px;margin:8px 0}
.high{background:#fff3cd;border-left:4px solid #d4a72c;padding:8px 12px;margin:10px 0}
.mid{background:#e7f1ff;border-left:4px solid #4a90d9;padding:8px 12px;margin:10px 0}
.low{background:#e9f7ef;border-left:4px solid #2f9e44;padding:8px 12px;margin:10px 0}
.crit{background:#ffe8e8;border-left:4px solid #d64545;padding:8px 12px;margin:10px 0}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:.82em;font-weight:600}
.b-high{background:#ffe3e3;color:#b02a2a}.b-mid{background:#fff3cd;color:#8a6d0b}.b-low{background:#e3f6e8;color:#1e7e34}
.muted{color:#656d76;font-size:.9em}
"""


def md_to_html(md_text: str, title: str = "报告", images: Sequence[Path] = ()) -> str:
    """够用的 Markdown → HTML。只支持标题/表格/列表/代码块/图片/粗体，够报告用。"""
    lines = md_text.splitlines()
    html: list[str] = []
    in_code = False
    in_table = False
    in_list = False

    def close_blocks() -> None:
        nonlocal in_code, in_table, in_list
        if in_code:
            html.append("</pre>")
            in_code = False
        if in_table:
            html.append("</table>")
            in_table = False
        if in_list:
            html.append("</ul>")
            in_list = False

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("```"):
            close_blocks()
            if in_code:
                pass
            else:
                html.append("<pre>")
            in_code = not in_code
            continue
        if in_code:
            html.append(_esc(line))
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            if not in_table:
                close_blocks()
                html.append("<table>")
                in_table = True
                html.append("<tr>" + "".join(f"<th>{_inline(c)}</th>" for c in cells) + "</tr>")
            else:
                html.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
            continue
        close_blocks()
        if not line.strip():
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            lvl = len(m.group(1))
            html.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            continue
        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{_inline(m.group(1))}</li>")
            continue
        if re.match(r"^\s*\d+\.\s+", line):
            text = re.sub(r"^\s*\d+\.\s+", "", line)
            html.append(f"<p>{_inline(text)}</p>")
            continue
        if line.startswith("!["):
            m2 = re.match(r"^!\[(.*?)\]\((.*?)\)$", line)
            if m2:
                html.append(f'<img alt="{_esc(m2.group(1))}" src="{_esc(m2.group(2))}">')
            continue
        if line.startswith("> "):
            html.append(f"<blockquote>{_inline(line[2:])}</blockquote>")
            continue
        html.append(f"<p>{_inline(line)}</p>")
    close_blocks()
    return (f"<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            f"<title>{_esc(title)}</title><style>{HTML_STYLE}</style></head><body>"
            + "\n".join(html) + "</body></html>")


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _inline(text: str) -> str:
    out = _esc(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", out)
    out = re.sub(r"!\[(.*?)\]\((.*?)\)", r'<img alt="\1" src="\2">', out)
    return out
