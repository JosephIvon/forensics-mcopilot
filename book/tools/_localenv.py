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
    同级仓（`axiscope` / `trae_factory` / `forensics-learning-book`）就在那儿，
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


def expand(path_like: str) -> str:
    """把 `%USERPROFILE%` / `%WORKSPACE%` 展开成实际路径。

    `%WORKSPACE%` 不是系统变量，所以先自己替换，再交给 expandvars 处理其余的。
    """
    out = path_like.replace("%WORKSPACE%", str(workspace()))
    return os.path.expandvars(out)
