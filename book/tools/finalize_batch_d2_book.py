#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""finalize_batch_d2_book.py —— 批 D 续：干净克隆门禁入册 + 台账补两条（2026-10-23 上午）。

这一轮做的是**上一轮没做的那件事**：公开仓的验收标准不是"本机工作树绿"，
而是**读者克隆下来能跑** ✓。实测挖出五个真发布缺陷 ✓，全部已修 ✓，
并固化成常设门禁 `tools/verify_clean_clone.py` ✓。

五个缺陷（一律只有换一副眼睛才看得见 ✓）：
  ① `.gitignore` 的 `*.log` 把三个测试夹具扫掉 → 克隆里 14 个测试红 ✓
  ② 原始数据按 A-131 不入库 → axiscope 87 个测试函数 FileNotFoundError ✓
  ③ mcopilot 的 G5 与 G7/G12 缺件口径不一致 → G5 把「原件不在位」判成失败 ✓
  ④ 负向门禁 N1 在缺件时**假绿**：拒绝的是「规范文本缺失」，
     却记成「编造引文被拒」的检测力已证明 ✓
  ⑤ 跨仓桥接用例缺跳过守卫 → CI 上（只有 mcopilot 一个仓）必红 ✓

台账两条：
  A. **验收要在读者的环境里做**（干净克隆 / 干净环境 / 别人的机器）✓
  B. **跳过必须区分「没跑」与「跑了没通过」** ✓ —— 混起来就是假绿 ✓
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


# ── 1. 决策清单：V15 / B15 ─────────────────────────────────────────────
txt = read(DL)
txt = sub(txt,
    "- **V14 保留 `trae` 公开仓名**",
    """- **V15 用「本机工作树全绿」当发布验收**——否决 ✗。
  公开仓的验收标准是**读者克隆下来能跑** ✓。2026-10-23 发布前实测：
  本机全绿（mcopilot 387 passed / 门禁 12/12；axiscope 403 passed ✓），
  但**本地路径克隆**（= GitHub 将提供的同一份内容 ✓）里挖出**五个真发布缺陷** ✓
  （`.gitignore` 误扫测试夹具 ✓、原始数据不在位导致 87 个测试红 ✓、
  G5 与 G7/G12 缺件口径不一致 ✓、负向门禁 N1 **假绿** ✓、
  跨仓桥接用例缺守卫 ✓）。
  → 固化为常设门禁 `tools/verify_clean_clone.py` ✓（三仓 16 步全绿 ✓）。
- **V14 保留 `trae` 公开仓名**""",
    "V15")

txt = sub(txt,
    "- **B13 可见性：三个工程仓全部公开**",
    """- **B15 跳过必须分三态**（PASS / FAIL / SKIP）✓：**SKIP = 没跑** ✓，
  不是「跑了没通过」✓，更不是「通过了」✓。
  缺件时：门禁记 SKIP ✓、测试 loud SKIP ✓、负向门禁的用例整条 SKIP 且**不执行注入** ✓
  —— 混起来就是假绿 ✓（本轮 N1 就是这么假绿的 ✓）。
  每条 SKIP 都必须：①在汇总行单列 ✓；②写明「当前不可自动复核」✓；
  ③**不许记成 PASS** ✓。
- **B13 可见性：三个工程仓全部公开**""",
    "B15")
write(DL, txt)
print("  ✓ decision-lists/release-hardening-20261022.md：V15 / B15")

# ── 2. ASSETS：登记干净克隆门禁与五处处置 ────────────────────────────
txt = read(AS)
anchor = "  只改 GitHub 公开名 ✓，并在仓内 README 写明**内部名 ↔ 公开名**的对应 ✓。\n"
if anchor not in txt:
    print("✗ ASSETS 锚点未命中")
    sys.exit(1)
add = """- [2026-10-23 上午·批 D 续] **新增发布硬门槛：干净克隆可跑** ✓：
  本机工作树绿 ≠ 公开后能用 ✓。实测（本地路径克隆 = GitHub 将提供的同一份内容 ✓）
  挖出**五个真发布缺陷** ✓，全部已修 ✓：
  ① mcopilot `.gitignore` 的 `*.log` 把 `samples/logs/*.log` 三个测试夹具扫掉 ✗
     → 克隆里 14 个测试因缺夹具而红 ✓（补 `!samples/logs/*.log` ✓）；
  ② axiscope 原始数据按 A-131 不入库 ✗ → 87 个测试函数 FileNotFoundError ✓
     （新增 `tests/conftest.py` ✓，按各文件 `REQUIRES_DATA` **显式声明** loud SKIP ✓）；
  ③ mcopilot 的 G5 与 G7/G12 缺件口径不一致 ✗ → G5 把「原件不在位」判成失败 ✓
     （改为与 G7/G12 同口径记 SKIP ✓）；
  ④ mcopilot 负向门禁 N1 在缺件时**假绿** ✗ —— 拒绝的是「规范文本缺失」，
     却记成「编造引文被拒」的检测力已证明 ✓
     （基线不可核 ⟹ 整条用例 SKIP 且**不执行注入** ✓；框架加 SKIP 三态 ✓）；
  ⑤ mcopilot 跨仓桥接用例缺跳过守卫 ✗ → CI 上（只有 mcopilot 一个仓）必红 ✓
     （补守卫 ✓）。
  固化：书仓新增门禁 `tools/verify_clean_clone.py` ✓——克隆三仓到临时目录 ✓，
  按各自 CI 步骤**逐条复演** ✓（三仓 16 步全绿 ✓），
  并把 SKIP 的条数与原因原样带出来 ✓（跳过 ≠ 通过 ✓）。
  索引仓另附 `push_to_github.ps1` ✓：建空仓 → 推四仓 → **从 GitHub 干净克隆复验** ✓；
  令牌只进进程环境 ✓，不落盘 ✓、不进 git config ✓。
  **推送仍未执行** ✓：2026-10-23 试过账号密码，三种鉴权头全 401 ✗
  → 需作者给一个可用 PAT（勾 `repo`）✓。
"""
txt = txt.replace(anchor, anchor + add, 1)
write(AS, txt)
print("  ✓ ASSETS.md：干净克隆门禁与五处处置登记")

# ── 3. 台账两条 ───────────────────────────────────────────────────────
old = io.open(LEDGER, encoding="utf-8").read()
entry = (
    "- [2026-10-23 上午] 命中 **验收要在读者的环境里做**（新类）：发布前的验收我一直在\n"
    "  **本机工作树**上做 ✓ —— 那是作者的环境、带着未跟踪文件 ✓、三个仓摆在一起 ✓。\n"
    "  改成**本地路径克隆**（= 公开后读者拿到的东西 ✓）再跑一遍当天的 CI 步骤 ✓，\n"
    "  一次挖出**五个真发布缺陷** ✓：`.gitignore` 的 `*.log` 误扫测试夹具 ✓、\n"
    "  原始数据不入库导致 87 个测试红 ✓、两个门禁的缺件口径不一致 ✓、\n"
    "  负向门禁在缺件时**假绿** ✓、跨仓用例缺跳过守卫 ✓。\n"
    "  新规：①任何交付物的验收，必须在**干净环境**里做（干净克隆/干净容器/别人的机器）✓；\n"
    "  ②「本机绿」只能证明**代码没写错**，不能证明**读者能用** ✓；\n"
    "  ③把这条固化成常设门禁（书仓 `tools/verify_clean_clone.py` ✓）✓，\n"
    "     别靠记性——下个月谁还会记得克隆一遍 ✓。\n"
    "- [2026-10-23 上午] 命中 **跳过必须分三态**（PASS / FAIL / SKIP）：\n"
    "  负向门禁 N1 在缺件时退出码非 0 → 被记成 `[PASS=YES]` ✓，\n"
    "  但它拒绝的是「规范文本缺失」，**不是**「编造引文」✓ —— 把**没核**记成**核过** ✓。\n"
    "  这是「静默 skip 也算绿」一族里最坏的一种 ✓。\n"
    "  新规：①SKIP 单列一态 ✓，含义是「**没跑**」✓，不许与 FAIL 混 ✓；\n"
    "  ②基线不可核时**整条用例 SKIP 且不执行注入** ✓（跑了也只是在测别的东西 ✓）；\n"
    "  ③汇总行必须把 SKIP 的条数与原因喊出来 ✓，分母不含 SKIP ✓；\n"
    "  ④有 SKIP 时不许说「检测力已证明」✓（本轮连收尾话都自相矛盾过 ✓，已改 ✓）。\n"
)
if not old.endswith("\n"):
    old += "\n"
io.open(LEDGER, "w", encoding="utf-8").write(old + entry)
print("  ✓ 台账：补 2 条（验收环境 / 跳过三态）")
