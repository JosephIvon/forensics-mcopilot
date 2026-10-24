# ============================================================================
#  run_frame_tests.ps1 —— Modbus 帧级黄金测试一键脚本（P2-2 可执行入口）
#
#  流程：Framework csc（C#5）源码直编
#        ModbusTcpClient.cs + ModbusRtuClient.cs + ModbusFrameTests.cs
#        + ~20 行 Main 驱动（本脚本内嵌生成 FrameTestDriver.cs，构建脚手架）
#        → 单文件 exe → 跑 ModbusFrameTests.RunAll() → 退出码 = 失败用例数（0 = 全绿）
#
#  与 run_contract.ps1 的区别：本脚本不联网、不起从站——黄金测试是「已知请求字节
#  序列 ↔ 预期字节序列」的纯帧级断言（CRC 参考实现经目录校验值 0x4B37 与规范示例
#  0x8776 两个独立公认锚点验证）。
#
#  写入范围：仅 out/_protocols_csharp/**。
#  兼容 PowerShell 5.1+ / pwsh 7+。
# ============================================================================
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$TestDir   = $PSScriptRoot
$RepoRoot  = (Resolve-Path (Join-Path $TestDir "..\..\..")).Path
$WorkDir   = Join-Path $RepoRoot "out\_protocols_csharp"
$DriverCs  = Join-Path $WorkDir "FrameTestDriver.cs"
$TestExe   = Join-Path $WorkDir "ModbusFrameTestsRunner.exe"
$ResultLog = Join-Path $WorkDir "frame_tests_result.log"

foreach ($f in @("ModbusTcpClient.cs", "ModbusRtuClient.cs", "ModbusFrameTests.cs")) {
    $p = Join-Path $TestDir $f
    if (-not (Test-Path $p)) { throw "缺少必需文件：$p" }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

# ---- 1) 生成 ~20 行 Main 驱动（构建脚手架，不属于交付物）----------------------
$driverSource = @'
// ============================================================================
//  FrameTestDriver.cs —— 帧级黄金测试运行入口（由 run_frame_tests.ps1 生成）
//  调用 ModbusFrameTests.RunAll()，退出码 = 失败用例数（0 = 全部通过）。
// ============================================================================
using System;
using Mcopilot.Protocols.Modbus;

internal static class FrameTestDriver
{
    private static int Main()
    {
        try { Console.OutputEncoding = System.Text.Encoding.UTF8; } catch { }
        ModbusTestReport report = ModbusFrameTests.RunAll();
        Console.WriteLine(report.Summary());
        return report.Failed;       // 退出码 = 失败数
    }
}
'@
Set-Content -Path $DriverCs -Value $driverSource -Encoding UTF8

# ---- 2) Framework csc 源码直编（C#5，零运行时依赖）---------------------------
$csc = @("$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
         "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe") |
       Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $csc) { throw "未找到 .NET Framework csc.exe（v4.0.30319）" }

$sources = @((Join-Path $TestDir "ModbusTcpClient.cs"),
             (Join-Path $TestDir "ModbusRtuClient.cs"),
             (Join-Path $TestDir "ModbusFrameTests.cs"),
             $DriverCs)
$out = & $csc "/nologo" "/codepage:65001" "/target:exe" "/platform:anycpu" "/out:$TestExe" @sources 2>&1
if ($LASTEXITCODE -ne 0) {
    $out | ForEach-Object { Write-Output "  $_" }
    throw "编译失败（csc=$csc，退出码 $LASTEXITCODE）"
}
Write-Output "[compile] Framework csc(C#5) 源码直编: ModbusTcpClient.cs + ModbusRtuClient.cs + ModbusFrameTests.cs + FrameTestDriver.cs -> 单文件 exe"
Write-Output "[compile] csc = $csc"
Write-Output ""

# ---- 3) 跑黄金测试（退出码 = 失败用例数）--------------------------------------
Write-Output "[run] $TestExe"
Write-Output "------------------------------------------------------------"
$runOutput = & $TestExe 2>&1
$exitCode = $LASTEXITCODE
$runOutput | Tee-Object -FilePath $ResultLog | ForEach-Object { Write-Output $_ }
Write-Output "------------------------------------------------------------"

if ($exitCode -eq 0) {
    Write-Output "[PASS] 帧级黄金测试全绿（退出码 0）"
} else {
    Write-Output "[FAIL] 帧级黄金测试存在失败（退出码 = 失败数 $exitCode）"
}
exit $exitCode
