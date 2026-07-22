# LQE Translator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Agent Skill](https://img.shields.io/badge/Agent%20Skill-Codex-blue.svg)](SKILL.md)
[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)

[English](README.md) | 中文

用于游戏本地化 LQE：先做机器预检，再由专项检查模块报告问题和安全的局部修改，最后由 Python 校验、评分并生成 Excel 交付文件。

> 项目经理可直接阅读独立版 [PM 操作手册](PM_GUIDE.html)；开发记录保留在 `docs/`。

## 核心约束

- 项目上下文来自 `profile.json`、`confirmed_rules.md`、风格指南和目标语言说明；标准模式还加载术语表。
- 标准模式必需模块为术语、准确性、语法和自然度；无术语模式必需模块为 `precheck_review`、准确性、语法和自然度，专名模块只在标准模式下可选。
- 模型只提交 `issues` 和安全的局部 `edit`；Python 校验后生成内部完整文本。
- `confirmed: true` 表示该译法已经确认，可在证据唯一时安全修改；`protected: true` 表示不可修改。
- 受保护段不修改、不计分。
- SDLXLIFF 1.2 可直接读取单文件或递归目录，不需要先转换为工作簿。
- 标准交付文件为 `<任务名>_lqe.xlsx` 和按输入格式确定扩展名的 corrected 文件：CSV/TSV 保持原扩展名，XLSX 与 SDLXLIFF 使用 `.xlsx`。

## 目录结构

```text
lqe-translator/
├── scripts/
│   ├── lqe_io.py           # 读取、预检、保护、报告和导出
│   ├── lqe_chunk.py        # 分块、校验、合并和归属处理
│   ├── lqe_corrections.py  # 校验局部修改并生成完整文本
│   ├── lqe_calc.py         # LQE 评分
│   └── finalize_job.sh     # 从校验到导出的一键收尾
├── references/check_modules/
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
    └── <任务名>_corrected.<csv|tsv|xlsx>
```

## 安装与路径

```bash
pip install "openpyxl>=3.1" regex requests python-docx -q
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

初始化先在 staging 中生成并校验全部资源，拒绝输入/输出/资源别名（含软链和硬链），最后发布 `state.json`。失败时不留下正式 `state.json`、`scope.json`、`terms.json` 或半套 SDL 资源。

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

- 新 job 的每个术语/候选必须显式带布尔 `confirmed` 和 `protected`；任一字段缺失都在正式资源发布前失败。
- 已经同时显式带两个布尔字段的 canonical CSV/XLSX/JSON 可保留 `status` 作为审计元数据，无需 `term_status_map`；如果提供映射但与显式字段冲突，则失败。
- 以下状态列规则适用于缺少任一布尔字段、仍需转换的原始术语表。**状态列检测是「规则」而非「枚举」**：只要表头**包含** `status` 或 `状态`（大小写不敏感、任意位置、不论前后缀/括号）即视为状态列。未来主术语库改列名（如 `术语状态 Status(TH)`、`审核状态`）也能自动命中，不会因漏检而静默全 `confirmed:false`。若**同时命中多个**状态列，转换器报错退出并要求用 `--status-col '<表头>'` 指定，绝不猜测。
- 原始条目缺少任一布尔字段且**存在 `status` 列时，必须显式提供确认决策**，否则转换器 fail-closed 报错退出（并列出检测到的状态值），绝不静默产出全 `confirmed:false`：
  - 确认决策 = `--approved-statuses '<值>'` / `'*'`（整份确认） / `''`（显式整份未确认）；**仅传 `--protected-statuses` 不算确认决策**，仍会 fail-closed。
  - 转换器参数 `--approved-statuses 'Approved,合规审核通过'`（按需）；
  - 或 `--exclude-statuses '<status>'` 把额外驳回状态的术语整条剔除（不参与检查、不判术语问题）；
  - **`Denied` 状态术语默认整条排除，无需任何 flag**（既定规则：客户驳回的术语永不进入术语表；大小写不敏感，`denied`/`DENIED` 同样排除）；`--exclude-statuses` 仅用于追加其它需排除的状态；
  - 或 profile 的 `term_status_map`。
- **状态值比较大小写不敏感（规则）**：`Approved`/`approved`、`Denied`/`denied` 一视同仁，不存在逐值特判。
- 需要转换但**未检测到任何状态列时，转换器同样 fail-closed**，除非显式传 `--no-status`（声明该术语表确实无任何确认信息）。这彻底堵死「列被改名/移位 → 静默全未确认」的口子。
- **不要凭「未映射」的 `status` 自行推断 `confirmed`**；但一旦用户提供了映射，转换器应据映射显式写出 `confirmed`/`protected`，这属于契约授权的落地方式，而非猜测。
- 缺少显式布尔字段的 CSV/XLSX/JSON 状态值必须由 `profile.term_status_map` 明确映射。`protected_term_statuses` 只能补充保护，不构成确认决策；如提供，必须是元素均为非空字符串的数组。`Denied` 始终大小写不敏感地排除且不得映射。

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

标准模式下，`split` 通过 state 读取术语；`--terms <file>` 只是可选覆盖，无术语模式会拒绝该参数。分块输入带指纹；state、当前译文、scope、预检、术语或分块参数变化时，旧 chunks 会归档，旧模块输出不可复用。每个 `chunk_NN.json` 按 `state.check_scope` 生成：

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

每个模块读取 `references/check_modules/common.md`、自己的说明和任务上下文，并覆盖全部分配 id；没有问题的段也要输出空 `issues`。

模型把 JSON 数组写入草稿文件，再用 `lqe_chunk.py publish-module` 和所读 chunk 顶层的 `split_fingerprint`、`payload_digest` 发布。发布器在 generation 锁内校验覆盖和类别归属并生成正式绑定 envelope；当前任务会拒绝正式路径中的裸数组和旧指纹。

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
  --errors "$JOB/errors.json"
```

`merge` 会从当前绑定模块重新推导 merged 问题与 provenance，拒绝伪造的中间 merged 文件，再原子发布 `errors.json` 与 `errors.contract.json`。正式 module entries 的内容摘要与独立本地发布收据都会被校验；模型草稿不能自报 AI 复核/编辑状态。calc、write、apply、export 和聚合持有 generation lease，并拒绝 provenance 缺失以及契约缺失、篡改或过期。当前 reader 创建的任务在 `chunks/` 缺失时也不会退回 state-only 校验。

首轮检查应明确使用 `single`：

```bash
bash "$SCRIPTS/finalize_job.sh" "$JOB" <分块数> single
```

只有用户明确要求自动迭代时才使用 `iterate`。仅 PASS 创建 `.finalized`；FAIL+single 只写审阅产物，不改当前译文、不完成。FAIL+iterate 只有至少应用一处重新验证通过的安全局部 edit 时，才更新 `current_target`、iteration、设置 `pending_recheck=true` 并返回 `PENDING-RECHECK`；零修改时写出本轮报告，并通过 `export --errors` 写出已验证的错误覆盖，返回 `REVIEW-REQUIRED`，清除 `.iteration_pending`，不推进 iteration。下一轮必须重新预检、分块并运行全部模块。

### 6. 生成标准交付文件

```bash
python3 "$SCRIPTS/lqe_io.py" write \
  --state "$JOB/state.json" \
  --errors "$JOB/errors.json" \
  --score <分数>

python3 "$SCRIPTS/lqe_io.py" export \
  --state "$JOB/state.json" \
  --errors "$JOB/errors.json"
```

所有输入都生成 `<任务名>_lqe.xlsx`，记录分数、问题、建议译文、处理方式和历史记录。corrected 输出按输入格式区分：

`write --score` 是一致性输入；脚本按 state policy 与 errors 重算，分数不一致时告警并采用重算值。

- CSV/TSV 输入输出 `<任务名>_corrected.csv` 或 `<任务名>_corrected.tsv`，保持原行列和输入扩展名。
- XLSX 输入输出 `<任务名>_corrected.xlsx`，保持工作簿、工作表、空行、列顺序和格式。
- SDLXLIFF 输出新建固定 5 列的 `<任务名>_corrected.xlsx`。

LQE 报告使用富文本显示修改差异：原译中删除或替换的内容显示为红色删除线，建议译文中新增或替换的内容显示为红色字体。`LQE Results` 每个错误一行，同一 `LQE Segment ID` 的错误连续排列，无错误段保留一行；审计列区分直接 AI 复核、重复段复用、机器预检保留和旧流程未知。“已生成并验证建议”表示修改已纳入建议译文，不表示已写回 state；“AI 模块记录”是本地内容绑定证据，不是外部身份签名。Scorecard 历史明细同步保留 provenance。corrected 文件不添加差异样式。

用户可见报告使用“建议修改、需要人工确认、保持原译、已保护”。`corrected` 仅用于内部数据和标准输出文件名。

经验证的内部结果中，`corrected: ""` 是合法的整段删除；只有 `corrected: null` 表示没有建议修改。write、apply、export 和聚合都必须保留这一区别。

SDLXLIFF 的 `LQE Results` 固定为 16 列：来源文件、TU ID、SDL Segment ID、原文、原译、建议译文、处理方式、LQE Segment ID、LQE 错误序号、LQE AI 复核状态、LQE AI 编辑状态、LQE 检查来源、错误详情、Protected、Protection Evidence、LQE_Iter；表格与 SDLXLIFF 报告都把 `LQE_Iter` 固定在最后一列。`source_manifest.json` 保存输入 SHA-256、声明语言、扩展 namespace、规则命中、排除和 locked/TM 证据；`tm_candidates.json` 把严格候选与保护决定分开。新建的 corrected Excel 固定为 5 列：来源文件、TU ID、SDL Segment ID、原文、译文。

第一版不回写 SDLXLIFF XML；`export` 只生成 `<任务名>_corrected.xlsx`，所有原始 XML 保持不变。

## 评分

```text
K_per_category = Σ severity_points
L_per_category = weight × K
score = max((1 - ΣL / 固定词数) × 100, 0)
```

`state.scoring_policy` 是 calc、write、报告、迭代和聚合的默认策略，CLI 只做显式覆盖。策略包含阈值、评分卡、LISA/MQM 严重度、Critical gate 和重复去重；每次计分都会清除并重建 repeated。默认严重度点数为 Neutral 0、Minor 1、Major 5、Critical 10；默认阈值为 98。受保护段不计分。

## 多工作表

每个工作表单独建立子任务，全部检查完成后再聚合：

```bash
python3 "$SCRIPTS/aggregate_sheets.py" \
  --job <任务名> \
  --sheets <工作表一>,<工作表二>
```

父任务保留工作表顺序、空行、公式、样式和合并单元格，只替换已校验/当前译文。聚合会按每个子任务的当前 state、`errors.contract.json` 和已验证 chunk generation 重新校验结果，并复用 chunk 术语上下文；隐藏 `_LQE_CONTRACT` 同时绑定 state/errors、可见 `LQE Results` 及逐错误 provenance 行结构，汇总报告复制各子任务 Results 与 Scorecard 历史。发布前会按稳定顺序重新取得全部子任务 lease。结果/报告缺失、损坏、过期或未绑定、chunk 证据过期、输入漂移都会失败且不替换原有父级产物。子任务默认继承各自 policy；除阈值外策略不一致时失败。显式 `--threshold` 只覆盖阈值；任一子任务 FAIL 则汇总 FAIL。

该聚合命令只用于表格工作簿；SDLXLIFF 目录属于一个多文件任务，不是多工作表任务。

## 验证

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 scripts/run_tests.py
```
