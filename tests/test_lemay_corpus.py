# -*- coding: utf-8 -*-
"""lemay_corpus（真实语料 CSV+pcap → comm_log/1 → 检出 → 判卷）守护测试。

三条被守的结论：
  1) 映射器行为钉死在入库夹具上：lemay_sample 三件（pcap/csv/期望 JSON）映射
     复现逐行一致、过 comm_log/1 契约门（阳性对照），首行字段手工对过原始字节；
  2) 契约门有牙齿：副本注入非法记录（unit_id 越域 / seq 回退 I1 / 日历不存在
     I6）必须逐条产生违规；pcap_mapping.json 结构完整、映射目标词表合法；
  3) 检出接线：映射产物喂 forensics_comm（只读复用）——自然夹具 0 检出；
     合成异常风暴段按窗口口径算出预期覆盖率；数据缺失时 --gate-full 走 SKIP。

诚实边界：夹具是真实数据集（polling_only 前 30 包）截取；这里守的是映射与
判卷机制，不是归因质量——真实分布误报率只报告不设阈值（首测无基线）。
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SAMPLE_DIR = ROOT / "knowledge" / "protocols" / "pcap_samples"
MAPPING_JSON = ROOT / "knowledge" / "protocols" / "pcap_mapping.json"
PY = sys.executable

sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "src" / "mcopilot" / "agents"))
import lemay_corpus as lc  # noqa: E402
import forensics_comm as fc  # noqa: E402
import validate_comm_log as vcl  # noqa: E402

CONTRACT = vcl.load_contract(None)


def _fixture_records() -> list[dict]:
    labels = lc.read_labels(SAMPLE_DIR / "lemay_sample.csv")
    frames, _stats = lc.parse_frames(SAMPLE_DIR / "lemay_sample.pcap")
    return lc.map_records(frames, labels, "lemay/fixture")


# --------------------------------------------------------------- ① 夹具与映射行为
def test_夹具三件在场且行数达标():
    for name in ("lemay_sample.pcap", "lemay_sample.csv", "lemay_sample_expected.json"):
        assert (SAMPLE_DIR / name).is_file(), f"缺入库夹具 {name}"
    exp = json.loads((SAMPLE_DIR / "lemay_sample_expected.json").read_text(encoding="utf-8"))
    assert exp["meta"]["rows"] >= 20, "夹具至少截 20 行（任务口径）"
    labels = lc.read_labels(SAMPLE_DIR / "lemay_sample.csv")
    assert len(labels) == exp["meta"]["rows"]


def test_pcap读取器_包数与对齐():
    exp = json.loads((SAMPLE_DIR / "lemay_sample_expected.json").read_text(encoding="utf-8"))
    packets = list(lc.iter_pcap(SAMPLE_DIR / "lemay_sample.pcap"))
    assert len(packets) == exp["packets_total"]
    assert [p[0] for p in packets] == list(range(1, exp["packets_total"] + 1))
    labels = lc.read_labels(SAMPLE_DIR / "lemay_sample.csv")
    assert len(labels) == len(packets), "标注行数必须等于包数（对齐根契约）"


def test_映射复现与期望JSON逐行一致():
    exp = json.loads((SAMPLE_DIR / "lemay_sample_expected.json").read_text(encoding="utf-8"))
    records = _fixture_records()
    assert len(records) == exp["frames_total"]
    for rec, want in zip(records, exp["lines"]):
        got = {"line": want["line"], "pcap_index": rec["pcap_index"],
               "timestamp_utc": rec["timestamp_utc"], "direction": rec["direction"],
               "unit_id": rec["unit_id"], "function_code": rec["function_code"],
               "device": rec["device"]["host_or_port"], "client": rec["client"],
               "label": rec["label"]}
        assert got == want, f"L{want['line']} 映射漂移：{got} != {want}"


def test_首行字段与原始字节手工核对值一致():
    """守映射器回归：首行值与 2026-10-21 人工解码 pkt#4 原始字节一致
    （payload 0594 0000 0006 01 03 0008 0004：tid=0x0594 pid=0 len=6 uid=1 FC3 读保持寄存器）。"""
    records = _fixture_records()
    first = records[0]
    assert first["pcap_index"] == 4            # 前 3 包是 TCP 握手，无载荷
    assert first["timestamp_utc"] == "2015-02-23T19:55:38.728216Z"
    assert first["direction"] == "req" and first["unit_id"] == 1
    assert first["function_code"] == 3         # 曾回归为 1（PDU 切片含 uid 字节的 bug），钉死
    assert first["device"]["host_or_port"] == "192.168.1.106:502"
    assert first["client"] == "192.168.1.100:1726" and first["label"] == 0


def test_映射产物过契约门_阳性对照():
    records = _fixture_records()
    v, _ = vcl.validate_records(records, CONTRACT)
    assert v == [], f"夹具映射必须 0 违规（阳性对照），实得：{v[:3]}"


# --------------------------------------------------------------- ② 契约门有牙齿
def test_负向注入三重断言_逐条必红():
    records = _fixture_records()

    def violations(mutate):
        bad = copy.deepcopy(records)
        mutate(bad)
        v, _ = vcl.validate_records(bad, CONTRACT)
        return v

    assert violations(lambda b: b[0].__setitem__("unit_id", 300)), "unit_id 越域必须红"
    assert violations(lambda b: b[1].__setitem__("seq", b[0]["seq"])), "seq 回退必须红（I1）"
    assert violations(lambda b: b[0].__setitem__("timestamp_utc", "2026-02-30T00:00:00.000000Z")), \
        "2 月 30 日必须红（I6）"


def test_标注CSV拒载口径():
    """列数/取值域/对齐破坏必须抛错——对齐是映射的根契约，宁可拒载不可错位。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bad.csv"
        p.write_text("1;0\n2;2\n", encoding="utf-8")          # label 出词表
        try:
            lc.read_labels(p)
            assert False, "label=2 必须拒载"
        except ValueError:
            pass
        p.write_text("1;0\n3;0\n", encoding="utf-8")          # 序号断档
        try:
            lc.read_labels(p)
            assert False, "包序号不连续必须拒载"
        except ValueError:
            pass


def test_pcap_mapping_json结构与词表():
    doc = json.loads(MAPPING_JSON.read_text(encoding="utf-8"))
    assert doc["schema"] == "lemay_to_comm_log/1"
    for key in ("csv_columns", "mapping", "parsing_rules", "segment_registry",
                "judging", "boundaries"):
        assert key in doc, f"mapping json 缺 {key} 节"
    cols = doc["csv_columns"]
    assert [c["index"] for c in cols] == [0, 1], "数据集事实：标注 CSV 恒两列"
    assert cols[1]["maps_to"].startswith("扩展字段 label"), "label 透传口径必须写明"
    contract_fields = set(vcl.REQUIRED) | {"exception_code", "frame_hex", "error",
                                           "notes", "schema"}
    for m in doc["mapping"]:
        assert m.get("target"), "每个映射条目必须有 target"
        assert m.get("source", m.get("value")), f"{m['target']} 缺依据（source/value）"
        base = m["target"].split("（")[0].split(" /")[0]
        if "." not in base and base not in contract_fields:
            # 扩展字段允许，但必须显式标注「扩展」
            assert "扩展" in m["target"], f"{base} 既非契约字段也未标注扩展"
    assert "label" in json.dumps(doc), "窗口真值透传必须在 mapping json 里有交代"


# --------------------------------------------------------------- ③ 检出接线与判卷
def _storm_records():
    """合成异常风暴：同流连续 4 条异常 resp，前 2 条标 1（攻击窗口）后 2 条标 0。"""
    def mk(seq, direction, label, **kw):
        rec = {"schema": "comm_log/1", "timestamp_utc": "2026-10-21T02:15:30.000Z",
               "seq": seq, "channel": "tcp", "direction": direction, "unit_id": 1,
               "function_code": 3, "device": {"host_or_port": "192.168.1.104:502"},
               "label": label, "pcap_index": seq, "client": "192.168.1.101:1631",
               "source": "synthetic"}
        rec.update({k: v for k, v in kw.items() if v is not None})
        return rec
    return [
        mk(0, "req", 0),
        mk(1, "resp", 1, exception_code=2, frame_hex="01038202"),
        mk(2, "req", 0),
        mk(3, "resp", 1, exception_code=2, frame_hex="01038202"),
        mk(4, "resp", 0, exception_code=2, frame_hex="01038202"),
        mk(5, "resp", 0, exception_code=2, frame_hex="01038202"),
    ]


def test_检出接线_自然夹具零检出():
    records = _fixture_records()
    dets = fc.detect_entries(records)
    assert dets == [], "自然轮询夹具必须 0 检出（真实分布首测口径的夹具版）"
    judged = lc.judge_segment("natural_fixture", "夹具", records,
                              {"packets": 30, "modbus_pdus": len(records)},
                              dets)
    assert judged["fpr_on_label0"] == 0.0 and judged["detections_total"] == 0


def test_检出接线_异常风暴窗口覆盖率():
    records = _storm_records()
    v, _ = vcl.validate_records(records, CONTRACT)
    assert v == [], "合成风暴样例必须自身合规（否则检出测试无效）"
    dets = fc.detect_entries(records)
    assert len(dets) == 1 and dets[0]["cause"] == fc.CAUSE_STORM, "连续 4 条异常 resp 必须判 1 段风暴"
    judged = lc.judge_segment("synthetic_storm", "合成", records,
                              {"packets": 6, "modbus_pdus": 6}, dets)
    assert judged["label1_frames"] == 2 and judged["detections_in_window"] == 1
    assert judged["window_coverage"] == 1.0, "风暴证据行（4 条异常 resp）盖住全部 2 条标签1帧"
    assert judged["fpr_on_label0"] == 0.0, "唯一检出的证据全在窗口内，窗外误报为 0"


def test_gate_full数据缺失走SKIP():
    """out/_corpus_pcaps 缺失 → gate_full 退出 0 且打印 SKIP（环境事实不算回归）。"""
    import io
    import contextlib
    real_dir = lc.DATA_DIR
    try:
        lc.DATA_DIR = ROOT / "out" / "_definitely_missing_dir__"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = lc.gate_full()
        out = buf.getvalue()
        assert code == 0, "SKIP 必须退出 0"
        assert "CORPUS\tSKIP" in out, "SKIP 必须打 SKIP 行（gate_corpus.ps1 靠它分 SKIP/FAIL）"
    finally:
        lc.DATA_DIR = real_dir


def test_cli_gate_fixtures退出码0():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([PY, str(SCRIPTS / "lemay_corpus.py"), "--gate-fixtures"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120, cwd=str(ROOT), env=env)
    assert r.returncode == 0, f"--gate-fixtures 必须 0：{r.stdout[-400:]}"
    assert "CORPUS\tPASS\t负向N3" in r.stdout, "负向三重断言必须全打 PASS 行"
