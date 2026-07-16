---
name: lqe-translator
description: "LQE scoring and review workflow for game-localization translations. Project profiles provide language settings, style guides, terminology, confirmed rules, deterministic checks, scorecards, and Excel reports. AI check modules report issues and safe local edits; Python validates edits, builds corrected text, and calculates scores. Triggers: LQE/LQA, 译文质检/评估/打分, translation QA."
---

# LQE Translator

每次会话先定义：

```bash
SCRIPTS=~/.codex/skills/lqe-translator/scripts
```

## 1. 收集输入

需要：

- Excel、CSV、TSV，或 SDLXLIFF 1.2 路径；SDLXLIFF 可传单文件或目录。
- 表格输入的原文列和译文列；SDLXLIFF 从句段结构读取，不需要列名。
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
  "protected_term_statuses": [],
  "sdlxliff": {
    "tm_protection": "candidate-only",
    "content_type_rules": [
      {"id": "dialog", "glob": "**/dialog*.sdlxliff", "content_type": "剧情/对话"}
    ],
    "exclude_rules": [
      {"id": "rejected", "field": "confirmation", "equals": "Rejected", "reason": "Client excluded"}
    ]
  }
}
```

`language_pair`、`source_lang`、`target_lang` 必填。相对路径以 profile 所在目录为基准。`protected_term_statuses` 只能来自客户资料或用户明确确认；空数组表示没有受保护的术语状态。

目标语言事实放在 `target_languages/<code>/attributes.json`，语言级检查说明放在 `eval_notes.md`。合并顺序为：内置默认 < 语言属性 < 项目 `checks.json` < CLI 参数。

项目规则顺序：实时要求 > `confirmed_rules.md` > 风格指南 > 通用检查方法。运行检查前必须读取项目背景、确认规则、风格指南和语言说明。

## 2. 初始化

```bash
pip install "openpyxl>=3.1" regex requests python-docx -q

python "$SCRIPTS/lqe_io.py" read \
  --project "<game>/<source>-<target>" \
  --input "<输入文件>" \
  --source-col "<原文列>" \
  --target-col "<译文列>" \
  --out "jobs/<文件名>/state.json"
```

SDLXLIFF 初始化：

```bash
python "$SCRIPTS/lqe_io.py" read \
  --project "<game>/<source>-<target>" \
  --input "<SDLXLIFF 文件或目录>" \
  --input-format sdlxliff \
  --out "jobs/<文件名>/state.json"
```

`--input-format` 可取 `auto`、`tabular`、`sdlxliff`，默认 `auto`。单个 `.sdlxliff` 或只含 SDLXLIFF 的目录可自动识别；混有表格文件的目录必须显式使用 `--input-format sdlxliff`，未选中的受支持文件会记录在来源清单。目录会递归读取并按相对路径排序。表格目录仍不支持。

第一版只接受带 SDL namespace 的 XLIFF 1.2/SDLXLIFF 1.2；XLIFF 2.0 明确失败。未知厂商扩展若不影响句段定位、文本边界和 `mid` 配对，会保留证据并记录 namespace；存在结构歧义时失败，不猜测。内容类型与排除只能来自 profile 的显式 `sdlxliff.content_type_rules` 和 `sdlxliff.exclude_rules`，不得根据 CC、FF、文件名或目录名推断。

任务明确要求“不检查术语”时，在同一条 `read` 命令加入 `--no-terminology`。该参数高于 profile 的术语配置，且不能与显式 `--terminology <file>` 同时使用。初始化会把解析后的模式写入 `state.check_scope`，并在 job 根目录生成内容相同的 `scope.json`。

`--no-terminology` 只关闭术语、专名和术语审计；不会关闭文件内一致性、Markup、数字等检查。初始化后报告段数、词数、语言、检查模式、启用模块、风格指南、确认规则、术语表和受保护内容的加载情况。

以下可见合同精确定义两种模式，所有入口都以解析后的 scope 为准：

<pre data-lqe-scope-contract>
{
  "mode_flag": "--no-terminology",
  "standard": {
    "required": ["terminology", "accuracy", "grammar", "naturalness"],
    "optional": ["proper_names"]
  },
  "no-terminology": {
    "required": ["precheck_review", "accuracy", "grammar", "naturalness"],
    "optional": [],
    "disabled": ["terminology", "proper_names", "term_audit"]
  },
  "scope_artifact": {
    "path": "scope.json",
    "state_field": "state.check_scope",
    "relation": "same resolved scope"
  },
  "kept_checks": ["file-wide consistency", "Markup", "numeric checks"]
}
</pre>

## 3. 术语标记

本节只适用于标准模式；无术语模式不读取或使用术语条目。

原始术语表没有 `confirmed`、`approved`、`status` 等明确确认字段，且项目资料没有提供“哪些状态等于已确认”的映射时，**必须在初始化前询问用户**如何处理。不得根据文件名、工作表名或“通常如此”自行决定；**不得默认全部已确认，也不得默认全部未确认**。在用户回答前，不生成正式 `terms_*.json`、不运行术语预检、不评分。

询问时明确给出三种处理口径：

1. 整份术语表视为已确认；唯一译法写 `confirmed: true`，多译词保留候选并按语境判断。
2. 整份术语表仅作未确认参考；写 `confirmed: false`。
3. 用户提供逐行规则或状态映射后再转换。

<pre data-lqe-term-confirmation-contract>
{
  "trigger": "terminology has no explicit confirmation field or confirmed-status mapping",
  "required_action": "ask_user_before_initialization",
  "forbidden_defaults": ["all_confirmed", "all_unconfirmed"],
  "choices": [
    "treat_entire_glossary_as_confirmed",
    "treat_as_unconfirmed_reference",
    "provide_row_or_status_mapping"
  ]
}
</pre>

术语条目或多义候选必须显式带：

```json
{"source":"源词","target":"译法","confirmed":false,"protected":false}
```

- `confirmed: true`：客户已经确认该译法；匹配证据完整时允许安全局部修改。
- `protected: true`：不可修改。
- 完成上述用户确认后，转换结果必须显式写出两个字段；不得依赖缺失字段的隐式默认值，也不要根据未映射的 `status` 自行推断 `confirmed`。
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

SDLXLIFF 的保护规则单独处理：

- SDL 明确 locked 的段初始化时自动保护为 `SOURCE_LOCKED`，不依赖 TM 策略。
- 默认 `candidate-only` 只把同时满足 `origin=tm`、`percent=100`、`text-match=SourceAndTarget` 的段写入 `tm_candidates.json`，不会自动保护。
- 确认候选后，可用上面的 `protect-segments` 命令把 `tm_candidates.json` 作为 `--protected-file`；或者在 profile 使用 `protect-exact-source-and-target`。
- CLI `--protect-exact-tm` 等同于当次显式启用严格自动保护，并优先于 profile。普通 100% 值或缺少任一条件都不保护。
- locked 与 TM 同时命中时，主原因仍为 `SOURCE_LOCKED`，两类证据分别保留。

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

流程要求 subagent 并行检查时，如果因并发上限、权限、工具不可用或运行环境限制而无法启用，**必须主动询问用户**如何处理；**不得静默回退**为主 Agent 单跑、跳过模块、缩小覆盖范围或降低检查标准。用户明确同意替代方案后才能继续。

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

LQE 报告使用富文本显示修改差异：原译中删除或替换的内容显示为红色删除线，建议译文中新增或替换的内容显示为红色字体。corrected 文件不添加差异样式。

SDLXLIFF 的 `LQE Results` 固定为 11 列：来源文件、TU ID、SDL Segment ID、原文、原译、建议译文、处理方式、错误详情、LQE_Iter、Protected、Protection Evidence。其余 SDL 私有字段、文件 SHA-256、语言、扩展 namespace、规则命中、排除和保护证据写入 `source_manifest.json`。SDL corrected Excel 固定为 5 列：来源文件、TU ID、SDL Segment ID、原文、译文。

第一版不回写 SDLXLIFF XML；`export` 只生成 `<任务名>_corrected.xlsx`，原始 XML 保持不变。

## 10. 多工作表

每个工作表单独建立子 job，完成检查后聚合：

```bash
python "$SCRIPTS/aggregate_sheets.py" \
  --job <文件名> \
  [--sheets 剧情,功能,社媒] \
  [--threshold 98]
```

聚合结果放在父 job 目录，保留原工作簿工作表、空行、列顺序和格式，只替换目标列。

该聚合命令只用于表格工作簿；SDLXLIFF 目录是一个多文件 job，不建立多工作表子 job。

## 11. 文件结构

```text
jobs/<文件名>/
├── state.json
├── scope.json
├── source_manifest.json       # SDLXLIFF job
├── tm_candidates.json         # SDLXLIFF job；默认只是候选
├── sg.txt
├── background.md
├── lang_notes.md
├── confirmed_rules.md
├── terms.json                 # 仅标准模式需要落盘转换时存在
├── errors_precheck.json
├── errors.json
├── chunks/
├── <任务名>_lqe.xlsx
└── <任务名>_corrected.<ext>   # SDLXLIFF job 固定为 .xlsx
```

不要修改用户原始 Excel，也不要改写历史 `outputs`。任务产物只写入对应 job 目录。

## 12. 验证

```bash
python3 -m unittest -v tests.test_correction_builder
python3 -m unittest -v tests.test_corrected_ownership
python3 -m unittest -v tests.test_no_terminology_mode
python3 -m unittest -v tests.test_sdlxliff_input
python3 -m unittest -v tests.test_documented_contract
python3 -m unittest -v tests.test_plain_language
python3 scripts/run_tests.py
```
