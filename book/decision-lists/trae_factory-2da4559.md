# 收尾决策清单：trae_factory（@2da4559）

> 日期：2026-10-22 ｜ 收尾人：JosephIvon（所有者授权）｜ 停机点：`2da4559`
> 战役窗口：2026-10-19 → 2026-10-22（基线 `ae91bd1`/`3e58a42` → 收尾提交 `2da4559`）

## 一、否决了什么

- **V1 死会话路径作知识库回退根**：`gen/truth_kb.js:24` 回退根指向已消亡的
  minimax 会话工作区（`mvs_838bec01…`）。裁决：唯一事实源是 mcopilot
  `knowledge/sdks/` 官方绑定行号（truth_kb.js 头注自述），回退根必须指现行家
  `%WORKSPACE%\mcopilot`。与 mcopilot 0cfc358 路径清偿同类债，本次清偿。
- **V2 bin/exe 入库**：仓内零先例（ls-files 无 bin/、无 .exe）。裁决：gitignore
  `bin/`；产物以 .zip 按既有惯例跟踪。
- **V3 运行日志入库**：根目录 glue_*.txt 为一次性生成日志。裁决：gitignore
  `glue_*.txt`，不入库。

## 二、划了什么边界

- **B1 全品牌套件不含 ACS**：其适配器引用官方 ACS.SPiiPlusNET.dll，缺 DLL 整套
  编不过；单独生成专用套件（`gen/index.js:66-68` 原文边界）。
- **B2 真值链只标注不改写**：两边口径不一致时显式列出人工裁决，绝不悄悄选边
  （`gen/truth_kb.js:7-8`）；未收录品牌显式降级不中断生成。
- **B3 out_v_unique/ 冻结为迁居凭证**：mcopilot 2026-10-22 分流的 29 件独有资产
  接收地，原样入库（tech-debt.md、factory_bad.html 等），不整合不重排。
- **B4 收尾期间不动上游**：mcopilot 侧只读（verify_trae_pinvoke.py 跑在 mcopilot
  工作目录，未写其任何文件）。

## 三、选了什么真值锚点

- **T1 跨仓真值桥全 [OK]**：mcopilot `scripts/verify_trae_pinvoke.py` 当日实跑
  退出码 0，58 条 P/Invoke 逐条 `[OK] ← <厂商>.csv:行号`。
- **T2 再生一致性**：`node test_gen.js all` 当日实跑退出码 0——全品牌套件
  22 文件/3372 行 + 温控 7 文件，产物与 gen 源同源可再生（P/Invoke 58 条：
  知识库钉扎 49 / 未收录降级 9）。
- **T3 产物自证无效**：工厂产物的"对"由 mcopilot 官方绑定与编译门（build_net48.bat
  零安装 csc）外部裁决，生成器自述不作为验收依据。
- **T4 Tier C 真机挂起**：生成的适配器无真机波次验证——设计性挂起，记入
  待实测清单，不是完成声明。

## 四、付出了什么代价

- **C1 NODE_OPTIONS 首跑失败**：`--encoding` 不被允许，node 退出码 9——改用
  `chcp 65001`。教训：跨工具编码设置没有可移植速记，逐工具验证。
- **C2 死路径期间的部分产物带降级真值链**：mc_all/mb_temp 已由本次再生刷新；
  其余品牌套件（mc_gts/mc_leadshine/mc_gaochuan/mc_softwin/mc_zmotion）的
  TruthChain.md 生成于修复前，**真值链完整度未逐份复核**（代码层无虞——T1
  真值桥已全 [OK]）。未结清项：如需逐份刷新，对每品牌重跑
  `node test_gen.js <brand>`。
- **C3 再生时点不一致**：mc_all/mb_temp 为修复后再生（2026-10-22），其余品牌
  套件为并行流先前生成——同一仓库内产物生成时点混排，如实登记，不粉饰。

## 五、R1 四件套核验

| 件 | 状态 |
|---|---|
| 同步文档 | ✅ 本清单 + commit message 全记录（`2da4559`） |
| 处置未提交 | ✅ 收尾前 71 条（54 M + 17 ??）逐件裁决 → 收尾后 0 未提交 |
| 决策清单 | ✅ 本文件（书仓归档 `decision-lists/trae_factory-2da4559.md`） |
| 明确停机点 | ✅ `2da4559`；真机层设计性挂起 |

## 六、清偿追记（2026-10-22）

- **C2 已清偿**（`954c210`）：五品牌套件修复后逐个再生——gts 19/22、
  leadshine 13/16、zmotion 17/20 钉扎（高川/软赢 0 条 P/Invoke，无真值链可挂
  属设计事实）；TruthChain.md ×5 全部刷新为现行知识库口径。
- C1/C3 为一次性过程代价，已如实入账，无后续动作。
