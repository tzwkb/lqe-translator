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
  "protected_term_statuses": []
}
```

`language_pair`、`source_lang`、`target_lang` 必填。相对路径以当前语言轨目录为基准。设置合并顺序为：内置默认 < 目标语言属性 < 项目 `checks.json` < 命令行参数。

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
confirmed_rules.md
errors_precheck.json
errors.json
chunks/
<任务名>_lqe.xlsx
<任务名>_corrected.xlsx
```

原始输入保持不变。`<任务名>_lqe.xlsx` 用于检查和评分记录；`<任务名>_corrected.xlsx` 保留原工作簿结构，只写入通过校验的建议修改。
