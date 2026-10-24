# -*- coding: utf-8 -*-
"""failure_signatures.json 语料库自检 + 接入循环解释器确定性测试。

为什么要有这个文件
------------------
failure_signatures.json 是 harness 接入闭环（scripts/onboard_loop.py）的「失败解读
真值来源」。语料库如果没人守，它可以悄悄烂掉：签名正则编译不过、evidence 锚点指向
不存在的文件/散列、良性输出被误归因、action_class 写出循环执行不了的动词——
而接入循环**照跑**（归因错误比不归因更危险：会引导错误动作）。

这几条断言盯的就是这些（rule 4 精神：锚点必须可查）：

  1) schema：每条必有 {id, signature, root_cause, next_action, evidence, gate}，
     id 唯一、signature 可编译、action_class 在循环的动作词表内；
  2) evidence 引用存在性：`path:<仓库相对路径>#<锚点文本>` 的文件必须在场且锚点
     文本出现在文件内容里；`commit:<散列>` 必须能在仓库文本（文档/知识库/脚本）
     里查到——禁 git 环境下以仓库文本为可查口径；
  3) 每条签名的 probe_sample（真实观测样本）必须被自己的签名命中；
  4) 良性/语料外样本零误报（含接入门场景 C 的未知失败样本——必须 UNKNOWN 而非误归因）；
  5) 解释器确定性：首中即归因、顺序 = 语料数组顺序、RESULT 行两种形态都能解析。
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import onboard_loop  # noqa: E402

SIG_PATH = ROOT / "knowledge" / "protocols" / "failure_signatures.json"
LOOP_PY = ROOT / "scripts" / "onboard_loop.py"
REQUIRED_FIELDS = {"id", "signature", "root_cause", "next_action", "evidence", "gate"}
EVIDENCE_RE = re.compile(r"^(commit:[0-9a-fA-F]{7,40}|path:[^#]+(?:#.+)?)$")
# 跳过 out/ 等可再生目录（同 test_repo_encoding 的口径）
SEARCH_SKIP_DIRS = {".git", "out", "__pycache__", ".pytest_cache", ".venv"}


@pytest.fixture(scope="module")
def corpus():
    data = json.loads(SIG_PATH.read_text(encoding="utf-8"))
    assert str(data.get("schema_version", "")).startswith("failure_signatures/"), \
        "schema_version 必须以 failure_signatures/ 开头"
    return data


@pytest.fixture(scope="module")
def signatures(corpus):
    return onboard_loop.load_signatures(SIG_PATH)


# ---------------------------------------------------------------- 1) schema
def test_语料至少六条且必填字段齐全(corpus):
    sigs = corpus["signatures"]
    assert len(sigs) >= 6, f"语料不足 6 条：{len(sigs)}"
    for s in sigs:
        missing = REQUIRED_FIELDS - set(s.keys())
        assert not missing, f"{s.get('id')}：缺必填字段 {missing}"
        assert s["id"].startswith("SIG-"), f"{s['id']}：id 必须 SIG- 前缀"
        assert s["root_cause"].strip() and s["next_action"].strip(), \
            f"{s['id']}：root_cause/next_action 不得为空"
        assert re.match(r"^G\d+(?:/G\d+)*$", s["gate"]), f"{s['id']}：gate 形如 G3 或 G2/G4"


def test_签名id唯一且正则可编译(signatures):
    ids = [s.id for s in signatures]
    assert len(ids) == len(set(ids)), f"签名 id 重复：{ids}"
    for s in signatures:
        assert s.regex is not None  # load_signatures 已编译，编译失败会在装载时炸


def test_action_class必须在循环动词表内(corpus):
    for s in corpus["signatures"]:
        assert s.get("action_class", "escalate") in onboard_loop.VALID_ACTION_CLASSES, \
            f"{s['id']}：action_class 循环执行不了"


# ---------------------------------------------------------------- 2) evidence 可查
def _repo_text_files():
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or any(x in p.parts for x in SEARCH_SKIP_DIRS):
            continue
        if p.suffix.lower() in {".py", ".md", ".json", ".cs", ".ps1", ".txt", ".tmpl"}:
            yield p


def test_evidence每条都是path或commit格式(corpus):
    for s in corpus["signatures"]:
        assert isinstance(s["evidence"], list) and s["evidence"], \
            f"{s['id']}：evidence 必须非空数组"
        for ev in s["evidence"]:
            assert EVIDENCE_RE.match(ev), f"{s['id']}：evidence 格式非法：{ev}"


def test_evidence_path文件与锚点文本都在场(corpus):
    for s in corpus["signatures"]:
        for ev in s["evidence"]:
            if not ev.startswith("path:"):
                continue
            ref = ev[len("path:"):]
            rel, _, anchor = ref.partition("#")
            target = ROOT / rel
            assert target.is_file(), f"{s['id']}：evidence 文件不存在：{rel}"
            if anchor:
                content = target.read_text(encoding="utf-8")
                assert anchor in content, \
                    f"{s['id']}：锚点文本「{anchor}」不在 {rel} 中（引用漂移）"


def test_evidence_commit散列在仓库文本可查(corpus):
    """禁 git 环境：散列必须能在仓库文本（文档/知识库/脚本）里查到，否则不可查证。"""
    assert list(_repo_text_files()), "仓库文本扫描为空（环境异常）"
    contents = {p: p.read_text(encoding="utf-8", errors="replace") for p in _repo_text_files()}
    for s in corpus["signatures"]:
        for ev in s["evidence"]:
            if not ev.startswith("commit:"):
                continue
            h = ev[len("commit:"):]
            hits = [p.relative_to(ROOT).as_posix() for p, c in contents.items() if h in c]
            assert hits, f"{s['id']}：commit 散列 {h} 在仓库任何文本中都查不到（不可查证）"


# ---------------------------------------------------------------- 3) 阳性样本命中
def test_每条签名的真实观测样本必须命中自身(corpus, signatures):
    for s in corpus["signatures"]:
        probe = s.get("probe_sample", "")
        assert probe.strip(), f"{s['id']}：缺 probe_sample（真实观测样本）"
        hit = onboard_loop.match_signature(probe, signatures)
        assert hit is not None, f"{s['id']}：probe_sample 没命中任何签名"
        assert hit.id == s["id"], \
            f"{s['id']}：probe_sample 被先序签名 {hit.id} 抢走（数组顺序/模式过宽）"


# ---------------------------------------------------------------- 4) 良性/未知零误报
def test_良性与语料外样本零误报(corpus, signatures):
    samples = corpus.get("must_not_match_samples", [])
    assert len(samples) >= 3, "must_not_match_samples 至少覆盖 PASS 行与一条语料外失败"
    for sample in samples:
        hit = onboard_loop.match_signature(sample, signatures)
        assert hit is None, f"良性/语料外样本被误归因为 {hit.id}：{sample[:60]}"


# ---------------------------------------------------------------- 5) 解释器确定性
def test_归因按语料数组顺序首中即归因(signatures, corpus):
    order = [s["id"] for s in corpus["signatures"]]
    short = order.index("SIG-P1-2-SHORT-READ")
    poison = order.index("SIG-P1-3-POISONED-CONN")
    assert short < poison, "前提：短读在毒化之前（测试自身口径）"
    text = ("IOException: FC3 从站短读：请求 5，实收 4\n"
            "InvalidOperationException: 连接已因协议/网络错误失效，请重连\n")
    hit = onboard_loop.match_signature(text, signatures)
    assert hit.id == "SIG-P1-2-SHORT-READ", "首中即归因被破坏（应取语料数组序更前者）"


def test_真实失败样本各自归因到正确签名(signatures):
    cases = {
        "IOException: FC1 响应字节数字段与帧长不符：247": "SIG-P1-1-BITBYTE-CAP-245",
        "IOException: FC3 从站短读：请求 5，实收 4（响应数量不足）": "SIG-P1-2-SHORT-READ",
        "InvalidDataException: 事务标识不匹配：发送 0x0005，收到 0x0004": "SIG-P1-3-POISONED-CONN",
        "InvalidOperationException: 连接已因协议/网络错误失效，请重连": "SIG-P1-3-POISONED-CONN",
        "InvalidDataException: RTU 帧 CRC 校验失败（响应帧：01-83-02-C1-F1）": "SIG-RTU-CRC-REJECT",
        "error CS1061: \"ModbusTcpClient\" 未包含 \"TransactRaw\" 的定义": "SIG-01-OLD-DLL-CS1061",
        "[docsync-fail] README 黄金测试数 31 != 实算 30（ModbusFrameTests.cs）": "SIG-G8-DOC-DRIFT",
    }
    for text, want in cases.items():
        hit = onboard_loop.match_signature(text, signatures)
        assert hit is not None and hit.id == want, \
            f"归因错误：{text[:40]!r} -> {hit.id if hit else None}（期望 {want}）"


def test_result行两种形态都能解析():
    lines = [
        "RESULT\tPASS\tFC3_ReadSeededRegisters\t",
        "RESULT\tFAIL\tFC1_Big\tIOException: boom",
        "RESULT\tparam=正常(15020)\tPASS\tFC6_WriteSingleRegister_ReadBack\t",
        "RESULT\tparam=分片split3(15021)\tFAIL\tFragmentSplit3\t错位",
        "STAGE\tEXECUTE\tattempt=1",
        "",
    ]
    rows = onboard_loop.parse_result_lines(lines)
    assert [(r["status"], r["name"]) for r in rows] == [
        ("PASS", "FC3_ReadSeededRegisters"),
        ("FAIL", "FC1_Big"),
        ("PASS", "FC6_WriteSingleRegister_ReadBack"),
        ("FAIL", "FragmentSplit3"),
    ], f"RESULT 行解析不符：{rows}"


# ---------------------------------------------------------------- 6) 循环脚本自身
def test_onboard_loop零第三方依赖():
    """架构原则的机器可查面：内核 import 只许标准库（零依赖纪律）。"""
    tree = ast.parse(LOOP_PY.read_text(encoding="utf-8"))
    allowed = {
        "__future__", "argparse", "json", "os", "re", "socket", "subprocess",
        "sys", "time", "pathlib",
    }
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    stray = imported - allowed
    assert not stray, f"接入循环内核引入了非白名单依赖：{sorted(stray)}"


def test_循环与门禁脚本在约定的仓库路径上():
    assert LOOP_PY.is_file()
    assert (ROOT / "scripts" / "gate_onboard.ps1").is_file()
    assert SIG_PATH.is_file()
