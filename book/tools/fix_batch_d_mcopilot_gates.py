#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_batch_d_mcopilot_gates.py —— 批 D：mcopilot 的门禁在**干净克隆**里必须绿（2026-10-23）。

干净克隆 ≈ CI 环境（本地路径克隆跑出来的就是 CI 会跑的 ✓）。
实测：G1–G12 里 **G5 失败** ✗、负向门禁 **N1 假绿** ✗。

一、G5（quote 反查）失败 ✗
   协议标准原件按本仓约定外置在仓外 ✓，干净克隆里不在位 ✓ →
   `check_modbus_quotes.py` 必然退 1 ✗ → 门禁判失败 ✗。
   但同一份缺件下 G7（锚点门禁）、G12（语料门禁）都是 **SKIP** ✓ —— 口径不一致 ✗。
   处置：G5 在**既无已提取文本、又无外置原件**时记 SKIP ✓，
   并在摘要里喊明「当前不可自动复核」✓（SKIP 不计失败 ✓，但也不许静默 ✓）。

二、负向门禁 N1 **假绿** ✗（最危险的一种）
   N1 靠「阳性对照退 0 + 注入后退非 0」证明 G5 有检测力 ✓。
   干净克隆里阳性对照退的是 1 ✗（缺原件）→ 用例判 FAIL ✗；
   而注入后那条**也退 1** ✓ → 被记成 `[PASS=YES]` ✗✗
   —— 但它拒绝的是「规范文本缺失」，**不是**「编造引文」✗ → **假绿** ✗。
   处置：N1 先判**基线是否可核** ✓：
     基线不可核 → 整条用例记 **SKIP** ✓（带理由 ✓），**不再执行注入** ✓；
     绝不把「因为缺件而拒绝」记成检测力已证明 ✓。
   框架侧：Add-Row 加 -Skip ✓；汇总行把 SKIP 单列 ✓（分母不含 SKIP ✓）；
   退出码：SKIP 不算失败 ✓（与门禁框架一致 ✓）。

纪律：**静默 skip 也算绿 = 最危险失败模式** ✓。
所以这次的三处 SKIP 全部要求：①在汇总行喊出来 ✓；②写明「当前不可自动复核」✓；
③被跳过的那条**不许记成 PASS** ✓。
"""
import io
import os
import sys

MC = r"%WORKSPACE%\mcopilot"


def read(p):
    return io.open(p, encoding="utf-8", newline="").read()


def write(p, t):
    io.open(p, "w", encoding="utf-8", newline="").write(t)


def sub(txt, old, new, what):
    eol = "\r\n" if "\r\n" in txt else "\n"
    o, n = old.replace("\n", eol), new.replace("\n", eol)
    cnt = txt.count(o)
    if cnt != 1:
        print(f"✗ {what}：命中 {cnt} 处（应为 1）")
        print("   ", old[:100].replace("\n", "\\n"))
        sys.exit(1)
    return txt.replace(o, n)


# ── 一、gate_protocol.ps1：G5 缺件记 SKIP ──────────────────────────────
p = os.path.join(MC, "scripts", "gate_protocol.ps1")
txt = read(p)
old = '''Add-Gate "G5" "quote反查_check_modbus_quotes" 14 {
    $r = Invoke-Proc -Exe $PythonExe -ArgList @((Join-Path $RepoRoot "scripts\\check_modbus_quotes.py"))'''
new = '''Add-Gate "G5" "quote反查_check_modbus_quotes" 14 {
    # 协议标准原件按本仓约定外置在仓外（mcopilot-external/vendor_docs/protocol_specs）。
    # 干净克隆 / 原件未就位时：既没有已提取文本也没有原件 ⟹ **基线不可核** ⟹ 整门 SKIP，
    # 与 G7（锚点）、G12（语料）同一口径（缺件不算败），但摘要里必须喊明
    # 「当前不可自动复核」——SKIP 不等于已核过。
    $specs = Join-Path (Split-Path -Parent $RepoRoot) "mcopilot-external\\vendor_docs\\protocol_specs"
    $extDir = Join-Path $RepoRoot "out\\_protocols_extract"
    $hasText = (Test-Path $extDir) -and (@(Get-ChildItem $extDir -Filter "*.txt" -ErrorAction SilentlyContinue).Count -gt 0)
    if (-not $hasText -and -not (Test-Path $specs)) {
        return @{ Exit = 0; Skip = $true; Summary = "SKIP：协议标准原件按约定外置在 $specs，本机未就位且无已提取文本：当前不可自动复核（不是已核过）" }
    }
    $r = Invoke-Proc -Exe $PythonExe -ArgList @((Join-Path $RepoRoot "scripts\\check_modbus_quotes.py"))'''
txt = sub(txt, old, new, "G5 缺件记 SKIP")
write(p, txt)
print("  ✓ scripts/gate_protocol.ps1：G5 缺件记 SKIP（与 G7/G12 同口径）")

# ── 二、gate_negative.ps1：Add-Row 加 SKIP + N1 基线守卫 ────────────────
p = os.path.join(MC, "scripts", "gate_negative.ps1")
txt = read(p)

old = '''function Add-Row([string]$Case, [string]$Point, [string]$Gate, [string]$Expect, [string]$Observed, [bool]$Pass, [int]$Code) {
    $script:rows.Add([pscustomobject]@{
        Case = $Case; Inject = $Point; Gate = $Gate; Expect = $Expect; Observed = $Observed
        PASS = $(if ($Pass) { "YES" } else { "NO" }); exit = $Code
    })
    $tag = "PASS"; if (-not $Pass) { $tag = "FAIL" }
    Write-Output ("NEG`t{0}`t{1}`t[{2}] {3}" -f $Case, $tag, $Code, $Observed)
}'''
new = '''function Add-Row([string]$Case, [string]$Point, [string]$Gate, [string]$Expect, [string]$Observed, [bool]$Pass, [int]$Code, [switch]$Skip) {
    # SKIP = 这条用例**没跑**（基线不可核 / 缺件），不是跑了但没通过，
    # 更不是通过了。SKIP 不计失败，但必须单列出来喊（静默 skip 也算绿 = 最危险失败模式）。
    $script:rows.Add([pscustomobject]@{
        Case = $Case; Inject = $Point; Gate = $Gate; Expect = $Expect; Observed = $Observed
        PASS = $(if ($Skip) { "SKIP" } elseif ($Pass) { "YES" } else { "NO" }); exit = $Code
    })
    $tag = "PASS"; if ($Skip) { $tag = "SKIP" } elseif (-not $Pass) { $tag = "FAIL" }
    Write-Output ("NEG`t{0}`t{1}`t[{2}] {3}" -f $Case, $tag, $Code, $Observed)
}'''
new = '''function Add-Row([string]$Case, [string]$Point, [string]$Gate, [string]$Expect, [string]$Observed, [bool]$Pass, [int]$Code, [switch]$Skip) {
          # SKIP = 这条用例**没跑**（基线不可核 / 缺件），不是跑了但没通过，
          # 更不是通过了。SKIP 不计失败，但必须单列出来喊（静默 skip 也算绿 = 最危险失败模式）。
          $script:rows.Add([pscustomobject]@{
              Case = $Case; Inject = $Point; Gate = $Gate; Expect = $Expect; Observed = $Observed
              PASS = $(if ($Skip) { "SKIP" } elseif ($Pass) { "YES" } else { "NO" }); exit = $Code
          })
          $tag = "PASS"; if ($Skip) { $tag = "SKIP" } elseif (-not $Pass) { $tag = "FAIL" }
          Write-Output ("NEG`t{0}`t{1}`t[{2}] {3}" -f $Case, $tag, $Code, $Observed)
      }'''
txt = sub(txt, old, new, "Add-Row 加 SKIP")

old = '''      $sb = New-Sandbox "n1_quote"
      $chk = Copy-Into "scripts\\check_modbus_quotes.py" $sb'''
new = '''      # 基线可核性前置检查：没有已提取文本也没有外置原件 ⟹ **基线不可核** ⟹
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
      $sb = New-Sandbox "n1_quote"
      $chk = Copy-Into "scripts\\check_modbus_quotes.py" $sb'''
txt = sub(txt, old, new, "N1 基线守卫")

old = '''      $passCount = @($rows | Where-Object { $_.PASS -eq "YES" }).Count
      Write-Output ("检测力矩阵：{0}/{1} PASS（阳性对照 {2} 条含内）" -f $passCount, $rows.Count,
          @($rows | Where-Object { $_.Case -like "*阳性对照*" }).Count)'''
new = '''      $passCount = @($rows | Where-Object { $_.PASS -eq "YES" }).Count
      $skipCount = @($rows | Where-Object { $_.PASS -eq "SKIP" }).Count
      $judged = $rows.Count - $skipCount
      Write-Output ("检测力矩阵：{0}/{1} PASS（阳性对照 {2} 条含内）" -f $passCount, $judged,
          @($rows | Where-Object { $_.Case -like "*阳性对照*" }).Count)
      if ($skipCount -gt 0) {
          Write-Output ("SKIP {0} 条（**没跑**，不是没通过；当前不可自动复核）：" -f $skipCount)
          foreach ($r in @($rows | Where-Object { $_.PASS -eq "SKIP" })) {
              Write-Output ("  - {0}：{1}" -f $r.Case, $r.Observed)
          }
      }'''
txt = sub(txt, old, new, "汇总行单列 SKIP")

old = '''      if ($anyMiss) { Write-Output "总退出码 3：存在注入点未命中（注入没生效，检测力证明无效）"; exit 3 }
      if ($passCount -ne $rows.Count) { Write-Output "总退出码 1：存在未达预期的负向/对照用例"; exit 1 }'''
new = '''      if ($anyMiss) { Write-Output "总退出码 3：存在注入点未命中（注入没生效，检测力证明无效）"; exit 3 }
      if ($passCount -ne $judged) { Write-Output "总退出码 1：存在未达预期的负向/对照用例"; exit 1 }
      if ($skipCount -gt 0) { Write-Output "总退出码 0：已跑的用例全绿；SKIP 的用例**没跑**（当前不可自动复核），不算检测力已证明。" }'''
txt = sub(txt, old, new, "退出码判定：SKIP 不算失败")
write(p, txt)
print("  ✓ scripts/gate_negative.ps1：N1 基线守卫 + SKIP 状态 + 汇总单列")
