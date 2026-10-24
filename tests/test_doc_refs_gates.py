#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档坐标门禁的**检测力**自测（2026-10-25 独立第三方评审后补）。

背景
----
评审指出两道门禁在 CI 上「没有牙齿」，且都做了实测复现：

  · **P1-2** `scripts/verify_doc_refs.py`：真值 CSV 的行号指错**只打印不判**，
    exit 0 放行（同一脚本对**代码**行号引用却是硬判失败 —— 两处口径不一致）。
    复现：把 `leisai.csv L957` 改成 L958（仍在范围内、但符号不在那行）→ 放行。
  · **P1-4** 同脚本：`external_missing` 是**全局列表**却参与**单条引用**的判定，
    仓外原件缺位时 → 后续引用的「文件不存在」诊断被跳过 → 崩在 `io.open(None)`。

为什么要有这个文件
------------------
「门禁跑通了」不等于「门禁有牙齿」。本文件用**注入**证明这两道门现在会红：
每条用例先造一个坏引用，再断言门禁**判它坏**。
没有注入自测的门禁，绿灯只能说明「没崩」。

口径
----
* 阴性对照 ✓：造出坏引用，断言门禁**判失败**（这是"有牙齿"）。
* 阳性对照 ✓：造出正确引用，断言门禁**判通过**（防止"见谁都说坏"）。
* 全程不碰仓库里的真实文档与真值文件 ✓：临时文档写在 out/ 下（不入库区）✓。
"""
from __future__ import annotations

import importlib.util
import io
import os
import shutil

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "verify_doc_refs.py")

# 临时文档必须落在**仓内**：脚本会 os.path.relpath(doc, ROOT)，
# 而 pytest 的 tmp_path 在别的盘上时 relpath 会抛 ValueError（跨盘）。
# out/ 是不入库区（.gitignore 已声明），放这儿不污染仓库，跑完清掉。
TMP_DIR = os.path.join(ROOT, "out", "_pytest_doc_refs")


@pytest.fixture()
def doc_dir():
    os.makedirs(TMP_DIR, exist_ok=True)
    try:
        yield TMP_DIR
    finally:
        shutil.rmtree(TMP_DIR, ignore_errors=True)


def _load():
    """按路径加载 scripts/verify_doc_refs.py（它是脚本，不是包内模块）。"""
    spec = importlib.util.spec_from_file_location("_vdr_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(path, text):
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _truth_line_of(mod, symbol):
    """返回该符号在真值 CSV 里的行号（1 起）。"""
    rows = io.open(mod.TRUTH_FILES["leisai.csv"], encoding="utf-8").read().splitlines()
    for i, r in enumerate(rows, 1):
        if symbol in r:
            return i
    raise AssertionError("真值 CSV 里找不到符号 %s" % symbol)


# ── P1-2：真值行号指错必须判失败 ─────────────────────────────────────
def test_真值行号指错必须让门禁变红(monkeypatch, doc_dir):
    """引用行号指到**范围内但不对**的那一行 → 必须判失败。

    评审实测：把 `leisai.csv L957` 改成 L958（仍在范围内、但符号不在那行），
    门禁只打印一行提示，退出码仍是 0 —— 静默漂移放行。
    """
    mod = _load()
    right = _truth_line_of(mod, "dmc_cam_table_unit")     # L957
    wrong = right + 1                                       # L958 = dmc_cam_move
    rows = io.open(mod.TRUTH_FILES["leisai.csv"], encoding="utf-8").read().splitlines()
    assert "dmc_cam_table_unit" not in rows[wrong - 1], "错开的那行不该含该符号"

    doc = _write(os.path.join(doc_dir, "tmp_truth_ref.md"),
                 "结论见 `leisai.csv` L%d 的 dmc_cam_table_unit 一行。\n" % wrong)
    monkeypatch.setattr(mod, "CODE_DOC_GLOBS", [])   # 只测这条文档，不扫仓库里的
    assert mod.main(["--doc", doc, "--quiet"]) == 1, \
        "行号指错必须判失败（现在却放行了）"


def test_真值行号指对必须判通过(monkeypatch, doc_dir):
    """阳性对照：行号指对了就不能说坏——否则这门只会喊，不会看。"""
    mod = _load()
    right = _truth_line_of(mod, "dmc_cam_table_unit")
    doc = _write(os.path.join(doc_dir, "tmp_truth_ref_ok.md"),
                 "结论见 `leisai.csv` L%d 的 dmc_cam_table_unit 一行。\n" % right)
    monkeypatch.setattr(mod, "CODE_DOC_GLOBS", [])
    assert mod.main(["--doc", doc, "--quiet"]) == 0, \
        "正确的行号引用不该被判失败"


# ── P1-4：仓外原件缺位时不得崩溃，且缺失必须报出来 ───────────────────
def test_仓外原件缺位时不得崩溃且仍要报出缺失(monkeypatch, doc_dir):
    """先造一条「登记过但原件不在位」的引用，再造一条真·不存在的引用。

    旧实现：全局的 external_missing 让第二条的「文件不存在」诊断被跳过，
    接着 `targets = [None]` → `io.open(None)` → TypeError（exit 1，只吐栈）。
    新实现：不得崩；那条真·不存在的引用必须被判出来。
    """
    mod = _load()
    # 造一份「登记过、但落点必然不在位」的登记（不依赖本机 out/ 的状态）
    monkeypatch.setattr(mod, "EXTERNAL_BY_NAME", {
        "Modbus_Application_Protocol_V1_1b3.txt": {
            "name": "Modbus_Application_Protocol_V1_1b3.txt",
            "path": "out/_definitely_not_here_for_this_test/none.txt",
        }
    })
    doc = _write(os.path.join(doc_dir, "tmp_ext_ref.md"),
                 "规格原文见 Modbus_Application_Protocol_V1_1b3.txt:10。\n"
                 "另见 zzz_definitely_not_exist.py:10 这一处。\n")
    monkeypatch.setattr(mod, "CODE_DOC_GLOBS", [("tmp_ext_ref.md", doc)])
    total, bad = mod.check_code_refs(verbose=False)   # 旧实现在这里抛 TypeError
    assert bad >= 1, "真·不存在的引用必须被判出来（bad=%d）" % bad
