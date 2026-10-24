#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_batch_c_pyresolve.py —— 批 C 第 1 项续：门禁脚本的解释器解析（2026-10-22）。

改默认值（"python" 走 PATH）之后暴露了一个配套缺口：脚本用 `Test-Path` 判解释器
是否存在，而 Test-Path 只认**路径**、不认命令名 → 命令名一律判"不存在"。
处置：判存在之前先解析一次（命令名 → Get-Command 的 Source），
解析不到才报原来的错。**不改判定语义**（解析不到仍然 exit 2 / throw）✓。
"""
import io
import sys

MC = r"%WORKSPACE%\mcopilot"

RESOLVE = (
    "# 解释器可以是命令名（走 PATH）或完整路径——先解析成可执行文件路径再判存在\n"
    "if (-not (Test-Path -LiteralPath $PythonExe)) {\n"
    "    $cmd = Get-Command $PythonExe -ErrorAction SilentlyContinue\n"
    "    if ($cmd -and $cmd.Source) { $PythonExe = $cmd.Source }\n"
    "}\n"
)
RESOLVE2 = RESOLVE.replace("$PythonExe", "$PyTestExe")

FIXES = [
    (r"scripts\gate_protocol.ps1",
     "foreach ($exe in @($PythonExe, $PyTestExe)) {",
     RESOLVE + RESOLVE2 + "\nforeach ($exe in @($PythonExe, $PyTestExe)) {", 1),
    (r"scripts\gate_corpus.ps1",
     "foreach ($f in @($PythonExe, $CorpusPy, $Validator, $Detector)) {",
     RESOLVE + "\nforeach ($f in @($PythonExe, $CorpusPy, $Validator, $Detector)) {", 1),
    (r"scripts\gate_farm.ps1",
     "foreach ($f in @($PythonExe, $FarmPy, $DetectPy, $EvalPy)) {",
     RESOLVE + "\nforeach ($f in @($PythonExe, $FarmPy, $DetectPy, $EvalPy)) {", 1),
    (r"scripts\gate_negative.ps1",
     'if (-not (Test-Path $PythonExe)) { Write-Output "[negative-fail] python 不存在：$PythonExe"; exit 2 }',
     RESOLVE + '\nif (-not (Test-Path $PythonExe)) { Write-Output "[negative-fail] python 不存在：$PythonExe"; exit 2 }', 1),
    (r"scripts\gate_onboard.ps1",
     'if (-not (Test-Path $PythonExe)) { Write-Output "[onboard-fail] python 不存在：$PythonExe"; exit 2 }',
     RESOLVE + '\nif (-not (Test-Path $PythonExe)) { Write-Output "[onboard-fail] python 不存在：$PythonExe"; exit 2 }', 1),
    (r"knowledge\templates\protocol\run_contract.ps1",
     'if (-not (Test-Path $PythonExe)) { throw "未找到 python：$PythonExe" }',
     RESOLVE + '\nif (-not (Test-Path $PythonExe)) { throw "未找到 python：$PythonExe" }', 1),
    (r"knowledge\templates\protocol\run_rtu_contract.ps1",
     'if (-not (Test-Path $PythonExe)) { throw "未找到 python：$PythonExe" }',
     RESOLVE + '\nif (-not (Test-Path $PythonExe)) { throw "未找到 python：$PythonExe" }', 1),
]


def main():
    cache = {}
    applied, failed = 0, []
    for rel, old, new, cnt in FIXES:
        path = MC + "\\" + rel
        if path not in cache:
            cache[path] = io.open(path, encoding="utf-8", newline="").read()
        txt = cache[path]
        # 行尾按文件实际来（PowerShell 脚本在 Windows 上是 CRLF，匹配串必须跟着走）
        eol = "\r\n" if "\r\n" in txt else "\n"
        old_e = old.replace("\n", eol)
        new_e = new.replace("\n", eol)
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
