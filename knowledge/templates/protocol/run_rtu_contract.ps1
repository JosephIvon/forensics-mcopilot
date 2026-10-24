# ============================================================================
#  run_rtu_contract.ps1 —— Modbus RTU 行为契约测试一键脚本（两阶段编排）
#
#  链路（零真机）：
#    ModbusRtuContractRunner.exe ── COM3 ══ com0com 虚拟对 ══ COM4 ── python 从站
#    （tests/fixtures/modbus/modbus_rtu_slave.py；虚拟对忽略波特率，9600 仅形式参数）
#
#  编排（2026-10-21，与 run_contract.ps1 三阶段模式同构，RTU 为两阶段）：
#    阶段1 normal : 起从站 @COM4（--holding 0=1234,1=5678）
#                   → ModbusRtuContractRunner.exe normal（10 条基础契约，
#                     含广播闭环与 turnaround delay 实测）
#    阶段2 corrupt: 起从站 @COM4 + --corrupt-next（首个响应故意坏 CRC）
#                   → ModbusRtuContractRunner.exe corrupt（1 条：坏 CRC 拒收
#                     → 下一事务恢复正常）
#    每阶段跑完立即杀本阶段从站，再进下一阶段；从站就绪判定 = stdout 的
#    "RTU-SLAVE-READY" 标记（RTU 无监听端口可探测，改用标记行）。
#
#  编译：.NET Framework csc（C#5）源码直编，与当前模板完全一致：
#    knowledge/templates/protocol/ModbusTcpClient.cs（PDU/常量/异常定义）
#    + knowledge/templates/protocol/ModbusRtuClient.cs（RTU 帧层与串口客户端）
#    + 本目录 ModbusRtuContractTests.cs（用例 + Main）
#    → 单文件 exe，零运行时依赖。
#
#  写入范围：仅 out/protocols/contracttests/**（exe/日志）。
#  兼容 PowerShell 5.1+ / pwsh 7+。退出码 = 总失败用例数。
# ============================================================================
[CmdletBinding()]
param(
    [string]$PythonExe = "python",   # 默认用 PATH 上的 python；可用 -PythonExe 覆盖
    [string]$ClientPort = "COM3",
    [string]$SlavePort = "COM4"
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$env:PYTHONIOENCODING = "utf-8"

$TestDir    = $PSScriptRoot
$RepoRoot   = (Resolve-Path (Join-Path $TestDir "..\..\..")).Path
$WorkDir    = $TestDir
$TemplateCsTcp = Join-Path $RepoRoot "knowledge\templates\protocol\ModbusTcpClient.cs"
$TemplateCsRtu = Join-Path $RepoRoot "knowledge\templates\protocol\ModbusRtuClient.cs"
$SlavePy    = Join-Path $RepoRoot "tests\fixtures\modbus\modbus_rtu_slave.py"
$RunnerExe  = Join-Path $WorkDir "ModbusRtuContractRunner.exe"
$ResultLog  = Join-Path $WorkDir "rtu_contract_results.log"

# ---- 两阶段从站实例定义（Phase = C# 侧 ModbusRtuContractTests.RunPhase 参数）------
# 从站串口固定 COM4（须与 ModbusRtuContractTests.SlavePortName 一致，主站固定连 COM3）
$instances = @(
    @{ Name = "normal";  Phase = "normal";  Label = "正常(COM4)";        Args = @("--port", $SlavePort, "--holding", "0=1234,1=5678") },
    @{ Name = "corrupt"; Phase = "corrupt"; Label = "坏CRC注入(COM4)";   Args = @("--port", $SlavePort, "--holding", "0=1234,1=5678", "--corrupt-next") }
)
$phaseOrder = @("normal", "corrupt")

# ---- 前置检查 ---------------------------------------------------------------
foreach ($f in @((Join-Path $TestDir "ModbusRtuContractTests.cs"),
                 $SlavePy, $TemplateCsTcp, $TemplateCsRtu)) {
    if (-not (Test-Path $f)) { throw "缺少必需文件：$f" }
}
# 解释器可以是命令名（走 PATH）或完整路径——先解析成可执行文件路径再判存在
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $cmd = Get-Command $PythonExe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { $PythonExe = $cmd.Source }
}

if (-not (Test-Path $PythonExe)) { throw "未找到 python：$PythonExe" }
if ($ClientPort -ne "COM3" -or $SlavePort -ne "COM4") {
    Write-Warning "-ClientPort/-SlavePort 与 ModbusRtuContractTests.ClientPortName(COM3)/SlavePortName(COM4) 不一致，C# 用例仍固定连 COM3/COM4"
}

# RTU 专属预检：虚拟串口对必须已存在（com0com 配对）
$present = [System.IO.Ports.SerialPort]::GetPortNames()
foreach ($p in @($ClientPort, $SlavePort)) {
    if ($present -notcontains $p) {
        Write-Output ("[fail] 串口 {0} 不存在（现有：{1}）。" -f $p, ($present -join ", "))
        Write-Output "       请先安装 com0com 并创建配对，例如（管理员）："
        Write-Output ('       "C:\Program Files (x86)\com0com\setupc.exe" --silent install PortName=COM3 PortName=COM4')
        exit 97
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

# ---- 1) 编译（Framework csc，C#5，源码直编）---------------------------------
$csc = @("$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
         "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe") |
       Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $csc) { throw "未找到 .NET Framework csc.exe（v4.0.30319）" }

$commonArgs = @("/nologo", "/codepage:65001", "/target:exe", "/platform:anycpu", "/out:$RunnerExe")
$sources    = @($TemplateCsTcp, $TemplateCsRtu, (Join-Path $TestDir "ModbusRtuContractTests.cs"))

$out = & $csc @commonArgs @sources 2>&1
if ($LASTEXITCODE -ne 0) {
    $out | ForEach-Object { Write-Output "  $_" }
    throw "编译失败（csc=$csc，退出码 $LASTEXITCODE）"
}
$compileRoute = "Framework csc(C#5) 源码直编: ModbusTcpClient.cs + ModbusRtuClient.cs + ModbusRtuContractTests.cs -> 单文件 exe"
Write-Output "[compile] $compileRoute"
Write-Output "[compile] csc = $csc"
Write-Output ""

# ---- 2) 从站实例管理（RTU 版：就绪判定 = stdout 标记行）------------------------
function Start-SlaveInstance([hashtable]$inst) {
    # 只 return 句柄哈希表，不向管道输出文本（同 run_contract.ps1 的约定）
    $outLog = Join-Path $WorkDir ("rtu_slave_{0}_stdout.log" -f $inst.Name)
    $errLog = Join-Path $WorkDir ("rtu_slave_{0}_stderr.log" -f $inst.Name)
    $slaveArgs = @("`"$SlavePy`"") + $inst.Args
    $proc = Start-Process -FilePath $PythonExe -ArgumentList $slaveArgs -NoNewWindow -PassThru `
                -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    return @{ Proc = $proc; OutLog = $outLog; ErrLog = $errLog; Inst = $inst }
}

function Wait-SlaveReady($handle) {
    # RTU 无端口可探测：等 stdout 的 RTU-SLAVE-READY 标记（modbus_rtu_slave.py 打开
    # 串口并配置好 DCB/超时后打印该行，见串口打开失败即进程退出的错误路径）
    $inst = $handle.Inst
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline) {
        if ($handle.Proc.HasExited) { break }
        $text = Get-Content $handle.OutLog -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
        if ($text -match "RTU-SLAVE-READY") { return }
        Start-Sleep -Milliseconds 150
    }
    Write-Output ("[slave] 就绪标记未出现，从站日志（{0}）：" -f $inst.Label)
    foreach ($lf in @($handle.OutLog, $handle.ErrLog)) {
        Get-Content $lf -Encoding UTF8 -ErrorAction SilentlyContinue | ForEach-Object { Write-Output "  $_" }
    }
    throw ("从站实例 {0} 未在 {1} 上就绪（进程退出码 {2}）" -f `
        $inst.Name, $SlavePort, $handle.Proc.ExitCode)
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

# 启动前：COM4 不得已被占用（残留从站会让用例连到状态未知的实例上）
# 探测方式：尝试以独占方式打开 COM4，打不开视为占用（com0com 口允许独占探测）
$probe = New-Object System.IO.Ports.SerialPort $SlavePort
try {
    try { $probe.Open(); $probe.Close() }
    catch {
        throw ("串口 {0} 当前无法独占打开（疑似残留从站进程占用）。请先释放串口再跑。" -f $SlavePort)
    }
} finally { $probe.Dispose() }

# ---- 3) 两阶段编排：各起各的实例，跑完即杀 -------------------------------------
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
                Write-Output ("[slave] {0}: python pid={1} 已拉起（{2}），等待 {3} 就绪标记..." -f `
                    $inst.Label, $h.Proc.Id, ($inst.Args -join " "), $SlavePort)
                $handles += $h
                $script:activeHandles += $h
            }
            foreach ($h in $handles) { Wait-SlaveReady $h }
            Write-Output "[slave] 本阶段实例就绪（RTU-SLAVE-READY）。"
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
            Start-Sleep -Milliseconds 300    # 让串口句柄完全释放，避免下一阶段打开失败
        }
    }
}
finally {
    # ---- 4) 无论成败都清掉所有仍在场的从站 ----------------------------------
    foreach ($h in $script:activeHandles) { Stop-SlaveInstance $h }
    $script:activeHandles = @()
}

# ---- 5) 汇总 RTU 契约矩阵 -------------------------------------------------------
if ($allResults.Count -eq 0) {
    Write-Output "[fail] 未解析到任何 RESULT 行（runner 可能未正常运行），分阶段日志见 $ResultLog.*"
    exit 99
}

$allResults | ForEach-Object { ("RESULT`tparam={0}`t{1}`t{2}`t{3}" -f $_.Phase, $_.Status, $_.Name, $_.Detail) } |
    Set-Content -Path $ResultLog -Encoding UTF8

Write-Output ""
Write-Output "==================== Modbus RTU 行为契约矩阵（com0com 虚拟对）===================="
Write-Output ("  {0,-16} {1,-52} {2,-6} {3}" -f "阶段", "用例", "结果", "说明")
Write-Output ("  " + ("-" * 96))
foreach ($r in $allResults) {
    Write-Output ("  {0,-16} {1,-52} {2,-6} {3}" -f $r.Phase, $r.Name, $r.Status, $r.Detail)
}
Write-Output ("  " + ("-" * 96))
$pass = @($allResults | Where-Object { $_.Status -eq "PASS" }).Count
$fail = @($allResults | Where-Object { $_.Status -eq "FAIL" }).Count
Write-Output ("  总计 {0} 条 | 通过 {1} | 失败 {2} | 各阶段 runner 退出码: {3}" -f `
    $allResults.Count, $pass, $fail, ($phaseSummaries -join "; "))
Write-Output ("  编译器链: {0}" -f $compileRoute)
Write-Output ("  链路: exe({0}) ══ com0com 虚拟对(忽略波特率) ══ {1}(python 从站)" -f $ClientPort, $SlavePort)
foreach ($inst in $instances) {
    Write-Output ("    - {0} {1}" -f $inst.Label, ($inst.Args -join " "))
}
Write-Output ("  结果日志: {0}（另有每阶段 {0}.<phase>.log）" -f $ResultLog)
Write-Output "=========================================================================="

exit $totalFailed
