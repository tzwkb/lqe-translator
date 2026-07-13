# 术语检查模块

公共协议见 `common.md`。本模块只处理 Terminology、Inconsistency、Company style，并复核机器预检结果。必须覆盖全部分配 id；无问题时写空 `"issues"`。每条问题使用 `"needs_confirmation"` 和 `"edit"`，不得输出 corrected。

## 检查内容

1. 复核 `precheck`：保留确定的标记、长度、格式和空白问题；数值、含义等准确性问题交给 `accuracy`。
2. 检查 `term_hits`：每个候选已展开成单独记录，包含 `source`、`target`、`confirmed`、`protected` 及可选的 `status/category/definition`。
3. 同一来源概念在全文使用不同译法时报告 Inconsistency；术语表内的冲突仍归 Terminology。
4. 只有违反明确风格指南的写法才报告 Company style；单纯不自然交给 `naturalness`。

## 是否可直接修改

- 当前译文偏离唯一且 `confirmed: true` 的候选时，可给局部 `edit`，并把证据写成 `{"type":"confirmed_term","source":"源词","target":"确认译法"}`。
- 候选未确认、存在多个含义、需要新译名、术语表缺词或术语表自身可能错误时，写 `"needs_confirmation": true`、`"edit": null`。
- `protected: true` 的词和受保护段不修改。
- 最长匹配优先；已被更长术语覆盖的子词不重复报告。

## 输出示例

```json
[{"id": 8, "issues": [{"category": "Terminology", "severity": "Major", "comment": "The confirmed project term is not used.", "needs_confirmation": false, "edit": {"from": "Old Name", "to": "New Name", "evidence": {"type": "confirmed_term", "source": "新名", "target": "New Name"}}}]}]
```
