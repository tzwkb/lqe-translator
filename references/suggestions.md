# 报告专用参考建议

该 worker 只生成供审校判断的完整参考译文，不修改问题清单，也不生成或覆盖 `corrected`。

输入为 `reference_suggestions.packet.json`。必须审阅全部 `reviewed_ids`；允许只为有可靠方案的段提交建议，未提交 id 会在报告中显示“未生成建议，需人工处理”。

草稿格式固定为：

```json
{
  "schema": "lqe.reference-suggestion-draft",
  "version": 1,
  "packet_digest": "<packet.packet_digest>",
  "selection": {
    "categories": ["Audience appropriateness", "Company style", "Unidiomatic"],
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
- `selection` 必须逐项复制 packet 的同名对象；可用 `prepare --categories <逗号分隔类别> --only-missing` 建立有界审阅包。
- `suggestions` 可以稀疏，但 id 不得重复或越界。
- `reference_target` 必须是完整译文，不是说明、选项列表或局部片段。
- 可进行风格、自然度、文化适配和整句重写；以 packet 中 `errors` 和上下文为依据。
- 如果 packet 有 `validated_target`，以它作为已验证局部修正基础，避免恢复已修正问题。
- 变量、标签、显式换行、字面 `\n` 和 `protected_texts` 的数量及顺序必须与 `target` 一致。
- 不得为受保护段生成建议。
- 存在多个合理方案、上下文不足或无法可靠改写时，省略该 id。
- 不得添加 `status`、`comment`、`corrected` 或其他字段。

发布命令：

```bash
python "$SCRIPTS/lqe_suggestions.py" publish \
  --job "$JOB" --input <参考建议草稿.json>
```

publisher 会重新派生 live packet，拒绝旧 `packet_digest`、不完整 `reviewed_ids`、重复 id、保护内容变化和篡改后的正式产物。
