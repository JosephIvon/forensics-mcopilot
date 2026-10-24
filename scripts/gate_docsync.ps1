# ============================================================================
#  gate_docsync.ps1 —— 文档一致性门（G8 核心）：文档里的数字必须"从代码/知识库实算"
#
#  防什么：门禁自己抄自己。本脚本**不读文档里的数当真值**，而是反向计算——
#    黄金测试数 = ModbusFrameTests.cs 里 `new KeyValuePair<string, Action>` 的实际条数
#    TCP 契约数 = ModbusContractTests.cs 里 `defs.Add(new CaseDef(` 的实际条数
#    RTU 契约数 = ModbusRtuContractTests.cs 里 `new RtuCaseDef("唯一名")` 的去重条数
#    S7/Focas/SLMP 条数 = 三个 protocol json 里带 provenance 的条目实测数
#  然后要求 README.md 与 capability_matrix.md §5 / capability_matrix.json stats 的数字
#  **逐一等于实算值**；任何一处不符 → 退出码 1（G8 失败）。
#
#  参数化（负向测试 N3/N4 用）：-ReadmePath / -MatrixMdPath / -MatrixJsonPath /
#  -FrameTestsPath / -ContractTestsPath / -RtuContractTestsPath / -KnowledgeDir
#  全部可指向 out/gates/negative/ 下的副本——tracked 文件零改动。
#
#  退出码：0 = 全部一致；1 = 有数字漂移；2 = 结构性错误（文件缺失）。
#  兼容 PowerShell 5.1+ / pwsh 7+。-ErrorAction Stop + trap 兜底，异常路径退出码 ≠ 0。
# ============================================================================
[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$ReadmePath = "",
    [string]$MatrixMdPath = "",
    [string]$MatrixJsonPath = "",
    [string]$FrameTestsPath = "",
    [string]$ContractTestsPath = "",
    [string]$RtuContractTestsPath = "",
    [string]$KnowledgeDir = ""
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

trap {
    Write-Output ("[docsync-trap] 未捕获异常：{0}（{1}，行 {2}）" -f $_.Exception.Message, `
        $_.InvocationInfo.ScriptName, $_.InvocationInfo.ScriptLineNumber)
    exit 2
}

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
if (-not $KnowledgeDir)    { $KnowledgeDir    = Join-Path $RepoRoot "knowledge\protocols" }
if (-not $ReadmePath)      { $ReadmePath      = Join-Path $RepoRoot "knowledge\templates\protocol\README.md" }
if (-not $MatrixMdPath)    { $MatrixMdPath    = Join-Path $KnowledgeDir "capability_matrix.md" }
if (-not $MatrixJsonPath)  { $MatrixJsonPath  = Join-Path $KnowledgeDir "capability_matrix.json" }
if (-not $FrameTestsPath)   { $FrameTestsPath   = Join-Path $RepoRoot "knowledge\templates\protocol\ModbusFrameTests.cs" }
if (-not $ContractTestsPath){ $ContractTestsPath= Join-Path $RepoRoot "knowledge\templates\protocol\ModbusContractTests.cs" }
if (-not $RtuContractTestsPath){ $RtuContractTestsPath = Join-Path $RepoRoot "knowledge\templates\protocol\ModbusRtuContractTests.cs" }

foreach ($f in @($ReadmePath, $MatrixMdPath, $MatrixJsonPath, $FrameTestsPath,
                 $ContractTestsPath, $RtuContractTestsPath,
                 (Join-Path $KnowledgeDir "s7.json"), (Join-Path $KnowledgeDir "focas.json"),
                 (Join-Path $KnowledgeDir "slmp.json"))) {
    if (-not (Test-Path $f)) { Write-Output "[docsync-fail] 结构性缺失：$f"; exit 2 }
}

# ---------------------------------------------------------------- 实算真值
$frameText   = [System.IO.File]::ReadAllText($FrameTestsPath)
$contractText= [System.IO.File]::ReadAllText($ContractTestsPath)
$rtuText     = [System.IO.File]::ReadAllText($RtuContractTestsPath)

$golden   = [regex]::Matches($frameText, [regex]::Escape('new KeyValuePair<string, Action>')).Count
$contract = [regex]::Matches($contractText, [regex]::Escape('defs.Add(new CaseDef(')).Count
$rtuNames = [regex]::Matches($rtuText, 'new RtuCaseDef\("([^"]+)"') |
            ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique
$rtu = @($rtuNames).Count

# protocol json 实测：递归数「带 spec_ref 或 src_ref 取证字段」的条目对象
# （s7: spec_ref+src_ref=181；focas: 173；slmp: 11——与知识库条数口径一致；
#   顶层 judgment 注记等非条目对象不带取证字段，天然不计入）
function Count-ProvenanceEntries($node) {
    $n = 0
    if ($null -eq $node) { return 0 }
    if ($node -is [System.Collections.IDictionary]) {
        if ($node.ContainsKey("spec_ref") -or $node.ContainsKey("src_ref")) { $n++ }
        foreach ($v in $node.Values) { $n += Count-ProvenanceEntries $v }
    } elseif ($node -is [System.Collections.IEnumerable] -and $node -isnot [string]) {
        foreach ($v in $node) { $n += Count-ProvenanceEntries $v }
    }
    return $n
}

$s7Count    = Count-ProvenanceEntries ((Get-Content (Join-Path $KnowledgeDir "s7.json")    -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable))
$focasCount = Count-ProvenanceEntries ((Get-Content (Join-Path $KnowledgeDir "focas.json") -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable))
$slmpCount  = Count-ProvenanceEntries ((Get-Content (Join-Path $KnowledgeDir "slmp.json")  -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable))

# ---------------------------------------------------------------- 文档读入
$readme   = [System.IO.File]::ReadAllText($ReadmePath)
$matrixMd = [System.IO.File]::ReadAllText($MatrixMdPath)
$matrixJson = Get-Content $MatrixJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable

$failures = New-Object System.Collections.Generic.List[string]
function Add-Fail([string]$msg) { $script:failures.Add($msg) }

# —— README：所有「黄金测试（N 条」必须等于实算黄金数（命中 ≥1 处，否则视为清单缺失）
$m = [regex]::Matches($readme, '黄金测试（(\d+) 条')
if ($m.Count -lt 1) { Add-Fail "README 未找到「黄金测试（N 条」计数行" }
foreach ($x in $m) { if ([int]$x.Groups[1].Value -ne $golden) {
    Add-Fail ("README 黄金测试数 {0} != 实算 {1}（ModbusFrameTests.cs）" -f $x.Groups[1].Value, $golden) } }

$m = [regex]::Matches($readme, '(?<!RTU )行为契约测试（(\d+) 条')
if ($m.Count -lt 1) { Add-Fail "README 未找到「行为契约测试（N 条」计数行" }
foreach ($x in $m) { if ([int]$x.Groups[1].Value -ne $contract) {
    Add-Fail ("README TCP 契约数 {0} != 实算 {1}（ModbusContractTests.cs）" -f $x.Groups[1].Value, $contract) } }

$m = [regex]::Matches($readme, 'RTU 行为契约测试（(\d+) 条')
if ($m.Count -lt 1) { Add-Fail "README 未找到「RTU 行为契约测试（N 条」计数行" }
foreach ($x in $m) { if ([int]$x.Groups[1].Value -ne $rtu) {
    Add-Fail ("README RTU 契约数 {0} != 实算 {1}（ModbusRtuContractTests.cs 去重用例名）" -f $x.Groups[1].Value, $rtu) } }

if ($readme -notmatch 'RTU 超时契约') {
    Add-Fail "README 缺「RTU 超时契约」登记（门禁 G4 内置超时探针必须在文档挂账）"
}

# —— capability_matrix.md：N/N 分布与 §5 条数
$m = [regex]::Matches($matrixMd, '帧级黄金测试 (\d+)/(\d+)')
if ($m.Count -lt 1) { Add-Fail "矩阵 md 未找到「帧级黄金测试 N/N」" }
foreach ($x in $m) { if ([int]$x.Groups[1].Value -ne $golden -or [int]$x.Groups[2].Value -ne $golden) {
    Add-Fail ("矩阵 md 黄金 {0}/{1} != 实算 {2}/{2}" -f $x.Groups[1].Value, $x.Groups[2].Value, $golden) } }

$m = [regex]::Matches($matrixMd, 'ProtocolContractTests`? (\d+)/(\d+)')
if ($m.Count -lt 1) { Add-Fail "矩阵 md 未找到「ProtocolContractTests N/N」" }
foreach ($x in $m) { if ([int]$x.Groups[1].Value -ne $contract -or [int]$x.Groups[2].Value -ne $contract) {
    Add-Fail ("矩阵 md TCP 契约 {0}/{1} != 实算 {2}/{2}" -f $x.Groups[1].Value, $x.Groups[2].Value, $contract) } }

$m = [regex]::Matches($matrixMd, 'RTU 行为契约 (\d+)/(\d+)')
if ($m.Count -lt 1) { Add-Fail "矩阵 md 未找到「RTU 行为契约 N/N」" }
foreach ($x in $m) { if ([int]$x.Groups[1].Value -ne $rtu -or [int]$x.Groups[2].Value -ne $rtu) {
    Add-Fail ("矩阵 md RTU 契约 {0}/{1} != 实算 {2}/{2}" -f $x.Groups[1].Value, $x.Groups[2].Value, $rtu) } }

foreach ($pair in @(@("s7", $s7Count), @("focas", $focasCount), @("slmp", $slmpCount))) {
    $needle = "{0}.json {1} 条" -f $pair[0], $pair[1]
    if (-not $matrixMd.Contains($needle)) {
        Add-Fail ("矩阵 md §5 缺实测条数「{0}」（provenance 条目实算 = {1}）" -f $needle, $pair[1])
    }
}

# —— capability_matrix.json stats：知识库体量必须等于实测（json vs json 实测，不抄文档）
$vol = $null
if ($matrixJson -is [System.Collections.IDictionary] -and $matrixJson.ContainsKey("stats") -and
    $matrixJson["stats"] -is [System.Collections.IDictionary] -and
    $matrixJson["stats"].ContainsKey("knowledge_provenance_volume")) {
    $vol = $matrixJson["stats"]["knowledge_provenance_volume"]
}
if ($null -eq $vol) {
    Add-Fail "矩阵 json 缺 stats.knowledge_provenance_volume（结构漂移）"
} else {
    foreach ($pair in @(@("s7.json", $s7Count), @("focas.json", $focasCount), @("slmp.json", $slmpCount))) {
        if (-not ($vol -is [System.Collections.IDictionary] -and $vol.ContainsKey($pair[0]))) {
            Add-Fail ("矩阵 json stats 缺 {0} 条目" -f $pair[0]); continue
        }
        $entry = $vol[$pair[0]]
        $docN = if ($entry -is [System.Collections.IDictionary] -and $entry.ContainsKey("entries")) { $entry["entries"] } else { $null }
        if ($null -eq $docN -or [int]$docN -ne [int]$pair[1]) {
            Add-Fail ("矩阵 json stats {0}.entries = {1} != 实算 {2}" -f $pair[0], $docN, $pair[1])
        }
    }
}

# ---------------------------------------------------------------- 汇总
Write-Output ("[docsync] 实算真值：黄金={0}  TCP契约={1}  RTU契约={2}  s7={3}  focas={4}  slmp={5}" -f `
    $golden, $contract, $rtu, $s7Count, $focasCount, $slmpCount)
Write-Output ("[docsync] 对账对象：README={0}" -f $ReadmePath)
Write-Output ("[docsync]            矩阵md={0}" -f $MatrixMdPath)
Write-Output ("[docsync]            矩阵json={0}" -f $MatrixJsonPath)
if ($failures.Count -gt 0) {
    foreach ($f in $failures) { Write-Output ("[docsync-fail] {0}" -f $f) }
    Write-Output ("[docsync] 数字漂移 {0} 处 -> FAIL" -f $failures.Count)
    exit 1
}
Write-Output "[docsync] 全部数字与实算一致 -> PASS"
exit 0
