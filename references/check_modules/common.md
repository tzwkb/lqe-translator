# LQE 检查模块公共规范

标准模式要求 `terminology`、`accuracy`、`grammar`、`naturalness` 四个模块；`proper_names` 是可选模块，只用于术语表自检中的专名。无术语模式要求 `precheck_review`、`accuracy`、`grammar`、`naturalness` 四个模块，并禁用术语相关模块。当前模式和必需模块以 `state.check_scope` 为准；每个模块只提交检查结果，最终译文由脚本根据已验证的局部修改生成。

## 开始前读取

- 项目背景：受众、语气和文本用途。
- `confirmed_rules.md`：客户已经确认的规则，优先于风格指南和通用规则。
- 风格指南与语言说明。
- 当前模块的 `review_packets/<module>/chunk_NN.json`。packet 只保留该模块所需字段，并绑定原 chunk 的指纹。

按 `review_packets/batch_plan.json` 分配有界 worker。每个 worker 只处理一个批次：最多 4 个 packet，同时不超过 25,000 原译字符或 100,000 packet 字节；单个超限 packet 独占一个 worker。worker 在批次开始时读取本文件、自己的模块说明和项目上下文；新批次必须新建 worker 并重新读取。发生上下文压缩、异常重复判断或连续格式错误时立即重开，不得依赖上一 worker 的记忆作为证据。

## 默认紧凑草稿

模型只写合法 JSON 对象草稿，不加 Markdown 围栏或说明文字；不要直接覆盖正式的 `chunk_NN.<module>.json`。`reviewed_ids` 必须原样复制 packet 的同名数组，证明 packet 中全部可审段已覆盖；`findings` 只写确有问题的 id，无问题的 id 不写。

```json
{
  "schema": "lqe.compact-module-draft",
  "version": 1,
  "module": "grammar",
  "chunk_id": 0,
  "packet_digest": "<packet.packet_digest>",
  "reviewed_ids": [0, 1, 2],
  "findings": [
    {
      "id": 1,
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
}
```

`findings` 中每项的字段固定为 `{id, issues:[{category,severity,comment,needs_confirmation,edit}]}`。检查模块不得输出 corrected；脚本会补齐空结果，并在合并时生成该内部字段。

正式模块结果仍覆盖原 chunk 的全部 id。每个 id 无问题时也输出 `{"id": 0, "issues": []}`；这个补齐动作由 `lqe_review.py publish` 完成。受保护段，以及 `precheck_review` 中没有其负责类别预检的段，会被 packet 确定性排除并补空，不消耗 AI 审阅。

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

## 断点

packet 超过 30 段时，每完成最多 20 个 id 就原子更新一次紧凑草稿的 `reviewed_ids` 和 `findings`。恢复时从 packet 的 `reviewed_ids` 中扣除草稿已记录 id；最终发布前，草稿 `reviewed_ids` 必须与 packet 完全一致。

旧的完整数组流程仍可使用 `lqe_chunk.py ckpt-append`、`ckpt-finalize` 和 `publish-module`，用于兼容历史任务。

## 模块分工

| 模块 | 负责类别 | 范围 |
|---|---|---|
| `terminology` | Terminology、Inconsistency、Company style 与机器预检复核 | 全部段 |
| `precheck_review` | Markup、Length、Locale convention、Company style、Inconsistency、Other | 无术语模式下复核 chunk 中的非术语预检 |
| `accuracy` | Mistranslation、Omission、Addition、Untranslated | 全部段 |
| `grammar` | Grammar、Spelling、Punctuation | 全部段 |
| `naturalness` | Audience appropriateness、Culture specific reference、Unidiomatic | 全部段 |
| `proper_names` | 专名音译相关的 Mistranslation、Culture specific reference | 术语表自检中的 name 段 |

当前模式下的所有必需模块正式产物都要覆盖全部 id。紧凑 publisher 负责补齐，合并、去重、类别归属检查和最终译文生成仍由原合同完成。

## 发布模块结果

完成紧凑草稿后发布。命令会重新从当前正式 chunk 派生 packet，核对 `packet_digest`、完整 `reviewed_ids`、类别和预检引用，再生成原有完整绑定 envelope：

```bash
python3 "$SCRIPTS/lqe_review.py" publish \
  --job "$JOB" --chunk <NN> --module <module> \
  --input <紧凑草稿.json>
```

指纹不匹配表示任务已过期，必须重新运行 `prepare` 并读取当前 packet；不得把旧草稿绑定到新 generation。当前 schema 会拒绝缺失审阅 id、空 `findings` 项、越权类别、错误预检引用和直接写入正式路径的裸数组。
