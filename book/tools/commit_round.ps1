param(
  # 提交目标仓：默认为**同级目录**下的独立书仓（书尚未并仓时的产物）；
  # 并仓之后书就在本仓里，传 -Repo 指到本仓即可。
  # 不写死绝对路径——公开仓里读者换台机器就跑不了，而本机路径也不是别人需要知道的事。
  [string]$Repo = ""
)
$ErrorActionPreference = "Stop"

if (-not $Repo) {
  $workspace = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
  $Repo = Join-Path $workspace "forensics-learning-book"
}
if (-not (Test-Path $Repo)) {
  Write-Error "目标仓不存在：$Repo（用 -Repo 指定；书已并仓时指向本仓根即可）"
  exit 2
}
Set-Location $Repo

$msg = @"
作者三项授权（2026-10-22）：C6 L1→L6 补写 / 旧章坐标机判化 / 书的前言与尾声

一、C6 L1→L6 补写（册一 ch06）
  增设 §6.6「现场操作步骤分级：L1→L6 与"L1 也不执行"」，原 §6.6/§6.7/§6.8 顺移为
  §6.7 实战案例 / §6.8 习题 / §6.9 简历句框 + 讲师切分；章首指针、简历句、讲师切分
  （8'+18'+16'+12'+12'+15'+5'+4' = 90'）、习题第 4 题、尾注坐标同步。

二、旧章坐标机判化（全书裸行号 70 → 0）
  起因：清点正则写作 "`:\\d+`"，匹配不到区间写法 "`:25-26`"，清点与修补脚本同时漏网。
  改正则后实点 70 处（卷一 ch02/ch04/ch06 52 + 册一 2 + 册二 6 + 书级尾声 4），
  逐处回锚点核对源文件原文后落笔。过程中当场修掉两处真实缺陷：
    · 卷一 ch06「诚实边界」原指 eval_forensics.py:38-40（实为 read_jsonl），
      正确落点 forensics_comm.py:38-40；
    · 册一 ch06 `scripts/dialects.py` 应为 `src/axiscope/dialects.py`。

三、书级前后记落盘
  前言.md（114 行）与 尾声.md（105 行）首次入证据层，并纳入坐标审计与结构体检。

四、锚点纪律（本轮最重要的一处）
  axiscope 在书中锚点 b95ffb2 之后有提交（KB0 +7/-3、新增 docs/wiki 7 篇）。
  审计器原读工作树 —— 同样判 [OK] 却指向另一行，"0 失败"成假话；
  改为按锚点 commit 读源文件（git show <rev>:<path>），并新增三个根目录
  （mcopilot-pending / self-improving / mcopilot-external）。
  规模数一律按锚点口径订正：KB 8 件 = 8141 物理行（原写 8142，系加总笔误）；
  docs md 锚点处实存 20 件 = 主体 19 + 收尾文档 1（原写"实存 27"是 HEAD 的数）。

五、核验（2026-10-22 本机实跑）
  坐标审计：697 引用 / 697 可解析 / 失败 0（覆盖 24 个文件：卷一 9 + 册一 9 + 册二 4 + 前言 + 尾声）
  结构体检：13 章 + 前言 + 尾声，0 问题
  裁剪核验：6 件逐字原样，0 不一致（新增 crop_vol1.py 重建卷一两件并纳入核验）
  正文物理行：卷一 2006 / 册一 1730 / 册二 735
"@
# 提交身份走**你自己的 git 配置**（git config user.name / user.email）。
# 不在脚本里写死身份：脚本是要进公开仓的，写死等于把个人邮箱贴出去。
git add -A
git commit -m $msg
"`n== 提交结果 =="
git log --oneline -1
git status --porcelain | Measure-Object | % { "剩余未提交: $($_.Count) 项" }
