# languages/ — 语言属性层

**属性声明制**：每种目标语言一个文件夹（language code 命名），描述该语言的语言学事实（语言"是什么样"），不放检查开关（"开不开"由代码从属性推导；客户取向走项目 checks.json 覆盖，优先级最高）。

入层判断标准：**项目 SG 有可能推翻的东西不是语言学事实，不得入此层**（em_dash、省略号样式、引号样式都是项目取向——同语言不同项目实证取向相反）。

## 目录约定（固定文件名，存在即挂载）

```
languages/<code>/
├── attributes.json   语言属性声明（必须）
└── eval_notes.md     语言级 AI 评估关注点（可选；read 拷入 job/lang_notes.md，Step 2 注入）
```

`<code>` = profile `language_pair` 后缀小写（`ZHCN-TH` → `th`），或 `read --target-lang` 显式指定。已建：`en`、`th`。

## attributes.json schema

| 字段 | 取值 | 消费者 |
|---|---|---|
| `script` | `latin` / `thai` / `cjk` | pre-check：`cjk` 自动关 `fullwidth_punct`（日语等 CJK 目标语全角标点合法）；〔待批 N8/术语大小写：仅 `latin` 适用〕 |
| `word_delim` | `space` / `none` | read：`none` 且词数基准 `target-words` 时警告防呆（泰语词数会低估数倍）；〔待批 N7 词重复：仅 `space` 适用〕 |
| `sentence_terminator` | 终止符字符集 / `none` | 〔待批 N5 句尾标点：`none` 自动不适用〕 |
| `numerals` | 数字系统数组 | 〔待批 N6 中文数字：译侧可接受的数词体系〕 |
| `wordcount_basis` | `target-words` / `source-chars` | read 词数链：CLI 显式 > profile > 此处 > 内置 `target-words` |

## 为什么按单语言而非语言对建层

属性描述的是**目标语言文本本身**的语言学事实（泰语无句号，与源是什么语言无关），按语言对建层会组合爆炸（N源×M目标）且内容重复。语言对信息在 profile `language_pair` 里，运行时解析（源, 目标）各取所需。当前源恒为中文（ZHCN），源侧假设（CJK 残留检测、中文数字解析、CJK 长度门控）硬编码于代码；将来出现非中文源时的演化方向是把源侧也属性化（解析 language_pair 前缀挂源语言包），目录结构不变。

## 新语言接入（agent 自助，无需改代码）

1. 建 `languages/<code>/attributes.json`，按上表填属性
2. （可选）写 `languages/<code>/eval_notes.md`：只写语言学层面（语法范畴、敬语体系、文字系统陷阱），项目取向一律留项目层
3. 新检查需求先分类：语言学事实 → 提属性 + 代码推导一处（`_lang_toggle_defaults`）；客户取向 → 项目 checks.json custom
