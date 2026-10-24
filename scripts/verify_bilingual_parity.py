#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Verify that README.md (ZH) and README_EN.md (EN) are section-for-section synchronised.

Both READMEs must agree on:
  * the number and nesting level of every heading
  * the number of ``` code fences
  * the number of table rows
  * every `mcopilot ...` command invocation
  * every file path referenced in inline code
  * a set of key identifiers (requirement IDs, knowledge filenames, API symbols)

Only the prose is allowed to differ — the structure may not.

Usage:  python scripts/verify_bilingual_parity.py
Exit code: 0 = in sync, 1 = out of sync (details printed).
Standard library only; does not import mcopilot.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZH_PATH = ROOT / "README.md"
EN_PATH = ROOT / "README_EN.md"

fail = []


def note(ok, msg):
    print(("  ok  " if ok else "  !!  ") + msg)
    if not ok:
        fail.append(msg)


if not ZH_PATH.exists() or not EN_PATH.exists():
    print("!!  missing README.md or README_EN.md")
    sys.exit(1)

ZH = ZH_PATH.read_text(encoding="utf-8")
EN = EN_PATH.read_text(encoding="utf-8")

print("== headings ==")
zh_h = re.findall(r"^(#{1,3}) (.+)$", ZH, re.M)
en_h = re.findall(r"^(#{1,3}) (.+)$", EN, re.M)
note(len(zh_h) == len(en_h), f"heading count: ZH={len(zh_h)} EN={len(en_h)}")
mismatch = [f"#{i} ZH='{zt}' EN='{et}'" for i, ((zl, zt), (el, et))
            in enumerate(zip(zh_h, en_h)) if zl != el]
note(not mismatch, f"heading levels align ({len(mismatch)} mismatches)")

print("== section numbering ==")
zh_secs = re.findall(r"^## (.+)$", ZH, re.M)
en_secs = re.findall(r"^## (.+)$", EN, re.M)
note(len(zh_secs) == len(en_secs), f"## count: ZH={len(zh_secs)} EN={len(en_secs)}")

print("== code fences ==")
note(ZH.count("```") == EN.count("```"),
     f"fence count: ZH={ZH.count('```')} EN={EN.count('```')}")

print("== table rows ==")
zh_rows = sum(1 for ln in ZH.splitlines() if ln.startswith("|"))
en_rows = sum(1 for ln in EN.splitlines() if ln.startswith("|"))
note(zh_rows == en_rows, f"table rows: ZH={zh_rows} EN={en_rows}")

print("== command invocations ==")
cmd_re = r"mcopilot (?:[a-z_]+)(?: [a-z|]+)?"
zh_cmds = set(re.findall(cmd_re, ZH))
en_cmds = set(re.findall(cmd_re, EN))
note(zh_cmds == en_cmds,
     f"same command set (ZH-only={sorted(zh_cmds - en_cmds)} EN-only={sorted(en_cmds - zh_cmds)})")

print("== file paths ==")
path_re = r"`([A-Za-z0-9_./*\-一-鿿]+(?:\.[A-Za-z0-9_]+|/[^`\s]*)+)`"


def looks_like_path(p):
    return "/" in p or ("." in p and any(p.endswith(e) for e in (
        ".json", ".md", ".py", ".cs", ".csv", ".bat", ".ps1", ".ps", ".txt", ".yml")))


zh_p = {p for p in re.findall(path_re, ZH) if looks_like_path(p)}
en_p = {p for p in re.findall(path_re, EN) if looks_like_path(p)}
# The ZH localises a word inside a path where the EN keeps it in English.
ALLOWED_DIFF = {"02_CSharp封装/<位数>_single_card/", "GT2-400-ACC2-VB-G/-V", "单位/秒"}
missing = sorted(p for p in zh_p if p not in en_p and p not in ALLOWED_DIFF)
note(not missing, f"paths in ZH but not EN: {missing}")

print("== key identifiers ==")
IDENTIFIERS = [
    "requirements_map.json", "requirements_map", "coverage_ledger.json",
    "brands_in_scope", "binding_returns.csv", "extract_binding_returns.py",
    "HasRealFeedback(axis)", "e≈a/ωn²", "Q-06a", "Q-06b", "R-03",
    "servo_rules.json", "review_rules.json", "cam_rules.json",
    "dmc_cam_table_unit", "ZAux_Direct_Cam", "GT_GantryHoming",
]
for ident in IDENTIFIERS:
    note(ident in ZH and ident in EN, f"present in both: {ident}")

print("== forbidden framing ==")
for bad in ["JD 拆解", "mcopilot jd", "jd_map", "岗位描述里", "从一份 JD"]:
    note(bad not in ZH and bad not in EN, f"absent from both: {bad!r}")

print()
if fail:
    print("BILINGUAL PARITY FAILED (%d):" % len(fail))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("BILINGUAL PARITY OK — README.md and README_EN.md are in sync")
