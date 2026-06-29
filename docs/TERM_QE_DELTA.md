# 术语 QE 相比普通 QE 的更改点

普通 QE = 句子/对话/UI 文本质检（标准大文件分块流程）。术语 QE = 术语表/glossary 自审：**目标语译文本身是审校对象，没有外部 TB 可对照**（如 Master TB 自审）。本文只列两者的差异；相同部分见末节。

## 全流程对照

| 阶段 | 普通 QE | 术语 QE | 为什么改 |
|---|---|---|---|
| 输入 | 句段表，target 列是待审译文 | TB 文件；某语言列是待审译文；**顶部有说明/图例行，真表头不在第 1 行** | TB 排版自带说明行，得先删掉 |
| 读取 | `lqe_io.py read` 一步 | `mastertb_prep.py prep`（先删顶部行，再拆几个文件，见下） | 标准 read 默认表头在第 1 行、也不带词条上下文 |
| 术语检查 | 开（拿外部 TB 对照译文，`term_hits`/`term_near`） | **关**（`terms_path` 置空） | TB 本身就是审校对象，没有外部库可比 |
| 分块 | `lqe_chunk.py split`：`{id,source,target,kind,precheck,term_hits,term_near}`，按(源,译)去重 | `mastertb_prep.py chunks`：`{id,zhcn,en,definition,category,gender,th,kind,auto_flags}`，**不去重** | 判专名音译要 EN 对照 + 类别/定义来区分同名；每个词条唯一，无需去重 |
| kind 怎么定 | 按内容猜（name/desc） | **按 category 定**（name 类目→name；Creature Individual 按含「的/们」或长度细分） | 词条有明确的类别字段，不用猜 |
| lens（审校员） | T / A / G / R 四个 | **多一个 N（专名音译）**；A 只判 desc，name 交给 N；运行时附加 `_term_audit.md` | 短词条里「判音译」和「判词义」是两件事，合在一个 agent 里会盯着显眼的错、放过细的 |
| 合并 | `merge-lenses`（T 打底全 id，A/G/R 并入，改写取 A>T>G>R） | 同脚本，**N 一并并入**，改写取 **N>A>T>G>R**；`mastertb_prep merge` 再并入 `consistency.json` | 专名以 N 的音译为准；跨词条一致性单独算 |
| 完整性检查 | 无（句子流靠四个 lens 分工来减少漏判） | **缺了该跑的 lens → `verdict_allowed=false` → 不出 PASS/FAIL，只给临时下限** | 防「被限流逼得只跑一遍 → 算出虚高 PASS」（实证只跑一遍漏掉约 86%） |
| 交付物 | `_lqe.xlsx` + `_corrected.xlsx` | **多 `_审校建议.xlsx`**（给人看的清单）**+ `missing_th.xlsx`**（空译排除）**+ 待人工裁决表** | TB 审校结果交 PM 逐条定，不自动改写客户 TB |
| agent 不可用时 | — | `mastertb_prep.py view`（精简视图，一个人在主流程里逐块判，召回低、只作下限） | 限流/会话上限时的备用路径 |

## 更改点详解

### 1. 读取改用 prep
`mastertb_prep.py prep` 比 `read` 多做三件事：
- **删顶部说明行**：找到含「术语 ZHCN」的真表头行，丢掉它上面的说明/图例行，输出 `clean_input.xlsx`（真表头落到第 1 行）。
- **拆几个文件**：`context.json`（id → {zhcn, en, definition, category, gender, scope, th, th_comment, th_status}）；`consistency.json`（同源不同译、同译不同源、译文里没有目标文字、译文里残留中文）；`missing_th.xlsx`（空译行，排除审校、不计分）。
- **列定位按表头名 + 位置**：一个 TB 有多语种列、「术语状态 Status」重复出现，取目标列之后第一个 status 列。

之后照常 `read --project` 落 SG/背景/裁决/语言注记，但 **read 完把 `state.terms_path` 置空**。

### 2. 关掉术语检查
没有外部 TB 可对照：`term_hits`/`term_near` 为空，T 从「拿外部库对照」改为「只查内部一致性 + 占位/垃圾值」（译文用通用词顶替专名、误填了别的条目的值）。

### 3. 分块时带上下文
标准分块只带 source/target，判专名音译没有 EN 对照就不准。术语分块每条多带 `en`（音译对照）、`definition`、`category`、`gender`，给 N 判音译、A 判词义、区分同名。词条唯一，不做(源,译)去重。

### 4. lens 拆分（细节见 `TERM_AUDIT_LENS_DESIGN.md`）
- **新增 N（专名音译）**：跑 name 段，把译文读音和 `en` 对照；丢音节、整名认不出、撞已知品牌、人名地名安错。
- **A 只判 desc**：name 段的专名归 N，A 只判 desc 段的词义——把「判音译」和「判词义」分给两个 agent，各管一摊，免得一个 agent 盯着显眼的错、放过细的。
- **共用的 A/G/R/T 内容不改**：差异都写在 `_term_audit.md` 里、运行时附加进去（A.md 明文「跑全部段含 name 短词」，是句子流要的，全局改会砸了句子评估）。
- 分派：N 只跑 name；A、R 只跑 desc；T、G 跑全部。

### 5. 完整性检查（术语 QE 独有）
`mastertb_prep merge` 按每个 chunk 的 kind 算出「该跑哪些 lens」：`{T,G} ∪ {N if 有 name} ∪ {A,R if 有 desc}`；只要少一个，就写 `recall_status.json` `verdict_allowed=false` + 打印警告 + 在报告汇总页标「降级·临时下限」。**起因**：术语自审被限流逼得只跑一遍时，`calc` 照样能算出高分 PASS（实测 98.71 是虚高，补全后真值约 95 FAIL），所以把「流程有没有跑全」做成程序自动检查，不靠人记得。

### 6. 交付物多一层人审
TB 审校不自动改写客户 TB，结果交 PM 逐条定：`_审校建议.xlsx`（id / 剧情范围 / 类别 / 中文 / EN / 原译 / 建议译文 / 错误类别 / 严重度 / **置信** / 说明 / 状态，外加汇总页）；拦下的关键专名和分歧进 `待人工裁决_<job>.xlsx`；PM 定后回填 `terms_*.json`(status=Approved) + `adjudications.md`。

## 两个流程相同的部分
- 17 个错误子类别 + MQM-Core / ISO 5060:2024 七个父维度映射；严重度 Neutral/Minor/Major/Critical；Terminology/Untranslated/Markup/Length 一律 Major。
- 计分公式 `MAX((1 - ΣL/词数) × 100, 0)`，词数在第一轮锁定。
- lens 保持项目/语言中立，靠运行时注入：题材从 `background`、目标语规则从 `lang_notes`、裁决从 `adjudications`、风格从 `sg`。
- 脚本 `lqe_chunk.py`（merge-lenses/validate-lenses/reconcile）、`lqe_calc.py` 共用；对它们的改动一律向后兼容（句子流不产 N 文件，就跳过、不校验）。
- SKILL.md step3 的稳定性铁律共用：断点优先 / 小批波次 ≤5–6 并发 / 存活只看落盘文件 / 降级不出裁决。

## 脚本与触发
- 术语 QE 专用：`mastertb_prep.py`（prep/chunks/merge/report/view）、`docs/lenses/N.md`、`docs/lenses/_term_audit.md`。
- 共用：`lqe_chunk.py`、`lqe_calc.py`、`lqe_io.py`、`docs/lenses/{_common,T,A,G,R}.md`。
- 何时走术语 QE：输入是术语表/glossary，**且某语言列译文本身是审校对象**（没有外部权威 TB 可对照）。普通 QE 审的是句子/对话/UI，术语表只作为**外部参照**来查译文。
