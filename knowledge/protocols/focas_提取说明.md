# focas.json 提取说明（FANUC FOCAS 库参考）

- 产出：`knowledge/protocols/focas.json`（schema 风格对齐同目录 `s7.json`/`modbus.json`）
- 生成日期：2026-10-21；提取/解析/校验脚本留档于 `out/_protocols_focas/`（`parse_inventcom.py`、`build_focas_json.py`、`verify_quotes.py`）

## 1. 来源诚实声明（重要）

**FOCAS 是发那科（FANUC）CNC 的以太网/HSSB 库 API（Windows `fwlib32.dll` / Linux `libfwlib32.so`），不是公开标准协议；其线缆级报文格式为 FANUC 私有，本文件不含任何字节布局（见 judgment #2）。** 任务原意是找「FOCAS library manual / fwlib32」官方 PDF，实际检索结果：

1. **FANUC 官方 PDF 手册（B-63xx 系列）未能从公开渠道下载获得**（官方文档仅对授权用户开放；多份第三方镜像已失效，如 multi-dnc.com 的 FOCAS 文档目录 404、PTC/Kepware 手册链接 404）。
2. 因此**主源改用 inventcom.net 的「Fanuc Focas Library」在线参考**——这是第三方（inventcom，CNCnetPDM 厂商）以 HTML 复刻的 FANUC《FANUC Open CNC FOCAS1/FOCAS2 CNC/PMC Data window library》手册内容，逐函数一页、共 664 个函数链接，内容即官方手册原文（含 Available CNC 支持表），**但非官方渠道、页码与官方 PDF 无法对应**。
3. 两份 PDF 佐证源（官方手册的影印/分发版）来自 GitHub 第三方仓库 `wheeliar/FANUC_Focas_API`（FOCAS 开发包集合仓库）：`FOCAS2_Ethernet for Linux Operator's Manual (Edition 2)` 与 `FOCAS 库函数清单`（函数名+一句话说明，17 页）。**仓库分发件未经 FANUC 验证**，仅作连接/Linux 差异与覆盖面佐证。
4. 另以 `Fwlib32.h`（FOCAS2 SDK 头文件 30i 副本，随 `wheeliar/FANUC_Focas_API`、`strangesast/fwlib` 流转）核对函数签名与 EW_* 宏值，不作主引文源。

因此：focas.json 中每一条值均为上述来源的机械提取（含逐字引文 + URL 或 PDF 物理页码），来源未给出的内容**不做虚构**，一律以 `provenance: "judgment"` + `needs: "manual_check"` 标注。如需权威校验，应向 FANUC 索取官方 FOCAS 手册（B-63xx 系列）或对照实际 SDK。

## 2. 文档与提取物料

| 项 | 值 |
|---|---|
| 主源 | Invencom FOCAS Library Reference（在线 HTML），`https://www.inventcom.net/fanuc-focas-library/`（抓取 2026-10-21） |
| 主源缓存 | `out/_protocols_focas/inventcom/`（11 个章节页 + 57 个函数页 HTML，`parse_inventcom.py` 转文本；每条 spec_ref.url 指向在线页，`verify_quotes.py` 按 URL 定位本地缓存校验） |
| PDF 佐证 1 | `knowledge/protocols/specs/FOCAS2_Ethernet_Linux_en.pdf`（108,130 字节）— FOCAS2/Ethernet for Linux Operator's Manual, Edition 2 |
| sha256 | `3546536BDCA8883456FA49DECCFE067A831AF679F31EC09AB5028F27068968F5`；下载源 `https://github.com/wheeliar/FANUC_Focas_API`（codeload main 分支 tar 包内 `Document/Linux/FOCAS2_Linux.pdf`） |
| PDF 佐证 2 | `knowledge/protocols/specs/FOCAS_function_list.pdf`（388,213 字节）— FOCAS 库函数清单（Function Name + Brief description，17 页） |
| sha256 | `17C37CF839673D83ECCC7ADD4E4A620D93528ACF4637CFA27036C2B6C9CE7FD1`；下载源同上（tar 包内 `FANUC_focas_库函数目录.pdf`） |
| 头文件 | `out/_protocols_focas/Fwlib32_30i.h`（SDK 头文件 30i 副本，仅核对签名/宏值） |
| 来源性质 | 见 §1：主源=第三方复刻的官方手册 HTML；PDF=第三方仓库分发的官方手册影印/清单；**非 FANUC 官方渠道，官方手册需向 FANUC 索取** |

## 3. 提取方法

1. inventcom HTML 经 `parse_inventcom.py` 保留结构转文本（表格行 `c1 | c2 | c3`、`typedef` 代码块原样保留）；引文逐字照抄该文本（HTML→文本允许空白差异），未改动词句，保留原拼写错误（如 `recieved`、`exetues`、`fucntion`、`Plese`、`descri bed`）。
2. 表格/列表型引文（PDF 表格行被打散或在线页表格）以 **quote 片段数组**给出：每个片段逐字、取自同一页，按原文顺序排列；entry 上以 `table_merge`/`list_merge` 提示，行列值同时落入 `values` 字段。
3. 全量机器校验：`verify_quotes.py` 将每条 quote（去空白后）在其 spec_ref 指向的本地源文本中做包含匹配，**540/540 片段全部命中**（2026-10-21 运行）。PDF 源引文对 `pdf2txt.py`（specs/ 下的脚本）产出的页标记文本校验。
4. functions 各条目的 request/response 字段表是 **FOCAS 库 API 参数层**（函数入参/出参，含 `[in]/[out]` 方向），非线缆字节布局（缺口见 judgment #2）。
5. 主源在线页无页码，spec_ref 用 `{doc, section, url, quote}`；PDF 源用 `{doc, section, page, quote}`（page=PDF 物理页）。

## 4. 覆盖范围（各节内容）

| 节 | 条目数 | 覆盖内容 |
|---|---|---|
| connection | 18 | 库文件组成 FWLIB32.DLL/FWLIBE1.DLL（INV-general）、TCP/IP socket 底座与 Embedded Ethernet（INV-dnc1）、cnc_allclibhndl3 建连、句柄生命周期（获取/线程独占/同 IP 单连接/必须释放）、HSSB 断电 EW_HSSB/EW_HANDLE、以太网 half-open 断电检测、并发客户端上限 20/10/5(3)、DNC1 与 FOCAS 关系及重连差异、Ethernet vs HSSB 函数差异（*3 系列）、新增 4 返回状态、端口 8193 示例、Linux 库（libfwlib32.so / cnc_startupprocess）（F2LX p3-4）、官方函数目录句柄类清单（F2FL p1） |
| functions | 57 | 每函数一条（签名+参数表+主要返回码+逐字引文）：句柄 6（allclibhndl/allclibhndl3/freelibhndl/settimeout/getlibopt/setlibopt）；参数/设定 6（rdparam/wrparam/rdparainfo/rdparanum/rdset/wrset）；诊断 4（diagnoss/diagnosr/rddiaginfo/rddiagnum）；位置/进给/负载 14（absolute/relative/machine/distance/rdposition/rdaxisdata/actf/acts/rddynamic/rdsvmeter/rdspmeter/rdspload）；程序 10（rdprogdir3/rdprogdir4/rdproginfo/rdprgnum/exeprgname/rdexecprog/search/delete/download/upload）；报警/状态/杂项 15（alarm/alarm2/rdalminfo/rdalmmsg/statinfo/sysinfo/modal/rdopmsg/clralm/reset/getpath/setpath/getdtailerr/rdcoordnum）；宏/刀补/坐标 2（rdmacro/rdtofs）+rdwkcdshft；PMC 2（pmc_rdpmcrng/pmc_rdpmcinfo） |
| data_types | 27 | ODB 系结构体逐 typedef 机械提取（C 代码逐字引文+字段表）：ODBAXIS/ODBACT/ODBST(16i 系版)/ODBDY/IODBPSD/ODBDGN/ODBALM/ALMINFO/ODBALMMSG/ODBPOS+POSELM/ODBAXDT/ODBSVLOAD+LOADELM/ODBSPLOAD+LOADELM/ODBSPN/PRGDIR3/ODBNC/ODBPRO/ODBEXEPRG/OPMSG/ODBM/ODBTOFS/IODBWCSF/ODBERR/ODBPARAIF/ODBSYS/IODBPMC/ODBPMCINF |
| error_codes | 56 | 总览 1 + CNC Data Window 全表 32 条（EW_PROTOCOL -17 … EW_PASSWD 17，每条含数值/含义/处理建议）+ PMC 窗口专用 3 条（EW_NOPMC(1)/EW_RANGE(3)/EW_TYPE(4)）+ 头文件补充 5 条（EW_INIERR(-14)/EW_ITLOW(-13)/EW_ITHIGHT(-12)/EW_PMC(18)/EW_PMCHANDLE(19)，HDR）+ EW_SOCKET 明细 8 条（err_no 1..7,10；err_dtno=错误发生位置）+ EW_PROTOCOL 明细 6 条（err_no 1..6）+ 以太网板错误码 1 条（超并发上限=2） |
| limits_and_timeouts | 15 | 超时单位（秒，0=无限等待）、取值建议（10s LAN/60s 低速）、单 CNC 并发上限、half-open 感知时延=设定超时、发送数据 ≤ 最大传输单元（数值未给出→judgment）、cnc_download ≤256 字符/次、cnc_upload 缓冲默认 256、程序注释 ≤48 字符、报警消息 ≤32 字符、cnc_rdaxisdata 单次 ≤4 种、MAX_AXIS 编译期 -D 表（4..32 轴）与 FS30i 高级/传统模式（32/8 轴、8/4 主轴）、Ethernet 新增返回状态；judgment 3 条 |
| **合计** | **173** | （其中 error 子表 54 行 + 2 个单条目） |

## 5. judgment 清单（3 条，均 `needs: manual_check`）

| # | id | 内容 | 理由 |
|---|---|---|---|
| 1 | `judg_default_port_8193` | FOCAS Ethernet (TCP) 默认端口 8193 | 手册正文仅以 cnc_allclibhndl3 示例出现（"its port number of the Ethernet (TCP) is 8193"），无「默认端口」规范陈述；工业通行值与第三方驱动文档（Kepware 等）一致，正式依据需 FANUC 官方以太网功能手册（如 B-63354EN）或 CNC 侧设定 |
| 2 | `judg_wire_layout` | FOCAS/Ethernet 私有线缆帧格式 | 仅能从 EW_PROTOCOL 明细侧面推知包头含「协议标记/包类型标志/方向标志/数据块」，无任何字节布局/长度字段/帧图；FOCAS 线缆协议为 FANUC 私有，需抓包或向 FANUC 索取协议文档，本文件不虚构 |
| 3 | `judg_timeout_default` | 库出厂默认超时值 | timeout 完全由调用者在 cnc_allclibhndl3/cnc_settimeout 指定，手册未给任何默认数值（仅 0=无限等待与 10s/60s 经验建议），以实际 SDK 或实测为准 |

## 6. 未覆盖 / 未提取（透明声明）

- 主源共 664 个函数页，本文件仅逐条提取 57 个与「CNC 数据读写/状态/报警/程序清单/PMC」直接相关者；其余（程序传输 *3 系列、宏执行器、HSSB 专用、NCGuide 等）未提取，函数全集可查 `out/_protocols_focas/inventcom/flist_all.txt` 与 `knowledge/protocols/specs/FOCAS_function_list.pdf`。
- 未获得官方 PDF 手册：**无官方页码可引**，spec_ref 无 `page` 的条目均为主源在线页；官方核对需向 FANUC 索取 B-63xx 系列手册。
- Available CNC（各系列 O/E/H/X 支持矩阵）逐函数存在但未逐条录入（仅代表条目提及）；ECO/模式限定等细节以在线页为准。
- Linux 手册中 cnc_startupprocess 之外的 Linux 专属函数、通信日志格式未展开。
- Kepware/PTC 驱动手册（第三方驱动商文档）下载链接已失效（404），未纳入。

## 7. 复现

```powershell
python out/_protocols_focas/parse_inventcom.py out/_protocols_focas/inventcom   # HTML->文本（需先有 inventcom/ 缓存）
python out/_protocols_focas/build_focas_json.py      # 生成 knowledge/protocols/focas.json 并打印统计
python out/_protocols_focas/verify_quotes.py         # 引文逐字校验（当前 540/540 通过）
```

统计（2026-10-21）：connection 18 / functions 57 / data_types 27 / error_codes 56 / limits_and_timeouts 15，共 **173 条**；judgment **3 条**；引文校验 **540/540** 通过。
