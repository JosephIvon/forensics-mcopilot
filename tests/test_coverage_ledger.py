"""三项目覆盖账本（coverage_ledger.json）的一致性测试。

账本是「完成度」的唯一裁判：它说覆盖了才算覆盖。所以它自身必须
结构正确、与 requirements_map.json 逐条对得上、验证等级合法、每条证据可查
—— 本文件把这些约束机器化，防止账本自己变成第二份自嗨文档。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from mcopilot.agents import requirements as requirements_agent  # noqa: E402
from mcopilot.core import util  # noqa: E402

LEDGER = util.read_json(util.knowledge_path("coverage_ledger.json"))
REQS = util.read_json(util.knowledge_path("requirements_map.json"))


def test_账本与需求基线逐条对齐():
    req_ids = {i["id"] for i in REQS["items"]}
    covered = [e["requirement"] for e in LEDGER["entries"]]
    uncovered = [u["requirement"] for u in LEDGER["uncovered"]]
    assert len(covered) == len(set(covered)), "entries 里有重复需求条目"
    assert len(uncovered) == len(set(uncovered)), "uncovered 里有重复需求条目"
    assert not (set(covered) & set(uncovered)), "同一条需求同时出现在 entries 与 uncovered"
    assert set(covered) | set(uncovered) == req_ids, "账本没有对齐全部需求条目（缺漏即盲区）"


def test_项目与验证等级必须合法():
    projects = set(LEDGER["meta"]["projects"])
    levels = set(LEDGER["meta"]["verification_levels"])
    for e in LEDGER["entries"]:
        assert e["impls"], f"{e['requirement']} 挂了账但没有任何实现条目"
        for impl in e["impls"]:
            assert impl["project"] in projects, f"{e['requirement']} 引用了未登记的项目 {impl['project']}"
            assert impl["verification"] in levels, (
                f"{e['requirement']} {impl['project']} 的验证等级 {impl['verification']!r} 不在枚举里")
            assert impl.get("evidence"), (
                f"{e['requirement']} {impl['project']} 缺 evidence —— 账本的规矩：升档必须有外部证据可查")
    for u in LEDGER["uncovered"]:
        assert u.get("reason"), f"{u['requirement']} 未覆盖但没给理由"


def test_三个项目全部登记且角色不同():
    projects = LEDGER["meta"]["projects"]
    assert set(projects) == {"trae_factory", "mcopilot", "axiscope"}, "三项目清单变了要同步测试"
    assert len({p["role"] for p in projects.values()}) == 3, "三项目角色定位出现重复"


def test_需求报告渲染出账本节():
    data = requirements_agent.analyze()
    cov = requirements_agent.coverage(data)
    rep = requirements_agent.build_report(data, cov)
    titles = [h for h, _ in rep.sections]
    assert any("三项目覆盖账本" in t for t in titles), "需求报告没有渲染账本节"
    body = next(b for h, b in rep.sections if "三项目覆盖账本" in h)
    for name in (p["name"] for p in LEDGER["meta"]["projects"].values()):
        assert name in body, f"账本节里缺项目 {name}"
    assert "完成度以本账本为准" in body


def test_v2计划与账本同步():
    """开发计划 v2（协议层）定稿后，账本的 meta.plan_v2 必须与计划文档保持一致——
    计划改了账本没跟 = 定位漂移；账本写了文档没有 = 凭空计划。"""
    plan = LEDGER["meta"]["plan_v2"]
    doc = ROOT / "docs" / "开发计划_v2_协议层.md"
    assert doc.exists(), "计划文档不在档"
    text = doc.read_text(encoding="utf-8")
    for phase in ("P0", "P1", "P2", "P3", "P4"):
        assert phase in plan["phases"], f"{phase} 阶段账本未登记"
        assert phase in text, f"{phase} 阶段计划文档缺失"
        assert plan["phases"][phase].split("（")[0].split(":")[0][:6] or True  # 阶段描述非空由下方统一查
        assert len(plan["phases"][phase]) > 10, f"{phase} 阶段描述过简"
    # 重排定位四件套齐全，且统计判据在文档里可查
    for key in ("adapter", "forensics", "servo", "spc"):
        assert key in plan["repositioning"], f"v2 重排缺 {key} 定位"
    for stat in ("69%", "12%", "0%", "64"):
        assert stat in text, f"计划文档缺统计判据 {stat}"
    # 封版/冻结定位必须在项目角色里体现（账本是覆盖真相源，定位漂移在这里抓）
    roles = " || ".join(p["role"] for p in LEDGER["meta"]["projects"].values())
    assert "封版" in roles, "servo KB v5 封版未反映在项目角色里"
    assert "冻结" in roles, "SPC 冻结未反映在项目角色里"
    assert "协议" in next(p for p in LEDGER["meta"]["projects"].values() if p["name"] == "工业需求工具链 mcopilot")["role"], \
        "mcopilot 角色未反映 v2 协议层核心定位"
    # 验收门四条齐全（通用验收）
    gate = plan["acceptance_gate"]
    for kw in ("测试全绿", "provenance", "需求覆盖率", "诚实边界"):
        assert kw in gate, f"验收门缺 {kw}"
