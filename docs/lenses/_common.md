# LQE 分块评估 · lens 公共规范

多 lens 架构:把"一个 agent 找所有错"拆成 4 个窄 lens（T/A/G/R），各只干自己那一摊、互不可见——**召回靠结构保证,不靠嘱咐**。每个 lens agent 读本规范 + 自己的 lens 文件，调用方另给 background / sg / lang_notes / adjudications / chunk / 输出路径。**本规范与各 lens 文件一律项目中立**——游戏题材/受众/语气从【背景】注入，目标语语域规则从【lang_notes】注入，别在本文或 lens 文件凭空假设某语种或某游戏。

## 先读（效力：adjudications > SG > 本规范）
- **背景**（`profile.background`，可空）：项目游戏类型/受众/语气/语域基调——据此校准「自然/口吻/语域」判断
- **adjudications**（共通+语言，已合并）：已裁决项不得判错
- **sg**（风格指南）、**lang_notes**（语言级关注点）
- **chunk**：每段 `{id, source, target, kind, precheck[], term_hits[]}`（`kind`=name/desc）

## 输出
只写**合法 JSON 数组**（无散文/无围栏）到指定路径。每条 `{id, errors[], corrected}`，`errors[]` 每条 `{category, severity, comment}`，comment 引中/译片段、中文说明。
- **只用本 lens 授权的类别**（见各 lens 文件）。不是你的类别 → 不报，留给对应 lens（防重防漏）。
- **severity**：Neutral / Minor / Major / Critical。lens 强制 Major：Terminology / Untranslated（Markup / Length 属 pre-check 确定性域、lens 不报、不在此规定其 severity）。存疑取重；数值/机制错=Major；表面拼写=Minor。
- **corrected**：本 lens 有真错 → 完整修正译文；无 → `null`；locked 段 → `null`。
- **四要素法则**：准确 + 合规（SG/术语）+ 合语法 + 自然 ⇒ 不是错，别造错；偏好性改写至多 Neutral——但功能/规则文本里的时态·搭配不当按 R「地道性分场景」可至 Minor。

## 地盘划分（谁报谁不报）
| lens | 类别 owner | 跑哪些段 | 输出 |
|---|---|---|---|
| **T 术语一致** | Terminology, Inconsistency, Company style + pre-check 甄别 | 全部段 | **全部段**（含无错段 `errors:[]`，是 merge 基准轴） |
| **A 准确机制** | Mistranslation, Omission, Addition, Untranslated(语义) | 全部段 | 只命中段 |
| **G 语法拼写** | Grammar, Spelling, Punctuation(语义) | desc 段 | 只命中段 |
| **R 语域自然** | Audience appropriateness, Culture specific reference, Unidiomatic | desc 段 | 只命中段 |

merge 由 `lqe_chunk.py merge-lenses` 做：T 为基准（全 id+无错段），A/G/R union 进来；多 lens 同段取优先级最高的非空 corrected 作底（A>T>G>R，保证 Suggest translation 不空），全部候选存 `corr_candidates` 待可选整合。**所以你命中错误必须填 corrected**（locked 除外）——你留 null 该段就少一个候选，整合质量下降。
