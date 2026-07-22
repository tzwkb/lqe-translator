# LQE 检查模块公共规范

标准模式要求 `terminology`、`accuracy`、`grammar`、`naturalness` 四个模块；`proper_names` 是可选模块，只用于术语表自检中的专名。无术语模式要求 `precheck_review`、`accuracy`、`grammar`、`naturalness` 四个模块，并禁用术语相关模块。当前模式和必需模块以 `state.check_scope` 为准；每个模块只提交检查结果，最终译文由脚本根据已验证的局部修改生成。

## 开始前读取

- 项目背景：受众、语气和文本用途。
- `confirmed_rules.md`：客户已经确认的规则，优先于风格指南和通用规则。
- 风格指南与语言说明。
- 当前 chunk：每段包含 `id`、`source`、`target`、`kind`、`precheck`、`term_hits`、`term_near` 等上下文。

## 唯一输出格式

模型只写合法 JSON 数组草稿，不加 Markdown 围栏或说明文字；不要直接覆盖正式的 `chunk_NN.<module>.json`。每个模块必须覆盖分配给它的全部 id。每个 id 无问题时也输出 `{"id": 0, "issues": []}`，不能省略该 id 或把整个文件写成空数组。

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

字段固定为 `{id, issues:[{category,severity,comment,needs_confirmation,edit}]}`。检查模块不得输出 corrected；脚本会在合并时生成该内部字段。

`precheck_review` 保留问题时必须带 chunk 中原问题的 `precheck_ref`；`terminology` 复核并保留机器预检问题时也带该引用，新发现的问题不带。其他模块不使用该字段。

模型草稿不得输出 `review_provenance`。正式合并会根据当前绑定模块、`precheck_ref`、实际审阅段和脚本验证结果生成该字段；草稿自报的 AI 状态不会成为报告证据。

- `comment` 用英文简短说明，可引用少量原文或译文。
- `severity` 只能是 `Neutral`、`Minor`、`Major`、`Critical`。
- `edit` 只表示一个可安全应用的局部替换，必须带 `from`、`to`、`evidence`；同一子串出现多次时再带 `start`、`end`。
- 普通语法、标点、拼写或局部用词问题，如果改法唯一且不会碰变量、标签、换行或受保护文本，写 `needs_confirmation: false` 和具体 `edit`。
- 新译名、术语表错误、术语表缺词、多个合理译法或任何无法安全局部修改的问题，写 `needs_confirmation: true` 和 `edit: null`。
- 专名或术语改动只有在 `term_hits` 中存在唯一且 `confirmed: true` 的匹配时才可直接修改；`evidence` 写 `{"type":"confirmed_term","source":"...","target":"..."}`。
- 受保护段写空 `issues`，不建议修改。
- 只使用本模块负责的类别；不属于本模块的问题交给对应模块。

## 断点文件

段数超过 30 时，每完成一段立即追加：

```bash
python3 "$SCRIPTS/lqe_chunk.py" ckpt-append \
  --file <目标文件>.ckpt.jsonl \
  --entry '{"id":0,"issues":[]}'
```

开始前先读取现有断点并跳过已有 id。全部完成后生成 JSON 数组草稿，再按“发布模块结果”生成正式文件：

```bash
python3 "$SCRIPTS/lqe_chunk.py" ckpt-finalize \
  --jsonl <目标文件>.ckpt.jsonl \
  --out <JSON数组草稿>
```

## 模块分工

| 模块 | 负责类别 | 范围 |
|---|---|---|
| `terminology` | Terminology、Inconsistency、Company style 与机器预检复核 | 全部段 |
| `precheck_review` | Markup、Length、Locale convention、Company style、Inconsistency、Other | 无术语模式下复核 chunk 中的非术语预检 |
| `accuracy` | Mistranslation、Omission、Addition、Untranslated | 全部段 |
| `grammar` | Grammar、Spelling、Punctuation | 全部段 |
| `naturalness` | Audience appropriateness、Culture specific reference、Unidiomatic | 全部段 |
| `proper_names` | 专名音译相关的 Mistranslation、Culture specific reference | 术语表自检中的 name 段 |

当前模式下的所有必需模块都要输出全部 id。合并、去重、类别归属检查和最终译文生成由 `lqe_chunk.py` 完成。

## 发布模块结果

完成 JSON 数组草稿后，用所读 `chunk_NN.json` 顶层的 `split_fingerprint` 和 `payload_digest` 发布。发布命令会在 generation 共享锁内复核 id、类别和指纹，并生成正式的绑定 envelope：

```bash
python3 "$SCRIPTS/lqe_chunk.py" publish-module \
  --job "$JOB" --chunk <NN> --module <module> \
  --input <JSON数组草稿> \
  --split-fingerprint <chunk.split_fingerprint> \
  --chunk-payload-digest <chunk.payload_digest>
```

指纹不匹配表示任务已过期，必须重新读取当前 chunk 后重做；不得把旧草稿绑定到新 generation。当前 schema 会拒绝直接写入正式路径的裸 JSON 数组。
