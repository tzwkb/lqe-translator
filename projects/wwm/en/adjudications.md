# WWM（燕云十六声）裁决与经验 — 评估前必读
来源: WWM 历史 LQE 实操（Pet System 260601 首评 77.77 → 迭代 100 通过）+ 权威 SG（sg.txt 整合版，与桌面 LQE工作文件/styleguide.txt 有出入，以 sg.txt 为准）

## 术语匹配原则
- 官方术语库（terminology_0701.json，中文/英文），专有名词（角色/地名/武学/技能）**严格一致**
- **泛词命中按语境甄别勿硬判 Terminology**（小猫咪、河边石头等日常词条命中≠错误）
- 文化术语强制映射: 枪→Spear、火药→Explosive Powder、师傅/公子→Master、龙/凤/蛟→Dragon/Phoenix/Serpent、笔→Brush、火铳→Fire Lance、侠→Hero、大侠→Great Hero、少侠→Young Hero

## 硬规则（机械/格式取向一律以 SG 为准，勿在此复述）
标点半角与对齐、破折号·间隔号、千位、Item ×N、颜色标签/变量/换行、大小写 Title/Sentence 等**以 `sg.txt` §二/§三 为准**；已由检查自动覆盖的见 `checks.json`（middot/x-count/roman）+ pre-check（em_dash/全角标点/Markup/Length）。此处仅记 SG 未明、或需人工判的偏差：
- **非代码内容禁用 `< >` 改半角直引号**；代码标签 `<desc_id=…>` 合法——人工区分，勿确定性硬判。

（RAG/TM/locked 100% match 保护属通用 skill 机制，见 SKILL.md Step 1.2，非本项目裁决，已从此处移除）

## 0512 globaltrunk 人工 LQE 裁决（2026-06-11 注入，效力=Query 级）
源：《【AI】【英】0512【globaltrunk】【0511新增】_LQE Report》——人工审校对 AI 译文的实判（×=被判错的 AI 译法）。检查项与关注点总表见 docs/质量检查项清单.md。

### 术语定译
- 画卯=Roll Call（×Mark Mao）；画卯奖励=Roll Call Rewards；本人已到！=I'm here!
- 太极/强化太极=Cosmic Reversal（×Tai Chi）
- 新锐|新兵=Recruit；老将|老兵=Veteran（×New Edge / Old General）
- 青（巨子/手札）=Halcyon（×Qing）；与巨子青书=Letter to Grandmaster Halcyon
- 皇宫寻宝=Imperial Palace Treasure Hunt（×Treasures of the Imperial Palace）；前往寻宝=Go Treasure Hunting
- 御前练兵=Imperial Drill（×Prep – Defense Drill）
- 智赛·斗财主=Wisdom Contest: Landlords（×Wisdom Tournament - Landlords）
- 芝兰自芳=Fragrant Orchid；X·典藏=X - Premium（×Premium Collection）
- 鳞跃龙扉=Transcendence Gate（×Leap of the Dragon Gate）
- 赋神·乘桴归梦=Fu Shen - Rippling Dream（×Drifting Home on Dreams / Drifting Reverie）
- 桃源三剑·完本=Three Swords of the Haven（"完本"不译出）
- 残章任务=Lost Chapter quest；高堂野客·上=Throne and Tempest Ⅰ
- 手札=Journal 统一（鹤的手札=Crane's Journal，×Note）
- 瑞兽葡萄飞天镜=Apsara Grape Mirror（×直译长名）
- 朝生暮落花的寒花=frost flowers（×buds）
- 异色灵蝶=strangely colored butterflies（通名，×Spectral Butterfly——勿过度术语化）
- 心力值=Energy；青云之路=Azure Path（×Path to High Honors）
- 灶台=[Stove]、餐桌=[Dining Table]、蒸馏塔=[Distillation Tower]、窑炉=[Kiln]、休憩设施=[Resting Facility]、云间渡=[Cloudrest Passage]

### 风格/流程裁决
- 序号/卷号用 Unicode 罗马数字 Ⅰ Ⅱ Ⅲ Ⅳ（×ASCII I II III）：青的手札 - Ⅰ；Seek Within - Volume Ⅱ
- 设施/可放置物名用方括号 [X]（×「」保留、×#Y"X"#E 引号式）
- `<任务名>` 引用→去尖括号补通名：Continue completing the X quest（句子化大小写，×Continue Completing）
- 平行任务句族统一句型：Complete any X once with a Veteran/Recruit（×Team up with… and complete…）
- 对联/题目类文本**成组译**：上下联对仗+押韵（New Year at the Door / Spring Winds Grace the Floor；…the Pay Grows / …the Fortune Flows），拆单句直译=Critical
- 玩法规则文本错译一律 Critical；占位符缺失（`{}天后领取{}` 丢一个）判 Mistranslation Critical
- 重复错误：标 Repeated=YES 记录但不罚分（34 条实证）
- 及格阈值：TEP/MTPE=98；润色/二审=99

## 2026-06-22 社媒文案 PM 反馈（效力=Query 级）
源：《LQE测试用_社媒_lqe（已反馈）》第三表 PM 确认列。营销/社媒 transcreation 漏译口径：
- 纯氛围/叙事修饰被简化省略 **≠ Omission**（至多 Neutral）——宣传文案允许浓缩（如「隐雾林出现了新的面孔」铺陈新 NPC 登场，简化可省）。
- 但功能/商业信息漏译仍 = **Omission**：限时·数量·奖励·价格·条件·资格·玩法机制（「活动限时开启」漏「限时」=Omission Major，商业文案时效性不可丢）。
- 语气性反问尾（不是吗/对吧）承载语气，漏译记 Omission（审校实判：源「…不是吗？」译文丢 don't we?）。
- 弯引号 ' ' " "（U+2018/2019/201C/201D）违 SG 半角直引号——已转 pre-check 确定性检查（checks.json `wwm-smart-quotes`）。
