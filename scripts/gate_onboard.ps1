# ============================================================================
#  gate_onboard.ps1 —— 接入闭环门禁（G10，退出码域 19）：三场景验收
#
#  验收对象：scripts/onboard_loop.py（harness 接入闭环第一切片："把模拟设备接进
#  来"的完整循环 + 失败解读引擎）。架构原则=智能体在外、确定性内核在内：循环
#  决策权只限"解读失败+选下一步"，执行必走既有门禁（run_contract.ps1 / 其
#  normal 阶段的同源同参沙盒复刻）。
#
#  三场景（每场景独立退出码记录，独立 RESULT 行；负向纪律同五铁律：
#  副本注入（tracked 零改动）+ 注入三重断言 + 阳性对照）：
#    场景 A 全绿路径：正常从站 → 循环接入成功 → 报告含矩阵查询与契约 PASS 记录
#                     （走 canonical 路线 = run_contract.ps1 三阶段 18 条）
#    场景 B 已知故障归因：注入 byteCount 245 缺陷副本（gate_negative N2 同款注入点，
#                     MaxBitResponseBytes 250→245）→ 循环必须归因到
#                     SIG-P1-1-BITBYTE-CAP-245 且 next_action 正确（恢复 250），
#                     绝不许 UNKNOWN；随后按语料 action_class 弃用副本恢复模板源
#                     复跑 → 全绿出报告。阳性对照=未注入副本同路径必须 exit 0。
#    场景 C 未知故障升级：注入语料库外新缺陷（契约源 FC3 种子期望常量 1234→1235）
#                     → 循环必须 UNKNOWN 结构化上报（unknown_report.json 证据包）
#                     而非误归因到任何已知签名；绝不自动重试。阳性对照同上。
#
#  退出码：0 = 三场景全过；1 = 有场景未达预期；3 = 任一注入点未命中（注入未生效
#          绝不静默当 PASS）；2 = 用法/环境错误；100 = 未捕获异常（trap 兜底）。
#  总退出码域 = 19（gate_protocol.ps1 G10）。
#  兼容 PowerShell 5.1+ / pwsh 7+；⚠ 实际运行必须用 pwsh（5.1 下 .NET EventSource
#  初始化即崩，同 gate_protocol 的告诫）。
# ============================================================================
[CmdletBinding()]
param(
    [string]$PythonExe = "python",   # 默认用 PATH 上的 python；可用 -PythonExe 覆盖
    [string]$OutDir = "",
    [string]$Only = "",
    [switch]$Keep
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$env:PYTHONIOENCODING = "utf-8"

trap {
    Write-Output ("[onboard-trap] 未捕获异常：{0}（{1} 行 {2}）" -f $_.Exception.Message, `
        $_.InvocationInfo.ScriptName, $_.InvocationInfo.ScriptLineNumber)
    exit 100
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutDir) { $OutDir = Join-Path $RepoRoot "out\gates\onboard" }
$LoopPy = Join-Path $RepoRoot "scripts\onboard_loop.py"
$ClientCsTpl = Join-Path $RepoRoot "knowledge\templates\protocol\ModbusTcpClient.cs"
$ContractCsTpl = Join-Path $RepoRoot "knowledge\templates\protocol\ModbusContractTests.cs"

# 解释器可以是命令名（走 PATH）或完整路径——先解析成可执行文件路径再判存在
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $cmd = Get-Command $PythonExe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { $PythonExe = $cmd.Source }
}

if (-not (Test-Path $PythonExe)) { Write-Output "[onboard-fail] python 不存在：$PythonExe"; exit 2 }
foreach ($f in @($LoopPy, $ClientCsTpl, $ContractCsTpl)) {
    if (-not (Test-Path $f)) { Write-Output "[onboard-fail] 缺少必需文件：$f"; exit 2 }
}

# ---------------------------------------------------------------- 基础设施（同 gate_negative 纪律）
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
        return @{ Exit = 124; Output = @("(超时 ${BudgetSec}s)") }
    }
    $out = @()
    try { $out = @($outTask.GetAwaiter().GetResult() -split "`r?`n") + @($errTask.GetAwaiter().GetResult() -split "`r?`n" | ForEach-Object { "[err] $_" }) } catch { }
    return @{ Exit = $p.ExitCode; Output = $out }
}

function New-Sandbox([string]$case) {
    $dir = Join-Path $OutDir $case
    if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    return $dir
}

function Copy-Into([string]$src, [string]$dstDir) {
    $dst = Join-Path $dstDir $src
    New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
    Copy-Item -LiteralPath $src -Destination $dst -Force
    return $dst
}

class InjectionMissException : Exception {
    InjectionMissException([string]$msg) : base($msg) { }
}

function Assert-Injection {
    <# 铁律3（注入必须验证生效）三重断言：① 替换计数 ≥ MinCount；② 注入后内容 ≠ 原内容；
       ③ 注入后文件含探针标记。任一不满足 → 抛 InjectionMissException（该用例 exit 3）。#>
    param([string]$Path, [string]$Pattern, [string]$Replacement,
          [string]$Marker, [int]$MinCount = 1, [int]$MaxCount = 0)
    if (-not (Test-Path $Path)) { throw (New-Object InjectionMissException("注入点文件不存在：$Path")) }
    $before = [System.IO.File]::ReadAllText($Path)
    $mtx = [regex]::Matches($before, $Pattern)
    if ($mtx.Count -lt $MinCount) {
        throw (New-Object InjectionMissException(
            "注入点未命中：$Path 的 /$Pattern/ 只命中 $($mtx.Count) 处（要求 ≥$MinCount）"))
    }
    if ($MaxCount -gt 0) {
        $rx = New-Object System.Text.RegularExpressions.Regex($Pattern)
        $n = [Math]::Min($MaxCount, $mtx.Count)
        $after = $rx.Replace($before, $Replacement, $n)
        $hit = $n
    } else {
        $after = [regex]::Replace($before, $Pattern, $Replacement)
        $hit = $mtx.Count
    }
    if ($after -ceq $before) {
        throw (New-Object InjectionMissException("注入后内容未变化：$Path"))
    }
    if ($after.IndexOf($Marker, [System.StringComparison]::Ordinal) -lt 0) {
        throw (New-Object InjectionMissException("注入后缺探针标记「$Marker」：$Path"))
    }
    [System.IO.File]::WriteAllText($Path, $after, (New-Object System.Text.UTF8Encoding($false)))
    return $hit
}

$PwshExe = (Get-Process -Id $PID).Path
if (-not $PwshExe) { $PwshExe = "pwsh" }

function Invoke-OnboardLoop {
    <# 跑一轮接入闭环。$Tag 用于隔离 out-dir（每次运行独立目录，防 sandbox exe 冲突）。#>
    param([string]$Tag, [string]$SbDir, [string]$ClientCs = "", [string]$ContractCs = "",
          [int]$MaxAttempts = 2)
    $loopOut = Join-Path $SbDir $Tag
    $argList = @($LoopPy, "--python-exe", $PythonExe, "--pwsh-exe", $PwshExe,
                 "--out-dir", $loopOut, "--max-attempts", "$MaxAttempts")
    if ($ClientCs) { $argList += @("--client-cs", $ClientCs) }
    if ($ContractCs) { $argList += @("--contract-tests-cs", $ContractCs) }
    $r = Invoke-Proc -Exe $PythonExe -ArgList $argList -WorkDir $RepoRoot -BudgetSec 240
    $r.OutputText = ($r.Output -join "`n")
    $r.ReportMd = Join-Path $loopOut "onboard_report.md"
    $r.ReportJson = Join-Path $loopOut "onboard_report.json"
    $r.LoopOut = $loopOut
    return $r
}

$rows = New-Object System.Collections.Generic.List[object]
function Add-Row([string]$Case, [string]$Point, [string]$Expect, [string]$Observed, [bool]$Pass, [int]$Code) {
    $script:rows.Add([pscustomobject]@{
        Case = $Case; Inject = $Point; Expect = $Expect; Observed = $Observed
        PASS = $(if ($Pass) { "YES" } else { "NO" }); exit = $Code
    })
    $tag = "PASS"; if (-not $Pass) { $tag = "FAIL" }
    Write-Output ("ONBOARD`t{0}`t[{1}] {2}" -f $Case, $tag, $Observed)
}

$anyMiss = $false
$anyFail = $false
function Invoke-Scenario {
    param([string]$Case, [string]$Point, [string]$Expect, [scriptblock]$Body)
    try {
        & $Body
    } catch [InjectionMissException] {
        $script:anyMiss = $true
        Add-Row -Case $Case -Point $Point -Expect $Expect `
            -Observed ("注入点未命中：" + $_.Exception.Message) -Pass $false -Code 3
    } catch {
        $script:anyFail = $true
        Add-Row -Case $Case -Point $Point -Expect $Expect `
            -Observed ("用例异常：" + $_.Exception.Message) -Pass $false -Code 1
    }
}

# 断言小工具：不满足即抛（调用方捕获后计该场景 FAIL）
function Assert-That([bool]$cond, [string]$msg) {
    if (-not $cond) { throw $msg }
}

Write-Output "==================== 接入闭环门禁 G10（三场景，副本注入，tracked 零改动）===================="

# ---------------------------------------------------------------- 场景 A：全绿路径
if ($Only -eq "" -or $Only -eq "A") {
    Invoke-Scenario "A_全绿路径_canonical" "无注入（正常从站 15020）" `
        "循环 exit 0；报告含矩阵查询与契约 PASS 记录；无失败归因" {

        $sb = New-Sandbox "a_green"
        $r = Invoke-OnboardLoop -Tag "run" -SbDir $sb -MaxAttempts 2
        Assert-That ($r.Exit -eq 0) ("循环退出码 {0}（期望 0）。输出尾：{1}" -f $r.Exit,
            (($r.Output | Where-Object { $_ } | Select-Object -Last 4) -join " | "))
        Assert-That ($r.OutputText -match "STAGE`tSENSE") "缺 STAGE SENSE 行（状态机输出不完整）"
        Assert-That ($r.OutputText -match "DECISION`t") "缺 DECISION 行（状态机输出不完整）"
        Assert-That ($r.OutputText -match "ATTRIBUTION`tNONE") "缺 ATTRIBUTION NONE 行（无失败时应显式记 NONE）"
        Assert-That (Test-Path $r.ReportMd) "《接入报告》md 未产出：$($r.ReportMd)"
        Assert-That (Test-Path $r.ReportJson) "《接入报告》json 未产出：$($r.ReportJson)"
        $md = [System.IO.File]::ReadAllText($r.ReportMd)
        Assert-That ($md -match "矩阵查询") "报告缺「矩阵查询」记录（感知步骤必须在案）"
        Assert-That ($md -match "Modbus TCP") "报告缺协议名（矩阵查询记录不完整）"
        Assert-That ($md -match "PASS") "报告缺契约 PASS 记录"
        $json = Get-Content $r.ReportJson -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-That ($json.conclusion -eq "ONBOARDED") ("报告结论 {0} != ONBOARDED" -f $json.conclusion)
        Assert-That (@($json.results).Count -ge 18) ("报告契约 PASS 记录仅 {0} 条（canonical 三阶段应有 ≥18 条）" -f @($json.results).Count)
        Add-Row -Case "A_全绿路径_canonical" -Point "无注入（正常从站 15020，run_contract.ps1 三阶段）" `
            -Expect "exit 0 + 报告含矩阵查询与 PASS 记录" `
            -Observed ("exit 0；契约 {0} 条全 PASS；报告与状态机输出齐全" -f @($json.results).Count) `
            -Pass $true -Code 0
    }
}

# ---------------------------------------------------------------- 场景 B：已知故障归因
if ($Only -eq "" -or $Only -eq "B") {
    Invoke-Scenario "B_已知故障归因_byteCount245" "ModbusTcpClient.cs 副本 MaxBitResponseBytes 250→245" `
        "阳性对照 exit 0；注入后循环归因 SIG-P1-1 且 next_action 正确，绝无 UNKNOWN，复跑转绿" {

        $sb = New-Sandbox "b_bytecap"
        $client = Copy-Into "knowledge\templates\protocol\ModbusTcpClient.cs" $sb

        # 阳性对照：未注入副本走同一路径（沙盒 normal 阶段）必须 exit 0 —— 失败只可能来自注入
        $pos = Invoke-OnboardLoop -Tag "pos" -SbDir $sb -ClientCs $client -MaxAttempts 2
        Assert-That ($pos.Exit -eq 0) ("阳性对照退出码 {0}（期望 0）——副本路径本身有问题，注入证明无效" -f $pos.Exit)
        Add-Row -Case "B_阳性对照_未注入副本" -Point "ModbusTcpClient.cs 副本（未注入）" `
            -Expect "exit 0" -Observed "对照通过：沙盒路径 15 条契约全 PASS（exit 0）" -Pass $true -Code 0

        # 注入：P1-1 修复值倒退（gate_negative N2 同款注入点），三重断言在 Assert-Injection 内
        $n = Assert-Injection -Path $client `
            -Pattern 'MaxBitResponseBytes = 250' `
            -Replacement 'MaxBitResponseBytes = 245 /* GATE-ONBOARD-B */' `
            -Marker "GATE-ONBOARD-B" -MinCount 1

        # 负向：循环必须归因 SIG-P1-1（不许 UNKNOWN），且按语料动作恢复模板源复跑转绿
        $neg = Invoke-OnboardLoop -Tag "neg" -SbDir $sb -ClientCs $client -MaxAttempts 3
        Assert-That ($neg.Exit -eq 0) ("循环最终退出码 {0}（期望 0：归因后恢复模板源复跑应转绿）。输出尾：{1}" -f $neg.Exit,
            (($neg.Output | Where-Object { $_ } | Select-Object -Last 6) -join " | "))
        Assert-That ($neg.OutputText -match "ATTRIBUTION`tSIG-P1-1-BITBYTE-CAP-245") `
            "循环未归因到 SIG-P1-1-BITBYTE-CAP-245（已知故障必须确定性归因）"
        Assert-That ($neg.OutputText -notmatch "ATTRIBUTION`tUNKNOWN") `
            "已知故障被当成 UNKNOWN 上报（不许把语料库内失败升级）"
        Assert-That ($neg.OutputText -match "DECISION`tRERUN_CANONICAL") `
            "未执行语料 action_class=rerun_canonical（弃用副本恢复模板源）的决策"
        Assert-That (Test-Path $neg.ReportMd) "《接入报告》未产出"
        $negMd = [System.IO.File]::ReadAllText($neg.ReportMd)
        Assert-That ($negMd -match "SIG-P1-1-BITBYTE-CAP-245") "报告未把 P1-1 归因在案"
        Assert-That ($negMd -match "250") "报告/语料 next_action 未指向恢复 250（P1-1 修复值）"
        $negJson = Get-Content $neg.ReportJson -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-That (@($negJson.attributions).Count -ge 1) "报告 attributions 为空（归因丢失）"
        Add-Row -Case "B_已知故障归因_byteCount245" -Point "ModbusTcpClient.cs 副本（命中 $n 处）" `
            -Expect "归因 SIG-P1-1 + rerun_canonical 复跑转绿 + 无 UNKNOWN" `
            -Observed ("attempt1 沙盒归因 P1-1（245 缺陷）→ 恢复模板源复跑全绿；报告在案") `
            -Pass $true -Code 0
    }
}

# ---------------------------------------------------------------- 场景 C：未知故障升级
if ($Only -eq "" -or $Only -eq "C") {
    Invoke-Scenario "C_未知故障升级_语料外常量" "ModbusContractTests.cs 副本 FC3 种子期望 1234→1235（语料库外）" `
        "阳性对照 exit 0；注入后循环必须 UNKNOWN 上报且零误归因，绝不猜、绝不重试" {

        $sb = New-Sandbox "c_unknown_const"
        $tests = Copy-Into "knowledge\templates\protocol\ModbusContractTests.cs" $sb

        # 阳性对照：未注入副本同路径必须 exit 0
        $pos = Invoke-OnboardLoop -Tag "pos" -SbDir $sb -ContractCs $tests -MaxAttempts 2
        Assert-That ($pos.Exit -eq 0) ("阳性对照退出码 {0}（期望 0）" -f $pos.Exit)
        Add-Row -Case "C_阳性对照_未注入副本" -Point "ModbusContractTests.cs 副本（未注入）" `
            -Expect "exit 0" -Observed "对照通过：沙盒路径 15 条契约全 PASS（exit 0）" -Pass $true -Code 0

        # 注入：语料库外的新缺陷（契约期望常量改错值），只注第一处（FC3_ReadSeededRegisters）
        $n = Assert-Injection -Path $tests `
            -Pattern 'Check\(regs\[0\] == 1234 && regs\[1\] == 5678,' `
            -Replacement 'Check(regs[0] == 1235 && regs[1] == 5678, /* GATE-ONBOARD-C */' `
            -Marker "GATE-ONBOARD-C" -MinCount 1 -MaxCount 1

        # 负向：循环必须 UNKNOWN（exit 20）且零误归因，不得重试
        $neg = Invoke-OnboardLoop -Tag "neg" -SbDir $sb -ContractCs $tests -MaxAttempts 2
        Assert-That ($neg.Exit -eq 20) ("循环退出码 {0}（期望 20=UNKNOWN 升级）。输出尾：{1}" -f $neg.Exit,
            (($neg.Output | Where-Object { $_ } | Select-Object -Last 6) -join " | "))
        Assert-That ($neg.OutputText -match "ATTRIBUTION`tUNKNOWN") "缺 ATTRIBUTION UNKNOWN 行"
        Assert-That ($neg.OutputText -notmatch "ATTRIBUTION`tSIG-") `
            "语料库外失败被误归因到已知签名（绝不允许）"
        Assert-That ($neg.OutputText -match "DECISION`tESCALATE") "未知失败应 DECISION ESCALATE（交人/LLM）"
        $unknownJsonPath = Join-Path $neg.LoopOut "unknown_report.json"
        Assert-That (Test-Path $unknownJsonPath) "UNKNOWN 证据包 unknown_report.json 未产出"
        $uj = Get-Content $unknownJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-That ($uj.status -eq "UNKNOWN") "证据包 status != UNKNOWN"
        Assert-That ($null -ne $uj.failing_result_lines -and @($uj.failing_result_lines).Count -ge 1) `
            "证据包缺失败 RESULT 行（证据包不完整）"
        Add-Row -Case "C_未知故障升级_语料外常量" -Point "ModbusContractTests.cs 副本（命中 $n 处）" `
            -Expect "exit 20 + UNKNOWN 证据包 + 零误归因" `
            -Observed ("循环 UNKNOWN 升级（exit 20），零签名误归因，证据包含失败 RESULT 与输出尾巴") `
            -Pass $true -Code 0
    }
}

# ---------------------------------------------------------------- 检测力矩阵
Write-Output ""
Write-Output "==================== 接入闭环检测力矩阵（场景/注入点/期望/观测/PASS）===================="
Write-Output ("  {0,-30} {1,-52} {2,-8} {3}" -f "场景", "注入点", "期望", "观测/PASS")
Write-Output ("  " + ("-" * 130))
foreach ($r in $rows) {
    $obs = $r.Observed + "  [PASS=" + $r.PASS + "]"
    Write-Output ("  {0,-30} {1,-52} {2,-8} {3}" -f $r.Case, $r.Inject, $r.Expect, $obs)
}
Write-Output ("  " + ("-" * 130))
$passCount = @($rows | Where-Object { $_.PASS -eq "YES" }).Count
Write-Output ("接入闭环三场景：{0}/{1} PASS（阳性对照 {2} 条含内）" -f $passCount, $rows.Count,
    @($rows | Where-Object { $_.Case -like "*阳性对照*" }).Count)

if (-not $Keep) {
    Get-ChildItem $OutDir -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^(a_|b_|c_)' } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

if ($anyMiss) { Write-Output "总退出码 3：存在注入点未命中（注入没生效，检测力证明无效）"; exit 3 }
if ($anyFail -or $passCount -ne $rows.Count) { Write-Output "总退出码 1：存在未达预期的场景/对照"; exit 1 }
Write-Output "总退出码 0：全绿路径接入成功、已知故障确定性归因并复跑转绿、未知故障 UNKNOWN 升级零误归因。"
exit 0
