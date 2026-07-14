---
name: lqe-translator
description: LQE scoring and review workflow for game-localization translations. Project profiles provide language settings, style guides, terminology, confirmed rules, deterministic checks, scorecards, and Excel reports. AI check modules report issues and safe local edits; Python validates edits, builds corrected text, and calculates scores. Triggers: LQE/LQA, 译文质检/评估/打分, translation QA.
---

# LQE Translator

每次会话先定义：

```bash
SCRIPTS=~/.codex/skills/lqe-translator/scripts
```

## 1. 收集输入

需要：

- Excel、CSV 或 TSV 路径。
- 原文列和译文列。
- 项目语言轨，如 `nrc/zh-th`、`nrc/zh-en`、`wwm/zh-en`。
- 是否启用自动迭代；默认只跑首轮。

优先使用 `read --project <game>/<source>-<target>`。用户只给游戏名时，列出该游戏已有语言轨；没有目标语言轨时，先建立 profile，不回退到另一套临时入口。

项目目录：

```text
projects/<game>/<source>-<target>/
├── profile.json
├── checks.json
├── confirmed_rules.md
├── terms_*.json
└── sg*.md / sg*.txt
```

`profile.json` 常用字段：

```json
{
  "name": "nrc/zh-th",
  "language_pair": "zh-th",
  "source_lang": "zh",
  "target_lang": "th",
  "background": "项目背景",
  "style_guide": "sg.md",
  "terminology": "terms.json",
  "checks": "checks.json",
  "confirmed_rules": "confirmed_rules.md",
  "wordcount_basis": "source-chars",
  "threshold": 98,
  "protected_term_statuses": []
}
```

`language_pair`、`source_lang`、`target_lang` 必填。相对路径以 profile 所在目录为基准。`protected_term_statuses` 只能来自客户资料或用户明确确认；空数组表示没有受保护的术语状态。

目标语言事实放在 `target_languages/<code>/attributes.json`，语言级检查说明放在 `eval_notes.md`。合并顺序为：内置默认 < 语言属性 < 项目 `checks.json` < CLI 参数。

项目规则顺序：实时要求 > `confirmed_rules.md` > 风格指南 > 通用检查方法。运行检查前必须读取项目背景、确认规则、风格指南和语言说明。

## 2. 初始化

```bash
pip install openpyxl requests python-docx -q

python "$SCRIPTS/lqe_io.py" read \
  --project "<game>/<source>-<target>" \
  --input "<输入文件>" \
  --source-col "<原文列>" \
  --target-col "<译文列>" \
  --out "jobs/<文件名>/state.json"
```

任务明确要求“不检查术语”时，在同一条 `read` 命令加入 `--no-terminology`。该参数高于 profile 的术语配置，且不能与显式 `--terminology <file>` 同时使用。初始化会把解析后的模式写入 `state.check_scope`，并在 job 根目录生成内容相同的 `scope.json`。

`--no-terminology` 只关闭术语、专名和术语审计；不会关闭文件内一致性、Markup、数字等检查。初始化后报告段数、词数、语言、检查模式、启用模块、风格指南、确认规则、术语表和受保护内容的加载情况。

## 3. 术语标记

本节只适用于标准模式；无术语模式不读取或使用术语条目。

术语条目或多义候选必须显式带：

```json
{"source":"源词","target":"译法","confirmed":false,"protected":false}
```

- `confirmed: true`：客户已经确认该译法；匹配证据完整时允许安全局部修改。
- `protected: true`：不可修改。
- 缺失的两个字段按 `false` 处理；不要根据 `status` 自行推断 `confirmed`。
- profile 的 `protected_term_statuses` 只负责把明确列出的状态映射为 `protected: true`。

## 4. TM 100% 匹配保护

输入自带 match 信息时，Agent 先检查列名、样例值和证据，再生成明确的 id 列表。脚本不猜列名或值。

```json
{"protected_ids":[0,12],"source":"agent_decision","evidence":"exact TM match"}
```

```bash
python "$SCRIPTS/lqe_io.py" protect-segments \
  --state "$JOB/state.json" \
  --protected-file "$JOB/tm_protected.agent_decision.json" \
  --reason TM_100_MATCH
```

项目配置了本地 TM 时：

```bash
python "$SCRIPTS/tm_index.py" build \
  --libraries <profile.tm.libraries...> \
  --out <profile.tm.index>

python "$SCRIPTS/tm_index.py" tm-match \
  --state "$JOB/state.json" \
  --index <profile.tm.index> \
  --out-protected "$JOB/tm_protected.json"
```

只有源文精确匹配且当前译文属于该源文的已收录译法时才保护。受保护段不修改、不扣分，报告和导出保留原译。

## 5. 机器预检

首轮运行：

```bash
python "$SCRIPTS/lqe_io.py" pre-check \
  --state "$JOB/state.json" \
  --out "$JOB/errors_precheck.json"
```

预检覆盖：未翻译内容、空译文、变量、标签、换行、数字、长度、空格、全角标点、句尾标点、中文数字与量词、重复词、词内大小写、成对标点、拼音残留、文件内一致性和项目自定义规则。标准模式还运行术语命中、术语大小写和依赖术语表的专名检查；无术语模式从源头跳过这些术语检查。

`checks.json` 的 `builtin` 可关闭不适用项，`custom` 可增加 regex 或 `count_match` 检查。语言属性会自动关闭不适用于目标语言的检查。预检结果仍需按上下文复核。

## 6. 检查模块

大文件按模块并行检查；小文件也使用同一协议。模块说明位于：

```text
docs/check_modules/common.md
docs/check_modules/terminology.md
docs/check_modules/precheck_review.md
docs/check_modules/accuracy.md
docs/check_modules/grammar.md
docs/check_modules/naturalness.md
docs/check_modules/proper_names.md
docs/check_modules/term_audit.md
```

每个子任务读取 `common.md`、自己的模块文件、项目上下文和 chunk。模型只提交检查结果，不生成整段最终译文。

唯一输出协议：

```json
[
  {
    "id": 0,
    "issues": [
      {
        "category": "Grammar",
        "severity": "Minor",
        "comment": "The verb form does not agree with the subject.",
        "needs_confirmation": false,
        "edit": {
          "from": "are",
          "to": "is",
          "start": 4,
          "end": 7,
          "evidence": null
        }
      }
    ]
  }
]
```

固定接口为 `{id, issues:[{category,severity,comment,needs_confirmation,edit}]}`。检查模块不得输出 corrected；`lqe_corrections.py` 验证局部修改后生成该内部字段。

- 所有必需模块覆盖全部 id；无问题写 `issues: []`。
- `comment` 统一用英文。
- 安全、唯一、局部的改法写 `needs_confirmation: false` 和 `edit`。
- 新译名、术语表错误或缺词、多个合理方案、整句重写写 `needs_confirmation: true` 和 `edit: null`。
- 术语或专名修改必须引用唯一的 `confirmed: true` 候选，证据格式为 `{"type":"confirmed_term","source":"...","target":"..."}`。
- 变量、标签、换行、受保护文本和受保护段不得被修改。

模块分工：

| 模块 | 类别 |
|---|---|
| `terminology` | Terminology、Inconsistency、Company style、预检复核 |
| `precheck_review` | 无术语模式下复核 Markup、Length、Locale convention、Company style、非术语 Inconsistency 和 Other 预检 |
| `accuracy` | Mistranslation、Omission、Addition、Untranslated |
| `grammar` | Grammar、Spelling、Punctuation |
| `naturalness` | Audience appropriateness、Culture specific reference、Unidiomatic |
| `proper_names` | 术语表自检中的专名音译 |

## 7. 分块流程

```bash
python "$SCRIPTS/lqe_chunk.py" split \
  --state "$JOB/state.json" \
  --errors "$JOB/errors_precheck.json" \
  --outdir "$JOB/chunks" \
  --size 100
```

`split` 会从 state 读取当前模式允许的术语，按相同源文和译文去重、过滤被更长术语覆盖的命中、保留术语候选标记，并为每段写 `kind`。标准模式可用 `--terms <file>` 显式覆盖术语源；无术语模式禁止该参数。密集内容可加 `--char-budget N`。

必需输出由 `state.check_scope` 决定：

```text
# 标准模式
chunk_NN.terminology.json
chunk_NN.accuracy.json
chunk_NN.grammar.json
chunk_NN.naturalness.json

# 无术语模式
chunk_NN.precheck_review.json
chunk_NN.accuracy.json
chunk_NN.grammar.json
chunk_NN.naturalness.json
```

术语表自检可再写 `chunk_NN.proper_names.json`。段数超过 30 时按 `common.md` 使用 `ckpt-append` 和 `ckpt-finalize`。

结构检查与合并：

```bash
python "$SCRIPTS/lqe_chunk.py" validate-checks --job "$JOB"
python "$SCRIPTS/lqe_chunk.py" merge-checks --job "$JOB"
python "$SCRIPTS/lqe_chunk.py" reconcile --job "$JOB"
python "$SCRIPTS/lqe_chunk.py" merge \
  --state "$JOB/state.json" \
  --errors "$JOB/errors_precheck.json" \
  --outdir "$JOB/chunks" \
  --out "$JOB/errors.json"
```

`validate-checks` 按 `state.check_scope` 要求当前四个必需模块结构正确且 id 完整。`merge-checks` 合并并去重问题；`reconcile` 确保准确性类别只由 `accuracy` 模块确认；`merge` 广播重复段、恢复必须保留的确定性问题，并由脚本生成最终内部结果。

一键收尾：

```bash
bash "$SCRIPTS/finalize_job.sh" "$JOB" <nchunks> [single|iterate]
```

`single` 只生成首轮报告和建议译文；`iterate` 在未达阈值时应用已验证修改。用户未明确选择时使用 `single`。

## 8. 评分

```bash
python "$SCRIPTS/lqe_calc.py" \
  --state "$JOB/state.json" \
  --errors "$JOB/errors.json" \
  --threshold 98
```

```text
K_per_category = Σ severity_points
L_per_category = weight × K
score = max((1 - ΣL / 固定词数) × 100, 0)
```

默认严重度点数：Neutral 0、Minor 1、Major 5、Critical 10。默认阈值 98。词数在初始化时固定。相同源译文段的同类同级问题默认只首次计分；`--no-repeat-dedup` 可关闭该规则。`--critical-gate` 可让任一 Critical 直接 FAIL；`--scorecard-profile lqe_2026` 使用 2026 评分卡。

脚本强制 Terminology、Untranslated、Markup、Length 为 Major。受保护段自动跳过计分。

## 9. 报告、迭代和导出

PASS 或单轮模式：

```bash
python "$SCRIPTS/lqe_io.py" write \
  --state "$JOB/state.json" \
  --errors "$JOB/errors.json" \
  --score <分数> \
  --threshold 98
```

用户明确启用自动迭代且结果为 FAIL 时：

```bash
python "$SCRIPTS/lqe_io.py" apply-fixes \
  --state "$JOB/state.json" \
  --errors "$JOB/errors.json" \
  --score <分数> \
  --threshold 98
```

导出建议译文：

```bash
python "$SCRIPTS/lqe_io.py" export \
  --state "$JOB/state.json" \
  --errors "$JOB/errors.json"
```

报告面向用户显示“建议修改、需要人工确认、保持原译、已保护”。`*_corrected.<ext>` 是标准交付文件名；其中 corrected 仅是内部机器字段和标准文件名的一部分。

## 10. 多工作表

每个工作表单独建立子 job，完成检查后聚合：

```bash
python "$SCRIPTS/aggregate_sheets.py" \
  --job <文件名> \
  [--sheets 剧情,功能,社媒] \
  [--threshold 98]
```

聚合结果放在父 job 目录，保留原工作簿工作表、空行、列顺序和格式，只替换目标列。

## 11. 文件结构

```text
jobs/<文件名>/
├── state.json
├── scope.json
├── sg.txt
├── background.md
├── lang_notes.md
├── confirmed_rules.md
├── terms.json                 # 仅标准模式需要落盘转换时存在
├── errors_precheck.json
├── errors.json
├── chunks/
├── <任务名>_lqe.xlsx
└── <任务名>_corrected.<ext>
```

不要修改用户原始 Excel，也不要改写历史 `outputs`。任务产物只写入对应 job 目录。

## 12. 验证

```bash
python3 -m unittest -v tests.test_correction_builder
python3 -m unittest -v tests.test_corrected_ownership
python3 -m unittest -v tests.test_no_terminology_mode
python3 -m unittest -v tests.test_documented_contract
python3 -m unittest -v tests.test_plain_language
python3 scripts/run_tests.py
```
