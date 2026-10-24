# -*- coding: utf-8 -*-
"""守卫电子凸轮这一块的外部真值表述。

起因（2026-10-20）
------------------
`knowledge/cam_rules.json` 的 `dll_exported_not_in_csharp_binding` 列了 9 个符号，
说是「在 LTDMC.dll 的 PE 导出表里存在，但不在官方 C# 绑定里」。
逐条对 `knowledge/sdks/official_api/leisai.csv` 核对后：**7 个是错报**
（`dmc_cam_add_tappet` / `dmc_cam_in` / `dmc_cam_read_tappet_status` /
`dmc_cam_read_tappet_value` / `dmc_cam_write_tappet_value` /
`dmc_cam_read_points_packet` / `dmc_cam_write_points_packet` **都在官方托管绑定里**），
真正缺托管签名的只有**单数**版 `dmc_cam_read_point` / `dmc_cam_write_point`。
`knowledge/cards.json` 里也重复了同一处不准确说法。

这类错误的危害是**双向**的：
  · 说「不在」→ 以为官方没给签名，白手抄一遍 C 头文件，抄错就是运行期 EntryPointNotFound
  · 说「在」→ 以为有托管签名就直接调，真机上没有 → 一样炸
所以必须由**真值 CSV 自动判定**，不能靠人写。

本测试做集合相等：名单 == 「PE 导出表里有、官方 C# 绑定里没有、且是凸轮相关」的实际集合。
"""
from __future__ import annotations

import csv
import io
import json
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
API = os.path.join(ROOT, "knowledge", "sdks", "official_api")

# 与电子凸轮同名但不是电子凸轮的（相机吹气 / 飞拍排序）
CAM_EXCLUDE = ("camerablow", "sorting_", "d5480_", "smc_cam")


def _read_csv(name):
    path = os.path.join(API, name)
    if not os.path.isfile(path):
        pytest.skip("缺真值文件 %s" % name)
    out = {}
    with io.open(path, encoding="utf-8-sig", newline="") as fh:
        for i, r in enumerate(csv.DictReader(fh), 2):
            fn = (r.get("函数名") or "").strip()
            if fn:
                out[fn] = i
    return out


def _is_cam(name):
    low = name.lower()
    if "cam" not in low:
        return False
    return not any(bad in low for bad in CAM_EXCLUDE)


def _is_decorated(name):
    """stdcall 装饰名（`_foo@44`）—— 是同一个函数的别名，不是另一个函数。"""
    return name.startswith("_") and "@" in name


@pytest.fixture(scope="module")
def cam_truth():
    cs = _read_csv("leisai.csv")
    hdr = _read_csv("leisai_cpp.csv")
    exported = set()
    path = os.path.join(API, "dll_exports.csv")
    with io.open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("DLL") or "").strip() == "LTDMC.dll":
                exported.add((r.get("函数名") or "").strip())
    return cs, hdr, exported


def test_listed_symbols_are_exactly_the_missing_ones(cam_truth):
    cs, hdr, exported = cam_truth
    with io.open(os.path.join(ROOT, "knowledge", "cam_rules.json"), encoding="utf-8") as fh:
        rules = json.load(fh)
    leisai = rules["vendors"]["雷赛"]
    listed = set(leisai.get("dll_exported_not_in_csharp_binding", []))

    # 实际「导出了但官方托管绑定没有」的凸轮相关符号（排除 stdcall 装饰别名）
    actual = {n for n in exported
              if _is_cam(n) and n not in cs and not _is_decorated(n)}

    assert listed == actual, (
        "cam_rules.json 的 dll_exported_not_in_csharp_binding 与真值对不上：\n"
        "  名单多出来（其实在官方 C# 绑定里）：%s\n"
        "  名单漏掉（其实不在官方 C# 绑定里）：%s"
        % (sorted(listed - actual), sorted(actual - listed))
    )


def test_listed_symbols_do_have_a_c_prototype(cam_truth):
    """说「官方没给托管签名」的符号，至少要在官方 C 头文件里有原型可抄。"""
    cs, hdr, exported = cam_truth
    with io.open(os.path.join(ROOT, "knowledge", "cam_rules.json"), encoding="utf-8") as fh:
        rules = json.load(fh)
    listed = rules["vendors"]["雷赛"].get("dll_exported_not_in_csharp_binding", [])
    missing = [s for s in listed if s not in hdr]
    assert not missing, f"这些符号连官方 C 头文件里都没有原型，抄不出来：{missing}"


def test_cards_json_does_not_claim_missing_symbols_exist_in_binding(cam_truth):
    """cards.json 里不能把「官方绑定里没有的符号」说成「官方绑定里有」。"""
    cs, hdr, exported = cam_truth
    with io.open(os.path.join(ROOT, "knowledge", "cards.json"), encoding="utf-8") as fh:
        cards = json.load(fh)
    blob = json.dumps(cards, ensure_ascii=False)
    # 只查明确声称「官方 LTDMC.cs 里有 ...」的那一句
    for m in re.finditer(r"官方\s*LTDMC\.cs\s*里有([^。\"]+)", blob):
        frag = m.group(1)
        for sym in re.findall(r"dmc_[a-z_]+", frag):
            if sym not in cs:
                raise AssertionError(
                    "cards.json 声称「官方 LTDMC.cs 里有 %s」，但它在官方 C# 绑定里查不到" % sym
                )


def test_cam_capability_table_matches_truth(cam_truth):
    """cam_rules.json 里「谁能整表下发」的说法要与真值一致。"""
    cs, hdr, exported = cam_truth
    with io.open(os.path.join(ROOT, "knowledge", "cam_rules.json"), encoding="utf-8") as fh:
        rules = json.load(fh)
    v = rules["vendors"]
    # 雷赛：原生凸轮表 + 能整表下发
    assert v["雷赛"]["native_cam_table"] is True
    assert v["雷赛"]["table_upload_from_host"] is True
    assert v["雷赛"].get("table_upload_api")
    # 正运动：凸轮在控制器侧，上位机不整表下发
    assert v["正运动"]["native_cam_table"] is True
    assert v["正运动"]["table_upload_from_host"] is False
    # 固高：没有凸轮
    assert v["固高"]["native_cam_table"] is False
    assert v["固高"]["table_upload_from_host"] is False
    # 整表下发的入口函数确实在官方 C# 绑定里
    api = v["雷赛"]["table_upload_api"]
    assert api in cs, f"雷赛整表下发入口 {api} 不在官方 C# 绑定里"
