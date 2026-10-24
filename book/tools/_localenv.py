# -*- coding: utf-8 -*-
"""公开仓里不写死本机路径：个人目录与工作区根都从环境变量解析。

为什么需要这个
--------------
这本书要连同代码一起公开，而书与书里的工具大量引用"我本机上的路径"。
批 C 的纪律是**脱敏而不是删**——读者要看得见那是个路径，只是不该看见使用者的家目录。

两个占位符
----------
``%USERPROFILE%``
    真存在的 Windows 环境变量。`os.path.expandvars` 直接展开，
    读者拿到就能用，不是死记的假路径。
``%WORKSPACE%``
    工作区根（同级仓所在）。默认取**本仓的上一级**——
    同级仓（`axiscope` / `forensics-code-factory` / `forensics-learning-book`）就在那儿，
    这不是猜的，是布局事实。可用环境变量 `MCOPILOT_WORKSPACE` 覆盖。

环境变量
--------
``MCOPILOT_SELF_IMPROVING``  个人自改进目录（记忆/台账），默认 ``%USERPROFILE%\\self-improving``
``MCOPILOT_WORKSPACE``       工作区根，默认本仓的上一级
``MCOPILOT_ROOT``            本仓根（`core/util.py` 用的那个）
"""
from __future__ import annotations

import os
from pathlib import Path

# <repo>/book/tools/_localenv.py → <repo>/book → <repo> → <repo>/..
REPO_ROOT = Path(__file__).resolve().parents[2]
BOOK_DIR = REPO_ROOT / "book"


def user_dir() -> Path:
    """个人自改进目录（记忆 memory.md / 台账 ledger.md 所在）。"""
    raw = os.environ.get("MCOPILOT_SELF_IMPROVING", r"%USERPROFILE%\self-improving")
    return Path(os.path.expandvars(raw))


def workspace() -> Path:
    """工作区根——同级仓所在。默认本仓的上一级。"""
    env = os.environ.get("MCOPILOT_WORKSPACE")
    if env:
        return Path(os.path.expandvars(env)).resolve()
    return REPO_ROOT.parent


# 同级仓的**目录名**可能与仓名不同，也可能改过：
#   2026-10-24 `trae_factory` 目录改名为 `forensics-code-factory`（与 GitHub 仓名一致）。
# 代码里对它的引用是**项目标识**（锚点 `trae_factory@954c210`、知识库与测试里的 key），
# 不该跟着目录改；但**找目录**必须认得出新名字。集中一张别名表，避免各处各写一份。
SIBLING_ALIASES: dict[str, tuple[str, ...]] = {
    "trae_factory": ("forensics-code-factory", "trae_factory"),
}


def sibling(name: str):
    """按别名表解析同级仓目录；都没有就返回首选名（调用方据此判「缺仓」）。"""
    ws = workspace()
    for cand in SIBLING_ALIASES.get(name, (name,)):
        p = ws / cand
        if p.is_dir():
            return p
    return ws / SIBLING_ALIASES.get(name, (name,))[0]


def expand(path_like: str) -> str:
    """把 `%USERPROFILE%` / `%WORKSPACE%` 展开成实际路径。

    `%WORKSPACE%` 不是系统变量，所以先自己替换，再交给 expandvars 处理其余的。

    同级仓改过名时（见 `SIBLING_ALIASES`），`%WORKSPACE%\trae_factory` 这种
    **旧写法**会重定向到真实目录——否则它会变成一个不存在的路径，
    让引用静默落到「仓不在位」，门禁少扫而没人知道。
    """
    ws = workspace()
    out = path_like.replace("%WORKSPACE%", str(ws))
    out = os.path.expandvars(out)
    for alias in SIBLING_ALIASES:
        stale = ws / alias
        if stale.exists():
            continue
        real = sibling(alias)
        head = str(stale)
        if real.exists() and (out == head or out.startswith(head + os.sep)):
            out = str(real) + out[len(head):]
    return out
