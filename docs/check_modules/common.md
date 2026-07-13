# LQE 检查模块公共规范

检查任务按术语、准确性、语法和自然度四个必需模块分开运行；`proper_names` 是可选模块，只用于术语表自检中的专名。每个模块只提交检查结果；最终译文由脚本根据已验证的局部修改生成。

## 开始前读取

- 项目背景：受众、语气和文本用途。
- `confirmed_rules.md`：客户已经确认的规则，优先于风格指南和通用规则。
- 风格指南与语言说明。
- 当前 chunk：每段包含 `id`、`source`、`target`、`kind`、`precheck`、`term_hits`、`term_near` 等上下文。

## 唯一输出格式

只向指定路径写合法 JSON 数组，不加 Markdown 围栏或说明文字。每个模块必须覆盖分配给它的全部 id。每个 id 无问题时也输出 `{"id": 0, "issues": []}`，不能省略该 id 或把整个文件写成空数组。

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

开始前先读取现有断点并跳过已有 id。全部完成后生成正式 JSON：

```bash
python3 "$SCRIPTS/lqe_chunk.py" ckpt-finalize \
  --jsonl <目标文件>.ckpt.jsonl \
  --out <正式目标文件>
```

## 模块分工

| 模块 | 负责类别 | 范围 |
|---|---|---|
| `terminology` | Terminology、Inconsistency、Company style 与机器预检复核 | 全部段 |
| `accuracy` | Mistranslation、Omission、Addition、Untranslated | 全部段 |
| `grammar` | Grammar、Spelling、Punctuation | 全部段 |
| `naturalness` | Audience appropriateness、Culture specific reference、Unidiomatic | 全部段 |
| `proper_names` | 专名音译相关的 Mistranslation、Culture specific reference | 术语表自检中的 name 段 |

所有必需模块都要输出全部 id。合并、去重、类别归属检查和最终译文生成由 `lqe_chunk.py` 完成。
