# SDLXLIFF 原生导入与无术语检查模式设计

## 目标

把两个已经在实际任务中验证过的通用能力纳入 `lqe-translator`：

1. 原生读取单个 SDLXLIFF 文件或包含多个 SDLXLIFF 文件的目录。
2. 原生运行“不检查术语”的 LQE 流程。

完成后，同类任务不再需要 job 目录中的 `prepare_sdlxliff.py`、`skip_terminology.py`、`create_skipped_terminology_outputs.py` 或 `filter_precheck.py`。

本次修改不改变评分权重、严重度、阈值、修订写入权或历史 job 产物。

## 范围

### 第一版支持

- SDLXLIFF 1.2，包含 XLIFF 1.2 与 SDL 命名空间。
- 单文件输入和目录递归输入。
- 多个 `<file>`、`<trans-unit>` 和 SDL 句段。
- 原文、译文、内联标签、批注、状态、锁定信息和 TM 匹配证据的读取。
- 未知厂商扩展的容错保留；无法安全确定句段结构时明确失败。
- profile 显式配置内容类型映射和项目排除规则。
- profile 或 CLI 显式启用严格 TM 自动保护；默认只生成候选。
- 将 SDL 元数据写入 `state.json` 和来源清单。
- 无术语模式下继续执行准确性、语法、自然度和非术语预检复核。

### 第一版边界

- XLIFF 2.0 使用独立数据模型，不由 SDLXLIFF 1.2 adapter 解析。
- 未知厂商扩展会尽量保留，但不承诺理解所有私有字段的业务语义。
- 内容类型和排除规则只接受 profile 显式配置；不把 CC、FF 或本次文件名约定写死在 skill。
- 严格 TM 自动保护必须由 profile 或 CLI 明确启用；不能仅凭任意 `100%` 字段无条件保护。
- 项目规则不得硬编码易变化的段号；段级临时决定仍写入当次 job。
- 第一版不将修改后的译文回写到 SDLXLIFF XML，仍导出标准 corrected Excel。
- 新版可把同一来源重新处理为新 job，但不自动改写历史 job 或历史产物。

## 方案选择

采用“输入适配器 + 核心流水线原生检查范围”方案。

- 不把现有 job 脚本原样复制进 `scripts/`；其中含有路径、文件分类和项目判断。
- 不继续用空的 terminology 输出欺骗四模块校验。
- `lqe_io.py read` 负责分发输入格式；SDLXLIFF 解析放在独立模块中。
- 检查范围写入 `state.json`，后续预检、分块、校验、合并、报告都读取同一份范围。

这比“先转换成 14 列 Excel，再按普通 Excel 读取”多一个输入适配层，但能避免中间工作簿成为事实标准，也能防止 SDL 私有字段继续扩张第三个 sheet。

## SDLXLIFF 输入设计

### 命令行

现有 `read` 命令增加：

```bash
python "$SCRIPTS/lqe_io.py" read \
  --project "<game>/<source>-<target>" \
  --input "<file-or-directory>" \
  --input-format sdlxliff \
  --no-terminology \
  --protect-exact-tm \
  --out "<job>/state.json"
```

- `--input-format` 取值为 `auto`、`tabular` 或 `sdlxliff`，默认 `auto`。
- 单个 `.sdlxliff` 文件可自动识别。
- 目录在只包含 SDLXLIFF 输入时可自动识别；混合格式目录必须显式指定。
- `--source-col` 和 `--target-col` 改为仅对表格输入必填。
- `--protect-exact-tm` 显式启用严格 SDL TM 自动保护；未提供时只生成候选。
- 表格输入行为保持不变。

### Profile 输入规则

项目 profile 可增加：

```json
{
  "sdlxliff": {
    "tm_protection": "candidate-only",
    "content_type_rules": [
      {
        "id": "dialog-files",
        "glob": "**/dialogs_*.sdlxliff",
        "content_type": "剧情/对话"
      }
    ],
    "exclude_rules": [
      {
        "id": "client-excluded-status",
        "field": "confirmation",
        "equals": "Rejected",
        "reason": "Client marked the segment as excluded"
      }
    ]
  }
}
```

- `tm_protection` 取值为 `candidate-only` 或 `protect-exact-source-and-target`；CLI 显式参数优先。
- 内容类型规则按顺序匹配，第一个命中的 `glob` 生效；未命中时 `content_type` 留空。
- 排除规则可限定 `glob`，并在 `relative_path`、`file_original`、`confirmation`、`origin`、`locked`、`source`、`target` 上使用 `equals` 或 `regex`。
- 同一段命中多个排除规则时，manifest 记录所有规则 ID 和原因。
- 不接受基于本次连续 `segment.id` 的 profile 规则，因为该 ID 会随输入变化。
- 未知字段、非法 glob/regex、缺失规则 ID 或 reason 时初始化失败，不静默忽略。

### 代码边界

新增独立适配器：

```text
scripts/lqe_inputs/__init__.py
scripts/lqe_inputs/sdlxliff.py
```

适配器只负责：

- 发现和排序输入文件；
- 验证 XLIFF/SDL 版本与命名空间；
- 解析句段及来源元数据；
- 返回核心流水线可消费的标准结构；
- 生成 TM 候选证据和来源清单。

适配器不自行读取项目 profile；`lqe_io.py` 负责校验并传入已解析的 SDLXLIFF 输入规则。术语开关、评分和报告仍不进入适配器。

### 稳定顺序与句段标识

- 文件按相对路径排序。
- 文件内按 XML 文档顺序读取。
- 一个 TU 含多个 `<mrk mtype="seg">` 时，每个 `mrk` 生成独立段；按 `mid` 与 `s:seg-defs/s:seg@id` 配对，禁止只取第一个 `mrk`。
- `segment.id` 仍为 job 内从 0 开始的连续整数。
- 每段增加稳定的 `source_ref`：相对文件路径、`<file>` 序号、TU ID、SDL Segment ID 和句段序号。
- TU ID 或 SDL Segment ID 缺失时使用文档序号定位，不猜造业务 ID。
- 相同 TU ID 在不同文件中允许存在；唯一性由完整 `source_ref` 保证。

### 文本与内联标签

- 不使用 `.strip()` 改写原始句段空白。
- 对任何合法内联元素进行确定性序列化并保留 QName、属性、嵌套和 tail；`g`、`x`、`bx`、`ex`、`ph`、`bpt`、`ept`、`it`、`sub` 和内层 `mrk` 是必须覆盖的测试集合。
- `source` 和 `target` 使用确定性的可读序列化，供现有标签与变量检查使用。
- `metadata.sdlxliff` 保存原始混合内容和标签签名，防止报告或 corrected Excel 丢失证据。
- 未知扩展 namespace 和与句段相关的原始 XML 片段写入 metadata/manifest；不影响句段定位时继续处理，影响 source/target 或 `mid` 配对时失败。
- XML 无法解析、版本不支持或句段结构损坏时立即失败，并报告相对文件路径及可用的行号；不静默跳过整个文件。

### 纳入与排除

- 原文和译文同时为空的句段排除并计入清单。
- source/target 节点存在但只有一侧文本为空的句段保留，由现有空译文或准确性检查处理；缺少 source 节点属于结构错误。
- 不内置“原文/译文表头”“Sheet 名”等本次任务启发式；确有需要时写入项目 profile，并在 manifest 记录规则与原因。
- SDL 明确标记为 locked 的句段自动保护为 `SOURCE_LOCKED`，且与 TM 保护分开记录。

### TM 证据

适配器识别并记录 SDL 的 `origin`、`percent` 和 `text-match`，生成 `tm_candidates.json`。只有满足当前已验证条件的句段才列为候选：

```text
origin=tm, percent=100, text-match=SourceAndTarget
```

默认 `candidate-only` 时，TM 候选不会写入 `protected=true`，仍可通过 `protect-segments` 形成当次 job 决定。profile 设为 `protect-exact-source-and-target` 或 CLI 使用 `--protect-exact-tm` 时，上述严格三条件候选自动保护为 `TM_100_MATCH`；配置本身即为显式决定，保护证据逐段写入 state 和 manifest。`SOURCE_LOCKED` 不依赖 TM 策略。

### 标准状态与报告字段

SDLXLIFF 段在 `state.json` 中至少包含：

```json
{
  "id": 0,
  "row_index": 0,
  "source": "...",
  "target": "...",
  "corrected": null,
  "source_ref": {
    "relative_path": "...",
    "file_index": 0,
    "tu_id": "...",
    "sdl_segment_id": "...",
    "segment_index": 0
  },
  "metadata": {
    "sdlxliff": {
      "file_original": "...",
      "source_language": "...",
      "target_language": "...",
      "confirmation": "...",
      "origin": "...",
      "match_percent": "...",
      "text_match": "...",
      "locked": "...",
      "last_modified_by": "...",
      "comment": "...",
      "content_type": "..."
    }
  }
}
```

SDLXLIFF 的 `LQE Results` 使用固定输入列：来源文件、TU ID、SDL Segment ID、原文、原译。其余 SDL 私有字段写入 `source_manifest.json`，不再全部透传到第三个 sheet。清单同时记录 importer 版本、输入文件 SHA-256、发现的扩展 namespace、内容类型规则命中、纳入/排除数量及原因、TM/locked 保护策略和逐段证据。LQE 增补列沿用现有六列。

第一版的 `export` 为 SDLXLIFF job 生成标准 `<job>_corrected.xlsx`，不修改或重建原 XML。SDLXLIFF 安全回写需单独设计标签往返和多文件交付契约。

## 无术语检查模式

### 生效规则

新增 `--no-terminology`。解析后的状态写入：

```json
{
  "check_scope": {
    "mode": "no-terminology",
    "terminology_enabled": false,
    "enabled_modules": ["precheck_review", "accuracy", "grammar", "naturalness"],
    "disabled_modules": ["terminology", "proper_names", "term_audit"],
    "source": "runtime"
  }
}
```

- 实时 CLI 要求优先于 profile 的术语表配置。
- `--no-terminology` 与显式 `--terminology <file>` 同时出现时失败，避免同一命令自相矛盾。
- profile 自带术语表但 CLI 使用 `--no-terminology` 时，不加载术语表，并在日志中明确说明覆盖关系。
- 所有术语读取统一经过 `lqe_engine.load_terms(state)`；禁用时固定返回空列表，防止预检、分块或查询命令绕过范围设置。
- 未含 `check_scope` 的历史 state 按现有标准四模块模式处理。

### 预检

无术语模式从源头关闭：

- 术语命中和候选复核；
- 术语大小写检查；
- 依赖术语表的专名检查。

以下检查继续运行：

- Markup、标签、变量和占位符；
- 数字、空译文、标点、长度和空格；
- 文件内同源异译、异源同译和省略号风格一致性；
- 项目中与术语无关的自定义规则。

因此不再按错误类别整体删除所有 `Inconsistency`；只禁用真正依赖术语表的规则。

`lqe_chunk.py split --terms` 改为可选参数。标准模式默认从 state 加载术语；无术语模式得到空的术语命中，不要求创建 `terms_disabled.json`。

### 非术语预检复核模块

现有流程把 Markup、Length、Locale convention 等预检复核寄放在 terminology 模块中。无术语模式新增真实的 `precheck_review` 模块，负责复核这些非术语预检结果。该名称也覆盖文件内一致性和非术语 Company style，避免误称为纯机械检查。

```text
docs/check_modules/precheck_review.md
chunk_NN.precheck_review.json
```

- 输出协议仍为 `{id, issues:[...]}`，且覆盖全部 chunk ID。
- 它不是自动生成的空占位文件，也不承载术语或专名判断。
- 允许确认或排除预检误报；未经复核的非确定性机械问题不得直接计分。
- 它只拥有 Markup、Length、Locale convention、Company style、Inconsistency 和非术语 Other；准确性与语言类问题仍由原模块复核。
- accuracy、grammar 和 naturalness 的类别所有权保持不变。

标准模式继续使用现有四模块契约；无术语模式动态要求 `precheck_review`、`accuracy`、`grammar`、`naturalness`。这样不强迫历史项目立即增加第五个模块。

### 校验、合并和收尾

`validate-checks`、`merge-checks` 和 `finalize_job.sh` 从 `state.check_scope.enabled_modules` 获取必需模块，不再使用全局固定元组。

- 禁用的模块文件缺失不报错。
- 出现禁用模块文件时给出范围冲突错误，避免误把术语问题混入结果。
- 无术语模式的最终结果若包含 `Terminology` 类别，校验失败。
- `proper_names` 和 `term_audit` 在无术语模式中不得运行或合并。
- 评分公式不变；禁用范围内没有问题，自然也没有对应扣分。

### 可追溯性

初始化时生成 `scope.json`。最终报告的导读和计分卡显示：

```text
Terminology check: Disabled by runtime request
```

报告同时列出实际启用模块。这样无需从空 terminology 文件反推检查范围。

## 错误处理

- 输入目录没有 SDLXLIFF：失败。
- 同一批文件声明多个源语言或目标语言：失败并列出文件；不自动混跑。
- 用户指定的项目语言轨与 SDLXLIFF 声明冲突：失败。比较前规范化大小写和 `-`/`_`；profile 只写基础语言码时允许匹配该语言的区域变体。
- XML 损坏、命名空间或版本不支持：失败并定位文件。
- 缺少 TU source、重复句段定位键、source/target 的 `mid` 无法配对：失败并定位文件和 TU。
- 未知扩展不影响句段结构时保留并继续；影响句段定位、文本边界或配对时失败并列出 namespace。
- profile 输入规则字段未知、语法无效或缺少审计信息：在读取任何句段前失败。
- 单个句段缺少目标节点：保留为空译文，不中止整批。
- 术语禁用但显式提供术语表：失败。
- 检查输出包含禁用类别或禁用模块：在计分前失败。
- 多文件导入采用整批原子写入；任一文件失败时不留下可被后续流程误用的半成品 state。

## 测试

### SDLXLIFF 单元测试

- 单文件和目录递归导入。
- 多 `<file>`、单 TU 多 `mrk`、重复 TU ID 和缺失 SDL Segment ID。
- 文件排序及句段顺序稳定。
- 空目标、双空句段和锁定句段。
- 批注、状态、修改者和 TM 证据读取。
- `g/x/bx/ex/ph/bpt/ept/it/sub/mrk` 的嵌套、尾文本和边界空白不丢失。
- 未知 namespace 的非关键扩展被保留并记录；干扰句段结构的扩展明确失败。
- profile 内容类型规则按顺序命中，未命中保持为空，且没有内置 CC/FF 判断。
- profile 排除规则支持允许字段并完整记录规则 ID、原因和数量；段号规则及非法规则失败。
- 默认 TM 策略只生成候选；profile/CLI 严格模式只保护三条件同时满足的段；其他 100% 表示不保护。
- locked 段始终以 `SOURCE_LOCKED` 保护，且不与 TM 证据混写。
- source/target `mid` 错配、重复句段定位键明确失败。
- 非法 XML、XLIFF 2.0 和混合语言批次明确失败。
- 客户数据不进入测试库；使用最小匿名 fixture。

### 无术语模式测试

- profile 有术语表时，`--no-terminology` 不加载术语。
- 显式术语表与禁用参数冲突时失败。
- 预检不产生 Terminology 或 `TERM REVIEW`。
- Markup、数字、变量和文件内一致性检查仍运行。
- 校验要求 precheck_review 而不要求 terminology。
- 缺少 precheck_review 输出时失败。
- terminology 文件或 Terminology 问题意外出现时失败。
- 合并、计分、报告和 corrected Excel 可在没有任何 terminology 文件时完成。
- 报告和 `scope.json` 正确记录检查范围。

### 回归测试

- 普通 XLSX/CSV/TSV 的 `read` 行为不变。
- 不带 `check_scope` 的历史 state 仍按原四模块契约校验。
- 标准术语模式仍加载项目术语表并要求 terminology 模块。
- 现有 corrected 写入权、受保护段和评分测试继续通过。

## 验收标准

1. 一个 SDLXLIFF 1.2 文件或目录可直接生成 `state.json`、chunks、LQE 报告和 corrected Excel。
2. 无术语任务不生成空 terminology 模块文件，也不需要事后过滤预检 JSON。
3. 无术语任务仍复核并保留有效的 Markup 等机械问题。
4. 报告明确显示术语检查已禁用及实际启用模块。
5. SDLXLIFF job 的第三个 sheet 使用固定输入列，不随 SDL 私有 metadata 数量变化。
6. 未知厂商扩展在不影响句段结构时被保留并记录，不因未识别业务语义而静默丢弃。
7. profile 可显式配置内容类型、排除规则和严格 TM 保护，所有命中与证据可审计。
8. 当前 XLSX/CSV/TSV 与标准术语模式无行为回归。
9. 所有新增测试和现有 `scripts/run_tests.py` 通过。

## 后续工作

SDLXLIFF corrected XML 回写作为独立功能处理。开始该功能前必须定义：内联标签往返不变量、多文件输出目录或压缩包格式、锁定句段策略，以及 Trados 重新打开验证。
