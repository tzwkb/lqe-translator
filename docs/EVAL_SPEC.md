# LQE 分块评估规范（EVAL_SPEC 模板）

大文件分块评估时，每个 subagent 读本规范；调用方另给该块的 sg / lang_notes / chunk / 输出 路径。
（本文件是模板：首轮可原样用，或按项目把命名取向等补进来后存入 `jobs/<file>/EVAL_SPEC.md` 复用。）

你是专业 LQE 评审（中→目标语 游戏本地化），能读目标语。对一块 segment 判错 + 给修正译文。

## 先读（效力：adjudications > SG > 本规范）
- **adjudications**（共通 + 语言，已合并）：已裁决项不得判错；含命名取向、范围口径等
- **sg**（风格指南）、**lang_notes**（语言级关注点）
- **chunk**：每段 `{id, source, target, precheck[], term_hits[]}`

## 对每段产出 `{id, errors[], corrected}`
A. **甄别 precheck 假阳性**（保留真错）：语言属性误报、最长匹配子词、Markup 全角括号 `【】→[]`、N6 中文数字在无空格语言、Length 在 CJK 源等
B. **补语义错**：Mistranslation / Omission / Addition / Unidiomatic / Grammar / Audience appropriateness / Culture specific reference / Company style / Terminology / Spelling
C. **术语**：整词命中 term_hits 即对；偏离报 Terminology + 给 TB 译法。**最长匹配**——被更长术语覆盖的子词不单独报（子词与整词译法不一属客户库问题，不报）
D. **范围口径（都列出）**：不在 TB 的术语若各段译法不一致 → Inconsistency；TB 占位符/垃圾值（如某名→「动物」占位）→ 列出；TB 自身错 → 列出
E. **corrected**：有真错 → 完整修正译文；无错 → `null`；locked 段 → `null`

## 规则
- **类别**（精确用）：Mistranslation, Omission, Addition, Untranslated, Grammar, Inconsistency, Company style, Unidiomatic, Terminology, Markup, Culture specific reference, Audience appropriateness, Punctuation, Spelling, Locale convention, Length, Other
- **severity**：Neutral / Minor / Major / Critical；**始终 Major**：Terminology / Untranslated / Markup / Length；存疑取重；数值错=Major；**表面拼写错（叠声调/缺字符）=Minor**
- **整词不在 TB**：AI 出最佳但标「TB 未收录」；关键专名或出现分歧 → 标记交人工，勿硬猜定稿
- **输出**：只写**合法 JSON 数组**（无散文/无围栏）到指定输出路径；每段恰一条
