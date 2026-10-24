# -*- coding: utf-8 -*-
"""modbus.json 的 quote 反查复核（无裸提取红线，跨会话同纪律）。

遍历 knowledge/protocols/modbus.json（modbus_extract/1）中所有带 spec_ref 且
quote 非空的条目，quote 规范化（折叠全部空白，允许行折断点合并）后必须在
out/_protocols_extract/ 的提取文本（引文的同源文本，由 specs/pdf2txt.py 生成）
对应 PAGE 段中命中。judgment 项跳过并计数。**提取文本缺失时脚本自己先跑一次
pdf2txt.py**（干净检出 / CI 里 out/ 是空的，没有它等于一条都没查）。

跑法：python scripts/check_modbus_quotes.py   （退出码 0 = 全命中）
参数化（2026-10-21，向后兼容）：--json <路径> 指定被反查的知识库 JSON，
--txt-dir <目录> 指定提取文本目录；两者均缺省时行为与历史版本完全一致
（即本仓库 modbus.json + out/_protocols_extract/，门禁/负向用例按无参调用）。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

KB = ROOT / "knowledge" / "protocols" / "modbus.json"
TXT_DIR = ROOT / "out" / "_protocols_extract"

# spec_ref.doc 完整名 → 提取文本名关键词（pdf2txt.py 产物）
DOC_PDF = [
    ("V1.1b3", "Modbus_Application_Protocol_V1_1b3.txt"),
    ("V1.02", "Modbus_over_serial_line_V1_02.txt"),
    ("V1.0b", "Modbus_Messaging_Implementation_Guide_V1_0b.txt"),
]

NORM = re.compile(r"\s+")
PUNCT = re.compile(r"\s+([.,;:!?])")   # pdf2txt 词法把标点拆成独立 token（server \n . → server .）
SIG = re.compile(r"[^a-z0-9]+")        # 签名：连字符断行（16 - bit→16bit）、词中断行（gate way→gateway）同化
PAGE_MARK = re.compile(r"===== \[PAGE (\d+)\] =====")


def norm(s: str) -> str:
    return PUNCT.sub(r"\1", NORM.sub(" ", s)).strip()


def sig(s: str) -> str:
    return SIG.sub("", s.lower())


def noisy_hit(qsig: str, psig: str) -> bool:
    """脏字符容错：引文签名从中点切两半，两半都在页签名中即视为「同源含提取噪声」。
    （提取器偶发词内插脏字符如 the e implied；编造引文的两半恰好都落在同页的概率可忽略。）"""
    if len(qsig) < 8:
        return False
    mid = len(qsig) // 2
    return qsig[:mid] in psig and qsig[mid:] in psig


def _load_pages(txt_name: str) -> dict[int, str]:
    """读提取文本 → {物理页: 页文本}。"""
    pages: dict[int, str] = {}
    raw = (TXT_DIR / txt_name).read_text(encoding="utf-8")
    cur, buf = 0, []
    for line in raw.splitlines():
        m = PAGE_MARK.match(line.strip())
        if m:
            if cur:
                pages[cur] = "\n".join(buf)
            cur, buf = int(m.group(1)), []
        else:
            buf.append(line)
    if cur:
        pages[cur] = "\n".join(buf)
    return pages


def walk(obj, path=""):
    """递归产出 (路径, 宿主对象, spec_ref)。"""
    if isinstance(obj, dict):
        ref = obj.get("spec_ref")
        if isinstance(ref, dict) and ref.get("quote"):
            yield path, obj, ref
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


def ensure_extract() -> None:
    """缺提取文本就跑一次 pdf2txt.py。

    为什么必须自动跑：提取文本在 out/ 下（gitignored），**干净检出/CI 里没有** ——
    没有它，quote 反查一条都查不了，整条门禁在 CI 上必红（不是「查出来有问题」，
    是「根本没查」）。pdf2txt.py 只用标准库（re/sys/zlib），不引入新依赖。
    """
    need = [n for _, n in DOC_PDF if not (TXT_DIR / n).exists()]
    if not need:
        return
    specs = ROOT / "knowledge" / "protocols" / "specs"          # 提取工具仍在仓内
    # 原件按本仓约定外置（仓内不存厂商/标准一手件）：优先仓外约定位，找不到再看仓内历史位置
    ext = ROOT.parent / "mcopilot-external" / "vendor_docs" / "protocol_specs"
    pdfs = sorted(ext.glob("*.pdf")) or sorted(specs.glob("*.pdf"))
    TXT_DIR.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, str(specs / "pdf2txt.py"), str(TXT_DIR)]
                       + [str(p) for p in pdfs],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    still = [n for n in need if not (TXT_DIR / n).exists()]
    if still:
        print(f"✗ 规范文本提取失败，缺：{still}\n{r.stdout[-800:]}{r.stderr[-800:]}",
              file=sys.stderr)


def _parse_args(argv):
    """参数化接口：缺省值即历史硬编码路径（无参调用 = 原行为，门禁不受影响）。"""
    ap = argparse.ArgumentParser(
        description="modbus.json 的 quote 反查复核（退出码 0 = 全命中）")
    ap.add_argument("--json", type=Path, default=KB,
                    help="被反查的知识库 JSON（缺省 knowledge/protocols/modbus.json）")
    ap.add_argument("--txt-dir", type=Path, default=TXT_DIR,
                    help="pdf2txt.py 提取文本目录（缺省 out/_protocols_extract）")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    global KB, TXT_DIR
    args = _parse_args(argv)
    KB, TXT_DIR = args.json, args.txt_dir
    ensure_extract()
    doc = json.loads(KB.read_text(encoding="utf-8"))
    total = skipped = strict = sig_hit = noisy = 0
    misses = []

    for path, host, ref in walk(doc):
        # judgment 项与 needs:manual_check 项的 quote 允许是概括/待核对描述，不做逐字反查
        if host.get("provenance") == "judgment" or host.get("needs") == "manual_check" \
                or ref.get("provenance") == "judgment":
            skipped += 1
            continue
        target = None
        for key, pdf in DOC_PDF:
            if key in ref.get("doc", ""):
                target = pdf
                break
        if target is None:
            misses.append(f"{path}: 未映射规范 {ref.get('doc')!r}")
            continue
        page = _load_pages(target).get(ref["page"])
        if page is None:
            misses.append(f"{path}: 页 {ref['page']} 超出 {target} 页范围")
            continue
        total += 1
        page_sig = sig(page)
        if norm(ref["quote"]) in norm(page):
            strict += 1
        elif sig(ref["quote"]) in page_sig:
            sig_hit += 1
        elif noisy_hit(sig(ref["quote"]), page_sig):
            noisy += 1
        else:
            misses.append(f"{path}: p{ref['page']} 引文与页面文本无同源证据「{norm(ref['quote'])[:60]}…」")

    hit = strict + sig_hit + noisy
    print(f"quote 反查：{hit}/{total} 通过（严格逐字 {strict}、签名同源 {sig_hit}、噪声容错 {noisy}；"
          f"judgment/manual_check 跳过 {skipped}）")
    for m in misses:
        print("  ✗", m)
    return 1 if misses else 0


class _Page:
    """单个 PDF 的页文本缓存（惰性，仅取所需页）。"""

    def __init__(self, pdf: Path):
        from pypdf import PdfReader
        self.reader = PdfReader(str(pdf))
        self._pages: dict[int, str] = {}

    def page_text(self, pno: int):
        if pno not in self._pages:
            if not (1 <= pno <= len(self.reader.pages)):
                return None
            self._pages[pno] = self.reader.pages[pno - 1].extract_text() or ""
        return self._pages[pno]


def _load(pdf_name: str) -> _Page:
    if not hasattr(main, "_cache"):
        main._cache = {}
    if pdf_name not in main._cache:
        main._cache[pdf_name] = _Page(SPEC_DIR / pdf_name)
    return main._cache[pdf_name]


if __name__ == "__main__":
    sys.exit(main())
