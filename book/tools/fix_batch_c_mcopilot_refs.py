#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_batch_c_mcopilot_refs.py —— 批 C 第 3 项续：mcopilot 仓内指向"已外置原件"的引用同步改（2026-10-22）。

纪律：精确串 + 命中次数断言；次数不符即退出。
另含一处**断言逻辑**的变更：SLMP 验收原来断言"一手件 PDF 必须在库"——
原件外置后该断言在干净检出上必然失败。改法不是"改成跳过"（那是把纪律弄坏），
而是把可核的拆成两半：
  ① 在档指纹自洽（slmp.json ↔ anchors.json ↔ 提取脚本默认值）——**任何检出都能核**；
  ② 原件在位时核实物 sha256——不在位时明确 SKIP 并写明"当前不可自动复核"。
"""
import io
import sys

MC = r"%WORKSPACE%\mcopilot"
EXT_REL = "../mcopilot-external/vendor_docs/protocol_specs"

FIXES = [
    # ── scripts/extract_slmp.py：原件位置随约定改 ─────────────────────────────
    (r"scripts\extract_slmp.py",
     'PDF = ROOT / "knowledge" / "protocols" / "slmp_specs" / "FX5_SLMP_JY997D54401.pdf"',
     '# 原件按本仓约定外置（仓内不存厂商一手件）：默认走 ../mcopilot-external 约定\n'
     'PDF = ROOT.parent / "mcopilot-external" / "vendor_docs" / "protocol_specs" / "FX5_SLMP_JY997D54401.pdf"', 1),

    # ── knowledge/protocols/focas.json：两处 source_pdf ──────────────────────
    (r"knowledge\protocols\focas.json",
     '"source_pdf": "knowledge/protocols/specs/FOCAS2_Ethernet_Linux_en.pdf"',
     f'"source_pdf": "{EXT_REL}/FOCAS2_Ethernet_Linux_en.pdf"', 1),
    (r"knowledge\protocols\focas.json",
     '"source_pdf": "knowledge/protocols/specs/FOCAS_function_list.pdf"',
     f'"source_pdf": "{EXT_REL}/FOCAS_function_list.pdf"', 1),

    # ── tests/test_protocol_slmp.py：原件目录 + 断言拆分 ──────────────────────
    (r"tests\test_protocol_slmp.py",
     "import hashlib\nimport json\nimport re\nimport subprocess\nimport sys\n",
     "import hashlib\nimport json\nimport re\nimport subprocess\nimport sys\n\nimport pytest\n", 1),
    (r"tests\test_protocol_slmp.py",
     'SPECS = ROOT / "knowledge" / "protocols" / "slmp_specs"',
     '# 原件按本仓约定外置（仓内不存厂商一手件）；在位即核实物，不在位则记 SKIP\n'
     'SPECS = ROOT.parent / "mcopilot-external" / "vendor_docs" / "protocol_specs"', 1),
    (r"tests\test_protocol_slmp.py",
     '''        match = [p for p in SPECS.glob("*.pdf")
                 if hashlib.sha256(p.read_bytes()).hexdigest() == dv["sha256"]]
        assert match, "一手件 PDF 必须在库且指纹一致"''',
     '''        # ① 在档指纹自洽：slmp.json 记的指纹必须与锚点清单一致（任何检出都能核）
        anchors = json.loads((ROOT / "knowledge" / "protocols" / "anchors.json").read_text(encoding="utf-8"))
        recorded = {a["name"]: a.get("sha256", "").lower()
                    for a in anchors.get("anchors", [])}
        pdf_name = dv["manual_number"] + ".pdf"
        assert recorded.get(pdf_name, "").lower() == dv["sha256"].lower(), (
            "在档指纹与锚点清单不一致：" + pdf_name)
        # ② 原件在位时核实物；不在位（仓外未就位）→ SKIP 并写明当前不可自动复核
        match = [p for p in SPECS.glob("*.pdf")
                 if hashlib.sha256(p.read_bytes()).hexdigest() == dv["sha256"]]
        if not match:
            pytest.skip("一手件 PDF 不在位（按约定外置到 %s）：指纹在档且自洽，"
                        "但**当前不可自动复核**" % SPECS)''', 1),

    # ── docs/CodeWiki_20261022.md：计数与目录树同步 ───────────────────────────
    (r"docs\CodeWiki_20261022.md",
     "| 真值锚点 | 14 条外部件 sha256 + 21 份厂商官方 CSV + 7 份规范 PDF | 【实测】 |",
     "| 真值锚点 | 15 条外部件 sha256（其中 7 份规范 PDF 按约定**外置**）+ 21 份厂商官方 CSV | 【实测】 |", 1),
    (r"docs\CodeWiki_20261022.md",
     "`protocols/anchors.json`（14 条）",
     "`protocols/anchors.json`（15 条）", 1),
    (r"docs\CodeWiki_20261022.md",
     "| ├ `specs/` | 7 | Modbus×3 + FOCAS×2 + Snap7 PDF + `pdf2txt.py` | `gate_anchors.py` |",
     "| ├ `specs/` | 1 | `pdf2txt.py`（厂商/标准 PDF 原件已外置，见 `../mcopilot-external/vendor_docs/protocol_specs/`） | `gate_anchors.py` |", 1),
    (r"docs\CodeWiki_20261022.md",
     "| ├ `slmp_specs/` | 1 | 三菱 FX5 SLMP 手册 PDF | `extract_slmp.py` |\n",
     "", 1),
    (r"docs\CodeWiki_20261022.md",
     "| 协议标准 PDF | 6 份 `specs/` + 1 份 `slmp_specs/` | `gate_anchors.py` 重算 sha256 + 再提取抽查 + URL 存活性 |",
     "| 协议标准 PDF | 7 份（Modbus×3 + FOCAS×2 + Snap7 + 三菱 FX5；**全部外置**到 `../mcopilot-external/vendor_docs/protocol_specs/`，仓内只留指针 + sha256） | `gate_anchors.py` 重算 sha256（外置件在位即核、不在位记 SKIP）+ 再提取抽查 + URL 存活性 |", 1),
    (r"docs\CodeWiki_20261022.md",
     "2. **`anchors.json` ↔ 一手件** —— 14 条 `path → sha256 + size`，PDF/源码包/安装包任一被替换即红。",
     "2. **`anchors.json` ↔ 一手件** —— 15 条 `path → sha256 + size`，PDF/源码包/安装包任一被替换即红。"
     "非入库区条目（`out/` 本地产物、`../mcopilot-external/` 仓外原件）在干净检出上必然不在位："
     "在位即核、缺位记 **SKIP** 并在汇总行喊出「当前不可自动复核」，**不判 FAIL**（那是把设计当缺件）。", 1),
]


def main():
    cache = {}
    applied, failed = 0, []
    for rel, old, new, cnt in FIXES:
        path = MC + "\\" + rel
        if path not in cache:
            cache[path] = io.open(path, encoding="utf-8", newline="").read()
        txt = cache[path]
        got = txt.count(old)
        if got != cnt:
            failed.append((rel, old[:80], got, cnt))
            continue
        cache[path] = txt.replace(old, new)
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
