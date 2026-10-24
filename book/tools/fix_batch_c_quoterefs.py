#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_batch_c_quoterefs.py —— 批 C 第 3 项续 2：外置原件的**代码层**引用同步改（2026-10-22）。

批 B 的检查器只核"文档里的路径"，代码里的路径没人核——本轮外置原件把这条漏网点踩出来了：
quote 反查与两个验收测试都指着仓内 PDF 目录。处置原则与门禁一致：
  ① 在档指纹自洽（知识库 ↔ 锚点清单）：任何检出都能核；
  ② 原件在位时核实物；不在位 → 明确 SKIP 并写明"当前不可自动复核"。
另外：断言里**按 sha256 匹配**而不是按文件名——锚点条目的名字是文件名，
而知识库记的是手册编号，两者本来就对不上。
"""
import io
import sys

MC = r"%WORKSPACE%\mcopilot"
EXT_REL = "../mcopilot-external/vendor_docs/protocol_specs"

FIXES = [
    # ── scripts/check_modbus_quotes.py：PDF 取自仓外约定位，工具仍在仓内 ────────
    (r"scripts\check_modbus_quotes.py",
     '''    specs = ROOT / "knowledge" / "protocols" / "specs"
    pdfs = sorted(specs.glob("*.pdf"))''',
     '''    specs = ROOT / "knowledge" / "protocols" / "specs"          # 提取工具仍在仓内
    # 原件按本仓约定外置（仓内不存厂商/标准一手件）：优先仓外约定位，找不到再看仓内历史位置
    ext = ROOT.parent / "mcopilot-external" / "vendor_docs" / "protocol_specs"
    pdfs = sorted(ext.glob("*.pdf")) or sorted(specs.glob("*.pdf"))''', 1),

    # ── tests/test_protocol_modbus.py：按 sha256 匹配 + 原件不在位则 SKIP ──────
    (r"tests\test_protocol_modbus.py",
     '''    for dv in DOC["spec_version"]["documents"]:
        pdfs = list((ROOT / "knowledge" / "protocols" / "specs").glob("*.pdf"))
        match = [p for p in pdfs if hashlib.sha256(p.read_bytes()).hexdigest() == dv["sha256"]]
        assert match, f"一手件 {dv['doc']} 无指纹匹配的 PDF 在库（specs/ 必须存原件）"
        assert dv["source_url"].startswith("https://www.modbus.org/"), "规范来源必须是官方站"''',
     '''    # ① 在档指纹自洽：知识库记的 sha256 必须与锚点清单一致（任何检出都能核）
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
                        "但**当前不可自动复核**" % (dv["doc"], ext))''', 1),
    (r"tests\test_protocol_modbus.py",
     "import json\nimport re\nimport subprocess\nimport sys\nfrom pathlib import Path\n",
     "import json\nimport re\nimport subprocess\nimport sys\nfrom pathlib import Path\n\nimport pytest\n", 1),

    # ── tests/test_protocol_slmp.py：按 sha256 匹配（锚点条目名 ≠ 手册编号）─────
    (r"tests\test_protocol_slmp.py",
     '''        # ① 在档指纹自洽：slmp.json 记的指纹必须与锚点清单一致（任何检出都能核）
        anchors = json.loads((ROOT / "knowledge" / "protocols" / "anchors.json").read_text(encoding="utf-8"))
        recorded = {a["name"]: a.get("sha256", "").lower()
                    for a in anchors.get("anchors", [])}
        pdf_name = dv["manual_number"] + ".pdf"
        assert recorded.get(pdf_name, "").lower() == dv["sha256"].lower(), (
            "在档指纹与锚点清单不一致：" + pdf_name)''',
     '''        # ① 在档指纹自洽：slmp.json 记的指纹必须与锚点清单一致（任何检出都能核）
        #    （按 sha256 匹配，不按文件名——锚点条目名是文件名，文档记的是手册编号）
        anchors = json.loads((ROOT / "knowledge" / "protocols" / "anchors.json").read_text(encoding="utf-8"))
        recorded = [a.get("sha256", "").lower() for a in anchors.get("anchors", [])]
        assert dv["sha256"].lower() in recorded, (
            "在档指纹与锚点清单不一致：" + dv["manual_number"])''', 1),
]


def main():
    cache = {}
    applied, failed = 0, []
    for rel, old, new, cnt in FIXES:
        path = MC + "\\" + rel
        if path not in cache:
            cache[path] = io.open(path, encoding="utf-8", newline="").read()
        txt = cache[path]
        eol = "\r\n" if "\r\n" in txt else "\n"
        old_e, new_e = old.replace("\n", eol), new.replace("\n", eol)
        got = txt.count(old_e)
        if got != cnt:
            failed.append((rel, old[:60], got, cnt))
            continue
        cache[path] = txt.replace(old_e, new_e)
        applied += 1
    if failed:
        print("✗ 有替换未达期望命中数，未写盘：")
        for rel, old, got, cnt in failed:
            print(f"    {rel}  期望 {cnt} 实得 {got}  ← {old}")
        sys.exit(1)
    for path, txt in cache.items():
        io.open(path, "w", encoding="utf-8", newline="").write(txt)
        print(f"  ✓ {path[len(MC)+1:]}")
    print(f"\n共 {applied} 处落盘（{len(cache)} 个文件）")


if __name__ == "__main__":
    main()
