# -*- coding: utf-8 -*-
"""JD 职责块标注 + 智能体覆盖率（扩样后，含相关性过滤与分城市口径）"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

# 输入件在会话工作区（不随仓分发）：用环境变量 JDS_JSONL 指到它
SRC = os.environ.get("JDS_JSONL") or r"<会话工作区>\out\_boss\jds.jsonl"

# 相关性过滤：岗位须命中 设备软件/上位机/运动控制 语义，滤掉"运动康复师"类噪音
REL = re.compile(r"上位机|运动控制|自动化软件|自动化设备|非标设备|产测|设备软件|测控|控制器软件")

BLOCKS = {
    "协议层(Modbus/S7/串口/SECS等)": r"modbus|tcp|串口|socket|s7|slmp|mc协议|focas|secs|gem|can|profinet|以太网",
    "运动控制卡/SDK适配": r"运动控制卡|控制卡|板卡|固高|googol|雷赛|leadshine|正运动|zmotion|zmc|dmc\d|gts|adlink|凌华",
    "UI框架(WPF/Qt/组态)": r"wpf|winform|qt|mfc|组态|wincc|prism|mvvm",
    "数据库/报表/MES": r"sql|mysql|sqlite|oracle|数据库|报表|mes|数据存储|数据追溯",
    "机器视觉": r"视觉|halcon|opencv|相机|vision|海康|大恒",
    "现场调试/驻场": r"现场调试|驻场|出差|售后|安装调试|客户现场",
    "伺服/运动调试诊断": r"伺服|诊断|波形|频谱|故障分析|示波|调参|抖动|定位精度",
    "SPC/质量统计": r"\bspc\b|cpk|良率|过程能力|统计过程",
    "PLC/下位机协同": r"\bplc\b|西门子|三菱|欧姆龙|下位机",
    "运控算法(插补/轨迹/PID)": r"算法|轨迹规划|插补|pid|滤波|运动学",
}
AGENTS = {
    "adapter(六品牌卡封装)": ["运动控制卡/SDK适配", "协议层(Modbus/S7/串口/SECS等)"],
    "forensics(日志根因)": ["现场调试/驻场"],
    "servo(波形诊断)": ["伺服/运动调试诊断"],
    "spc(质量统计)": ["SPC/质量统计"],
}

rows = [json.loads(l) for l in open(SRC, encoding="utf-8") if l.strip()]
rel, dropped = [], []
for r in rows:
    text = (r.get("title", "") + " " + r.get("desc", "")).lower()
    (rel if REL.search(text) else dropped).append(r)

print(f"原始 {len(rows)} 份 → 相关 {len(rel)} 份（过滤掉 {len(dropped)}：{'、'.join(d['title'][:12] for d in dropped[:6])}…）\n")

cities: dict[str, int] = {}
for r in rel:
    cities[r.get("city", "?")] = cities.get(r.get("city", "?"), 0) + 1
print("相关样本分布：", "  ".join(f"{k}{v}" for k, v in sorted(cities.items())))

def coverage(rs, label):
    hits = {b: 0 for b in BLOCKS}
    ex: dict[str, list[str]] = {b: [] for b in BLOCKS}
    for r in rs:
        text = " ".join([r.get("title", ""), r.get("tags", ""), r.get("banner", ""), r.get("desc", "")]).lower()
        for b, pat in BLOCKS.items():
            if re.search(pat, text):
                hits[b] += 1
                if len(ex[b]) < 3:
                    ex[b].append(r["title"][:20])
    n = len(rs)
    print(f"\n=== {label}（n={n}）===")
    print(f"{'职责块':<26} 出现率")
    for b, k in sorted(hits.items(), key=lambda kv: -kv[1]):
        print(f"{b:<26} {k:>2}/{n} {round(k/n*100):>3}%  {'█' * round(k / n * 16)}")
    print("--- 智能体目标块 ---")
    for a, blocks in AGENTS.items():
        k = sum(1 for r in rs if any(re.search(BLOCKS[b], " ".join([r.get("title",""), r.get("tags",""), r.get("banner",""), r.get("desc","")]).lower()) for b in blocks))
        print(f"{a:<26} {k:>2}/{n} = {round(k/n*100)}%")

coverage(rel, "相关样本职责块")
# 运动控制方向的单独口径（与"上位机"分词对照）
mc = [r for r in rel if r.get("term") == "运动控制"]
sw = [r for r in rel if r.get("term") != "运动控制"]
if mc and sw:
    coverage(mc, "分词对照：运动控制类岗位")
    coverage(sw, "分词对照：上位机/自动化类岗位")
