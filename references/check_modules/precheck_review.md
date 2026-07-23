# 非术语预检复核模块

`precheck_review` 只在无术语模式运行。它只复核当前 chunk 的 `precheck` 中已有的非术语问题，不主动创建预检之外的问题。

## 输出要求

- 必须审阅 packet 的全部 `reviewed_ids`；没有问题的 id 不写入紧凑草稿的 `findings`，publisher 会补空。
- 允许类别只有 `Markup`、`Length`、`Locale convention`、`Company style`、`Inconsistency`、`Other`。
- 确认真实问题时保留并清楚说明；确认是误报时，从该 id 的 `issues` 中删除。
- 每条保留的问题必须原样复制 chunk 中对应问题的 `precheck_ref`；不得伪造、复用或把一个引用用于另一个问题。
- 不得创建术语或专名判断，不得输出 `Terminology`、`TERM REVIEW:` 或 `confirmed_term` 证据。
- 每个问题遵守公共规范的 `severity`、`comment`、`needs_confirmation` 和 `edit` 契约。

协议示例：

```json
[{"id": 0, "issues": [{"precheck_ref": "precheck:0:0123456789abcdef", "category": "Markup", "severity": "Major", "comment": "The target drops one inline tag.", "needs_confirmation": true, "edit": null}]}]
```

只写 `common.md` 所述的合法紧凑草稿，不加说明文字或 Markdown 围栏；正式 `chunk_NN.precheck_review.json` 必须经 `lqe_review.py publish` 发布。
