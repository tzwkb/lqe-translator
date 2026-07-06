# projects/ 文件地图

布局 `<game>/<source>-<target>/`（语言对轨）+ `<game>/common/`（游戏级共享素材），`read --project <game>/<source>-<target>` 即用（skill 根解析，CWD 无关）。目标语言学事实另见 `../target_languages/<code>/`。开发仓（Langglobal，GitHub 私有）跟踪客户数据；skills 测试副本侧 gitignored。

## 通用结构（每个项目）
| 文件 | 角色 | 谁读 |
|---|---|---|
| `profile.json` | 项目配置：SG/术语/阈值（相对路径相对本目录） | `lqe_io.py read --project` |
| `checks.json` | 确定性检查：内置开关 + 自定义 regex（仅项目风格取向） | `lqe_io.py pre-check` |
| `adjudications.md` | 客户裁决/经验记录，防误报 | Agent（评估前必读） |
| `terms_*.json` | 术语表（派生配置，json 可带 status） | read 时拷入 job |
| `sg_*.md` / `sg.txt` | 风格指南（文本版） | read 时转文本拷入 job |
| `sources/` | 客户原始交付件（SG/TB xlsx 原件及其工作副本） | profile 引用 / 溯源 |
| `inputs/` | 待评估的原始交付文件 | 人工指定给 read --input |

目标语言事实型默认（词数基准、检查适用性）不在项目层——见 `../target_languages/<code>/attributes.json`，按 profile `target_lang` 自动挂载；合并顺序 内置默认 < 属性推导 < 项目 checks.json < CLI。

## nrc/zh-th/ —— 洛克王国《世界》中→泰【本次 QA 项目】
- `sources/Style Guide Translation TH_20260430.xlsx` = 客户泰语 SG **原件**（企微 6/9 收，本次 QA 用这份）
- `sources/ROCO_Working TB - TH(1).xlsx` = 客户术语表**原件**（本次 QA 权威术语源，3,131 条）
- `sources/Working_TB_THTH.xlsx` = WorkingTB 状态子集工作副本（457 条，terms_th.json 上游工件）
- `terms_th.json` = tb_working(WorkingTB,硬判) + NRC主库TH列独有补充(New,软判) 合并 3,133 条
- `locked_terms_batch4.json` = 0611 审校"锁定"术语对照清单（adjudications 引用，TB 未改动）
- `inputs/普老师SourceTarget.xlsx`（1,614 段，86 空译文）、`inputs/夏老师SourceTargetFinal.xlsx`（~4,384 段，178 空译文）= 待评估译员文件
- `inputs/LOC_FILE-…QAFeedback.xlsx` = 客户反馈回填模板（5 列格式）

## nrc/zh-en/ —— 同游戏中→英轨
- `sg_en.md` = NRC 主表 EN-SG tab 全量转录
- `terms_en.json` = 主库 EN 列 2,945 条（586 Approved）

## nrc/common/ —— NRC 全语言轨共享参考（出自 NRC-Mastersheet_LB 在线表，6/10 提取）
- `NRC_extract_rules_all.md` = 14 tab 规则合集（Checklist/字符限制/更新要求/富文本/Lore 术语对照）
- `NRC_extract_Glossary_multilang.tsv` = 多语主术语库（ZHCN→11 语种+状态），terms_*.json 的上游
- `NRC_extract_Query.txt` = 60+ 客户裁决摘要（adjudications 的上游）
- `NRC_extract_Lore.md` = 世界观圣经全文（设定一致性依据，**非术语**；译名以 Glossary 为准）
- `NRC_extract_goodcase.md` = 叙事好例全量（创作尺度基准，含审注）
- `NRC_extract_GlossaryCategory.md` = 术语分类法全量（QA 术语错误归类标准）
- `NRC_extract_CharacterVoice.tsv` / `NRC_extract_JiniFactions.tsv` = 角色圣经 / 精灵谱系
- `LQA_template_extract.txt` = 客户 LQA 模板拆解（Error Log 7 列 + 计数制评分卡）——**归属哪条线待确认**

## wwm/zh-en/ —— 燕云十六声中→英（历史项目，随时可复跑）
- `sg.txt` = 权威整合版 SG（上游 `sources/WWM_Style_Guide_0612.docx` + `sources/WWM_Style_Guide_0701.docx` 补充）；`sources/terminology_0701.json` = 官方术语库（上游 `sources/terminology_0701.xlsx`）

## 运行产物
`../jobs/<输入文件名>/` —— read 初始化生成，state.json/sg.txt/terms.json/报告/修正稿都在里面，与 projects 互不污染。
