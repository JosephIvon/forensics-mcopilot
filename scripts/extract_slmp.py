# -*- coding: utf-8 -*-
"""SLMP（FX5 User's Manual (SLMP) JY997D54401）骨架知识提取。

机械提取范围（pypdf 文字形态可锚定的部分）：
- 3E 帧定义（p13）、指令表 Device Read/Write (Batch)（p41）、软元件码表（p46-47）。
- 副头部值仅存在于消息图解（pypdf 列打散），标 judgment + needs:manual_check，不冒充机械。
- End code 值表不在本手册文字层（在 MC Protocol 手册），骨架不含——如实缺。

跑法：python scripts/extract_slmp.py   （重建 knowledge/protocols/slmp.json）
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# 原件按本仓约定外置（仓内不存厂商一手件）：默认走 ../mcopilot-external 约定
PDF = ROOT.parent / "mcopilot-external" / "vendor_docs" / "protocol_specs" / "FX5_SLMP_JY997D54401.pdf"
OUT = ROOT / "knowledge" / "protocols" / "slmp.json"

import hashlib

from pypdf import PdfReader

NORM = re.compile(r"\s+")


def norm(s: str) -> str:
    return NORM.sub(" ", s).strip()


def build() -> dict:
    reader = PdfReader(str(PDF))
    pages = {i: (p.extract_text() or "") for i, p in enumerate(reader.pages, 1)}
    sha = hashlib.sha256(PDF.read_bytes()).hexdigest()
    doc = {
        "protocol": "slmp",
        "schema_version": "slmp_extract/1",
        "generated": "2026-10-21",
        "note": "FX5 User's Manual (SLMP) 骨架机械提取；消息图解区 pypdf 列打散不可还原，"
                "相关值标 judgment + needs:manual_check（不冒充机械提取）。",
        "spec_version": {
            "documents": [{
                "doc": "MELSEC iQ-F FX5 User's Manual (SLMP)",
                "doc_short": "FX5-SLMP",
                "manual_number": "JY997D54401",
                "pdf_pages": len(reader.pages),
                "sha256": sha,
                "source_url": "http://www.atronika.com/Mitsubishi/PLC/MITSUBISHI_manual_plc_fx5_slmp.pdf",
                "official_entry": "https://www.mitsubishielectric.co.jp/fa/download/search.page?mode=manual",
                "source_note": "官方下载页为 JS 动态无法直链，经镜像分发；一手件以手册编号+sha256 指纹验证，"
                               "内容为三菱官方手册原文（首页标题已核对）。",
            }],
        },
        "entries": [],
    }
    ent = doc["entries"]

    def ref(page, quote, section, **kw):
        r = {"doc": "MELSEC iQ-F FX5 User's Manual (SLMP)", "section": section,
             "page": page, "quote": norm(quote)}
        r.update(kw)
        return r

    # 1. 3E 帧定义（p13 文字形态）
    t13 = norm(pages[13])
    q3e = ("The message format is the same as the QnA compatible 3E frame of MC protocol.")
    assert q3e in t13, "p13 锚点失配（PDF 变版？）"
    ent.append({
        "id": "SLMP-FRAME-3E", "kind": "frame_format",
        "name": "3E frame (QnA compatible 3E frame of MC protocol)",
        "meaning": "SLMP 数据通信帧与 MC 协议 QnA 兼容 3E 帧相同；用于从外部设备访问 CPU 模块全部软元件。"
                   "支持二进制码/ASCII 码两种数据代码（由 GX Works3 模块参数决定）。",
        "spec_ref": ref(13, q3e, "2.1"),
        "provenance": "mechanical",
    })

    # 2. 指令表（p41）：先锚 (Command)(Subcommand) 数字对，name 从前文尾部捕获
    #    （表行形态：Device Read\n(Batch)\n0401H 0001H …——pypdf 换行打散 name，正向正则不稳）
    t41 = pages[41]
    NAME_TAIL = re.compile(r"((?:Device|Word|Bit)?\s?(?:Read|Write)(?:\s?/\s?(?:Read|Write))?\s*(?:\(Batch\)|Random)?)$")
    seen_cmds = set()
    for m in re.finditer(r"(\d{4})H\s+(\d{4})H", t41):
        cmd, sub = m.group(1), m.group(2)
        if not (0x0400 <= int(cmd, 16) <= 0x2099) or cmd in seen_cmds:
            continue
        pre = norm(t41[max(0, m.start() - 70):m.start()])
        tails = NAME_TAIL.findall(pre)
        name = tails[-1].strip() if tails else pre[-30:]
        if not name or not re.search(r"[A-Za-z]", name):
            continue
        seen_cmds.add(cmd)
        quote = pre[-70:] + f" {cmd}H {sub}H"
        ent.append({
            "id": f"SLMP-CMD-{cmd}", "kind": "command",
            "name": name, "command": f"{cmd}H", "subcommand": f"{sub}H",
            "spec_ref": ref(41, quote, "4.1"),
            "provenance": "mechanical",
        })
    assert "0401" in seen_cmds and "1401" in seen_cmds, f"指令表锚点失配：{sorted(seen_cmds)}"

    # 3. 软元件码表（p46-47）：形态 `Data register Word D*\n(D***)\nA8H\n(A800H)`
    dev_pat = re.compile(
        r"((?:[A-Z][A-Za-z]+ ){0,4}?)(Bit|Word)\s+([A-Z]\*)\s*\n?\s*\(([A-Z]\*\*\*)\)"
        r"\s*\n?\s*([0-9A-F]{2})H\s*\n?\s*\(([0-9A-F]{4})H\)")
    seen_dev = set()
    for pno in (46, 47):
        t = pages[pno]
        for m in dev_pat.finditer(t):
            name = norm(m.group(1)) or m.group(3)
            key = (name, m.group(5))
            if key in seen_dev:
                continue
            seen_dev.add(key)
            quote = norm(t[m.start():m.start() + 90])
            ent.append({
                "id": f"SLMP-DEV-{name.replace(' ', '')}-{m.group(5)}", "kind": "device_code",
                "name": name, "data_type": m.group(2), "spec_format": m.group(4),
                "ascii_code": f"{m.group(5)}H", "binary_code": f"{m.group(6)}H",
                "spec_ref": ref(pno, quote, "4.2"),
                "provenance": "mechanical",
            })
    assert any(e.get("ascii_code") == "A8H" for e in ent), "软元件码锚点失配（D 寄存器 A8H 未抓到）"

    # 4. 副头部（图解打散，judgment + needs:manual_check——不冒充机械）
    ent.append({
        "id": "SLMP-SUBHEADER", "kind": "frame_field",
        "name": "Subheader (request 0x5000 / response 0xD000, 3E binary frame)",
        "meaning": "3E 帧副头部：请求 0x5000（正常响应 0xD000、错误 0xD4/0xD5+信息——值来自消息图解，"
                   "pypdf 对图解列打散无法机械还原，须人工核对后再转为 mechanical。",
        "spec_ref": {"doc": "MELSEC iQ-F FX5 User's Manual (SLMP)", "section": "3.1 Subheader configuration",
                     "page": 19, "quote": "Subheader configuration", "provenance": "judgment",
                     "needs": "manual_check"},
        "provenance": "judgment", "needs": "manual_check",
    })

    return doc


def check(doc) -> int:
    """quote 反查：slmp.json 全部 mechanical 条目的引文须在同页文本中命中。"""
    from pypdf import PdfReader
    reader = PdfReader(str(PDF))
    pages = {i: norm(p.extract_text() or "") for i, p in enumerate(reader.pages, 1)}
    ok = bad = 0
    for e in doc["entries"]:
        if e.get("provenance") != "mechanical":
            continue
        sref = e["spec_ref"]
        q = NORM.sub(" ", sref["quote"]).strip()
        page = NORM.sub(" ", pages.get(sref["page"], ""))
        if q in page:
            ok += 1
        else:
            bad += 1
            print(f"  ✗ {e['id']}: p{sref['page']} 未命中「{q[:60]}…」")
    print(f"quote 反查：{ok}/{ok + bad} 命中（judgment 跳过 {sum(1 for e in doc['entries'] if e.get('provenance') != 'mechanical')}）")
    return 1 if bad else 0


def main() -> int:
    if "--check" in sys.argv:
        return check(json.loads(OUT.read_text(encoding="utf-8")))
    doc = build()
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    kinds = {}
    for e in doc["entries"]:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    print(f"slmp.json 重建：{len(doc['entries'])} 条 {kinds}")
    return check(doc)


if __name__ == "__main__":
    sys.exit(main())
