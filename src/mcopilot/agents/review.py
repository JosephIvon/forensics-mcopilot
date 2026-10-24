"""代码评审智能体（review）：把「实时运动上位机」的隐性规矩变成可执行的检查。

为什么值得做：需求基线的 R-10 要求建立代码评审与单元测试规范，
但这类规范最大的问题是「人review会漏、赶时间就跳」。
把规则做成机器检查，提交前自动跑一遍，比开会强调管用。

规则包在 knowledge/review_rules.json，改规则不用改代码。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..core.report import Report, callout
from ..core.util import knowledge_path, md_table, read_json

# 厂商 SDK 接口（脉冲/原始计数口径）
_PULSE_API = re.compile(r"\b(dmc_[a-z_0-9]+|ZAux_Direct_[A-Za-z_0-9]+|nmc_[a-z_0-9]+)\s*\(([^)]*)\)")
# 本项目的业务接口（mm 口径）
_MM_API = re.compile(r"\b(MoveAbs|MoveRel|MoveLinear|MoveArc|SetPosition|SetTarget|GoToPosition)\s*\(([^)]*)\)")
# 单位换算常量
_CONV = re.compile(r"(?:PulseRatio|PulsePerMm|PulsesPerMm|PulsePerMM|CountsPerMm|CountsPerMM|"
                   r"PulsePerUnit|EncoderScale|GetPulsePerMm|SetPulsePerMm|UNITS|unitsPerMm)")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CPP_KEYWORDS = {"int", "double", "float", "short", "ushort", "long", "byte", "bool", "void",
                 "ref", "out", "in", "var", "new", "true", "false", "null", "this"}


@dataclass
class Issue:
    rule_id: str
    level: str
    file: str
    line_no: int
    text: str
    message: str
    why: str
    fix: str
    requirement: str
    is_positive: bool = False

    @property
    def key(self) -> str:
        return f"{self.file}:{self.line_no}:{self.rule_id}"


def load_rules() -> dict:
    return read_json(knowledge_path("review_rules.json"))


def _iter_files(paths: Sequence[Path], exts: Sequence[str]) -> Iterable[Path]:
    for p in paths:
        if p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.is_file() and child.suffix.lower() in exts:
                    yield child
        elif p.is_file() and p.suffix.lower() in exts:
            yield p


def _idents(arg_text: str) -> list[str]:
    return [i for i in _IDENT.findall(arg_text) if i not in _CPP_KEYWORDS]


def check_unit_consistency(path: Path, rel: str, rules: dict) -> list[Issue]:
    """单位口径数据流检查（RT-004 的核心实现）。

    纯正则只能抓到「dmc_pmove(0, 1, 45.0mm, 1)」这种把单位写进字面量的情况；
    而现实里更常见的是：把一个 **mm 语义的变量**直接传给 **以脉冲为单位的 SDK 接口**。
    这里做一次轻量数据流：
      1. 哪些标识符出现在 mm 制业务接口的实参里（说明它是 mm 语义）；
      2. 哪些标识符出现在厂商 SDK（脉冲制）接口的实参里；
      3. 哪些标识符所在行含脉冲换算常量（说明做过换算）。
    同一个标识符同时落进 1 和 2、却不落进 3 —— 就是漏乘脉冲当量。
    """
    rule = next((r for r in rules["rules"] if r["id"] == "RT-004"), None)
    if rule is None:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()

    mm_vars: set[str] = set()
    pulse_calls: list[tuple[int, str, list[str]]] = []
    converted: set[str] = set()

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        for m in _MM_API.finditer(line):
            mm_vars.update(_idents(m.group(2)))
        for m in _PULSE_API.finditer(line):
            pulse_calls.append((i, stripped, _idents(m.group(2))))
        if _CONV.search(line):
            converted.update(_idents(line))

    issues: list[Issue] = []
    for line_no, snippet, vars_ in pulse_calls:
        for v in vars_:
            if v in mm_vars and v not in converted:
                issues.append(Issue(
                    "RT-004", rule["level"], rel, line_no, snippet,
                    f"疑似漏乘脉冲当量（变量 {v} 同时喂给 mm 制接口与脉冲制 SDK 接口）",
                    rule["why"], rule["fix"], rule.get("requirement", "")))
                break
    return issues


def scan_file(path: Path, root: Path, rules: dict) -> list[Issue]:
    issues: list[Issue] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return issues
    rel = str(path.relative_to(root)) if root in path.parents or path == root else str(path)
    pulse_const = re.compile(rules.get("pulse_constant_pattern", "PulseRatio"), re.IGNORECASE)
    lines = text.splitlines()

    for rule in rules["rules"]:
        try:
            rx = re.compile(rule["pattern"], re.MULTILINE)
        except re.error:
            continue
        # 跨行规则必须对整篇文本匹配，再把匹配位置换算成行号；
        # 逐行匹配对「catch ... { ... }」「嵌套 lock」这类结构永远命中不了。
        if rule.get("multiline"):
            for m in rx.finditer(text):
                line_no = text.count("\n", 0, m.start()) + 1
                snippet = lines[line_no - 1].strip() if line_no <= len(lines) else ""
                if not snippet or snippet.startswith("//") or snippet.startswith("*"):
                    continue
                issues.append(Issue(rule["id"], rule["level"], rel, line_no, snippet,
                                    rule["message"], rule["why"], rule["fix"], rule.get("requirement", ""),
                                    rule.get("is_positive", False)))
            continue
        for i, line in enumerate(lines, 1):
            if len(line) > 2000:
                continue
            if not rx.search(line):
                continue
            if rule.get("needs_pulse_constant"):
                # 该行若已含脉冲当量常量，说明作者做了换算，不报
                if pulse_const.search(line):
                    continue
            if rule.get("is_positive"):
                issues.append(Issue(rule["id"], rule["level"], rel, i, line.strip(),
                                    rule["message"], rule["why"], rule["fix"], rule.get("requirement", ""), True))
                continue
            # 注释行不报
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("#"):
                continue
            issues.append(Issue(rule["id"], rule["level"], rel, i, stripped,
                                rule["message"], rule["why"], rule["fix"], rule.get("requirement", "")))
    return issues


def scan(paths: Sequence[Path], root: Path | None = None) -> dict[str, Any]:
    rules = load_rules()
    root = root or Path.cwd()
    exts = set(rules.get("scan_extensions", [".cs"]))
    all_issues: list[Issue] = []
    files: list[Path] = []
    for p in paths:
        files.extend(_iter_files([p], exts))
    seen: set[Path] = set()
    for f in files:
        if f in seen:
            continue
        seen.add(f)
        issues = scan_file(f, root, rules)
        issues.extend(check_unit_consistency(f, str(f.relative_to(root)) if root in f.parents
                                             else str(f), rules))
        # 同一行同一规则只报一次
        dedup: dict[tuple[str, int, str], Issue] = {}
        for i in issues:
            dedup.setdefault((i.rule_id, i.line_no, i.file), i)
        all_issues.extend(dedup.values())
    order = {"高": 0, "中": 1, "低": 2}
    all_issues.sort(key=lambda i: (order.get(i.level, 9), i.file, i.line_no))
    return {"issues": all_issues, "files": len(seen), "rules": rules}


def build_report(result: dict, stem: str = "review") -> Report:
    issues: list[Issue] = result["issues"]
    rules = result["rules"]
    rep = Report(title="实时运动代码评审报告",
                 subtitle=f"扫描 {result['files']} 个文件　|　规则包 {len(rules['rules'])} 条　|　"
                          f"命中 {len([i for i in issues if not i.is_positive])} 处问题")

    problems = [i for i in issues if not i.is_positive]
    positives = [i for i in issues if i.is_positive]

    if not problems:
        rep.add("结论", callout("低", "**未命中任何规则。**"
                                      "（注意：规则包只覆盖实时运动上位机的典型隐患，"
                                      "不代表代码没问题；它能保证的是「已知坑没踩」。"))
    else:
        high = [i for i in problems if i.level == "高"]
        rep.add("结论先行", "\n".join([
            callout("高" if high else "中",
                    f"**命中 {len(problems)} 处问题，其中高危 {len(high)} 处。**"),
            "",
            "高危项的含义：",
            *["- " + f"`{i.rule_id}` {i.message}（{i.file}:{i.line_no}）" for i in high[:8]],
        ]))

    rep.add("问题清单", md_table(
        ["等级", "规则", "文件:行", "问题", "为什么危险", "怎么改", "需求"],
        [[i.level, i.rule_id, f"{i.file}:{i.line_no}", i.message, i.why, i.fix, i.requirement]
         for i in problems]))

    if positives:
        rep.add("正向提示", "\n".join([
            "以下不是问题，而是**确认你实现到位了**的信号：",
            "",
            md_table(["规则", "文件:行", "说明"],
                     [[i.rule_id, f"{i.file}:{i.line_no}", i.message] for i in positives[:20]]),
        ]))

    # 按规则统计
    stat: dict[str, int] = {}
    for i in problems:
        stat[i.rule_id] = stat.get(i.rule_id, 0) + 1
    rep.add("按规则分布", md_table(
        ["规则", "等级", "含义", "命中数"],
        [[r["id"], r["level"], r["message"], stat.get(r["id"], 0)]
         for r in rules["rules"] if not r.get("is_positive")]))

    rep.add("怎么用", "\n".join([
        "1. **接进提交流程**：`mcopilot review <src> --out out/` 返回非零即视为评审不通过，"
        "可以挂到 CI 或 Git hook 上。",
        "2. **规则包可扩展**：`knowledge/review_rules.json` 里加一条正则就是一个新规则，"
        "不需要改代码。团队可以把自己踩过的坑一条条沉淀进去。",
        "3. **规则不替代人工评审**：机器保证「已知坑不踩」，架构与工艺合理性仍需人判断。",
    ]))
    return rep


def run(paths: Sequence[Path], out_dir: Path, root: Path | None = None) -> dict[str, Any]:
    result = scan(paths, root)
    rep = build_report(result)
    return {"report": rep, "issues": result["issues"]}
