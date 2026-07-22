# 术语表自检补充规则

公共协议见 `common.md`。本文件只用于术语表自身检查：目标语言译名就是待检查内容，没有外部术语表可作硬性对照。各模块仍只输出 `"issues"`、`"needs_confirmation"` 和 `"edit"`，不得输出 corrected。

## 输入

每段是一条孤立术语，除 `source`、`target` 外可带 `en`、`category`、`gender`、`definition`。`kind` 为 `name` 或 `desc`。

## 分工

- `proper_names` 只检查 name 段的音译和专名类别。
- `accuracy` 只检查 desc 段的含义。
- `naturalness` 只检查 desc 段的自然度和受众适配。
- `terminology` 与 `grammar` 检查全部段。
- 外部术语匹配关闭；`terminology` 只检查内部一致性、占位值和明显无效值。

## 共同关注点

- 译文是否用“物品”“动物”等泛词代替实际名称，或误填另一条目的值。
- 同一系列、家族或进化链的命名是否保持组件和格式一致。
- 短词也必须逐条检查，不能因内容短而跳过。
- 新译名、缺少信息或多个合理方案写 `"needs_confirmation": true`、`"edit": null`。

```json
[{"id": 2, "issues": [{"category": "Inconsistency", "severity": "Major", "comment": "This family name uses a different component from the rest of the series.", "needs_confirmation": true, "edit": null}]}]
```
