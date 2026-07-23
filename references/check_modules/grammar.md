# 语法与拼写检查模块

公共协议见 `common.md`。本模块只处理 Grammar、Spelling、Punctuation。必须审阅 packet 的全部 `reviewed_ids`；紧凑草稿只在 `findings` 中写有问题的 id。每条问题使用 `"needs_confirmation"` 和 `"edit"`，不得输出 corrected。

## 检查内容

- 词序、连接词、属格、助词、量词、分类词和完整谓语。
- 目标语言需要时，检查时态、单复数、主谓一致和词形变化。
- 多字、少字、重复字符、重复词和明显拼写错误。
- 成对标点、引号一致性和影响理解的断句。
- 变量、标签、换行数量等纯机械问题由机器预检负责，不重复报告。
- 用词准确但不自然的问题交给 `naturalness`；含义错误交给 `accuracy`。

## 修改规则

单个拼写、标点、词形或可唯一定位的小范围语法问题可给 `"needs_confirmation": false` 和局部 `"edit"`。需要重排或整句改写时写 `"needs_confirmation": true`、`"edit": null`。

```json
[{"id": 5, "issues": [{"category": "Spelling", "severity": "Minor", "comment": "The word contains a duplicated letter.", "needs_confirmation": false, "edit": {"from": "lettter", "to": "letter", "evidence": null}}]}]
```
