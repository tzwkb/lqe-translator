# WWM/ZH-EN — LQA 人工结果分析与案例库

> 来源：《【AI】【英】0512【globaltrunk】【0511新增】_LQE Report.xlsx》（客户对 AI 中→英译文的人工质量评估，含 Error Severity / Error Definition / LQA Scorecard 三表）+《LQA template to evaluate current cooperating translators.xlsx》。
> 本文是 **wwm/zh-en 项目专有**的人工案例和历史报告分析。通用方法论见 `docs/质量检查项清单.md`；强制术语定译见 `confirmed_rules.md`《0512 确认记录》。"第 N 段"指 LQE 报告错误明细的 Segment 编号。凡归纳推断均注明"归纳"。

## 报告基础数据（0512 评分卡）

总词数 5,314；总分 82.78，低于阈值 98，判定 FAIL。计分错误 101 条（Minor 25、Major 35、Critical 41），另有重复标记 34 条（不计罚分）。

| 类别 | Minor | Major | Critical | 重复标记 | 加权罚分 | 占比 |
|---|---|---|---|---|---|---|
| Mistranslation | 2 | 22 | 41 | 13 | 783 | 85.6% |
| Terminology | 0 | 12 | 0 | 8 | 90 | 9.8% |
| Company style | 12 | 1 | 0 | 0 | 25.5 | 2.8% |
| Unidiomatic | 6 | 0 | 0 | 11 | 9 | 1.0% |
| Inconsistency | 5 | 0 | 0 | 2 | 7.5 | 0.8% |
| 其余 12 类 | 0 | 0 | 0 | 0 | 0 | 0 |
| 合计 | 25 | 35 | 41 | 34 | 915 | 100% |

41 条 Critical 构成（依错误明细整理）：成对祝词短句 26 条（"新岁临门""春风入户"等，第 47–75 段，修订稿两两押韵如 Door/Floor、Grows/Flows）；同流程对话选项 3 条（第 42–46 段）；玩法规则说明 7 条（第 256–265 段）；活动名称及签到界面文本 5 条。

主要结论：① 加权罚分 85.6% 来自 Mistranslation，集中于成对短句逐句直译 + 规则说明语义错；② Markup/Length/Punctuation/Spelling/Omission/Addition/Untranslated 在本报告均为零错误，pre-check 机制有效；③ 题目类文本（《玩法数据表_题目表》）预计同类风险（归纳）。

核验：罚分合计 915 = 计分错误加权和（重复 34 条未计入）；评分 1 − 915÷5314 = 82.78，与评分卡一致。

## 应用状态 changelog（2026-06）

- N1–N9 及 PM 反馈 #3/#7/#10 确定性检查已实施（2026-06-12）；N4 重复计分入 `lqe_calc`（repeated 列呈真实值）；成组送评（`--group-col` + 评估指引）接入 SKILL；0512 确认记录已归档（2026-06-11）。
- 与早期体系主要差异：重复错误仅首次计分（评分卡复核 34 条未计罚）；对联/题目按组评估（26 条 Critical 源于成对短句逐句直译）；使用人工确认规则（拼音残留/规则从严/平行句式/不得自创术语）；三点法则 + Word Choice 边界防误报；阈值分级 TEP/MTPE 98、润色/二审 99。

## 各子类 WWM 人工案例

**Mistranslation**（最大罚分来源）
- 拼音残留：画卯→Roll Call（误 Mark Mao，第 105 段）；平安→Peace（误 Ping'an，第 54 段）
- 普通词误作专名：年年（错误译为人名 Niannian，第 61 段）；岁月长安（错误关联城市 Chang'an，第 55 段）；紫色团花→purple flower（错误译为 Epic Flower，第 293 段）
- 规则文本：铜筹折算上限 2000（第 258 段）；多轮循环→Round-robin；规则说明类错译 7 条均为 Critical
- 操作指引：复原巨石使其停止（第 302 段）；招式→any attack（误 a Move，第 290 段）
- 价格限定语不可缺：折扣价格 2 音玉 译文缺"折扣"=Major（第 14 段）；"有机会获得[68金币]"错误译为 "contains [68 Gold]"=Critical
- 常见 Critical 情形（归纳）：误导玩家决策的规则、题答对应被破坏、占位符语义错位、涉付费/收益

**Terminology**（强制译名清单见 `confirmed_rules.md`《0512 确认记录》）
- 皇宫寻宝→Imperial Palace Treasure Hunt（误 Treasures of the Imperial Palace，第 2 段）；御前练兵→Imperial Drill（第 76 段）
- 新锐/新兵→Recruit、老将/老兵→Veteran（误 New Edge/Old General，第 366/367 段）
- 青→Halcyon（非拼音 Qing，第 194–201 段）；手札→Journal 统一（鹤的手札=Crane's Journal，误 Note，第 198 段）
- 不得通名自创专名：异色灵蝶→strangely colored butterflies（误 Spectral Butterfly，第 292 段）
- 系列名格式：赋神·乘桴归梦=Fu Shen - Rippling Dream，间隔号·→ - （第 13 段）

**Inconsistency**：平行句式统一 Complete any X once with a Veteran/Recruit（第 82–94 段，原 Team up with… 混用被标为错误）；任务名引用 Lost Chapter quest: X（第 89 段）

**Company style**：句中普通名词小写 accept a quest（第 155 段）；序号/卷号 Unicode 罗马数字（见 N3）；设施名方括号 [Stove]/[Dining Table]（第 260 段）；诗句宣传语允许押韵改写（第 249 段 bold/gold）；语域错置 Major 示例"Sup, Harry?"（古代背景用现代口语）

**Unidiomatic**：界面短句 Continue completing the X quest（去尖括号补通名 quest、句式大小写，第 17–28 段同问题 12 次）；直译腔 Warm Tips、Successfully Claimed

**Grammar/Punctuation/Spelling/Locale/Culture**（本次零计分，留错误定义表示例）：占位符后接可数名词复数兼容 "{} in {} day(s)"（第 107 段）；金额标点错误=Critical；Equipments/Acheive=Minor、accept/except 易混=Major；6/5/2023 日期歧义、人民币 299 误写 $299=Critical；文化错置 520/圣诞吃苹果

## N1 保留拼音名单（WWM）

报告修订稿确认保留的拼音专名：**Kaifeng、Qinghe、Jianghu、Fu Shen** 等（N1 拼音残留检查的白名单，命中这些不报）。新增专名经客户确认后续补。

## 实施事项归档（2026-06）

| 事项 | 涉及文件 | 状态 |
|---|---|---|
| 重复错误计分 N4 | lqe_calc.py | 完成 06-12 |
| 拼音残留 N1 / 同源异译 N2（含异源同译 ≥20 字） | lqe_checks.py | 完成 06-12 |
| 罗马数字 N3 | checks.json | 完成 06-12 |
| 0512 术语/风格确认记录 | confirmed_rules.md | 完成 06-11 |
| 评估引用清单 | SKILL.md | 完成 06-12 |
| 题目类成组送评（--group-col） | lqe_io.py、SKILL.md | 完成 06-12 |
| PM 反馈 N5–N9 及 #3/#7/#10 | lqe_io.py、SKILL.md、target_languages/ | 完成 06-12，PM 批准 |
