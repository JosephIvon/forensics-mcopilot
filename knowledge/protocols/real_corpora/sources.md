# 真实世界 Modbus/S7 通信故障语料 · 来源清单（sources.md）

- 采集日期：2026-10-21；采集人：mcopilot Phase 2 语料采集（自动化 + 人工核对）
- 采集方式：web 检索定位 GitHub issue → 抓取 issue 页面内嵌数据，`verbatim_excerpt` 按 ASCII 标记切片逐字复制（未改写、未补全、未翻译）。
- 纪律：每条含 `source_url`（可回查）；`root_cause_status` 仅两档——`confirmed`（维护者回复/修复 commit 佐证，note 注明依据）与 `reported`（仅用户报告）；`error_class` ∈ {timeout, crc, reset, refused, exception, short_read, malformed, other}，映射依据见 JSONL 每条的 `mapping_notes`。
- 统计：共 35 条；confirmed 11 / reported 24；覆盖 7 个仓库。

## pymodbus-dev/pymodbus（6 条）

- [Transaction failed. Connection reset by peer.](https://github.com/pymodbus-dev/pymodbus/issues/420) — 两个 Python 进程共用 ABB AC700F 的单一 Modbus/TCP 连接，第二个进程被 RST — `reset` / `confirmed`
- [asyncio TCP client timeout broken](https://github.com/pymodbus-dev/pymodbus/issues/640) — asyncio 客户端设置 timeout=10 仍在服务端慢响应时立即抛 TimeoutError — `timeout` / `confirmed`
- [target machine actively refused connection](https://github.com/pymodbus-dev/pymodbus/issues/2196) — 频繁 connect/close 轮询电表，设备主动拒绝连接（WinError 10061，后续还出现 10060/10054） — `refused` / `confirmed`
- [Reading registers from a Schneider Electric PM5340 with ModBus ID 255](https://github.com/pymodbus-dev/pymodbus/issues/2386) — 读 Schneider PM5340（slave=255）返回 Exception Response(132,4,IllegalFunction) — `exception` / `confirmed`
- [pymodbus tcp client does not clean socket when not receiving data.](https://github.com/pymodbus-dev/pymodbus/issues/667) — 逆变器占线不响应后 socket 未清理，此后连接全部 timed out 且无法自恢复 — `timeout` / `reported`
- [Default source_address breaks IPv6 and dual stack client connections - breaks localhost](https://github.com/pymodbus-dev/pymodbus/issues/1881) — 默认 source_address=0.0.0.0 破坏 IPv6/双栈连接，localhost 也连不上 — `refused` / `confirmed`

## stephane/libmodbus（7 条）

- [CRC Check Error and Slave not the requested One, Ignored](https://github.com/stephane/libmodbus/issues/723) — RTU 链路上连续 CRC 校验错误且混入非请求从站（slave 155 != 1）的帧 — `crc` / `reported`
- [costum request and response - response not fully received](https://github.com/stephane/libmodbus/issues/231) — 自定义协议原始请求的响应只收到 5 字节（长度不足） — `short_read` / `reported`
- [Not getting connection error when supposed to](https://github.com/stephane/libmodbus/issues/678) — RTU 设备离线时 modbus_connect 仍返回 0 并打印 Connected，只有后续读写超时 — `timeout` / `confirmed`
- [indication timeout in server mode times out while receiving master message](https://github.com/stephane/libmodbus/issues/712) — server 模式 indication timeout 在接收客户端报文中途误触发，造成周期性请求失败 — `timeout` / `reported`
- [Timeout not respected](https://github.com/stephane/libmodbus/issues/393) — modbus_set_response_timeout 设置 10ms 不生效，实际固定阻塞约 1 秒 — `timeout` / `reported`
- [With TCP, `modbus_connect()` returns -1 on timeout but does not set `errno`](https://github.com/stephane/libmodbus/issues/736) — modbus_connect() TCP 超时返回 -1 但不设置 errno=ETIMEDOUT — `timeout` / `confirmed`
- [Modbus RTU t1.5 and t3.5 timer issues](https://github.com/stephane/libmodbus/issues/400) — RTU t1.5/t3.5 帧间隔定时器未按协议实现（维护者确认属设计取舍） — `timeout` / `confirmed`

## NModbus/NModbus（4 条）

- [Response was not of expected transaction ID. Expected 4, received 1.](https://github.com/NModbus/NModbus/issues/185) — 多线程共用 master 导致响应事务 ID 错配（Expected 4, received 1） — `malformed` / `reported`
- [Modbus RTU times out if I donot wait 100ms between reads](https://github.com/NModbus/NModbus/issues/188) — RTU 连续读取需人工 100ms 延迟，否则下一次读取超时 — `timeout` / `reported`
- [NModbus.SlaveException: Exception of type 'NModbus.SlaveException' was thrown. Function Code: 134 Exception Code: 4](https://github.com/NModbus/NModbus/issues/194) — 设备返回异常响应 FC134/EC4（Slave Device Failure），库抛 NModbus.SlaveException — `exception` / `reported`
- [Port.Read Timeout on a SerialPort](https://github.com/NModbus/NModbus/issues/173) — SerialPort 与 Transport 两层超时配置关系不清，离线设备读取超时行为困惑 — `timeout` / `reported`

## xuetianjiu/nmodbus（5 条）

- [Uninterruptible CRC error cycle during ModbusIpMaster work](https://github.com/xuetianjiu/nmodbus/issues/61) — TCP 流残帧未清理导致不可中断的 CRC 错误循环 — `crc` / `reported`
- [Timeout read operation closing TCPClient connection](https://github.com/xuetianjiu/nmodbus/issues/69) — 读超时后重试时 TCP 连接已关闭，超时异常被 Connection closed 掩盖 — `timeout` / `reported`
- [Library throw an exception instead of return a exception response for illegal function](https://github.com/xuetianjiu/nmodbus/issues/74) — 从站收到非法功能码时应返回异常响应，库却直接抛异常 — `exception` / `reported`
- [IModbusSerialMaster.ReadWriteMultipleRegisters generates an invalid CRC.](https://github.com/xuetianjiu/nmodbus/issues/76) — ReadWriteMultipleRegisters 组帧错误导致请求帧 CRC 字段错误（含逐字节对照） — `crc` / `reported`
- [WriteMultipleRegisters GSM timeout](https://github.com/xuetianjiu/nmodbus/issues/77) — GSM 链路写多寄存器（>10 个）即超时 — `timeout` / `reported`

## S7NetPlus/s7netplus（4 条）

- [ReadTimeout is always 20s](https://github.com/S7NetPlus/s7netplus/issues/427) — ReadTimeout/WriteTimeout 属性无效，拔线后固定 20s 才超时 — `timeout` / `confirmed`
- [Reconnecting to S71500 after network broken](https://github.com/S7NetPlus/s7netplus/issues/525) — 拔网线后重连 S7-1500 失败，连接实例累积到 98 — `reset` / `reported`
- [My logging application stops reading values in 0.7.0](https://github.com/S7NetPlus/s7netplus/issues/328) — 0.7.0 升级后应用持续抛 WrongNumberReceivedBytes 且连接无法恢复 — `short_read` / `confirmed`
- [Unable to read PLC DB data](https://github.com/S7NetPlus/s7netplus/issues/252) — 读 S7-1200 DB 报 'connection was forcibly closed by the remote host' — `reset` / `reported`

## rossmann-engineering/EasyModbusTCP.NET（4 条）

- [Connected is still true after disconnection](https://github.com/rossmann-engineering/EasyModbusTCP.NET/issues/16) — WiFi 断开后 Connected 仍为 true，读取时才报 IO 异常 — `reset` / `confirmed`
- [Modbus RTU per Modbus TCP Adapter: Slave not connected](https://github.com/rossmann-engineering/EasyModbusTCP.NET/issues/59) — 网关后从站未接入时返回 0x0B 异常，EasyModbus 无处理、不报错 — `exception` / `reported`
- [Read weird result from InputRegisters when open multiple modbus client](https://github.com/rossmann-engineering/EasyModbusTCP.NET/issues/90) — 第二客户端启动后第一客户端读到 -29221/9435 等错乱值 — `other` / `reported`
- [UnitIdentifier & Modbus TCP](https://github.com/rossmann-engineering/EasyModbusTCP.NET/issues/44) — TCP 服务端按 UnitIdentifier 过滤导致非 1 从站 ID 访问失败 — `other` / `reported`

## gijzelaerr/python-snap7（5 条）

- [Сonnection Nvidia Jason nano to s7-300 problem](https://github.com/gijzelaerr/python-snap7/issues/216) — Jetson Nano 连 S7-300 报 Snap7Exception: b' TCP : Connection refused' — `refused` / `reported`
- [b' ISO : An error occurred during recv TCP : Connection timed out'](https://github.com/gijzelaerr/python-snap7/issues/387) — Pi4 每 0.65s 循环 db_read 偶发 recv TCP : Connection timed out，之后失去通信 — `timeout` / `reported`
- [how to recover from an intermittent TCP timeout exception ](https://github.com/gijzelaerr/python-snap7/issues/70) — TCP 超时一次后，后续 db_read 返回错位的旧数据（疑似内部排队） — `timeout` / `reported`
- [LOGO connectivity](https://github.com/gijzelaerr/python-snap7/issues/6) — LOGO 0BA7 set_connection_params+connect 后 get_connected()=False（需 TSAP 连接方式） — `timeout` / `reported`
- [as_db_read() doesnt work](https://github.com/gijzelaerr/python-snap7/issues/481) — as_db_read 异步读恒返回 [0,0]，同址同步 db_read 正常 — `other` / `reported`

---
未收录说明：pymodbus 讨论 #2413/#2389、python-snap7 讨论 #295/#393/#415 为 GitHub Discussions（非 issue）未计入；EASYMODBUS #68、python-snap7 #51/#519 等为 API/参数类问题，非通信故障，宁缺毋滥未收。