"""知识层真值回归：需求基线转写、品牌清单、P/Invoke 绑定必须与外部真值一致。

为什么单独一个文件：
    2026-10-20 复核需求基线来源时发现，**知识层的转写错误会一路污染下游**——
    「电子凸轮」被写成「电子齿轮」，于是覆盖审计报「无覆盖缺口」，
    而需求基线明写的电子凸轮其实一个工具都没有；「雷赛」被写成「菁赛」，
    于是品牌清单里少了做得最深的那一家。

    所以这里把「需求基线原文是什么」固化成可执行的断言：
    以后再有人改 requirements_map.json / cards.json，改错了这里会变红。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcopilot.agents import requirements  # noqa: E402
from mcopilot.core.util import knowledge_path, read_json  # noqa: E402

API = ROOT / "knowledge" / "sdks" / "official_api"

# 需求基线来源原文（招聘页 3 张截图 OCR 转写，2x/4x 放大二次确认）：
#   R-03「3.建立运动控制卡适配层，统一封装固高、雷赛、正运动、软赢、高川、ACS等品牌的SDK接口」
#   Q-04「4.精通至少两个品牌的运动控制卡开发，熟悉固高GTS/GSN/GEN卡、雷赛DMC/EMC系列运动控制卡、
#         正运动ZMC、软赢、高川、ACS中多家的API与调试工具」
#   Q-05「5.精通多轴联动控制：插补算法、电子凸轮、位置比较输出、飞拍、跟随误差补偿、回零与限位策略」
REQ_BRANDS = ["固高", "雷赛", "正运动", "软赢", "高川", "ACS"]


def _load_csv(name: str) -> list[dict]:
    with open(API / name, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _req_item(item_id: str) -> dict:
    data = read_json(knowledge_path("requirements_map.json"))
    for it in data["items"]:
        if it["id"] == item_id:
            return it
    raise KeyError(item_id)


# ------------------------------------------------------------------ 需求基线转写


def test_Q05_是电子凸轮不是电子齿轮():
    """需求基线原文是「电子凸轮」。电子齿轮与电子凸轮是完全不同的功能 ——
    写错会让覆盖审计漏报一个明确要求、却没有任何工具承接的能力缺口。"""
    title = _req_item("Q-05")["title"]
    assert "电子凸轮" in title
    assert "电子齿轮" not in title


def test_R03_品牌清单是雷赛不是菁赛():
    title = _req_item("R-03")["title"]
    assert "雷赛" in title
    assert "菁赛" not in title


def test_整份需求基线的条目正文里没有菁赛():
    """条目正文（title）必须是基线原文。注意 meta 里的修正说明会提到「菁赛」，
    那是记录这段错在哪儿的，不算条目内容。"""
    data = read_json(knowledge_path("requirements_map.json"))
    for it in data["items"]:
        assert "菁赛" not in it["title"], f"{it['id']} 的条目正文里出现了菁赛"
        for part in it.get("ai_part", []) + it.get("human_only", []):
            assert "菁赛" not in part, f"{it['id']} 的说明里出现了菁赛"


def test_R11_保留了专利软著申报且登记了已知缺口():
    """基线原文含「参与关键技术选型与专利、软著申报」；不能因为没工具就把它删掉。"""
    it = _req_item("R-11")
    assert "专利" in it["title"] and "软著" in it["title"]
    assert it.get("gap_note"), "有 AI 可承担部分但无工具承接的条目必须登记 gap_note"


def test_覆盖审计能报出已知缺口():
    """gap_note 的条目不能被「无覆盖缺口」一句话盖掉。"""
    data = requirements.analyze()
    cov = requirements.coverage(data)
    gap_ids = {g["id"] for g in cov["gap_items"]}
    assert "R-11" in gap_ids
    md = requirements.build_report(data, cov).to_markdown()
    assert "已登记的已知缺口" in md
    assert "R-11" in md.split("已登记的已知缺口")[1]


def test_每条有ai承担度的需求都有工具或登记了缺口():
    data = requirements.analyze()
    cov = requirements.coverage(data)
    gap_ids = {g["id"] for g in cov["gap_items"]}
    for it in data["items"]:
        if it["ai_share"] > 0:
            assert it["agents"] or it["id"] in gap_ids, (
                f"{it['id']} 有 AI 可承担部分，但既没有工具也没登记缺口")


def test_每个智能体都能追溯到需求条目():
    data = requirements.analyze()
    cov = requirements.coverage(data)
    assert cov["tools_without_requirement"] == []


def test_电子凸轮有工具承接():
    """这条是本轮补上的：Q-05 的电子凸轮必须有工具，不能只挂 motion_lab。"""
    assert "cam_lab" in _req_item("Q-05")["agents"]


# ------------------------------------------------------------------ 品牌清单


def test_能力矩阵的品牌清单与需求基线一致():
    cards = read_json(knowledge_path("cards.json"))
    assert cards["brands_in_scope"] == REQ_BRANDS


def test_菁赛被标为不在范围内而不是悄悄删掉():
    cards = read_json(knowledge_path("cards.json"))
    out = {c["brand"]: c for c in cards.get("out_of_scope_brands", [])}
    assert "菁赛" in out
    assert "雷赛" in out["菁赛"]["why_not_in_scope"]


def test_建了适配器的品牌必须都在需求基线品牌清单内():
    cards = read_json(knowledge_path("cards.json"))
    built = {c["brand"] for c in cards["cards"]}
    assert built <= set(cards["brands_in_scope"])


def test_能力矩阵里三家都有电子凸轮条目():
    cards = read_json(knowledge_path("cards.json"))
    for card in cards["cards"]:
        assert card.get("electronic_cam"), f"{card['brand']} 缺 electronic_cam 条目"


def test_跨品牌差异里有电子凸轮这一项():
    cards = read_json(knowledge_path("cards.json"))
    topics = {d["topic"] for d in cards["cross_brand_diffs"]}
    assert "电子凸轮" in topics


# ------------------------------------------------------------------ P/Invoke 与 DLL 真值


def test_zmotion绑定里没有DLL不导出的函数():
    """ZAux_GetTraceFile 在官方 C 头文件里声明了，但 zauxdll.dll 没导出它 ——
    绑上去 = 上机 EntryPointNotFoundException。"""
    sdk = read_json(knowledge_path("sdks/zmotion.json"))
    bound = {p["fn"] for p in sdk["pinvoke"]}
    assert "ZAux_GetTraceFile" not in bound
    exports = {r["函数名"].strip() for r in _load_csv("dll_exports.csv")
               if r["DLL"] == "zauxdll.dll"}
    assert "ZAux_GetTraceFile" not in exports
    # 但它确实在官方 C 头文件里 —— 所以这是个真问题，不是幻觉
    cpp = {r["函数名"] for r in _load_csv("zmotion_cpp.csv")}
    assert "ZAux_GetTraceFile" in cpp


def test_zmotion绑定里的每个函数都在DLL导出表里():
    """每条 P/Invoke 都必须有 PE 导出表背书。"""
    sdk = read_json(knowledge_path("sdks/zmotion.json"))
    exports: dict[str, set[str]] = {}
    for r in _load_csv("dll_exports.csv"):
        exports.setdefault(r["DLL"], set()).add(r["函数名"].strip())
    for p in sdk["pinvoke"]:
        entry = p.get("entry_point", p["fn"])
        assert entry in exports.get(sdk["dll"], set()), (
            f"{p['fn']} 在 {sdk['dll']} 的导出表里找不到")


def test_全部品牌的PInvoke都有DLL导出表背书():
    for sdk_file in ("dmc.json", "zmotion.json", "gts.json"):
        sdk = read_json(knowledge_path("sdks/" + sdk_file))
        exports: dict[str, set[str]] = {}
        for r in _load_csv("dll_exports.csv"):
            exports.setdefault(r["DLL"], set()).add(r["函数名"].strip())
        dll = sdk["dll"]
        for p in sdk.get("pinvoke", []):
            if p.get("skip_emit"):
                continue
            entry = p.get("entry_point", p["fn"])
            assert entry in exports.get(dll, set()), (
                f"{sdk_file}: {p['fn']} 在 {dll} 的导出表里找不到")
