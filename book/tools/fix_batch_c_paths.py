#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_batch_c_paths.py —— 批 C 第 1 项：绝对路径/用户名泄露的定点清偿（2026-10-22）。

两类处置，标准不同：
  · **参数化**（代码里的路径）：改环境变量 + 同级兄弟目录发现，读者换机即用；
  · **脱敏**（文档里的历史路径）：按该仓**自己写下的规则**替换占位
    （axiscope KB2 §六：「只留 basename 或占位」）——本仓的规则早就在，
    这次只是把没执行的地方执行掉。

纪律：精确串 + 命中次数断言；次数不符即退出，不静默改坏。
"""
import io
import os
import sys

MC = r"%WORKSPACE%\mcopilot"
AX = r"%WORKSPACE%\axiscope"

PY_RUNTIME = r"%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
PY_TOOLS = sys.executable

# (仓, 相对路径, 旧串, 新串, 期望命中数)
FIXES = [
    # ── mcopilot：门禁/模板脚本的 Python 解释器默认值 ───────────────────────────
    (MC, r"scripts\gate_protocol.ps1",
     f'[string]$PythonExe = "{PY_RUNTIME}",',
     '[string]$PythonExe = "python",   # 默认用 PATH 上的 python；可用 -PythonExe 覆盖', 1),
    (MC, r"scripts\gate_protocol.ps1",
     f'[string]$PyTestExe = "{PY_TOOLS}",',
     '[string]$PyTestExe = "python",   # 同上', 1),
    (MC, r"scripts\gate_corpus.ps1",
     f'[string]$PythonExe = "{PY_RUNTIME}",',
     '[string]$PythonExe = "python",   # 默认用 PATH 上的 python；可用 -PythonExe 覆盖', 1),
    (MC, r"scripts\gate_farm.ps1",
     f'[string]$PythonExe = "{PY_RUNTIME}",',
     '[string]$PythonExe = "python",   # 默认用 PATH 上的 python；可用 -PythonExe 覆盖', 1),
    (MC, r"scripts\gate_negative.ps1",
     f'[string]$PythonExe = "{PY_RUNTIME}",',
     '[string]$PythonExe = "python",   # 默认用 PATH 上的 python；可用 -PythonExe 覆盖', 1),
    (MC, r"scripts\gate_onboard.ps1",
     f'[string]$PythonExe = "{PY_RUNTIME}",',
     '[string]$PythonExe = "python",   # 默认用 PATH 上的 python；可用 -PythonExe 覆盖', 1),
    (MC, r"knowledge\templates\protocol\run_contract.ps1",
     f'[string]$PythonExe = "{PY_RUNTIME}",',
     '[string]$PythonExe = "python",   # 默认用 PATH 上的 python；可用 -PythonExe 覆盖', 1),
    (MC, r"knowledge\templates\protocol\run_rtu_contract.ps1",
     f'[string]$PythonExe = "{PY_RUNTIME}",',
     '[string]$PythonExe = "python",   # 默认用 PATH 上的 python；可用 -PythonExe 覆盖', 1),
    (MC, r"docs\CodeWiki_20261022.md",
     PY_TOOLS, "python", 1),
    (MC, r"knowledge\templates\protocol\README.md",
     PY_TOOLS, "python", 1),

    # ── mcopilot：跨仓路径参数化（兄弟目录发现 + 环境变量优先）───────────────────
    (MC, r"scripts\verify_trae_pinvoke.py",
     'DEFAULT_TRAE_OUT = r"%WORKSPACE%\\trae_factory\\out"',
     '# trae_factory 仓的位置：环境变量 TRAE_FACTORY_DIR 优先，其次按同级兄弟目录找\n'
     '_TRAE = os.environ.get("TRAE_FACTORY_DIR") or os.path.join(os.path.dirname(_REPO), "trae_factory")\n'
     'DEFAULT_TRAE_OUT = os.path.join(_TRAE, "out")', 1),
    (MC, r"scripts\verify_traekb_citations.py",
     'DEFAULT_KB = r"%WORKSPACE%\\trae_factory\\gen\\adapters_kb.js"',
     '# trae_factory 仓的位置：环境变量 TRAE_FACTORY_DIR 优先，其次按同级兄弟目录找\n'
     '_TRAE = os.environ.get("TRAE_FACTORY_DIR") or os.path.join(os.path.dirname(ROOT), "trae_factory")\n'
     'DEFAULT_KB = os.path.join(_TRAE, "gen", "adapters_kb.js")', 1),
    (MC, r"tests\test_trae_truth_bridge.py",
     'DEFAULT_KB = r"%WORKSPACE%\\trae_factory\\gen\\adapters_kb.js"',
     '# trae_factory 仓的位置：环境变量 TRAE_FACTORY_DIR 优先，其次按同级兄弟目录找\n'
     '_TRAE = os.environ.get("TRAE_FACTORY_DIR") or os.path.join(os.path.dirname(ROOT), "trae_factory")\n'
     'DEFAULT_KB = os.path.join(_TRAE, "gen", "adapters_kb.js")', 1),
    (MC, r"tests\test_fault_mode_slugs.py",
     'DEFAULT_KB0 = r"%USERPROFILE%\\Documents\\Qoder\\2026-10-19\\4dc146eb\\docs\\kb\\KB0-conventions.md"',
     '# axiscope 仓的 KB0：环境变量 AXISCOPE_DIR 优先，其次按同级兄弟目录找\n'
     '_AXIS = os.environ.get("AXISCOPE_DIR") or os.path.join(os.path.dirname(ROOT), "axiscope")\n'
     'DEFAULT_KB0 = os.path.join(_AXIS, "docs", "kb", "KB0-conventions.md")', 1),
    (MC, r"README.md",
     "mcopilot forensics thresholds D:\\logs\\你的日志.log --out out",
     "mcopilot forensics thresholds logs/你的日志.log --out out", 1),

    # ── axiscope：按本仓 KB2 §六「只留 basename 或占位」的规则脱敏 ────────────────
    (AX, r"docs\kb\KB0-conventions.md",
     r"%USERPROFILE%\.qoder-cn\memory\feedback-verify-subagent-completion-claims.md",
     "<个人 memory 目录>/feedback-verify-subagent-completion-claims.md", 1),
    (AX, r"docs\kb\KB0-conventions.md",
     r"%USERPROFILE%\Documents\Qoder\2026-10-19\4dc146eb",
     "<用户目录下的会话工作区>", 1),
    (AX, r"docs\kb\KB0-conventions.md",
     r"%WORKSPACE%\axiscope", "<工作区>\\axiscope", 1),
    (AX, r"docs\AUDIT-minimax-round3.md",
     r"%USERPROFILE%\.minimax\sessions\mvs_838bec01bb00476594f48711e6b172d0\workspace\mcopilot",
     "<另一会话的工作区>\\mcopilot", 1),
    (AX, r"docs\kb\KB5-simulation-plant.md",
     r"%USERPROFILE%\.minimax\sessions\mvs_838bec01bb00476594f48711e6b172d0\workspace\mcopilot",
     "<另一会话的工作区>\\mcopilot", 1),
    (AX, r"docs\AUDIT-glm-code-factory.md",
     r"%USERPROFILE%\Documents\Trae-CN\temp_20261019_01",
     "<Trae-CN 会话临时目录>", 1),
    (AX, r"data\PROVENANCE-TEMPLATE.md",
     r"D:\迅雷下载", "<本机下载目录>", 1),
    (AX, r"data\VERIFICATION-2026-10-20.md",
     r"D:\迅雷下载", "<本机下载目录>", 1),
    (AX, r"data\research_5171_cdd.md",
     r"<厂区>\Projekte\cati-twincat\TC3_MeasurementProjects\Experiments\Export_Ch2\Export 5.csv",
     "[REDACTED_HOST_PATH]\\Export 5.csv", 1),
    (AX, r"docs\kb\KB2-waveform-formats.md",
     r"<厂区>\Projekte\cable-actuator-testbed\...\Export 10.csv",
     "[REDACTED_HOST_PATH]\\Export 10.csv", 2),
    (AX, r"docs\kb\KB7-dataset-da-rus-cat.md",
     r"<厂区>\Projekte\...\Export 10.csv",
     "[REDACTED_HOST_PATH]\\Export 10.csv", 1),
    (AX, r"README.md",
     "（`Versuchsstand` / `141.58.` / `C:\\`）", "（厂区名 / IP 前缀 / 盘符）", 1),
]


def main():
    cache = {}
    applied, failed = 0, []
    for repo, rel, old, new, cnt in FIXES:
        path = os.path.join(repo, rel)
        if path not in cache:
            cache[path] = io.open(path, encoding="utf-8", newline="").read()
        txt = cache[path]
        got = txt.count(old)
        if got != cnt:
            failed.append((rel, old[:70], got, cnt))
            continue
        cache[path] = txt.replace(old, new)
        applied += 1
    if failed:
        print("✗ 有替换未达期望命中数，未写盘：")
        for rel, old, got, cnt in failed:
            print(f"    {rel}  期望 {cnt} 实得 {got}  ← {old}")
        sys.exit(1)
    for path, txt in cache.items():
        io.open(path, "w", encoding="utf-8", newline="").write(txt)
        print(f"  ✓ {os.path.relpath(path, MC if path.startswith(MC) else AX)}")
    print(f"\n共 {applied} 处落盘（{len(cache)} 个文件）")


if __name__ == "__main__":
    main()
