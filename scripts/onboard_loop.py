#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
onboard_loop.py —— harness 接入闭环第一切片：把模拟设备接进来（Modbus TCP 从站）
================================================================================

架构原则：**智能体在外、确定性内核在内。**
  - 本脚本（内核）只拥有两类决策权：①解读失败（failure_signatures.json 逐签名
    确定性匹配）②选择下一步（按命中签名的 action_class：rerun / rerun_canonical /
    escalate）。全部执行走既有门禁（run_contract.ps1 / 其 normal 阶段的沙盒复刻），
    不自创测试路径、不绕过任何门。
  - 语料库没有的失败 → 结构化上报 UNKNOWN（需人/LLM 介入）+ 完整证据包，绝不猜，
    也绝不在 UNKNOWN 上自动重试。

闭环（状态机，每步打印 STAGE / DECISION / ATTRIBUTION 行，均为 TAB 分隔、关键字段
全 ASCII 便于上层门禁断言）：
  SENSE     查 knowledge/protocols/capability_matrix.json（协议=Modbus TCP 能力在册）
  PLAN      出计划：起从站（--holding 种子）→ 跑契约门禁 → 收 RESULT/退出码 → 归因
  EXECUTE   两条既有执行路线（默认 canonical；仅当注入副本参数在场时走沙盒复刻）：
            canonical = run_contract.ps1（三阶段编排，从站由其自管，19 条契约口径）
            sandbox   = run_contract.ps1 normal 阶段的同源同参复刻（源文件可指向
                        负向测试注入的副本；从站由本脚本自起自停）
  INTERPRET 失败时逐签名匹配 failure_signatures.json → ATTRIBUTION{根因/证据/下一步}；
            无命中 → ATTRIBUTION UNKNOWN + unknown_report.json 证据包
  DECIDE    rerun → 同配置重试（有界）；rerun_canonical → 弃用漂移副本恢复模板源
            重跑；escalate/UNKNOWN → 停止，交人/LLM
  REPORT    写《接入报告》out/onboard_loop/onboard_report.md + .json；全绿出报告

退出码 = 接入成败：
  0  = 接入成功（契约全 PASS，报告含矩阵查询与契约 PASS 记录）
  20 = UNKNOWN 失败升级（语料库无匹配，需人/LLM 介入；证据包已落盘）
  21 = 已知失败但重试/恢复预算耗尽（归因报告已落盘）
  22 = 环境/用法错误（文件缺失、端口被占、矩阵无此协议等）

零第三方依赖（仅 Python 标准库）。Python 3.8+ 兼容写法。
================================================================================
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

# ---- 常量 ------------------------------------------------------------------
REPO = Path(__file__).resolve().parents[1]
MATRIX_PATH = REPO / "knowledge" / "protocols" / "capability_matrix.json"
SIGNATURES_PATH = REPO / "knowledge" / "protocols" / "failure_signatures.json"
SLAVE_PY = REPO / "tests" / "fixtures" / "modbus" / "modbus_tcp_slave.py"
TPL_DIR = REPO / "knowledge" / "templates" / "protocol"
CLIENT_CS = TPL_DIR / "ModbusTcpClient.cs"
CONTRACT_TESTS_CS = TPL_DIR / "ModbusContractTests.cs"
CONTRACT_RUNNER_CS = TPL_DIR / "ModbusContractRunner.cs"
RUN_CONTRACT_PS1 = TPL_DIR / "run_contract.ps1"

TARGET_PROTOCOL = "Modbus TCP"
TARGET_HOST = "127.0.0.1"
TARGET_PORT = 15020
TARGET_SEEDS = "0=1234,1=5678"
# canonical 路线（run_contract.ps1）占用的全部端口——预检必须全空闲
RUN_CONTRACT_PORTS = (15020, 15021, 15022, 15023)

EXIT_OK = 0
EXIT_UNKNOWN = 20
EXIT_EXHAUSTED = 21
EXIT_ENV = 22

VALID_ACTION_CLASSES = ("rerun", "rerun_canonical", "escalate")


# ---- 输出原语（状态机确定性输出；关键字段保持 ASCII）------------------------
def _one_line(text):
    """压成单行：TAB/换行折成空格，保证 STAGE/DECISION/ATTRIBUTION 行可整行解析。"""
    return re.sub(r"\s+", " ", str(text)).strip()


def emit(line):
    print(line, flush=True)


def stage(name, detail):
    emit("STAGE\t%s\t%s" % (name, _one_line(detail)))


def decision(what, because):
    emit("DECISION\t%s\t%s" % (_one_line(what), _one_line(because)))


def attribution(sig_id, root_cause, next_action, action_class, evidence):
    emit("ATTRIBUTION\t%s\troot_cause=%s\tnext_action=%s\taction_class=%s\tevidence=%s"
         % (sig_id, _one_line(root_cause), _one_line(next_action),
            action_class, _one_line(evidence)))


# ---- 语料库 ------------------------------------------------------------------
class Signature(object):
    """一条失败签名：原始条目 + 预编译正则。"""

    def __init__(self, raw):
        self.raw = raw
        self.id = raw["id"]
        self.regex = re.compile(raw["signature"])
        self.root_cause = raw["root_cause"]
        self.next_action = raw["next_action"]
        self.action_class = raw.get("action_class", "escalate")
        self.evidence = raw.get("evidence", [])
        self.gate = raw.get("gate", "")


def load_signatures(path):
    """读语料库并做最小结构校验（结构性问题=环境错误，退出码 22）。"""
    if not path.is_file():
        raise EnvironmentError("失败签名语料库不存在：%s" % path)
    with open(str(path), "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not str(data.get("schema_version", "")).startswith("failure_signatures/"):
        raise EnvironmentError("语料库 schema_version 不识别：%r" % data.get("schema_version"))
    sigs = []
    seen = set()
    for raw in data.get("signatures", []):
        if raw["id"] in seen:
            raise EnvironmentError("语料库签名 id 重复：%s" % raw["id"])
        seen.add(raw["id"])
        if raw.get("action_class", "escalate") not in VALID_ACTION_CLASSES:
            raise EnvironmentError("语料库 %s 的 action_class 非法：%r"
                                   % (raw["id"], raw.get("action_class")))
        sigs.append(Signature(raw))
    if not sigs:
        raise EnvironmentError("语料库为空：%s" % path)
    return sigs


def match_signature(text, signatures):
    """确定性归因：按语料数组顺序首个命中即返回；全不命中返回 None（绝不猜）。"""
    for sig in signatures:
        if sig.regex.search(text):
            return sig
    return None


def parse_result_lines(lines):
    """收 RESULT 行（两种形态）：
    runner 原始行：RESULT<TAB>PASS|FAIL<TAB>用例名<TAB>失败说明
    run_contract 汇总行：RESULT<TAB>param=<阶段><TAB>PASS|FAIL<TAB>用例名<TAB>…
    返回 [{status, name, detail}]，同名去重取首见。"""
    results = []
    seen = set()
    for raw in lines:
        line = raw
        for prefix in ("[out] ", "[err] "):
            if line.startswith(prefix):
                line = line[len(prefix):]
        parts = line.split("\t")
        if not parts or parts[0] != "RESULT" or len(parts) < 3:
            continue
        if parts[1] in ("PASS", "FAIL"):
            status, name = parts[1], parts[2]
            detail = parts[3] if len(parts) > 3 else ""
        elif parts[1].startswith("param=") and len(parts) >= 4:
            status, name = parts[2], parts[3]
            detail = parts[4] if len(parts) > 4 else ""
        else:
            continue
        if name in seen:
            continue
        seen.add(name)
        results.append({"status": status, "name": name, "detail": detail})
    return results


# ---- 子进程工具 ----------------------------------------------------------------
def find_csc(explicit=""):
    cands = [explicit,
             r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
             r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"]
    for c in cands:
        if c and Path(c).is_file():
            return c
    raise EnvironmentError("未找到 .NET Framework csc.exe（v4.0.30319）")


def run_process(cmd, workdir, timeout_s):
    """跑一条命令，收 (退出码, 输出行列表)；超时=杀进程按失败处理。"""
    try:
        proc = subprocess.run(cmd, cwd=str(workdir), capture_output=True,
                              timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return 124, ["(超时：%ds，进程已终止)" % timeout_s]
    except OSError as exc:
        return 127, ["(进程启动失败：%s)" % exc]
    out = proc.stdout.decode("utf-8", "replace").splitlines()
    err = proc.stderr.decode("utf-8", "replace").splitlines()
    return proc.returncode, ["[out] %s" % l for l in out] + ["[err] %s" % l for l in err]


def port_open(host, port, timeout_ms=300):
    try:
        sock = socket.create_connection((host, port), timeout=timeout_ms / 1000.0)
        sock.close()
        return True
    except OSError:
        return False


# ---- 感知：能力矩阵查询 --------------------------------------------------------
def sense_matrix():
    """查 capability_matrix.json：协议=Modbus TCP 的行必须存在且状态可接入。
    返回 (行 dict, 查询记录 dict)；不可接入返回 (None, 记录)。"""
    if not MATRIX_PATH.is_file():
        raise EnvironmentError("能力矩阵不存在：%s" % MATRIX_PATH)
    with open(str(MATRIX_PATH), "r", encoding="utf-8") as fh:
        matrix = json.load(fh)
    row = None
    for item in matrix.get("protocol_coverage", []):
        if item.get("protocol") == TARGET_PROTOCOL:
            row = item
            break
    record = {
        "file": "knowledge/protocols/capability_matrix.json",
        "query": "protocol_coverage[protocol=%s]" % TARGET_PROTOCOL,
        "found": row is not None,
        "status": row.get("status") if row else None,
        "transport": row.get("transport") if row else None,
        "knowledge_files": row.get("knowledge_files", []) if row else [],
    }
    if row is None or record["status"] not in ("ingested", "partial"):
        return None, record
    return row, record


# ---- 执行路线 1：canonical（既有门禁 run_contract.ps1，从站由其自管）------------
def execute_run_contract(args):
    for p in RUN_CONTRACT_PORTS:
        if port_open(TARGET_HOST, p):
            raise EnvironmentError(
                "端口 %d 已被占用（可能有残留从站，种子/劣化状态未知）。请先释放端口再跑。" % p)
    cmd = [args.pwsh_exe, "-NoProfile", "-File", str(RUN_CONTRACT_PS1),
           "-PythonExe", args.python_exe]
    return run_process(cmd, REPO, args.timeout_seconds)


# ---- 执行路线 2：sandbox（run_contract.ps1 normal 阶段的同源同参复刻）------------
# 仅当负向测试把源文件指向注入副本时启用；默认源=模板 → 等价 canonical 的 normal 阶段。
def execute_sandbox(args, client_cs, contract_tests_cs):
    workdir = Path(args.out_dir) / "sandbox"
    workdir.mkdir(parents=True, exist_ok=True)
    exe = workdir / "OnboardContractRunner.exe"

    # ① 编译（与 run_contract.ps1 相同的 csc 路线与源清单）
    csc = find_csc(args.csc_exe)
    compile_cmd = [csc, "/nologo", "/codepage:65001", "/target:exe", "/platform:anycpu",
                   "/out:%s" % exe, str(client_cs), str(contract_tests_cs),
                   str(CONTRACT_RUNNER_CS)]
    rc, lines = run_process(compile_cmd, workdir, min(args.timeout_seconds, 120))
    if rc != 0:
        lines.insert(0, "[compile] csc 源: %s +%s +%s" % (client_cs, contract_tests_cs,
                                                          CONTRACT_RUNNER_CS))
        return rc, lines

    # ② 起从站（--holding 种子），等端口就绪
    slave_cmd = [args.python_exe, str(SLAVE_PY), "--port", str(args.port),
                 "--holding", args.seeds]
    slave = subprocess.Popen(slave_cmd, cwd=str(REPO), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
    ready = False
    deadline = time.time() + 15
    try:
        while time.time() < deadline:
            if slave.poll() is not None:
                err = slave.stderr.read().decode("utf-8", "replace").strip()
                return 1, ["[slave] 从站进程提前退出（退出码 %s）：%s"
                           % (slave.returncode, _one_line(err or "(无 stderr)"))]
            if port_open(args.host, args.port):
                ready = True
                break
            time.sleep(0.15)
        if not ready:
            return 1, ["[slave] 从站 %s:%d 15s 内未就绪" % (args.host, args.port)]

        # ③ 跑契约 runner（normal 阶段）
        return run_process([str(exe), args.phase], workdir, args.timeout_seconds)
    finally:
        try:
            if slave.poll() is None:
                slave.terminate()
                try:
                    slave.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    slave.kill()
        except OSError:
            pass


# ---- 报告 ------------------------------------------------------------------
def write_report(path_md, path_json, ctx):
    """写《接入报告》（md 人读 + json 机器读）。newline='\n' 保证 LF。"""
    rows = "\n".join("| %d | %s | %s | %s |" %
                     (i + 1, r["name"], r["status"],
                      _one_line(r["detail"])[:160])
                     for i, r in enumerate(ctx["results"]))
    att_rows = "\n".join("| %s | %s | %s | %s |" %
                         (a["id"], _one_line(a["root_cause"])[:120],
                          _one_line(a["next_action"])[:120], a["action_class"])
                         for a in ctx["attributions"]) or "| - | 无失败，无需归因 | - | - |"
    att_section = ("## 归因记录（失败解读引擎）\n\n"
                   "| 签名 | 根因 | 下一步 | 动作类 |\n|---|---|---|---|\n%s\n" % att_rows)
    if ctx["unknown"]:
        att_section += ("\n**UNKNOWN 升级**：语料库无匹配签名，需人/LLM 介入——证据包 %s\n"
                        % ctx["unknown"]["report"])
    md = """# 模拟设备接入报告（Modbus TCP @%s:%d）

- 结论：**%s**（退出码 %d）
- 生成时间：%s
- 从站：tests/fixtures/modbus/modbus_tcp_slave.py --port %d --holding %s

## 矩阵查询（感知）

- 查询：%s
- 结果：protocol=**%s** status=**%s**（found=%s，可接入=是）
- transport：%s
- knowledge_files：%s

## 执行（既有门禁）

- 执行路线：%s
- attempts：%s

## 契约 RESULT 记录（去重 %d 条）

| # | 用例 | 结果 | 失败说明 |
|---|---|---|---|
%s

%s
## 结论

%s
""" % (ctx["host"], ctx["port"], ctx["conclusion"], ctx["exit_code"], ctx["time"],
       ctx["port"], ctx["seeds"],
       ctx["matrix"]["query"], TARGET_PROTOCOL, ctx["matrix"]["status"],
       ctx["matrix"]["found"], ctx["matrix"].get("transport") or "-", 
       ", ".join(ctx["matrix"]["knowledge_files"]) or "-",
       ctx["backend_line"], ctx["attempts_line"],
       len(ctx["results"]), rows or "| - | - | - | - |",
       att_section, ctx["conclusion_text"])
    path_md.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path_md), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(md)
    with open(str(path_json), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(ctx["json"], fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def write_unknown_report(path, ctx, failing_results, output_tail):
    """UNKNOWN 结构化证据包：给外层智能体（人/LLM）的完整输入，绝不猜。"""
    payload = {
        "schema_version": "unknown_failure/1",
        "status": "UNKNOWN",
        "instruction": "语料库（knowledge/protocols/failure_signatures.json）无匹配签名："
                       "需人/LLM 解读以下证据并决定处置；确认根因后按 evidence 纪律新增"
                       "签名条目。内核不得在 UNKNOWN 状态自动重试或猜测归因。",
        "target": {"protocol": TARGET_PROTOCOL, "host": ctx["host"], "port": ctx["port"],
                   "seeds": ctx["seeds"], "backend": ctx["backend"], "attempt": ctx["attempt"]},
        "exit_code": ctx["exit_code"],
        "failing_result_lines": ["%s\t%s\t%s" % (r["status"], r["name"], r["detail"])
                                 for r in failing_results],
        "output_tail": output_tail[-40:],
        "corpus": "knowledge/protocols/failure_signatures.json",
        "artifacts": {"full_log": ctx["log_path"], "report": ctx["report_json"]},
        "time": ctx["time"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# ---- 主闭环 ------------------------------------------------------------------
def build_parser():
    ap = argparse.ArgumentParser(
        description="harness 接入闭环第一切片：Modbus TCP 模拟从站接入（确定性内核）")
    ap.add_argument("--repo-root", default=str(REPO), help="仓库根目录")
    ap.add_argument("--python-exe", default=sys.executable, help="从站/契约脚本用 python")
    ap.add_argument("--pwsh-exe", default="pwsh", help="canonical 路线调 run_contract.ps1 用")
    ap.add_argument("--csc-exe", default="", help="指定 csc.exe（默认自动找 Framework v4.0.30319）")
    ap.add_argument("--host", default=TARGET_HOST)
    ap.add_argument("--port", type=int, default=TARGET_PORT)
    ap.add_argument("--seeds", default=TARGET_SEEDS, help="从站 --holding 种子")
    ap.add_argument("--phase", default="normal", choices=["normal"],
                    help="沙盒路线契约阶段（canonical 跑 run_contract 三阶段全量）")
    ap.add_argument("--max-attempts", type=int, default=2, help="总执行次数上限（含恢复重跑）")
    ap.add_argument("--timeout-seconds", type=int, default=240, help="单次执行预算")
    ap.add_argument("--client-cs", default="",
                    help="客户端源覆盖（负向注入副本路径；默认=模板 → canonical 路线）")
    ap.add_argument("--contract-tests-cs", default="",
                    help="契约测试源覆盖（负向注入副本路径；默认=模板）")
    ap.add_argument("--out-dir", default=str(REPO / "out" / "onboard_loop"),
                    help="报告/日志输出目录")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    t0 = time.time()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 源覆盖路径必须先解析为绝对路径（csc 的工作目录是沙盒目录，相对路径会 CS2001），
    # 且指向不存在的文件属用法错误（exit 22），不得让它伪装成语料库外失败去触发 UNKNOWN。
    try:
        client_cs = Path(args.client_cs).resolve() if args.client_cs else CLIENT_CS
        contract_cs = Path(args.contract_tests_cs).resolve() if args.contract_tests_cs \
            else CONTRACT_TESTS_CS
        for label, p in (("client-cs", client_cs), ("contract-tests-cs", contract_cs)):
            if not p.is_file():
                raise EnvironmentError("%s 指定的源文件不存在：%s" % (label, p))
    except EnvironmentError as exc:
        decision("ABORT", "环境错误：%s" % exc)
        return EXIT_ENV

    signatures = load_signatures(SIGNATURES_PATH)

    # ---- SENSE：矩阵查询 ------------------------------------------------------
    stage("SENSE", "查询 %s 的 %s" % (MATRIX_PATH.name,
                                      "protocol_coverage[protocol=%s]" % TARGET_PROTOCOL))
    try:
        row, matrix_record = sense_matrix()
    except EnvironmentError as exc:
        decision("ABORT", "环境错误：%s" % exc)
        return EXIT_ENV
    if row is None:
        decision("ABORT", "矩阵查询失败：Modbus TCP 不在册或状态不可接入（status=%r）——"
                          "不猜，先补知识库" % matrix_record["status"])
        return EXIT_ENV
    stage("SENSE", "矩阵命中：Modbus TCP status=%s knowledge_files=%d 项"
         % (matrix_record["status"], len(matrix_record["knowledge_files"])))

    # ---- PLAN ------------------------------------------------------------------
    canonical = not (args.client_cs or args.contract_tests_cs)
    plan = ("①起从站 tests/fixtures/modbus/modbus_tcp_slave.py --port %d --holding %s "
            "②跑契约门禁（backend=%s）③收 RESULT/退出码 ④失败按 failure_signatures.json "
            "（%d 条签名）归因；未知→UNKNOWN 升级，绝不猜"
            % (args.port, args.seeds,
               "run_contract.ps1" if canonical else "sandbox(normal 阶段同源复刻)",
               len(signatures)))
    stage("PLAN", plan)
    decision("PLAN", "预算：max_attempts=%d timeout=%ds" % (args.max_attempts,
                                                            args.timeout_seconds))

    ctx = {
        "host": args.host, "port": args.port, "seeds": args.seeds,
        "matrix": matrix_record, "results": [], "attributions": [], "unknown": None,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "attempt": 0, "backend": "", "exit_code": EXIT_OK, "log_path": "", "report_json": "",
        "backend_line": "-", "attempts_line": "-",
    }

    # ---- EXECUTE / INTERPRET / DECIDE -------------------------------------------
    attempt = 0
    while True:
        attempt += 1
        ctx["attempt"] = attempt
        backend = "run_contract" if (client_cs == CLIENT_CS and contract_cs == CONTRACT_TESTS_CS) \
            else "sandbox"
        ctx["backend"] = backend
        log_path = out_dir / ("attempt%d_%s.log" % (attempt, backend))
        ctx["log_path"] = str(log_path)
        stage("EXECUTE", "attempt=%d/%d backend=%s client_cs=%s contract_cs=%s"
             % (attempt, args.max_attempts, backend, client_cs.name, contract_cs.name))
        try:
            if backend == "run_contract":
                rc, lines = execute_run_contract(args)
            else:
                rc, lines = execute_sandbox(args, client_cs, contract_cs)
        except EnvironmentError as exc:
            decision("ABORT", "环境错误：%s" % exc)
            return EXIT_ENV

        with open(str(log_path), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")

        results = parse_result_lines(lines)
        fails = [r for r in results if r["status"] == "FAIL"]
        stage("INTERPRET", "退出码=%d RESULT=%d 条（FAIL %d）；候选签名 %d 条按序匹配"
             % (rc, len(results), len(fails), len(signatures)))

        if rc == 0 and results and not fails:
            ctx["results"] = results
            attribution("NONE", "无失败，无需归因", "-", "-", "-")
            decision("PASS", "契约 %d/%d PASS（attempt=%d backend=%s）"
                     % (len(results), len(results), attempt, backend))
            break

        evidence_text = "\n".join(lines)
        failing_text = "\n".join("RESULT\t%s\t%s\t%s" % (r["status"], r["name"], r["detail"])
                                 for r in fails)
        sig = match_signature(failing_text + "\n" + evidence_text, signatures)
        if sig is None:
            # ---- UNKNOWN：语料库外失败 → 结构化升级，绝不猜、绝不重试 ----------------
            unknown_path = out_dir / "unknown_report.json"
            write_unknown_report(unknown_path,
                                 dict(ctx, exit_code=rc),
                                 fails or [{"status": "FAIL", "name": "(无 RESULT 行)",
                                            "detail": "退出码 %d，无 RESULT 解析结果" % rc}],
                                 lines)
            attribution("UNKNOWN", "语料库无匹配签名（%d 条全不命中）" % len(signatures),
                        "需人/LLM 介入：解读 %s 证据包；确认根因后按 evidence 纪律新增签名"
                        % unknown_path.name, "escalate", str(unknown_path))
            decision("ESCALATE", "UNKNOWN：不猜、不重试；退出码 %d" % EXIT_UNKNOWN)
            ctx["unknown"] = {"report": str(unknown_path)}
            ctx["results"] = results
            ctx["exit_code"] = EXIT_UNKNOWN
            ctx["conclusion"] = "接入失败（UNKNOWN 升级，需人/LLM 介入）"
            ctx["conclusion_text"] = ("语料库外失败：已按「绝不猜」原则结构化上报。"
                                      "证据包：%s" % unknown_path)
            ctx["json"] = {"schema_version": "onboard_report/1", "conclusion": "FAILED_UNKNOWN",
                           "exit_code": EXIT_UNKNOWN, "attempt": attempt, "backend": backend,
                           "matrix_query": matrix_record, "results": results,
                           "attributions": [], "unknown": ctx["unknown"]}
            write_report(out_dir / "onboard_report.md", out_dir / "onboard_report.json", ctx)
            stage("REPORT", "报告 %s（结论=UNKNOWN 升级）" % (out_dir / "onboard_report.md"))
            return EXIT_UNKNOWN

        # ---- 已知签名：确定性归因 + 按 action_class 决策 ---------------------------
        attribution(sig.id, sig.root_cause, sig.next_action, sig.action_class,
                    "; ".join(sig.evidence))
        ctx["attributions"].append({
            "id": sig.id, "root_cause": sig.root_cause, "next_action": sig.next_action,
            "action_class": sig.action_class, "evidence": sig.evidence,
            "attempt": attempt, "backend": backend, "exit_code": rc,
            "failing": ["%s: %s" % (r["name"], r["detail"]) for r in fails],
        })
        ctx["results"] = results if results else ctx["results"]

        if attempt >= args.max_attempts:
            decision("EXHAUSTED", "预算耗尽（attempt=%d/%d）仍失败；归因=%s"
                     % (attempt, args.max_attempts, sig.id))
            ctx["exit_code"] = EXIT_EXHAUSTED
            ctx["conclusion"] = "接入失败（已知缺陷归因后预算耗尽）"
            ctx["conclusion_text"] = ("签名 %s（%s）已确定性归因，但 %d 次执行内未转绿。"
                                      "下一步（来自语料库）：%s"
                                      % (sig.id, sig.gate, attempt, sig.next_action))
            ctx["json"] = {"schema_version": "onboard_report/1", "conclusion": "FAILED_EXHAUSTED",
                           "exit_code": EXIT_EXHAUSTED, "attempt": attempt,
                           "matrix_query": matrix_record, "results": results,
                           "attributions": ctx["attributions"], "unknown": None}
            write_report(out_dir / "onboard_report.md", out_dir / "onboard_report.json", ctx)
            stage("REPORT", "报告 %s（结论=失败，归因在案）" % (out_dir / "onboard_report.md"))
            return EXIT_EXHAUSTED

        if sig.action_class == "rerun":
            decision("RERUN", "按 %s.next_action 同配置重试（attempt=%d/%d）"
                     % (sig.id, attempt + 1, args.max_attempts))
        elif sig.action_class == "rerun_canonical":
            if backend == "run_contract":
                decision("EXHAUSTED", "%s 要求恢复模板源，但当前已是 canonical 路线——"
                          "需人工修模板源，内核不越权改源码" % sig.id)
                ctx["exit_code"] = EXIT_EXHAUSTED
                ctx["conclusion"] = "接入失败（canonical 源本身带缺陷，需人工修复）"
                ctx["conclusion_text"] = ("签名 %s 命中且当前已运行在模板源上：修复动作在"
                                          "源码本身（%s），内核不越权。" % (sig.id, sig.next_action))
                ctx["json"] = {"schema_version": "onboard_report/1",
                               "conclusion": "FAILED_EXHAUSTED", "exit_code": EXIT_EXHAUSTED,
                               "attempt": attempt, "matrix_query": matrix_record,
                               "results": results, "attributions": ctx["attributions"],
                               "unknown": None}
                write_report(out_dir / "onboard_report.md", out_dir / "onboard_report.json", ctx)
                stage("REPORT", "报告 %s" % (out_dir / "onboard_report.md"))
                return EXIT_EXHAUSTED
            client_cs, contract_cs = CLIENT_CS, CONTRACT_TESTS_CS
            decision("RERUN_CANONICAL", "弃用漂移副本，恢复模板源后重跑既有门禁"
                                        "（attempt=%d/%d）" % (attempt + 1, args.max_attempts))
        else:
            decision("ESCALATE", "%s.action_class=escalate：停止自动行动，交人/LLM" % sig.id)
            ctx["exit_code"] = EXIT_EXHAUSTED
            ctx["conclusion"] = "接入失败（已知签名要求人工处置）"
            ctx["conclusion_text"] = "签名 %s 要求 escalate：%s" % (sig.id, sig.next_action)
            ctx["json"] = {"schema_version": "onboard_report/1", "conclusion": "FAILED_ESCALATE",
                           "exit_code": EXIT_EXHAUSTED, "attempt": attempt,
                           "matrix_query": matrix_record, "results": results,
                           "attributions": ctx["attributions"], "unknown": None}
            write_report(out_dir / "onboard_report.md", out_dir / "onboard_report.json", ctx)
            stage("REPORT", "报告 %s" % (out_dir / "onboard_report.md"))
            return EXIT_EXHAUSTED

    # ---- REPORT：全绿出《接入报告》------------------------------------------------
    ctx["exit_code"] = EXIT_OK
    ctx["conclusion"] = "接入成功"
    ctx["conclusion_text"] = ("契约 %d 条全 PASS；矩阵查询与契约 PASS 记录均在案。%s"
                              % (len(ctx["results"]),
                                 "恢复动作已执行（归因见上表）。" if ctx["attributions"] else ""))
    ctx["backend_line"] = "%s（日志 %s）" % (ctx["backend"], ctx["log_path"])
    ctx["attempts_line"] = "%d 次（归因 %d 次：%s）" % (
        attempt, len(ctx["attributions"]),
        ", ".join(a["id"] for a in ctx["attributions"]) or "无")
    ctx["json"] = {"schema_version": "onboard_report/1", "conclusion": "ONBOARDED",
                   "exit_code": EXIT_OK, "attempt": attempt, "backend": ctx["backend"],
                   "matrix_query": matrix_record, "results": ctx["results"],
                   "attributions": ctx["attributions"], "unknown": None}
    write_report(out_dir / "onboard_report.md", out_dir / "onboard_report.json", ctx)
    stage("REPORT", "《接入报告》%s" % (out_dir / "onboard_report.md"))
    decision("ONBOARDED", "接入成功：exit=0（用时 %.1fs）" % (time.time() - t0))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
