"""架构契约测试：本仓的目录结构是**设计决定**，不是历史遗留。

被钉住的五条不变式（每条都对应一条真实的架构理由）：

1. **包内只有代码。** `src/mcopilot/` 里不放数据、不放文档。
   理由：分发时打包器只会带走包内的东西；真值基座与书要留在仓里当**被审证据**。

2. **真值基座在包外。** `knowledge/` 不在 `src/mcopilot/` 下面。
   理由：真值基座同时是运行时数据、被审证据（记厂商原件 sha256）、书里的锚点，
   而且它自己还指向**仓外**的厂商原件（`../mcopilot-external/`）。
   放进包里就等于把它降级成"随包的普通数据"，这三个身份一起丢掉。

3. **仓库根的解析不依赖固定层数。** 不能写死 `parents[1]` / `parents[2]`。
   理由：换布局、换安装方式（签出 / 可编辑安装 / 换装）时根的位置会变，
   写死层数就会静默指向错的地方——本仓曾经因此在装成 wheel 后指向 `site-packages/knowledge`。

4. **包必须被显式声明。** 在仓库根直接 `import mcopilot` **应当失败**。
   理由：否则你可能跑到一个"装着的旧副本"，而不是你以为在跑的那份——
   这正是 src 布局要买的东西。扁平布局会把这一条悄悄弄丢。

5. **找不到真值基座时，报一条能照着做的错**，而不是裸 `FileNotFoundError`。
   理由：分发单元是仓库不是 wheel（见 `core/util.py` 的数据契约说明），
   使用者遇到的第一件事就是"那我怎么跑"，错误信息必须回答它。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mcopilot.core import util

REPO_ROOT = util.ROOT_DIR
PKG_DIR = util.PKG_DIR

# 临时目录：优先用系统临时目录（%TEMP%）；不可写就退回仓内 `.test_tmp/`。
# 系统临时目录在**仓外**——模拟"独立安装"布局时必须仓外，否则向上找根会找到真仓库。
def _sys_temp() -> Path | None:
    import tempfile

    d = Path(tempfile.gettempdir())
    probe = d / f".mcopilot_probe_{os.getpid()}"
    try:
        probe.mkdir(exist_ok=True)
        probe.rmdir()
    except OSError:
        return None
    return d


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _tmpdir(name: str, must_be_outside_repo: bool = False) -> Path:
    import uuid

    base = _sys_temp()
    if base is None or (must_be_outside_repo and _is_under(base, REPO_ROOT)):
        base = REPO_ROOT / ".test_tmp"
    d = base / f"mcopilot-{name}-{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- 1 & 2

def test_包内只有代码_没有数据与文档():
    """包目录里只允许 .py。数据/文档留在仓里，才不会被打包器悄悄带走。"""
    strays = [
        p for p in PKG_DIR.rglob("*")
        if p.is_file()
        and p.suffix != ".py"
        and "__pycache__" not in p.parts
    ]
    assert strays == [], f"包目录里出现了非 .py 文件：{[str(p.relative_to(PKG_DIR)) for p in strays]}"


def test_真值基座在包外():
    """`knowledge/` 必须在包外——它是证据，不是随包数据。"""
    assert (REPO_ROOT / "knowledge").is_dir(), "仓库根应当有真值基座 knowledge/"
    assert not (PKG_DIR / "knowledge").exists(), \
        "真值基座不得放进包里：它还指向仓外的厂商原件，装进包就断了"
    assert not (PKG_DIR / "book").exists(), "电子书不得放进包里"
    assert not (PKG_DIR / "samples").exists(), "样本夹具不得放进包里"


def test_仓库根确实是仓库根():
    """解析出来的根必须同时具备仓库的标志性目录，而不是碰巧存在的某个上级目录。"""
    for marker in ("knowledge", "samples", "src", "tests", "pyproject.toml"):
        assert (REPO_ROOT / marker).exists(), f"仓库根缺少 {marker}：{REPO_ROOT}"
    assert (PKG_DIR / "core" / "util.py").is_file()


# ---------------------------------------------------------------- 3

def test_仓库根解析不依赖固定层数(monkeypatch):
    """根由「找带 knowledge/ 的祖先」决定，不由「往上数几层」决定。"""
    monkeypatch.setenv("MCOPILOT_ROOT", str(REPO_ROOT))
    assert util._resolve_root() == REPO_ROOT.resolve()

    tmp = _tmpdir("rootresolve")
    try:
        (tmp / "knowledge").mkdir(exist_ok=True)
        monkeypatch.setenv("MCOPILOT_ROOT", str(tmp))
        assert util._resolve_root() == tmp.resolve()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_环境变量指向没有基座的目录时报错(monkeypatch):
    monkeypatch.setenv("MCOPILOT_ROOT", str(REPO_ROOT / "docs"))
    with pytest.raises(RuntimeError) as ei:
        util._resolve_root()
    assert "knowledge" in str(ei.value)


def test_找不到基座时报可操作的错(monkeypatch):
    """第 5 条不变式：错信息必须回答「那我该怎么跑」。"""
    monkeypatch.delenv("MCOPILOT_ROOT", raising=False)
    monkeypatch.setattr(util, "PKG_DIR", Path("/nonexistent/pkg/mcopilot"))
    monkeypatch.setattr(util.Path, "parents", property(lambda self: ()))  # 无祖先可找
    with pytest.raises(RuntimeError) as ei:
        util._resolve_root()
    msg = str(ei.value)
    for token in ("MCOPILOT_ROOT", "pip install -e", "PYTHONPATH"):
        assert token in msg, f"错误信息缺少可操作提示 {token!r}：{msg}"


# ---------------------------------------------------------------- 4

def test_从仓库根直接_import_mcopilot_不成立():
    """第 4 条不变式：包必须被显式声明，否则会跑到装着的旧副本上。"""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(
        [sys.executable, "-c", "import mcopilot"],
        cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, encoding="utf-8",
    )
    assert p.returncode != 0, (
        "在仓库根不声明 PYTHONPATH 就能 import mcopilot —— "
        "src 布局的包边界失效了，使用者可能跑到装着的旧副本上"
    )


# ---------------------------------------------------------------- 5

def test_装成wheel的布局会报出可操作的错():
    """把包单独放进 site-packages 式的目录，导入时应当报出可照着做的错。"""
    tmp = _tmpdir("wheellayout", must_be_outside_repo=True)
    if _is_under(tmp, REPO_ROOT):
        pytest.skip("需要一个仓外的临时目录才能模拟独立安装布局；本机系统临时目录不可用")
    try:
        fake_site = tmp / "site-packages"
        shutil.copytree(
            PKG_DIR, fake_site / "mcopilot",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = str(fake_site)
        p = subprocess.run(
            [sys.executable, "-c", "import mcopilot.core.util"],
            cwd=str(tmp), env=env,
            capture_output=True, text=True, encoding="utf-8",
        )
        assert p.returncode != 0
        combined = (p.stdout or "") + (p.stderr or "")
        assert "MCOPILOT_ROOT" in combined, (
            f"独立安装布局下应当报出可操作提示，实际输出：\n{combined[-1500:]}"
        )
        assert "FileNotFoundError" not in combined, (
            "不应把裸 FileNotFoundError 甩给使用者"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 6
# 第 6 条不变式：**声明的 Python 下限要真的成立**。

def _py_files_under(*rel_dirs: str) -> list[Path]:
    out: list[Path] = []
    for d in rel_dirs:
        base = REPO_ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" not in p.parts:
                out.append(p)
    return out


def _declared_python_floor() -> tuple[int, int]:
    """从 pyproject.toml 读 requires-python 的下限（如 ">=3.9" → (3, 9)）。"""
    import re as _re

    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = _re.search(r'requires-python\s*=\s*"[>=~^]*\s*(\d+)\.(\d+)"', text)
    assert m, "pyproject.toml 里读不到 requires-python 的版本下限"
    return int(m.group(1)), int(m.group(2))


def test_声明的_python_下限没有被运行期求值的语法突破():
    """`requires-python` 是一句对外承诺，必须真的兑现。

    最容易破的一条：`X | Y`（PEP 604）在**注解**里是 3.10 才有的写法。
    本仓大量使用它，所以每个文件都得开 `from __future__ import annotations`，
    否则在 3.9 上**导入即报错**（注解会在类/函数定义时被求值）。
    本仓曾经有一处漏开（`scripts/validate_comm_log.py`），已修。
    """
    import ast

    floor = _declared_python_floor()
    offenders: list[str] = []
    for p in _py_files_under("src", "scripts", "tests", "book"):
        src = p.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src, filename=str(p))
        except SyntaxError as e:  # pragma: no cover - 语法错误由 pytest 自己报
            offenders.append(f"{p}: 语法错误 {e}")
            continue
        has_future = any(
            isinstance(n, ast.ImportFrom) and n.module == "__future__"
            and any(a.name == "annotations" for a in n.names)
            for n in tree.body
        )
        if has_future:
            continue
        for node in ast.walk(tree):
            ann = None
            if isinstance(node, ast.AnnAssign):
                ann = node.annotation
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                ann = node.returns
            if ann is None:
                continue
            if any(isinstance(s, ast.BinOp) and isinstance(s.op, ast.BitOr)
                   for s in ast.walk(ann)):
                offenders.append(
                    f"{p.relative_to(REPO_ROOT)}:{getattr(node, 'lineno', '?')} "
                    f"注解用了 `X | Y`（PEP 604，3.10+）但本文件没开 "
                    f"`from __future__ import annotations`"
                )
                break
    assert not offenders, (
        "声明的 Python 下限是 "
        f"{floor[0]}.{floor[1]}，但下列文件在它上面会**导入即报错**：\n  "
        + "\n  ".join(offenders)
    )


def test_声明的_python_下限没有被_3_10_以上的标准库_API_突破():
    """上面那条管语法，这条管 API：`tomllib`（3.11）、`itertools.pairwise`（3.10）等。"""
    floor = _declared_python_floor()
    if floor >= (3, 12):
        pytest.skip("下限已到 3.12+，本检查针对 3.9/3.10/3.11 的 API 增量")
    newer = {
        "tomllib": (3, 11), "itertools.pairwise": (3, 10), "asyncio.TaskGroup": (3, 11),
        "asyncio.timeout": (3, 11), "typing.Self": (3, 11), "typing.TypeAlias": (3, 10),
        "datetime.UTC": (3, 11), "ExceptionGroup": (3, 11), "BaseExceptionGroup": (3, 11),
        "contextlib.chdir": (3, 11), "enum.StrEnum": (3, 11), "inspect.get_annotations": (3, 10),
        "types.NoneType": (3, 10), "itertools.batched": (3, 12),
    }
    offenders: list[str] = []
    for p in _py_files_under("src", "scripts"):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for api, need in newer.items():
                if api in line and need > floor:
                    offenders.append(
                        f"{p.relative_to(REPO_ROOT)}:{i} 用了 {api}（需 {need[0]}.{need[1]}+），"
                        f"但本仓声明的下限是 {floor[0]}.{floor[1]}"
                    )
    assert not offenders, "\n  ".join(offenders)
