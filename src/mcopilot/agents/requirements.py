"""工业需求基线智能体：把工程需求变成「谁做、机器做多少、产出是什么」的可执行地图。

产出三样：
  1. 逐条判定表（AI 承担度 + 判定 + 必须由人签字的部分）
  2. 覆盖审计（每条需求是否有工具兜住；每个工具是否真有需求依据 —— 防止工具自嗨）
  3. 完整报告 md / html
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.report import Report, callout
from ..core.util import fmt, knowledge_path, md_table, read_json

AGENT_ROLE = {
    "adapter_gen": "运动卡适配层生成器",
    "motion_lab": "运动/轨迹验证器",
    "cam_lab": "电子凸轮校验器",
    "servo": "伺服波形离线诊断器",
    "forensics": "设备日志根因分析器",
    "spc": "SPC 与良率分析器",
    "review": "实时运动代码评审器",
    "requirements": "工业需求基线与追溯器",
}


def load_map() -> dict:
    return read_json(knowledge_path("requirements_map.json"))


def verdict(ai_share: float, rules: dict) -> str:
    if ai_share >= 0.70:
        return "高替代"
    if ai_share >= 0.45:
        return "增强"
    return "人主导"


def analyze() -> dict:
    data = load_map()
    rules = data["verdict_rules"]
    items = data["items"]
    for it in items:
        it["verdict"] = verdict(it["ai_share"], rules)
    return data


def _rows(items: list[dict]) -> str:
    rows = []
    for it in items:
        rows.append([
            it["id"],
            it["group"],
            it["title"],
            it["category"],
            f'{it["ai_share"]:.0%}',
            it["verdict"],
            it["verify"],
            "、".join(AGENT_ROLE.get(a, a) for a in it["agents"]) or "—",
        ])
    return md_table(["编号", "来源", "条目", "类型", "AI 承担", "判定", "可验证性", "承接工具"], rows)


def _ai_part_section(items: list[dict]) -> str:
    out = []
    for it in items:
        if not it["ai_part"]:
            continue
        out.append(f"**{it['id']} {it['title']}**  \n"
                   f"AI 承担：\n" + "\n".join(f"- {x}" for x in it["ai_part"]))
        if it["human_only"]:
            out.append(f"  \n必须留人：\n" + "\n".join(f"- {x}" for x in it["human_only"]))
        out.append("")
    return "\n".join(out)


def coverage(data: dict) -> dict:
    items = data["items"]
    covered = {i["id"]: list(i["agents"]) for i in items}
    orphan_items = [i["id"] for i in items if not i["agents"] and i["ai_share"] > 0]
    all_agents = {a for v in covered.values() for a in v}
    no_req = sorted(a for a in AGENT_ROLE if a not in all_agents and a != "requirements")
    # 显式登记的「已知缺口」：条目本身有 AI 可承担的部分，但目前没有工具承接。
    # 不把它们混进 orphan_items（那是「忘了派活」），而是单列出来 ——
    # 否则审计会输出一句「无覆盖缺口」，把已知缺口一起盖掉。
    gap_items = [i for i in items if i.get("gap_note")]
    return {
        "items": covered,
        "orphan_items": orphan_items,
        "tools_without_requirement": no_req,
        "gap_items": gap_items,
        "agent_load": {a: sum(1 for v in covered.values() if a in v) for a in AGENT_ROLE},
    }


def _ledger_section() -> str:
    """三项目覆盖账本节：渲染 knowledge/coverage_ledger.json（账本是完成度唯一裁判）。

    契约见 tests/test_coverage_ledger.py::test_需求报告渲染出账本节：
    节标题含"三项目覆盖账本"，正文含全部项目名与账本规则原文。
    """
    led = read_json(knowledge_path("coverage_ledger.json"))
    meta = led["meta"]
    out = [
        callout("高", f"**{meta['rule']}**"),
        md_table(["项目", "厂商", "角色", "路径"],
                 [[p["name"], p.get("vendor", "—"), p["role"], p.get("path", "—")]
                  for p in meta["projects"].values()]),
        "",
        md_table(["验证等级枚举", "定义"],
                 [[k, v] for k, v in meta.get("verification_levels", {}).items()]),
        "",
        md_table(["需求条目", "实现方", "工件", "验证等级", "证据"],
                 [[e["requirement"], i["project"], i.get("artifact", "—"), i["verification"],
                   i.get("evidence", "—")]
                  for e in led["entries"] for i in e["impls"]]),
    ]
    if led.get("uncovered"):
        out.append(md_table(["未覆盖需求", "理由"],
                            [[u["requirement"], u.get("reason", "—")] for u in led["uncovered"]]))
    seams = led.get("seams", {}).get("items", [])
    if seams:
        out += ["", md_table(["接缝", "名称", "状态", "证据"],
                             [[s["id"], s["name"], s["status"], s.get("evidence", "—")]
                              for s in seams])]
    return "\n".join(out)


def build_report(data: dict, cov: dict) -> Report:
    items = data["items"]
    rep = Report(
        title=f"{data['meta']['domain']} · 工业需求基线与 AI 承接地图",
        subtitle=f"{data['meta']['scope']}　|　"
                 f"判定口径：AI 承担度 ≥70% 高替代 / 45%~70% 增强 / <45% 人主导",
        meta={
            "领域": data["meta"]["domain"],
            "技术栈": "、".join(data["meta"]["stack"]),
            "需求条目总数": len(items),
            "高替代条目": sum(1 for i in items if i["verdict"] == "高替代"),
            "增强条目": sum(1 for i in items if i["verdict"] == "增强"),
            "人主导条目": sum(1 for i in items if i["verdict"] == "人主导"),
            "AI 平均承担度": f'{sum(i["ai_share"] for i in items) / len(items):.0%}',
        },
    )

    rep.add("结论先行", "\n".join([
        callout("高", "**这批工业需求里，AI 能真正吃下的是「工程化负担」，不是「工艺判断力」。**"),
        "",
        "把需求基线逐条量化后，AI 承担度最高的是这几块，它们共同点是"
        "**①产出物是文件而不是手感 ②能被规则或数值验证 ③错了能被机器发现**：",
        "",
        "- **运动卡适配层 + 品牌能力矩阵**（R-03 / Q-04，AI 承担 85%）——"
        "把「换卡不改业务代码」从口号变成可回归的契约测试；能力矩阵是需求基线明确点名要沉淀的文档，"
        "正好是 AI 读函数手册最擅长的活。",
        "- **现场疑难问题攻关**（R-09，80%）——偶发定位偏差/时序竞争/丢包/良率波动，"
        "本质是「日志里证据没被串起来」，日志时间轴重建 + 缺陷规则检出是纯自动化能覆盖的。",
        "- **SPC / 稼动率 / 报表**（R-08，75%）——口径统一 + 控制图 + Cp·Cpk，"
        "有现成统计方法，AI 负责把散在各处的数据自动归到一套口径上。",
        "- **软件工程规范与文档**（R-10，85%）——规则包 + 代码反向生成文档，"
        "唯一难处是「推行力度」，那是管理问题不是工具问题。",
        "- **多轴联动与插补的算法层**（R-04 / Q-05，45~50%）——"
        "S 曲线参考实现、黄金测试向量、脉当量自检、硬件比较输出触发点计算可以交给 AI；"
        "但伺服整定、力控手感、产线验收必须留人。",
        "- **伺服波形的离线诊断**（Q-06b，75%）——这是本轮拆分出来的一条："
        "「现场闭环整定」不可自动化，但「由实测波形反推等效参数与候选根因」高度可自动化，"
        "两者混在一起算成「伺服整定难自动化」会漏掉这块。",
        "",
        callout("提示", "换句话说：**把 R-03 / R-08 / R-09 / R-10 四块交出去，"
                        "工程人力从「写适配层 + 拉报表 + 翻日志」释放到"
                        "「定工艺窗口、整伺服、做架构决断」——这才是这套自动化真正换回来的东西。**"),
    ]))

    rep.add("逐条判定表", _rows(items))

    rep.add("每条：AI 具体干什么 / 人必须干什么", _ai_part_section(items))

    rep.add("覆盖审计（防止工具自嗨）", "\n".join([
        "下面这张表回答两个问题：**每条需求有没有工具兜住？每个工具有没有需求依据？**",
        "",
        md_table(["智能体", "承接的需求条目", "条数"],
                 [[AGENT_ROLE[a], "、".join(sorted(k for k, v in cov["items"].items() if a in v)) or "—",
                   cov["agent_load"][a]] for a in AGENT_ROLE]),
        "",
        (callout("高", f"**覆盖缺口**：{'、'.join(cov['orphan_items'])} 有可 AI 化的部分但目前没有工具承接。")
         if cov["orphan_items"] else
         callout("低", "**无覆盖缺口**：所有 AI 承担度 > 0 且未登记缺点的需求条目都有对应工具。")),
        (callout("高", f"**无依据工具**：{'、'.join(cov['tools_without_requirement'])} 没有对应的需求依据，属于自嗨功能，应删。")
         if cov["tools_without_requirement"] else
         callout("低", "**无自嗨工具**：每个工具都能追溯到具体需求条目。")),
    ]))

    if cov["gap_items"]:
        rep.add("已登记的已知缺口（不算「无缺口」）", "\n".join([
            "下面这些需求条目里**确实有 AI 能吃下的部分，但目前没有工具承接**。"
            "把它们写出来，是为了不让上一条「无覆盖缺口」把已知缺口一起盖掉。",
            "",
            "\n".join(
                f"- **{g['id']} {g['title']}**\n  {g['gap_note']}"
                for g in cov["gap_items"]
            ),
        ]))

    rep.add("不做什么（明确划线）", "\n".join([
        "以下几类事情**不要交给 AI**，否则会把风险前移到现场：",
        "",
        "1. **伺服整定 / 惯量辨识的现场闭环操作**——需要示波器 + 上机，"
        "AI 只能做前置估算与离线波形诊断（Q-06a 留人、Q-06b 交给 AI，"
        "这两件事必须分开算，不能混成一句「伺服整定难自动化」）。",
        "2. **安全联锁、急停、力控压合的最终参数**——出事就是设备损坏 + 人员风险。",
        "3. **工艺窗口定版**——涉及产品可靠性与客户 spec，必须人对客户负责。",
        "4. **产线交付验收签字**——质量承诺的主体是人。",
        "",
        callout("提示", "判定原则：**AI 出草稿和检查项，人做决定和签字；"
                        "凡是「错了会伤到设备或人」的，一律不自动化。**"),
    ]))

    rep.add("与本套工具的对应关系", "\n".join([
        md_table(["工具", "一句话职责", "对应需求"],
                 [
                     ["`mcopilot adapter`", "厂商手册 → C# 适配器 + 契约测试 + 能力矩阵", "R-03、Q-04、Q-03"],
                     ["`mcopilot motion`", "S 曲线/到位时间/跟随误差/脉当量/硬件比较点，离线算清再上机", "R-04、Q-05、Q-06a"],
                     ["`mcopilot cam`", "电子凸轮表可行性校验 + 凸轮表生成 + 三家凸轮能力差异", "Q-05、R-03"],
                     ["`mcopilot servo`", "伺服波形**离线**诊断：实测波形 → 等效参数 → 候选根因", "Q-06b"],
                     ["`mcopilot forensics`", "设备日志时间轴重建 + 缺陷检出 + 根因报告", "R-09、Q-09、R-04"],
                     ["`mcopilot spc`", "SPC 控制图/Cp·Cpk/良率 Pareto/稼动率报表", "R-08、R-07、R-05"],
                     ["`mcopilot review`", "实时运动代码规则包自动评审", "R-10、Q-03、R-11"],
                     ["`mcopilot requirements`", "本文件：拆解与追溯", "全部"],
                 ]),
        "",
        callout("低", "用法：`mcopilot requirements report --out out/` 重新生成本报告；"
                        "每条判定都对应一个可执行命令，不是概念。"),
    ]))

    rep.add("三项目覆盖账本（coverage_ledger/1）", _ledger_section())
    return rep


def run(out_dir: Path, stem: str = "requirements_map") -> dict[str, Path]:
    data = analyze()
    cov = coverage(data)
    rep = build_report(data, cov)
    return rep.write(out_dir, stem)
