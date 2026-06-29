# 术语 QE 相比普通 QE 的更改点

普通 QE = 句子/对话/UI 文本质检（标准大文件分块流程）。术语 QE = 术语表/glossary 自审，**目标语译文本身是审校对象、无外部 TB 可比**（如 Master TB 自审）。本文只列两者的**差异**；相同部分见末节。

## 全流程对照

| 阶段 | 普通 QE | 术语 QE | 为什么 |
|---|---|---|---|
| 输入 | 句段表，target 是待审译文 | TB 本体；某语言列是待审译文；**顶部有说明/图例行、真表头非第 1 行** | TB 排版带说明带，须先删顶部行 |
| 读取 | `lqe_io.py read` 一步 | `mastertb_prep.py prep`（删表头偏移 + 拆产物，见下） | 标准 read 假设表头第 1 行、不带词条上下文 |
| 术语检查 | 开（对照外部 TB，`term_hits`/`term_near`） | **关**（`terms_path` 置空） | TB 自身是对象，无外部库可比 |
| 分块 | `lqe_chunk.py split`：`{id,source,target,kind,precheck,term_hits,term_near}`，按(源,译)去重 | `mastertb_prep.py chunks`：`{id,zhcn,en,definition,category,gender,th,kind,auto_flags}`，**不去重** | 专名音译要 EN 锚 + 类别/定义消歧；每词条唯一 |
| kind 路由 | 内容启发式（name/desc） | **由 category 推**（name 类目→name；Creature Individual 按 的/们/长度细分） | 词条有明确类别字段 |
| lens 集 | T / A / G / R | **+ N（专名音译）**；A 限 desc、name 归 N；注入 `_term_audit.md` | 原子词条要把"判音译"和"判词义"拆开，否则锚定漏挖 |
| merge | `merge-lenses`（T 脊柱 + A/G/R，corrected A>T>G>R） | 同脚本，**N 纳入**，corrected **N>A>T>G>R**；`mastertb_prep merge` 折叠 `consistency.json` | 专名以 N 的音译为准；跨词条一致性全局另算 |
| 召回闸 | 无（句子流靠 4-lens 结构兜底） | **缺适用 lens → `verdict_allowed=false` → 降级不出 PASS/FAIL** | 防"被限流逼成单遍→假阳 PASS"（实证单遍漏 ~86%） |
| 交付物 | `_lqe.xlsx` + `_corrected.xlsx` | **+ `_审校建议.xlsx`**（人审视图）**+ `missing_th.xlsx`**（空译排除）**+ 待人工裁决** | TB 审校产出给 PM 逐条裁决，非自动回写 |
| 降级兜底 | — | `mastertb_prep.py view`（精简视图供 inline 判，单判=低召回下限） | agent 不可用时的容错路径 |

## 更改点详解

### 1. 输入与读取（prep 取代 read）
`mastertb_prep.py prep` 在 `read` 之外多做：
- **删表头偏移**：定位含「术语 ZHCN」的真表头行，丢弃其上的说明/图例行 → `clean_input.xlsx`（真表头在第 1 行）。
- **拆产物**：`context.json`（id→{zhcn,en,definition,category,gender,scope,th,th_comment,th_status}）；`consistency.json`（同源异译/同译异源/无目标文字字符/残留 CJK）；`missing_th.xlsx`（空译文行，排除审校、不计分）。
- 列定位按表头名 + **位置**（一个 TB 多语种列重复出现「术语状态 Status」，按目标列之后第一个 status 列取）。

随后 `read --project` 照常落 SG/背景/裁决/语言注记，但 **read 后置空 `state.terms_path`**。

### 2. 术语检查关闭
TB 自身是审校对象，无外部 TB 可比：`term_hits`/`term_near` 为空，T lens 从"对照外部库"转为**纯内部一致性 + 占位/垃圾值甄别**（译文用通用词顶替专名、误填他条目值）。

### 3. 分块 schema 带上下文
标准 split 的 chunk 只带 source/target，专名音译缺 EN 锚判不准。术语 chunk 每条附 `en`（音译锚）、`definition`、`category`、`gender`，供 N 判音译、A 判词义、消歧。term 唯一，不做 (源,译) 去重。

### 4. lens 拆分（详见 `TERM_AUDIT_LENS_DESIGN.md`）
- **新增 N（专名音译）**：name 段，比对 target 读音 vs `en` 锚；丢音节/整名认不出/撞品牌/人名地名错位。
- **A 限 desc**：name 段的专名归 N，A 只判 desc 段词义——拆开"判音译/判词义"两种手艺，防一个 agent 锚定漏挖。
- **共用 A/G/R/T 内容不动**：差异全走 `_term_audit.md` 注入覆盖（A.md 明文"跑全部段含 name"，是句子流要的，不能全局改）。
- 门控：N 只 name；A、R 只 desc；T、G 全跑。

### 5. 召回闸（术语 QE 独有的硬闸）
`mastertb_prep merge` 按各 chunk 的 kind 推 `required = {T,G} ∪ {N if name} ∪ {A,R if desc}`；任一适用 lens 缺失 → 写 `recall_status.json` `verdict_allowed=false` + 横幅 + 报告汇总页标"降级·临时下限"。**根因**：术语自审被限流逼成单遍时，calc 仍会算出高分 PASS（实证 98.71 假阳，真值 ≈95 FAIL），故把"流程跑全没"做成机器闸，不靠人自觉。

### 6. 交付物多一层人审
TB 审校不自动回写覆盖客户 TB，产出给 PM 逐条裁决：`_审校建议.xlsx`（id/剧情范围/类别/中文/EN/原译/建议译文/错误类别/严重度/**置信**/说明/状态 + 汇总页）；拦下的关键专名/分歧 → `待人工裁决_<job>.xlsx`；PM 定后回填 `terms_*.json`(status=Approved) + `adjudications.md`。

## 不变（两流程共用）
- 17 子类别 + MQM-Core / ISO 5060:2024 七父维度映射；severity Neutral/Minor/Major/Critical；Terminology/Untranslated/Markup/Length 强制 Major。
- 计分公式 `MAX((1-ΣL/词数)×100, 0)`，词数首轮锁定。
- lens 项目/语言**中立 + 注入**机制：题材走 `background`、目标语规则走 `lang_notes`、裁决走 `adjudications`、风格走 `sg`。
- 脚本 `lqe_chunk.py`（merge-lenses/validate-lenses/reconcile）、`lqe_calc.py` 共用；对其改动一律**向后兼容**（句子流不产 N 文件 → 跳过/不校验）。
- SKILL.md step3 稳定性铁律共用：断点优先 / 小批波次 ≤5–6 并发 / 存活只认落盘 / 降级不出裁决。

## 脚本与触发
- 术语 QE 专属：`mastertb_prep.py`（prep/chunks/merge/report/view）、`docs/lenses/N.md`、`docs/lenses/_term_audit.md`。
- 共用：`lqe_chunk.py`、`lqe_calc.py`、`lqe_io.py`、`docs/lenses/{_common,T,A,G,R}.md`。
- 何时走术语 QE：输入是术语表/glossary 且**目标语译文列本身是审校对象**（无外部权威 TB 可比）。普通 QE 是句子/对话/UI，且术语表作为**外部参照**来查译文。
