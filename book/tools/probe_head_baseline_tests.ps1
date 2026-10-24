#!/usr/bin/env pwsh
# 用途：在 HEAD 的真检出（worktree）里跑那三个疑似失败的用例，判定"我改坏的"还是"本来就坏的"
param(
  # 代码仓位置：默认**同级目录**下的 mcopilot（并仓后是 forensics-mcopilot）。
  # 不写死绝对路径——公开仓里读者换台机器就跑不了。
  [string]$Repo = "",
  [string]$Worktree = "",
  # 解释器：默认 PATH 上的 python（原来写死某台机器的绝对路径，别人跑不了）
  [string]$PythonExe = ""
)
$ErrorActionPreference = 'Continue'
$py = if ($PythonExe) { $PythonExe } else { "python" }
if (-not $Repo) {
  $workspace = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
  foreach ($cand in @("forensics-mcopilot", "mcopilot")) {
    $p = Join-Path $workspace $cand
    if (Test-Path $p) { $Repo = $p; break }
  }
}
if (-not $Repo) { Write-Error "找不到代码仓，用 -Repo 指定"; exit 2 }
$mc = $Repo
if (-not $Worktree) { $Worktree = Join-Path ([System.IO.Path]::GetTempPath()) "mcopilot_head_wt" }
$tmp = $Worktree

Set-Location $mc
& git worktree remove --force $tmp 2>&1 | Out-Null
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
Write-Output "== 建 HEAD 干净 worktree =="
& git worktree add --detach $tmp HEAD 2>&1 | Select-Object -Last 2

Set-Location $tmp
Write-Output ""
Write-Output "== HEAD 干净检出：全量测试 =="
& $py -m pytest tests -q 2>&1 | Select-Object -Last 6

Write-Output ""
Write-Output "== HEAD 干净检出：本次 3 个疑似用例 =="
& $py -m pytest tests/test_onboard_loop.py tests/test_protocol_modbus.py tests/test_protocol_slmp.py -q 2>&1 | Select-Object -Last 8

Set-Location $mc
Write-Output ""
Write-Output "== 清理 worktree =="
& git worktree remove --force $tmp 2>&1 | Select-Object -Last 1
& git worktree prune
Write-Output "done"
