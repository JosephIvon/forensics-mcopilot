"""运动卡适配层生成器（adapter_gen）。

干三件事，都是工业需求基线里明确要求的东西：
  1. 渲染**品牌能力矩阵**（R-03：「沉淀品牌能力差异与性能边界文档」）；
  2. 从厂商函数手册的 API 绑定生成 C# 适配器 + P/Invoke 声明（Q-04）；
  3. 生成**跨品牌契约测试**，让「换卡不改业务代码」这句话能在 CI 里被验证。

原则：工具不猜厂商行为。查不到的一律标 TODO[需核对厂商手册]，
并在能力矩阵里列成待办清单 —— 这比编一个看起来像真的函数有用得多。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..core.report import Report, callout
from ..core.util import KNOWLEDGE_DIR, fmt, knowledge_path, md_table, read_json, write_cs, write_text

TEMPLATE_DIR = KNOWLEDGE_DIR / "templates"
SDK_DIR = KNOWLEDGE_DIR / "sdks"

_BODY_OPS = ["Open", "Close", "Enable", "IsEnabled", "MoveAbs", "MoveRel", "MoveLinear",
             "MoveArc", "Jog", "Stop", "Home", "GetPositionMm", "GetFeedbackMm", "HasRealFeedback",
             "IsMoving", "IsMotionDone", "GetStopReason", "GetStopReasonText", "GetState",
             "ReadInput", "WriteOutput", "SetCompareOutput", "SetLatch", "SetPulsePerMm",
             "GetPulsePerMm"]

# C# 关键字：厂商手册里的参数名（in / out / ref / event …）直接搬过来会生成编不过的代码。
# 踩过：ZAux_Direct_SetDatumIn 的参数名 in → `int in` 语法错误。
_CSHARP_KEYWORDS = {
    "abstract", "as", "base", "bool", "break", "byte", "case", "catch", "char", "checked",
    "class", "const", "continue", "decimal", "default", "delegate", "do", "double", "else",
    "enum", "event", "explicit", "extern", "false", "finally", "fixed", "float", "for",
    "foreach", "goto", "if", "implicit", "in", "int", "interface", "internal", "is", "lock",
    "long", "namespace", "new", "null", "object", "operator", "out", "override", "params",
    "private", "protected", "public", "readonly", "ref", "return", "sbyte", "sealed",
    "short", "sizeof", "stackalloc", "static", "string", "struct", "switch", "this", "throw",
    "true", "try", "typeof", "uint", "ulong", "unchecked", "unsafe", "ushort", "using",
    "virtual", "void", "volatile", "while",
}


def _fill(template: str, mapping: dict[str, str]) -> str:
    out = template
    for k, v in mapping.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def _indent(lines: list[str], spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + ln.strip() for ln in lines if ln.strip() != "" or True) if lines else ""


# ------------------------------------------------------------------ P/Invoke


def render_pinvoke(sdk: dict) -> str:
    conv = sdk.get("calling_convention", "StdCall")
    out: list[str] = []
    for f in sdk.get("pinvoke", []):
        if f.get("skip_emit"):
            continue
        args = []
        for a in f.get("args", []):
            t = a["type"]
            if a.get("is_ref"):
                t = "ref " + t
            name = a["name"]
            if name in _CSHARP_KEYWORDS:
                raise ValueError(
                    f"{sdk['vendor']}.{f['fn']} 的参数名 '{name}' 是 C# 关键字，"
                    "会生成编不过的代码 —— 请在 knowledge/sdks 里改名（EntryPoint 不受影响）")
            args.append(f"{t} {name}")
        entry = f.get("entry_point", f["fn"])
        out.append(f'        /// <summary>{f.get("doc", "")}</summary>')
        if f.get("verified") == "needs-manual-check":
            out.append(f'        // TODO[需核对厂商手册] {f["fn"]} 的签名与语义')
        out.append(f'        [DllImport("{sdk["dll"]}", EntryPoint = "{entry}", '
                   f'CallingConvention = CallingConvention.{conv})]')
        out.append(f'        public static extern {f["ret"]} {f["fn"]}({", ".join(args)});')
        out.append("")
    return "\n".join(out)


# ------------------------------------------------------------------ 适配器


def render_adapter(sdk: dict) -> str:
    tpl = (TEMPLATE_DIR / "adapter.cs.tmpl").read_text(encoding="utf-8")
    mapping = {
        "VENDOR": sdk["vendor"],
        "MODEL": sdk.get("model", ""),
        "INTERFACE": sdk.get("interface", ""),
        "DLL": sdk["dll"],
        "NAMESPACE": sdk["namespace"],
        "CLASS": sdk["class_name"],
        "CARD_TYPE": sdk.get("card_type", "0"),
        "AXIS_COUNT": str(sdk.get("axis_count", 4)),
        "SDK_FILE": sdk.get("sdk_file", ""),
        "PINVOKE": render_pinvoke(sdk),
    }
    bodies = sdk.get("bodies", {})
    for op in _BODY_OPS:
        lines = bodies.get(op, ["throw new NotSupportedException(\"该品牌适配器未实现此操作\");"])
        mapping[f"BODY:{op}"] = _indent(lines, 12)
    helpers = sdk.get("helpers", {})
    helper_text = []
    for name, lines in helpers.items():
        helper_text.append(_indent(lines, 8))
    mapping["HELPERS"] = "\n\n".join(helper_text)
    return _fill(tpl, mapping)


# ------------------------------------------------------------------ 静态模板产物


def render_interface() -> str:
    return (TEMPLATE_DIR / "IMotionController.cs.tmpl").read_text(encoding="utf-8")


def render_simulator() -> str:
    return (TEMPLATE_DIR / "SimulatedMotionController.cs.tmpl").read_text(encoding="utf-8")


def render_contract_tests() -> str:
    return (TEMPLATE_DIR / "ContractTests.cs.tmpl").read_text(encoding="utf-8")


def render_self_check() -> str:
    return (TEMPLATE_DIR / "SelfCheck.cs.tmpl").read_text(encoding="utf-8")


# ------------------------------------------------------------------ 能力矩阵


# form_factor 取值 → 能力矩阵里的中文标签
FORM_FACTOR_LABELS = {
    "plug_in_card": "插卡（PCIe 板卡，PC 直驱）",
    "standalone_controller": "独立式控制器（整机，主机走通信库）",
    "soft_master": "软主站（跑在主机里，不占额外硬件）",
}


def _card_value(card: dict, key: str) -> str:
    if key == "form_factor":
        return FORM_FACTOR_LABELS.get(card.get("form_factor"), "—")
    return str(card.get(key, "—"))


def _matrix_rows(cards: list[dict]) -> str:
    fields = [("form_factor", "产品形态"), ("interface", "接口形态"),
              ("position_unit", "位置单位"),
              ("feedback_truth", "反馈真伪"),
              ("velocity_unit", "速度单位"), ("interpolation", "插补"),
              ("position_compare", "硬件比较输出"), ("position_latch", "位置锁存"),
              ("speed_profile", "速度曲线"), ("max_pulse_freq", "最大脉冲频率"),
              ("io", "IO"), ("axis_state", "轴状态")]
    headers = ["项"] + [c["brand"] for c in cards]
    rows = []
    for key, label in fields:
        rows.append([label] + [_card_value(c, key) for c in cards])
    return md_table(headers, rows)


def build_matrix_report(out_dir: Path) -> Report:
    data = read_json(knowledge_path("cards.json"))
    cards = data["cards"]
    pending = data.get("pending_brands", [])

    rep = Report(
        title="运动控制卡能力矩阵",
        subtitle="需求 R-03 明确要求沉淀的文档　|　"
                 "口径：official-manual/official-binding = 来自厂商官方手册或官方 SDK 绑定（可逐行核对）；"
                 "public-doc = 来自公开厂商资料；needs-manual-check = 必须查厂商函数手册",
        meta={
            "范围内品牌": "、".join(data["brands_in_scope"]),
            "已覆盖品牌": f"{len(cards)}/{data['brands_total']}",
            "待录入品牌": "、".join(p["brand"] for p in pending) or "无",
        },
    )

    rep.add("这张表解决什么问题", "\n".join([
        "同一套上位机代码要跑在不同品牌的卡上时，真正会出事的从来不是「能不能动」，"
        "而是**单位口径、能力缺口、错误语义**这三件事。",
        "下面这张表把每家的口径摆在一起；"
        "**只要业务层坚持只用 mm/s，这张表里的差异就全部被挡在适配层内部。**",
    ]))

    rep.add("能力矩阵", _matrix_rows(cards))

    # 跨品牌差异表的列跟着 cards 走（新增品牌只需在 cards.json 里加一行 + 在差异里加一个 key）。
    diff_keys = [c.get("key", c["brand"]) for c in cards]
    rep.add("跨品牌关键差异（换卡最容易翻车的地方）", "\n".join([
        md_table(["议题"] + [c["brand"] for c in cards] + ["风险", "怎么规避"],
                 [[d["topic"]] + [d.get(k, "—") for k in diff_keys] +
                 [d["risk"], d["how_to_avoid"]] for d in data["cross_brand_diffs"]]),
        "",
        callout("高", "**特别提醒速度单位**：雷赛用 pulse/s，正运动用 单位/秒（由 UNITS 决定），"
                      "固高用 **pulse/ms**（比 pulse/s 小 1000 倍）。"
                      "换卡时把速度参数照抄，节拍可能直接差 1000 倍 —— "
                      "而且机器不会报错，只会「慢得离谱」。"),
    ]))

    brand_blocks: list[str] = []
    for c in cards:
        blk = [f"**{c['brand']}（{c['model']}）**",
               f"- 优势：{c.get('strength', '—')}",
               f"- 边界：{c.get('boundary', '—')}"]
        blk += [f"- ⚠ {e}" for e in c.get("edge_cases", [])]
        blk.append("")
        brand_blocks.append("\n".join(blk))
    rep.add("每个品牌的边界与坑", "\n".join(brand_blocks))

    # 待录入品牌清单
    if pending:
        rep.add("待录入品牌清单（拿厂商手册就能补齐）", "\n".join([
            f"需求基线覆盖 {data['brands_total']} 个品牌，目前有据可查的已覆盖 {len(cards)} 个。剩下的请按下面清单补：",
            "",
            md_table(["品牌", "型号系列", "资料来源", "需补齐字段"],
                     [[p["brand"], p.get("family", "—"), p["source_hint"], "、".join(p["fields"])]
                      for p in pending]),
            "",
            callout("提示", "补齐方式：把厂商函数手册/SDK 头文件里的对应函数填进 "
                            "`knowledge/sdks/<品牌>.json`，然后跑 "
                            "`mcopilot adapter gen --sdk <品牌>`，适配器与本矩阵会一起更新。"),
        ]))

    # TODO 清单
    todos = []
    for sdk_file in sorted(SDK_DIR.glob("*.json")):
        sdk = read_json(sdk_file)
        for f in sdk.get("pinvoke", []):
            if f.get("verified") == "needs-manual-check" and not f.get("skip_emit"):
                todos.append([sdk["vendor"], f["fn"], f.get("doc", "")])
    if todos:
        rep.add("适配器中的待核对项（TODO 清单）", "\n".join([
            "下列函数在生成代码里已标 `TODO[需核对厂商手册]`。"
            "**它们不是「已完成的功能」，是「明确的缺口」** —— 工具宁可留白，也不给你一个看起来能用其实会出事的实现。",
            "",
            md_table(["品牌", "函数", "用途"], todos),
            "",
            callout("中", "把缺口显式化（抛 `NotSupportedException`）比提供一个错误实现更有价值："
                          "业务层会立刻知道这个卡不支持，而不是在产线上慢慢发现。"),
        ]))

    # 必须问厂商/FAE 的清单
    manual = data.get("pending_manual_items", [])
    if manual:
        rep.add("必须问厂商 / FAE 的清单", "\n".join([
            "下面这些**不是「没查」**，是公开资料里查不到、但必须拿到才能写对的部分。",
            "每条都写清了「卡住什么」—— 拿不到就保持显式失败，比猜一个「看起来能跑」的实现安全。",
            "",
            md_table(["品牌", "待确认项", "为什么必须问", "具体怎么问", "卡住什么"],
                     [[m["brand"], m["item"], m["why"], m["ask"], m.get("blocks", "—")] for m in manual]),
            "",
            callout("高", "这份清单可以直接转给销售/FAE。**一次问齐，别来回挤牙膏** —— "
                          "每个来回都是一周工期，而这些问题只影响代码里的哪一段，上面已经标死了。"),
        ]))

    return rep


# ------------------------------------------------------------------ 入口


def run_gen(sdk_name: str, out_dir: Path) -> dict[str, Any]:
    sdk_path = SDK_DIR / f"{sdk_name}.json"
    if not sdk_path.exists():
        avail = ", ".join(p.stem for p in sorted(SDK_DIR.glob("*.json")))
        raise SystemExit(f"未找到 SDK 绑定 '{sdk_name}'。可用：{avail}")
    sdk = read_json(sdk_path)
    sdk["sdk_file"] = sdk_path.name

    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    # C# 源码一律带 UTF-8 BOM（见 util.write_cs 的说明）
    written["interface"] = write_cs(out_dir / "IMotionController.cs", render_interface())
    written["simulator"] = write_cs(out_dir / "SimulatedMotionController.cs", render_simulator())
    written["contract_tests"] = write_cs(out_dir / "MotionContractTests.cs", render_contract_tests())
    written["self_check"] = write_cs(out_dir / "MotionSelfCheck.cs", render_self_check())
    written["adapter"] = write_cs(
        out_dir / f"{sdk['class_name']}.cs", render_adapter(sdk))
    return {"written": written, "sdk": sdk}


def run_matrix(out_dir: Path, stem: str = "card_capability") -> dict[str, Any]:
    rep = build_matrix_report(out_dir)
    return {"report": rep}
