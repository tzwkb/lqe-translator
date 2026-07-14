# `projects/` 文件地图

项目按 `<game>/<source>-<target>/` 保存，游戏级共享资料放在 `<game>/common/`。使用 `read --project <game>/<source>-<target>` 加载；路径从 skill 根目录解析，不依赖当前工作目录。目标语言通用事实放在 `../target_languages/<code>/`。

## 语言轨结构

| 文件 | 用途 | 读取方 |
|---|---|---|
| `profile.json` | 语言、背景、阈值及各资源路径 | `lqe_io.py read --project` |
| `checks.json` | 机器预检开关和项目自定义规则 | `lqe_io.py pre-check` |
| `confirmed_rules.md` | 客户或用户已经确认的项目规则 | Agent，检查前必读 |
| `terms_*.json` | 术语数据，可显式带 `confirmed` 和 `protected` | 标准模式引用或按需转换；无术语模式不读取 |
| `sg*.md` / `sg*.txt` | 风格指南文本 | 初始化时复制到任务目录 |
| `sources/` | 原始风格指南、术语表及其工作副本 | 项目维护与溯源 |
| `inputs/` | 待检查的原始交付文件 | 人工传给 `read --input` |

建议的 `profile.json`：

```json
{
  "name": "game/zh-en",
  "language_pair": "zh-en",
  "source_lang": "zh",
  "target_lang": "en",
  "background": "项目背景",
  "style_guide": "sg.md",
  "terminology": "terms.json",
  "checks": "checks.json",
  "confirmed_rules": "confirmed_rules.md",
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

`language_pair`、`source_lang`、`target_lang` 必填。相对路径以当前语言轨目录为基准。设置合并顺序为：内置默认 < 目标语言属性 < 项目 `checks.json` < 命令行参数。

`sdlxliff.tm_protection` 可取 `candidate-only` 或 `protect-exact-source-and-target`；CLI `--protect-exact-tm` 优先。`content_type_rules` 按顺序匹配大小写敏感的相对路径 glob，第一个命中生效。`exclude_rules` 必须有唯一 `id` 和非空 `reason`，可选 glob，并在 `relative_path`、`file_original`、`confirmation`、`origin`、`locked`、`source`、`target` 上使用且只使用一个 `equals` 或 `regex`。不得用不稳定的 job 段号，也不得根据 CC、FF、文件名或目录名推断内容类型。

## SDLXLIFF 输入

单个 SDLXLIFF 1.2 文件或目录可直接初始化：

```bash
python3 scripts/lqe_io.py read \
  --project <game>/<source>-<target> \
  --input <SDLXLIFF 文件或目录> --input-format sdlxliff \
  --out jobs/<任务名>/state.json
```

`--input-format` 可取 `auto`、`tabular`、`sdlxliff`。单文件和只含 SDLXLIFF 的目录可自动识别；混合格式目录必须显式指定 `sdlxliff`。目录递归读取并按相对路径排序；表格目录不支持。

第一版只支持带 SDL namespace 的 XLIFF 1.2；XLIFF 2.0 明确失败。未知厂商扩展若不影响句段定位、文本边界和 `mid` 配对，会保留并写入 state/manifest；出现结构歧义时失败，不猜测。

locked 段始终以 `SOURCE_LOCKED` 保护。默认 `candidate-only` 只把同时满足 `origin=tm`、`percent=100`、`text-match=SourceAndTarget` 的段写入 `tm_candidates.json`；候选只有在执行 `protect-segments` 后才成为当次任务的保护决定。profile 的 `protect-exact-source-and-target` 或 CLI `--protect-exact-tm` 是显式严格自动保护决定；单独的 100% 值不够。

## 运行时检查模式

profile 可以配置术语，但任务明确不检查术语时，在初始化命令加入 `--no-terminology`：

```bash
python3 scripts/lqe_io.py read \
  --project <game>/<source>-<target> \
  --input <输入文件> --source-col <原文列> --target-col <译文列> \
  --no-terminology --out jobs/<任务名>/state.json
```

该实时参数高于 profile 术语配置，且不能与显式 `--terminology <file>` 同时使用。解析结果写入 `state.check_scope` 和任务根目录的 `scope.json`。标准模式要求 `terminology`、`accuracy`、`grammar`、`naturalness`；无术语模式要求 `precheck_review`、`accuracy`、`grammar`、`naturalness`。无术语模式只关闭术语、专名和术语审计；不会关闭文件内一致性、Markup、数字等检查。

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

## 术语字段

```json
{"source":"源词","target":"译法","confirmed":false,"protected":false}
```

- `confirmed: true`：译法已经确认；匹配证据唯一时允许安全的局部修改。
- `protected: true`：不可修改。
- 缺失字段按 `false` 处理，不能根据其他状态值推断 `confirmed`。
- `protected_term_statuses` 只能填写客户资料或用户明确确认的状态值。

## 检查结果接口

检查模块只提交 `{id, issues:[{category,severity,comment,needs_confirmation,edit}]}`。`edit` 只用于安全、唯一、局部的替换；需要新译名、存在多个合理方案或必须重写时，使用 `needs_confirmation: true` 和 `edit: null`。完整建议译文由脚本在校验后生成。

## 规则优先级

检查时按以下顺序执行：实时要求 > `confirmed_rules.md` > 风格指南 > 通用检查方法。新确认的规则应写入当前语言轨的 `confirmed_rules.md`，不要写进通用语言事实。

## 运行产物

任务产物写入 `../jobs/<任务名>/`，不写回项目资料：

```text
state.json
scope.json
source_manifest.json        # SDLXLIFF 任务
tm_candidates.json          # SDLXLIFF 任务
confirmed_rules.md
errors_precheck.json
errors.json
chunks/
<任务名>_lqe.xlsx
<任务名>_corrected.<csv|tsv|xlsx>
```

原始输入保持不变。`<任务名>_lqe.xlsx` 用于检查和评分记录。corrected 输出按输入格式区分：

- CSV/TSV 输入输出 `<任务名>_corrected.csv` 或 `<任务名>_corrected.tsv`，保持原行列和输入扩展名。
- XLSX 输入输出 `<任务名>_corrected.xlsx`，保持工作簿、工作表、空行、列顺序和格式。
- SDLXLIFF 输出新建固定 5 列的 `<任务名>_corrected.xlsx`。

SDLXLIFF 的 `source_manifest.json` 记录输入文件 SHA-256、语言、未知扩展 namespace、规则命中、纳入/排除原因和 locked/TM 证据；`tm_candidates.json` 单独记录严格候选。其 `LQE Results` 固定为来源文件、TU ID、SDL Segment ID、原文、原译、建议译文、处理方式、错误详情、LQE_Iter、Protected、Protection Evidence；新建的 corrected Excel 固定为来源文件、TU ID、SDL Segment ID、原文、译文。

第一版不回写 SDLXLIFF XML；只导出标准 `<任务名>_corrected.xlsx`，原始 XML 保持不变。
