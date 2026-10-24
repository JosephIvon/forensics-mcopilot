#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_vol2_anchors.py —— 卷二坐标审计的定点清偿脚本（2026-10-22）。

每处替换都要求 old 串在目标文件里**精确出现**（出现次数打印出来；不为 1 则该条跳过并计入失败），
写盘前先在内存里改完再整体落盘，避免半改状态。

背景：axiscope README 于 2026-10-22 提交 b95ffb2，行锚清偿（§六指针 :737-:768/:761 → :780-:818/:804，
状态"尚未完成"→"已执行"），使原 :74 之后内容整体 +3 行；卷二 ch02/ch03 引用的是修复前的旧号，
ch04 则存在同名文件歧义（ControllerFactory.cs 在 out/mc_all 29 行 / out/mc_gts 21 行）。
"""
import os
import sys

REPO = r"%WORKSPACE%\forensics-learning-book"

PAIRS = {
    "chapters-vol2a/ch02-证据等级.md": [
        ("> **素材坐标**：`axiscope@adf4c4b`", "> **素材坐标**：`axiscope@b95ffb2`"),
        ("README 尾部钉着这条纪律（:98-99，逐字）", "README 尾部钉着这条纪律（:101-103，逐字）"),
        ("（锚点：`axiscope@adf4c4b`", "（锚点：`axiscope@b95ffb2`"),
        ("`README.md:98-100`（引用纪律；其 :100 自带", "`README.md:101-103`（引用纪律；其 :103 自带"),
    ],
    "chapters-vol2a/ch03-引进纪律.md": [
        ("> **素材坐标**：`axiscope@adf4c4b`", "> **素材坐标**：`axiscope@b95ffb2`"),
        ("（README.md:80）", "（README.md:83）"),
        ("（README.md:82-83）", "（README.md:85-86）"),
        ("（README.md:85-96）", "（README.md:88-99）"),
        ("| README.md:87 →", "| README.md:90 →"),
        ("| README.md:88 →", "| README.md:91 →"),
        ("| README.md:92 →", "| README.md:95 →"),
        ("| README.md:96 →", "| README.md:99 →"),
        ("（README.md:87-96）", "（README.md:90-99）"),
        ('README §6 的节题干脆就叫"脱敏门禁（发布前\n必做，署名不得清除）"（README.md:74）。',
         'README §6 的节题在脱敏执行前叫"脱敏门禁（发布前必做，署名不得清除）"，\n当日执行后改为"脱敏门禁（发布前必做 → **已执行 2026-10-22**）"（README.md:74）。'),
        ("md5 前后对照（README.md:33-34）", "md5 前后对照（README.md:79-81）"),
        ('（README.md:98-100）', '（README.md:101-103）'),
        ("> `axiscope@adf4c4b README.md`", "> `axiscope@b95ffb2 README.md`"),
        ("*本章事实性句子坐标：`axiscope@adf4c4b` — `README.md`（:4、:6、:10、:12-27、:29-34、\n:51-53、:62-67、:74、:80-96、:98-100）",
         "*本章事实性句子坐标：`axiscope@b95ffb2` — `README.md`（:4、:6、:10、:12-27、:29-34、\n:51-53、:62-67、:74-81、:83-99、:101-103）"),
        ("已知行锚漂移两处批次，本章一律以实测行号为准：README.md:76-77\n转述的 KB2 §六位置（:737-:768、:761）实测已漂移（铁律句实测 KB2:804）；",
         "已知行锚漂移两处批次，本章一律以实测行号为准：README.md:76-77\n转述的 KB2 §六位置（:737-:768、:761）实测已漂移（铁律句实测 KB2:804）——该行锚已于\n2026-10-22 在 axiscope `b95ffb2` 当日修复（指针改指 :780-:818、:804，状态同步为已执行）；"),
    ],
    "chapters-vol2b/ch01-代码工厂.md": [
        ("> `src/Core/ControllerFactory.cs`、`src/Virtual/VirtualController.cs`",
         "> `out/mc_all/src/Core/ControllerFactory.cs`、`out/mc_all/src/Virtual/VirtualController.cs`"),
        ("（README.md:3）", "（out/mc_all/README.md:3）"),
        ("（README.md:9-16）", "（out/mc_all/README.md:9-16）"),
        ("（README.md:18-22）", "（out/mc_all/README.md:18-22）"),
        ("（README.md:41-43）", "（out/mc_all/README.md:41-43）"),
        ("`default: throw new NotSupportedException`（ControllerFactory.cs:25）",
         "`default: throw new NotSupportedException`（out/mc_all/src/Core/ControllerFactory.cs:25）"),
        ("`NotSupportedException`（ControllerFactory.cs:25）", "`NotSupportedException`（out/mc_all/src/Core/ControllerFactory.cs:25）"),
        ("`src/Core/ControllerFactory.cs`（:12 唯一耦合点、:25", "`out/mc_all/src/Core/ControllerFactory.cs`（:12 唯一耦合点、:25"),
        ("`src/Virtual/VirtualController.cs`（:9-13/:38 用途与种子", "`out/mc_all/src/Virtual/VirtualController.cs`（:9-13/:38 用途与种子"),
    ],
    # —— 2026-10-22 21:10 第二批：三代理收尾润色回写了裸文件名坐标（消歧再失效）——
    "ch04-代码工厂.md#2": [],
}

PAIRS["chapters-vol2b/ch01-代码工厂.md#2"] = [
    ("（ControllerFactory.cs:25）。换卡成立靠三条纪律",
     "（out/mc_all/src/Core/ControllerFactory.cs:25）。换卡成立靠三条纪律"),
    ("（ControllerFactory.cs:25）。真正的 ACS 用户",
     "（out/mc_all/src/Core/ControllerFactory.cs:25）。真正的 ACS 用户"),
    ("是栈损坏级故障（VirtualController.cs:317）",
     "是栈损坏级故障（out/mc_all/src/Virtual/VirtualController.cs:317）"),
    ("回归（VirtualController.cs:133）失去无硬件复现场所",
     "回归（out/mc_all/src/Virtual/VirtualController.cs:133）失去无硬件复现场所"),
]
PAIRS["chapters-vol2a/ch03-引进纪律.md#2"] = [
    ("而冻结锚 `adf4c4b` 的 §7 表实数**十行**（README.md:90-99）",
     "而冻结锚 `b95ffb2` 的 §7 表实数**十行**（README.md:90-99）"),
]

fail = 0
already = 0
for fn, pairs in PAIRS.items():
    if not pairs:
        continue
    path = os.path.join(REPO, fn.split("#")[0].replace("/", os.sep))
    text = open(path, encoding="utf-8").read()
    print("=" * 80)
    print(fn)
    for old, new in pairs:
        n = text.count(old)
        if n == 0:
            already += 1
            print(f"  [已生效] {old[:64]!r}")
            continue
        if n != 1:
            print(f"  [SKIP 命中 {n} 次] {old[:70]!r}")
            fail += 1
            continue
        text = text.replace(old, new)
        print(f"  [OK] {old[:64]!r} → {new[:40]!r}")
    open(path, "w", encoding="utf-8", newline="\n").write(text)
print("=" * 80)
print(f"失败条数：{fail} ｜ 已生效（无需再改）：{already}")
sys.exit(1 if fail else 0)
