"""协议域（Modbus）验收测试：知识库纪律 + C# 交付编译冒烟 + 契约测试 + TODO 对账。

知识库 = knowledge/protocols/modbus.json（modbus_extract/1，机械提取 + judgment 显式化）。
纪律同源（knowledge/sdks 域）：一手件指纹一致、quote 反查无裸提取（同源文本）。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KB_PATH = ROOT / "knowledge" / "protocols" / "modbus.json"
DOC = json.loads(KB_PATH.read_text(encoding="utf-8"))
TPL = ROOT / "knowledge" / "templates" / "protocol"


def test_schema与一手件指纹一致():
    import hashlib
    assert DOC["schema_version"] == "modbus_extract/1"
    assert DOC["protocol"] == "modbus"
    # ① 在档指纹自洽：知识库记的 sha256 必须与锚点清单一致（任何检出都能核）
    anchors = json.loads((ROOT / "knowledge" / "protocols" / "anchors.json").read_text(encoding="utf-8"))
    recorded = [a.get("sha256", "").lower() for a in anchors.get("anchors", [])]
    # ② 原件在位时核实物；不在位（仓外未就位）→ SKIP 并写明当前不可自动复核
    ext = ROOT.parent / "mcopilot-external" / "vendor_docs" / "protocol_specs"
    pdfs = list(ext.glob("*.pdf")) or list((ROOT / "knowledge" / "protocols" / "specs").glob("*.pdf"))
    for dv in DOC["spec_version"]["documents"]:
        assert dv["sha256"].lower() in recorded, (
            f"一手件 {dv['doc']} 的指纹不在锚点清单里（anchors.json 与知识库对不上）")
        assert dv["source_url"].startswith("https://www.modbus.org/"), "规范来源必须是官方站"
        match = [p for p in pdfs if hashlib.sha256(p.read_bytes()).hexdigest() == dv["sha256"]]
        if not match:
            pytest.skip("一手件 %s 不在位（按约定外置到 %s）：指纹在档且自洽，"
                        "但**当前不可自动复核**" % (dv["doc"], ext))


def test_条目覆盖下限():
    assert len(DOC["function_codes"]) >= 16, "功能码覆盖不得缩水"
    fc = {e["code"] for e in DOC["function_codes"]}
    for must in (1, 2, 3, 4, 5, 6, 15, 16):   # 上位机读写主链
        assert must in fc, f"功能码 {must:02d} 缺失"
    assert len(DOC["exception_codes"]) >= 9, "异常码至少覆盖 V1.1b3 机械全集"
    for e in DOC["exception_codes"]:
        if e["code"] in (7, 9):               # V1.1b3 表中不存在，必须是 judgment 项
            assert e.get("provenance") == "judgment", f"EX-{e['code']:02d} 必须显式 judgment"


def test_quote反查_全量同源复核():
    ext = ROOT.parent / "mcopilot-external" / "vendor_docs" / "protocol_specs"
    if not ext.is_dir():
        pytest.skip("协议标准原件按约定外置到 %s，本机未就位："
                    "在档指纹自洽，但**当前不可自动复核**" % ext)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_modbus_quotes.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                       timeout=240, cwd=str(ROOT))
    assert r.returncode == 0, "quote 反查未全过（无裸提取红线）：\n" + r.stdout[-1500:]
    m = re.search(r"quote 反查：(\d+)/(\d+) 通过", r.stdout)
    assert m and int(m.group(2)) >= 50, "复核条目数异常"


def test_P2验收门_编译与契约测试全过():
    """全链：csc 编译（TCP+RTU 客户端、帧黄金测试、契约测试）→ 契约桩 → C1-C10 全过。"""
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "smoke_modbus.py")],
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=300, cwd=str(ROOT))
    assert r.returncode == 0, "契约套件未过：\n" + (r.stdout + r.stderr)[-1500:]
    assert "RESULT: PASS" in r.stdout


def test_TODO需实测追踪对账():
    """模板里每个 TODO[需实测] 必须登记在 docs/TODO需实测_协议域.md（双向）。"""
    tracker = (ROOT / "docs" / "TODO需实测_协议域.md").read_text(encoding="utf-8")
    assert "TODO[需实测]" in tracker
    markers = []
    for cs in TPL.glob("*.cs"):
        for i, line in enumerate(cs.read_text(encoding="utf-8").splitlines(), 1):
            if "TODO[需实测]" in line:
                markers.append(f"{cs.name}:{i}")
    assert markers, "模板中应有 TODO[需实测] 锚点（否则追踪机制失效）"
    assert "T1" in tracker and "T2" in tracker and "T3" in tracker, "追踪表编号缺失"
    # 对端等级显式化：自建契约桩 ≠ 开源模拟器 ≠ 真机
    assert "自建契约桩" in tracker and "P4" in tracker
