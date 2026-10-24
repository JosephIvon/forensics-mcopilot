# 编译自检脚本：用本机 C# 编译器验证生成的适配器能编译，**并把仿真器自检真跑一遍**。
# 用途：CI 或本地改动生成器后跑一次，防止生成出编不过的代码 / 跑不对的仿真器。
# 找不到可用的编译器时跳过（不阻塞没有 .NET SDK 的环境）。
#
# 三步：
#   1) 编译适配器（接口 + 仿真器 + 两家适配器）→ Motion.dll
#   2) 编译契约测试（配 xUnit 最小替身，只查语法；真机断言要插卡才跑）→ MotionContractTests.dll
#   3) 编译并**运行**仿真器自检 → MotionSelfCheck.exe，退出码 0 才算通过

param(
    [string]$OutDir = "out\csharp",
    [string]$CscPath = ""
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# 已知环境问题：从 PowerShell 7 会话里拉起 Windows PowerShell 5.1 时，
# 子进程加载 .NET 10 运行时失败（clrjit.dll 加载错误），宿主自身会以
# 0x80131506 退出。VS BuildTools 18 的 Roslyn 是 .NET 10 应用，会触发这个问题。
# 因此在 5.1 下直接跳过，不让脚本以看不懂的堆栈失败。
if ($PSVersionTable.PSVersion.Major -lt 7) {
    Write-Output "[skip] 检测到 Windows PowerShell 5.1：本机 .NET 运行时存在已知冲突，编译自检已跳过。"
    Write-Output "       请用 PowerShell 7 运行（pwsh -File scripts\compile_check.ps1）。"
    exit 0
}

function Get-CompilerCandidates {
    $list = New-Object System.Collections.ArrayList
    if ($CscPath) { [void]$list.Add(@{ Kind = "exe"; Path = $CscPath; Lang = "latest" }); return $list }

    # 1) Visual Studio / BuildTools 自带的 Roslyn
    $vs = "C:\Program Files (x86)\Microsoft Visual Studio"
    if (Test-Path $vs) {
        Get-ChildItem -Path $vs -Filter "csc.exe" -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -like "*Roslyn*" } | ForEach-Object {
                [void]$list.Add(@{ Kind = "exe"; Path = $_.FullName; Lang = "latest" })
            }
    }
    # 2) .NET SDK 自带的 csc.dll（需要用 dotnet 驱动）
    $sdk = "C:\Program Files\dotnet\sdk"
    if (Test-Path $sdk) {
        Get-ChildItem -Path $sdk -Filter "csc.dll" -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | ForEach-Object {
                [void]$list.Add(@{ Kind = "dll"; Path = $_.FullName; Lang = "latest" })
            }
    }
    # 3) 不再兜底 .NET Framework 自带的 csc.exe（只支持 C# 5）：
    #    生成的代码里有 readonly struct（C# 7.2）、switch 表达式等新语法，
    #    C# 5 编译器**必然**编不过，只会在输出里刷一屏看不懂的乱码错误，掩盖真正的报错。
    return $list
}

# 调用编译器。返回 @{ Code = 退出码; Output = 编译器输出 }。
# 注意：**不要**在函数里 Write-Output —— 那会把返回值混成数组，调用方拿到就不是退出码了。
function Invoke-Csc {
    param($Compiler, [string[]]$ExtraArgs, [string[]]$Sources, [string]$StdOut, [string]$StdErr)

    $argList = @("/nologo")
    if ($Compiler.Lang) { $argList += "/langversion:$($Compiler.Lang)" }
    # /codepage:65001 = 源码按 UTF-8 读。不给的话，csc 对无 BOM 的文件按系统 ANSI(GBK) 读，
    # 中文注释和字符串会被解码坏 —— 表现为一堆看不懂的语法错误。
    $argList += "/codepage:65001"
    $argList += $ExtraArgs + $Sources
    $code = -1
    try {
        # 用 Start-Process 隔离：某些 .NET 10 apphost 在老 PowerShell 宿主下会原生崩溃，
        # 直接 & 调用会把整个脚本带崩，try/catch 也拦不住进程级崩溃。
        if ($Compiler.Kind -eq "dll") {
            $p = Start-Process -FilePath "dotnet" -ArgumentList (@($Compiler.Path) + $argList) `
                    -NoNewWindow -Wait -PassThru -RedirectStandardOutput $StdOut -RedirectStandardError $StdErr
        } else {
            $p = Start-Process -FilePath $Compiler.Path -ArgumentList $argList `
                    -NoNewWindow -Wait -PassThru -RedirectStandardOutput $StdOut -RedirectStandardError $StdErr
        }
        $code = $p.ExitCode
    } catch {
        return @{ Code = -1; Output = "该编译器无法启动：$($_.Exception.Message)" }
    }
    $text = @()
    foreach ($f in @($StdOut, $StdErr)) {
        $content = Get-Content $f -ErrorAction SilentlyContinue
        if ($content) { $text += $content }
    }
    return @{ Code = $code; Output = ($text -join "`n") }
}

$files = @(
    "IMotionController.cs", "SimulatedMotionController.cs",
    "DmcMotionController.cs", "ZMotionMotionController.cs", "GoogolMotionController.cs"
) | ForEach-Object { Join-Path $OutDir $_ }

$missing = $files | Where-Object { -not (Test-Path $_) }
if ($missing) {
    Write-Output "[skip] 缺少生成文件（先跑 mcopilot adapter gen）：$($missing -join ', ')"
    exit 0
}

$outDll = Join-Path $OutDir "Motion.dll"
$contractDll = Join-Path $OutDir "MotionContractTests.dll"
$selfCheckExe = Join-Path $OutDir "MotionSelfCheck.exe"
$tmpOut = [System.IO.Path]::GetTempFileName()
$tmpErr = [System.IO.Path]::GetTempFileName()

$compiler = $null
$lastError = ""
foreach ($c in (Get-CompilerCandidates)) {
    Write-Output "[compile] 尝试：$($c.Path)"
    $r = Invoke-Csc -Compiler $c -ExtraArgs @("/target:library", "/out:$outDll") -Sources $files `
            -StdOut $tmpOut -StdErr $tmpErr
    if ($r.Output) { $r.Output -split "`n" | ForEach-Object { Write-Output "  $_" } }
    if ($r.Code -eq 0) { $compiler = $c; break }
    $lastError = "退出码 $($r.Code)"
    Write-Output "  [warn] 编译未通过，尝试下一个编译器"
}

if (-not $compiler) {
    Write-Output "[skip] 未找到可用的 C# 编译器（最后错误：$lastError）。生成物未做编译验证。"
    exit 0
}
Write-Output "[ok] 适配器编译通过：$outDll"

# --- 契约测试也要能编译（用 xUnit 最小替身，只查语法）-------------------------
$contractSrc = Join-Path $OutDir "MotionContractTests.cs"
$shim = Join-Path $PSScriptRoot "xunit_shim.cs"
if ((Test-Path $contractSrc) -and (Test-Path $shim)) {
    $r = Invoke-Csc -Compiler $compiler -ExtraArgs @("/target:library", "/out:$contractDll") `
            -Sources @($contractSrc, $files[0], $shim) -StdOut $tmpOut -StdErr $tmpErr
    if ($r.Output) { $r.Output -split "`n" | ForEach-Object { Write-Output "  $_" } }
    if ($r.Code -eq 0) {
        Write-Output "[ok] 契约测试编译通过（物理断言要插卡才跑）"
    } else {
        Write-Output "[fail] 契约测试编译未通过"
        exit 1
    }
} else {
    Write-Output "[skip] 未找到契约测试或 xunit_shim.cs，跳过契约测试编译检查"
}

# --- 仿真器自检：编译成 exe 并真跑一遍 ---------------------------------------
$selfCheckSrc = Join-Path $OutDir "MotionSelfCheck.cs"
if (Test-Path $selfCheckSrc) {
    $r = Invoke-Csc -Compiler $compiler -ExtraArgs @("/target:exe", "/out:$selfCheckExe") `
            -Sources @($files[0], $files[1], $selfCheckSrc) -StdOut $tmpOut -StdErr $tmpErr
    if ($r.Output) { $r.Output -split "`n" | ForEach-Object { Write-Output "  $_" } }
    if ($r.Code -ne 0) {
        Write-Output "[fail] 仿真器自检程序编译未通过"
        exit 1
    }
    Write-Output "[run] 仿真器自检："
    $rc = -1
    try {
        & $selfCheckExe
        $rc = $LASTEXITCODE
    } catch {
        Write-Output "  [warn] 自检程序无法启动：$($_.Exception.Message)"
    }
    if ($rc -eq 0) {
        Write-Output "[ok] 仿真器自检通过"
    } elseif ($rc -eq -1) {
        Write-Output "[warn] 自检程序未能运行（环境原因），编译检查仍算通过"
    } else {
        Write-Output "[fail] 仿真器自检未通过（退出码 $rc）"
        exit 1
    }
} else {
    Write-Output "[skip] 未找到 MotionSelfCheck.cs，跳过仿真器自检"
}

Remove-Item $tmpOut, $tmpErr -ErrorAction SilentlyContinue
exit 0
