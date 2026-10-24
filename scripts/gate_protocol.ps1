# ============================================================================
#  gate_protocol.ps1 —— 协议域总门禁（铁律1）：把本域全部"结论"落成可执行门禁
#
#  顺序跑 G1-G12，每门独立超时（默认 300s，超时=该门失败）、独立退出码域，
#  每门输出 RESULT<TAB>PASS|FAIL|SKIP<TAB>门名<TAB>摘要；总退出码 = 失败门数
#  （SKIP 不计失败）。末尾写机器可读汇总 out/gates/gate_report_<时间戳>.json
#  （含各门时长、原始退出码、git HEAD）。
#
#  门清单与退出码域：
#    G1 编译（csc 直编客户端+契约源，0 错误）                    -> 域 10
#    G2 黄金帧测试（run_frame_tests.ps1，30 条）                 -> 域 11
#    G3 TCP 契约三阶段（run_contract.ps1 18 条）+ sweep 扫掠 1 条 -> 域 12
#    G4 RTU 行为契约（run_rtu_contract.ps1 11 条）+ 超时契约 1 条；
#       前置探测 COM3/COM4+com0com，缺失则整门 SKIP 不算败        -> 域 13
#    G5 quote 反查（check_modbus_quotes.py，53/53）              -> 域 14
#    G6 pytest 协议域子集（4 个测试文件）                         -> 域 15
#    G7 外部锚点（gate_anchors.py：sha256+再提取抽查+URL WARN）   -> 域 16
#    G8 文档一致性（gate_docsync.ps1：数字全部从代码/知识库实算）  -> 域 17
#    G9 SLMP 契约（smoke_slmp.py C1-C9）                         -> 域 18
#    G10 接入闭环（gate_onboard.ps1 三场景：全绿/已知归因/未知升级）-> 域 19
#    G11 故障注入农场（gate_farm.ps1：批产→检出→判卷→矩阵→负向N1错标必红）-> 域 20
#    G12 真实语料（gate_corpus.ps1：Lemay 夹具逐行断言+负向三重→全量检出判卷；
#        数据缺失→SKIP 不算败；真实分布误报率只报告不设阈值）      -> 域 21
#    G13 接缝3评测集（gate_joint_eval.py：静态核对两侧 BEH 编号与评测集一致 + 真跑两侧逐条对齐；缺编译器/缺工厂兄弟仓→动态截 SKIP）  -> 域 22
#
#  -Only G2,G5 可只跑子集（此时失败门的退出码 = 其退出码域值）。
#  兼容 PowerShell 5.1+ / pwsh 7+。-ErrorAction Stop + trap 兜底：异常路径退出码 100 ≠ 0，
#  绝不"崩溃即过"。
# ============================================================================
[CmdletBinding()]
param(
    [string]$PythonExe = "python",   # 默认用 PATH 上的 python；可用 -PythonExe 覆盖
    [string]$PyTestExe = "python",   # 同上
    [int]$TimeoutSeconds = 300,
    [string]$Only = "",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$env:PYTHONIOENCODING = "utf-8"

trap {
    Write-Output ("[gate-trap] 未捕获异常：{0}（{1} 行 {2}）" -f $_.Exception.Message, `
        $_.InvocationInfo.ScriptName, $_.InvocationInfo.ScriptLineNumber)
    try { $script:active | Stop-Process -Force -ErrorAction SilentlyContinue } catch { }
    exit 100
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutDir) { $OutDir = Join-Path $RepoRoot "out\gates" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$TplDir     = Join-Path $RepoRoot "knowledge\templates\protocol"
$SlavePy    = Join-Path $RepoRoot "tests\fixtures\modbus\modbus_tcp_slave.py"
$RtuSinkDir = Join-Path $OutDir "g4_rtu_timeout"
$G3Dir      = Join-Path $OutDir "g3_sweep"
$G1Dir      = Join-Path $OutDir "g1_compile"
$script:active = @()          # 本门禁拉起的从站/桩进程（finally 统一清理）

# 解释器可以是命令名（走 PATH）或完整路径——先解析成可执行文件路径再判存在
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $cmd = Get-Command $PythonExe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { $PythonExe = $cmd.Source }
}
# 解释器可以是命令名（走 PATH）或完整路径——先解析成可执行文件路径再判存在
if (-not (Test-Path -LiteralPath $PyTestExe)) {
    $cmd = Get-Command $PyTestExe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { $PyTestExe = $cmd.Source }
}

foreach ($exe in @($PythonExe, $PyTestExe)) {
    if (-not ($exe -and (Test-Path $exe))) { Write-Output "[gate-fail] python 不存在：$exe"; exit 2 }
}

# ---------------------------------------------------------------- 基础设施
function Find-Csc {
    $cands = @("C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
               "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe")
    foreach ($c in $cands) { if (Test-Path $c) { return $c } }
    throw "未找到 .NET Framework csc.exe（v4.0.30319）"
}

function Quote-Arg([string]$a) { '"' + ($a -replace '"', '\"') + '"' }

function Invoke-Proc {
    <# 跑一条命令：捕获 stdout/stderr、限时（超时即杀）。返回 @{Exit;TimedOut;Output}。
       Output 为字符串数组（stdout+stderr 合并，stderr 前缀 [err]）。
       预算 = min(显式 BudgetSec, 当前门剩余预算)——落实"每门单超时 300s，超时=该门失败"。#>
    param([string]$Exe, [string[]]$ArgList, [string]$WorkDir = $RepoRoot, [int]$BudgetSec = 300)
    if ($null -ne $script:gateDeadline) {
        $remain = [int]($script:gateDeadline - (Get-Date)).TotalSeconds
        if ($remain -lt 5) { $remain = 5 }
        if ($remain -lt $BudgetSec) { $BudgetSec = $remain }
    }
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
    $ok = $p.WaitForExit([int]($BudgetSec * 1000))
    if (-not $ok) {
        try { $p.Kill($true) } catch { try { $p.Kill() } catch { } }
        return @{ Exit = 124; TimedOut = $true; Output = @("(超时：预算 ${BudgetSec}s，进程已终止)") }
    }
    $out = @()
    try { $out = @($outTask.GetAwaiter().GetResult() -split "`r?`n") + @($errTask.GetAwaiter().GetResult() -split "`r?`n" | ForEach-Object { "[err] $_" }) } catch { }
    return @{ Exit = $p.ExitCode; TimedOut = $false; Output = $out }
}

function Test-PortOpen([string]$h, [int]$p, [int]$timeoutMs) {
    $c = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $c.BeginConnect($h, $p, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne($timeoutMs, $false) -and $c.Connected) { return $true }
        return $false
    } catch { return $false }
    finally { try { $c.Close() } catch { } }
}

function Start-GateSlave {
    <# 拉起 python 从站/桩（stdout/stderr 落日志），登记进 $script:active 便于兜底清理。#>
    param([string[]]$ArgList, [string]$Name, [string]$WorkDir)
    $outLog = Join-Path $WorkDir ("{0}_stdout.log" -f $Name)
    $errLog = Join-Path $WorkDir ("{0}_stderr.log" -f $Name)
    $proc = Start-Process -FilePath $PythonExe -ArgumentList ($ArgList | ForEach-Object { Quote-Arg $_ }) `
              -NoNewWindow -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    $script:active += $proc
    return @{ Proc = $proc; OutLog = $outLog; ErrLog = $errLog }
}

function Stop-GateSlave($h) {
    if ($null -eq $h) { return }
    try {
        if (-not $h.Proc.HasExited) {
            Stop-Process -Id $h.Proc.Id -Force -ErrorAction SilentlyContinue
            $h.Proc.WaitForExit(3000) | Out-Null
        }
    } catch { }
    $script:active = @($script:active | Where-Object { $_ -ne $h.Proc })
}

function Wait-PortReady([int]$port, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortOpen "127.0.0.1" $port 300) { return $true }
        Start-Sleep -Milliseconds 200
    }
    return $false
}

function Wait-LogMarker([string]$log, [string]$marker, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        $text = Get-Content $log -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
        if ($text -and $text.Contains($marker)) { return $true }
        Start-Sleep -Milliseconds 200
    }
    return $false
}

function Get-GitHead {
    try {
        $git = Get-Command git -ErrorAction SilentlyContinue
        if (-not $git) { return "unknown(no-git)" }
        $head = (& git -C $RepoRoot rev-parse HEAD 2>$null)
        $branch = (& git -C $RepoRoot rev-parse --abbrev-ref HEAD 2>$null)
        if ($LASTEXITCODE -ne 0 -or -not $head) { return "unknown" }
        return ("{0} ({1})" -f $head, $branch)
    } catch { return "unknown" }
}

$PwshExe = (Get-Process -Id $PID).Path
if (-not $PwshExe) { $PwshExe = "pwsh" }
$CscExe = Find-Csc

# ---------------------------------------------------------------- 生成物（G3/G4）
# G3：sweep 阶段专用 runner（复用 ModbusContractRunner 的 Main：ModbusContractTests.cs
#     里新增的 "sweep" 阶段 → 15024 扫掠实例，退出码 = 失败数）
function New-G3SweepRunner {
    New-Item -ItemType Directory -Force -Path $G3Dir | Out-Null
    $exe = Join-Path $G3Dir "ModbusSweepRunner.exe"
    $src = @((Join-Path $TplDir "ModbusTcpClient.cs"),
             (Join-Path $TplDir "ModbusContractTests.cs"),
             (Join-Path $TplDir "ModbusContractRunner.cs"))
    $argList = @("/nologo", "/codepage:65001", "/target:exe", "/platform:anycpu", "/out:$exe") + $src
    $r = Invoke-Proc -Exe $CscExe -ArgList $argList -BudgetSec 120
    if ($r.Exit -ne 0) { throw "G3 sweep runner 编译失败（csc 退出码 $($r.Exit)）：`n" + ($r.Output -join "`n") }
    return $exe
}

# G4：no-respond 桩（收帧不回——复用 modbus_rtu_slave 的 kernel32 串口层，读到的帧全部丢弃）
function New-G4Artifacts {
    New-Item -ItemType Directory -Force -Path $RtuSinkDir | Out-Null
    $sinkPy = Join-Path $RtuSinkDir "no_respond_slave.py"
    $fixtureDir = Join-Path $RepoRoot "tests\fixtures\modbus"
    @"
# -*- coding: utf-8 -*-
# 由 scripts/gate_protocol.ps1 生成（G4 RTU 超时契约桩）：收帧不回——
# 打开串口后只读不写，读到的字节全部丢弃、永不响应，主站必须超时。
# 复用 tests/fixtures/modbus/modbus_rtu_slave.py 的 kernel32 串口层（零第三方依赖）。
import argparse
import sys
import time

sys.path.insert(0, r"$fixtureDir")
from modbus_rtu_slave import Win32SerialPort  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="RTU no-respond 桩（收帧不回，超时契约用）")
    ap.add_argument("--port", default="COM4")
    ap.add_argument("--baud", type=int, default=9600)
    a = ap.parse_args()
    p = Win32SerialPort(a.port, a.baud)
    p.open()
    print("RTU-NORESPOND-READY port={}".format(a.port), flush=True)
    try:
        while True:
            p.read(512)          # 收帧不回：读到的帧全部丢弃，永不写串口
            time.sleep(0.002)
    except KeyboardInterrupt:
        pass
    finally:
        p.close()


if __name__ == "__main__":
    main()
"@ | Set-Content -Path $sinkPy -Encoding UTF8

    $probeCs = Join-Path $RtuSinkDir "RtuTimeoutProbe.cs"
    @"
// ============================================================================
//  RtuTimeoutProbe.cs —— G4 RTU 超时契约探针（由 scripts/gate_protocol.ps1 生成）
//  对 no-respond 从站（收帧不回）发 FC3 读：必须 TimeoutException，且消息可辨识
//  （含「Modbus RTU 等待响应超时」）。退出码 = 0(契约成立) / 1(契约被破坏)。
//  C# 5 兼容（.NET Framework 4 自带 csc 直接编译）。
// ============================================================================
using System;
using System.IO.Ports;
using Mcopilot.Protocols.Modbus;

internal static class RtuTimeoutProbe
{
    private static int Main(string[] args)
    {
        try { Console.OutputEncoding = System.Text.Encoding.UTF8; } catch { }
        string port = args.Length > 0 ? args[0] : "COM3";
        int timeoutMs = args.Length > 1 ? int.Parse(args[1]) : 1500;
        ModbusRtuClient client = new ModbusRtuClient(port, 9600, Parity.None, 8, StopBits.One, 1, timeoutMs);
        try
        {
            client.Open();
            Exception thrown = null;
            try { client.ReadHoldingRegisters(0, 1); }
            catch (Exception ex) { thrown = ex; }

            if (thrown == null)
            {
                Console.WriteLine("RESULT\tFAIL\tRtuTimeout_NoRespond\t从站收帧不回却未抛任何异常");
                return 1;
            }
            TimeoutException toe = thrown as TimeoutException;
            if (toe == null)
            {
                Console.WriteLine("RESULT\tFAIL\tRtuTimeout_NoRespond\t异常类型 " + thrown.GetType().Name + "，期望 TimeoutException：" + thrown.Message);
                return 1;
            }
            // 可辨识口径：TimeoutException 类型本身就是"超时≠协议错"的可操作判别；
            // 消息必属两个已知签名之一——客户端自有的「Modbus RTU 等待响应超时」（帧中
            // 停滞路径，ModbusRtuClient.ReadByteBefore deadline 到点）或 SerialPort 总
            // 静默超时的「操作已超时/timed out」（首字节即无响应时 SerialPort 先抛，
            // 模板 .cs 包装它在模板只读轮次不可改，见 README 诚实边界）。其余消息一律 FAIL。
            string msg = toe.Message ?? "";
            bool identifiable = msg.Contains("等待响应超时") || msg.Contains("操作已超时")
                || msg.IndexOf("timed out", StringComparison.OrdinalIgnoreCase) >= 0
                || msg.IndexOf("timeout", StringComparison.OrdinalIgnoreCase) >= 0;
            if (!identifiable)
            {
                Console.WriteLine("RESULT\tFAIL\tRtuTimeout_NoRespond\tTimeoutException 消息不可辨识（非已知超时签名）：" + msg);
                return 1;
            }
            Console.WriteLine("RESULT\tPASS\tRtuTimeout_NoRespond\tTimeoutException: " + msg);
            return 0;
        }
        finally
        {
            try { client.Close(); } catch { }
        }
    }
}
"@ | Set-Content -Path $probeCs -Encoding UTF8

    $exe = Join-Path $RtuSinkDir "RtuTimeoutProbe.exe"
    $src = @((Join-Path $TplDir "ModbusTcpClient.cs"),
             (Join-Path $TplDir "ModbusRtuClient.cs"),
             $probeCs)
    $argList = @("/nologo", "/codepage:65001", "/target:exe", "/platform:anycpu", "/out:$exe") + $src
    $r = Invoke-Proc -Exe $CscExe -ArgList $argList -BudgetSec 120
    if ($r.Exit -ne 0) { throw "G4 超时探针编译失败（csc 退出码 $($r.Exit)）：`n" + ($r.Output -join "`n") }
    return @{ SinkPy = $sinkPy; ProbeExe = $exe }
}

# ---------------------------------------------------------------- 十二道门
$gates = @()
function Add-Gate([string]$Id, [string]$Name, [int]$Domain, [scriptblock]$Body) {
    $script:gates += @{ Id = $Id; Name = $Name; Domain = $Domain; Body = $Body }
}

Add-Gate "G1" "编译_csc直编客户端与契约源" 10 {
    New-Item -ItemType Directory -Force -Path $G1Dir | Out-Null
    $exe = Join-Path $G1Dir "GateCompileCheck.exe"
    $src = @((Join-Path $TplDir "ModbusTcpClient.cs"),
             (Join-Path $TplDir "ModbusRtuClient.cs"),
             (Join-Path $TplDir "ModbusContractTests.cs"),
             (Join-Path $TplDir "ModbusContractRunner.cs"))
    $r = Invoke-Proc -Exe $CscExe -ArgList (@("/nologo", "/codepage:65001", "/target:exe", "/platform:anycpu", "/out:$exe") + $src)
    if ($r.TimedOut) { return @{ Exit = 1; Summary = "编译超时" } }
    if ($r.Exit -ne 0) {
        return @{ Exit = 1; Summary = ("csc 退出码 {0}：{1}" -f $r.Exit, (($r.Output | Where-Object { $_ }) | Select-Object -First 4) -join " | ") }
    }
    if (-not (Test-Path $exe)) { return @{ Exit = 1; Summary = "csc 退出码 0 但未产出 exe" } }
    return @{ Exit = 0; Summary = ("csc(C#5) 0 错误：客户端+契约 4 源 -> {0}" -f (Split-Path $exe -Leaf)) }
}

Add-Gate "G2" "黄金帧测试_run_frame_tests" 11 {
    $r = Invoke-Proc -Exe $PwshExe -ArgList @("-NoProfile", "-File", (Join-Path $TplDir "run_frame_tests.ps1"))
    $tail = ($r.Output | Where-Object { $_ -match "黄金测试|PASS|FAIL" } | Select-Object -Last 1)
    if ($r.Exit -ne 0) { return @{ Exit = 1; Summary = "退出码 $($r.Exit)：$tail" } }
    return @{ Exit = 0; Summary = "$tail" }
}

Add-Gate "G3" "TCP契约三阶段_plus_异常码扫掠" 12 {
    # ① 三阶段（run_contract.ps1 自带编排：normal/fragment/sticky，18 条）
    $r1 = Invoke-Proc -Exe $PwshExe -ArgList @("-NoProfile", "-File", (Join-Path $TplDir "run_contract.ps1"), "-PythonExe", $PythonExe)
    if ($r1.Exit -ne 0) {
        $tail = ($r1.Output | Where-Object { $_ } | Select-Object -Last 3) -join " | "
        return @{ Exit = 1; Summary = "三阶段退出码 $($r1.Exit)：$tail" }
    }
    # ② sweep 阶段（门禁自驱：15024 扫掠从站 + runner sweep，1 条）
    $sweepExe = New-G3SweepRunner
    $h = Start-GateSlave -ArgList @($SlavePy, "--port", "15024", "--exception-sweep") -Name "sweep15024" -WorkDir $G3Dir
    try {
        if (-not (Wait-PortReady 15024 15)) {
            $logs = @()
            foreach ($lf in @($h.OutLog, $h.ErrLog)) { $logs += (Get-Content $lf -ErrorAction SilentlyContinue | Select-Object -Last 2) }
            return @{ Exit = 1; Summary = "扫掠从站 15024 未就绪：$($logs -join ' | ')" }
        }
        $r2 = Invoke-Proc -Exe $sweepExe -ArgList @("sweep") -WorkDir $G3Dir
        $line = ($r2.Output | Where-Object { $_ -like "RESULT*" } | Select-Object -Last 1)
        if ($r2.Exit -ne 0) { return @{ Exit = 1; Summary = "sweep 退出码 $($r2.Exit)：$line" } }
        return @{ Exit = 0; Summary = "三阶段 18 条全过 + sweep 扫掠 1 条（$($line -replace "`t", " ")）" }
    } finally { Stop-GateSlave $h }
}

Add-Gate "G4" "RTU行为契约_plus_超时契约" 13 {
    # 前置探测：COM3/COM4 必须成对在场（com0com），缺失 → SKIP 不算败
    $present = [System.IO.Ports.SerialPort]::GetPortNames()
    if ($present -notcontains "COM3" -or $present -notcontains "COM4") {
        return @{ Exit = 0; Skip = $true; Summary = "SKIP：COM3/COM4 缺失（现有：$($present -join ', ')）；RTU 契约与超时契约未实跑" }
    }
    # ① 两阶段行为契约（normal/corrupt，11 条）
    $r1 = Invoke-Proc -Exe $PwshExe -ArgList @("-NoProfile", "-File", (Join-Path $TplDir "run_rtu_contract.ps1"), "-PythonExe", $PythonExe)
    if ($r1.Exit -ne 0) {
        $tail = ($r1.Output | Where-Object { $_ } | Select-Object -Last 3) -join " | "
        return @{ Exit = 1; Summary = "RTU 契约退出码 $($r1.Exit)：$tail" }
    }
    # ② 超时契约（no-respond 桩收帧不回 → 客户端 TimeoutException 可辨识，1 条）
    $art = New-G4Artifacts
    $h = Start-GateSlave -ArgList @($art.SinkPy, "--port", "COM4") -Name "norespond" -WorkDir $RtuSinkDir
    try {
        if (-not (Wait-LogMarker $h.OutLog "RTU-NORESPOND-READY" 15)) {
            $logs = (Get-Content $h.ErrLog -ErrorAction SilentlyContinue | Select-Object -Last 2) -join " | "
            return @{ Exit = 1; Summary = "no-respond 桩未就绪：$logs" }
        }
        Start-Sleep -Milliseconds 400    # 让串口句柄/缓冲稳定
        $r2 = Invoke-Proc -Exe $art.ProbeExe -ArgList @("COM3", "1500") -WorkDir $RtuSinkDir
        $line = ($r2.Output | Where-Object { $_ -like "RESULT*" } | Select-Object -Last 1)
        if ($r2.Exit -ne 0) { return @{ Exit = 1; Summary = "超时契约退出码 $($r2.Exit)：$line" } }
        return @{ Exit = 0; Summary = "RTU 契约 11 条全过 + 超时契约 1 条（$($line -replace "`t", " ")）" }
    } finally { Stop-GateSlave $h }
}

Add-Gate "G5" "quote反查_check_modbus_quotes" 14 {
    # 协议标准原件按本仓约定外置在仓外（mcopilot-external/vendor_docs/protocol_specs）。
    # 干净克隆 / 原件未就位时：既没有已提取文本也没有原件 ⟹ **基线不可核** ⟹ 整门 SKIP，
    # 与 G7（锚点）、G12（语料）同一口径（缺件不算败），但摘要里必须喊明
    # 「当前不可自动复核」——SKIP 不等于已核过。
    $specs = Join-Path (Split-Path -Parent $RepoRoot) "mcopilot-external\vendor_docs\protocol_specs"
    $extDir = Join-Path $RepoRoot "out\_protocols_extract"
    $hasText = (Test-Path $extDir) -and (@(Get-ChildItem $extDir -Filter "*.txt" -ErrorAction SilentlyContinue).Count -gt 0)
    if (-not $hasText -and -not (Test-Path $specs)) {
        return @{ Exit = 0; Skip = $true; Summary = "SKIP：协议标准原件按约定外置在 $specs，本机未就位且无已提取文本：当前不可自动复核（不是已核过）" }
    }
    $r = Invoke-Proc -Exe $PythonExe -ArgList @((Join-Path $RepoRoot "scripts\check_modbus_quotes.py"))
    $sum = ($r.Output | Where-Object { $_ -match "quote 反查：" } | Select-Object -First 1)
    if ($r.Exit -ne 0) { return @{ Exit = 1; Summary = "退出码 $($r.Exit)：$sum" } }
    if ($sum -notmatch "quote 反查：(\d+)/(\d+) 通过") { return @{ Exit = 1; Summary = "无法解析反查计数：$sum" } }
    if ($Matches[1] -ne $Matches[2]) { return @{ Exit = 1; Summary = "反查计数不相等：$sum" } }
    return @{ Exit = 0; Summary = $sum.Trim() }
}

Add-Gate "G6" "pytest协议域子集" 15 {
    $pytestExe = $PyTestExe
    if (-not (Test-Path $pytestExe)) { $pytestExe = $PythonExe }   # 回退（须已装 pytest）
    $files = @("tests\test_protocol_modbus.py", "tests\test_protocol_slmp.py",
               "tests\test_capability_matrix.py", "tests\test_coverage_ledger.py")
    $psiArgs = @("-m", "pytest") + $files + @("-q", "--no-header")
    $budget = [Math]::Max(30, $TimeoutSeconds - 15)
    $r = Invoke-Proc -Exe $pytestExe -ArgList $psiArgs -BudgetSec $budget
    $sum = ($r.Output | Where-Object { $_ -match "passed|failed|error" } | Select-Object -Last 1)
    if ($r.Exit -ne 0) { return @{ Exit = 1; Summary = "pytest 退出码 $($r.Exit)：$sum" } }
    return @{ Exit = 0; Summary = "pytest 4 文件子集：$sum" }
}

Add-Gate "G7" "外部真值锚点_gate_anchors" 16 {
    $r = Invoke-Proc -Exe $PythonExe -ArgList @((Join-Path $RepoRoot "scripts\gate_anchors.py"))
    $sum = ($r.Output | Where-Object { $_ -match "锚点门禁：" } | Select-Object -Last 1)
    $warns = @($r.Output | Where-Object { $_ -match "^(ANCHOR`tWARN)" }).Count
    if ($r.Exit -ne 0) { return @{ Exit = 1; Summary = "退出码 $($r.Exit)：$sum" } }
    return @{ Exit = 0; Summary = "$sum（WARN $warns 项，不计失败）" }
}

Add-Gate "G8" "文档一致性_实算对账" 17 {
    $r = Invoke-Proc -Exe $PwshExe -ArgList @("-NoProfile", "-File", (Join-Path $PSScriptRoot "gate_docsync.ps1"), "-RepoRoot", $RepoRoot)
    $sum = ($r.Output | Where-Object { $_ -match "实算真值|漂移" } | Select-Object -Last 2) -join " | "
    if ($r.Exit -ne 0) { return @{ Exit = 1; Summary = "退出码 $($r.Exit)：$sum" } }
    return @{ Exit = 0; Summary = $sum }
}

Add-Gate "G9" "SLMP契约_smoke_slmp" 18 {
    $r = Invoke-Proc -Exe $PythonExe -ArgList @((Join-Path $RepoRoot "scripts\smoke_slmp.py"))
    $sum = ($r.Output | Where-Object { $_ -match "RESULT|C\d" } | Select-Object -Last 1)
    if ($r.Exit -ne 0) { return @{ Exit = 1; Summary = "退出码 $($r.Exit)：$sum" } }
    return @{ Exit = 0; Summary = "C1-C9 全过：$sum" }
}

Add-Gate "G10" "接入闭环_onboard_loop三场景" 19 {
    # harness 接入闭环第一切片：模拟设备接入（2026-10-21）。验收 scripts/onboard_loop.py：
    #   A 全绿路径（矩阵查询→从站→契约→报告）；B 已知故障确定性归因（byteCount 245 注入
    #   副本 → 必须 SIG-P1-1 且复跑转绿，不许 UNKNOWN）；C 语料库外新缺陷必须 UNKNOWN
    #   升级零误归因。负向纪律同 gate_negative：副本注入+三重断言+阳性对照。
    $r = Invoke-Proc -Exe $PwshExe -ArgList @("-NoProfile", "-File", `
            (Join-Path $PSScriptRoot "gate_onboard.ps1"), "-PythonExe", $PythonExe)
    $sum = ($r.Output | Where-Object { $_ -match "^ONBOARD`t|三场景|退出码" } | Select-Object -Last 1)
    if ($r.Exit -ne 0) { return @{ Exit = 1; Summary = "退出码 $($r.Exit)：$sum" } }
    return @{ Exit = 0; Summary = "$sum" }
}

Add-Gate "G11" "故障注入农场_fault_farm全链闭环" 20 {
    # 故障注入农场 Phase 1（2026-10-21）：scripts/fault_farm.py 批产 10 场景带标签
    # comm_log/1（真值=注入参数构造即知）→ src/mcopilot/agents/forensics_comm.py
    # 7 规则检出 → scripts/eval_forensics.py 判卷（注入类 recall=100%、clean 误报=0）
    # → 混淆矩阵对角（检出类必须==注入类）；负向 N1：真值副本错标一条必须让判卷
    # 翻红（副本注入+三重断言+阳性对照，纪律同 gate_negative 五铁律）。
    $r = Invoke-Proc -Exe $PwshExe -ArgList @("-NoProfile", "-File", `
            (Join-Path $PSScriptRoot "gate_farm.ps1"), "-PythonExe", $PythonExe)
    $sum = ($r.Output | Where-Object { $_ -match "^FARM\t|总退出码" } | Select-Object -Last 1)
    if ($r.Exit -ne 0) { return @{ Exit = 1; Summary = "退出码 $($r.Exit)：$sum" } }
    return @{ Exit = 0; Summary = "$sum" }
}

Add-Gate "G12" "真实语料_lemay_modbus全链" 21 {
    # 真实分布首测（2026-10-21）：Lemay CSET16 真机测试床 Modbus 流量（标注 CSV+pcap
    # →comm_log/1→forensics_comm 检出→窗口判卷）。夹具（入库）逐行断言+负向三重
    # 断言+阳性对照必须全绿；全量六段判卷产出真实分布误报率（只报告不设阈值）。
    # 数据集不入库：out/_corpus_pcaps 缺失 → 整门 SKIP 不算败。
    $r = Invoke-Proc -Exe $PwshExe -ArgList @("-NoProfile", "-File", `
            (Join-Path $PSScriptRoot "gate_corpus.ps1"), "-PythonExe", $PythonExe)
    $skip = ($r.Output | Where-Object { $_ -match "^CORPUS-GATE\t.*SKIP|CORPUS-SUMMARY\tSKIP" } | Select-Object -Last 1)
    $sum = ($r.Output | Where-Object { $_ -match "^CORPUS-GATE\t|CORPUS-SUMMARY|总退出码" } | Select-Object -Last 1)
    if ($skip) { return @{ Exit = 0; Skip = $true; Summary = "SKIP：数据集未就绪（夹具门已全绿）；$sum" } }
    if ($r.Exit -ne 0) { return @{ Exit = 1; Summary = "退出码 $($r.Exit)：$sum" } }
    return @{ Exit = 0; Summary = "$sum" }
}

# ---------------------------------------------------------------- 编排执行
Add-Gate "G13" "接缝3_共享评测集账实相符" 22 {
    # 接缝 3 闭合：评测集（knowledge/shared_eval.json）与对照脚本（scripts/joint_eval.py）
    # 都已入库。本门禁两截：①静态核对两侧的 BEH 编号与评测集一致（任何环境都能跑）；
    # ②真跑两侧逐条对齐（要编译器 + 工厂兄弟仓）。
    # 缺环境 → 静态截照跑、动态截记 SKIP（当前不可自动复核），**不算失败也不算通过**。
    $env:PYTHONPATH = (Join-Path $RepoRoot "src")
    $r = Invoke-Proc -Exe $PythonExe -ArgList @("-X", "utf8", (Join-Path $PSScriptRoot "gate_joint_eval.py"))
    $res = ($r.Output | Where-Object { $_ -match "^GATE-RESULT:" } | Select-Object -Last 1)
    $sum = ($r.Output | Where-Object { $_ -match "GATE-RESULT:|FAIL：|SKIP：" } | Select-Object -Last 4) -join " | "
    if ($res -match "SKIP") { return @{ Exit = 0; Skip = $true; Summary = "SKIP：$sum" } }
    if ($r.Exit -ne 0) { return @{ Exit = 1; Summary = "退出码 $($r.Exit)：$sum" } }
    return @{ Exit = 0; Summary = "$sum" }
}

# ---------------------------------------------------------------- 编排执行
$selected = $gates
if ($Only) {
    $want = @($Only -split "," | ForEach-Object { $_.Trim().ToUpperInvariant() } | Where-Object { $_ })
    $selected = @($gates | Where-Object { $want -contains $_.Id })
    if ($selected.Count -eq 0) { Write-Output "[gate-fail] -Only 没有匹配的门：$Only"; exit 2 }
}

$gitHead = Get-GitHead
$gateResults = @()
$failed = 0; $skipped = 0
Write-Output "==================== 协议域总门禁（$($selected.Count) 门，单门超时 ${TimeoutSeconds}s）===================="
Write-Output ("git HEAD: {0}" -f $gitHead)
foreach ($g in $selected) {
    $t0 = Get-Date
    $script:gateDeadline = $t0.AddSeconds($TimeoutSeconds)   # 每门单超时（铁律1）
    $status = "FAIL"; $exit = 1; $summary = ""
    try {
        $r = & $g.Body
        $exit = [int]$r.Exit
        $summary = [string]$r.Summary
        if ($r.Skip) { $status = "SKIP"; $exit = 0 } elseif ($exit -eq 0) { $status = "PASS" } else { $status = "FAIL" }
    } catch {
        $status = "FAIL"; $exit = 1
        $summary = "门内异常：" + $_.Exception.Message
    }
    $dur = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
    if ($status -eq "FAIL") { $failed++ }
    if ($status -eq "SKIP") { $skipped++ }
    Write-Output ("RESULT`t{0}`t{1}_{2}`t{3}" -f $status, $g.Id, $g.Name, $summary)
    Write-Output ("  [{0}] 域 {1} 原始退出码 {2} 用时 {3}s" -f $status, $g.Domain, $exit, $dur)
    $gateResults += [pscustomobject]@{
        gate = $g.Id; name = $g.Name; domain = $g.Domain; status = $status
        exit_code = $exit; duration_s = $dur; summary = $summary
    }
}

$ts = (Get-Date).ToString("yyyyMMdd_HHmmss")
$reportPath = Join-Path $OutDir ("gate_report_{0}.json" -f $ts)
$report = [pscustomobject]@{
    generated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    git_head     = $gitHead
    ps_version   = $PSVersionTable.PSVersion.ToString()
    python_exe   = $PythonExe
    pytest_exe   = $PyTestExe
    timeout_seconds_per_gate = $TimeoutSeconds
    gates        = $gateResults
    total_pass   = ($gateResults | Where-Object { $_.status -eq "PASS" }).Count
    total_skip   = $skipped
    total_failed = $failed
    exit_code    = $failed
}
$json = $report | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($reportPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Output "==================== 门禁汇总 ===================="
foreach ($g in $gateResults) {
    Write-Output ("  {0} {1,-8} 域{2,3}  {3,7}s  {4}" -f $g.status.PadRight(4), $g.gate, $g.domain, $g.duration_s, $g.summary)
}
Write-Output ("通过 {0} / {1}（SKIP {2}，失败 {3}）；机器可读报告：{4}" -f `
    ($gateResults.Count - $failed - $skipped), $gateResults.Count, $skipped, $failed, $reportPath)
Write-Output ("总退出码 = 失败门数 = {0}" -f $failed)
exit $failed
