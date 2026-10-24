# TODO[需实测] 追踪 —— 协议域（P2 起）

纪律：模板/知识库里所有 `TODO[需实测]` 注释必须在本文件登记（编号 + 状态），
`tests/test_protocol_modbus.py::test_TODO需实测追踪对账` 双向对账。
真机波（P4）逐条消除：删模板注释 + 本文件状态改 ✅（附实测环境记录）。

| # | 项 | 位置 | 登记状态 | 来源 |
|---|---|---|---|---|
| T1 | diagslave 正式模拟器对跑同一契约套件（当前对端=自建契约桩，行为受 C1-C10 约束但非第三方实现） | `ModbusContracts.cs` 文件头 | ◐ P2/P4 | 契约测试 |
| T2 | 断线重连语义（网络闪断后恢复；桩不可模拟半开连接） | `ModbusContracts.cs` C11 | ◐ P4 真机波 | 契约测试 |
| T3 | 广播（unit=0）行为——串行域语义，TCP 桩不可模拟 | `ModbusContracts.cs` C11 | ◐ P4 真机波 | 契约测试 |
| T4 | SLMP 位单位读写（0001H 子指令）+ 真机 CPU 互操作（桩本轮只实现字单位） | `SlmpContracts.cs` C10 | ◐ P4 真机波 | SLMP 契约 |
| T5 | SLMP 副头部值（0x5000/0xD000）真机核对（现 judgment：与自建桩互洽但非独立证据）；SLMP 结束代码语义表（现只判 0/非 0，不编造翻译） | `SlmpTcpClient.cs` 文件头 + slmp.json SLMP-SUBHEADER | ◐ P4 真机波 | SLMP 客户端/知识库 |

补充边界（非 TODO 但同属诚实边界）：
- 知识库引文复核现为三层判定（严格逐字 36 / 签名同源 17 / judgment 跳过 7），
  签名层吃掉的是 pdf2txt 的排版噪声（连字符断行、词中断行），不放过任何编造句子。
- `fc_quantity_limits_summary` 引文为概括，已按纪律标 `needs: manual_check`（本轮复核发现并补标）。
