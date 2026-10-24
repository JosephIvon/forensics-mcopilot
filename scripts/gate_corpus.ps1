# ============================================================================
#  gate_corpus.ps1 —— 真实语料门禁（G12，退出码域 21）：CSV+pcap→comm_log→检出→判卷
#
#  把「真实分布首测」落成可执行门禁（纪律同 gate_farm 五铁律的适用子集）：
#
#  步骤 ① 夹具门：python scripts/lemay_corpus.py --gate-fixtures
#         入库夹具（knowledge/protocols/pcap_samples/lemay_sample.{pcap,csv}
#         + lemay_sample_expected.json）映射复现 → 契约门（validate_comm_log
#         唯一裁判）阳性对照必须 0 违规 → 期望 JSON 逐行字段级断言 →
#         负向三重断言（unit_id 越域 300 / seq 回退 I1 / 2月30日 I6，副本注入
#         各一条非法记录）→ 契约门必须 FAIL；任一负向不红 = 门禁无牙齿 = FAIL。
#  步骤 ② 全量判卷：python scripts/lemay_corpus.py --gate-full
#         数据缺失 → SKIP（**整门 SKIP 不算败**——数据集不入库，out/_corpus_pcaps
#         未就绪是环境事实不是回归）；就绪则六段（自然 1 + 攻击 5）映射→契约门→
#         forensics_comm 检出（只读复用）→窗口口径判卷→报告落 out/corpus_lemay/
#         lemay_report.json。真实分布误报率**只报告不设阈值**（首测无基线）。
#
#  退出码：0 = 两步全过（或数据缺失整体 SKIP）；21 = 夹具门失败；
#         22 = 全量判卷失败；100 = 未捕获异常（trap 兜底）。
#         总退出码域 = 21（gate_protocol.ps1 G12）。SKIP 时退出码 0 + SKIP 行。
#  兼容 PowerShell 5.1+ / pwsh 7+。-ErrorAction Stop + trap，绝不"崩溃即过"。
# ============================================================================
[CmdletBinding()]
param(
    [string]$PythonExe = "python",   # 默认用 PATH 上的 python；可用 -PythonExe 覆盖
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$env:PYTHONIOENCODING = "utf-8"

trap {
    Write-Output ("[gate-corpus-trap] 未捕获异常：{0}（{1} 行 {2}）" -f $_.Exception.Message, `
        $_.InvocationInfo.ScriptName, $_.InvocationInfo.ScriptLineNumber)
    exit 100
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutDir) { $OutDir = Join-Path $RepoRoot "out\corpus_lemay" }
$CorpusPy   = Join-Path $RepoRoot "scripts\lemay_corpus.py"
$Validator  = Join-Path $RepoRoot "scripts\validate_comm_log.py"
$Detector   = Join-Path $RepoRoot "src\mcopilot\agents\forensics_comm.py"
$SampleDir  = Join-Path $RepoRoot "knowledge\protocols\pcap_samples"
$ReportJson = Join-Path $OutDir "lemay_report.json"

# 解释器可以是命令名（走 PATH）或完整路径——先解析成可执行文件路径再判存在
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $cmd = Get-Command $PythonExe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { $PythonExe = $cmd.Source }
}

foreach ($f in @($PythonExe, $CorpusPy, $Validator, $Detector)) {
    if (-not (Test-Path $f)) { Write-Output "[corpus-fail] 缺少必需文件：$f"; exit 21 }
}
foreach ($f in @("lemay_sample.pcap", "lemay_sample.csv", "lemay_sample_expected.json")) {
    if (-not (Test-Path (Join-Path $SampleDir $f))) {
        Write-Output "[corpus-fail] 缺少入库夹具：$SampleDir\$f（跑 --make-fixtures 生成并人工核对）"
        exit 21
    }
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
function Add-Row([string]$Step, [string]$Observed, [bool]$Pass, [int]$Code) {
    $script:rows.Add([pscustomobject]@{
        Step = $Step; Observed = $Observed
        PASS = $(if ($Pass) { "YES" } else { "NO" }); exit = $Code
    })
    $tag = "PASS"; if (-not $Pass) { $tag = "FAIL" }
    Write-Output ("CORPUS-GATE`t{0}`t[{1}] {2}" -f $Step, $tag, $Observed)
}

Write-Output "==================== 真实语料门禁（G12：夹具逐行断言+负向N → 全量检出判卷）===================="

# ---------------------------------------------------------------- ① 夹具门
$r1 = Invoke-Proc -Exe $PythonExe -ArgList @($CorpusPy, "--gate-fixtures") -BudgetSec 120
foreach ($l in ($r1.Output | Where-Object { $_ -match "^CORPUS\t" })) { Write-Output "  [fixture] $l" }
if ($r1.Exit -ne 0) {
    Add-Row "①夹具门_映射复现+逐行断言+负向三重断言" "退出码 $($r1.Exit)（阳性对照/逐行/负向 任一不达即红）" $false 21
    Write-Output "总退出码 21：夹具门失败（详见上方 [fixture] 行）"
    exit 21
}
$fxNegative = @($r1.Output | Where-Object { $_ -match "^CORPUS\tPASS\t负向N" }).Count
if ($fxNegative -lt 3) {
    Add-Row "①夹具门_负向三重断言" "负向 PASS 行 $fxNegative（必须恰 3：越域/I1/I6）" $false 21
    Write-Output "总退出码 21：负向三重断言不全"
    exit 21
}
Add-Row "①夹具门_映射复现+逐行断言+负向三重断言" "契约门 0 违规 + 期望 JSON 逐行一致 + 负向 3/3 红 + 阳性对照绿" $true 0

# ---------------------------------------------------------------- ② 全量判卷
$r2 = Invoke-Proc -Exe $PythonExe -ArgList @($CorpusPy, "--gate-full") -BudgetSec 240
foreach ($l in ($r2.Output | Where-Object { $_ -match "^CORPUS\t" })) { Write-Output "  [full] $l" }
$skipLine = ($r2.Output | Where-Object { $_ -match "^CORPUS\tSKIP" } | Select-Object -Last 1)
if ($skipLine) {
    Add-Row "②全量判卷" ("SKIP：数据缺失（" + ($skipLine -replace "CORPUS`tSKIP`t[^`t]*`t", "") + "）") $true 0
    Write-Output "CORPUS-SUMMARY`tSKIP`t数据集未就绪，夹具门已全绿；全量判卷未实跑（SKIP 不计失败）"
    Write-Output "总退出码 0（SKIP）"
    exit 0
}
if ($r2.Exit -ne 0) {
    Add-Row "②全量判卷_六段映射→检出→判卷" "退出码 $($r2.Exit)（任一段契约门/报告失败即红）" $false 22
    Write-Output "总退出码 22：全量判卷失败"
    exit 22
}
$segPass = @($r2.Output | Where-Object { $_ -match "^CORPUS\tPASS\t(attack_|natural_)" }).Count
if ($segPass -lt 6) {
    Add-Row "②全量判卷_六段齐全" "六段 PASS 行 $segPass（必须 6：自然 1 + 攻击 5）" $false 22
    Write-Output "总退出码 22：六段判定行不全"
    exit 22
}
if (-not (Test-Path $ReportJson)) {
    Add-Row "②全量判卷_报告产物" "报告缺失：$ReportJson" $false 22
    Write-Output "总退出码 22：报告文件未产出"
    exit 22
}
$fprLine = ($r2.Output | Where-Object { $_ -match "自然段误报率首测" } | Select-Object -Last 1)
Add-Row "②全量判卷_六段映射→检出→判卷→报告" ("六段全过 + 报告在场；" + ($fprLine -replace "^CORPUS\tPASS\t报告\t", "")) $true 0

# ---------------------------------------------------------------- 汇总
Write-Output "CORPUS-SUMMARY`tPASS`t夹具门全绿（含负向 3/3 + 阳性对照）+ 全量六段判定 + 报告在场（误报率只报告不设阈值）"
Write-Output "总退出码 0"
exit 0
