---
name: lqe-translator
description: LQE scoring + self-iteration agent for AI-generated ZH→EN translations (燕云/WWM). Claude identifies errors AND provides corrected translations in one pass. Python calculates score. /loop drives iteration until score ≥ 98.
---

# LQE Translator

路径变量（每次会话开始时定义）：
```bash
SCRIPTS=~/.claude/skills/lqe-translator/scripts
```

---

## 首次启动

### 1. 收集参数

询问用户选择接入方式：

**方式 A：接入 AIPE**
- AIPE 导出的 CSV 路径（`GET /translate/task/{id}/csv`）
- AIPE 服务地址（如 `http://localhost:8000`）

**方式 B：独立使用**
- 输入 Excel 路径
- 原文列名/索引、译文列名/索引
- 风格指南路径（`.docx`/`.txt`/`.md`/`.xlsx`，可选；xlsx 多 sheet 自动转 markdown：sheet=章节、行=规则、空表头首列=分类前向填充）
- 术语表路径（`.xlsx`/`.csv`/`.tsv`/`.json`，可选；词条零宽字符自动清理；含 CJK 的 2 字词条参与 pre-check 匹配；json 词条可带 `status` 字段透传到报错注记）
- 词数基准 `--wordcount-basis`：`target-words`（默认，译文空格分词，适用 EN）/ `source-chars`（源文 CJK 字符+拉丁词，**泰语等无空格译文必选**，否则词数低估数倍、98 阈值失真）
- 目标语言 `--target-lang`（可选，`en`/`th`）：挂载 `languages/<lang>.json` 语言属性（词数基准默认、检查适用性推导、评估关注点），见方式 C 语言层说明

**方式 C：项目档案（同项目多文件复用，优先推荐）**
- `read --project <项目名>`：从 `projects/<项目名>/profile.json` 带出 SG/术语/词数基准/阈值/checks/adjudications，显式 CLI 参数优先
- `projects/<名>/` 结构：
  - `profile.json`：`{name, language_pair, style_guide, terminology, checks, adjudications, wordcount_basis, threshold, lock_statuses}`（相对路径相对 profile 所在目录解析；`lock_statuses`=哪些术语 status 算锁定，空数组=确认无锁定）
  - `checks.json`：项目专属确定性检查。`builtin` 开关内置项（键：`untranslated_cjk/em_dash/color_tags/variables/newline_count/length/locale_numbers/terminology/pos_placeholder/numbers_consistency/whitespace/fullwidth_punct/empty_target`，默认全开）；`custom` 数组：`{id, pattern(regex), where(target|source|both), category, severity, comment}`，每段命中一次报一条
  - `adjudications.md`：客户裁决/changelog 摘要——**Step 2 评估前必须 Read 注入上下文**，效力顺序通常为 实时更新要求 > Query 裁决 > SG，防止把已裁决项判成错误
- 语言层 `languages/<lang>.json`（skill 根，与 projects/ 平级；已建 `en`/`th`，schema 与新语言接入指南见 `languages/README.md`）：按 profile `language_pair` 后缀自动挂载，或 `read --target-lang` 显式指定。**属性声明制**——只放语言学事实（`script`/`word_delim`/`sentence_terminator`/`numerals`/`wordcount_basis`/`eval_notes`），不放检查开关；pre-check 由属性推导检查适用性（如 `script: cjk` 自动关 `fullwidth_punct`），read 由属性防呆（`word_delim: none` 配 target-words 词数基准时警告）。`eval_notes` 指向语言级 AI 评估关注点（泰语性别语尾/敬语/佛历等），read 拷入 `job/lang_notes.md`。合并顺序：内置默认 < 属性推导 < 项目 checks.json < CLI 显式参数。风格取向（em_dash、省略号样式、引号样式）一律留项目 checks.json——同语言不同项目实证取向相反（wwm 禁破折号、nrc-en 允许）
- 已建项目：`nrc-th`（洛克王国中→泰）、`nrc-en`（中→英）、`wwm`（燕云十六声中→英，28,534 条官方术语库）
- 注意：SKILL.md 下文的"内置规则"（Title/Sentence Mode、禁破折号、文化术语映射等）实为 WWM 规则，仅在**无 SG 且无项目档案**时兜底；有项目档案时以其 SG/checks/adjudications 为准

### 2. 初始化

```bash
pip install openpyxl requests python-docx -q
```

**方式 A：**
```bash
python "$SCRIPTS/lqe_io.py" from-aipe \
  --aipe-csv "<CSV路径>" \
  --aipe-url "<AIPE地址>" \
  --out "jobs/<文件名>/state.json"
```

**方式 B：**
```bash
python "$SCRIPTS/lqe_io.py" read \
  --input "<Excel路径>" \
  --source-col "<原文列>" \
  --target-col "<译文列>" \
  --style-guide "<SG路径>" \
  --terminology "<术语表路径>" \
  --out "jobs/<文件名>/state.json"
```

`<文件名>` 取输入文件的 stem（去扩展名）。`read` 会自动创建 `jobs/<文件名>/` 目录，并将 SG 写入 `sg.txt`，术语表写入 `terms.json`。

### 3. 术语锁定确认（首轮评估前必做）

锁定 = 判错后**跳过二次 review**：报错不可移除、不可改判，corrected 必须采用锁定译法。锁定级只能来自客户数据列或用户确认，**不得自创**：
- profile 已有 `lock_statuses`（含空数组）→ 直接生效：`read` 已给命中词条打 `locked` 标，pre-check 报错带 `[LOCKED]`
- 未定义且术语带 status/状态类列 → 列出全部取值问用户哪些算锁定；答案写回 profile.json（确认「无」写 `[]`）持久化，下批不再问；方式 B 无 profile 时把 `locked: true` 直接写进 `jobs/<名>/terms.json` 对应词条
- 术语表无任何状态信息 → 全部术语 review 时可甄别、可修改，不存在硬判级

初始化完成后告知：段落数、词数、是否加载 SG 和术语表、锁定术语数（或「全部可 review」），提示运行 `/loop`。

---

## 每轮迭代（/loop 调用时执行）

```bash
JOB=jobs/<文件名>
```

### Step 1：读取状态

Read `$JOB/state.json`，提取：
- `segments`：当前段落（取 `corrected` 若存在，否则取 `target`）
- `sg_path`：指向 `$JOB/sg.txt`，读取内容作为风格指南
- `terms_path`：指向 `$JOB/terms.json`，读取内容作为术语表
- `wordcount`：固定词数（迭代不变）
- `iteration`：当前轮次
- `adjudications_path`（项目档案带入，可空）：**非空必须 Read**，裁决内容优先于 SG，已裁决项不得判错
- `lang_notes_path`（语言层带入，可空）：非空必须 Read，作为语言级评估关注点注入（效力低于项目 SG/裁决）
- `threshold`：评分阈值（项目档案可改，默认 98），传给 lqe_calc/write/apply-fixes 的 `--threshold`

### Step 1.2：RAG 100% match 保护

评估前必须检查输入列名和样例值，识别 RAG/TM/memory 100% match 句段。Agent 自行判断，不由脚本硬编码列名。

识别信号：
- 列名含 `rag` / `tm` / `memory` / `match` / `score` / `exact` / `locked` / `100%`
- 值含 `100%` / `1.0` / `exact` / `perfect` / `locked` / `true` / `yes`

若某 segment 明确为 100% / exact / locked match：
- 不修改 target
- 不写 corrected
- 不把该段写成 actionable error
- 即使发现轻微问题，也只作为保护说明，不参与扣分和修正
- final/export 必须保留原译文

### Step 1.5：pre-check（仅第一轮）

```bash
python "$SCRIPTS/lqe_io.py" pre-check \
  --state "$JOB/state.json" \
  --out "$JOB/errors.json"
```

确定性自动检测（纯文本可判定项前移，消除 LLM 跨轮方差）：

| 检查 | 类别 | 严重度 |
|------|------|--------|
| target 含中文 | Untranslated | Major |
| 破折号 `—` | Punctuation | Minor |
| 颜色标签 `#G/#C/#Y…#E` 整对数量不匹配（源↔译） | Markup | Major |
| 变量 `{}` / `%s` 缺失或多余 | Markup | Major |
| **无索引位置占位符 `%s/%d` 顺序错位**（命名/带索引允许重排）**[R1]** | Markup | Major |
| `\n` 数量不匹配 | Markup | Major |
| **数值漏译/改值**（源阿拉伯数字未在译文出现，如伤害 100→1000）**[R6]** | Mistranslation | Major |
| `max-length` 列存在且译文超长 **[R3]** | Length | Major |
| 译文 > 1.5× 源（无 max-length 列时回退，仅非 CJK 源） | Length | Major |
| 千位分隔符缺失 | Locale convention | Minor |
| **首尾空白 / 双空格 / 译文含全角 CJK 标点（含「」『』；CJK 目标语言在语言层关）[R5]** | Punctuation | Minor |
| 术语表 source 命中但 target 缺译 | Terminology | Major |

`max-length` 列自动识别表头：`maxlen/max_length/char_limit/限长/字符上限` 等。输出作为本轮 `errors.json` 的基底。项目档案的 `checks.json` 在此生效：`builtin` 开关可关闭与项目规范冲突的内置项（如 Em-dash 允许的项目关 `em_dash`），`custom` regex 追加项目专属检查；术语报错带 `[TB:status]` 注记；带 `[LOCKED]`（profile `lock_statuses` 命中，见「术语锁定确认」）的跳过二次 review——不可移除、不可改判，corrected 必须采用锁定译法；**其余术语报错无论 status（含 Approved）评估时均可按语境甄别**。pre-check 术语匹配最长词条优先：长词条命中且译法正确时不报被包含子词。若 pre-check 命中 locked segment，Agent 评估时必须移除该段 actionable error，保持 `errors=[]`, `corrected=null`。R6 数值检查仅在源含阿拉伯数字时触发（中文数字不误报）；Agent 评估时可移除上下文误报。

### Step 2：评估所有段落

读取 `$JOB/errors.json`（pre-check 输出），对非 locked 段补充 AI 判断类错误，**同时给出修正译文**。locked 段不提供 corrected。

#### 术语注入

从 `terms_path` 加载术语表，格式化注入评估上下文：
```
=== MANDATORY TERMINOLOGY (deviation = Terminology [Major]) ===
长鸣玉    → Echo Jade
师傅/公子 → Master
...
```

#### 风格指南

优先使用 `sg_path` 文件内容。若不存在，使用以下内置规则：

**大小写**
- Title Mode（UI/技能/道具/地名/角色/成就）：名词/代词/动词/形容词/副词/≥5字母介词首字母大写；冠词/并列连词/＜5字母介词小写（首尾词除外）
- Sentence Mode（对话/描述/提示文本）：首词 + 专有名词

**标点**
- 严格对齐原文标点（原文无句号则译文不加）
- 全部使用半角标点
- 禁用破折号 `—`，改用 ` - `（两侧空格）
- 中文 `·` → ` - `（如：猫猫·珍珠 → Cat - Pearl）

**数字**
- 千位分隔符：2,000 非 2000
- 物品数量：`Item ×N`（× 前空格，× 后无空格）

**Markup**
- 颜色标签 `#G...#E` `#C...#E` `#Y...#E` 保持相对位置
- 变量 `{}` `%s` `{slot_name}` 原样保留，前后加空格
- `\n` 换行符保留

**文化术语（强制）**
- 枪→Spear，火药→Explosive Powder，师傅/公子→Master
- 龙/凤/蛟→Dragon/Phoenix/Serpent，笔→Brush，火铳→Fire Lance
- 侠→Hero，大侠→Great Hero，少侠→Young Hero

#### LQE 错误分类

| 子类别 | 权重 | 说明 |
|--------|------|------|
| Mistranslation | 1.5 | 含义偏离原文 |
| Omission | 1.5 | 漏译 |
| Addition | 1.5 | 多译 |
| Untranslated | 1.5 | 未翻译，**始终 Major** |
| Grammar | 1.5 | 语法错误 |
| Inconsistency | 1.5 | 不一致 |
| Company style | 1.5 | 违反项目风格 |
| Unidiomatic | 1.5 | 表达不自然 |
| Terminology | 1.5 | 术语不符，**始终 Major** |
| Markup | 1.5 | 标签/变量错误，**始终 Major** |
| Culture specific reference | 1.5 | 文化本地化错误 |
| Audience appropriateness | 1.5 | 译文准确但不符目标受众/语域/世界观期待 |
| Punctuation | 1.0 | 标点错误 |
| Spelling | 1.0 | 拼写错误 |
| Locale convention | 1.0 | 数字/日期格式 |
| Length | 1.0 | 超出原文1.5倍字符数，**始终 Major** |
| Other | 1.0 | 其他 |

严重级别：Neutral（0分）/ Minor（1分）/ Major（5分）/ Critical（10分）

> **父维度对齐**：17 个子类别归入 MQM-Core / ISO 5060:2024 七个一级维度 —— Terminology / Accuracy / Linguistic Conventions / Style / Locale Conventions / Audience Appropriateness / Design and Markup（+ Other）。`Culture specific reference` 与 `Audience appropriateness` 归入 Audience Appropriateness（不再错置于 Accuracy）。

> **注意**：Terminology / Untranslated / Markup / Length 的 severity 由脚本强制纠正，无论 AI 填写什么值。

> **Critical 门（可选）**：`lqe_calc.py --critical-gate` 开启后，任一 Critical 错误直接 FAIL（MQM/ISO 5060/LISA 行业硬规则）；默认关，向后兼容。`--severity-scale mqm` 切换 0/1/5/25 指数严重度档。

#### 归类决策规则

**单一归属**：每条错误只记一个类别（避免重复计分）。同一处可落多类时，按下表取最具体 / 最严的一个（对齐 MQM 决策树单维度归属）。

| 现象 | 归类 |
|------|------|
| 含义偏离原文 | Mistranslation |
| 漏内容 / 多内容 | Omission / Addition |
| 整段未译、中文残留 | Untranslated（始终 Major）|
| 错词命中术语表 **或强制文化映射**（枪→Spear、师傅→Master 等） | **Terminology**（始终 Major）|
| 不在术语表的普通错词 | Mistranslation |
| 文化专有概念译错（龙的内涵、典故、节气） | Culture specific reference |
| 译文准确但口吻 / 语域 / 世界观不符（仙侠敬语→现代俚语） | Audience appropriateness |
| 违反明文风格指南 | Company style |
| 无明文、仅表达不自然 | Unidiomatic |
| 与同文件他处译法冲突 —— **涉及术语表词条** | **Terminology** |
| 与同文件他处译法冲突 —— 其余 | Inconsistency |
| 句子不合语法（破句） | Grammar |
| 标点符号本身 | Punctuation |
| 数字 / 日期 / 货币格式 | Locale convention |
| 标签 / 变量 / 换行 | Markup（始终 Major）|
| 超长 / 截断 | Length（始终 Major）|

**严重度判定（非强制类）**
- **Critical**：卡上线 / 崩溃 / 冒犯性 / 法律风险。
- **Major**：改变含义、破坏功能、砸品牌（误译、术语、漏译）。
- **Minor**：表面瑕疵、偏好问题（轻微不自然、标点）。
- **存疑取重**（J2450 元规则）：不确定 Major / Minor → 取 Major。
- **数值错误**（技能 / 战斗数值，如 100→1000）默认 **Major**（归 Mistranslation）。
- Terminology / Untranslated / Markup / Length 由脚本强制 Major，无需手判。

### Step 3：写入评估结果

Write `$JOB/errors.json`，**所有段落都必须写入，无错误写空数组**：

```json
[
  {
    "id": 0,
    "errors": [
      {"category": "Mistranslation", "severity": "Major", "comment": "说明，引用原文/译文片段"}
    ],
    "corrected": "修正后的完整译文"
  },
  {
    "id": 1,
    "errors": [],
    "corrected": null
  }
]
```

**`corrected` 字段规则：**
- 有错误且非 locked → 必须提供修正后完整译文
- 无错误 → `null`
- RAG/TM/memory 100% locked → 必须为 `null`，不得修改

### Step 4：计算分数

```bash
python "$SCRIPTS/lqe_calc.py" \
  --state "$JOB/state.json" --errors "$JOB/errors.json" --threshold 98
```

输出：`SCORE=XX.XX STATUS=PASS/FAIL ERRORS=N WORDCOUNT=N`，以及错误分布。

### Step 5：判断与处理

**STATUS=PASS：**
```bash
python "$SCRIPTS/lqe_io.py" write \
  --state "$JOB/state.json" --errors "$JOB/errors.json" \
  --score <分数> --threshold 98
```
报告输出文件路径，**停止 /loop**。

**STATUS=FAIL：**
```bash
python "$SCRIPTS/lqe_io.py" apply-fixes \
  --state "$JOB/state.json" --errors "$JOB/errors.json" \
  --score <分数> --threshold 98 \
  --locked-ids "<逗号分隔的RAG/TM 100% match segment ids>"
```
Agent 识别到 RAG/TM/memory 100% match 后，必须通过 `--locked-ids` 或 `--locked-file` 传给脚本。脚本会强制跳过 locked 段修正，并在 LQE 表中显示 `RAG Protected / RAG Evidence`。自动存档本轮 errors → `errors_iter{N}.json`，生成 `*_lqe_iter{N}.xlsx`，将非 locked 修正写回 state。报告结果，等待下一次 `/loop`。

---

## 辅助命令

**导出修正译文**（PASS 后）：
```bash
python "$SCRIPTS/lqe_io.py" export --state "$JOB/state.json"
```
输出 `*_corrected.xlsx`：原始文件结构，target 列替换为修正后译文，其余列不变。

**术语查询**（评估前可用）：
```bash
python "$SCRIPTS/lqe_io.py" lookup-terms \
  --state "$JOB/state.json" [--ids "0,1,5"]
```

---

## 评分公式

```
K_per_category  = Σ severity_points（每条错误独立）
L_per_category  = weight × K
最终得分        = MAX((1 - ΣL / 固定词数) × 100, 0)
阈值            = 98
词数在第一轮锁定，迭代过程不变
```

---

## 文件结构

```
languages/<lang>.json     语言属性声明（语言学事实；en/th 已建，schema 见其 README.md）
languages/eval_*.md       语言级 AI 评估关注点（read 拷入 job/lang_notes.md）
projects/<项目名>/        项目档案（可复用，方式 C）
├── profile.json        SG/术语/词数基准/阈值/checks/adjudications 配置
├── checks.json         内置检查开关 + 自定义 regex 检查
├── adjudications.md    客户裁决记录（评估前必读）
└── terms_*.json        项目术语（可带 status）

jobs/<文件名>/
├── state.json          初始化一次；跨轮持久化（译文、词数、迭代历史）
├── sg.txt              风格指南全文
├── lang_notes.md       语言级评估关注点（语言层带入，可无）
├── terms.json          术语表
├── errors.json         当前轮评估结果（每轮覆盖）
├── errors_precheck.json  pre-check 输出（首轮自动生成）
├── errors_iter{N}.json   各 FAIL 轮存档（apply-fixes 自动生成）
├── *_lqe_iter{N}.xlsx    各 FAIL 轮报告
├── *_corrected.xlsx       最终修正译文；locked 段保持原 target
└── *_lqe.xlsx            最终 PASS 报告
```
