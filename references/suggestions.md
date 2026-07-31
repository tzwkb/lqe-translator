# 报告专用参考建议

该 worker 只生成供审校判断的完整参考译文，不修改问题清单，也不生成或覆盖 `corrected`。

输入为 `reference_suggestions.packet.json`。先读取其中的 `review_policy`，不得自行切换模式。必须审阅全部 `reviewed_ids`；允许只为有可靠方案的段提交建议，未提交 id 会在报告中显示“未生成建议，需人工处理”。

草稿格式固定为：

```json
{
  "schema": "lqe.reference-suggestion-draft",
  "version": 3,
  "packet_digest": "<packet.packet_digest>",
  "selection": {
    "categories": ["Audience appropriateness", "Company style", "Unidiomatic"],
    "severities": ["Critical", "Major"],
    "only_missing": true
  },
  "reviewed_ids": [0, 1, 2],
  "suggestions": [
    {
      "id": 1,
      "reference_target": "完整的参考译文"
    }
  ]
}
```

规则：

- `reviewed_ids` 必须逐项复制 packet 的同名数组，顺序不变。
- `selection` 必须逐项复制 packet 的同名对象；可用 `prepare --categories <逗号分隔类别> --severities Major,Critical --only-missing` 建立有界审阅包。
- `optimized` 的 suggestion packet 默认只把 Major/Critical 作为候选；`full` 默认纳入 Neutral/Minor/Major/Critical。严重度只决定候选范围，不要求 Agent 为每个候选都生成建议。
- `suggestions` 只提交 Agent 判断为可靠的建议，id 不得重复或越界。
- `reference_target` 必须是完整译文，不是说明、选项列表或局部片段。
- 可进行风格、自然度、文化适配和整句重写；以 packet 中 `errors` 和上下文为依据。
- 如果 packet 有 `validated_target`，以它作为已验证局部修正基础，避免恢复已修正问题。
- 变量、标签、显式换行、字面 `\n` 和 `protected_texts` 的数量及顺序必须与 `target` 一致。
- 不得为受保护段生成建议。
- 存在多个合理方案、上下文不足或无法可靠改写时，省略该 id。
- 不得添加 `status`、`comment`、`corrected` 或其他字段。

`optimized` 的文本分类只使用 packet 中的上游字段：优先读取非空 `content_type`，否则读取 `text_type_context`；缺失或未知时按普通文本处理，不自行分类。`full` 可把字段作为上下文，但不按分类改变建议口径。

- UI/界面文本、系统提示/教程、战斗/操作提示：优先保证简洁、清楚、可执行，并准确保留操作、条件和结果。
- 技能/道具描述：准确保留机制、数值关系和术语，再处理表达自然度。
- 主线剧情对话、支线/NPC 对话：结合上下文保持角色声音、语域和口语自然度。
- 世界观/背景文本：同时保持术语、叙事风格和文化表达。

发布命令：

```bash
python "$SCRIPTS/lqe_suggestions.py" publish \
  --job "$JOB" --input <参考建议草稿.json>
```

publisher 会重新派生 live packet，拒绝旧 `packet_digest`、不完整 `reviewed_ids`、重复 id、保护内容变化和篡改后的正式产物。
