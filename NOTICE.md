# NOTICE —— 第三方材料、再分发与外置原件说明

本仓**自有的代码、项目文档与电子书正文**（`book/`）按 MIT 许可发布（见 `LICENSE`）。
本仓同时收录/引用了第三方材料；那些材料**不适用** MIT，其权利归各自权利人。
下表逐件说明：留在仓内的（附许可与署名义务）、**外置到仓外的**（仓内只留指针 + 指纹），
以及**本 NOTICE 不替使用者决定**的事。

本文件与 `samples/servo/PROVENANCE.md` 互补：那份管**样本数据**的来源与署名，
本文件管**全仓**的第三方材料与外置原件。

---

## 一、留在仓内的第三方材料

| 路径 | 出处 | 许可 / 归属 | 使用方义务 |
|---|---|---|---|
| `samples/servo/darus3252_prbs_pos_ppi.csv`（+ `.truth.json`） | DaRUS-3252（斯图加特大学数据仓储），DOI `10.18419/DARUS-3252` | **CC BY 4.0** | **署名**：数据集 DOI + 论文 DOI + 原始文件名与 md5（已在 `samples/servo/PROVENANCE.md` §2.1 随数据入档） |
| `samples/servo/darus6114_x_prbs.csv`、`samples/servo/darus6114_x_velsweep.csv`（+ `.truth.json`） | DaRUS-6114，DOI `10.18419/DARUS-6114` | **CC BY 4.0** | 同上（逐件要素见 PROVENANCE §2.1） |
| `samples/servo/klipper_resonance_x.csv`（+ `.truth.json`） | Klipper 论坛附件 `raw_data_x_20230409_173541.zip`（zip sha256 在档） | Klipper **GPLv3** 社区数据 | **须先读** `samples/servo/PROVENANCE.md` §2.3：其中已写明定性边界与法律保留（建议合规复核后再对外分发） |
| `samples/servo/twincat_export10.csv` | Beckhoff CODESYS Scope View (TwinCAT 3) 导出；入库的是**派生规范 CSV**，不是厂商原件 | 厂商知识产权 | 仅作内部测试夹具；授权范围需自行确认（PROVENANCE §2.2） |
| `knowledge/protocols/pcap_samples/lemay_sample.pcap`（+ `.csv` / `lemay_sample_expected.json`） | Lemay CSET'16 公开素材 | 第三方公开素材 | 来源记录在 `knowledge/protocols/real_corpora/sources.md` |
| `knowledge/protocols/real_corpora/issues_corpus.jsonl` | 公开 GitHub issue（python-snap7 / NModbus / pymodbus 等）的通信故障语料 | 第三方公开文本 | 逐条来源 URL 记录在 `knowledge/protocols/real_corpora/sources.md` |
| `knowledge/sdks/official_api/*.csv`（21 份） | 从厂商官方 SDK / 手册**机械抽取的事实表**（绑定签名、PE 导出表、头文件宏、端子表、PDO 表、返回类型表等） | 抽取结果属本仓；被抽取的厂商件权利归各厂商 | 这类是**抽取事实**，不是原件副本；原件外置（见第二节） |
| `docs/requirements_provenance_20261021/jds.jsonl` | **公开招聘网站**（BOSS 直聘等）抓取的岗位语料 | 平台公开页面内容 | 本仓只做**统计与标注**（需求块归类 / 智能体覆盖率），不重发布个人简历；抓取时间与来源 URL 逐条留痕 ✓。该语料只用于**交叉核对需求基线是否遗漏工业界普遍要求的能力项**，不决定基线口径 |
| `samples/servo/case_*.csv` | 本仓 `make_samples.py` 按二阶模型**合成** | 本仓生成 | 自洽性验证件，**不得**用来支撑任何准确率声明（PROVENANCE §1） |

---

## 二、外置到仓外的厂商 / 标准原件（按本仓既有约定）

**约定位置**：`../mcopilot-external/vendor_docs/protocol_specs/`
（与 `scripts/extract_binding_returns.py` 的默认路径一致 ✓）

仓内只留 `knowledge/protocols/anchors.json` 里的 **指针 + size + sha256** ✓。

| 文件 | 规格 / 出处 | 在档指纹 |
|---|---|---|
| `Modbus_Application_Protocol_V1_1b3.pdf` | MODBUS Application Protocol Specification V1.1b3（2012-04-26，modbus.org 官方发布） | anchors.json ✓ |
| `Modbus_Messaging_Implementation_Guide_V1_0b.pdf` | MODBUS Messaging Implementation Guide V1.0b（2006-10-24，modbus.org 官方发布） | anchors.json ✓ |
| `Modbus_over_serial_line_V1_02.pdf` | MODBUS over Serial Line Specification V1.02（2006-12-20，modbus.org 官方发布） | anchors.json ✓ |
| `FOCAS_function_list.pdf` | FOCAS1/2 函数清单（**第三方分发的 FANUC 手册副本**；官方 B-63xx 未获得，来源性质见 `knowledge/protocols/focas.json` 的 `spec_version`） | anchors.json ✓ |
| `FOCAS2_Ethernet_Linux_en.pdf` | FOCAS2/Ethernet for Linux OPERATOR'S MANUAL Edition 2（GitHub 第三方仓库翻印副本；在线源见 anchors.json 的 `url_liveness`） | anchors.json ✓ |
| `Snap7-refman.pdf` | Snap7 Reference Manual Rev.8（对应 Snap7 1.4.2；S7 无官方公开协议规范） | anchors.json ✓ |
| `FX5_SLMP_JY997D54401.pdf` | FX5 User's Manual (SLMP)，手册编号 JY997D54401，114 页（三菱官方手册原文，经镜像分发；镜像地址见 `knowledge/protocols/slmp.json` 的 `source_url`） | anchors.json ✓ |

**为什么外置**：本仓自己的约定就是**厂商原件不入库**——`docs/CodeWiki_20261022.md` 的"外部真值锚点"一节
写明厂商原始资料走 `<仓库根>/../mcopilot-external/vendor_docs`，`scripts/extract_binding_returns.py`
的默认路径也是那里 ✓。而这 7 份 PDF 当时躺在 `knowledge/protocols/specs/` 与 `slmp_specs/` 里，
**与自己的约定相悖** ✓。2026-10-22 公开前审把它们挪回约定位置，仓内指针与指纹一条不少 ✓。

**顺带补上的洞**：`FX5_SLMP_JY997D54401.pdf` 此前**根本没进锚点清单**——只有
`knowledge/protocols/slmp.json` 记了 sha256，门禁压根没在核它 ✓。本次补登，
锚点清单由 14 条变 15 条 ✓。

**门禁怎么处置**：原件在位 → 照核 sha256（PASS）；原件不在位（干净检出上的常态）→
记 **SKIP** 并在汇总行明确喊出「当前不可自动复核」，**不判 FAIL**——
把"设计上不入库"误报成"缺件"是另一种不诚实 ✓。
仓内跟踪文件缺位仍然是结构性缺失（退出码 2），不放水 ✓。

---

## 三、原件从哪来（公开渠道）

- **MODBUS 三份规范**：modbus.org 官方发布（`spec_version` 的描述与日期见 anchors.json）。
- **FOCAS 在线副本**：anchors.json 的 `url_liveness` 段记了在线源（`inventcom.net`）。
- **Snap7 参考手册**：对应 Snap7 1.4.2 的公开参考手册。
- **三菱 FX5 SLMP 手册**：手册编号 JY997D54401；官方下载页为 JS 动态无法直链，
  镜像地址记在 `knowledge/protocols/slmp.json` 的 `source_url`（取用时**必须核对 sha256**）。

指纹一律以 `knowledge/protocols/anchors.json` 为准；**指纹不符即拒收**，与样本门禁同一纪律。

---

## 四、本 NOTICE 不替你决定的事

1. **Klipper 数据的再分发口径**：本仓的分析与保留意见写在 `samples/servo/PROVENANCE.md` §2.3
   （测量数据通常不被视为 GPL 源码衍生作品；`cmd` 通道是按公开参数重建的），
   但对外分发前**建议合规过一遍** ✓。
2. **Beckhoff 导出件**：厂商知识产权，授权范围需自行确认 ✓。
3. **FANUC / 三菱手册副本**：官方件未取得、用的是第三方分发副本——若要公开分发本仓，
   建议先确认这几份的再分发边界（当前处置是**不入仓**，把风险留在仓外 ✓）。
4. **本仓自有的代码许可**：MIT（见 `LICENSE`）；若你要把本仓并入更大的工程，
   注意 MIT 不含专利授权条款 ✓。

> 纪律：本文件只登记**已核过的事实**（许可标识、出处、指纹、在档位置）。
> 任何一条"我们认为可以"而没有出处支撑的判断，都不写进这里。
