#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_batch_d_axiscope.py —— 批 D：让 axiscope 的**干净克隆**能跑（2026-10-23）。

干净克隆实测：19 failed + 313 passed + 68 errors ✗ → 四类成因，四类处置：

① **原始数据按 A-131 口径不入库**（data/raw、data/incoming ✗）
   → 87 个测试函数依赖它 ✗。处置：新增 `tests/conftest.py` ✓
     统一按各文件顶部的 `REQUIRES_DATA` **显式声明**执行 loud SKIP ✓
     （写明「当前不可自动复核」✓）；不许红着装作已核过 ✓，也不许静默跳过 ✓。

② **行号指针指向不入库区**（README 指向 `build/probe_kb7_b_group.out` ✗）
   → 干净克隆里 build/ 不在位 ✓ → 被判成 `missing-file` 病例 ✗（假病例 ✓）。
   处置：`data/probe_doc_line_refs.py` 增加 `not-in-repo` 桶 ✓——
     与既有的 `external-target` 同构 ✓：**不判病例，但必须单列一桶、条数可核** ✓。

③ **CLI 遇到缺失输入抛未捕获异常** ✗
   → 契约是「拒收即退 2」✓，但 FileNotFoundError 不在捕获列表 ✓ → 抛栈 ✗。
   处置：`src/axiscope/__main__.py` 单独捕获 FileNotFoundError ✓ → 退 2 并说清缺哪个文件 ✓。

④ **两条 CLI 用例需要原始数据** ✓ → 走 fixture 级跳过 ✓，
   不连累同文件里其余的离线纪律用例 ✓（整份跳过会把那些覆盖也丢掉 ✗）。

纪律提醒：跳过 ≠ 绿 ✓。每个 skip 都带原因 ✓，CI 里能一眼看出
「有多少断言在缺件时没跑」✓ —— 不许把 skip 当成通过 ✓。
"""
import io
import os
import sys

AX = r"%WORKSPACE%\axiscope"

CONFTEST = '''"""原始数据按 A-131 口径不入库（可按 DOI 重下 / 由生成器再生）；干净克隆里缺件时，
依赖它的测试必须**响亮地跳过**并写明「当前不可自动复核」——
既不许红着装作已核过，也不许静默跳过（KB0 §6 检查 22 的形状：跳过也要有口径）。

声明方式：各测试文件顶部写 `REQUIRES_DATA = ("data/raw/xxx.csv", ...)`，
由本文件统一执行。**显式声明，不靠猜路径**——猜出来的口径迟早会漂。
"""
from __future__ import annotations

import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# CLI 用例需要的原始数据（与 test_offline_discipline.py 的两条用例对应）
CLI_DATA = (
    "data/raw/Export10_244531.csv",
    "data/incoming/6114_ObserverTestSet.tab",
)


def _missing(rel_paths):
    return [rel for rel in rel_paths
            if not os.path.isfile(os.path.join(ROOT, rel.replace("/", os.sep)))]


def pytest_collection_modifyitems(config, items):
    """缺原始数据的测试逐条跳过，并把缺件清单写进 skip 原因（loud skip）。"""
    for item in items:
        need = getattr(item.module, "REQUIRES_DATA", ())
        if not need:
            continue
        missing = _missing(need)
        if missing:
            item.add_marker(pytest.mark.skip(
                reason="原始数据按 A-131 口径不入库，缺 %s："
                       "在档结论与指纹自洽，但**当前不可自动复核**" % "、".join(missing)))


@pytest.fixture
def require_cli_data():
    missing = _missing(CLI_DATA)
    if missing:
        pytest.skip("原始数据按 A-131 口径不入库，缺 %s："
                    "**当前不可自动复核**" % "、".join(missing))
'''

# 各测试文件的原始数据依赖（实测自这些文件里的路径常量）
REQUIRES = {
    "tests/test_slice.py": ('("data/raw/Export10_244531.csv",)'),
    "tests/test_export_dialects.py": (
        '(\n'
        '    "data/raw/Export10_244531.csv",\n'
        '    "data/raw/参数分析仪波形_PMU_1t1r_CVSV导出样例.csv",\n'
        '    "data/incoming/2563_LDD_Transfer_function_Force_controlled.csv",\n'
        '    "data/incoming/6114_lsmc.csv",\n'
        '    "data/incoming/6114_ObserverTestSet.tab",\n'
        '    "data/incoming/current-hunt/3900_const_vel_110.tab",\n'
        ')'),
    "tests/test_identity_scan.py": ('("data/raw/Export10_244531.csv",)'),
    "tests/test_counts_and_pairs.py": ('("data/raw/Export10_244531.csv",)'),
    "tests/test_resonance_counts.py": ('("data/raw/Export10_244531.csv",)'),
}

DECL = ("\n\n# 原始数据按 A-131 口径不入库；缺件时本文件整份 loud SKIP\n"
        "# （口径见 tests/conftest.py；跳过 ≠ 通过，原因会写在 skip 理由里）\n"
        "REQUIRES_DATA = %s\n")


def read(path):
    return io.open(path, encoding="utf-8", newline="").read()


def write(path, txt):
    io.open(path, "w", encoding="utf-8", newline="").write(txt)


def sub(txt, old, new, what):
    eol = "\r\n" if "\r\n" in txt else "\n"
    o, n = old.replace("\n", eol), new.replace("\n", eol)
    if txt.count(o) != 1:
        print(f"✗ {what}：命中 {txt.count(o)} 处（应为 1）")
        print("   ", old[:90].replace("\n", "\\n"))
        sys.exit(1)
    return txt.replace(o, n)


def main():
    # ── A. tests/conftest.py（新建）────────────────────────────────────
    p = os.path.join(AX, "tests", "conftest.py")
    if os.path.isfile(p):
        print("  ! tests/conftest.py 已存在，未覆盖")
    else:
        write(p, CONFTEST)
        print("  ✓ tests/conftest.py（新建）：缺件 loud SKIP 的统一口径")

    # ── B. 五个测试文件加 REQUIRES_DATA 声明 ──────────────────────────
    for rel, decl in REQUIRES.items():
        p = os.path.join(AX, rel.replace("/", os.sep))
        txt = read(p)
        if "REQUIRES_DATA" in txt:
            print(f"  ! {rel} 已有声明，跳过")
            continue
        txt = sub(txt, "\nimport pytest\n", "\nimport pytest\n" + (DECL % decl),
                  f"{rel} 加 REQUIRES_DATA")
        write(p, txt)
        print(f"  ✓ {rel}：REQUIRES_DATA 声明")

    # ── C. 两条 CLI 用例加 fixture ────────────────────────────────────
    p = os.path.join(AX, "tests", "test_offline_discipline.py")
    txt = read(p)
    txt = sub(txt,
              "def test_cli_dialect_rejection_exits_2_not_crash(tmp_path):",
              "def test_cli_dialect_rejection_exits_2_not_crash(tmp_path, require_cli_data):",
              "CLI 拒收用例加 fixture")
    txt = sub(txt,
              "def test_cli_clean_run_still_exits_zero(tmp_path):",
              "def test_cli_clean_run_still_exits_zero(tmp_path, require_cli_data):",
              "CLI 零退用例加 fixture")
    write(p, txt)
    print("  ✓ tests/test_offline_discipline.py：两条 CLI 用例改走 fixture 级跳过")

    # ── D. probe_doc_line_refs.py：not-in-repo 桶 ──────────────────────
    p = os.path.join(AX, "data", "probe_doc_line_refs.py")
    txt = read(p)
    helper = '''def is_not_in_repo(target):
    """被指文件是不是**不入库区**（生成物，如 `build/`、`out/`）——
    仓内文档可以指向它们（那是「跑出来的东西」），但公开克隆里它们不在位。

    口径：这类指针**不判病例**（那会让每个干净克隆必红），
    但也**不许静默吞掉** → 单列 `not-in-repo` 一桶打印出来，条数在
    `tests/test_doc_line_refs.py` 里锁死（多一条 = 可能真漂移，少一条 = 引用被改掉了）。
    """
    t = (target or "").replace("\\\\", "/")
    return t.startswith("build/") or t.startswith("out/")


'''
    txt = sub(txt, "def is_audit_doc(rel):", helper + "def is_audit_doc(rel):",
              "probe 加 is_not_in_repo")

    old_judge = '''            if status == "missing-file" and is_audit_doc(rel):
                # 两条判定路径（带引文 / 不带引文）都会落到 missing-file，豁免放在这里统一改判，
                # 否则「引文写得越全越像病例」这种反直觉的差别会留在实现里。
                status, detail = "external-target", "指向被审计项目的文件，不在本仓可核范围"'''
    new_judge = '''            if status == "missing-file":
                # 两条判定路径（带引文 / 不带引文）都会落到 missing-file，豁免放在这里统一改判，
                # 否则「引文写得越全越像病例」这种反直觉的差别会留在实现里。
                if is_audit_doc(rel):
                    status, detail = "external-target", "指向被审计项目的文件，不在本仓可核范围"
                elif is_not_in_repo(tgt.cands[0] if tgt.cands else ptext):
                    status, detail = "not-in-repo", "指向不入库区（生成物），公开克隆里不在位：当前不可自动复核"'''
    txt = sub(txt, old_judge, new_judge, "probe 判定改判 not-in-repo")

    old_sum = '''    print("扫描指针 %d 条 | 命中 %d | stale %d | partial-quote %d | no-quote %d | "
          "missing-file %d | range-out-of-bounds %d | external-target %d | 病例 %d" % (
              total, counts.get("hit", 0), counts.get("stale", 0),
              counts.get("partial-quote", 0), counts.get("no-quote", 0),
              counts.get("missing-file", 0), counts.get("range-out-of-bounds", 0),
              counts.get("external-target", 0), cases))'''
    new_sum = '''    print("扫描指针 %d 条 | 命中 %d | stale %d | partial-quote %d | no-quote %d | "
          "missing-file %d | range-out-of-bounds %d | external-target %d | not-in-repo %d | 病例 %d" % (
              total, counts.get("hit", 0), counts.get("stale", 0),
              counts.get("partial-quote", 0), counts.get("no-quote", 0),
              counts.get("missing-file", 0), counts.get("range-out-of-bounds", 0),
              counts.get("external-target", 0), counts.get("not-in-repo", 0), cases))'''
    txt = sub(txt, old_sum, new_sum, "probe 汇总行加 not-in-repo")
    write(p, txt)
    print("  ✓ data/probe_doc_line_refs.py：not-in-repo 桶（不判病例但响亮）")

    # ── E. __main__.py：缺输入按契约退 2 ──────────────────────────────
    p = os.path.join(AX, "src", "axiscope", "__main__.py")
    txt = read(p)
    old = '''    except (c1.PackError, features.FeatureError, ScopeFormatError) as exc:
        print(f"拒收：{exc}", file=sys.stderr)
        return 2'''
    new = '''    except FileNotFoundError as exc:
        # 缺输入是**拒收**，不是崩溃：契约是「拒收即退 2」，
        # 抛栈会让调用方以为程序崩了（干净克隆里原始数据不在位，必踩）。
        print(f"拒收：输入文件不存在（{getattr(exc, 'filename', None) or exc}）", file=sys.stderr)
        return 2
    except (c1.PackError, features.FeatureError, ScopeFormatError) as exc:
        print(f"拒收：{exc}", file=sys.stderr)
        return 2'''
    txt = sub(txt, old, new, "__main__ 捕获 FileNotFoundError")
    write(p, txt)
    print("  ✓ src/axiscope/__main__.py：缺输入按契约退 2（不抛栈）")


if __name__ == "__main__":
    main()
