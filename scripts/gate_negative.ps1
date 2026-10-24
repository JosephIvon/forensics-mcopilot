# ============================================================================
#  gate_negative.ps1 —— 门禁负向测试（铁律2/3）：注入已知缺陷，证明门禁真的会 FAIL
#
#  一个永远绿的检查等于没有检查。本脚本对关键门各注入一个已知缺陷（只注入
#  out/gates/negative/ 下的**副本**，tracked 文件零改动），要求对应门必须变红；
#  每个负向用例都带**阳性对照**（同一门跑未注入副本 → 必须 PASS），证明失败
#  来自注入而非副本路径。
#
#  用例（用例/注入点/门/期望）：
#    N1  modbus.json 副本某条 spec_ref.quote 注入编造文本 → G5 quote 反查必须非零退出
#    N2  ModbusTcpClient.cs 副本 `MaxBitResponseBytes = 250` → `245`，副本编译+黄金测试
#        → G2 必须失败（250=ceil(2000/8) 是 P1-1 修复值，退回 245 即翻红）
#    N3  capability_matrix.json 副本 stats.s7.entries 181→180 → 矩阵统计实测对账必须失败
#        （检测器 = gate_docsync.ps1 的 json-vs-实测对账；注：pytest 的
#        test_capability_matrix.py 自 2026-10-21 精简后不含 stats 断言，统计数字的
#        检测力由门禁族的对账脚本承担——README「CI 门禁」节有说明）
#    N4  README 副本「黄金测试（30 条」→「31 条」→ G8 文档一致性必须失败
#    META 元用例：故意不命中的注入点 → 注入器必须退出码 3（注入未生效绝不静默当 PASS）
#
#  铁律3（注入必须验证生效）：每次注入后断言
#    ① 替换计数 ≥ 1；② 注入后内容 ≠ 原内容；③ 注入后文件含探针标记。
#    任一不满足 → 该用例记 exit 3「注入点未命中」（整个脚本末尾退出码 3）。
#
#  退出码：0 = 检测力矩阵全 PASS；1 = 有用例未达预期（门没红/对照没绿）；
#          3 = 任一注入点未命中；100 = 未捕获异常（trap 兜底）。
#  兼容 PowerShell 5.1+ / pwsh 7+。-ErrorAction Stop + trap，异常路径退出码 ≠ 0。
# ============================================================================
[CmdletBinding()]
param(
    [string]$PythonExe = "python",   # 默认用 PATH 上的 python；可用 -PythonExe 覆盖
    [string]$OutDir = "",
    [switch]$Keep
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$env:PYTHONIOENCODING = "utf-8"

trap {
    Write-Output ("[gate-negative-trap] 未捕获异常：{0}（{1} 行 {2}）" -f $_.Exception.Message, `
        $_.InvocationInfo.ScriptName, $_.InvocationInfo.ScriptLineNumber)
    exit 100
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutDir) { $OutDir = Join-Path $RepoRoot "out\gates\negative" }
$TplDir  = Join-Path $RepoRoot "knowledge\templates\protocol"
$KbDir   = Join-Path $RepoRoot "knowledge\protocols"

# 解释器可以是命令名（走 PATH）或完整路径——先解析成可执行文件路径再判存在
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $cmd = Get-Command $PythonExe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { $PythonExe = $cmd.Source }
}

if (-not (Test-Path $PythonExe)) { Write-Output "[negative-fail] python 不存在：$PythonExe"; exit 2 }

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
    <# 铁律3：注入必须验证生效——替换计数≥1、内容改变、含探针标记，任一不满足即抛
       InjectionMissException（该负向用例 exit 3「注入点未命中」，绝不静默当 PASS）。
       MaxCount>0 时只注入前 N 处（如"只往某一条 quote 注入"）。#>
    param([string]$Path, [string]$Pattern, [string]$Replacement,
          [string]$Marker, [int]$MinCount = 1, [int]$MaxCount = 0)
    if (-not (Test-Path $Path)) { throw (New-Object InjectionMissException("注入点文件不存在：$Path")) }
    $before = [System.IO.File]::ReadAllText($Path)
    if ($MaxCount -gt 0) {
        $rx = New-Object System.Text.RegularExpressions.Regex($Pattern)
        $mtx = $rx.Matches($before)
        if ($mtx.Count -lt $MinCount) {
            throw (New-Object InjectionMissException(
                "注入点未命中：$Path 的 /$Pattern/ 只命中 $($mtx.Count) 处（要求 ≥$MinCount）"))
        }
        $n = [Math]::Min($MaxCount, $mtx.Count)
        $after = $rx.Replace($before, $Replacement, $n)
        $hit = $n
    } else {
        $mtx = [regex]::Matches($before, $Pattern)
        if ($mtx.Count -lt $MinCount) {
            throw (New-Object InjectionMissException(
                "注入点未命中：$Path 的 /$Pattern/ 只命中 $($mtx.Count) 处（要求 ≥$MinCount）"))
        }
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

$rows = New-Object System.Collections.Generic.List[object]
function Add-Row([string]$Case, [string]$Point, [string]$Gate, [string]$Expect, [string]$Observed, [bool]$Pass, [int]$Code, [switch]$Skip) {
    $script:rows.Add([pscustomobject]@{
        Case = $Case; Inject = $Point; Gate = $Gate; Expect = $Expect; Observed = $Observed
        PASS = $(if ($Skip) { "SKIP" } elseif ($Pass) { "YES" } else { "NO" }); exit = $Code
    })
    $tag = "PASS"; if ($Skip) { $tag = "SKIP" } elseif (-not $Pass) { $tag = "FAIL" }
    Write-Output ("NEG`t{0}`t{1}`t[{2}] {3}" -f $Case, $tag, $Code, $Observed)
}

$anyMiss = $false
function Run-Case {
    <# 统一用例执行：捕获 InjectionMissException → 记 exit 3「注入点未命中」。#>
    param([string]$Case, [string]$Point, [string]$Gate, [string]$Expect, [scriptblock]$Body)
    try {
        & $Body
    } catch [InjectionMissException] {
        $script:anyMiss = $true
        Add-Row -Case $Case -Point $Point -Gate $Gate -Expect $Expect `
            -Observed ("注入点未命中：" + $_.Exception.Message) -Pass $false -Code 3
    } catch {
        Add-Row -Case $Case -Point $Point -Gate $Gate -Expect $Expect `
            -Observed ("用例异常：" + $_.Exception.Message) -Pass $false -Code 1
    }
}

Write-Output "==================== 门禁负向测试（检测力证明，副本注入，tracked 零改动）===================="

# ---------------------------------------------------------------- N1 → G5
Run-Case "N1_quote反查_编造引文" "modbus.json 副本 spec_ref.quote 首条" "G5 check_modbus_quotes.py" `
    "阳性对照(未注入副本)退出码 0；注入后非 0" {

    # 基线可核性前置检查：没有已提取文本也没有外置原件 ⟹ **基线不可核** ⟹
    # 本用例整条 SKIP，**不执行注入**。
    # 不许把「因为规范文本缺失而拒绝」记成「编造引文被拒」的检测力证明——那是假绿。
    $specs = Join-Path (Split-Path -Parent $RepoRoot) "mcopilot-external\vendor_docs\protocol_specs"
    $extDir = Join-Path $RepoRoot "out\_protocols_extract"
    $hasText = (Test-Path $extDir) -and (@(Get-ChildItem $extDir -Filter "*.txt" -ErrorAction SilentlyContinue).Count -gt 0)
    if (-not $hasText -and -not (Test-Path $specs)) {
        Add-Row -Case "N1_quote反查_编造引文" -Point "modbus.json 副本 spec_ref.quote 首条" `
            -Gate "G5 check_modbus_quotes.py" -Expect "阳性对照(未注入副本)退出码 0；注入后非 0" `
            -Observed "SKIP：协议标准原件按约定外置在 $specs，本机未就位且无已提取文本：基线不可核，无法证明检测力（当前不可自动复核）" `
            -Pass $false -Code 0 -Skip $true
        return
    }
    $sb = New-Sandbox "n1_quote"
    $chk = Copy-Into "scripts\check_modbus_quotes.py" $sb
    $kb  = Copy-Into "knowledge\protocols\modbus.json" $sb
    foreach ($t in (Get-ChildItem (Join-Path $RepoRoot "out\_protocols_extract") -Filter "*.txt")) {
        $null = Copy-Into ("out\_protocols_extract\" + $t.Name) $sb
    }
    # 阳性对照：未注入副本必须 PASS（反查 53/53）
    $pos = Invoke-Proc -Exe $PythonExe -ArgList @($chk) -WorkDir $sb
    $posLine = ($pos.Output | Where-Object { $_ -match "quote 反查：" } | Select-Object -First 1)
    if ($pos.Exit -ne 0) {
        Add-Row -Case "N1阳性对照" -Point "未注入副本" -Gate "G5" -Expect "退出码 0" `
            -Observed "对照退出码 $($pos.Exit)：$posLine" -Pass $false -Code 1
    } else {
        Add-Row -Case "N1阳性对照" -Point "未注入副本" -Gate "G5" -Expect "退出码 0" `
            -Observed "对照通过：$posLine" -Pass $true -Code 0
    }
    # 注入：仅第一条 spec_ref 直属 quote（= 反查器 walk 序的第一条 CHECK 条目）的值
    # 整体替换为编造文本（探针标记内嵌）→ 同源反查必 miss。
    # （不能按文本序盲改首个 "quote"：spec_ref 下层字段行也有 quote，反查器不读它们，
    #   注进去等于没注——检测器的口径决定注入点的口径。）
    $n = Assert-Injection -Path $kb `
        -Pattern '("spec_ref"\s*:\s*\{[^{}]*?"quote"\s*:\s*")([^"]{40,})(")' `
        -Replacement '${1}GATE-NEG-N1 fabricated probe text zezt quux never in any spec page${3}' `
        -Marker "GATE-NEG-N1" -MinCount 1 -MaxCount 1
    $neg = Invoke-Proc -Exe $PythonExe -ArgList @($chk) -WorkDir $sb
    $negLine = ($neg.Output | Where-Object { $_ -match "quote 反查：|✗" } | Select-Object -First 2) -join " | "
    if ($neg.Exit -eq 0) {
        Add-Row -Case "N1_quote反查_编造引文" -Point "modbus.json 副本 spec_ref.quote（命中 $n 处）" -Gate "G5" `
            -Expect "非 0" -Observed "注入后反查仍通过（退出码 0）——检测力未证明" -Pass $false -Code 1
    } else {
        Add-Row -Case "N1_quote反查_编造引文" -Point "modbus.json 副本 spec_ref.quote（命中 $n 处）" -Gate "G5" `
            -Expect "非 0" -Observed "注入后退出码 $($neg.Exit)（反查拒绝编造引文）：$negLine" -Pass $true -Code 0
    }
}

# ---------------------------------------------------------------- N2 → G2
Run-Case "N2_黄金测试_上限常量倒退" "ModbusTcpClient.cs 副本 MaxBitResponseBytes 250→245" "G2 run_frame_tests 逻辑（副本编译+运行）" `
    "阳性对照(未注入副本)30/30 退出码 0；注入后非 0" {

    $sb = New-Sandbox "n2_frame"
    $client = Copy-Into "knowledge\templates\protocol\ModbusTcpClient.cs" $sb
    $rtu    = Copy-Into "knowledge\templates\protocol\ModbusRtuClient.cs" $sb
    $frames = Copy-Into "knowledge\templates\protocol\ModbusFrameTests.cs" $sb
    $driver = Join-Path $sb "FrameTestDriver.cs"
    @"
// 由 gate_negative.ps1 生成：黄金测试驱动（同 run_frame_tests.ps1 的内嵌 Main）
using System;
using Mcopilot.Protocols.Modbus;
internal static class FrameTestDriver
{
    private static int Main()
    {
        try { Console.OutputEncoding = System.Text.Encoding.UTF8; } catch { }
        ModbusTestReport report = ModbusFrameTests.RunAll();
        Console.WriteLine(report.Summary());
        return report.Failed;
    }
}
"@ | Set-Content -Path $driver -Encoding UTF8
    $csc = @("C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
             "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe") |
           Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $csc) { throw "未找到 csc.exe" }
    $exe = Join-Path $sb "FrameTestsRunner.exe"

    function Build-And-Run {
        $r = Invoke-Proc -Exe $csc -ArgList @("/nologo", "/codepage:65001", "/target:exe", "/platform:anycpu", `
            ("/out:{0}" -f $exe), $client, $rtu, $frames, $driver) -WorkDir $sb -BudgetSec 120
        if ($r.Exit -ne 0) { return @{ Exit = 90; Summary = "编译失败" } }
        $rr = Invoke-Proc -Exe $exe -ArgList @() -WorkDir $sb -BudgetSec 120
        $sum = ($rr.Output | Where-Object { $_ -match "黄金测试" } | Select-Object -Last 1)
        return @{ Exit = $rr.Exit; Summary = $sum }
    }

    # 阳性对照：未注入副本编译+运行必须 30/30 全绿
    $pos = Build-And-Run
    if ($pos.Exit -ne 0) {
        Add-Row -Case "N2阳性对照" -Point "未注入副本" -Gate "G2" -Expect "退出码 0" `
            -Observed "对照退出码 $($pos.Exit)：$($pos.Summary)" -Pass $false -Code 1
    } else {
        Add-Row -Case "N2阳性对照" -Point "未注入副本" -Gate "G2" -Expect "退出码 0" `
            -Observed "对照通过：$($pos.Summary)" -Pass $true -Code 0
    }
    # 注入：上限常量 250 → 245（P1-1 修复值倒退），并验证注入生效
    $n = Assert-Injection -Path $client `
        -Pattern 'MaxBitResponseBytes = 250' `
        -Replacement 'MaxBitResponseBytes = 245 /* GATE-NEG-N2 */' `
        -Marker "GATE-NEG-N2" -MinCount 1
    $neg = Build-And-Run
    if ($neg.Exit -eq 0) {
        Add-Row -Case "N2_黄金测试_上限常量倒退" -Point "ModbusTcpClient.cs 副本（命中 $n 处）" -Gate "G2" `
            -Expect "非 0" -Observed "注入后黄金测试仍全绿（退出码 0）——P1-1 回归点失守" -Pass $false -Code 1
    } else {
        Add-Row -Case "N2_黄金测试_上限常量倒退" -Point "ModbusTcpClient.cs 副本（命中 $n 处）" -Gate "G2" `
            -Expect "非 0" -Observed "注入后退出码 $($neg.Exit)（$($neg.Summary)）" -Pass $true -Code 0
    }
}

# ---------------------------------------------------------------- N3 → 矩阵统计对账
Run-Case "N3_矩阵统计数字改错" "capability_matrix.json 副本 stats.s7.json.entries 181→180" "G8 对账器 gate_docsync.ps1（矩阵统计实测对账）" `
    "阳性对照(未注入副本)退出码 0；注入后非 0" {

    $sb = New-Sandbox "n3_matrix"
    $mj = Copy-Into "knowledge\protocols\capability_matrix.json" $sb
    $docsync = Join-Path $PSScriptRoot "gate_docsync.ps1"
    # 阳性对照：未注入副本（仅路径不同）必须 PASS
    $pos = Invoke-Proc -Exe (Get-Process -Id $PID).Path -ArgList @("-NoProfile", "-File", $docsync, `
        "-RepoRoot", $RepoRoot, "-MatrixJsonPath", $mj) -WorkDir $RepoRoot
    $posLine = ($pos.Output | Where-Object { $_ -match "docsync" } | Select-Object -Last 1)
    if ($pos.Exit -ne 0) {
        Add-Row -Case "N3阳性对照" -Point "未注入副本" -Gate "G8 对账器" -Expect "退出码 0" `
            -Observed "对照退出码 $($pos.Exit)：$posLine" -Pass $false -Code 1
    } else {
        Add-Row -Case "N3阳性对照" -Point "未注入副本" -Gate "G8 对账器" -Expect "退出码 0" `
            -Observed "对照通过（副本路径本身不引入漂移）" -Pass $true -Code 0
    }
    # 注入：stats.s7.json.entries 181 → 180，探针标记以合法 JSON 键内嵌同处（一次替换同时落地）
    $n = Assert-Injection -Path $mj `
        -Pattern '("s7\.json"\s*:\s*\{[^{]*?"entries"\s*:\s*)181' `
        -Replacement '${1}180, "gate_negative_probe_marker": "GATE-NEG-N3"' `
        -Marker "GATE-NEG-N3" -MinCount 1
    $chk = Invoke-Proc -Exe $PythonExe -ArgList @("-c", "import json;json.load(open(r'$mj',encoding='utf-8'));print('json-ok')") `
        -WorkDir $RepoRoot -BudgetSec 60
    if ($chk.Exit -ne 0) { throw "注入后的矩阵 json 不再是合法 JSON（注入方式损坏了文件）" }
    # 负向：对账器必须抓住 180 != 实测 181
    $neg = Invoke-Proc -Exe (Get-Process -Id $PID).Path -ArgList @("-NoProfile", "-File", $docsync, `
        "-RepoRoot", $RepoRoot, "-MatrixJsonPath", $mj) -WorkDir $RepoRoot
    $negLine = ($neg.Output | Where-Object { $_ -match "docsync-fail" } | Select-Object -First 2) -join " | "
    if ($neg.Exit -eq 0) {
        Add-Row -Case "N3_矩阵统计数字改错" -Point "capability_matrix.json 副本 stats（命中 $n 处）" -Gate "G8 对账器" `
            -Expect "非 0" -Observed "注入后对账仍通过（退出码 0）——统计漂移漏网" -Pass $false -Code 1
    } else {
        Add-Row -Case "N3_矩阵统计数字改错" -Point "capability_matrix.json 副本 stats（命中 $n 处）" -Gate "G8 对账器" `
            -Expect "非 0" -Observed "注入后退出码 $($neg.Exit)：$negLine" -Pass $true -Code 0
    }
}

# ---------------------------------------------------------------- N4 → G8
Run-Case "N4_README黄金计数漂移" "README 副本「黄金测试（30 条」→「31 条」" "G8 gate_docsync.ps1" `
    "阳性对照(未注入副本)退出码 0；注入后非 0" {

    $sb = New-Sandbox "n4_readme"
    $rd = Copy-Into "knowledge\templates\protocol\README.md" $sb
    $docsync = Join-Path $PSScriptRoot "gate_docsync.ps1"
    $pwshExe = (Get-Process -Id $PID).Path
    $pos = Invoke-Proc -Exe $pwshExe -ArgList @("-NoProfile", "-File", $docsync, `
        "-RepoRoot", $RepoRoot, "-ReadmePath", $rd) -WorkDir $RepoRoot
    if ($pos.Exit -ne 0) {
        Add-Row -Case "N4阳性对照" -Point "未注入副本" -Gate "G8" -Expect "退出码 0" `
            -Observed "对照退出码 $($pos.Exit)" -Pass $false -Code 1
    } else {
        Add-Row -Case "N4阳性对照" -Point "未注入副本" -Gate "G8" -Expect "退出码 0" `
            -Observed "对照通过（副本路径本身不引入漂移）" -Pass $true -Code 0
    }
    $n = Assert-Injection -Path $rd `
        -Pattern '黄金测试（30 条' `
        -Replacement '黄金测试（31 条<!--GATE-NEG-N4-->' `
        -Marker "GATE-NEG-N4" -MinCount 1
    $neg = Invoke-Proc -Exe $pwshExe -ArgList @("-NoProfile", "-File", $docsync, `
        "-RepoRoot", $RepoRoot, "-ReadmePath", $rd) -WorkDir $RepoRoot
    $negLine = ($neg.Output | Where-Object { $_ -match "docsync-fail" } | Select-Object -First 1)
    if ($neg.Exit -eq 0) {
        Add-Row -Case "N4_README黄金计数漂移" -Point "README 副本（命中 $n 处）" -Gate "G8" `
            -Expect "非 0" -Observed "注入后文档一致性仍通过（退出码 0）——数字漂移漏网" -Pass $false -Code 1
    } else {
        Add-Row -Case "N4_README黄金计数漂移" -Point "README 副本（命中 $n 处）" -Gate "G8" `
            -Expect "非 0" -Observed "注入后退出码 $($neg.Exit)：$negLine" -Pass $true -Code 0
    }
}

# ---------------------------------------------------------------- META 元用例
Run-Case "META_注入器必须能失败" "故意不命中的注入点" "本脚本 Assert-Injection" `
    "注入点未命中 → exit 3（绝不静默当 PASS）" {

    $sb = New-Sandbox "meta_probe"
    $probe = Copy-Into "knowledge\protocols\anchors.json" $sb
    try {
        Assert-Injection -Path $probe -Pattern '这个正则绝对不会命中__zzz__META' `
            -Replacement 'x' -Marker "GATE-NEG-META" -MinCount 1 | Out-Null
        Add-Row -Case "META_注入器必须能失败" -Point "故意不命中的正则" -Gate "注入器自检" `
            -Expect "抛注入未命中" -Observed "注入器对不命中的注入点没有报错——负向测试会自欺" -Pass $false -Code 1
    } catch [InjectionMissException] {
        Add-Row -Case "META_注入器必须能失败" -Point "故意不命中的正则" -Gate "注入器自检" `
            -Expect "抛注入未命中" -Observed "注入器正确抛出注入未命中（exit 3 语义）" -Pass $true -Code 0
    }
}

# ---------------------------------------------------------------- 检测力矩阵
Write-Output ""
Write-Output "==================== 检测力矩阵（用例/注入点/门/期望/观测/PASS）===================="
Write-Output ("  {0,-26} {1,-44} {2,-28} {3,-6} {4}" -f "用例", "注入点", "门", "期望", "观测/PASS")
Write-Output ("  " + ("-" * 130))
foreach ($r in $rows) {
    $obs = $r.Observed + "  [PASS=" + $r.PASS + "]"
    Write-Output ("  {0,-26} {1,-44} {2,-28} {3,-6} {4}" -f $r.Case, $r.Inject, $r.Gate, $r.Expect, $obs)
}
Write-Output ("  " + ("-" * 130))
$passCount = @($rows | Where-Object { $_.PASS -eq "YES" }).Count
$skipCount = @($rows | Where-Object { $_.PASS -eq "SKIP" }).Count
$judged = $rows.Count - $skipCount
Write-Output ("检测力矩阵：{0}/{1} PASS（阳性对照 {2} 条含内）" -f $passCount, $judged,
    @($rows | Where-Object { $_.Case -like "*阳性对照*" }).Count)
if ($skipCount -gt 0) {
    Write-Output ("SKIP {0} 条（**没跑**，不是没通过；当前不可自动复核）：" -f $skipCount)
    foreach ($r in @($rows | Where-Object { $_.PASS -eq "SKIP" })) {
        Write-Output ("  - {0}：{1}" -f $r.Case, $r.Observed)
    }
}

if (-not $Keep) {
    Get-ChildItem $OutDir -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^(n\d_|meta_probe)' } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

if ($anyMiss) { Write-Output "总退出码 3：存在注入点未命中（注入没生效，检测力证明无效）"; exit 3 }
if ($passCount -ne $judged) { Write-Output "总退出码 1：存在未达预期的负向/对照用例"; exit 1 }
if ($skipCount -gt 0) {
    Write-Output "总退出码 0：已跑的用例全绿；SKIP 的用例**没跑**（当前不可自动复核），不算检测力已证明。"
} else {
    Write-Output "总退出码 0：每个注入都让对应门变红，阳性对照全绿——检测力已证明。"
}
exit 0
