# Modbus 客户端（C#，零第三方依赖）

由 mcopilot protocol 生成，用于给上位机工程师生成跨品牌 Modbus 适配代码的基础传输层。
风格：**C# 7.3**，.NET Framework 4.8 可直接编译（`csc /target:library`），无 NuGet、无第三方 DLL。
实际代码同时保持 **.NET Framework 4 自带 csc（C#5）可直接编译**——`run_frame_tests.ps1` /
`run_contract.ps1` 即以该编译器源码直编并实跑通过。

## 文件清单

| 文件 | 内容 |
|---|---|
| `ModbusTcpClient.cs` | Modbus TCP 客户端 + **共享静态纯函数层**（ModbusFunctionCode / ModbusConst / ModbusPdu / ModbusSlaveException / ModbusWordOrder / ModbusRegisters / ModbusTcpFrame） |
| `ModbusRtuClient.cs` | Modbus RTU 串口客户端 + ModbusCrc16 + ModbusRtuFrame（static 纯函数） |
| `ModbusFrameTests.cs` | 帧级黄金测试（30 条，无第三方测试框架，`RunAll()` 返回报告） |
| `run_frame_tests.ps1` | 黄金测试一键入口：Framework csc 源码直编 → 跑 `RunAll()` → 退出码 = 失败数 |
| `run_contract.ps1` | 行为契约测试一键入口（三阶段编排：正常/分片/粘包各起独立从站实例）：编译 + 起从站模拟器 + 跑契约套件（退出码 = 总失败数）；另含第 4 阶段 `sweep`（异常码扫掠 @15024，`--exception-sweep` 从站，由 `scripts\gate_protocol.ps1` G3 拉起驱动） |
| `ModbusRtuContractTests.cs` + `run_rtu_contract.ps1`（本目录，入库副本） | **RTU 行为契约测试**（com0com 虚拟串口对，两阶段 normal/corrupt 共 11 条）：编译 ModbusTcpClient.cs + ModbusRtuClient.cs + 契约 → 起串口从站 → 跑（退出码 = 总失败数） |

构建脚手架（不属于交付物）：`out\_protocols_csharp\ModbusTestDriver.cs`（旧测试驱动）、`ModbusClients.dll`、`ModbusFrameTestsRunner.exe`（由 run_frame_tests.ps1 重建）。

## 功能清单

**ModbusTcpClient**（每请求显式带 unitId，便于经网关访问多从机）
- `Connect()` / `Close() / Dispose()`，基于 `TcpClient`；连接/收/发三个超时均可配
- 连接后设 `NoDelay=true`（禁 Nagle）；`Connect()` 对旧 `_tcp/_stream` 先 Close 再覆盖（防半开 socket 泄漏）
- 事务标识符自动自增（0xFFFF 回绕），响应按事务标识回验
- FC1 读线圈 / FC2 读离散输入 / FC3 读保持寄存器 / FC4 读输入寄存器
- **读响应数量交叉校验**（P1-2）：实收寄存器数/位数 < 请求 quantity → `IOException`（信息含请求量与实收量），防劣化从站短读被静默当真值
- **出错即重连（P1-3）**：事务中出现任何 `IOException` / `InvalidDataException` / `TimeoutException`（含 MBAP 头解析失败、事务/单元标识校验失败）→ 连接置毒化并 `Close()`；毒化后所有公开方法入口抛 `InvalidOperationException("连接已因协议/网络错误失效，请重连")`——出错后的字节流位置已不可信，继续复用只会得到错位/TID 错乱；恢复路径 = `Connect()` 用全新连接复活实例（TCP 层面）。RTU 路因按预期长度+CRC 收帧、每帧前 DiscardInBuffer，无此毒化语义，出错后 `Close()+Open()` 重开串口即可
- FC5 写单线圈（OFF=0x0000 / ON=0xFF00）/ FC6 写单寄存器 / FC15 写多线圈（LSB 在前打包）/ FC16 写多寄存器
- MBAP 帧构造与解析（事务标识 / 协议标识=0 / 长度 / 单元标识符），响应头逐字段校验
- 从机异常响应（功能码\|0x80 + 异常码）→ `ModbusSlaveException`，消息含标准名称（如 `ILLEGAL FUNCTION`）

**ModbusRtuClient**（基于 `SerialPort`）
- `Open()` / `Close()` / `Dispose()`；构造参数：端口、波特率、校验、数据位、停止位、从机地址、超时
- 帧 = 地址 + PDU + CRC16（**低字节在前**）；发送前按 t3.5 保持帧间隔；接收按"预期响应长度"精确收满后校验 CRC
- 同 TCP 的 FC1/2/3/4/5/6/15/16；异常帧同样解析为 `ModbusSlaveException`
- `CalcT35Milliseconds(baudRate)`：≤19200bps 按 3.5 字符时间（每字符 11 位），9600bps ≈ **4.01ms**；>19200bps 固定 1.75ms
- **广播（NoResponse，2026-10-21 新增）**：`SendBroadcast(slaveAddress, pdu)` 组帧（地址+PDU+CRC）→ 发送 → **不接收任何响应** → 仅等广播后 turnaround delay `BroadcastTurnaroundDelayMs = 150ms`（区间 100-200ms 抄录自 modbus.json `limits_and_timeouts.serial_turnaround_delay_after_broadcast`，spec_ref: Serial Line V1.02 §2.4.1 p10）；参数护栏：非 0 地址、读命令广播一律 `ArgumentException`（modbus.json `broadcast_semantics`：地址 0、必然写命令、无响应，§2.1 p7）。类型化包装：`WriteSingleCoilNoResponse` / `WriteMultipleCoilsNoResponse` / `WriteSingleRegisterNoResponse` / `WriteMultipleRegistersNoResponse`（unitId 恒 = 0）
  - ⚠ 广播语义：无响应 = **错误不可知**（是否执行/越界/异常统统不可知，规范如此）；方法返回 ≠ 执行成功；仅适用于广播安全命令，需确认结果请单播写 + 回读

**共享静态纯函数层（可独立单测，不碰 IO）**
- `ModbusCrc16.Compute()`：反射多项式 0xA001、初值 0xFFFF，逐位算法
- `ModbusPdu.Build*Request() / Parse*Response()`：功能码级 PDU 构造/解析（TCP/RTU 共用）；`EnsureReadCount()` 读响应数量交叉校验（P1-2，TCP/RTU 类型化读共用）
- `ModbusTcpFrame.BuildRequestFrame() / TryParseHeader()`：MBAP 封帧与解帧
- `ModbusRtuFrame.BuildFrame() / TryParseFrame()`：RTU 封帧与 CRC 校验解帧
- `ModbusRegisters.ToRegisters() / ToUInt32()`：双寄存器 UInt32 组合，**字序可配 ABCD（高字在前）/ CDAB（低字在前）**；字节内恒为大端（Modbus 网络序）
- `ModbusSlaveException.GetExceptionName()`：异常码 → 标准名称表

## 协议常量 spec_ref 占位表

> 以下常量按模型知识预写，spec_ref 原为**占位**；2026-10-20 已与 modbus.json 完成语义对账（5 条 framing 项 + 异常码表/位打包 2 条落定，见各行「已核/⚠」标记，页码为 PDF 物理页）。
> 代码内每条常量旁有同款 spec_ref 注释——本次对账仅更新本表（.cs 不在本次可改范围），后续同步时以本表为准改注释即可。

| 常量 | 值 | spec_ref（占位） |
|---|---|---|
| CRC16 算法 | 反射多项式 0xA001，初值 0xFFFF，结果低字节在前 | 已核：modbus.json framing.rtu.crc16（Serial Line V1.02 §2.5.1.2 p14 初值全 1/低字节先发；§6.2.2 App B p39 算法 LSB=1 异或 0xA001、p40 多项式 1010 0000 0000 0001） |
| CRC 校验锚点 | "123456789"→0x4B37；`11 03 00 6B 00 03`→帧尾 `76 87` | 锚点一为 CRC 目录标准校验值；锚点二为 Serial Line V1.02 规范示例, 待对账 |
| RTU 帧格式 | 地址(1) + PDU(n) + CRC(2, 低前高后) | 已核：modbus.json framing.rtu.frame_structure（Serial Line V1.02 §2.5.1 Figure 12 p13：地址 1 + 功能码 1 + 数据 0..252 + CRC 2，帧最大 256 字节；原占位 §2.5.1.2 实为 CRC 小节，帧格式在 §2.5.1） |
| t3.5 帧间隔 | ≤19200bps: 3.5×字符时间（11 位/字符）；>19200bps: 固定 1.75ms | 已核：modbus.json framing.rtu.inter_frame_delay_t3_5（Serial Line V1.02 §2.5.1.1 p13：帧间静默 ≥3.5 字符时间、字符间 >t1.5 丢帧；>19200bps 固定 t3.5=1.750ms、t1.5=750µs 同节） |
| 字符 = 11 位 | 1 起始 + 8 数据 + 1 校验/停止 + 1 停止 | MODBUS over Serial Line V1.02 §2.2, 待对账 |
| MBAP 头 | 事务标识(2) / 协议标识(2, =0) / 长度(2) / 单元标识(1)；长度 = PDU+1 | 已核：modbus.json framing.tcp.mbap_header（Messaging on TCP/IP V1.0b §3.1.3 p5：头 7 字节四字段；长度=后续字节数含单元标识 §3.1.3 p5/§4.5.2 p32；各字段大端 §3.1.3 p6） |
| 协议标识 ProtocolId | 0x0000 | 已核：modbus.json framing.tcp.mbap_header.fields[Protocol Identifier] = 0（Messaging on TCP/IP V1.0b §3.1.3 p5 "0 = MODBUS protocol"；modbus.json 无独立 tcp.protocol_id 键，该值载于 mbap_header.fields） |
| TCP 默认端口 | 502 | MODBUS Messaging on TCP/IP V1.0b §2.1（IANA 502）, 待对账 |
| 事务标识符 | 客户端生成、自增、0xFFFF 回绕 | MODBUS Messaging on TCP/IP V1.0b §3.1, 待对账 |
| PDU 上限 | 253 字节（ADU = 地址 1 + PDU 253 = 256） | MODBUS Application Protocol V1.1b3 §4.1, 待与 modbus.json 对账 |
| 字节序 | 大端（网络序） | MODBUS Application Protocol V1.1b3 §4.2, 待对账 |
| FC1 读线圈 | 数量 1..2000 | MODBUS Application Protocol V1.1b3 §6.1, 待对账 |
| FC2 读离散输入 | 数量 1..2000 | MODBUS Application Protocol V1.1b3 §6.2, 待对账 |
| FC3 读保持寄存器 | 数量 1..125 | MODBUS Application Protocol V1.1b3 §6.3, 待对账 |
| FC4 读输入寄存器 | 数量 1..125 | MODBUS Application Protocol V1.1b3 §6.4, 待对账 |
| FC5 写单线圈 | OFF=0x0000，ON=0xFF00 | MODBUS Application Protocol V1.1b3 §6.5, 待对账 |
| FC6 写单寄存器 | 值域 0x0000..0xFFFF | MODBUS Application Protocol V1.1b3 §6.6, 待对账 |
| FC15 写多线圈 | 数量 1..1968，数据 LSB 在前打包 | MODBUS Application Protocol V1.1b3 §6.11, 待对账 |
| FC16 写多寄存器 | 数量 1..123 | MODBUS Application Protocol V1.1b3 §6.12, 待对账 |
| 异常响应 | 功能码 \| 0x80 + 异常码；码 0x01..0x0B 名称见代码表 | 已核：modbus.json exception_codes + limits_and_timeouts.exception_response_format（AP V1.1b3 §4.5 p9 / §7 表 p48-49）。✓ 已对齐（2026-10-21）：0x04/0x06 代码名已按 V1.1b3 §7 表改为 "SERVER DEVICE FAILURE/BUSY"（原 "SLAVE DEVICE *" 为同义异名，已弃用；黄金测试名称表抽查同步断言）；0x07/0x09 在 V1.1b3 表中无定义，代码回退 UNKNOWN，与 modbus.json judgment 一致 |
| 位响应打包 | 首字节 LSB = 第一个线圈（含 FC1/2 响应与 FC15 请求） | 已核：modbus.json function_codes[1/2/15]（AP V1.1b3 §6.1 p11 / §6.2 p12-13 "LSB of the first data byte" = 查询中首个寻址输出/输入；§6.11 p29 官方示例 CD 01：LSB addressing the lowest output，与实现及黄金向量一致。modbus.json FC15 条目仅收补零句，LSB 句为本次对原文补证） |
| 广播地址 BroadcastAddress | 0x00 | 已核：modbus.json limits_and_timeouts.broadcast_semantics（address=0；Serial Line V1.02 §2.1 p7 "The address 0 is reserved to identify a broadcast exchange"；广播必然是写命令、无响应）（2026-10-21） |
| 广播后 turnaround delay | 区间 100-200ms，实现取中值 150ms（`BroadcastTurnaroundDelayMinMs/MaxMs/Ms`） | 已核：modbus.json limits_and_timeouts.serial_turnaround_delay_after_broadcast（Serial Line V1.02 §2.4.1 p10 "a delay is respected by the Master in order to allow any slave to process the current request before sending a new one"；条目值「典型 100-200ms」）（2026-10-21） |

## 黄金测试（30 条，全部通过）

不依赖真机：已知请求字节序列 ↔ 预期字节序列逐字节断言。覆盖：
TCP 帧头（构造 3 条 + 解析 + 非法拒绝）、RTU 帧+CRC（FC3/5/6/15/16 请求 + FC1/FC3 响应解析 + CRC 损坏/短帧拒绝）、
异常响应（PDU 级 + RTU 帧级 + 名称表）、UInt32 双寄存器 ABCD/CDAB、t3.5 时序、RTU 响应长度推算，
**P1-1 位响应 Byte Count 上限 4 条**（250 字节/2000 位解析通过、251 字节越界拒绝、1969 位=247 字节解析通过——
247 > 旧错误上限 0xF5=245，为修复的直接回归点；RTU 大批量收帧长度 1969→250 / 2000→253），
以及 **RTU 广播 4 条（2026-10-21 新增）**：
- `RTU黄金_广播FC6写单寄存器_unit0加CRC`：`00 06 00 01 00 03` + CRC 0xDA99（帧尾 99 DA，低前高后）
- `RTU黄金_广播FC16写多寄存器_unit0全帧`：`00 10 00 01 00 02 04 00 0A 01 02` + CRC 0xCC96（帧尾 96 CC）
- `RTU广播_turnaround延迟常量_对齐modbusjson`：Min=100 / Max=200 / 取值=150ms 与 modbus.json `serial_turnaround_delay_after_broadcast` 条目钉值；广播地址常量 = 0
- `RTU广播_非广播地址或读命令_参数拒绝`：非 0 地址、FC3 读命令广播 → `ArgumentException`（broadcast_semantics 行为钉桩）

CRC 参考实现经两个独立公认校验值验证（目录校验值 0x4B37、规范示例 0x8776）；广播黄金向量由同一已验证参考算法生成。

## 行为契约测试（19 条，三阶段 + 异常码扫掠，全部通过）

对端 = `tests/fixtures/modbus/modbus_tcp_slave.py`（每区 10000 元素，`run_contract.ps1` 按阶段自动拉起，
门禁 `sweep` 阶段由 `scripts\gate_protocol.ps1` 拉起，各实例独立端口）。
**三阶段编排**（2026-10-21）：
- 阶段 normal @15020 正常从站 → 原 15 条（种子读/写读闭环/数量 0→03/越界→02/不支持 FC→01/TID 回显/压力 50/重连 + P1-1×2 + P1-2 短读 + P1-3 坏帧毒化）
- 阶段 fragment @15021（`--fragment split3`，响应拆 3 段段间 20-50ms）+ @15022（`--fragment byte1`，逐字节滴流）→ 2 条分片重组契约
- 阶段 sticky @15023（`--sticky-stale 1`，每响应附发旧 TID 陈旧帧占住管道）→ 1 条粘包→毒化→复活闭环（P1-3 端到端）
- 阶段 sweep @15024（`--exception-sweep`，每请求按序回异常码 01,02,03,05,06,08,0A,0B 循环）→ 1 条异常码扫掠契约（2026-10-21 门禁轮新增）

新增 3 条（劣化注入）+ 1 条（异常码扫掠，2026-10-21 门禁轮）：
- `FragmentSplit3_FC3SeedRead_Fc6WriteReadBack`：分片实例 FC3 种子读 + FC6 三轮写读回全对——主站按 MBAP 长度补齐重组，半帧不当全帧用
- `FragmentByte1_FC16BatchWrite_Fc3ReadBack`：逐字节滴流下 FC16 批量写 + FC3 块读/逐个回读全对——ReadExact 循环真重组
- `StickyStaleFrame_PoisonsConnection_ReconnectRecovers`：第 1 事务正常 → 第 2 事务必撞旧 TID 陈旧帧（`InvalidDataException`，绝不静默用错数据）→ 毒化断开 → 后续调用得 `InvalidOperationException("连接已因协议/网络错误失效，请重连")` 而非诡异 TID 错 → `Connect()` 复活后读/写/回读全部正常（P1-3 端到端验证）
- `ExceptionSweep_EightRequests_ExceptionNamesExactMatch`：连发 8 请求，从站按序回异常码 01,02,03,05,06,08,0A,0B——逐请求断言抛 `ModbusSlaveException` 且异常码逐一精确相等、消息含 §7 表精确名称（ILLEGAL FUNCTION / ILLEGAL DATA ADDRESS / ILLEGAL DATA VALUE / ACKNOWLEDGE / SERVER DEVICE BUSY / MEMORY PARITY ERROR / GATEWAY PATH UNAVAILABLE / GATEWAY TARGET DEVICE FAILED TO RESPOND）；另以名称表断言单独钉住 **0x04=SERVER DEVICE FAILURE、0x06=SERVER DEVICE BUSY**（V1.1b3 §7 原文，弃用 SLAVE DEVICE * 同义异名——改名即翻红）与 0x07/0x09=UNKNOWN（表中无定义）

## RTU 行为契约测试（11 条，com0com 虚拟串口对，全部通过 2026-10-21）

**RTU 行为层已由 com0com 虚拟串口对实测打通（零真机）**：本机 C# 主站 ↔ COM3 ══ com0com 虚拟对 ══ COM4 ↔
python 从站 `tests/fixtures/modbus/modbus_rtu_slave.py`（ctypes 直调 kernel32 串口 API，零第三方依赖；
FC1-6/15/16 执行语义复用 modbus_tcp_slave，支持广播不回帧与 `--corrupt-next` 单帧坏 CRC 注入）。
⚠ 诚实边界：**com0com 虚拟对忽略波特率/电气层**（9600 仅是形式参数），本套件验证的是帧格式/CRC/帧间隔/
广播语义/异常翻译等**协议行为层**；真机波特率时序与电气层仍待现场验证（见待办）。

- 契约源：`ModbusRtuContractTests.cs`（本目录入库副本；自带 Main，勿与其他 Main 同编）
- 一键脚本：`run_rtu_contract.ps1`（本目录；就绪判定 = 从站 stdout 的 `RTU-SLAVE-READY` 标记行）
- 阶段 normal @COM4 正常从站 → 10 条：种子读 FC3=[1234,5678] / FC6、FC16 写读回 / FC5、FC15 线圈写读回 /
  数量 0 客户端本地拦截 / 越界 9999+2→异常码 02（且总线不毒化）/ **广播闭环**
  （`WriteSingleRegisterNoResponse(800,777)` 无异常快速返回 → FC3 unit1 读回 777，证明从站执行了广播）/
  **turnaround delay 实测**（广播发送→返回间隔 ≥ 下限 100ms，实测落在 150ms 档）/ 连续 30 事务零错误
- 阶段 corrupt @COM4 +`--corrupt-next` → 1 条：首个响应坏 CRC → 客户端 `InvalidDataException` 拒收 →
  **下一事务立即恢复正常**（种子值原样读回，接收管道不毒化）
- **RTU 超时契约 1 条（2026-10-21 门禁轮新增，`scripts\gate_protocol.ps1` G4 内置）**：
  从站侧为门禁生成的 no-respond 桩（`out/gates/g4_rtu_timeout/no_respond_slave.py`，复用
  `modbus_rtu_slave.py` 的 kernel32 串口层，行为 = **收帧不回**：读到的字节全部丢弃、永不发送），
  主站 @COM3 发 FC3 读 → 必须 `TimeoutException`（类型即"超时≠协议错"的可操作判别），消息必属
  两个已知超时签名之一：客户端自有的「Modbus RTU 等待响应超时（… ms）」（`ReadByteBefore` 帧中
  停滞路径）或 SerialPort 总静默的「操作已超时」——首字节即无响应时 SerialPort 先抛，客户端包装
  位于 `ModbusRtuClient.cs`（本轮许可写清单未含该文件，"首字节静默也补可辨识包装"留作模板轮待办）。
  探针把实际消息打进 RESULT 行，其余异常类型/未知消息一律 FAIL。
  对应从站口径：`modbus_rtu_slave.py` 本体保持只读不动（同上许可边界），
  no-respond 行为由门禁生成桩提供，观察语义与 `--no-respond` 等价。

## CI 门禁（2026-10-21 新增——本目录全部结论的门禁化入口）

**一条命令跑全部**（顺序 G1→G9，每门独立超时 300s；总退出码 = 失败门数，0 = 全绿）：

```pwsh
pwsh -NoProfile -File scripts\gate_protocol.ps1
# 可选参数：-PythonExe <从站/反查用 python>  -PyTestExe <G6 pytest 用 python（需已装 pytest）>
#           -TimeoutSeconds 300              -Only G2,G5（只跑指定门，退出码=该门退出码域）
```

⚠ **必须用 pwsh 7（`pwsh`）运行**：Windows PowerShell 5.1（`powershell`）下 .NET
EventSource 初始化即崩（0x80131506，2026-10-21 双签实测），CI 配置 runner 时勿用。

门禁清单与**退出码域**（每门失败时归属自己的域，互不混淆；总门禁退出码 = 失败门数）：

| 门 | 内容 | 退出码域 |
|---|---|---|
| G1 | csc 直编客户端+契约源，0 错误 | 10 |
| G2 | 黄金帧测试 `run_frame_tests.ps1`（30 条） | 11 |
| G3 | TCP 契约 `run_contract.ps1` 三阶段（18 条）+ 门禁 sweep 阶段（异常码扫掠 1 条） | 12 |
| G4 | RTU 行为契约 `run_rtu_contract.ps1`（11 条）+ RTU 超时契约探针（1 条）；COM3/COM4+com0com 缺失 → SKIP 不算败 | 13 |
| G5 | quote 反查 `check_modbus_quotes.py`（53/53） | 14 |
| G6 | pytest 协议域子集（test_protocol_modbus / test_protocol_slmp / test_capability_matrix / test_coverage_ledger）+ 矩阵统计对账 | 15 |
| G7 | 外部真值锚点 `gate_anchors.py`（sha256 全清单 + PDF→txt 再提取抽查；inventcom URL 默认 WARN） | 16 |
| G8 | 文档一致性（README/能力矩阵 §5 的数字 vs 从代码/知识库**实算**） | 17 |
| G9 | SLMP 契约 `smoke_slmp.py`（C1-C9） | 18 |

每门打印 `RESULT<TAB>PASS|FAIL|SKIP<TAB>门名<TAB>摘要`；末尾写机器可读汇总
`out/gates/gate_report_<时间戳>.json`（含各门时长、原始退出码与 git HEAD）。

**负向自检**（证明门禁有检测力——注入已知缺陷必须变红，且每例带未注入阳性对照；全部注入只落在
`out/gates/negative/` 副本上，tracked 文件零改动；注入未命中即退出码 3，绝不静默当 PASS）：

```pwsh
pwsh -NoProfile -File scripts\gate_negative.ps1
# → 检测力矩阵（用例/注入点/门/期望/观测/PASS），总退出码 0 = 检测力已证明
```

锚点门单独复跑：`python scripts\gate_anchors.py`（`--strict` 时把 URL 存活性计入失败）。

## 编译与运行

```pwsh
# 黄金测试一键（推荐；写入范围仅 out/_protocols_csharp/**）
pwsh -File knowledge\templates\protocol\run_frame_tests.ps1
# → Framework csc(C#5) 源码直编 ModbusTcpClient.cs + ModbusRtuClient.cs + ModbusFrameTests.cs
#   + 内嵌 ~20 行 Main 驱动 → ModbusFrameTestsRunner.exe → 退出码 = 失败数

# 行为契约一键（自动起 python 从站模拟器）
pwsh -File knowledge\templates\protocol\run_contract.ps1 -PythonExe python

# 库（交付物，零错误）
& "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\MSBuild\Current\Bin\Roslyn\csc.exe" `
  /nologo /codepage:65001 /langversion:7.3 /target:library /out:ModbusClients.dll `
  ModbusTcpClient.cs ModbusRtuClient.cs ModbusFrameTests.cs
```

结果（本机已验证，2026-10-21）：库编译 0 错误；Framework csc（C#5）编译 0 错误；
`run_frame_tests.ps1` → `Modbus 黄金测试：30/30 通过，0 失败`（退出码 0）；
`run_contract.ps1` 三阶段 → normal 15 + fragment 2 + sticky 1 = 契约用例 18 条：通过 18，失败 0（退出码 0；
粘包→毒化→复活端到端含内）。模拟器三种劣化模式（split3/byte1/sticky-stale）另经独立字节流冒烟验证：
split3 段间确有 20-50ms 间隔、byte1 逐字节 1-3ms 滴流、sticky-stale 的旧 TID 陈旧帧在真实响应之前占住管道。
**RTU 路（同日新增）**：`run_rtu_contract.ps1` 两阶段 → normal 10 + corrupt 1 = 契约用例 11 条：通过 11，失败 0
（退出码 0；com0com 配对 CNCA0=COM3 ↔ CNCB0=COM4，广播闭环/坏 CRC 拒收恢复/turnaround 实测均含内）；
python 从站另有 13 条独立冒烟（双 python 进程对跑）全过。
**门禁轮追记（2026-10-21）**：契约套件追至 19 条（+异常码扫掠 sweep 阶段 1 条）与 RTU 超时契约 1 条
（门禁生成 no-respond 探针），均已纳入 `scripts\gate_protocol.ps1` G3/G4 实跑全绿；
检测力由 `scripts\gate_negative.ps1`（N1-N4 注入 + 阳性对照）证明。

> 注：仓库 `scripts\compile_check.ps1` 面向 `out\csharp` 运动适配器那路（源文件列表写死），本路沿用其
> 编译器选择与调用方式（Roslyn csc + `/codepage:65001`），未改动该脚本。

## 待办（对账清单）

- [ ] **串口默认参数偏离注明（有意保留，不改默认）**：SL V1.02 §2.5.1 要求 RTU 字符帧 = 11 位（8E1 或 8N2），模板 `ModbusRtuClient` 构造默认 **8N1（10 位/字符）** 为现场兼容偏离——存量现场设备大量固定 8N1，故默认值不动；t3.5 按 11 位/字符计算（`CalcT35Milliseconds`），对 8N1 偏保守（间隔更长），方向安全。接入严格按规范的从站时，构造参数显式传 `Parity.Even`（8E1）或 `StopBits.Two`（8N2）
- [ ] 上表 spec_ref 对账：CRC16/RTU 帧格式/t3.5/MBAP/ProtocolId/异常码表/位打包 7 条已核（2026-10-20，与 modbus.json 及三份 PDF 原文语义核对）；其余行（CRC 锚点、字符 11 位、端口 502、事务标识、PDU 上限、字节序、FC1-16 数量上限）仍待核
- [x] 确认 >19200bps 的 t3.5 固定值（1.75ms）与字符 11 位的口径 —— 已核：Serial Line V1.02 §2.5.1.1 p13 固定 t3.5=1.750ms（t1.5=750µs）；§2.5.1 p12 字符 11 位（无校验时 2 停止位）。注：实现默认串口参数 8N1 为 10 位/字符，严格 11 位需 8E1 或 8N2；t3.5 按 11 位计算偏保守（方向安全）
- [ ] 如需 BADC/DCBA 字节交换序，在 `ModbusWordOrder` 增补（当前只覆盖 ABCD/CDAB 字序）
- [x] 广播地址（0）写命令"发送即返回"语义 —— 已加（2026-10-21）：`SendBroadcast` + 4 个 `*NoResponse` 包装，
      无响应 + 仅等 turnaround delay（150ms，modbus.json `serial_turnaround_delay_after_broadcast` 区间 100-200ms 取中值）；
      帧级黄金测试已钉（广播 FC6/FC16 字节级 + 常量对账 + 参数护栏），行为层见下一条
- [~] **RTU 广播/行为边界：帧级已钉、行为层已由 com0com 虚拟对实测（2026-10-21 收窄），真机项仍待现场** ——
      广播的帧构造（地址 0 + PDU + CRC）、"不接收任何响应"、turnaround delay 常量均已帧级钉死；
      行为层（广播闭环 = 广播写后单播读回生效、坏 CRC 拒收后下一事务恢复、turnaround 实测 ≥100ms、
      FC1-16 全 FC 写读回、异常码 02 翻译、连续 30 事务）已由 com0com 虚拟串口对 + python 从站实测全绿
      （见「RTU 行为契约测试」节，11/11）。**仍未覆盖（需真机现场）**：真实波特率/8N1-vs-8E1 电气层差异、
      真实多从站对广播的并发处理与广播后首帧吞帧、长线缆噪声。接入真机前，广播仍仅建议用于
      "丢了也无妨"的命令

## 接入循环（2026-10-21 新增——harness 接入闭环第一切片）

**架构原则：智能体在外、确定性内核在内。** `scripts/onboard_loop.py`（零第三方依赖）把
「把模拟设备接进来」落成状态机闭环：感知（查 `knowledge/protocols/capability_matrix.json`
的 Modbus TCP 行）→ 计划 → 执行（**只走既有门禁**：canonical = `run_contract.ps1` 三阶段
全量；负向沙盒 = 其 normal 阶段的同源同参复刻，源文件可指向注入副本，从站自起自停）→
解读（`knowledge/protocols/failure_signatures.json` 逐签名确定性归因）→ 决策（按语料
action_class：`rerun` 同配置重试 / `rerun_canonical` 弃用漂移副本恢复模板源复跑 /
`escalate` 停止交人）→ 复跑 → 全绿出《接入报告》`out/onboard_loop/onboard_report.md`（**运行产物，out/ 不入库**）。

```pwsh
python scripts\onboard_loop.py --python-exe <python> --pwsh-exe <pwsh>
# 退出码 = 接入成败：0 成功；20 UNKNOWN 升级；21 已知失败预算耗尽；22 环境/用法错误
# 每步打印 STAGE / DECISION / ATTRIBUTION 行（TAB 分隔，关键字段全 ASCII 便于上层断言）
```

失败语料库 `failure_signatures.json`（6 条，全部为本轮 session 亲手挖出并已门禁化的真实
缺陷：旧 DLL 缺 TransactRaw(CS1061)、byteCount 上限 245 误拒 1969 位(P1-1)、静默短读
(P1-2)、带毒连接 TID 不匹配+失效异常(P1-3)、RTU CRC 损坏拒收、文档数字漂移(G8)）。每条
`{id, signature, root_cause, next_action, evidence, gate}`；evidence 一律
`path:<仓库相对路径>#<锚点文本>` 或 `commit:<散列>`，可查性由 `tests/test_onboard_loop.py`
守护（文件在场+锚点文本在场+散列在仓库文本可查+良性样本零误报）。

**边界（诚实）**：
- 已知签名 → 确定性归因 + 语料声明的有限动作（重试/恢复模板源复跑）。**归因 ≠ 自动改
  代码**：模板源自身带缺陷时内核不越权改源码，停下给人。
- 语料库外失败 → 结构化 UNKNOWN 上报（`unknown_report.json` 证据包：失败 RESULT 行 +
  输出尾巴 + 产物路径 + 目标参数），**绝不猜、绝不在 UNKNOWN 上自动重试**；处置权在
  人/LLM，确认根因后按 evidence 纪律把新缺陷补进语料库再复跑。
- 门禁验收：`pwsh -NoProfile -File scripts\gate_onboard.ps1`（退出码域 19；三场景：
  A 全绿路径 / B 已知故障归因（byteCount 245 注入副本必须归因 P1-1 且复跑转绿）/
  C 语料库外新缺陷必须 UNKNOWN 零误归因；副本注入+三重断言+阳性对照，纪律同
  `gate_negative.ps1`），已注册为总门禁 G10（`scripts/gate_protocol.ps1`）。
