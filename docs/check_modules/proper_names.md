# 专名检查模块

公共协议见 `common.md`。本模块用于术语表自检，只处理 `kind=name` 的专名音译问题，类别使用 Mistranslation 或 Culture specific reference。必须覆盖全部分配 id；无问题时写空 `"issues"`。每条问题使用 `"needs_confirmation"` 和 `"edit"`，不得输出 corrected。

## 检查内容

- 目标读音是否与英文锚点一致；英文为空时再参考中文读音。
- 是否丢失或增加音节、替换首辅音、误用另一条目的名称。
- 人名、地名、怪物名或物品名是否类别错置。
- 是否违反 `confirmed_rules.md` 中已经确认的专名写法。
- 罗马化、转写、声调和目标文字规则以语言说明为准。

整名无法辨认通常为 Major；轻微音节或元音偏差可为 Minor。纯拼写问题交给 `grammar`，描述词义交给 `accuracy`，跨条目一致性交给 `terminology`。

## 修改规则

专名默认需要人工确认。只有 `term_hits` 中存在唯一 `confirmed: true` 的候选，并且替换整个名称时，才可给 `"needs_confirmation": false` 和带 `confirmed_term` 证据的 `"edit"`。其他情况写 `"needs_confirmation": true`、`"edit": null`。

```json
[{"id": 7, "issues": [{"category": "Mistranslation", "severity": "Major", "comment": "The transliteration does not match the supplied name anchor.", "needs_confirmation": true, "edit": null}]}]
```
