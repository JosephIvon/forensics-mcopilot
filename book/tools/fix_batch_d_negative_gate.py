#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_batch_d_negative_gate.py —— 批 D：负向门禁在干净克隆里不许假绿（2026-10-23）。

问题（干净克隆 ≈ CI 环境 ✓）：N1（编造引文 → G5 必须拒收）靠
「阳性对照退 0 + 注入后退非 0」证明检测力 ✓。
干净克隆里协议标准原件不在位 ✓：
  · 阳性对照退的是 1（缺件）→ 用例判 FAIL ✗；
  · 注入后那条**也退 1** ✓ → 被记成 [PASS=YES] ✗✗
    —— 但它拒绝的是「规范文本缺失」，**不是**「编造引文」✗ → **假绿** ✗。
    这是「静默 skip 也算绿」一族里最坏的一种：**把没核记成核过**。

处置：
  ① N1 先判**基线是否可核** ✓：既无已提取文本又无外置原件 ⟹ 整条用例记 **SKIP** ✓
     （带理由 ✓），并且**不执行注入** ✓。
  ② 框架侧：Add-Row 加 -Skip ✓；PASS 字段记 "SKIP" ✓（不许记 YES ✓）；
     汇总行把 SKIP 单列 ✓（分母不含 SKIP ✓）；退出码：SKIP 不算失败 ✓。

口径：SKIP = **没跑**，不是「没通过」，更不是「通过了」✓。
"""
import io
import os
import sys

MC = r"%WORKSPACE%\mcopilot"
P = os.path.join(MC, "scripts", "gate_negative.ps1")


def read(p):
    return io.open(p, encoding="utf-8", newline="").read()


def sub(txt, old, new, what):
    eol = "\r\n" if "\r\n" in txt else "\n"
    o, n = old.replace("\n", eol), new.replace("\n", eol)
    cnt = txt.count(o)
    if cnt != 1:
        print(f"✗ {what}：命中 {cnt} 处（应为 1）")
        print("   ", old[:110].replace("\n", "\\n"))
        sys.exit(1)
    return txt.replace(o, n)


txt = read(P)

# ① Add-Row 加 SKIP
txt = sub(txt,
    'function Add-Row([string]$Case, [string]$Point, [string]$Gate, [string]$Expect, '
    '[string]$Observed, [bool]$Pass, [int]$Code) {',
    'function Add-Row([string]$Case, [string]$Point, [string]$Gate, [string]$Expect, '
    '[string]$Observed, [bool]$Pass, [int]$Code, [switch]$Skip) {',
    "Add-Row 签名加 -Skip")

txt = sub(txt,
    '        PASS = $(if ($Pass) { "YES" } else { "NO" }); exit = $Code',
    '        PASS = $(if ($Skip) { "SKIP" } elseif ($Pass) { "YES" } else { "NO" }); exit = $Code',
    "PASS 字段加 SKIP")

txt = sub(txt,
    '    $tag = "PASS"; if (-not $Pass) { $tag = "FAIL" }',
    '    $tag = "PASS"; if ($Skip) { $tag = "SKIP" } elseif (-not $Pass) { $tag = "FAIL" }',
    "标签加 SKIP")

# ② N1 基线守卫
txt = sub(txt,
    '    $sb = New-Sandbox "n1_quote"',
    '''    # 基线可核性前置检查：没有已提取文本也没有外置原件 ⟹ **基线不可核** ⟹
    # 本用例整条 SKIP，**不执行注入**。
    # 不许把「因为规范文本缺失而拒绝」记成「编造引文被拒」的检测力证明——那是假绿。
    $specs = Join-Path (Split-Path -Parent $RepoRoot) "mcopilot-external\\vendor_docs\\protocol_specs"
    $extDir = Join-Path $RepoRoot "out\\_protocols_extract"
    $hasText = (Test-Path $extDir) -and (@(Get-ChildItem $extDir -Filter "*.txt" -ErrorAction SilentlyContinue).Count -gt 0)
    if (-not $hasText -and -not (Test-Path $specs)) {
        Add-Row -Case "N1_quote反查_编造引文" -Point "modbus.json 副本 spec_ref.quote 首条" `
            -Gate "G5 check_modbus_quotes.py" -Expect "阳性对照(未注入副本)退出码 0；注入后非 0" `
            -Observed "SKIP：协议标准原件按约定外置在 $specs，本机未就位且无已提取文本：基线不可核，无法证明检测力（当前不可自动复核）" `
            -Pass $false -Code 0 -Skip $true
        return
    }
    $sb = New-Sandbox "n1_quote"''',
    "N1 基线守卫")

# ③ 汇总行单列 SKIP
txt = sub(txt,
    '''$passCount = @($rows | Where-Object { $_.PASS -eq "YES" }).Count
Write-Output ("检测力矩阵：{0}/{1} PASS（阳性对照 {2} 条含内）" -f $passCount, $rows.Count,
    @($rows | Where-Object { $_.Case -like "*阳性对照*" }).Count)''',
    '''$passCount = @($rows | Where-Object { $_.PASS -eq "YES" }).Count
$skipCount = @($rows | Where-Object { $_.PASS -eq "SKIP" }).Count
$judged = $rows.Count - $skipCount
Write-Output ("检测力矩阵：{0}/{1} PASS（阳性对照 {2} 条含内）" -f $passCount, $judged,
    @($rows | Where-Object { $_.Case -like "*阳性对照*" }).Count)
if ($skipCount -gt 0) {
    Write-Output ("SKIP {0} 条（**没跑**，不是没通过；当前不可自动复核）：" -f $skipCount)
    foreach ($r in @($rows | Where-Object { $_.PASS -eq "SKIP" })) {
        Write-Output ("  - {0}：{1}" -f $r.Case, $r.Observed)
    }
}''',
    "汇总行单列 SKIP")

# ④ 退出码：SKIP 不算失败
txt = sub(txt,
    '''if ($passCount -ne $rows.Count) { Write-Output "总退出码 1：存在未达预期的负向/对照用例"; exit 1 }''',
    '''if ($passCount -ne $judged) { Write-Output "总退出码 1：存在未达预期的负向/对照用例"; exit 1 }
if ($skipCount -gt 0) { Write-Output "总退出码 0：已跑的用例全绿；SKIP 的用例**没跑**（当前不可自动复核），不算检测力已证明。" }''',
    "退出码判定")

io.open(P, "w", encoding="utf-8", newline="").write(txt)
print("  ✓ scripts/gate_negative.ps1：Add-Row 加 SKIP + N1 基线守卫 + 汇总单列 + 退出码")
