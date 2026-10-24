#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_trae_pinvoke.py —— 「上位机代码工厂」P/Invoke 声明与官方真值对撞工具（长期使用）

用途
----
扫描 Trae 生成器产物里的 C# 适配器源码（src/Adapters/*.cs），把每一条
[DllImport] 声明逐条拿去和三层外部真值比对：

  1) DLL PE 导出表   : knowledge/sdks/official_api/dll_exports.csv
                        列: DLL, 位数, 函数名, 已导出, 变体
                        —— 只有「已导出=1」的符号才算真正能被 P/Invoke 调用；
                           「已导出=0」表示符号在但没导出（不可调用）。
  2) 官方 C# 绑定    : zmotion.csv / gts.csv / leisai.csv
  3) 官方 C 头文件   : zmotion_cpp.csv / gts_hdr.csv / leisai_cpp.csv

判定三态（判据只有一条：官方真值里存在）
------------------------------
  双绿    ok           —— PE 导出表有（已导出=1）且 官方 C#/C 头文件里有
  需自证  needs_proof  —— PE 导出表有，但官方 C#/C 头文件里没有
                          （说明签名只能自己从 PE 侧自证，必须人工确认）
  不可用  missing      —— PE 导出表（已导出=1）里没有，官方绑定里也没有
                          —— 典型：函数名臆造，或 DllImport 写错了 DLL 名

另外单独报告「DLL 名本身不存在于 PE 导出表」的情况（整卡级别的致命错误）。

输出
----
  * 默认：人读文本报告（按品牌分组 + 明细 + 汇总）
  * --json：机器可读结果（供 CI / 回归对比使用）

示例
----
  python verify_trae_pinvoke.py
  python verify_trae_pinvoke.py --json
  python verify_trae_pinvoke.py --json > verify.json
  python verify_trae_pinvoke.py --strict        # 有 missing 时退出码 1

作者备注：函数名匹配用「规范化后的精确匹配」，不用 \b 词边界正则
（GT_SetTrapPrm 里下划线是单词字符，词边界会漏配）。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import OrderedDict, defaultdict

# ---------------------------------------------------------------- 默认路径
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# trae_factory 仓的位置：环境变量 TRAE_FACTORY_DIR 优先，其次按同级兄弟目录找
def _sib_trae():
    """工厂仓目录：新名优先、旧名兜底（目录 2026-10-24 改名，项目标识不变）。"""
    base = os.path.dirname(_REPO)
    for n in ("forensics-code-factory", "trae_factory"):
        p = os.path.join(base, n)
        if os.path.isdir(p):
            return p
    return os.path.join(base, "forensics-code-factory")


_TRAE = os.environ.get("TRAE_FACTORY_DIR") or _sib_trae()
DEFAULT_TRAE_OUT = os.path.join(_TRAE, "out")
DEFAULT_KNOWLEDGE = os.path.join(_REPO, "knowledge", "sdks", "official_api")

# 品牌目录名（out/mc_<brand>）-> 官方真值里的 DLL 名
BRAND_DLL = OrderedDict(
    [
        ("gts", "gts.dll"),
        ("leadshine", "LTDMC.dll"),
        ("zmotion", "zauxdll.dll"),
        ("gaochuan", None),   # 骨架，无 DllImport
        ("softwin", None),    # 骨架，无 DllImport
    ]
)

# DLL 名 -> 品牌（一个适配器文件属于唯一品牌，mc_all 里也会出现同一份文件）
BRAND_BY_DLL = {
    "gts.dll": "gts",
    "ltdmc.dll": "leadshine",
    "zauxdll.dll": "zmotion",
    "acs.spiiplusnet.dll": "acs",
}

# 适配器源文件名 -> 品牌（DllImport 里 DLL 名写错时仍可归类品牌）
BRAND_BY_ADAPTER_FILE = {
    "googolgtscontroller.cs": "gts",
    "leadshinedmccontroller.cs": "leadshine",
    "zmotionzmccontroller.cs": "zmotion",
    "acsspiipluscontroller.cs": "acs",
    "softwincontroller.cs": "softwin",
    "gaochuancontroller.cs": "gaochuan",
}

# 官方 C# 绑定（层 2）与 官方 C 头文件（层 3）文件
CS_BINDINGS = ["zmotion.csv", "gts.csv", "leisai.csv"]
C_HEADERS = ["zmotion_cpp.csv", "gts_hdr.csv", "leisai_cpp.csv"]

# 状态常量
OK = "ok"                    # 双绿
NEEDS_PROOF = "needs_proof"  # 需自证（只在导出表）
MISSING = "missing"          # 不可用（不存在）

STATUS_CN = {OK: "双绿", NEEDS_PROOF: "需自证", MISSING: "不可用"}


# ---------------------------------------------------------------- 工具函数
def read_csv_rows(path):
    """读 CSV，兼容 BOM，返回 (行号, dict)。行号从 1 开始，含表头行。"""
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for idx, row in enumerate(reader, start=2):  # 2 = 表头之后的第一行
            rows.append((idx, row))
    return rows


def normalize_export_name(name):
    """PE 导出名规范化：32 位 stdcall 会写成 _Func@12，去掉前导 _ 与 @N 后缀。

    只用于「找得到 / 找不到」的判断；报告里始终给出原始导出名。
    """
    if name is None:
        return ""
    n = name.strip()
    if n.startswith("_"):
        n = n[1:]
    n = re.sub(r"@\d+$", "", n)
    return n


def dll_key(dll):
    return (dll or "").strip().lower()


# ---------------------------------------------------------------- 真值装载
class Truth(object):
    """三层官方真值的内存索引。"""

    def __init__(self, knowledge_dir):
        self.knowledge_dir = knowledge_dir
        self.exports = OrderedDict()      # dll(lower) -> {norm_name: [rowinfo,...]}
        self.export_rows = OrderedDict()   # dll(lower) -> [rowinfo,...]
        self.export_dlls = set()           # PE 导出表里出现过的 DLL 名（小写）
        self.bindings = defaultdict(dict)  # dll(lower) -> {name: [(file,line,proto)]}
        self.headers = defaultdict(dict)    # dll(lower) -> {name: [(file,line,proto)]}
        # 厂商官方 C# 绑定的返回类型（同一层语言，C# 声明该对标的就是它）
        # dll(lower) -> {name: [{ret, variant, params, src}, ...]}
        self.binding_returns = defaultdict(lambda: defaultdict(list))
        self.binding_files = []
        self.header_files = []
        self._load_exports()
        self._load_api_tables(CS_BINDINGS, self.bindings, self.binding_files)
        self._load_api_tables(C_HEADERS, self.headers, self.header_files)
        self._load_binding_returns()

    # -- 厂商 C# 绑定的返回类型 ------------------------------------------
    def _load_binding_returns(self):
        """binding_returns.csv —— 从厂商官方 C# 绑定源码抽出的返回类型真值。

        为什么必须用这一层而不是 C 头文件：
        C 头文件是 C 语言，`long` 在 Windows(LLP64) 是 32 位；C# 的 `long` 是 Int64。
        拿 C# 声明去比 C 头文件的返回类型会口径错位。
        厂商自己的 C# 绑定才是 C# 声明该对标的那一层
        （雷赛 LTDMC.cs:891 把 C 的 long 映射成 Int32）。
        """
        path = os.path.join(self.knowledge_dir, "binding_returns.csv")
        if not os.path.isfile(path):
            return
        for lineno, row in read_csv_rows(path):
            dll = (row.get("DLL") or "").strip()
            fname = (row.get("函数名") or "").strip()
            if not dll or not fname:
                continue
            self.binding_returns[dll_key(dll)][fname].append({
                "file": "binding_returns.csv",
                "line": lineno,
                "ret": (row.get("返回类型") or "").strip(),
                "variant": (row.get("变体") or "").strip(),
                "params": (row.get("参数表") or "").strip(),
                "src": (row.get("源文件") or "").strip(),
            })

    # -- PE 导出表 ------------------------------------------------------
    def _load_exports(self):
        path = os.path.join(self.knowledge_dir, "dll_exports.csv")
        if not os.path.isfile(path):
            raise SystemExit("[FATAL] 找不到 PE 导出表真值: %s" % path)
        for lineno, row in read_csv_rows(path):
            dll = (row.get("DLL") or "").strip()
            fname = (row.get("函数名") or "").strip()
            if not dll or not fname:
                continue
            key = dll_key(dll)
            self.export_dlls.add(key)
            info = {
                "file": "dll_exports.csv",
                "line": lineno,
                "dll": dll,
                "bits": (row.get("位数") or "").strip(),
                "name": fname,
                "exported": (row.get("已导出") or "").strip(),
                "variant": (row.get("变体") or "").strip(),
            }
            self.export_rows.setdefault(key, []).append(info)
            self.exports.setdefault(key, {}).setdefault(
                normalize_export_name(fname), []
            ).append(info)

    # -- 官方绑定 / 头文件 ---------------------------------------------
    def _load_api_tables(self, filenames, target, loaded):
        for fname in filenames:
            path = os.path.join(self.knowledge_dir, fname)
            if not os.path.isfile(path):
                continue
            loaded.append(fname)
            for lineno, row in read_csv_rows(path):
                dll = (row.get("DLL") or "").strip()
                name = (row.get("函数名") or "").strip()
                proto = (row.get("官方原型") or "").strip()
                if not name:
                    continue
                key = dll_key(dll)
                bucket = target[key]
                bucket.setdefault(name, []).append((fname, lineno, proto))

    # -- 查询 ----------------------------------------------------------
    def export_hits(self, dll, func):
        """PE 导出表命中：返回 (已导出=1 的行, 已导出=0 的行)。"""
        key = dll_key(dll)
        hits = self.exports.get(key, {}).get(func, [])
        exported = [h for h in hits if h["exported"] == "1"]
        not_exported = [h for h in hits if h["exported"] != "1"]
        return exported, not_exported

    def binding_hits(self, dll, func):
        return self.bindings.get(dll_key(dll), {}).get(func, [])

    def header_hits(self, dll, func):
        return self.headers.get(dll_key(dll), {}).get(func, [])


# ---------------------------------------------------------------- 源码扫描
# [DllImport("xxx.dll", ...)] 后面可能跟若干 [xxx] 特性和 extern 声明
DLLIMPORT_RE = re.compile(
    r"\[DllImport\(\s*\"(?P<dll>[^\"]+)\"\s*(?P<attrs>[^\]]*)\)\]"
    r"(?P<between>(?:\s*\[[^\]]*\])*)"
    r"\s*private\s+static\s+extern\s+(?P<ret>[\w\.\[\]\?<>,\s]+?)\s+"
    r"(?P<name>\w+)\s*\((?P<args>[^;]*?)\)\s*;",
    re.S,
)


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


# ---------------------------------------------------------------- 签名比对
# 参数比对用官方 C# 绑定（与 C# 声明同一种类型语言）；
# 返回类型比对用官方 C 头文件（绑定 CSV 的原型列不给返回类型）。
#
# 宽度归一口径：
#   * C 的 long 在 Windows(LLP64) 是 32 位 —— 雷赛官方 C# 绑定把
#     dmc_pmove 的 long dist 写成 Int32，与本口径一致，故 long -> i32。
#   * 指针 / 结构体 / string 一律记为 None（非标量），只核对参数个数，
#     不硬比宽度——否则 C 的 `char *` 与 C# 的 `string` 会误报。

CS_TYPE_MAP = {
    "sbyte": "i8", "byte": "u8", "short": "i16", "ushort": "u16",
    "int": "i32", "uint": "u32", "long": "i64", "ulong": "u64",
    "float": "f32", "double": "f64", "bool": "i32", "char": "i8",
    "int16": "i16", "uint16": "u16", "int32": "i32", "uint32": "u32",
    "int64": "i64", "uint64": "u64", "single": "f32", "double": "f64",
    "boolean": "i32", "char": "i8", "intptr": "ptr", "uintptr": "ptr",
    "string": None, "object": None, "void": "void",
}

C_TYPE_MAP = {
    "short": "i16", "unsigned short": "u16", "int": "i32",
    "unsigned int": "u32", "unsigned": "u32", "long": "i32",
    "unsigned long": "u32", "long long": "i64",
    "unsigned long long": "u64", "float": "f32", "double": "f64",
    "void": "void", "bool": "i32", "char": "i8", "signed char": "i8",
    "unsigned char": "u8",
    "WORD": "u16", "DWORD": "u32", "BYTE": "u8", "CHAR": "i8",
    "INT": "i32", "UINT": "u32", "LONG": "i32", "ULONG": "u32",
    "BOOL": "i32", "FLOAT": "f32", "DOUBLE": "f64",
}

MODIFIERS = ("ref", "out", "in")


def _split_params(text):
    """按顶层逗号切分参数表（不切嵌套的 <> 与 ()）。"""
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch in "<([":
            depth += 1
        elif ch in ">)]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


def _strip_modifier(tok):
    for m in MODIFIERS:
        if tok.lower() == m:
            return True
    return False


def _width(tok, table):
    """一个类型记号 -> 宽度标识；认不出来返回 None（非标量）。"""
    t = tok.strip().rstrip("*").strip()
    if not t:
        return None
    if t.endswith("[]"):
        t = t[:-2].strip()
    low = t.lower()
    for k, v in table.items():
        if k.lower() == low:
            return v
    return None


def parse_cs_decl_args(args_text):
    """C# 声明的实参表 -> [(宽度 or None, 是否 ref/out), ...]。

    形如 'ushort cardNo, ref TJogPrm pPrm'：类型 = 去掉最后一个参数名后的部分。
    """
    text = (args_text or "").strip()
    if not text:
        return []
    out = []
    for p in _split_params(text):
        p = re.sub(r"\[[^\]]*\]", "", p).strip()          # 去掉 [MarshalAs(...)]
        p = re.sub(r"\[[^\]]*\]\s*$", "", p).strip()      # 去掉数组维度
        if not p:
            continue
        toks = p.split()
        if not toks:
            continue
        by_ref = _strip_modifier(toks[0])
        type_part = " ".join(toks[:-1]) if len(toks) > 1 else toks[0]
        out.append((_width(type_part, CS_TYPE_MAP), by_ref))
    return out


def parse_binding_proto(proto):
    """官方 C# 绑定原型 'dmc_pmove(UInt16,UInt16,Int32,UInt16)' -> 宽度列表。"""
    if not proto:
        return None
    m = re.search(r"\((.*)\)\s*$", proto.strip(), flags=re.S)
    if not m:
        return None
    inner = m.group(1).strip()
    if not inner:
        return []
    out = []
    for p in _split_params(inner):
        p = p.strip()
        if not p:
            continue
        by_ref = _strip_modifier(p.split()[0])
        toks = p.replace("*", " ").split()
        if not toks:
            continue
        # 绑定原型不带参数名；若首 token 是修饰符则类型是前两个 token
        if by_ref and len(toks) > 1:
            type_part = toks[0] + " " + toks[1]
        else:
            type_part = toks[0]
        out.append((_width(type_part, CS_TYPE_MAP), by_ref))
    return out


def parse_c_return(proto):
    """C 头文件原型的返回类型 -> 宽度 or None（原型没给返回类型时返回 'unknown'）。"""
    if not proto:
        return "unknown", None
    p = proto.strip()
    m = re.search(r"\((.*)\)\s*$", p, flags=re.S)
    if not m:
        return "unknown", None
    head = p[: m.start()].strip()
    toks = head.split()
    # C 原型里 "<返回类型> <函数名>(...)"；只有函数名一个 token = 没给返回类型
    if len(toks) < 2:
        return "unknown", None
    ret = toks[0]
    if ret in ("void",):
        return "known", "void"
    return "known", _width(ret, C_TYPE_MAP)


def compare_signature(decl, binding_rows, header_rows):
    """把一条 C# 声明与官方原型比对。

    返回 (status, detail)：
      MATCH          参数个数一致，且所有双方都能定宽的参数宽度一致
      ARITY_MISMATCH 参数个数与官方原型不一致
      TYPE_MISMATCH  个数一致但有参数宽度对不上
      NO_PROTO       官方真值里没有可比对的原型
    """
    binding_proto = binding_rows[0]["proto"] if binding_rows else None
    if not binding_proto:
        return "NO_PROTO", {"reason": "官方 C# 绑定里没有这一条的原型，无法比对签名"}
    want = parse_binding_proto(binding_proto)
    got = parse_cs_decl_args(decl.get("args"))
    if want is None:
        return "NO_PROTO", {"reason": "官方原型解析不出来"}
    if len(want) != len(got):
        return "ARITY_MISMATCH", {
            "declared": len(got), "official": len(want),
            "declared_types": [w for w, _ in got],
            "official_types": [w for w, _ in want],
        }
    mismatches = []
    compared = 0
    for idx, ((gw, gb), (ww, wb)) in enumerate(zip(got, want)):
        if gw is None or ww is None:
            continue                      # 非标量：只核个数，不比宽度
        compared += 1
        if gw != ww or gb != wb:
            mismatches.append({
                "index": idx,
                "declared": gw, "official": ww,
                "declared_by_ref": gb, "official_by_ref": wb,
            })
    detail = {
        "official_proto": binding_proto,
        "compared_params": compared,
        "non_scalar_params": len(got) - compared,
        "mismatches": mismatches,
    }
    if mismatches:
        return "TYPE_MISMATCH", detail
    detail["return_type"] = decl.get("return_type")
    return "MATCH", detail


def check_return_type(decl, header_rows, binding_ret_rows=None):
    """返回类型比对。

    优先用**厂商官方 C# 绑定**的返回类型（同一层语言，C# 声明该对标的就是它）；
    该层没有记录时才退回 C 头文件，并按 Windows LLP64 口径解释 C 的 `long`（32 位）。
    """
    declared = (decl.get("return_type") or "").strip()
    dw = _width(declared, CS_TYPE_MAP)

    # 第一优先：官方 C# 绑定的返回类型
    if binding_ret_rows:
        rets = {r["ret"] for r in binding_ret_rows}
        variants = sorted({r["variant"] for r in binding_ret_rows})
        if len(rets) == 1:
            official = next(iter(rets))
            ow = _width(official, CS_TYPE_MAP)
            note = {"declared": declared, "official": official,
                    "official_source": "厂商官方C#绑定 " + binding_ret_rows[0]["src"],
                    "variants": variants}
            if dw is None or ow is None:
                note["status"] = "SKIP"
                return note
            note["status"] = "MATCH" if dw == ow else "MISMATCH"
            return note
        note = {"declared": declared, "official": sorted(rets),
                "official_source": "厂商官方C#绑定（多变体返回类型不一致）",
                "variants": variants, "status": "SKIP"}
        return note

    # 退回：C 头文件（LP64 → LLP64 口径：C 的 long 是 32 位）
    proto = header_rows[0]["proto"] if header_rows else None
    known, width = parse_c_return(proto)
    if known != "known":
        return {"status": "NO_TRUTH", "note": "官方 C 头文件原型未给返回类型，且厂商 C# 绑定无记录"}
    if dw is None or width is None:
        return {"status": "SKIP", "declared": declared, "official": proto}
    return {"status": "MATCH" if dw == width else "MISMATCH",
            "declared": declared, "official": proto}


def scan_cs_file(path):
    """扫描一个 .cs 文件里的所有 DllImport 声明。"""
    with open(path, "r", encoding="utf-8-sig") as fh:
        text = fh.read()
    decls = []
    for m in DLLIMPORT_RE.finditer(text):
        attrs = m.group("attrs") or ""
        cc = "StdCall"
        cmm = re.search(r"CallingConvention\s*=\s*CallingConvention\.(\w+)", attrs)
        if cmm:
            cc = cmm.group(1)
        chars = ""
        csm = re.search(r"CharSet\s*=\s*CharSet\.(\w+)", attrs)
        if csm:
            chars = csm.group(1)
        decls.append(
            {
                "file": path,
                "line": line_of(text, m.start()),
                "dll": m.group("dll").strip(),
                "function": m.group("name").strip(),
                "return_type": " ".join(m.group("ret").split()),
                "args": " ".join((m.group("args") or "").split()),
                "calling_convention": cc,
                "charset": chars,
            }
        )
    return decls


def find_adapter_files(out_dir):
    """找出 out/mc_*/src/Adapters/*.cs（不含 samples / Core）。

    mc_all 套件放在最后扫：同一份适配器在多套件里重复出现时，
    报告优先引用单品牌套件里的那份。
    """
    files = []
    if not os.path.isdir(out_dir):
        return files
    kits = [k for k in sorted(os.listdir(out_dir)) if k.startswith("mc_")]
    kits.sort(key=lambda k: (k == "mc_all", k))
    for kit in kits:
        adir = os.path.join(out_dir, kit, "src", "Adapters")
        if not os.path.isdir(adir):
            continue
        for name in sorted(os.listdir(adir)):
            if name.lower().endswith(".cs"):
                files.append((kit, os.path.join(adir, name)))
    return files


# ---------------------------------------------------------------- 核对
def verify(out_dir, knowledge_dir):
    truth = Truth(knowledge_dir)
    kits = OrderedDict()
    all_decls = []

    for kit, path in find_adapter_files(out_dir):
        file_brand = BRAND_BY_ADAPTER_FILE.get(os.path.basename(path).lower())
        for d in scan_cs_file(path):
            d["kit"] = kit
            # 品牌归属：先看 DLL 名，再退回适配器源文件名（mc_all 里同一文件会重复出现）
            d["brand"] = (
                BRAND_BY_DLL.get(dll_key(d["dll"]))
                or file_brand
                or kit[3:]
            )
            d["file"] = path
            all_decls.append(d)

    # 逐条判定
    for d in all_decls:
        dll, func = d["dll"], d["function"]
        exported, not_exported = truth.export_hits(dll, func)
        binding = truth.binding_hits(dll, func)
        header = truth.header_hits(dll, func)
        d["in_exports"] = bool(exported)
        d["in_binding"] = bool(binding)
        d["in_header"] = bool(header)
        d["export_rows"] = [
            {"file": h["file"], "line": h["line"], "bits": h["bits"],
             "name": h["name"], "variant": h["variant"]}
            for h in exported
        ]
        d["not_exported_rows"] = [
            {"file": h["file"], "line": h["line"], "bits": h["bits"],
             "name": h["name"], "variant": h["variant"]}
            for h in not_exported
        ]
        d["binding_rows"] = [
            {"file": f, "line": ln, "proto": pr} for (f, ln, pr) in binding
        ]
        d["header_rows"] = [
            {"file": f, "line": ln, "proto": pr} for (f, ln, pr) in header
        ]
        d["dll_known"] = dll_key(dll) in truth.export_dlls

        # 签名比对：参数用官方 C# 绑定原型，返回类型优先用厂商官方 C# 绑定的返回类型
        sig_status, sig_detail = compare_signature(d, d["binding_rows"], d["header_rows"])
        d["signature_status"] = sig_status
        d["signature_detail"] = sig_detail
        bret = truth.binding_returns.get(dll_key(dll), {}).get(func, [])
        d["binding_return_rows"] = bret
        d["return_type_check"] = check_return_type(d, d["header_rows"], bret)
        # 变体口径：该函数在厂商 C# 绑定的不同变体间参数表是否一致
        d["variant_conflict"] = (
            sorted({r["params"] for r in bret}) if len({r["params"] for r in bret}) > 1 else []
        )

        if exported and binding:
            d["status"] = OK
            d["reason"] = "PE 导出表已导出 + 官方 C# 绑定存在"
        elif exported:
            d["status"] = NEEDS_PROOF
            d["reason"] = "PE 导出表已导出，但官方 C#/C 头文件未收录，签名需人工自证"
        else:
            d["status"] = MISSING
            if not d["dll_known"]:
                d["reason"] = "DLL 名在 PE 导出表中不存在（该库根本没有这个 DLL）"
            elif not_exported:
                d["reason"] = "符号存在于 PE 表但「已导出=0」，无法 P/Invoke 调用"
            else:
                d["reason"] = "官方真值（PE 导出表 / C# 绑定 / C 头文件）中均无此函数"

    # 去重：同一 (dll, function) 在多个套件里重复出现（mc_all 含全部适配器）
    unique = OrderedDict()
    for d in all_decls:
        key = (dll_key(d["dll"]), d["function"])
        if key not in unique:
            unique[key] = d
    unique_list = list(unique.values())

    def summarize(items):
        c = {OK: 0, NEEDS_PROOF: 0, MISSING: 0}
        for it in items:
            c[it["status"]] += 1
        return c

    by_brand = OrderedDict()
    brand_order = list(BRAND_DLL.keys())
    for d in unique_list:
        if d["brand"] not in brand_order:
            brand_order.append(d["brand"])
    for brand in brand_order:
        items = [d for d in unique_list if d["brand"] == brand]
        by_brand[brand] = {
            "brand": brand,
            "dll": BRAND_DLL.get(brand),
            "declarations": len(items),
            "ok": sum(1 for i in items if i["status"] == OK),
            "needs_proof": sum(1 for i in items if i["status"] == NEEDS_PROOF),
            "missing": sum(1 for i in items if i["status"] == MISSING),
        }

    return {
        "tool": "verify_trae_pinvoke.py",
        "truth_sources": {
            "pe_exports": "dll_exports.csv",
            "cs_bindings": CS_BINDINGS,
            "c_headers": C_HEADERS,
            "binding_returns": "binding_returns.csv（厂商官方C#绑定的返回类型与变体）",
            "knowledge_dir": knowledge_dir,
        },
        "out_dir": out_dir,
        "totals": {
            "occurrences": len(all_decls),
            "declarations": len(unique_list),
            "ok": sum(1 for i in unique_list if i["status"] == OK),
            "needs_proof": sum(1 for i in unique_list if i["status"] == NEEDS_PROOF),
            "missing": sum(1 for i in unique_list if i["status"] == MISSING),
        },
        "signature_totals": {
            "match": sum(1 for i in unique_list if i.get("signature_status") == "MATCH"),
            "arity_mismatch": sum(1 for i in unique_list if i.get("signature_status") == "ARITY_MISMATCH"),
            "type_mismatch": sum(1 for i in unique_list if i.get("signature_status") == "TYPE_MISMATCH"),
            "no_proto": sum(1 for i in unique_list if i.get("signature_status") == "NO_PROTO"),
            "return_match": sum(1 for i in unique_list if i.get("return_type_check", {}).get("status") == "MATCH"),
            "return_no_truth": sum(1 for i in unique_list if i.get("return_type_check", {}).get("status") == "NO_TRUTH"),
            "return_mismatch": sum(1 for i in unique_list if i.get("return_type_check", {}).get("status") == "MISMATCH"),
        },
        "variant_conflict_total": sum(1 for i in unique_list if i.get("variant_conflict")),
        "by_brand": by_brand,
        "declarations_detail": unique_list,
        "occurrences_detail": all_decls,
    }


# ---------------------------------------------------------------- 输出
def print_text_report(res):
    t = res["totals"]
    print("=" * 78)
    print("P/Invoke 官方真值对撞报告 —— Trae「上位机代码工厂」产物")
    print("=" * 78)
    print("PE 导出表 : %s" % res["truth_sources"]["pe_exports"])
    print("官方 C# 绑定: %s" % ", ".join(res["truth_sources"]["cs_bindings"]))
    print("官方 C 头文件: %s" % ", ".join(res["truth_sources"]["c_headers"]))
    print("扫描目录 : %s" % res["out_dir"])
    print("")
    print("声明总数(去重) : %d   (文件内出现次数 %d)"
          % (t["declarations"], t["occurrences"]))
    print("双绿(ok)        : %d" % t["ok"])
    print("需自证(导出表有) : %d" % t["needs_proof"])
    print("不可用(missing) : %d" % t["missing"])
    st = res.get("signature_totals") or {}
    if st:
        print("")
        print("签名比对(参数用官方C#绑定 / 返回类型用厂商官方C#绑定)")
        print("  参数签名 MATCH           : %d" % st.get("match", 0))
        print("  参数个数不一致          : %d" % st.get("arity_mismatch", 0))
        print("  参数宽度不一致          : %d" % st.get("type_mismatch", 0))
        print("  无原型可比对            : %d" % st.get("no_proto", 0))
        print("  返回类型一致            : %d" % st.get("return_match", 0))
        print("  返回类型无真值依据      : %d" % st.get("return_no_truth", 0))
        print("  返回类型不一致          : %d" % st.get("return_mismatch", 0))
        vc = res.get("variant_conflict_total", 0)
        if vc:
            print("  ⚠ 变体间参数表冲突(单卡/多卡同DLL同符号) : %d 条" % vc)
    print("")
    print("-" * 78)
    print("按品牌")
    print("-" * 78)
    print("%-12s %-12s %8s %6s %8s %8s" % ("品牌", "DLL", "声明数", "双绿", "需自证", "不可用"))
    for brand, st in res["by_brand"].items():
        print("%-12s %-12s %8d %6d %8d %8d"
              % (brand, st["dll"] or "(骨架)", st["declarations"],
                 st["ok"], st["needs_proof"], st["missing"]))
    print("")

    for status in (MISSING, NEEDS_PROOF):
        items = [d for d in res["declarations_detail"] if d["status"] == status]
        if not items:
            continue
        print("-" * 78)
        print("%s 明细 (%d 条)" % (STATUS_CN[status], len(items)))
        print("-" * 78)
        for d in items:
            print("  [%s] %s!%s" % (d["brand"], d["dll"], d["function"]))
            print("        位置: %s:%d" % (d["file"], d["line"]))
            print("        签名: %s %s(%s)"
                  % (d["return_type"], d["function"], d["args"]))
            print("        判定: %s" % d["reason"])
            if d["export_rows"]:
                h = d["export_rows"][0]
                print("        导出表: %s:%d %s 位数=%s 变体=%s"
                      % (h["file"], h["line"], h["name"], h["bits"], h["variant"]))
            if d["not_exported_rows"]:
                h = d["not_exported_rows"][0]
                print("        仅符号: %s:%d %s (已导出=0)"
                      % (h["file"], h["line"], h["name"]))
            if d["binding_rows"]:
                for b in d["binding_rows"]:
                    print("        C#绑定: %s:%d %s" % (b["file"], b["line"], b["proto"]))
            if d["header_rows"]:
                for b in d["header_rows"]:
                    print("        C头文件: %s:%d %s" % (b["file"], b["line"], b["proto"]))
            print("")

    ok_items = [d for d in res["declarations_detail"] if d["status"] == OK]
    if ok_items:
        print("-" * 78)
        print("双绿明细 (%d 条)" % len(ok_items))
        print("-" * 78)
        for d in ok_items:
            b = d["binding_rows"][0] if d["binding_rows"] else None
            print("  [OK] %-10s %s!%s  <- %s"
                  % (d["brand"], d["dll"], d["function"],
                     ("%s:%d" % (b["file"], b["line"])) if b else "PE导出表"))
        print("")


def main(argv=None):
    # Windows 控制台默认 GBK，中文报告会被写花；强制 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(
        description="核对 Trae 上位机代码工厂产物里的 P/Invoke 声明与官方真值")
    ap.add_argument("--out-dir", default=DEFAULT_TRAE_OUT,
                    help="Trae 生成产物根目录（含 mc_<brand> 子目录）")
    ap.add_argument("--knowledge-dir", default=DEFAULT_KNOWLEDGE,
                    help="官方真值目录（official_api）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--strict", action="store_true",
                    help="存在『不可用』声明时以退出码 1 结束（CI 用）")
    args = ap.parse_args(argv)

    res = verify(args.out_dir, args.knowledge_dir)

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print_text_report(res)

    if args.strict and res["totals"]["missing"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
