#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_codewiki_numbers3.py —— 核 CodeWiki 第二轮数字（2026-10-22）。"""
import io
import json
import os
import re
import subprocess

MC = r"%WORKSPACE%\mcopilot"


def git(*a):
    return subprocess.run(["git", "-C", MC] + list(a), capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


tracked = [f for f in git("ls-files").splitlines() if f]
cli = io.open(os.path.join(MC, "src", "mcopilot", "cli.py"), encoding="utf-8").read()
mcp = io.open(os.path.join(MC, "src", "mcopilot", "mcp_server.py"), encoding="utf-8").read()
sr = json.load(io.open(os.path.join(MC, "knowledge", "servo_rules.json"), encoding="utf-8"))
fs = json.load(io.open(os.path.join(MC, "knowledge", "protocols", "failure_signatures.json"), encoding="utf-8"))

cmd_funcs = len(re.findall(r"^def cmd_\w+", cli, re.M))
leaf = len(re.findall(r"add_parser\(", cli))
mcp_tools = len(re.findall(r'^\s*\{\s*"name"\s*:', mcp, re.M))
if not mcp_tools:
    mcp_tools = len(re.findall(r'"name"\s*:\s*"[a-z_]+"', mcp))
sig = fs.get("signatures", fs if isinstance(fs, list) else [])
not_eval = sr.get("not_evaluable_asks", [])
cm = sr.get("confidence_model", [])
caps = sr.get("caps", [])
thr = 0
for r in sr.get("rules", []):
    thr += len(r.get("thresholds", {})) if isinstance(r.get("thresholds"), dict) else 0

print(f"  cli.py 里的 cmd_ 函数数     = {cmd_funcs}   （CodeWiki 称 18 个叶子命令）")
print(f"  cli.py 里的 add_parser 数   = {leaf}")
print(f"  mcp_server TOOLS 条数      = {mcp_tools}   （CodeWiki 称 14）")
print(f"  servo_rules 规则数         = {len(sr.get('rules', []))}   （CodeWiki 称 22）")
print(f"  not_evaluable_asks 条数   = {len(not_eval)}   （CodeWiki 称 15）")
print(f"  confidence_model 条数      = {len(cm)}   （CodeWiki 称 14）")
print(f"  caps 条数                  = {len(caps)}   （CodeWiki 称 4）")
print(f"  failure_signatures 签名数  = {len(sig)}   （CodeWiki 称 6）")
print(f"  knowledge/templates 文件数 = {len([f for f in tracked if f.startswith('knowledge/templates/')])}"
      f"   （CodeWiki 称 5 + 21）")
print(f"  servo_rules 阈值数（rules[].thresholds 键计数）= {thr}   （CodeWiki 称 102）")
print(f"\n  servo_rules 顶层键 = {list(sr.keys())}")
print(f"  rules[0] 的键 = {list(sr['rules'][0].keys()) if sr.get('rules') else '-'}")
