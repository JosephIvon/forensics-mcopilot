# 品牌 × 协议 × 特性能力矩阵（开发计划 v2 P3 交付物）

- 生成日期：2026-10-21
- 交付依据：`docs/开发计划_v2_协议层.md` P3「产出：品牌 × 协议 × 特性能力矩阵（读写/批量/事件/断线重连）」；行业需求面统计依据见该文档头部（5 城市 × 3 搜索词、64 份有效岗位描述：协议层 69%｜运动控制卡 SDK 14%）。
- 数据纪律：**只依据仓库内已入库知识**（`knowledge/protocols/*.json`、`knowledge/sdks/*.json`、`knowledge/cards.json`、`knowledge/templates/protocol/*`、`docs/TODO需实测_协议域.md`），每条能力注明出处文件；知识库未覆盖的格子一律如实留白，不编造。
- 机器可读版：同目录 `capability_matrix.json`（schema 键 `schema_version` = `capability_matrix/1`，同结构；2026-10-21 由旧键名 `schema` 统一迁移为 `schema_version`，键值不变）。

状态词表（全文统一）：

| 标注 | 含义 |
|---|---|
| **已入库** | 知识库有规范级条目（mechanical 提取 + spec_ref 逐字引文）支撑该格 |
| **提取中 / ◐** | 骨架或部分条目已入库（含 judgment 项待人工核对），或工程侧模拟器/真机缺口未销 |
| **规划 / 进行中** | 计划文档点名，知识库**尚未入库** |
| **延期** | 计划文档明示延后，并写明原因 |
| ✗ 无 | 该协议模型中**不存在**此特性（有知识依据，不是没提取） |

---

## 1. 协议覆盖

| 协议 | 传输/变体 | 状态 | 知识文件 | 规范版本（spec_version） | provenance 分布 |
|---|---|---|---|---|---|
| Modbus TCP | TCP/IP，端口 502，MBAP 头 | **已入库** | `knowledge/protocols/modbus.json` + `knowledge/templates/protocol/ModbusTcpClient.cs` | AP **V1.1b3**（2012-04-26，50 页）+ MSG **V1.0b**（2006-10-24，46 页），均取自 modbus.org 官网现行地址，sha256 在档 | FC+异常码 32 条：mechanical 29 / judgment 3；全文件 needs:manual_check 7 处 |
| Modbus RTU | 串行线（RS232/485），CRC-16 | **已入库** | `knowledge/protocols/modbus.json` + `knowledge/templates/protocol/ModbusRtuClient.cs`（+SL V1.02 framing/CRC16） | Serial Line **V1.02**（2006-12-20，44 页），sha256 在档 | 同上（framing.rtu / limits_and_timeouts 各条 mechanical） |
| S7 | ISO TCP (RFC1006)，端口 102 | **已入库** | `knowledge/protocols/s7.json` | Snap7 Reference Manual **Rev.8**（对应 Snap7 1.4.2，2016-12-03，289 页，sha256 在档）；**第三方逆向工程文档，非西门子官方规范**（西门子未公开 S7 内部协议规范，s7.json p18 引文已注明） | 181 条：mechanical 161 + mechanical-evidence 20 / judgment 0（connection 30 + pdu 21 + functions 24 + addressing 13 + limits 12 + 错误码 81：iso_tcp 15 + client 38 + server 8 + partner 18 + composition/full_32bit 2）。2026-10-21 对库更正：原记 166 条 / judgment 6 与库不符——原 7 条 judgment 已全部经 Snap7 1.4.3 源码取证升级为 mechanical-evidence（src_ref 在档），needs:manual_check 同步移除 |
| SLMP / MC（三菱） | 以太网 3E 帧（QnA 兼容，二进制/ASCII） | **提取中**（骨架已入库） | `knowledge/protocols/slmp.json` + `knowledge/templates/protocol/SlmpTcpClient.cs` / `SlmpContracts.cs` | MELSEC iQ-F FX5 User's Manual (SLMP) **JY997D54401**（114 页，手册编号 + sha256 验证，官方下载页 JS 动态无法直链、经镜像分发已如实记录） | 11 条：mechanical 10 / judgment 1（副头部 0x5000/0xD000 值在消息图解区，pypdf 列打散，标 needs:manual_check） |
| Focas（发那科 CNC） | 以太网/HSSB 库 API（fwlib32.dll），非公开标准协议 | **提取中（知识已入库）** | `knowledge/protocols/focas.json`（2026-10-21 入库，173 条：mechanical 170 / judgment 3） | Inventcom FOCAS Library Reference（第三方 HTML 复刻，非官方渠道）+ FOCAS2 Linux 手册翻印 / 函数清单 / Fwlib32.h（GitHub 第三方仓库分发，sha256 在档）；**官方 PDF（B-63xx）未获得**，来源性质在 focas.json spec_version.nature 如实标注 | 173 条（mechanical 170 / judgment 3，judgment 带 needs:manual_check）；特性格 8 格未评估，按下表留白 |
| SECS-GEM | — | **延期** | 仓库内无知识文件 | 开发计划 v2 P3：「SEMI 标准收费——只到公开手册摘录为止，边界诚实标注」；coverage_ledger `meta.plan_v2.phases.P3` 同口径 | — |

> 口径说明：任务下发时 SLMP 标注为「规划中」，但仓库实际进度已超前——`slmp.json` 骨架（2026-10-21）与 SLMP TCP 客户端模板已入库（coverage_ledger P2 行有登记），故本矩阵如实标「提取中」，不回退为「规划」。

---

## 2. 特性覆盖（每协议 × 8 特性）

汇总表（✓=已入库支撑，◐=部分/待销项，✗=协议模型中无，—=未入库）：

| 协议 | 读 | 写 | 批量读写 | 位操作 | 异常映射 | 断线重连 | 广播 | 模拟器可测 |
|---|---|---|---|---|---|---|---|---|
| Modbus TCP | ✓ | ✓ | ✓ | ✓ | ✓ | ◐ | ◐ | ◐ |
| Modbus RTU | ✓ | ✓ | ✓ | ✓ | ✓ | ◐ | ✓ | ◐ |
| S7 | ✓ | ✓ | ✓ | ✓ | ✓ | ◐ | ✗ | ◐ |
| SLMP / MC | ◐ | ◐ | ◐ | ◐ | ◐ | — | — | ◐ |

> Focas 知识已入库（173 条）但特性格未评估、SECS-GEM 未入库——均不占特性格：16 格全空白无信息量，见 §2.4 文字说明（2026-10-21 更新）。

### 2.1 Modbus（TCP + RTU，出处 `knowledge/protocols/modbus.json`）

| 特性 | 判定 | 依据（知识库条目 → 规范章节） |
|---|---|---|
| 读 | ✓ | `function_codes[0..3]` FC1 Read Coils / FC2 Read Discrete Inputs / FC3 Read Holding Registers / FC4 Read Input Registers（§6.1–6.4，p11–16，mechanical）；数量上限 2000 位 / 125 寄存器（`limits_and_timeouts.fc_quantity_limits_summary`，该条引文为概括、标 needs:manual_check） |
| 写 | ✓ | `function_codes[4..5]` FC5 Write Single Coil（0xFF00=ON）/ FC6 Write Single Register（§6.5–6.6，p17–19） |
| 批量读写 | ✓ | `function_codes[10..11]` FC15 Write Multiple Coils（1..1968）/ FC16 Write Multiple Registers（1..123）（§6.11–6.12，p29–30）；单事务读+写 FC23 Read/Write Multiple Registers（§6.17，p38）；掩码写 FC22 Mask Write Register（§6.16，p36）。另：诊断/事件类 FC7/8/11/12 已入库（串行域，对应计划文档「事件」维度） |
| 位操作 | ✓ | FC1/2/5/15 全为位访问（响应 LSB 打包，§6.1/6.2/6.11）；FC22 AND/OR 掩码位修改（公式 Result=(Current AND And_Mask) OR (Or_Mask AND NOT And_Mask)，§6.16 p36） |
| 异常映射 | ✓ | `exception_codes[0..10]` 异常码 01–0B（§7 表 p48–49，01–06/08/0A/0B mechanical；07/09 在 V1.1b3 表中不存在，标 judgment）；异常响应格式 = 功能码+0x80（§4.5 p9 / §7 p47）。模板已实现 `ModbusSlaveException` + 标准名称表（`ModbusTcpClient.cs`，与知识库已对账；0x04/0x06 名称已于 2026-10-21 按 V1.1b3 §7 表统一为 SERVER DEVICE FAILURE/BUSY，原 SLAVE DEVICE * 措辞弃用，黄金测试名称表抽查同步断言） |
| 断线重连 | ◐ | 规范只给超时/重试语义：串行 Response Time-out（SL §2.4.1 p9–10）、TCP「故意不规定响应时间，客户端超时应大于预期最大合理响应时间」（MSG §4.4.1.4 p25）→ 重连策略属实现层（`ModbusTcpClient.cs` Connect/三超时可配）；**契约 C11 断线重连语义待真机**（T2，半开连接桩不可模拟） |
| 广播 | ✓（RTU）／◐（TCP） | RTU：地址 0 = 广播、仅写命令、无响应（SL §2.1 p7，`limits_and_timeouts.broadcast_semantics`）；广播后 Turnaround delay 100–200ms（§2.4.1 p10）。TCP：直连服务器 Unit Identifier 无意义须用 0xFF（MSG §4.3.2 p23），unit=0 经网关路由到串行广播 → 实现层「发送即返回」语义待加（`templates/protocol/README.md` 待办）；**TCP 桩不可模拟广播**（T3 待真机） |
| 模拟器可测 | ◐ | 自建契约桩已建并全绿：`ProtocolContractTests` 19/19（15 条 + 劣化注入 3 条 + 异常码扫掠 1 条，2026-10-21 门禁轮纳入 `scripts/gate_protocol.ps1` G3；契约曾修出真 bug：位响应未裁剪填充位 TCP/RTU 四处，coverage_ledger P2）；RTU 行为契约 11/11 + RTU 超时契约 1/1（com0com 虚拟对，含广播闭环、坏 CRC 自愈与 no-respond 超时可辨识，G4）；帧级黄金测试 30/30（`ModbusFrameTests.cs`，`run_frame_tests.ps1` 可直接复跑）；**第三方 diagslave 对跑待接**（T1，`docs/TODO需实测_协议域.md`） |

### 2.2 S7（出处 `knowledge/protocols/s7.json`）

| 特性 | 判定 | 依据（知识库条目 → 手册页） |
|---|---|---|
| 读 | ✓ | `functions.fn_read_area` Cli_ReadArea——主读函数，DB/I/Q/M/T/C 全区域（p104，mechanical）；12 个区域便捷函数 `fn_area_wrappers`（p107–118） |
| 写 | ✓ | `functions.fn_write_area` Cli_WriteArea（p106）；同上便捷写函数 |
| 批量读写 | ✓ | `functions.fn_read_multivars` / `fn_write_multivars`（p119/121，单次最多 20 项 `limits_and_timeouts.lim_max_items_20`）；超 PDU 自动分包 `pdu.pdu_auto_split`（p26），MultiVars 例外不自动分包 `pdu.pdu_multivars_nosplit`（p119） |
| 位操作 | ✓ | `addressing.addr_byte_bit`：WordLen=S7WLBit 时 Start 以 bit 计，DB4.DBX10.3 → (10*8)+3=83（p105）；`addr_wordlen_table` S7WLBit=0x01（p104） |
| 异常映射 | ✓ | `error_codes`：32 位错误码三层组合（低 16 位 TCP/IP / 第 5 半字节 ISO TCP / 高 3 半字节 S7 协议，p252）；iso_tcp 15 条 + client 38 条 + server 8 条 + partner 18 条；完整 32 位常量**已由 Snap7 1.4.3 源码取证证实**（原 judgment 于 2026-10-21 升级为 mechanical-evidence，src_ref 文件/行号/引文在档，needs:manual_check 移除） |
| 断线重连 | ◐ | 机制入库：断线重连可直接用无参 Cli_Connect()（`conn_connectto`/`conn_connect`，p96/99）；SmartConnect 先 ping 后 TCP，规避 PLC 断电时 TCP 超时不可控（`conn_smart_connect`/`to_tcp_connect_timeout`，p26）；Partner 侧 RecoveryTime/KeepAliveTime 参数（p89）。**自动重连策略为实现层，知识库无「重连算法」条目** |
| 广播 | ✗ | S7 为 Client/Server/Partner 三角色问答模型：客户端只发起、服务器只应答（`connection.conn_roles`，p19）——知识库全文无广播概念，如实标「协议模型中无」 |
| 模拟器可测 | ◐ | Snap7Server 服务器规范已入库：并发连接默认 1024（`lim_server_max_clients`，p43）、可注册 DB ≤2048（`lim_server_db_2048`，p254）、虚拟 CPU 状态 Srv_SetCpuStatus（p225）→ 知识层可支撑 Snap7 demo server；**工程侧 Snap7 demo server 对接待做**（开发计划 P2 点名，coverage_ledger P2 余量未销） |

### 2.3 SLMP / MC（出处 `knowledge/protocols/slmp.json`——骨架，逐格 partial）

| 特性 | 判定 | 依据 |
|---|---|---|
| 读 | ◐ | `SLMP-CMD-0401` Device Read (Batch) 0401H/0001H（§4.1 p41，mechanical） |
| 写 | ◐ | `SLMP-CMD-1401` Device Write (Batch) 1401H/0001H（§4.1 p41）；随机读 `SLMP-CMD-0403` 0403H |
| 批量读写 | ◐ | 即上述 Batch 读/写两条（BIN 960 words / 15360 points 上限值在引文内）；随机读仅条目名入库 |
| 位操作 | ◐ | 位软元件码已入库：X* 9CH(9C00H) 等 6 类 device_code（§4.2 p46–47）；位单位子指令 0001H 见 `SlmpTcpClient.cs` SlmpCommand 常量 |
| 异常映射 | ◐ | 副头部错误值 0xD4/0xD5 为 judgment（消息图解区 pypdf 打散，`SLMP-SUBHEADER` needs:manual_check）；**End code 值表不在手册文字层**——客户端只区分 0=正常/非 0=错误并透传原始码，不编造翻译表（`SlmpTcpClient.cs` 头注释，TODO[需实测]） |
| 断线重连 | — | 知识库无对应条目 |
| 广播 | — | 知识库无对应条目 |
| 模拟器可测 | ◐ | 自建契约桩已建并**全绿 C1-C9**（`scripts/smoke_slmp.py` → `out/protocol_smoke/SlmpContracts.exe` RESULT: PASS，2026-10-21）；契约互测修出真 bug：客户端数据长度字段 offset 错位（写进 multi 站号位）、桩响应副头部未改 D000；位单位/真机 TODO[需实测]（T4） |

### 2.4 Focas / SECS-GEM

**Focas（2026-10-21 更正）**：知识已入库——`focas.json` 173 条（mechanical 170 / judgment 3，judgment 带 needs:manual_check：默认端口 8193 / 线缆级布局 / 超时默认值）。来源为第三方复刻手册（inventcom HTML 逐函数页 + GitHub 翻印 PDF/SDK 头文件），**官方 PDF（B-63xx 系列）未获得**，来源性质在 `focas.json` spec_version.nature 如实标注。**特性格 8 格尚未评估登记**（入库后按同一词表补格，本矩阵不预填），工程侧 fwlib32.dll 对接未做。

**SECS-GEM**：未入库，不编造任何特性。因 SEMI 标准收费延期（只到公开手册为止的边界延续有效）。json 版不为未登记协议保留空白格——16 格全空白无信息量，补格时按同一套词表。

---

## 3. 品牌映射

> 两个域合并登记：**协议域品牌**（西门子/三菱/发那科 → PLC/CNC 协议）与**运动卡六品牌**（需求基线 R-03：固高/雷赛/正运动/软赢/高川/ACS，见 `knowledge/cards.json` `brands_in_scope`）。

| 品牌 | 主通道 | 状态 | 出处文件 | 说明 |
|---|---|---|---|---|
| 西门子 | S7 | 已入库 | `knowledge/protocols/s7.json` | S7-300 固定 Rack0/Slot2，S7-1200/1500 走「base 协议 + HMI 角色」且需 PLC 侧允许 GET/PUT（`addr_s71200_1500_limits`，p34） |
| 三菱 | SLMP/MC（主）+ Modbus（备选） | SLMP 提取中；Modbus 已入库 | `slmp.json`、`modbus.json` | SLMP 3E 帧与 MC 协议 QnA 兼容 3E 帧相同（`SLMP-FRAME-3E`，§2.1 p13）——即 MC 协议入口 |
| 发那科 | Focas | 提取中（知识已入库） | `knowledge/protocols/focas.json` | 2026-10-21 更正：173 条已入库（第三方复刻手册来源，官方 PDF 未获得）；特性格评估与工程侧对接未做 |
| 雷赛 | 卡 SDK | 已入库（official-manual） | `knowledge/sdks/dmc.json` | DMC3000/DMC5000 脉冲卡 + DMC-E 总线卡，`LTDMC.dll`；知识文件 40 条 P/Invoke；**板卡型 DMC 本身不提供 Modbus 主站能力**（cards.json 雷赛 edge_cases） |
| 固高 | 卡 SDK | 已入库（official-binding） | `knowledge/sdks/gts.json` | GTS-400/800 PCIe 插卡，`gts.dll`（StdCall）；知识文件 35 条 P/Invoke；GEN（GTN_）是独立产品线、不在 GTS SDK 包内（README §10） |
| 正运动 | 卡 SDK | 已入库（official-binding） | `knowledge/sdks/zmotion.json` | ZMC 系列 EtherCAT 总线控制器，`zauxdll.dll`；知识文件 41 条 P/Invoke |
| 软赢 | 待录入 | —（一手件不足） | `knowledge/cards.json`（`needs-manual-check` 口径）、README §10 | 连公开一手件都不足，建出来只能是猜的，不建 |
| 高川 | 待录入 | —（一手件不足） | 同上 | 同上 |
| ACS | 待录入 | —（形态不同） | 同上 | SA/SA-LT 是独立整机、没有卡驱动可 P/Invoke，须先定「通信库分支」架构路线（README §10） |
| 通用（无品牌约束的从站设备） | Modbus TCP/RTU | 已入库 | `knowledge/protocols/modbus.json` + 模板 | 温控器/仪表类外设通用路径；字序 ABCD/CDAB 可配（`ModbusRegisters`） |

---

## 4. 待办清单

### 4.1 各协议模拟器（Simulators per protocol）

| 协议 | 模拟器 | 状态 | 出处 |
|---|---|---|---|
| Modbus | **diagslave** | 待接（T1）：当前对端=自建契约桩，行为受 C1–C10 约束但非第三方实现 | `docs/TODO需实测_协议域.md` T1；`knowledge/templates/protocol/ModbusContracts.cs` 文件头 |
| Modbus | 自建契约桩 | ✓ 已建并全绿（C1–C10；修出位响应未裁剪填充位真 bug） | `knowledge/coverage_ledger.json` `meta.plan_v2.phases.P2` |
| S7 | **Snap7 demo server** | 待接：开发计划 P2 点名「Snap7 demo server（S7）」，账本 P2 余量未销；知识层 Snap7Server 规范已入库（并发 1024 / DB≤2048 / Srv_SetCpuStatus） | `docs/开发计划_v2_协议层.md` P2；`coverage_ledger.json` P2 行；`s7.json` limits 条目 |
| SLMP | 自建契约桩 | 骨架已入库（`SlmpContracts.cs`），无第三方模拟器对接 | `knowledge/templates/protocol/` |
| Focas / SECS-GEM | 无 | Focas 知识已入库（`focas.json` 173 条，2026-10-21）但模拟器层未规划；SECS-GEM 知识未入库 | — |

### 4.2 真机验证缺口（T 编号对账 `docs/TODO需实测_协议域.md`）

| # | 缺口 | 状态 | 备注 |
|---|---|---|---|
| T1 | diagslave 第三方对跑同一契约套件 | ◐ P2/P4 | 消除「自建桩同源自证」 |
| T2 | 断线重连语义（网络闪断后半开连接） | ◐ P4 真机波 | 桩不可模拟半开连接（契约 C11） |
| T3 | 广播（unit=0）行为 | ◐ P4 真机波 | 串行域语义，TCP 桩不可模拟 |
| T4 | SLMP 位单位读写（0001H 子指令）+ 真机 CPU 互操作 | ◐ P4 真机波 | SLMP 契约桩本轮只实现字单位（`SlmpContracts.cs` C10） |
| T5 | SLMP 副头部值真机核对（现 judgment）+ 结束代码语义表 | ◐ P4 真机波 | 现只透传原始码不编造翻译（`SlmpTcpClient.cs` 头注释） |

### 4.3 知识库缺口（judgment / needs:manual_check 待销）

| 协议 | 缺口 | 出处 |
|---|---|---|
| S7 | TPKT/COTP 建连序列手册未覆盖（只称 ISO TCP/RFC1006）——**已闭合**：2026-10-21 Snap7 1.4.3 源码取证升级为 mechanical-evidence | `s7.json` `connection.conn_judg_tpkt_cotp`（p17） |
| S7 | 读/写 PDU 线缆级字节布局手册未定义——**已闭合**：源码取证给出线缆级布局（mechanical-evidence） | `s7.json` `pdu.pdu_judg_wire_layout`（p104） |
| S7 | 各超时参数默认值手册未提供——**已闭合**：源码取证给出默认值（mechanical-evidence） | `s7.json` `limits_and_timeouts.to_judg_default_values`（p89） |
| S7 | 完整 32 位错误码常量原为推导值——**已闭合**：五张错误表常量组在源码中逐条证实（mechanical-evidence） | `s7.json` `error_codes.full_32bit_judgment`（p252） |
| SLMP | 副头部 0x5000/0xD000（含错误 0xD4/0xD5）在消息图解区，待人工核对后转 mechanical | `slmp.json` `SLMP-SUBHEADER`（needs:manual_check） |
| SLMP | End code 错误码语义待真机核对（MC Protocol 手册），现只透传原始码 | `SlmpTcpClient.cs` 头注释 TODO[需实测] |
| Modbus | `fc_quantity_limits_summary` 引文为概括（已标 needs:manual_check）；FC16/FC43 异常功能码 0x90/0xAB 为推导值 | `modbus.json` 条目内标注 ×7 |
| 运动卡（品牌域） | 固高三项待厂商确认：当量变换公式 / 现场实际型号与固件版本 / GEN SDK 包；雷赛总线轴使能序列未公开（Enable 保持显式失败） | README §10；`cards.json` 雷赛 edge_cases |

---

## 5. 矩阵规模与标注分布

- **规模**：协议覆盖 6 行；特性覆盖 4 协议（已入库/提取中）× 8 特性 = 32 格（未入库协议不占格，见 §2.4）；品牌映射 10 行；待办 3 表（模拟器 5 项 / 真机 T1–T5 / 知识缺口 8 项）。
- **协议覆盖标注**：已入库 3（Modbus TCP、Modbus RTU、S7）｜提取中 2（SLMP；Focas——知识已入库、特性格未评估）｜延期 1（SECS-GEM）。
- **特性覆盖标注（32 格）**：✓ 已入库 16｜◐ 部分/待销 13｜✗ 协议模型无 1（S7 广播）｜— 未登记 2（SLMP 重连/广播）。
- **知识库 provenance 体量**（出处）：modbus.json FC+异常码 32 条（mechanical 29 / judgment 3，全文件 manual_check 7 处）；s7.json 181 条（mechanical 161 + mechanical-evidence 20 / judgment 0，2026-10-21 对库更正，原记 166/judgment 6 作废）；focas.json 173 条（mechanical 170 / judgment 3，manual_check 3 处）；slmp.json 11 条（mechanical 10 / judgment 1，manual_check 2 处）；sdks 三品牌 P/Invoke 条目 40/35/41（雷赛/固高/正运动）。

## 6. 诚实边界

- 模拟器 ≠ 真机（T1–T3 销项前，协议域所有「可测」仅指自建桩口径）。
- S7 知识源自第三方逆向工程文档（Snap7 Reference Manual）；原 judgment 缺口已于 2026-10-21 经 Snap7 1.4.3 源码取证闭合（mechanical-evidence，src_ref 在档）。
- Focas 知识源自第三方复刻手册（inventcom HTML + GitHub 翻印 PDF），官方 PDF 未获得；特性格未评估不预填。
- SLMP 为骨架提取：消息图解区值不冒充机械提取；End code 不编造翻译表。
- SECS-GEM 因 SEMI 标准收费延期，只到公开手册为止的边界延续有效。
- 本矩阵不覆盖运动卡六品牌中无一手件的软赢/高川/ACS（不猜）。
