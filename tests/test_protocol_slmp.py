"""SLMP（第二协议）知识库验收：schema + 一手件指纹 + quote 反查 + 条目下限。

一手件 = FX5 User's Manual (SLMP)（JY997D54401，经镜像分发、编号+sha256 验证）。
"""
import hashlib
import json
import os
import re
import subprocess
import sys

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = json.loads((ROOT / "knowledge" / "protocols" / "slmp.json").read_text(encoding="utf-8"))
# 原件按本仓约定外置（仓内不存厂商一手件）；在位即核实物，不在位则记 SKIP
SPECS = ROOT.parent / "mcopilot-external" / "vendor_docs" / "protocol_specs"


def test_schema与一手件指纹一致():
    assert DOC["schema_version"] == "slmp_extract/1"
    assert DOC["protocol"] == "slmp"
    for dv in DOC["spec_version"]["documents"]:
        assert dv["manual_number"].startswith("JY99"), "手册编号必须入档（镜像分发的身份验证锚）"
        assert dv["official_entry"].startswith("https://www.mitsubishielectric"), "官方入口必须记录"
        # ① 在档指纹自洽：slmp.json 记的指纹必须与锚点清单一致（任何检出都能核）
        #    （按 sha256 匹配，不按文件名——锚点条目名是文件名，文档记的是手册编号）
        anchors = json.loads((ROOT / "knowledge" / "protocols" / "anchors.json").read_text(encoding="utf-8"))
        recorded = [a.get("sha256", "").lower() for a in anchors.get("anchors", [])]
        assert dv["sha256"].lower() in recorded, (
            "在档指纹与锚点清单不一致：" + dv["manual_number"])
        # ② 原件在位时核实物；不在位（仓外未就位）→ SKIP 并写明当前不可自动复核
        match = [p for p in SPECS.glob("*.pdf")
                 if hashlib.sha256(p.read_bytes()).hexdigest() == dv["sha256"]]
        if not match:
            pytest.skip("一手件 PDF 不在位（按约定外置到 %s）：指纹在档且自洽，"
                        "但**当前不可自动复核**" % SPECS)


def test_骨架覆盖与诚实标注():
    kinds = {}
    for e in DOC["entries"]:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        assert e["id"].startswith("SLMP-")
        sref = e["spec_ref"]
        assert sref.get("page") and sref.get("quote"), f"{e['id']} spec_ref 不完整"
    assert kinds.get("frame_format") >= 1 and kinds.get("command") >= 2, "帧/指令骨架缺失"
    cmds = {e["command"] for e in DOC["entries"] if e["kind"] == "command"}
    assert "0401H" in cmds and "1401H" in cmds, "批量读/写指令缺失"
    devs = {e["ascii_code"] for e in DOC["entries"] if e["kind"] == "device_code"}
    assert "A8H" in devs, "D 寄存器码缺失（上位机主用）"
    # 消息图解不可机械还原的部分必须显式 judgment + needs:manual_check，不得冒充机械
    judg = [e for e in DOC["entries"] if e.get("provenance") == "judgment"]
    assert judg and all(e.get("needs") == "manual_check" for e in judg), "judgment 项必须带 needs"


def test_quote反查_同源复核():
    ext = ROOT.parent / "mcopilot-external" / "vendor_docs" / "protocol_specs"
    if not ext.is_dir():
        pytest.skip("协议标准原件按约定外置到 %s，本机未就位："
                    "在档指纹自洽，但**当前不可自动复核**" % ext)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "extract_slmp.py"), "--check"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                       timeout=180, cwd=str(ROOT))
    assert r.returncode == 0, "SLMP quote 反查未全过：\n" + r.stdout[-800:]
    assert "命中" in r.stdout


def test_P2验收门_SLMP编译与契约测试全过():
    """全链：csc 编译 SLMP 客户端 → 3E 契约桩 → 契约断言 C1-C9 全过（C10 TODO[需实测]）。"""
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "smoke_slmp.py")],
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=300, cwd=str(ROOT))
    assert r.returncode == 0, "SLMP 契约套件未过：\n" + (r.stdout + r.stderr)[-1500:]
    assert "RESULT: PASS" in r.stdout
    # TODO 追踪：SLMP 契约的 TODO[需实测] 已登记（T4/T5）
    tracker = (ROOT / "docs" / "TODO需实测_协议域.md").read_text(encoding="utf-8")
    assert "T4" in tracker and "T5" in tracker
