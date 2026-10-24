#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`tests/` 目录卫生：不许再有「看着像测试、其实不被收集」的文件。

背景（评审 P2-7）
----------------
`tests/_gts_tests_append.py` 曾经待在 `tests/` 顶层 ✓：
文件名不匹配 `test_*.py` → **pytest 根本不收集它** ✓
（`pyproject.toml` 只设 `testpaths`，`python_files` 用默认值 ✓），
所以里面的断言**从来没有跑过**，却看起来像一套测试 ✓。

更坏的是它**与现真相冲突** ✓：
它断言 `verified == "needs-manual-check"`，而现真相是 `"official-binding"` ✓
→ 任何人把它改名成 `test_*.py` 会**立刻红** ✓，
而「改哪个才对」正是这个文件会诱导出的错误方向 ✓✓。

处置
----
它已移入 `tests/archive/`（档案，保留可追溯性 ✓，
文件头写明「勿收集、勿改名」✓）。
本文件是配套的**元测试** ✓：扫描 `tests/*.py` 顶层，
断言其中**没有**非 `test_*.py` 的文件含 `def test_` ✓。

为什么按顶层扫、不递归 ✓
----------------------
档案目录**本来就该保留**当年那份带 `def test_` 的原文 ✓（那是「当时写了什么」的证据 ✓）。
只要求它**不被当成现役测试** ✓ —— 而 pytest 只收 `test_*.py` ✓，
`archive/_gts_tests_append.py` 不会被收 ✓。
"""
from __future__ import annotations

import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")


def _top_level_py():
    return sorted(n for n in os.listdir(TESTS)
                  if n.endswith(".py") and os.path.isfile(os.path.join(TESTS, n)))


def test_tests顶层没有藏着测试的非test文件():
    """`tests/*.py` 里非 `test_*.py` 的文件，不得含 `def test_` ✓。

    这类文件是**假测试** ✓：看起来在测，实际永不被收集 ✓ → 比没有测试更坏 ✓。
    """
    bad = []
    for name in _top_level_py():
        if name.startswith("test_"):
            continue
        txt = io.open(os.path.join(TESTS, name), encoding="utf-8", errors="replace").read()
        if re.search(r"^def test_", txt, re.M):
            bad.append(name)
    assert not bad, (
        "这些文件在 tests/ 顶层但不叫 test_*.py，pytest 不会收集它们，"
        "里面的 def test_ 永远不会跑（假测试）：%s\n"
        "处置：要么改名成 test_*.py 让它真的跑；要么移进 tests/archive/ 并写明是档案。" % bad)


def test_档案目录里的旧版本不得被收集():
    """`tests/archive/` 存在的意义是**不**被收集 ✓ —— 文件名必须不匹配 test_*.py ✓。"""
    arch = os.path.join(TESTS, "archive")
    if not os.path.isdir(arch):
        return
    collected = [n for n in os.listdir(arch)
                 if n.startswith("test_") and n.endswith(".py")]
    assert not collected, (
        "tests/archive/ 里有会被 pytest 收集的文件：%s\n"
        "档案是「当时的证据」，不是现役测试；改名成 test_* 会立刻红。" % collected)


def test_档案里头号文件仍是固高段的早期版本():
    """留档要留得**认得出来** ✓：抬头写明「勿收集、勿改名」✓，且内容确实是旧版本 ✓。"""
    p = os.path.join(TESTS, "archive", "_gts_tests_append.py")
    assert os.path.isfile(p), "固高段的早期版本应留档在 tests/archive/_gts_tests_append.py"
    txt = io.open(p, encoding="utf-8", errors="replace").read()
    assert "勿收集" in txt and "勿改名" in txt, "档案抬头缺「勿收集/勿改名」警示"
    assert 'needs-manual-check' in txt, \
        "档案应是**旧版本**（断言 needs-manual-check）；现真相是 official-binding"
