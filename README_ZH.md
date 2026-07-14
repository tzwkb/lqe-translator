# LQE Translator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Agent Skill](https://img.shields.io/badge/Agent%20Skill-Codex-blue.svg)](SKILL.md)
[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)

[English](README.md) | 中文

用于游戏本地化 LQE：先做机器预检，再由专项检查模块报告问题和安全的局部修改，最后由 Python 校验、评分并生成 Excel 交付文件。

> 项目经理可直接阅读独立版 [PM 操作手册](PM_GUIDE.html)。

## 核心约束

- 项目上下文来自 `profile.json`、`confirmed_rules.md`、风格指南和目标语言说明；标准模式还加载术语表。
- 标准模式必需模块为术语、准确性、语法和自然度；无术语模式必需模块为 `precheck_review`、准确性、语法和自然度，专名模块只在标准模式下可选。
- 模型只提交 `issues` 和安全的局部 `edit`；Python 校验后生成内部完整文本。
- `confirmed: true` 表示该译法已经确认，可在证据唯一时安全修改；`protected: true` 表示不可修改。
- 受保护段不修改、不计分。
- SDLXLIFF 1.2 可直接读取单文件或递归目录，不需要先转换为工作簿。
- Excel 标准交付文件为 `<任务名>_lqe.xlsx` 和 `<任务名>_corrected.xlsx`。

## 目录结构

```text
lqe-translator/
├── scripts/
│   ├── lqe_io.py           # 读取、预检、保护、报告和导出
│   ├── lqe_chunk.py        # 分块、校验、合并和归属处理
│   ├── lqe_corrections.py  # 校验局部修改并生成完整文本
│   ├── lqe_calc.py         # LQE 评分
│   └── finalize_job.sh     # 从校验到导出的一键收尾
├── docs/check_modules/
│   ├── common.md
│   ├── terminology.md
│   ├── precheck_review.md
│   ├── accuracy.md
│   ├── grammar.md
│   ├── naturalness.md
│   ├── proper_names.md
│   └── term_audit.md
├── target_languages/<code>/
│   ├── attributes.json
│   └── eval_notes.md
├── projects/<game>/<source>-<target>/
│   ├── profile.json
│   ├── checks.json
│   ├── confirmed_rules.md
│   ├── terms_*.json
│   └── sg*.md / sg*.txt
└── jobs/<任务名>/
    ├── state.json
    ├── scope.json
    ├── source_manifest.json       # SDLXLIFF 任务
    ├── tm_candidates.json         # SDLXLIFF 任务
    ├── confirmed_rules.md
    ├── errors_precheck.json
    ├── errors.json
    ├── chunks/
    ├── <任务名>_lqe.xlsx
    └── <任务名>_corrected.xlsx
```

## 安装与路径

```bash
pip install openpyxl requests python-docx -q
SCRIPTS=~/.codex/skills/lqe-translator/scripts
```

在 skill 根目录运行回归测试：

```bash
python3 scripts/run_tests.py
```

## 标准流程

### 1. 初始化

优先使用项目档案；一个参数即可加载语言设置、检查项、确认规则、术语和风格指南。

```bash
JOB="jobs/<任务名>"
python3 "$SCRIPTS/lqe_io.py" read \
  --project "<game>/<source>-<target>" \
  --input "<file>.xlsx" \
  --source-col "<原文列>" \
  --target-col "<译文列>" \
  --out "$JOB/state.json"
```

项目档案必须声明 `language_pair`、`source_lang` 和 `target_lang`。运行检查前，必须读取项目背景、`confirmed_rules.md`、风格指南和语言说明。

任务明确不检查术语和专名时，在 `read` 中加入 `--no-terminology`。该参数覆盖 profile 术语配置，且不能与显式 `--terminology <file>` 同时使用：

```bash
python3 "$SCRIPTS/lqe_io.py" read \
  --project "<game>/<source>-<target>" \
  --input "<file>.xlsx" \
  --source-col "<原文列>" \
  --target-col "<译文列>" \
  --no-terminology \
  --out "$JOB/state.json"
```

解析后的模式写入 `state.check_scope`，并同步生成 `$JOB/scope.json`。无术语模式只关闭术语、专名和术语审计；不会关闭文件内一致性、Markup、数字等检查。

SDLXLIFF 可传单个 `.sdlxliff` 文件或目录。`--input-format` 可取 `auto`、`tabular`、`sdlxliff`；单文件和只含 SDLXLIFF 的目录可自动识别，混合格式目录必须显式指定。SDLXLIFF 直接读取句段，不使用 `--source-col` 或 `--target-col`：

```bash
python3 "$SCRIPTS/lqe_io.py" read \
  --project "<game>/<source>-<target>" \
  --input "<文件或目录>" \
  --input-format sdlxliff \
  --out "$JOB/state.json"
```

第一版只支持带 SDL namespace 的 XLIFF 1.2/SDLXLIFF 1.2；XLIFF 2.0 明确失败。未知厂商扩展若不影响句段边界会保留并记录，若造成 source、target 或 `mid` 配对歧义则失败。内容类型与排除只由 profile 显式规则决定，不根据 CC、FF、文件名或目录名推断。

以下可见合同精确定义两种解析后 scope：

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

### 2. 标记受保护内容

标准模式的术语条目使用明确字段；无术语模式忽略术语条目。两种模式都可使用经过证据确认的 TM 匹配等显式段保护。

```json
{"source":"源词","target":"确认译法","confirmed":true,"protected":false}
```

- 字段缺失时按 `false` 处理。
- 不根据状态标签推断 `confirmed`。
- 只有用户明确确认的状态值，才能通过 `protected_term_statuses` 映射为 `protected: true`。

输入文件带 TM 精确匹配证据时，Agent 先确认列名、样例值和证据，写出明确的段 id，再运行：

```bash
python3 "$SCRIPTS/lqe_io.py" protect-segments \
  --state "$JOB/state.json" \
  --protected-file "$JOB/tm_protected.agent_decision.json" \
  --reason TM_100_MATCH
```

脚本不会猜测匹配列或匹配值。

SDLXLIFF 中明确 locked 的段始终以 `SOURCE_LOCKED` 保护。默认策略 `candidate-only` 只把同时满足 `origin=tm`、`percent=100`、`text-match=SourceAndTarget` 的段写入 `tm_candidates.json`，不会自动保护。确认后可将该文件交给 `protect-segments`，也可在 profile 使用 `protect-exact-source-and-target`，或用 CLI `--protect-exact-tm` 显式启用严格自动保护；只有 100% 数值不够。locked 与严格 TM 同时命中时，主原因仍为 `SOURCE_LOCKED`，两类证据分别保留。

profile 可增加可审计的 SDLXLIFF 规则：

```json
{
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

### 3. 机器预检

```bash
python3 "$SCRIPTS/lqe_io.py" pre-check \
  --state "$JOB/state.json" \
  --out "$JOB/errors_precheck.json"
```

预检覆盖未翻译或空译文、变量、标签、换行、数字、长度、空格、标点、重复词、大小写、文件内一致性和项目自定义规则。标准模式还运行术语及依赖术语表的专名检查；无术语模式跳过这些术语检查，其余预检仍需结合上下文复核。

### 4. 分块并运行检查模块

```bash
python3 "$SCRIPTS/lqe_chunk.py" split \
  --state "$JOB/state.json" \
  --errors "$JOB/errors_precheck.json" \
  --outdir "$JOB/chunks" \
  --size 100
```

标准模式下，`split` 通过 state 读取术语；`--terms <file>` 只是可选覆盖，无术语模式会拒绝该参数。每个 `chunk_NN.json` 按 `state.check_scope` 生成：

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

每个模块读取 `docs/check_modules/common.md`、自己的说明和任务上下文，并覆盖全部分配 id；没有问题的段也要输出空 `issues`。

`precheck_review` 只确认或删除 Markup、Length、Locale convention、Company style、Inconsistency、Other 类别的非术语预检，不得创建 Terminology、`TERM REVIEW:` 或 `confirmed_term` 证据。

模型唯一输出协议：

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

新译名、术语表缺词、多个合理方案或整句重写，使用 `needs_confirmation: true` 和 `edit: null`。术语或专名修改还必须有唯一的 `confirmed: true` 候选和 `confirmed_term` 证据。

### 5. 校验、合并和评分

```bash
python3 "$SCRIPTS/lqe_chunk.py" validate-checks --job "$JOB"
python3 "$SCRIPTS/lqe_chunk.py" merge-checks --job "$JOB"
python3 "$SCRIPTS/lqe_chunk.py" reconcile --job "$JOB"
python3 "$SCRIPTS/lqe_chunk.py" merge \
  --state "$JOB/state.json" \
  --errors "$JOB/errors_precheck.json" \
  --outdir "$JOB/chunks" \
  --out "$JOB/errors.json"

python3 "$SCRIPTS/lqe_calc.py" \
  --state "$JOB/state.json" \
  --errors "$JOB/errors.json" \
  --threshold 98
```

首轮检查应明确使用 `single`：

```bash
bash "$SCRIPTS/finalize_job.sh" "$JOB" <分块数> single
```

只有用户明确要求自动迭代时才使用 `iterate`。

### 6. 生成标准交付文件

```bash
python3 "$SCRIPTS/lqe_io.py" write \
  --state "$JOB/state.json" \
  --errors "$JOB/errors.json" \
  --score <分数> \
  --threshold 98

python3 "$SCRIPTS/lqe_io.py" export \
  --state "$JOB/state.json" \
  --errors "$JOB/errors.json"
```

表格输入对应以下产物：

| 文件 | 用途 |
|---|---|
| `<任务名>_lqe.xlsx` | 分数、问题、建议译文、处理方式和历史记录 |
| `<任务名>_corrected.xlsx` | 保留原工作簿结构，仅把通过校验的建议修改写入目标列 |

用户可见报告使用“建议修改、需要人工确认、保持原译、已保护”。`corrected` 仅用于内部数据和标准输出文件名。

SDLXLIFF 的 `LQE Results` 固定为 11 列：来源文件、TU ID、SDL Segment ID、原文、原译、建议译文、处理方式、错误详情、LQE_Iter、Protected、Protection Evidence。`source_manifest.json` 保存输入 SHA-256、声明语言、扩展 namespace、规则命中、排除和 locked/TM 证据；`tm_candidates.json` 把严格候选与保护决定分开。corrected Excel 固定为 5 列：来源文件、TU ID、SDL Segment ID、原文、译文。

第一版不回写 SDLXLIFF XML；`export` 只生成 `<任务名>_corrected.xlsx`，所有原始 XML 保持不变。

## 评分

```text
K_per_category = Σ severity_points
L_per_category = weight × K
score = max((1 - ΣL / 固定词数) × 100, 0)
```

默认严重度点数为 Neutral 0、Minor 1、Major 5、Critical 10；默认阈值为 98。Terminology、Untranslated、Markup、Length 强制为 Major。受保护段不计分。

## 多工作表

每个工作表单独建立子任务，全部检查完成后再聚合：

```bash
python3 "$SCRIPTS/aggregate_sheets.py" \
  --job <任务名> \
  --sheets <工作表一>,<工作表二> \
  --threshold 98
```

父任务保留工作表顺序、空行、公式、样式和合并单元格，只替换经过校验的目标单元格。

该聚合命令只用于表格工作簿；SDLXLIFF 目录属于一个多文件任务，不是多工作表任务。

## 验证

```bash
python3 -m unittest -v tests.test_correction_builder
python3 -m unittest -v tests.test_corrected_ownership
python3 -m unittest -v tests.test_no_terminology_mode
python3 -m unittest -v tests.test_sdlxliff_input
python3 -m unittest -v tests.test_documented_contract
python3 -m unittest -v tests.test_plain_language
python3 scripts/run_tests.py
```
