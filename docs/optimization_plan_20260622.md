# LQE Translator Skill 优化方案

> 依据：2026-06-22 运行 `jobs/鲁老师SourceTarget0622`（1378 段 ZH→TH，nrc/th，单轮，20 子代理多-lens，终分 96.51/FAIL）。
> 每条问题均附本次实证、根因、修法、风险。原则：**优先结构性"直接报错/可回看存档"，少靠 prompt 自律**（见文末 0617 教训）。本文件只提案，不擅改代码。

---

## P0 · 静默丢数据 / 分数失真（最先修）

### 1. lens 输出 schema 漂移被 merge-lenses 静默吞掉 ★最危险
- **实证**：`chunk_02.A`/`chunk_03.A` 写成扁平 `{id,category,severity,comment,corrected}`（每错一对象），非约定的嵌套 `{id,errors:[...],corrected}`。`lqe_chunk.py` merge-lenses（约 178–180 行）`for e in load(f): if not e.get("errors"): continue` → 这 26 条发现被**静默跳过**，含 686 物种混淆、739/808 月份错、893 时间错等 Major。本次靠人工校验+归一化才补回；若不查，分数虚高、Major 漏报。
- **根因**：子代理输出格式自由 + merge-lenses 不校验、见不到 `errors` 键即跳过、无任何告警。
- **修法（结构性）**：
  - **A. merge-lenses 自检+兜底**：检测顶层带 `category` 而无 `errors` 的扁平条目 → 按 id 自动归并为嵌套 + stderr 告警；无法识别就**直接报错退出**，绝不静默跳过。
  - **B. 新增 `lqe_chunk.py validate-lenses --outdir`**：逐文件校验结构（id/errors/corrected + 每错 category/severity/comment + 类别白名单）、T 脊柱满覆盖、所有 id 齐；不过则非零退出。`finalize` 前强制跑。
  - **C. 子代理自检升级**：从"JSON 可解析"升到"结构合规"——prompt 内给最小 schema，自检失败必须重写再交。
- **风险**：低（纯校验/归并）。建议 A+B 都上。

### 2. cmd_write 单轮丢失全部建议修正（已确认 BUG）
- **实证**：`lqe_io.py` 报告生成（约 967 行）`is_final_report` 模式下 `Suggest translation` 取 `seg.corrected`（来自 **state**）。单轮未 apply-fixes → state.corrected 全空 → 65 条建议在报告里全空（errors.json 实际有）。本次以"errors.json 的 corrected 仅记录进 state（不迭代、分数不变）"绕过。
- **根因**：write 假设 state.corrected 已被 apply-fixes 填好——只对 PASS/迭代路径成立，单轮 FAIL 不成立。**所有单轮 FAIL 都会触发。**
- **修法**：cmd_write 当 `seg.corrected` 为空时回退取 `errors.json` 对应 `corrected`（即非 final 分支已有的 `current_entries[id].corrected`）。约一行。或：单轮路径自动做本次的"记录建议入 state（不迭代）"。
- **风险**：低、确定性。

---

## P1 · 正确性（把本次手工步骤固化进管线）

### 3. T-lens 透传不一致 → 假阳性 Mistranslation
- **实证**：T01/T04 把 pre-check 的 Mistranslation 当真错透传（592/600/602/604 二级密码、1316 一个），而 A（Mistranslation 唯一 owner）已判这些为 FP；T00/02/03 未透传。本次人工 reconcile 剔 5 条（存档 `reconcile_dropped.json`）。
- **根因**：透传边界模糊——`_common.md`/`T.md` 说只透传 Markup/Length/Locale 真缺，实操中 T 扩到了语义类。
- **修法**：
  - **A. 文档收紧**（`T.md`/`_common.md`）：T 只透传确定性类（Markup/Length/Locale/机械空白 Punctuation）；语义类 pre-check 项（Mistranslation/数值/N6）一律不透传，交 A 独立判。
  - **B. 结构性兜底（推荐）**：新增 `lqe_chunk.py reconcile --outdir`（或并入 merge-lenses）——A_OWNED 类（Mistranslation/Omission/Addition/Untranslated）仅当 A 文件确认该 (id,类别) 才保留，自动剔除 T 透传项并**另存** dropped 清单（不静默删，可人工回看）。去除"每个 T agent 行为必须一致"的依赖。
- **风险**：中（含改判）。先上 B 的存档式（标记+另存）。

### 4. pre-check 把 hex 色值当千分位/数值（反复出现，高 ROI）
- **实证**：`#c15100` 被读成 `15100` 报 Locale 千分位——T01 剔 644–655 共 12 条、T03 剔 969–977；`#292929` 同样（T02）。每个 chunk 都触发，耗 T 大量甄别。
- **修法（确定性）**：pre-check 在 R6/Locale/数值检查前，先屏蔽 `#[0-9a-fA-F]{3,8}` 及颜色标签内 hex。消灭整类 FP。
- **风险**：低。建议尽快做。

---

## P2 · 召回/覆盖 & 流程

### 5. A-lens 覆盖不一致
- **实证**：A 自报扫描 162/165/200/74/88（块大小 200/200/200/200/81），A03 仅 74/200。
- **风险**：name 段的语义误译可能漏（本次靠 T 兜底 + A04 抓到 name 残留，未酿事故）。
- **修法**：A prompt 明确"全段扫描含 name，自报数=块段数"；或 orchestrator 记录 A 自报扫描数对块大小，差距大即告警/补扫。把覆盖变成可审计量。

### 6. 编排手工、token 重；缺单轮一键流程
- **实证**：20 子代理手工派发（4 pilot + 16）、人工逐个跟踪+校验+归一化+reconcile+merge。`finalize_job.sh` 只覆盖 merge→calc→apply-fixes→export，**缺 merge-lenses/validate/reconcile**，且默认走迭代（apply-fixes）。
- **修法**：
  - 扩 `finalize_job.sh`：补 merge-lenses（已知缺）+ validate-lenses（#1B）+ reconcile（#3B）；加**单轮分支**（到 calc+write 止，跳 apply-fixes）。
  - lens 派发本质 agent 驱动（不可纯 bash），但把"pilot 1 块→校验→fan-out→finalize"固化成 `SKILL.md` 大文件流程下的可执行清单（含本次的并行派发模板）。

---

## P3 · 打磨

### 7. 多-lens 段 corrected=null（本次 28 段）
现状=设计（交人工整合）。可选增强：对多-lens 段补一个轻量"整合"子代理产单一 corrected，提升建议覆盖率。低优先。

### 8. N6 中文数字虚指仍 FP
"一/三"等虚指（179 下一回合、1316 一个）仍触发后由 lens 剔。可继续收紧强模式词表。

---

## 落地顺序
1. **P0**：#1A+#1B、#2（防静默错/分数失真，最先）
2. **P1**：#4（确定性高 ROI）、#3B（存档式 reconcile）
3. **P2**：#6（finalize 扩展+单轮分支）、#5
4. 文档收紧 #3A；P3 视需要

## 新增/改动清单（一览）
| 文件 | 改动 | 优先级 |
|---|---|---|
| `scripts/lqe_chunk.py` | merge-lenses 检测扁平 schema：归并+告警 / 否则报错退出 | P0 |
| `scripts/lqe_chunk.py` | 新 `validate-lenses` 子命令 | P0 |
| `scripts/lqe_io.py` | cmd_write：state.corrected 空时回退 errors.json | P0 |
| `scripts/lqe_chunk.py` | 新 `reconcile`（A_OWNED 归属权威化+存档） | P1 |
| `scripts/lqe_io.py` | pre-check：先屏蔽 hex 色值再做数值/Locale | P1 |
| `scripts/finalize_job.sh` | 补 merge-lenses/validate/reconcile + 单轮分支 | P2 |
| `docs/lenses/T.md`,`_common.md` | 收紧透传边界（只确定性类） | P1 |
| `docs/lenses/A.md` + 大文件流程 | A 全段覆盖+自报数=块大小；编排 recipe | P2 |
| `SKILL.md` | 大文件流程补可执行清单/并行派发模板 | P2 |

## 0617 教训提醒
LQE 工具改动须谨慎：优先"直接报错 / 可回看存档"的结构性兜底，而非靠 prompt 自律（弱模型会绕）。改 `lqe_io.py`/`lqe_chunk.py` 前人工确认；改完先同步 dev 仓 Langlobal/lqe-translator 与本地 skill 副本，再统一改。
