#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""外部真值锚点门禁（铁律4）：协议域的一手件必须钉在外部、且**没有被静默换过**。

清单 = knowledge/protocols/anchors.json（文件 → sha256 + size）。本门禁做三件事：

  1. **指纹重算**：对清单里每个文件重算 sha256（顺带核对 size），与在档值比对——
     任何一个不一致即 FAIL（一手件被换/被改 = 全域结论的地基塌了）。
  2. **再提取抽查**：对 Modbus AP PDF 用 knowledge/protocols/specs/pdf2txt.py 重新提取，
     输出文本哈希必须等于在档 txt 的哈希——证明「PDF→提取文本」链条未被篡改，
     quote 反查（check_modbus_quotes.py）所依赖的同源文本仍然同源。
  3. **URL 存活性**：focas inventcom 在线源默认只 WARN（CI 无网不误报）；
     ``--strict`` 时计入失败。

  **非入库区的处置**（2026-10-22 公开前审新增）：厂商/标准原件按本仓约定外置到
  ``../mcopilot-external/vendor_docs/``，本地产物在 ``out/``——两者在干净检出上
  **必然不在位**。这类条目：在位即核指纹（PASS），缺位记 **SKIP** 并写明
  "当前不可自动复核"，**不判 FAIL**（那会把"设计上不入库"误报成"缺件"）；
  但仓内跟踪文件缺位仍是结构性缺失（MISSING → 退出码 2），不放水。
  SKIP 会在汇总行单独喊出来——静默 skip 也算绿 = 最危险的失败模式。

用法：
    python scripts/gate_anchors.py             # 全部锚点检查
    python scripts/gate_anchors.py --strict    # URL 存活性计入失败
    python scripts/gate_anchors.py --list      # 只列锚点清单

退出码：
    0 = 无失败（可能含 SKIP：非入库区原件不在位，当次不可自动复核）
    1 = 任一指纹/再提取不一致（或 strict 下 URL 不可达）
    2 = 用法/配置错误（清单缺失、仓内锚点文件不存在等结构性问题）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "knowledge" / "protocols" / "anchors.json"
WORKROOT = ROOT / "out" / "gates"
URL_TIMEOUT_S = 10


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def emit(status: str, name: str, detail: str) -> None:
    """统一行格式：ANCHOR<TAB>状态<TAB>名<TAB>说明（与门禁族 RESULT 行同风格）。"""
    print(f"ANCHOR\t{status}\t{name}\t{detail}")


def _is_nonrepo(rel: str) -> bool:
    """判定锚点是否属"非入库区"（本地产物 out/ 或仓外原件 ../）。

    非入库区的条目在**干净检出上必然不在位**——这不是缺件，是设计。
    处置：在位就核指纹（PASS），缺位记 SKIP 并写明"当前不可自动复核"；
    仓内条目缺位仍是结构性缺失（MISSING → 退出码 2），不许一起放水。
    """
    r = rel.replace("\\", "/")
    return r.startswith("out/") or r.startswith("../")


def check_anchor(a: dict) -> tuple[str, str]:
    """核对单个锚点。返回 (状态, 说明)：状态 PASS / FAIL / MISSING / SKIP。"""
    rel = a["path"]
    p = ROOT / rel
    if not p.is_file():
        if _is_nonrepo(rel):
            return "SKIP", (f"{rel}：非入库区（按约定不随仓分发），当前不在位 → "
                            f"本锚点当前不可自动复核（size/sha256 在档，指纹待原件就位后复核）")
        return "MISSING", f"锚点文件不存在：{rel}"
    got = sha256_of(p)
    if a.get("size") is not None and p.stat().st_size != a["size"]:
        return "FAIL", (f"{rel}: size {p.stat().st_size} != 在档 {a['size']}")
    if got != a["sha256"].lower():
        return "FAIL", f"{rel}: sha256 {got} != 在档 {a['sha256']}"
    return "PASS", f"{rel}: sha256 一致"


def reextract_check(a: dict) -> tuple[str, str]:
    """再提取抽查：pdf2txt.py 重提取 → 输出哈希必须等于在档 txt 哈希。"""
    tool = ROOT / a["reextract_tool"]
    pdf = ROOT / a["reextract_from"]
    archived = ROOT / a["path"]
    if not tool.is_file() or not pdf.is_file():
        if not tool.is_file():
            return "FAIL", f"再提取输入缺失：tool={tool.name} 不存在"
        return "SKIP", (f"再提取原件不在位（{a['reextract_from']}：非入库区，当前不可自动复核）"
                        f"——提取链的同源性待原件就位后复核")
    workdir = Path(tempfile.mkdtemp(prefix="anchors_reextract_", dir=str(WORKROOT)))
    try:
        r = subprocess.run(
            [sys.executable, str(tool), str(workdir), str(pdf)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=240, cwd=str(ROOT))
        if r.returncode != 0:
            return "FAIL", f"再提取失败（退出码 {r.returncode}）：{(r.stdout + r.stderr)[-300:]}"
        out_txt = workdir / archived.name
        if not out_txt.is_file():
            return "FAIL", f"再提取未产出 {archived.name}"
        got = sha256_of(out_txt)
        if got != a["sha256"].lower():
            return "FAIL", (f"再提取哈希 {got} != 在档 {a['sha256']}"
                            f" —— 提取链与在档文本不再同源（pypdf 版本漂移或文本被改）")
        return "PASS", f"再提取抽查一致（{archived.name}，{archived.stat().st_size}B）"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def url_check(u: dict, strict: bool) -> tuple[str, str]:
    """URL 存活性：默认 WARN 不计失败；--strict 计失败。"""
    req = urllib.request.Request(u["url"], method="HEAD",
                                 headers={"User-Agent": "mcopilot-gate-anchors/1"})
    try:
        with urllib.request.urlopen(req, timeout=URL_TIMEOUT_S) as resp:
            code = resp.getcode()
        if 200 <= code < 400:
            return "WARN" if not strict else "PASS", f"{u['url']} -> HTTP {code}"
        return ("WARN" if not strict else "FAIL"), f"{u['url']} -> HTTP {code}"
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        msg = f"{u['url']} 不可达（{exc.__class__.__name__}）"
        return ("WARN" if not strict else "FAIL"), msg + ("" if strict else "（默认 WARN 不计失败）")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="外部真值锚点门禁（sha256 全清单 + 再提取抽查 + URL 存活）")
    ap.add_argument("--strict", action="store_true",
                    help="URL 存活性计入失败（默认 WARN，CI 无网不误报）")
    ap.add_argument("--list", action="store_true", help="只列锚点清单，不做检查")
    args = ap.parse_args(argv)

    if not MANIFEST.is_file():
        print(f"✗ 锚点清单缺失：{MANIFEST}")
        return 2
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    anchors = doc.get("anchors") or []
    if not anchors:
        print("✗ 锚点清单为空（清单本身坏了）")
        return 2

    if args.list:
        for a in anchors:
            emit("LIST", a["name"], f"{a['path']} role={a.get('role')}")
        for u in doc.get("url_liveness") or []:
            emit("LIST", u["name"], f"{u['url']} policy={u.get('policy')}")
        return 0

    WORKROOT.mkdir(parents=True, exist_ok=True)
    failed = 0
    skipped = 0
    reextract_done = 0
    for a in anchors:
        status, detail = check_anchor(a)
        if status == "MISSING":
            print(f"✗ 结构性缺失：{detail}")
            return 2
        emit(status, a["name"], detail)
        if status == "FAIL":
            failed += 1
        if status == "SKIP":
            skipped += 1
        if status == "PASS" and a.get("reextract_from"):
            reextract_done += 1
            status2, detail2 = reextract_check(a)
            emit(status2, f"{a['name']}#reextract", detail2)
            if status2 == "FAIL":
                failed += 1
            elif status2 == "SKIP":
                skipped += 1

    strict_tag = " --strict" if args.strict else ""
    for u in doc.get("url_liveness") or []:
        status, detail = url_check(u, args.strict)
        emit(status, u["name"], detail)
        if status == "FAIL":
            failed += 1

    total = len(anchors)
    print(f"锚点门禁：{total} 个锚点 + {reextract_done} 项再提取抽查"
          f" + {len(doc.get('url_liveness') or [])} 项 URL 存活（strict={args.strict}）"
          f" -> 失败 {failed}")
    if skipped:
        # 静默 skip 也算绿 = 最危险的失败模式：SKIP 必须自己喊出来，
        # 并说明这些锚点当前**不可自动复核**（指纹在档，但原件不在位）。
        print(f"⚠ 本次有 {skipped} 项锚点因原件不在位而 SKIP —— "
              f"它们的指纹在档（size/sha256），但**当前不可自动复核**；"
              f"不得把本次结果读作『全部已核』。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
