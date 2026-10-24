#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lemay_corpus.py —— Lemay CSET16 真机测试床 Modbus 数据 → comm_log/1 → 检出 → 判卷
（真实分布首测，2026-10-21。零第三方依赖：Python 标准库 only，无 tshark。）

数据集（out/_corpus_pcaps/，不入库；缺失 → 门禁 SKIP）：
  Lemay et al. CSET'16「Modbus_dataset」真机测试床抓包。关键结构：每个 pcap 配一份
  「预转录带标签 CSV」，但该 CSV **只有两列**（packet_index;label，0|1）——它是逐包
  攻击窗口标注（第 N 行 ↔ pcap 第 N 个包，已实测逐一对齐），不含时间/源目/功能码。
  因此时间与协议字段取自 pcap 本身（纯 stdlib struct 解析 classic pcap），CSV 提供
  每包真值标签，两者按包序号逐一对齐后映射成 comm_log/1。列语义与逐字段依据见
  knowledge/protocols/pcap_mapping.json。

管线（单遍线性，无全局排序/bisect——上一路废稿死于过度架构，本版刻意保持简单）：
  1) classic pcap 读取（4 种 magic：大小端 × µs/ns）→ Ethernet/IPv4/TCP；
  2) 每条双向 TCP 流一个**顺序携带缓冲**：追加载荷后贪心解析完整 MBAP+PDU；
     粘包（一段多 PDU）与拆包（PDU 跨段）同一路径处理，无重组排序；
  3) 映射 comm_log/1（契约 knowledge/contracts/comm_log_contract.json，
     scripts/validate_comm_log.py 是唯一裁判）：时间戳←包时间戳(UTC)、seq←包序号、
     direction←端口（源 502=resp 否则 req）、unit_id/function_code/exception_code←PDU、
     device.host_or_port←从站端点(ip:502)；CSV label 透传为扩展字段；
  4) 检出：src/mcopilot/agents/forensics_comm.py 原样消费（只读，不加规则）；
  5) 判卷（窗口口径）：自然段误报率 = 标签 0 帧上的检出占比（**只报告不设阈值**，
     首测无基线）；攻击段窗口覆盖率 = 检出证据行覆盖到的标签 1 帧占比；
     label 1 全在非 502 端口的主机层场景（CnC/exploit/moving）如实报「Modbus 面
     零攻击帧、协议层工具天然不可见」，不硬凑规则。

门禁与夹具（--gate-fixtures / --gate-full，由 scripts/gate_corpus.ps1 域 21 编排）：
  · 夹具：knowledge/protocols/pcap_samples/lemay_sample.{pcap,csv}（polling_only
    前 30 包原字节截取）+ lemay_sample_expected.json（期望映射，逐行断言）；
  · 负向 N：对夹具映射副本注入一条非法记录（unit_id 越域 / seq 回退 / 日历不存在
    时间戳，三重断言）+ 阳性对照（原副本必须 0 违规）→ 契约门必须 FAIL。

诚实边界：标签是「攻击窗口」二元标注，不是协议级 cause 真值；检出的协议归因
（exception_storm 等）对不上 cause 级真值，判卷只做窗口口径，不装能评 cause。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "out" / "_corpus_pcaps"
SAMPLE_DIR = ROOT / "knowledge" / "protocols" / "pcap_samples"
OUT_DIR = ROOT / "out" / "corpus_lemay"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# 核心六段：自然段 1 + 攻击段 5（含 characterization——唯一 Modbus 面可见攻击，
# 给检出引擎一个非零召回的正对照；其余三段是主机层攻击的诚实边界样本）。
SEGMENTS = [
    ("natural_polling_only", "Modbus_polling_only_6RTU_labeled.csv",
     "Modbus_polling_only_6RTU(2).pcap", "自然轮询（6 从站纯 FC1/2/3 读）"),
    ("attack_fake_command", "send_a_fake_command_modbus_6RTU_with_operate_labeled.csv",
     "send_a_fake_command_modbus_6RTU_with_operate.pcap", "伪造命令（未授权主机 FC5 写）"),
    ("attack_cnc_uploading", "CnC_uploading_exe_modbus_6RTU_with_operate_labeled.csv",
     "CnC_uploading_exe_modbus_6RTU_with_operate.pcap", "CnC 反连上传 exe（4444/139 端口）"),
    ("attack_exploit_ms08", "exploit_ms08_netapi_modbus_6RTU_with_operate_labeled.csv",
     "exploit_ms08_netapi_modbus_6RTU_with_operate.pcap", "ms08 netapi 溢出（445/4444 端口）"),
    ("attack_moving_two_files", "moving_two_files_modbus_6RTU_labeled.csv",
     "moving_two_files_modbus_6RTU.pcap", "SMB 挪文件（139 等端口）"),
    ("attack_characterization", "characterization_modbus_6RTU_with_operate_labeled.csv",
     "characterization_modbus_6RTU_with_operate.pcap", "探测画像（读越界地址→异常响应风暴）"),
]
FIXTURE_ROWS = 30  # 夹具截取的包数（≥20 行要求）

WRITE_FCS = frozenset({5, 6, 15, 16})  # 任务口径：功能码 5/6/15/16=写，1-4=读


# ---------------------------------------------------------------- 数据读取
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_labels(path: Path) -> list[int]:
    """读「packet_index;label」逐包标注 CSV → 标签列表（0|1，行序=包序-1）。

    数据集事实（实测）：整文件无表头、恒两列、首列 1..N 连续。列数/取值域不符
    即抛错——标注文件与 pcap 的对齐是本映射的根契约，宁可拒载不可错位。
    """
    labels: list[int] = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for no, row in enumerate(csv.reader(fh, delimiter=";"), 1):
            if not row:
                continue
            if len(row) != 2:
                raise ValueError(f"{path.name}:L{no}: 应为 2 列（index;label），实得 {len(row)} 列")
            if int(row[0]) != no:
                raise ValueError(f"{path.name}:L{no}: 包序号不连续（期望 {no}，实得 {row[0]!r}）")
            lab = int(row[1])
            if lab not in (0, 1):
                raise ValueError(f"{path.name}:L{no}: label 只允许 0|1，实得 {lab}")
            labels.append(lab)
    if not labels:
        raise ValueError(f"{path.name}: 标注 CSV 为空")
    return labels


_PCAP_MAGICS = {
    b"\xd4\xc3\xb2\xa1": ("<", 1e-6),   # 小端 µs（本数据集全部命中此格式）
    b"\xa1\xb2\xc3\xd4": (">", 1e-6),   # 大端 µs
    b"\x4d\x3c\xb2\xa1": ("<", 1e-9),   # 小端 ns（纳秒变体，留兼容）
    b"\xa1\xb2\x3c\x4d": (">", 1e-9),   # 大端 ns
}


def iter_pcap(path: Path):
    """classic pcap 逐包产出 (index_1based, ts_seconds_float, raw_bytes)。

    只支持 classic pcap（本数据集全部是）；pcapng/其他 magic 抛错拒载。
    """
    with open(path, "rb") as fh:
        gh = fh.read(24)
        if len(gh) < 24 or gh[:4] not in _PCAP_MAGICS:
            raise ValueError(f"{path.name}: 不是 classic pcap（magic {gh[:4].hex()}）")
        endian, res = _PCAP_MAGICS[gh[:4]]
        linktype = struct.unpack(endian + "I", gh[20:24])[0]
        if linktype != 1:  # EN10MB
            raise ValueError(f"{path.name}: 链路层类型 {linktype} 非 Ethernet，本映射只认 EN10MB")
        n = 0
        while True:
            ph = fh.read(16)
            if not ph:
                return
            if len(ph) < 16:
                raise ValueError(f"{path.name}: 包头截断")
            ts_sec, ts_frac, incl, _orig = struct.unpack(endian + "IIII", ph)
            data = fh.read(incl)
            if len(data) < incl:
                raise ValueError(f"{path.name}: 第 {n + 1} 包数据截断")
            n += 1
            yield n, ts_sec + ts_frac * res, data


# ---------------------------------------------------------------- 帧解析（单遍线性）
class _StreamBuf:
    """一条双向 TCP 流的顺序携带缓冲：追加载荷、贪心吐完整 PDU。

    start_pkt = 缓冲头字节所属的包号——粘包时同段多个 PDU 都记该段包号，
    拆包时 PDU 记它**起始**包的包号（标签按起始包归属，与「攻击从哪帧开始」
    的直觉一致）。流关闭仍吐不出完整 PDU 的残字节 → 计入 malformed 统计。
    """

    __slots__ = ("buf", "start_pkt")

    def __init__(self) -> None:
        self.buf = bytearray()
        self.start_pkt = 0


def parse_frames(pcap_path: Path):
    """单遍扫描 pcap → (frames, stats)。

    frames：Modbus/TCP 帧字典列表（保序）；stats：包构成计数（诚实报告用）。
    非 Modbus 包（握手/ARP/SMB/UDP…）照占包序号但不产出帧——标签对齐不受影响。
    残字节/头非法等解析不了的字节如实计数（malformed_leftovers），不硬映射成
    comm_log 行——契约必填字段填不出来时不造数据。
    """
    frames: list[dict] = []
    stats = {"packets": 0, "arp_other_ethertype": 0, "ipv6": 0, "non_tcp_ip": 0,
             "tcp_no_payload": 0, "tcp_other_port": 0, "modbus_pdus": 0,
             "streams": 0, "malformed_leftovers": 0}
    streams: dict[tuple, _StreamBuf] = {}

    def emit(sb: _StreamBuf, ts: float, src: str, dst: str, sport: int, dport: int,
             uid, fc, exc, tid, raw: bytes) -> None:
        direction = "resp" if sport == 502 else "req"
        slave = dst if direction == "req" else src
        client = f"{src}:{sport}" if direction == "req" else f"{dst}:{dport}"
        frames.append({"pcap_index": sb.start_pkt, "ts": ts, "slave": f"{slave}:502",
                       "client": client, "direction": direction, "unit_id": uid,
                       "function_code": fc, "exception_code": exc, "tid": tid,
                       "raw": raw})

    for idx, ts, data in iter_pcap(pcap_path):
        stats["packets"] += 1
        if len(data) < 14:
            continue
        ethertype = struct.unpack(">H", data[12:14])[0]
        if ethertype == 0x86DD:
            stats["ipv6"] += 1
            continue
        if ethertype != 0x0800:
            stats["arp_other_ethertype"] += 1
            continue
        ihl = (data[14] & 0x0F) * 4
        if len(data) < 14 + ihl + 20:
            continue
        if data[23] != 6:  # 非 TCP（UDP/ICMP…）
            stats["non_tcp_ip"] += 1
            continue
        o = 14 + ihl
        sport, dport = struct.unpack(">HH", data[o:o + 4])
        src = ".".join(str(b) for b in data[26:30])
        dst = ".".join(str(b) for b in data[30:34])
        doff = (data[o + 12] >> 4) * 4
        payload = data[o + doff:]
        if not payload:
            stats["tcp_no_payload"] += 1
            continue
        if 502 not in (sport, dport):
            stats["tcp_other_port"] += 1
            continue

        # 双向流键：排序四元组（client:port 与 slave:502 不分方向，只求同流同桶）
        key = tuple(sorted([(src, sport), (dst, dport)]))
        sb = streams.get(key)
        if sb is None:
            sb = streams[key] = _StreamBuf()
            stats["streams"] += 1
        if not sb.buf:
            sb.start_pkt = idx
        sb.buf += payload

        # 贪心吐完整 PDU（MBAP 7B：tid(2)/pid(2)/len(2)/uid(1)；PDU=len-1 B，自 FC 起）
        while len(sb.buf) >= 7:
            tid, pid, plen, uid = struct.unpack(">HHHB", sb.buf[:7])
            if pid != 0 or plen < 2:
                # MBAP 头本身非法：残局如实记账，不猜边界不硬映射
                sb.buf.clear()
                stats["malformed_leftovers"] += 1
                break
            total = 6 + plen  # len 域 = uid(1B) + PDU，不含 MBAP 前 6 字节
            if len(sb.buf) < total:
                break  # 拆包：等下一段补齐（顺序到达假设，见模块边界说明）
            pdu = bytes(sb.buf[7:total])  # PDU 从第 8 字节起（FC 起始），uid 已在头里解出
            del sb.buf[:total]
            fc = pdu[0]
            exc = None
            base = fc
            if fc & 0x80:
                base = fc & 0x7F
                exc = pdu[1] if len(pdu) > 1 else None
            direction = "resp" if sport == 502 else "req"
            if exc is not None and direction != "resp":
                # 异常码只可能从从站回来（I3）；请求向出现 FC|0x80 属未知形态，不映射
                stats["malformed_leftovers"] += 1
            else:
                emit(sb, ts, src, dst, sport, dport, uid, base, exc, tid, pdu[:32])
                stats["modbus_pdus"] += 1

    # 流尾残字节（承诺长度没凑齐的半个 PDU）→ 如实计数
    for sb in streams.values():
        if sb.buf:
            stats["malformed_leftovers"] += 1
    return frames, stats


# ---------------------------------------------------------------- 映射 comm_log/1
def ts_iso(ts: float) -> str:
    """pcap 秒时间戳 → ISO8601 UTC（微秒精度，Z 结尾，契约 1-6 位小数口径）。"""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond:06d}Z"


def map_records(frames: list[dict], labels: list[int], source: str) -> list[dict]:
    """帧+逐包标签 → comm_log/1 记录（保序，行号=记录序=非空行序号）。

    label 按帧的起始包号对齐透传（扩展字段）；seq 用全局包序号——任何流内都
    严格递增，I1 自动满足且可回查到原始包。
    """
    need = max((f["pcap_index"] for f in frames), default=0)
    if len(labels) < need:
        raise ValueError("标注行数少于 pcap 包数——对齐根契约破坏，拒映射")
    records: list[dict] = []
    for f in frames:
        rec: dict = {
            "schema": "comm_log/1",
            "timestamp_utc": ts_iso(f["ts"]),
            "seq": f["pcap_index"],
            "channel": "tcp",
            "direction": f["direction"],
            "unit_id": f["unit_id"],
            "function_code": f["function_code"],
            "device": {"host_or_port": f["slave"]},
            # ---- 扩展字段（契约允许额外字段；标签透传 + 可回查性）----
            "label": labels[f["pcap_index"] - 1],
            "pcap_index": f["pcap_index"],
            "client": f["client"],
            "source": source,
        }
        if f["exception_code"] is not None:
            rec["exception_code"] = f["exception_code"]
            rec["frame_hex"] = f["raw"].hex()  # 异常帧契约建议携带原始字节
        records.append(rec)
    return records


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 复用仓库裁判与检出引擎
def _load_script(name: str):
    for anc in Path(__file__).resolve().parents:
        cand = anc / "scripts" / name
        if cand.is_file():
            if str(anc / "scripts") not in sys.path:
                sys.path.insert(0, str(anc / "scripts"))
            return __import__(name[:-3])
    raise RuntimeError(f"找不到 scripts/{name}")


def _load_detector():
    for anc in Path(__file__).resolve().parents:
        cand = anc / "src" / "mcopilot" / "agents" / "forensics_comm.py"
        if cand.is_file():
            if str(anc / "src" / "mcopilot" / "agents") not in sys.path:
                sys.path.insert(0, str(anc / "src" / "mcopilot" / "agents"))
            import forensics_comm  # noqa: E402
            return forensics_comm
    raise RuntimeError("找不到 src/mcopilot/agents/forensics_comm.py")


def contract_validate(records: list[dict]) -> list[str]:
    """契约门（唯一裁判 scripts/validate_comm_log.py）→ 违规摘要列表。"""
    vcl = _load_script("validate_comm_log.py")
    contract = vcl.load_contract(None)
    violations, _adv = vcl.validate_records(records, contract)
    return violations


# ---------------------------------------------------------------- 判卷（窗口口径）
def judge_segment(name: str, desc: str, records: list[dict], stats: dict,
                  detections: list[dict]) -> dict:
    """窗口口径判卷：自然段=误报率；攻击段=窗口覆盖率+窗口内外检出分布。

    检出的证据行号即 comm_log 行号（forensics_comm 口径），行号→记录→label。
    """
    lab_by_line = {i: r["label"] for i, r in enumerate(records, 1)}
    label1_lines = {i for i, lab in lab_by_line.items() if lab == 1}
    label0_lines = set(lab_by_line) - label1_lines

    def det_in_window(d: dict) -> bool:
        return any(no in label1_lines for no in d.get("evidence", []))

    in_window = [d for d in detections if det_in_window(d)]
    only_out = [d for d in detections if not det_in_window(d)]
    covered = {no for d in in_window for no in d.get("evidence", [])
               if no in label1_lines}
    writes = [r for r in records if r.get("function_code") in WRITE_FCS]
    return {
        "segment": name, "desc": desc,
        "packets": stats["packets"], "modbus_pdus": stats["modbus_pdus"],
        "comm_log_lines": len(records),
        "packet_kinds": {k: v for k, v in sorted(stats.items()) if k != "packets"},
        "label1_packets": len({r["pcap_index"] for r in records if r["label"] == 1}),
        "label1_frames": len(label1_lines), "label0_frames": len(label0_lines),
        "write_frames": len(writes),
        "detections_total": len(detections),
        "detections_by_cause": dict(sorted(
            (c, sum(1 for d in detections if d["cause"] == c))
            for c in {d["cause"] for d in detections})),
        "detections_in_window": len(in_window),
        "detections_outside_window": len(only_out),
        "window_covered_frames": len(covered),
        "window_coverage": (len(covered) / len(label1_lines)) if label1_lines else None,
        "fpr_on_label0": (len(only_out) / len(label0_lines)) if label0_lines else None,
    }


def run_segment(name: str, desc: str, csv_name: str, pcap_name: str, out_dir: Path):
    """映射 → 契约门 → 检出 → 窗口判卷，落盘产物并返回 (判定, 记录, 违规)。"""
    labels = read_labels(DATA_DIR / csv_name)
    frames, stats = parse_frames(DATA_DIR / pcap_name)
    if stats["packets"] != len(labels):
        raise ValueError(f"{name}: pcap 包数 {stats['packets']} ≠ 标注行数 {len(labels)}（对齐破坏）")
    records = map_records(frames, labels, f"lemay/{pcap_name}")
    violations = contract_validate(records)
    if violations:
        return None, records, violations
    write_jsonl(out_dir / f"{name}.comm_log.jsonl", records)
    detections = _load_detector().detect_entries(records)
    write_jsonl(out_dir / f"{name}.detections.jsonl", detections)
    return judge_segment(name, desc, records, stats, detections), records, []


# ---------------------------------------------------------------- 夹具
def make_fixtures() -> int:
    """从 polling_only 前 FIXTURE_ROWS 包截原字节 → 三件入库夹具。"""
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    seg_csv, seg_pcap = SEGMENTS[0][1], SEGMENTS[0][2]
    labels = read_labels(DATA_DIR / seg_csv)

    src = (DATA_DIR / seg_pcap).read_bytes()
    gh, pos, packets = src[:24], 24, []
    while pos + 16 <= len(src) and len(packets) < FIXTURE_ROWS:
        incl = struct.unpack("<I", src[pos + 8:pos + 12])[0]
        packets.append(src[pos:pos + 16 + incl])
        pos += 16 + incl
    (SAMPLE_DIR / "lemay_sample.pcap").write_bytes(gh + b"".join(packets))
    with open(SAMPLE_DIR / "lemay_sample.csv", "w", encoding="utf-8", newline="") as fh:
        for i, lab in enumerate(labels[:FIXTURE_ROWS], 1):
            fh.write(f"{i};{lab}\n")

    frames, stats = parse_frames(SAMPLE_DIR / "lemay_sample.pcap")
    records = map_records(frames, labels[:FIXTURE_ROWS], f"lemay/{seg_pcap}")
    lines = [{"line": i, "pcap_index": r["pcap_index"], "timestamp_utc": r["timestamp_utc"],
              "direction": r["direction"], "unit_id": r["unit_id"],
              "function_code": r["function_code"],
              "device": r["device"]["host_or_port"], "client": r["client"],
              "label": r["label"]} for i, r in enumerate(records, 1)]
    expected = {
        "meta": {
            "fixture": "lemay_sample",
            "source_csv": seg_csv, "source_csv_sha256": sha256(DATA_DIR / seg_csv),
            "source_pcap": seg_pcap, "source_pcap_sha256": sha256(DATA_DIR / seg_pcap),
            "rows": FIXTURE_ROWS, "generated": "2026-10-21",
            "note": "polling_only 前 30 包原字节截取；期望映射由 --make-fixtures 一次生成、"
                    "人工核对后入库，门禁逐行断言（更新夹具须走 make 并复核 diff）",
        },
        "packets_total": stats["packets"], "frames_total": len(records),
        "lines": lines,
    }
    (SAMPLE_DIR / "lemay_sample_expected.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")  # 仓库纪律：源码/JSON 文件 LF（test_repo_encoding）
    print(f"FIXTURE\t写 lemay_sample.pcap({len(packets)}包) + lemay_sample.csv({FIXTURE_ROWS}行)"
          f" + lemay_sample_expected.json({len(records)}帧)")
    for ln in lines[:3]:
        print("  sample L%d: pkt#%d %s %s fc=%s uid=%s dev=%s label=%s"
              % (ln["line"], ln["pcap_index"], ln["timestamp_utc"], ln["direction"],
                 ln["function_code"], ln["unit_id"], ln["device"], ln["label"]))
    return 0


def gate_fixtures() -> int:
    """夹具门：映射复现 → 契约门阳性对照 → 逐行断言 → 负向三重断言。"""
    exp = json.loads((SAMPLE_DIR / "lemay_sample_expected.json").read_text(encoding="utf-8"))
    labels = read_labels(SAMPLE_DIR / "lemay_sample.csv")
    frames, stats = parse_frames(SAMPLE_DIR / "lemay_sample.pcap")

    # 阳性对照：夹具映射必须 0 违规过契约门（唯一裁判 validate_comm_log）
    records = map_records(frames, labels, "lemay/fixture")
    violations = contract_validate(records)
    print(f"CORPUS\t{'PASS' if not violations else 'FAIL'}\t夹具契约门\t"
          f"{len(records)} 帧期望 0 违规，实得 {len(violations)}"
          + ("；".join(violations[:3]) if violations else ""))
    if violations:
        return 1

    # 逐行断言：映射输出 == 期望 JSON（字段级）
    lines = exp["lines"]
    mismatch: list[str] = []
    if len(records) != exp["frames_total"] or stats["packets"] != exp["packets_total"]:
        mismatch.append(f"行数不匹配（帧 {len(records)}≠{exp['frames_total']} 或包 "
                        f"{stats['packets']}≠{exp['packets_total']}）")
    for rec, want in zip(records, lines):
        got = {"line": want["line"], "pcap_index": rec["pcap_index"],
               "timestamp_utc": rec["timestamp_utc"], "direction": rec["direction"],
               "unit_id": rec["unit_id"], "function_code": rec["function_code"],
               "device": rec["device"]["host_or_port"], "client": rec["client"],
               "label": rec["label"]}
        if got != want:
            mismatch.append(f"L{want['line']}: {got} != {want}")
    print(f"CORPUS\t{'PASS' if not mismatch else 'FAIL'}\t夹具逐行断言\t"
          f"{len(lines)} 行字段级比对，不一致 {len(mismatch)}"
          + ("；".join(mismatch[:2]) if mismatch else ""))
    if mismatch:
        return 1

    # 负向 N（三重断言）：注入非法记录的副本 → 契约门必须 FAIL
    def mutate(fn):
        bad = json.loads(json.dumps(records))
        fn(bad)
        return contract_validate(bad)

    fails = 0
    negatives = [
        ("unit_id越域300", lambda bad: bad[0].__setitem__("unit_id", 300)),
        ("seq回退I1", lambda bad: bad[1].__setitem__("seq", bad[0]["seq"])),
        ("2月30日I6", lambda bad: bad[0].__setitem__("timestamp_utc", "2026-02-30T00:00:00.000000Z")),
    ]
    for i, (nm, fn) in enumerate(negatives, 1):
        v = mutate(fn)
        hit = len(v) > 0
        if not hit:
            fails += 1
        print(f"CORPUS\t{'PASS' if hit else 'FAIL'}\t负向N{i}_{nm}\t"
              f"注入违规 {len(v)} 条（必须>0）" + ("" if hit else "——契约门没有牙齿"))
    return fails


# ---------------------------------------------------------------- 全量判卷
def gate_full() -> int:
    """全量：数据缺失 → SKIP（退出 0）；否则六段映射→检出→判卷 → 报告。"""
    missing = [p for seg in SEGMENTS for p in (DATA_DIR / seg[1], DATA_DIR / seg[2])
               if not p.is_file()]
    if missing:
        print(f"CORPUS\tSKIP\t全量判卷\t数据缺失 {len(missing)} 份："
              + "、".join(m.name for m in missing[:4]) + " …（out/_corpus_pcaps 未就绪）")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fails = 0
    results: list[dict] = []
    for name, csv_name, pcap_name, desc in SEGMENTS:
        judged, _records, violations = run_segment(name, desc, csv_name, pcap_name, OUT_DIR)
        if judged is None:
            fails += 1
            print(f"CORPUS\tFAIL\t{name}\t契约门违规 {len(violations)}："
                  + "；".join(violations[:3]))
            continue
        r = judged
        results.append(r)
        fpr, cov = r["fpr_on_label0"], r["window_coverage"]
        print(f"CORPUS\tPASS\t{name}\t包 {r['packets']} 帧 {r['comm_log_lines']}"
              f"（攻击窗口帧 {r['label1_frames']}）\t检出 {r['detections_total']} "
              f"{r['detections_by_cause']}\t窗口覆盖率 "
              f"{'n/a(窗口无Modbus帧)' if cov is None else format(cov, '.4f')}"
              f"\tlabel0误报率 {'n/a' if fpr is None else format(fpr, '.6f')}")

    report = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": "scripts/lemay_corpus.py",
        "detector": "src/mcopilot/agents/forensics_comm.py（只读复用，未加规则）",
        "honesty": "标签=攻击窗口二元标注，非 cause 级真值；判卷只做窗口口径；"
                   "自然段误报率为首测数字，只报告不设阈值（无基线）",
        "segments": results,
    }
    rp = OUT_DIR / "lemay_report.json"
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    nat = next((r for r in results if r["segment"] == "natural_polling_only"), None)
    if nat is None:
        print("CORPUS\tFAIL\t自然段\t缺 natural_polling_only 判定行")
        return fails + 1
    print(f"CORPUS\tPASS\t报告\t{rp.relative_to(ROOT)}"
          f"（自然段误报率首测="
          f"{'n/a' if nat['fpr_on_label0'] is None else format(nat['fpr_on_label0'], '.6f')}"
          f"，只报告不设阈值）")
    return fails


# ---------------------------------------------------------------- CLI
def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Lemay 数据集 → comm_log/1 → 检出 → 判卷（零依赖）")
    ap.add_argument("--make-fixtures", action="store_true", help="截取入库夹具三件")
    ap.add_argument("--gate-fixtures", action="store_true", help="夹具门：复现+逐行断言+负向N")
    ap.add_argument("--gate-full", action="store_true", help="全量判卷（数据缺失→SKIP）")
    a = ap.parse_args(argv)
    if a.make_fixtures:
        return make_fixtures()
    if a.gate_fixtures:
        return gate_fixtures()
    if a.gate_full:
        return gate_full()
    ap.error("需要 --make-fixtures / --gate-fixtures / --gate-full 之一")


if __name__ == "__main__":
    sys.exit(main())
