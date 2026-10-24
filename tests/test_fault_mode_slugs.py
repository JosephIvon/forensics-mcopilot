# -*- coding: utf-8 -*-
"""守住 C3 硬规则 3：`fault_mode` 必须是 KB0 §2 的 slug 原样字符串。

规则原文（axiscope `docs/kb/KB0-conventions.md` §2）：

> 归因三大族（C3 硬性规则 8）
>   - `mechanical_*`：8 个
>   - `electrical_*`：7 个
>   - `software_induced_*`：7 个

C3 的硬规则是「**不许臆造 slug**」——`fault_mode` 只能取自 KB0 的 slug 原样字符串。
这条有两个方向：
  · **不许多**：编一个不存在的 slug 出来（更常见、也更危险）
  · **不许少**：漏掉一个合法 slug（导致该族永远无法被归因）

所以本测试做**集合相等**，不是包含。

**权威源是 axiscope 的 KB0**，不在本仓库里 —— 所以读不到就跳过（skip，不是静默通过）。
可用环境变量 `AXISCOPE_KB0` 指向别处的 KB0。
"""
from __future__ import annotations

import io
import json
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RULES = os.path.join(ROOT, "knowledge", "servo_rules.json")

# axiscope 仓的 KB0：环境变量 AXISCOPE_DIR 优先，其次按同级兄弟目录找
_AXIS = os.environ.get("AXISCOPE_DIR") or os.path.join(os.path.dirname(ROOT), "axiscope")
DEFAULT_KB0 = os.path.join(_AXIS, "docs", "kb", "KB0-conventions.md")

# KB0 里出现过、但**不是** fault_mode slug 的字符串（族级标签 / KB6 域解释项）
NOT_SLUGS = {
    "software_induced_error",              # 族级标签，只能出现在 family 键上
    "mechanical_axis_straightness_error",  # KB6 龙门/标定域解释项
    "mechanical_pitch_yaw_wobble",         # KB6 角度侧解释项
}


@pytest.fixture(scope="module")
def kb0_slugs():
    path = os.environ.get("AXISCOPE_KB0", DEFAULT_KB0)
    if not os.path.isfile(path):
        pytest.skip("找不到 axiscope 的 KB0（%s）；设 AXISCOPE_KB0 指向它" % path)
    with io.open(path, encoding="utf-8") as fh:
        text = fh.read()
    # 只取 §2 那一节
    m = re.search(r"^##\s*2\b.*?$", text, re.M)
    if not m:
        pytest.skip("KB0 里找不到 §2 标题")
    rest = text[m.end():]
    nxt = re.search(r"^##\s*3\b", rest, re.M)
    sec = rest[: nxt.start()] if nxt else rest
    slugs = set(re.findall(r"`([a-z][a-z0-9_]*)`", sec))
    slugs = {s for s in slugs if s.startswith(("mechanical_", "electrical_", "software_induced_"))}
    slugs -= NOT_SLUGS
    if not slugs:
        pytest.skip("KB0 §2 里没解析出 slug")
    return slugs


@pytest.fixture(scope="module")
def rule_slugs():
    with io.open(RULES, encoding="utf-8") as fh:
        d = json.load(fh)
    return set(d.get("fault_modes", {}))


def test_counts_match_kb0(kb0_slugs):
    assert len(kb0_slugs) == 22, "KB0 §2 的 slug 数变了（%d 个）—— 知识层更新了，测试要跟着更新" % len(kb0_slugs)
    fams = {}
    for s in kb0_slugs:
        fams[s.split("_")[0] if not s.startswith("software_induced_") else "software_induced"] = \
            fams.get(s.split("_")[0] if not s.startswith("software_induced_") else "software_induced", 0) + 1
    assert fams == {"mechanical": 8, "electrical": 7, "software_induced": 7}, fams


def test_fault_modes_exactly_equal_kb0(kb0_slugs, rule_slugs):
    extra = sorted(rule_slugs - kb0_slugs)
    missing = sorted(kb0_slugs - rule_slugs)
    assert not extra, f"这些 fault_mode 在 KB0 §2 里不存在（臆造 slug）：{extra}"
    assert not missing, f"KB0 §2 里这些 slug 没被实现：{missing}"


def test_no_rule_uses_out_of_set_slug(rule_slugs):
    with io.open(RULES, encoding="utf-8") as fh:
        d = json.load(fh)
    for r in d.get("rules", []):
        fm = r.get("fault_mode")
        if fm:
            assert fm in rule_slugs, f"{r.get('id')} 的 fault_mode={fm} 不在 slug 集内"


def test_families_are_all_present(rule_slugs):
    with io.open(RULES, encoding="utf-8") as fh:
        d = json.load(fh)
    fams = {v.get("family") for v in d.get("fault_modes", {}).values()}
    assert fams == {"mechanical", "electrical", "software_induced"}, fams


def test_display_name_present_and_distinct(rule_slugs):
    with io.open(RULES, encoding="utf-8") as fh:
        d = json.load(fh)
    fm = d.get("fault_modes", {})
    for slug, v in fm.items():
        assert v.get("display_name"), f"{slug} 缺 display_name"
    names = [v.get("display_name") for v in fm.values()]
    assert len(set(names)) == len(names), "有 slug 复用了同一个 display_name"
