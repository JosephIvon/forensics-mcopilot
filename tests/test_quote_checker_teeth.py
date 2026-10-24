#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引文反查（G5）的**检测力**自测（评审 P1-5）。

背景
----
评审 P1-5：`scripts/check_modbus_quotes.py` 在 CI 上**结构性不执行** ✓ ——
它读的页文本在 `out/_protocols_extract/`（gitignored ✓），
干净检出/CI 里没有 ✓ → 于是「引文是不是编的」这条验证在 CI 上
**永远没有结论** ✓，而它的输出又被当成"绿" ✓✓。

为什么不改成"把原件放进仓里"
--------------------------
本仓的约定是**一手件外置** ✓（厂商/标准原文不入库 ✓，
`gate_anchors.py` 靠 sha256 钉住"在位即必核"✓）。
为了跑一条测试而把 4 份 PDF 塞进仓里，会推翻整条资产策略 ✓ ——
那是**用一个问题换另一个更大的问题** ✓✓。
所以这里换一条路：**用合成小样证明检查器有牙齿** ✓。

做法
----
`check_modbus_quotes.py` 已经参数化（`--json` / `--txt-dir` ✓
缺省值即历史硬编码路径 ✓ → 无参调用行为不变 ✓）。
本文件造一份**极小**的：
  · 提取文本（`===== [PAGE 1] =====` + 一页真文本 ✓）
  · 知识库 JSON（一条 spec_ref ✓）
跑两遍：
  · 引文照抄页文本 → 必须 **exit 0 / 1/1 通过** ✓（阳性对照）
  · 引文被编造   → 必须 **exit 1** 且指出「无同源证据」✓✓（阴性对照）
没有这两条，G5 的"53/53 通过"只证明「跑了没报错」✓，
不证明「编造的引文会被抓」✓。
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "check_modbus_quotes.py")

# 与 DOC_PDF 的映射键一致：doc 字段里含 "V1.1b3" → 读这份提取文本
PAGE_TEXT = (
    "The function code field of a message frame contains eight bits.\n"
    "Valid codes are in the range of 1 to 255 decimal.\n"
)


def _make_case(tmp_path, quote: str):
    """造一份提取文本 + 一份只含一条 spec_ref 的知识库 JSON。"""
    txt_dir = tmp_path / "extract"
    txt_dir.mkdir()
    # 三份都要在：check_modbus_quotes.ensure_extract() 只要发现**任一**缺失就会去
    # 跑 pdf2txt.py（真·PDF 抽取，几十秒）✓ —— 本测试不该依赖仓外原件 ✓。
    (txt_dir / "Modbus_Application_Protocol_V1_1b3.txt").write_text(
        "===== [PAGE 1] =====\n" + PAGE_TEXT, encoding="utf-8")
    for name in ("Modbus_over_serial_line_V1_02.txt",
                 "Modbus_Messaging_Implementation_Guide_V1_0b.txt"):
        (txt_dir / name).write_text("===== [PAGE 1] =====\nplaceholder\n", encoding="utf-8")
    kb = {
        "function_codes": {
            "valid_range": {
                "spec_ref": {
                    # 必须含映射键 "V1.1b3"（DOC_PDF 用子串匹配）✓
                    "doc": "Modbus_Application_Protocol_V1.1b3",
                    "page": 1,
                    "quote": quote,
                }
            }
        }
    }
    kb_path = tmp_path / "kb.json"
    kb_path.write_text(json.dumps(kb, ensure_ascii=False), encoding="utf-8")
    return kb_path, txt_dir


def _run(kb_path, txt_dir):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, SCRIPT, "--json", str(kb_path), "--txt-dir", str(txt_dir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=300)


def test_照抄页文本的引文必须通过(tmp_path):
    """阳性对照 ✓：一字不差抄页文本 → exit 0，且**确实核过 1 条**（不是 0/0）✓。"""
    quote = "The function code field of a message frame contains eight bits."
    kb, txt = _make_case(tmp_path, quote)
    p = _run(kb, txt)
    out = (p.stdout or "") + (p.stderr or "")
    assert p.returncode == 0, "correct quote should pass, got exit %d\n%s" % (p.returncode, out)
    assert "1/1" in out, "必须真的核过 1 条（0/0 是假绿）：%s" % out


def test_编造的引文必须被抓出来(tmp_path):
    """阴性对照 ✓：页面上根本没有这句话 → 必须 exit 1 并说明无同源证据 ✓✓。

    这是 P1-5 的要害 ✓：G5 的价值全在「编造的引文会被抓」✓。
    如果这条不通，报告里的「53/53 通过」就只是「跑了没报错」✓。
    """
    quote = "The function code field must always be zero for broadcast frames."
    kb, txt = _make_case(tmp_path, quote)
    p = _run(kb, txt)
    out = (p.stdout or "") + (p.stderr or "")
    assert p.returncode == 1, "编造的引文必须让门禁变红，实际 exit %d\n%s" % (p.returncode, out)
    assert "无同源证据" in out, "必须指出「无同源证据」：%s" % out


def test_页面文本只有一半的引文也必须被抓(tmp_path):
    """**半真引文**（前半句在、后半句编）—— 最容易混过人工复核的那一类 ✓。

    页面上确实有 "The function code field of a message frame contains eight bits." ✓，
    但把后半句换成不存在的内容 ✓ → 必须仍是「无同源证据」✓✓。
    """
    quote = ("The function code field of a message frame contains eight bits, "
             "and it must be echoed back by the slave in every response.")
    kb, txt = _make_case(tmp_path, quote)
    p = _run(kb, txt)
    out = (p.stdout or "") + (p.stderr or "")
    assert p.returncode == 1, "半真引文必须变红，实际 exit %d\n%s" % (p.returncode, out)
    assert "无同源证据" in out, "必须指出「无同源证据」：%s" % out


def test_引用的页超出范围时必须报错(tmp_path):
    """页号越界（引用到不存在的页）不得静默通过 ✓。"""
    kb, txt = _make_case(tmp_path, "The function code field of a message frame contains eight bits.")
    doc = json.loads(kb.read_text(encoding="utf-8"))
    doc["function_codes"]["valid_range"]["spec_ref"]["page"] = 999
    kb.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    p = _run(kb, txt)
    out = (p.stdout or "") + (p.stderr or "")
    assert p.returncode == 1, "页号越界必须变红，实际 exit %d\n%s" % (p.returncode, out)
    assert "超出" in out, "必须说明页号越界：%s" % out


def test_本仓真值库的引文条数不得为零():
    """真值库本身必须**还有**可反查的引文 ✓（否则门禁会以 0/0 假绿）✓。"""
    kb = os.path.join(ROOT, "knowledge", "protocols", "modbus.json")
    if not os.path.isfile(kb):
        pytest.skip("modbus.json 不存在，当前不可自动复核")
    doc = json.loads(io.open(kb, encoding="utf-8").read())

    def walk(obj):
        if isinstance(obj, dict):
            ref = obj.get("spec_ref")
            if isinstance(ref, dict) and ref.get("quote"):
                yield obj, ref
            for v in obj.values():
                yield from walk(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from walk(v)

    countable = [1 for host, ref in walk(doc)
                 if not (host.get("provenance") == "judgment"
                         or host.get("needs") == "manual_check"
                         or ref.get("provenance") == "judgment")]
    assert countable, "modbus.json 里一条可反查的引文都没有 → G5 会以 0/0 假绿"
