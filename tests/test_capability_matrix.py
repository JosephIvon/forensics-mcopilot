"""能力矩阵对账：只保留两条轻对账——引用文件存在性 + T 编号双向一致。

（2026-10-21 精简：状态词表/契约产物一致/stats 分布三个对账删除——
矩阵是手动维护的盘点文档，记账成本超过防漂移收益；契约真值由
test_protocol_modbus / test_protocol_slmp 的契约套件直接提供。）
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = json.loads(
    (ROOT / "knowledge" / "protocols" / "capability_matrix.json").read_text(encoding="utf-8"))


def test_协议行引用的知识文件都存在():
    for p in DOC["protocol_coverage"]:
        for f in p.get("knowledge_files") or []:
            assert (ROOT / f).exists(), f"{p['protocol']} 引用 {f} 不存在（矩阵不得引用幽灵文件）"


def test_T编号与TODO文档双向对账():
    tracker = (ROOT / "docs" / "TODO需实测_协议域.md").read_text(encoding="utf-8")
    doc_ts = set(re.findall(r"\bT\d\b", tracker))
    assert {"T1", "T2", "T3", "T4", "T5"} <= doc_ts, f"TODO 文档缺编号：{doc_ts}"
    for g in DOC["backlog"]["real_machine_gaps"]:
        assert g["id"] in doc_ts, f"矩阵缺口 {g['id']} 未在 TODO 文档登记"
