# -*- coding: utf-8 -*-
"""真值桥的常驻守卫：Trae 生成器知识库的真值行号引用必须一直对得上。

背景
----
Trae 的 `gen/adapters_kb.js` 是**手抄**的官方真值 —— 函数原型与出处写死在
`chk: '官方原型 GT_Open(...)（gts.csv:326 / gts_hdr.csv:398）'` 这种散文里，
生成器从不读 `official_api/` 下的 CSV。没人管的话，真值 CSV 一改引用就悄悄过期。

这里的守卫跑 `scripts/verify_traekb_citations.py`（同一套逻辑），
要求 **0 失配**，并额外断言两条已经发生过、不能重犯的教训：

1. **同族宏外溢**：固高回零 mode 一度只列 4 个（10/20/22/30），
   把官方表里 11/12/13 与 40/41 藏住了 —— 读者按引用范围找不到它们。
2. **宏语义未背书要自己标注**：`MC_GPI`/`MC_GPO` 与 diType/doType 的对应关系
   真值里查不到，KB 必须自己写明「待手册确认」，不许装作已背书。

Trae 目录不在本仓库里 —— 找不到就跳过（skip，不静默通过）。
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "scripts", "verify_traekb_citations.py")
# trae_factory 仓的位置：环境变量 TRAE_FACTORY_DIR 优先，其次按同级兄弟目录找
def _sib_trae():
    base = os.path.dirname(ROOT)
    for n in ("forensics-code-factory", "trae_factory"):
        p = os.path.join(base, n)
        if os.path.isdir(p):
            return p
    return os.path.join(base, "forensics-code-factory")


_TRAE = os.environ.get("TRAE_FACTORY_DIR") or _sib_trae()
DEFAULT_KB = os.path.join(_TRAE, "gen", "adapters_kb.js")


def _run():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, SCRIPT, "--kb", DEFAULT_KB],
                       cwd=ROOT, env=env, capture_output=True, text=True,
                       encoding="utf-8")
    return r


@pytest.fixture(scope="module")
def bridge():
    if not os.path.isfile(DEFAULT_KB):
        pytest.skip("找不到 Trae 知识库 %s" % DEFAULT_KB)
    r = _run()
    return r


def test_all_citations_resolve(bridge):
    """核心断言：每条 file:line 引用都必须指向真值里真的含有该符号的那一行。"""
    assert bridge.returncode == 0, "真值桥有失配：\n" + bridge.stdout[-3000:] + bridge.stderr[-800:]
    assert "全部引用对得上" in bridge.stdout
    assert "不命中              : 0" in bridge.stdout
    assert "行号越界            : 0" in bridge.stdout


def test_home_mode_family_is_fully_covered(bridge):
    """教训 1：回零 mode 一度漏掉 5 个官方宏（其中 40/41 还在引用范围外）。

    修复方式是把引用范围扩到 163-171 并点名全部 9 个 mode。
    若再出现「同族宏在引用范围之外」，说明又有人只列了部分 mode。"""
    assert "同族宏在引用范围之外" not in bridge.stdout, (
        "知识库又有同族宏被引用范围漏掉了：\n" + bridge.stdout[-2000:]
    )


def test_unbacked_macro_semantics_are_self_flagged(bridge):
    """教训 2：MC_GPI/MC_GPO 的语义真值里没有，KB 必须自己标注「待手册确认」。"""
    # 不允许出现「无背书且没标注」
    assert "宏语义无真值背书且未标注" not in bridge.stdout
    # 必须以「已自行标注」的姿态出现
    assert "宏语义未背书（已自行标注）" in bridge.stdout, (
        "MC_GPI/MC_GPO 的语义标注消失了 —— 那是把未背书的语义当成已背书的来用"
    )


def test_pinvoke_still_double_green():
    """真值桥的另一半：Trae 生成的 P/Invoke 对撞官方真值必须仍是 58/58 双绿。

    这条是 B 阶段的成果（61 条 → 删 3 条臆造 → 58 条全对），
    任何一次重新生成套件都可能把它弄坏，所以锁在这里。"""
    script = os.path.join(ROOT, "scripts", "verify_trae_pinvoke.py")
    if not os.path.isfile(script):
        pytest.skip("缺 verify_trae_pinvoke.py")
    # trae_factory 不在本仓里（干净克隆 / CI 上只有本仓一个）→ 跨仓对撞不可核 → 跳过，
    # 但必须写明「当前不可自动复核」：跳过 ≠ 通过（与本文件 docstring 的口径一致）。
    if not os.path.isfile(DEFAULT_KB):
        pytest.skip("找不到 Trae 知识库 %s：跨仓对撞**当前不可自动复核**" % DEFAULT_KB)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, script], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, "P/Invoke 对撞真值失败：\n" + r.stdout[-2000:]
    # 58 条声明、0 不可用、0 不一致
    assert "声明总数(去重) : 58" in r.stdout
    assert "参数签名 MATCH           : 58" in r.stdout
    assert "返回类型一致            : 58" in r.stdout
    assert "返回类型不一致          : 0" in r.stdout
