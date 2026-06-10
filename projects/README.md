# projects/ 文件地图

每个 LQE 项目一个目录，`read --project <目录名>` 即用。本目录整体 gitignored（客户数据不上 GitHub）。

## 通用结构（每个项目）
| 文件 | 角色 | 谁读 |
|---|---|---|
| `profile.json` | 项目配置：SG/术语/词数基准/阈值（相对路径相对本目录） | `lqe_io.py read --project` |
| `checks.json` | 确定性检查：内置开关 + 自定义 regex | `lqe_io.py pre-check` |
| `adjudications.md` | 客户裁决/经验记录，防误报 | Agent（评估前必读） |
| `terms_*.json` / `*.xlsx` | 术语表（json 可带 status） | read 时拷入 job |
| `sg.*` | 风格指南源文件 | read 时转文本拷入 job |
| `inputs/` | 待评估的原始交付文件 | 人工指定给 read --input |

## nrc-th/ —— 洛克王国《世界》中→泰【本次 QA 项目】
- `Style Guide Translation TH_20260430.xlsx` = 客户泰语 SG **原件**（企微 6/9 收，本次 QA 用这份）
- `ROCO_Working TB - TH(1).xlsx` = 客户术语表**原件**（本次 QA 权威术语源，3,131 条）
- `terms_th.json` = tb_working(WorkingTB,硬判) + NRC主库TH列独有补充(New,软判) 合并 3,133 条
- `inputs/普老师SourceTarget.xlsx`（1,614 段，86 空译文）、`inputs/夏老师SourceTargetFinal.xlsx`（~4,384 段，178 空译文）= 待评估译员文件
- `inputs/LOC_FILE-…QAFeedback.xlsx` = 客户反馈回填模板（5 列格式）

## nrc-en/ —— 同项目中→英轨
- `sg_en.md` = NRC 主表 EN-SG tab 全量转录
- `terms_en.json` = 主库 EN 列 2,945 条（586 Approved）

## nrc-common/ —— NRC 两轨共享参考（出自 NRC-Mastersheet_LB 在线表，6/10 提取）
- `NRC_extract_rules_all.md` = 14 tab 规则合集（Checklist/字符限制/更新要求/富文本/Lore 术语对照）
- `NRC_extract_Glossary_multilang.tsv` = 多语主术语库（ZHCN→11 语种+状态），terms_*.json 的上游
- `NRC_extract_Query.txt` = 60+ 客户裁决摘要（adjudications 的上游）
- `NRC_extract_Lore.md` = 世界观圣经全文（设定一致性依据，**非术语**；译名以 Glossary 为准）
- `NRC_extract_goodcase.md` = 叙事好例全量（创作尺度基准，含审注）
- `NRC_extract_GlossaryCategory.md` = 术语分类法全量（QA 术语错误归类标准）
- `NRC_extract_CharacterVoice.tsv` / `NRC_extract_JiniFactions.tsv` = 角色圣经 / 精灵谱系
- `LQA_template_extract.txt` = 客户 LQA 模板拆解（Error Log 7 列 + 计数制评分卡）——**归属哪条线待确认**

## wwm/ —— 燕云十六声中→英（历史项目，随时可复跑）
- `sg.txt` = 权威整合版 SG；`terminology_0509.xlsx` = 官方 28,534 条术语库（自包含副本）

## xiuxiu/ —— 咻咻勇者（非 LQE 项目，仅存参考）
- `咻咻勇者_内部SG_Query_extract.txt` = 内部 SG 32 条 regex 检查清单 + Query 表（建档时可直接转 checks.json）

## 运行产物
`../jobs/<输入文件名>/` —— read 初始化生成，state.json/sg.txt/terms.json/报告/修正稿都在里面，与 projects 互不污染。
