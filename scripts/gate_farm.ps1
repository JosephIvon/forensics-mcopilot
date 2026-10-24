# ============================================================================
#  gate_farm.ps1 —— 故障注入农场门禁（G11，退出码域 20）：批产→检出→判卷全链闭环
#
#  一个只在"全绿输入"上跑过的评测链等于没有评测链。本门禁把农场 Phase 1 的
#  每一环都落成可执行断言（五铁律：三重断言 + 阳性对照 + 负向必须红 + 构造性
#  真值可回查 + 异常路径退出码非零）：
#
#  步骤 ① 批产：python scripts/fault_farm.py --out out/farm
#         10 场景（8 TCP + 2 RTU）各产出 comm_log/1 日志 + 构造性标签
#         （真值=注入参数推出，逐行过「构造==现实」自检，场景日志全过契约门）。
#  步骤 ② 检出：python src/mcopilot/agents/forensics_comm.py（先过契约门再检出，
#         R2 同款：违规即拒跑）。
#  步骤 ③ 判卷：python scripts/eval_forensics.py（注入类 recall=100%、
#         clean/容忍场景误报=0 —— precision=recall=1.0000 缺一即 FAIL）。
#  步骤 ④ 混淆矩阵：scenario_index.json × detections 逐场景对账，
#         检出类必须==注入类（对角化；SKIP 场景不参判）。
#  步骤 ⑤ 负向 N1：真值文件**副本**错标一条（timeout→crc_error，探针
#         GATE-FARM-N1）→ eval 指标必须跌破 1.0 且漏检清单在场 → 门禁语义的
#         FAIL 被观察到 = 判卷有检测力；阳性对照=未错标副本必须仍 1.0000。
#         注入三重断言：①替换计数≥1 ②注入后内容≠原内容 ③含探针标记，
#         任一不满足 → exit 3「注入点未命中」（绝不静默当 PASS）。
#
#  退出码：0 = 五步全过；21 = 农场场景 FAIL；22 = 检出/判卷未达标；
#         23 = 混淆矩阵非对角；24 = 负向 N1 未达预期；3 = 注入点未命中；
#         100 = 未捕获异常（trap 兜底）。总退出码域 = 20（gate_protocol.ps1 G11）。
#  兼容 PowerShell 5.1+ / pwsh 7+。-ErrorAction Stop + trap，绝不"崩溃即过"。
# ============================================================================
[CmdletBinding()]
param(
    [string]$PythonExe = "python",   # 默认用 PATH 上的 python；可用 -PythonExe 覆盖
    [string]$OutDir = "",
    [switch]$SkipRtu
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$env:PYTHONIOENCODING = "utf-8"

trap {
    Write-Output ("[gate-farm-trap] 未捕获异常：{0}（{1} 行 {2}）" -f $_.Exception.Message, `
        $_.InvocationInfo.ScriptName, $_.InvocationInfo.ScriptLineNumber)
    exit 100
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutDir) { $OutDir = Join-Path $RepoRoot "out\farm" }
$FarmPy    = Join-Path $RepoRoot "scripts\fault_farm.py"
$DetectPy  = Join-Path $RepoRoot "src\mcopilot\agents\forensics_comm.py"
$EvalPy    = Join-Path $RepoRoot "scripts\eval_forensics.py"

# 解释器可以是命令名（走 PATH）或完整路径——先解析成可执行文件路径再判存在
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $cmd = Get-Command $PythonExe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { $PythonExe = $cmd.Source }
}

foreach ($f in @($PythonExe, $FarmPy, $DetectPy, $EvalPy)) {
    if (-not (Test-Path $f)) { Write-Output "[farm-fail] 缺少必需文件：$f"; exit 21 }
}

# ---------------------------------------------------------------- 基础设施
function Quote-Arg([string]$a) { '"' + ($a -replace '"', '\"') + '"' }

function Invoke-Proc {
    param([string]$Exe, [string[]]$ArgList, [string]$WorkDir = $RepoRoot, [int]$BudgetSec = 240)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = ($ArgList | ForEach-Object { Quote-Arg $_ }) -join " "
    $psi.WorkingDirectory = $WorkDir
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    [void]$p.Start()
    $outTask = $p.StandardOutput.ReadToEndAsync()
    $errTask = $p.StandardError.ReadToEndAsync()
    if (-not $p.WaitForExit([int]($BudgetSec * 1000))) {
        try { $p.Kill($true) } catch { try { $p.Kill() } catch { } }
        return @{ Exit = 124; Output = @("(超时 ${BudgetSec}s，进程已终止)") }
    }
    $out = @()
    try { $out = @($outTask.GetAwaiter().GetResult() -split "`r?`n") + @($errTask.GetAwaiter().GetResult() -split "`r?`n" | ForEach-Object { "[err] $_" }) } catch { }
    return @{ Exit = $p.ExitCode; Output = $out }
}

$rows = New-Object System.Collections.Generic.List[object]
function Add-Row([string]$Step, [string]$Expect, [string]$Observed, [bool]$Pass, [int]$Code) {
    $script:rows.Add([pscustomobject]@{
        Step = $Step; Expect = $Expect; Observed = $Observed
        PASS = $(if ($Pass) { "YES" } else { "NO" }); exit = $Code
    })
    $tag = "PASS"; if (-not $Pass) { $tag = "FAIL" }
    Write-Output ("FARM`t{0}`t[{1}] {2}" -f $Step, $tag, $Observed)
}

Write-Output "==================== 故障注入农场门禁（G11：批产→检出→判卷→矩阵→负向N1）===================="

# ---------------------------------------------------------------- ① 批产
$farmArgs = @($FarmPy, "--out", $OutDir, "--python-exe", $PythonExe)
if ($SkipRtu) { $farmArgs += "--skip-rtu" }
$r1 = Invoke-Proc -Exe $PythonExe -ArgList $farmArgs -BudgetSec 240
foreach ($l in ($r1.Output | Where-Object { $_ -match "^FARM\t" })) { Write-Output "  [farm] $l" }
$sumLine = ($r1.Output | Where-Object { $_ -match "^FARM-SUMMARY\t" } | Select-Object -Last 1)
if ($r1.Exit -ne 0) {
    Add-Row "①批产_fault_farm" "退出码 0（全场景 PASS/SKIP）" `
        "退出码 $($r1.Exit)：$sumLine" $false 21
    Write-Output "总退出码 21：农场场景失败（详见上方 [farm] 行）"
    exit 21
}
if (-not $sumLine) {
    Add-Row "①批产_fault_farm" "FARM-SUMMARY 行在场" "汇总行缺失——农场输出不可信" $false 21
    Write-Output "总退出码 21：农场汇总行缺失"
    exit 21
}
Add-Row "①批产_fault_farm" "退出码 0" "$sumLine" $true 0

$allLog    = Join-Path $OutDir "comm_log_all.jsonl"
$truthAll  = Join-Path $OutDir "truth_all.jsonl"
$detections= Join-Path $OutDir "detections_all.jsonl"
$indexPath = Join-Path $OutDir "scenario_index.json"
foreach ($f in @($allLog, $truthAll, $indexPath)) {
    if (-not (Test-Path $f)) {
        Add-Row "①批产产物" "农场产物齐全" "缺 $f" $false 21
        Write-Output "总退出码 21：农场产物不全"
        exit 21
    }
}

# ---------------------------------------------------------------- ② 检出
$r2 = Invoke-Proc -Exe $PythonExe -ArgList @($DetectPy, "--log", $allLog, "--out", $detections) -BudgetSec 120
$detLine = ($r2.Output | Where-Object { $_ -match "^COMM-DETECT\t" } | Select-Object -Last 1)
if ($r2.Exit -ne 0) {
    $why = ($r2.Output | Where-Object { $_ } | Select-Object -Last 2) -join " | "
    Add-Row "②检出_forensics_comm" "退出码 0（契约门+规则检出）" "退出码 $($r2.Exit)：$why" $false 22
    Write-Output "总退出码 22：检出环失败"
    exit 22
}
if (-not (Test-Path $detections)) {
    Add-Row "②检出_forensics_comm" "detections 落盘" "检出文件缺失" $false 22
    Write-Output "总退出码 22：检出文件缺失"
    exit 22
}
Add-Row "②检出_forensics_comm" "退出码 0" "$detLine" $true 0

# ---------------------------------------------------------------- ③ 判卷
function Get-Metric([string[]]$lines, [string]$name) {
    $pat = $name + '\s*=\s*([0-9.]+)'
    $m = [regex]::Match(($lines -join "`n"), $pat)
    if ($m.Success) { return $m.Groups[1].Value }
    return "(缺失)"
}
function Assert-EvalPerfect([string[]]$lines, [int]$exitCode, [string]$step) {
    <# 判卷口径：precision=recall=1.0000（注入类 recall=100% 且 clean/容忍场景误报=0
       同时成立，缺一即 FAIL）。返回错误信息，全绿返回 $null。#>
    if ($exitCode -ne 0) { return "eval 退出码 $exitCode" }
    $p = Get-Metric $lines "precision"
    $rc = Get-Metric $lines "recall"
    if ($p -ne "1.0000" -or $rc -ne "1.0000") {
        $miss = ($lines | Where-Object { $_ -match "^\s+-\s+" } | Select-Object -First 3) -join " | "
        return "precision=$p recall=$rc（要求双 1.0000）漏检/误报：$miss"
    }
    return $null
}

$r3 = Invoke-Proc -Exe $PythonExe -ArgList @($EvalPy, "--logs", $allLog, "--detections", $detections, "--truth", $truthAll) -BudgetSec 120
$bad = Assert-EvalPerfect $r3.Output $r3.Exit "③判卷"
if ($bad) {
    Add-Row "③判卷_eval_forensics" "precision=recall=1.0000" $bad $false 22
    Write-Output "总退出码 22：判卷未达注入类全召回/clean 零误报"
    exit 22
}
Add-Row "③判卷_eval_forensics" "precision=recall=1.0000" `
    "precision=$(Get-Metric $r3.Output 'precision') recall=$(Get-Metric $r3.Output 'recall')（TP=10 FP=0 FN=0 口径见 eval 输出）" $true 0

# ---------------------------------------------------------------- ④ 混淆矩阵
# 场景×检出对账：检出按行号落进 scenario_index 的行区间，检出类集合必须
# ==期望检出集合；期望为空的场景（clean/fragment_byte1）必须零检出。
$index = Get-Content $indexPath -Raw -Encoding UTF8 | ConvertFrom-Json
$detRows = @(Get-Content $detections -Encoding UTF8 | Where-Object { $_.Trim() } |
    ForEach-Object { $_ | ConvertFrom-Json })
$matrixOk = $true
$matrixLines = @()
$offDiag = @()
foreach ($sc in $index) {
    $inRange = @($detRows | Where-Object {
        $no = [int]($_.id -replace "^L", "")
        $no -ge $sc.start_line -and $no -le $sc.end_line
    })
    $got = @($inRange | ForEach-Object { $_.cause } | Sort-Object -Unique)
    $want = @($sc.expected_detection | Sort-Object -Unique)
    $verdict = "DIAG"
    if ($sc.status -eq "SKIP") {
        $verdict = "SKIP"
    } elseif ($want.Count -eq 0) {
        if ($got.Count -ne 0) { $verdict = "OFF"; $matrixOk = $false; $offDiag += "$($sc.scenario)：期望无检出，实得 $($got -join ',')" }
    } elseif ($got.Count -ne $want.Count) {
        $verdict = "OFF"; $matrixOk = $false
        $offDiag += "$($sc.scenario)：检出 [$($got -join ',')] ≠ 注入 [$($want -join ',')]"
    } else {
        for ($i = 0; $i -lt $want.Count; $i++) {
            if ($got[$i] -ne $want[$i]) { $verdict = "OFF"; $matrixOk = $false; $offDiag += "$($sc.scenario)：检出 [$($got -join ',')] ≠ 注入 [$($want -join ',')]" }
        }
    }
    $matrixLines += ("  {0,-16} {1,-14} 注入[{2}] 检出[{3}] {4}" -f `
        $sc.scenario, $sc.status, ($want -join ","), ($got -join ","), $verdict)
}
$orphan = @($detRows | Where-Object {
    $no = [int]($_.id -replace "^L", "")
    -not ($index | Where-Object { $no -ge $_.start_line -and $no -le $_.end_line })
})
if ($orphan.Count -gt 0) {
    $matrixOk = $false
    $offDiag += "检出落在任何场景区间之外：$(($orphan | ForEach-Object { $_.id }) -join ',')"
}
Write-Output "-------------------- 混淆矩阵（场景 × 检出类，检出类必须==注入类）--------------------"
foreach ($l in $matrixLines) { Write-Output $l }
if (-not $matrixOk) {
    Add-Row "④混淆矩阵" "对角化（检出类==注入类，clean 零检出）" ($offDiag -join "；") $false 23
    Write-Output "总退出码 23：混淆矩阵非对角"
    exit 23
}
Add-Row "④混淆矩阵" "对角化（检出类==注入类，clean/容忍零检出）" "全部场景对角；检出 $(@($detRows).Count) 条全部落位" $true 0

# ---------------------------------------------------------------- ⑤ 负向 N1
# 真值**副本**错标一条：timeout→crc_error（探针 GATE-FARM-N1）→ 判卷必须跌破 1.0。
$sb = Join-Path $OutDir "n1_sandbox"
if (Test-Path $sb) { Remove-Item -Recurse -Force $sb }
New-Item -ItemType Directory -Force -Path $sb | Out-Null
$truthPos = Join-Path $sb "truth_pos.jsonl"
$truthBad = Join-Path $sb "truth_bad.jsonl"
Copy-Item -LiteralPath $truthAll -Destination $truthPos -Force

class InjectionMissException : Exception {
    InjectionMissException([string]$msg) : base($msg) { }
}

# 阳性对照：未错标副本走同一条 eval 路径必须仍 1.0000——失败只可能来自错标
$rPos = Invoke-Proc -Exe $PythonExe -ArgList @($EvalPy, "--logs", $allLog, "--detections", $detections, "--truth", $truthPos) -BudgetSec 120
$posBad = Assert-EvalPerfect $rPos.Output $rPos.Exit "N1阳性对照"
if ($posBad) {
    Add-Row "⑤N1阳性对照" "未错标副本仍 1.0000" $posBad $false 24
    Write-Output "总退出码 24：阳性对照未过——副本路径本身有问题，负向证明无效"
    exit 24
}
Add-Row "⑤N1阳性对照" "未错标副本仍 1.0000" "对照通过（precision=recall=1.0000）" $true 0

$targetPath = Join-Path $OutDir "n1_target.json"
$target = Get-Content $targetPath -Raw -Encoding UTF8 | ConvertFrom-Json
$lines = @(Get-Content $truthPos -Encoding UTF8)
$hitIdx = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i].Contains(('"' + 'id' + '": "' + $target.id + '"')) -and
        $lines[$i].Contains(('"cause": "' + $target.cause + '"'))) { $hitIdx = $i; break }
}
if ($hitIdx -lt 0) {
    Add-Row "⑤N1错标注入" "目标行在场（$($target.id)/$($target.cause)）" "注入点未命中：真值副本中找不到目标行" $false 3
    Write-Output "总退出码 3：注入点未命中（注入没生效，检测力证明无效）"
    exit 3
}
$newLine = $lines[$hitIdx].Replace(('"cause": "' + $target.cause + '"'),
    ('"cause": "crc_error", "probe": "GATE-FARM-N1"'))
if ($newLine -ceq $lines[$hitIdx]) {
    Add-Row "⑤N1错标注入" "注入后内容变化" "替换未生效（内容未变）" $false 3
    Write-Output "总退出码 3：注入点未命中（注入没生效，检测力证明无效）"
    exit 3
}
if (-not $newLine.Contains("GATE-FARM-N1")) {
    Add-Row "⑤N1错标注入" "注入后含探针标记" "缺探针标记 GATE-FARM-N1" $false 3
    Write-Output "总退出码 3：注入点未命中（注入没生效，检测力证明无效）"
    exit 3
}
$lines[$hitIdx] = $newLine
[System.IO.File]::WriteAllText($truthBad, ($lines -join "`n") + "`n", (New-Object System.Text.UTF8Encoding($false)))
Add-Row "⑤N1错标注入" "三重断言（计数≥1/内容变化/探针标记）" `
    "已错标 $($target.id)：$($target.cause)→crc_error（探针 GATE-FARM-N1 在场）" $true 0

$rNeg = Invoke-Proc -Exe $PythonExe -ArgList @($EvalPy, "--logs", $allLog, "--detections", $detections, "--truth", $truthBad) -BudgetSec 120
$pNeg = Get-Metric $rNeg.Output "precision"
$rNeg2 = Get-Metric $rNeg.Output "recall"
$hasMiss = ($rNeg.Output | Where-Object { $_ -match "漏检清单" }).Count -gt 0
if (($pNeg -eq "1.0000" -and $rNeg2 -eq "1.0000") -or -not $hasMiss) {
    Add-Row "⑤N1负向必须红" "错标后 precision/recall<1.0000 且漏检清单在场" `
        "错标后 precision=$pNeg recall=$rNeg2 漏检清单=$hasMiss——判卷对错标无感，检测力未证明" $false 24
    Write-Output "总退出码 24：负向 N1 未达预期（判卷没有牙齿）"
    exit 24
}
Add-Row "⑤N1负向必须红" "错标后跌破 1.0 + 漏检清单在场" `
    "precision=$pNeg recall=$rNeg2，漏检清单在场（$($target.id) 错标被抓）——判卷有检测力" $true 0

# ---------------------------------------------------------------- 检测力矩阵
Write-Output ""
Write-Output "==================== 检测力矩阵（步骤/期望/观测/PASS）===================="
foreach ($r in $rows) {
    Write-Output ("  {0,-24} {1,-34} {2}  [PASS={3}]" -f $r.Step, $r.Expect, $r.Observed, $r.PASS)
}
$passCount = @($rows | Where-Object { $_.PASS -eq "YES" }).Count
Write-Output ("检测力矩阵：{0}/{1} PASS（含阳性对照 1 条）" -f $passCount, $rows.Count)
if ($passCount -ne $rows.Count) { Write-Output "总退出码 1：存在未达预期步骤"; exit 1 }
Write-Output "总退出码 0：批产→检出→判卷全链绿，矩阵对角，错标必红——农场闭环有检测力。"
exit 0
