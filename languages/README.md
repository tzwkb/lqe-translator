# languages/ — 语言属性层

**属性声明制**：每个文件描述一种目标语言的语言学事实（语言"是什么样"），不放检查开关（"开不开"由代码从属性推导；客户取向走项目 checks.json 覆盖，优先级最高）。

入层判断标准：**项目 SG 有可能推翻的东西不是语言学事实，不得入此层**（em_dash、省略号样式、引号样式都是项目取向——同语言不同项目实证取向相反）。

## schema

| 字段 | 取值 | 消费者 |
|---|---|---|
| `script` | `latin` / `thai` / `cjk` | pre-check：`cjk` 自动关 `fullwidth_punct`（日语等 CJK 目标语全角标点合法）；〔待批 N8/术语大小写：仅 `latin` 适用〕 |
| `word_delim` | `space` / `none` | read：`none` 且词数基准 `target-words` 时警告防呆（泰语词数会低估数倍）；〔待批 N7 词重复：仅 `space` 适用〕 |
| `sentence_terminator` | 终止符字符集 / `none` | 〔待批 N5 句尾标点：`none` 自动不适用〕 |
| `numerals` | 数字系统数组 | 〔待批 N6 中文数字：译侧可接受的数词体系〕 |
| `wordcount_basis` | `target-words` / `source-chars` | read 词数链：CLI 显式 > profile > 此处 > 内置 `target-words` |
| `eval_notes` | 同目录 md 文件名 | read 拷入 `job/lang_notes.md`，Step 2 评估注入（效力低于项目 SG/裁决） |

## 新语言接入（agent 自助，无需改代码）

1. 建 `<lang>.json`：lang = profile `language_pair` 后缀小写（`ZHCN-VI` → `vi.json`），按上表填属性
2. （可选）写 `eval_<lang>.md`：语言级 AI 评估关注点——只写语言学层面（语法范畴、敬语体系、文字系统陷阱），项目取向一律留项目层
3. 新检查需求先分类：语言学事实 → 提属性 + 代码推导一处；客户取向 → 项目 checks.json custom
