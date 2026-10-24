#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""finalize_publish_book.py —— 批 D 收官：发布事实入册（2026-10-23 中午）。

事实（全部经 GitHub API 独立复核 ✓，不只信推送脚本自己的回显 ✓）：
  JosephIvon/mcopilot                 public  main  85e45d4
  JosephIvon/axiscope                 public  main  0bf4ad4
  JosephIvon/forensics-code-factory   public  main  e651f3b
  JosephIvon/forensics-learning-index public  main  6a8e9d2
  四仓本地 HEAD 与远端 refs/heads/main **逐个一致** ✓
  中文名路径真实在位 ✓（mcopilot 30 条 / axiscope 49 条 / 工厂 1 条 ✓）
  索引仓 README 的 `<账号>` 占位符已替换为真链接 ✓

从 GitHub **干净克隆**复验 ✓（读者实际拿到的东西 ✓）：
  mcopilot                376 passed / 11 skipped ✓；门禁 10/12（SKIP 2，失败 0）✓
  axiscope                294 passed / 110 skipped ✓；脱敏自检退出码 0 ✓
  forensics-code-factory  全品牌再生退出码 0 ✓；单文件与 gen/ 同源 ✓
"""
import io
import os
import sys

BOOK = r"%WORKSPACE%\forensics-learning-book"
DL = os.path.join(BOOK, "decision-lists", "release-hardening-20261022.md")
AS = os.path.join(BOOK, "ASSETS.md")
LEDGER = r"%USERPROFILE%\self-improving\ledger.md"


def read(p):
    return io.open(p, encoding="utf-8", newline="").read()


def write(p, t):
    io.open(p, "w", encoding="utf-8", newline="").write(t)


def sub(txt, old, new, what):
    eol = "\r\n" if "\r\n" in txt else "\n"
    o, n = old.replace("\n", eol), new.replace("\n", eol)
    if txt.count(o) != 1:
        print(f"✗ {what}：命中 {txt.count(o)} 处（应为 1）")
        sys.exit(1)
    return txt.replace(o, n)


# ── 1. 决策清单：结转表改成"已发布" ───────────────────────────────────
txt = read(DL)
old = ("| GitHub 三个独立仓 + 索引仓的**实际推送** | 批 D | **四仓内容与命令均已备** ✓"
       "（`mcopilot` / `axiscope` / `forensics-code-factory` / `forensics-learning-index` ✓，"
       "分支统一 `main` ✓，可见性全部公开 ✓）；**推送未执行** ✓——"
       "本机无 `gh`、且 GitHub 账号未提供 ✓，由作者本机执行 ✓（命令见索引仓 `PUSH-CHECKLIST.md` ✓） |")
new = ("| GitHub 三个独立仓 + 索引仓的**实际推送** | 批 D | **已推送并复验** ✓："
       "`JosephIvon/mcopilot` ✓ / `JosephIvon/axiscope` ✓ / "
       "`JosephIvon/forensics-code-factory` ✓ / `JosephIvon/forensics-learning-index` ✓，"
       "全部**公开** ✓、分支 `main` ✓；四仓本地 HEAD 与远端逐个一致 ✓；"
       "并从 GitHub **干净克隆**复验通过 ✓（读者实际拿到的东西 ✓） |")
txt = sub(txt, old, new, "结转表")
write(DL, txt)
print("  ✓ decision-lists/release-hardening-20261022.md：结转表 → 已发布")

# ── 2. ASSETS：发布登记 ───────────────────────────────────────────────
txt = read(AS)
anchor = ("  **推送仍未执行** ✓：2026-10-23 试过账号密码，三种鉴权头全 401 ✗\n"
          "  → 需作者给一个可用 PAT（勾 `repo`）✓。\n")
if anchor not in txt:
    print("✗ ASSETS 锚点未命中")
    sys.exit(1)
add = """- [2026-10-23 中午·批 D 收官] **四仓已发布到 GitHub（公开）✓**：
  | 仓（GitHub） | 分支 | 发布时 HEAD |
  |---|---|---|
  | `JosephIvon/mcopilot` ✓ | `main` ✓ | `85e45d4` ✓ |
  | `JosephIvon/axiscope` ✓ | `main` ✓ | `0bf4ad4` ✓ |
  | `JosephIvon/forensics-code-factory` ✓ | `main` ✓ | `e651f3b` ✓ |
  | `JosephIvon/forensics-learning-index` ✓ | `main` ✓ | `6a8e9d2` ✓ |

  核验（**GitHub API 独立复核**，不只信推送脚本的回显 ✓）：
  四仓均 `public` ✓、默认分支 `main` ✓；四仓本地 HEAD 与远端 `refs/heads/main`
  **逐个一致** ✓；**中文名路径真实在位** ✓（mcopilot 30 条 ✓ / axiscope 49 条 ✓ /
  工厂 1 条 ✓ —— 这正是此前 `git ls-files` 加引号漏检的那批 ✓）；
  索引仓 README 的 `<账号>` 占位符已替换为真链接 ✓。
  从 GitHub **干净克隆**复验 ✓：mcopilot 376 passed/11 skipped ✓、门禁 10/12（SKIP 2）✓；
  axiscope 294 passed/110 skipped ✓、脱敏自检退出码 0 ✓；
  工厂全品牌再生退出码 0 ✓、单文件与 `gen/` 同源 ✓。
  坐标锚点**未动** ✓（mcopilot `b53ac62` / axiscope `b95ffb2` / trae `954c210` ✓）——
  锚点之后的提交在本书 `ASSETS.md` 登记 ✓，书里 697 个坐标一个没受影响 ✓。
  仍挂账的（不许抹掉 ✓）：真机层未验证 ✓、接缝 3 未闭合 ✓、
  mcopilot 早期提交仍是自动化署名 ✓、协议标准原件外置 ✓（干净克隆时相关门禁记 SKIP ✓）。
"""
txt = txt.replace(anchor, anchor + add, 1)
write(AS, txt)
print("  ✓ ASSETS.md：发布登记")

# ── 3. 台账一条：URL 的 owner 在路径段 ─────────────────────────────────
old = io.open(LEDGER, encoding="utf-8").read()
entry = (
    "- [2026-10-23 中午] 命中 **URL 里的 owner 在路径段，不在 userinfo 段**（小坑，报错很像鉴权失败）：\n"
    "  写 `https://<账号>@github.com/<仓名>.git` ⟹ 账号段只决定**鉴权身份** ✓，\n"
    "  路径仍指向 `github.com/<仓名>` ✗ → 报 `remote: Not Found` ✗。\n"
    "  看着像令牌不行，实际是地址不对 ✓ —— 排查时被它带偏过一次 ✓。\n"
    "  正确：`https://<账号>@github.com/<账号>/<仓名>.git` ✓。\n"
    "  另：`.cmd` 文件里**不许写中文注释** ✓ —— cmd.exe 按本地代码页读 ✓，\n"
    "  中文会被拆成命令执行（实测报 `'不落盘、不进' is not recognized` ✗）✓。\n"
)
if not old.endswith("\n"):
    old += "\n"
io.open(LEDGER, "w", encoding="utf-8").write(old + entry)
print("  ✓ 台账：补 1 条（URL owner 段 / .cmd 纯 ASCII）")
