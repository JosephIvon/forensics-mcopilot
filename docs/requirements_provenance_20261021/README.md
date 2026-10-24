# 需求基线来源语料（provenance）

本目录是**工业需求基线的来源留痕**，不是本项目的产品功能。

- `jds.jsonl` —— 从公开招聘网站采集的在招岗位描述语料（69 份有效记录）。
- `harvest*.js` / `probe*.js` / `cdp_eval.js` —— 采集与探针脚本。
- `tag_jds.py` —— 标注器：把岗位描述切成职责块 / 要求块。

**它在本项目里的唯一作用**：把 `knowledge/requirements_map.json` 的需求基线
拿去和行业在招岗位做一次交叉核对，确认基线**没有遗漏工业界普遍要求的能力项**
（例如协议层对接、现场调试、数据与通信能力）。

它**不决定**基线的口径 —— 基线按运动控制上位机软件工程的实际交付物清单编制，
条目定义见 `knowledge/requirements_map.json` 的 `meta.baseline_source`。

采集时间与来源 URL 在 `jds.jsonl` 里逐条留痕；本仓只做统计与标注，
不重发布任何个人简历。
