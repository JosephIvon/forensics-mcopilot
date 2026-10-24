# ============================================================================
#  run_contract.ps1 —— Modbus TCP 行为契约测试一键脚本（三阶段编排）
#
#  编排（2026-10-21 扩展为三阶段，各从站实例独立端口）：
#    阶段1 normal   : 起正常从站 @15020（--holding 0=1234,1=5678）
#                     → ModbusContractRunner.exe normal（15 条基础契约）
#    阶段2 fragment : 起 --fragment split3 @15021（响应拆 3 段发送）
#                     + --fragment byte1 @15022（逐字节滴流）
#                     → ModbusContractRunner.exe fragment（2 条分片重组契约）
#    阶段3 sticky   : 起 --sticky-stale 1 @15023（每响应附发旧 TID 陈旧帧，粘包占管道）
#                     → ModbusContractRunner.exe sticky（1 条：粘包→毒化→重连复活，
#                       P1-3 端到端验证）
#    每阶段跑完立即杀本阶段实例，再进下一阶段；结果矩阵含阶段列。
#
#  流程：编译（.NET Framework csc，C#5；把 knowledge/templates/protocol/ModbusTcpClient.cs
#        与本目录两个源文件一起编译成单文件 exe）
#        → 分阶段起 python 从站模拟器（劣化注入参数见上）→ 跑 runner → 收集 RESULT 行
#        → finally 杀掉所有实例 → 末尾打印三阶段契约矩阵 → 退出码 = 总失败数。
#
#  为什么不 /r: 引用 out/_protocols_csharp/ModbusClients.dll：
#    该 DLL 是旧版模板的产物，缺少后来加入的低层事务方法 TransactRaw()
#    （本契约套件发数量 0 / 越界 / 不支持 FC 的原始帧正需要它），
#    引用它会报 CS1061。源码直编保证与当前模板完全一致。
#
#  写入范围：仅 out/protocols/contracttests/**（exe/日志；2026-10-21 起从旧目录
#  out/_protocols_contract/** 迁入，与文件头历史声明对齐）。
#  兼容 PowerShell 5.1+ / pwsh 7+。
# ============================================================================
[CmdletBinding()]
param(
    [string]$PythonExe = "python",   # 默认用 PATH 上的 python；可用 -PythonExe 覆盖
    [int]$Port = 15020
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$TestDir    = $PSScriptRoot
$RepoRoot   = (Resolve-Path (Join-Path $TestDir "..\..\..")).Path
$WorkDir    = Join-Path $RepoRoot "out\protocols\contracttests"
$TemplateCs = Join-Path $RepoRoot "knowledge\templates\protocol\ModbusTcpClient.cs"
$SlavePy    = Join-Path $RepoRoot "tests\fixtures\modbus\modbus_tcp_slave.py"
$RunnerExe  = Join-Path $WorkDir "ModbusContractRunner.exe"
$ResultLog  = Join-Path $WorkDir "contract_results.log"

# ---- 三阶段从站实例定义（Phase = C# 侧 ModbusContractTests.RunPhase 参数）------
# normal 阶段端口 = $Port（须与 ModbusContractTests.SlavePort=15020 一致，否则 C# 连不上）
$instances = @(
    @{ Name = "normal";       Port = $Port;  Phase = "normal";   Label = "正常(15020)";      Args = @("--holding", "0=1234,1=5678") },
    @{ Name = "split3";       Port = 15021;  Phase = "fragment"; Label = "分片split3(15021)"; Args = @("--holding", "0=1234,1=5678", "--fragment", "split3") },
    @{ Name = "byte1";        Port = 15022;  Phase = "fragment"; Label = "分片byte1(15022)";  Args = @("--holding", "0=1234,1=5678", "--fragment", "byte1") },
    @{ Name = "sticky-stale"; Port = 15023;  Phase = "sticky";   Label = "粘包stale(15023)";  Args = @("--holding", "0=1234,1=5678", "--sticky-stale", "1") }
)
$phaseOrder = @("normal", "fragment", "sticky")

# ---- 前置检查 ---------------------------------------------------------------
foreach ($f in @((Join-Path $TestDir "ModbusContractTests.cs"),
                 (Join-Path $TestDir "ModbusContractRunner.cs"),
                 $SlavePy, $TemplateCs)) {
    if (-not (Test-Path $f)) { throw "缺少必需文件：$f" }
}
# 解释器可以是命令名（走 PATH）或完整路径——先解析成可执行文件路径再判存在
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $cmd = Get-Command $PythonExe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { $PythonExe = $cmd.Source }
}

if (-not (Test-Path $PythonExe)) { throw "未找到 python：$PythonExe" }
if ($Port -ne 15020) {
    Write-Warning "-Port=$Port 与 ModbusContractTests.SlavePort(15020) 不一致，normal 阶段 C# 用例仍连 15020"
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

# ---- 1) 编译（Framework csc，C#5）------------------------------------------
$csc = @("$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
         "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe") |
       Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $csc) { throw "未找到 .NET Framework csc.exe（v4.0.30319）" }

$commonArgs = @("/nologo", "/codepage:65001", "/target:exe", "/platform:anycpu", "/out:$RunnerExe")
$sources    = @($TemplateCs,
                (Join-Path $TestDir "ModbusContractTests.cs"),
                (Join-Path $TestDir "ModbusContractRunner.cs"))

# 单路线：模板源码 + 契约测试源码 → 单文件 exe（零运行时依赖）。
# 注意 /r: 参数不要带内嵌引号：pwsh 7.3+ 的原生参数传递会把 `\"` 转义，
# 老 csc 解析不了，会误报 CS0006“元数据文件未找到”（本路径无空格，无需引号）。
$out = & $csc @commonArgs @sources 2>&1
if ($LASTEXITCODE -ne 0) {
    $out | ForEach-Object { Write-Output "  $_" }
    throw "编译失败（csc=$csc，退出码 $LASTEXITCODE）"
}
$compileRoute = "Framework csc(C#5) 源码直编: ModbusTcpClient.cs + ModbusContractTests.cs + ModbusContractRunner.cs -> 单文件 exe"
Write-Output "[compile] $compileRoute"
Write-Output "[compile] csc = $csc"
Write-Output ""

# ---- 2) 从站实例管理 --------------------------------------------------------
function Test-PortOpen([string]$h, [int]$p, [int]$timeoutMs) {
    $c = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $c.BeginConnect($h, $p, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne($timeoutMs, $false) -and $c.Connected) { return $true }
        return $false
    } catch {
        return $false
    } finally {
        try { $c.Close() } catch { }
    }
}

function Start-SlaveInstance([hashtable]$inst) {
    # 注意：本函数只 return 句柄哈希表，不向管道输出任何文本——
    # 否则调用方 $h 会拿到「文本 + 哈希表」的数组，破坏句柄取值。
    $outLog = Join-Path $WorkDir ("slave_{0}_stdout.log" -f $inst.Name)
    $errLog = Join-Path $WorkDir ("slave_{0}_stderr.log" -f $inst.Name)
    $slaveArgs = @("`"$SlavePy`"", "--port", "$($inst.Port)") + $inst.Args
    $proc = Start-Process -FilePath $PythonExe -ArgumentList $slaveArgs -NoNewWindow -PassThru `
                -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    return @{ Proc = $proc; OutLog = $outLog; ErrLog = $errLog; Inst = $inst }
}

function Wait-SlaveReady($handle) {
    $inst = $handle.Inst
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline) {
        if ($handle.Proc.HasExited) { break }
        if (Test-PortOpen "127.0.0.1" $inst.Port 300) { return }
        Start-Sleep -Milliseconds 150
    }
    Write-Output ("[slave] 端口未就绪，从站日志（{0}）：" -f $inst.Label)
    foreach ($lf in @($handle.OutLog, $handle.ErrLog)) {
        Get-Content $lf -ErrorAction SilentlyContinue | ForEach-Object { Write-Output "  $_" }
    }
    throw ("从站实例 {0} 未能监听 127.0.0.1:{1}（进程退出码 {2}）" -f `
        $inst.Name, $inst.Port, $handle.Proc.ExitCode)
}

function Stop-SlaveInstance($handle) {
    if ($null -eq $handle) { return }
    try {
        if (-not $handle.Proc.HasExited) {
            Stop-Process -Id $handle.Proc.Id -Force -ErrorAction SilentlyContinue
            $handle.Proc.WaitForExit(3000) | Out-Null
        }
        Write-Output ("[slave] {0} 从站进程已停止 (pid={1})" -f $handle.Inst.Label, $handle.Proc.Id)
    } catch {
        Write-Output ("[slave] 清理从站进程（{0}）时出现非致命错误：{1}" -f `
            $handle.Inst.Label, $_.Exception.Message)
    }
}

# 启动前：四个端口必须全部空闲（防残留从站让用例连到状态未知的实例上）
foreach ($inst in $instances) {
    if (Test-PortOpen "127.0.0.1" $inst.Port 300) {
        throw ("端口 {0} 已被占用（实例 {1}，可能有残留从站进程，种子/劣化状态未知）。请先释放端口再跑。" -f `
            $inst.Port, $inst.Name)
    }
}

# ---- 3) 三阶段编排：各起各的实例，跑完即杀 -------------------------------------
$script:activeHandles = @()
$allResults = @()
$phaseSummaries = @()
$totalFailed = 0
try {
    foreach ($phase in $phaseOrder) {
        $phaseInstances = @($instances | Where-Object { $_.Phase -eq $phase })
        Write-Output ""
        Write-Output ("==================== 阶段 [{0}] ====================" -f $phase)
        $handles = @()
        try {
            foreach ($inst in $phaseInstances) {
                $h = Start-SlaveInstance $inst
                Write-Output ("[slave] {0}: python pid={1} 已拉起（{2}），等待 127.0.0.1:{3} 就绪..." -f `
                    $inst.Label, $h.Proc.Id, ($inst.Args -join " "), $inst.Port)
                $handles += $h
                $script:activeHandles += $h
            }
            foreach ($h in $handles) { Wait-SlaveReady $h }
            Write-Output "[slave] 本阶段实例就绪。"
            Write-Output ""
            Write-Output "[run] $RunnerExe $phase"
            Write-Output "------------------------------------------------------------"
            $runOutput = & $RunnerExe $phase 2>&1
            $phaseExit = $LASTEXITCODE
            $runOutput | Tee-Object -FilePath ("{0}.{1}.log" -f $ResultLog, $phase) | ForEach-Object { Write-Output $_ }
            Write-Output "------------------------------------------------------------"

            $phaseTag = ($phaseInstances | ForEach-Object { $_.Label }) -join "+"
            foreach ($line in $runOutput) {
                $parts = ([string]$line) -split "`t"
                if ($parts.Length -ge 4 -and $parts[0] -eq "RESULT") {
                    $allResults += [pscustomobject]@{
                        Phase = $phaseTag; Status = $parts[1]; Name = $parts[2]; Detail = $parts[3]
                    }
                }
            }
            $totalFailed += $phaseExit
            $phaseSummaries += ("阶段 {0}: 退出码 {1}" -f $phase, $phaseExit)
        }
        finally {
            foreach ($h in $handles) { Stop-SlaveInstance $h }
            foreach ($h in $handles) { $script:activeHandles = @($script:activeHandles | Where-Object { $_ -ne $h }) }
        }
    }
}
finally {
    # ---- 4) 无论成败都清掉所有仍在场的从站 ----------------------------------
    foreach ($h in $script:activeHandles) { Stop-SlaveInstance $h }
    $script:activeHandles = @()
}

# ---- 5) 汇总三阶段契约矩阵 -----------------------------------------------------
if ($allResults.Count -eq 0) {
    Write-Output "[fail] 未解析到任何 RESULT 行（runner 可能未正常运行），分阶段日志见 $ResultLog.*"
    exit 99
}

# 汇总日志（含阶段标记）
$allResults | ForEach-Object { ("RESULT`tparam={0}`t{1}`t{2}`t{3}" -f $_.Phase, $_.Status, $_.Name, $_.Detail) } |
    Set-Content -Path $ResultLog -Encoding UTF8

Write-Output ""
Write-Output "==================== Modbus TCP 行为契约矩阵（三阶段）===================="
Write-Output ("  {0,-18} {1,-50} {2,-6} {3}" -f "阶段", "用例", "结果", "说明")
Write-Output ("  " + ("-" * 96))
foreach ($r in $allResults) {
    Write-Output ("  {0,-18} {1,-50} {2,-6} {3}" -f $r.Phase, $r.Name, $r.Status, $r.Detail)
}
Write-Output ("  " + ("-" * 96))
$pass = @($allResults | Where-Object { $_.Status -eq "PASS" }).Count
$fail = @($allResults | Where-Object { $_.Status -eq "FAIL" }).Count
Write-Output ("  总计 {0} 条 | 通过 {1} | 失败 {2} | 各阶段 runner 退出码: {3}" -f `
    $allResults.Count, $pass, $fail, ($phaseSummaries -join "; "))
Write-Output ("  编译器链: {0}" -f $compileRoute)
Write-Output ("  从站: python tests/fixtures/modbus/modbus_tcp_slave.py")
foreach ($inst in $instances) {
    Write-Output ("    - {0} @ 127.0.0.1:{1} {2}" -f $inst.Label, $inst.Port, ($inst.Args -join " "))
}
Write-Output ("  结果日志: {0}（另有每阶段 {0}.<phase>.log）" -f $ResultLog)
Write-Output "=========================================================================="

exit $totalFailed
