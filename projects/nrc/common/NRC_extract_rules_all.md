# NRC-Mastersheet_LB 全量提取 — 规则类 tab 合集
提取日 2026-06-10 | 来源: doc.weixin.qq.com/sheet/e3_AXUASgZQAPcCNW8ghvJILTMSDJPyw (14 tabs)
姊妹文件: NRC_extract_Glossary_multilang.tsv(多语术语库8986行,含TH+状态) / NRC_extract_CharacterVoice.tsv / NRC_extract_JiniFactions.tsv / NRC_extract_Query.txt(裁决摘要)

## 效力顺序（重要）
CN-EN更新要求（实时） > Query 裁决 > EN-SG/富文本规范 > 内置惯例。例证：Query 曾裁决"点击=Click/Tap"，6/1 更新要求改为统一 **press**。

## Checklist（项目交付检查清单，QA 直接引用）
交付件：1待翻译文件 2QA报告 3术语表
1. 待翻译文件表头/tab/原件一致，无错列、空白、筛选、隐藏
2. QA 报告中无有效问题（遗留）
3. 术语表登记完成：category、译文、必要 comment
4. Query 页已答复的问题完成修改；未答复的交付时备注临时方案
5. 检查文本字符限制
6. 待提交 changelog 提交完成

## 文本字符限制（含空格标点）
- TASK_DIALOGUE/SELECT_CONF、LOC_FILE/NPC_OPTION_CONF：中日韩 10 字；其他语言 不改字号 11 字 / 最小字号 32 字
- 所有精灵名字：12 字符

## CN-EN 更新要求（8 条，5/28-6/8）
1. 咕噜球=buddy pod；xx球=xx pod（TB已更）
2. /// 断句符（玩家点击触发下一句）：格式=无空格+///+1空格。"We can't wait any longer! /// We need to break out of here, now!"
3. xx系：名词=xx Class（大C空格）；形容词=xx-class（小c连字符，标题也小写）。Fire-class Skill Boost / Deals 0.5× damage to Flora, Ice, and Dragon Classes.
4. 游戏名=Roco Kingdom（"Roco Kingdom: World"=违禁词，"世界"不译）
5. 小洛克≠术语：禁 Little Roco；可 Young Roco / kid
6. (6/1) 点击=press 统一双端；双击=double press（废止 click/tap）
7. (6/8) 双防/双攻=Dual Defense/Dual Attack（禁 Physical and Magic Attack）
8. (6/8) 呵呵嘿嘿：禁 Hehe；用 Heh / (Playful Laugh) / (Giggle) / 省略

## 富文本使用规范
- {gender:a,b} 性别通配符：保持不变；a=男称呼 b=女称呼按玩家性别（EN={gender:he,she}）
- {} 内文本（除性别通配符）=占位符：EN 按占位符映射表译英；JA 保留中文；其他语言保留英语
- {name}=玩家名：不译保留（译文流畅时可去掉，已确认不报错）
- <a id="洛克里安"> 样式已废弃，再出现报 Query
- 占位符映射表（中文 Pattern→新英文 Pattern）：精灵物种→PetSpecies、精灵等级→PetLevel、精灵重量→PetWeight、精灵身高→PetHeight、已捕捉数量→CatchCount、精灵阶位→PetStage、新捕捉精灵总数→SubmitPetNum、捕捉精灵报告→SubmitPetReport、星链移转发起方玩家名字→MiraclePlayerName、发起方玩家名字→MiracleFinishPlayerName、发起方玩家的精灵名字→MiracleFinishPetName、物品数量:(%d+)→ItemCount:(%d+)、物品名称:(%d+)→ItemName:(%d+)、庇护所升级消耗→SanctuaryLevelUpCount、精灵上报→CampPetReport、切磋胜利场次→PvpWin、切磋失败场次→PvpLose、切磋最常用精灵名称→PvpPetName、切磋最常用精灵形态→PvpPetForm、选择精灵名称→FinalBattlePetName、树苗所处地区→FruitTreeArea、图鉴考核差值→FruitTreeDiffNum、图鉴考核数量→FruitTreeTotalNum、可解锁土地数量→MaxUnlockFarmLandNum、跟随任务→Follow Task、跟随NPC→Follow NPC；（精灵名字行后标注"以下是待收录占位符"）

## EN-SG 全文要点（30 行，Harry Leung 维护）
核心风格：美式拼写（Color/Defense/Center）；轻奇幻（禁 thee/thy/hath、不堆修辞、白树类角色可"高级但清晰"、中文语义模糊勿直译要沟通）；自然现代英语（禁中文语序/逐字/四字堆叠；命运交织的羁绊→A bond shaped by fate）；沉浸感（禁UI语气进剧情/过度解释/破第四面墙）；IP规避（避宝可梦词汇但勿显刻意：✘Grass Type✔Flora Type；火/水系不强行区分 ✔Fire Type）
命名规则：地名可创译不必加 Village/Town，可用 Valley/Cliffs/Cove/Pass/Mesa/Hollow/Bay/Plains/Harbor；道具=[核心词]+类型名（Wish Crystal）；精灵命名 9 条——压缩专名勿描述句、意象融合（Bulbasaur式）、2-3音节可读、进化线家族感（共享词根渐强）、词根暗示属性（Charizard）、可爱圆润vs强势爆破音、**禁影射现有名（✘Aquachu/Flamizard）**、**禁黑/白颜色核心名**（异色联想+种族联想）、**禁体型评价词**（fat/skinny/chubby/massive/oversize→fluffy/streamlined）；附命名指南5步（外观定音感→音译意译判断→习性入手查PETBASE_CONF→形态共享词缀轴心(Pidgey式)→风格/文化锁定(Abra咒语系)）
人物称呼：NPC标签=形容词+名词；性别不明用 Youth/Youngster/Kid/Child/Onlooker；禁外形词 fat/chubby/short/stout→cruel/gruff/guard 等
人名：NPC 全欧美外观，避亚洲（尤其日本）/印度/非洲人名
本地化：文化处理（不保留中文结构、禁拼音语气词）；幽默（谐音双关重写语气、禁 bro/sus/no cap）；敏感内容（禁现实宗教/政治/国家对应词，不确定就标记讨论）
翻译方法：直译（数值/属性/UI按钮/系统提示）；意译（诗意地名/世界观/愿力魇力/拟声）；混合（核心设定保留语气可重构，自然度>一致性>形式对齐）
通配符：原样保留 %s {0} {name}，语序可调不得改通配符拼写/顺序/符号
UI 文本：动词原形/短名词（Save/Confirm/Start Battle）；禁完整礼貌句；系统提示短自然（Inventory Full）
大小写：专有/系统/道具/技能=Title Case；叙述/对话=sentence case；the player/the crystal 不大写
粗斜体：原文没有不得自加（3/21）
代名词：**精灵一律 it 无视性别**（5/12）

## 叙事文本 goodcase（4 段落+审注）
基准译例：伊里斯=Irys、翼王眷属=King of Flight's kin、泡泡老师=Professor Bubby、罗兰=Ronan、大魔法师=Archmages、愿力强化=Wishpower Boost、卡洛西亚=Caeroxia、亚瑟=Arthiel、可丽希亚=Krithya、火花=Sparka、凶狠胖鸭→crazy duck
创作尺度：自由改写 OK（"咦，这就是飞艇吗，怎么破破的？"→"A shipwreck! That's our ride to the academy?" 审注：发挥稍多可确认）；语气词表达情感（可恶！→Tch—；大，大人？→M-my Lord?）；过度创作会被标注（Hoory, I mean hurry!→叙事组确认）

## 待提交 changelog（TB 待改项）
coolu→Mr. Hoolu；Jini复数 Jinis→Jinies（"now we are going by Jinies, fyi"）；炫彩→Iriscent；异色炫彩→（待定）；Blackout In/Out→fade in/out/fade to black 系；白兔灯塔 Hara Lighthouse→Harelight Tower

## Glossary 结构（NRC_extract_Glossary_multilang.tsv）
列：剧情范围 | Category | 术语ZHCN | 曾用名 | 定义 | 性别 | 图像 | 来源 | EN+Comment+Status | JA | ES | DE | FR | PTBR | RU | ID | KO | **TH** | ZHTW（各语种带 Status）
状态：Approved已确定 / New待审核 / Pending原文或指定译文可能改 / Denied不通过 / Updated需统改历史译文
TH 列已有大量条目（มาร์วิน/ฟีบี/ลูอิส…多为 New 状态）——TH QA 时 Approved 严格执行，New 软参考

## Glossary Category（术语分类法）
Character Name: Named NPC/Generic NPC/Enemy NPC；Jini: Creature Species（1/3 2/3 3/3=进化链，命名需整链考虑）/Creature Individual；System Narrative Object: Interactive/Narrative Element；Lore: Core Lore/Faction/Title；Gameplay: System/Key Items/World Resources/Overworld Exploration Abilities/Special Mechanics/Utility Systems/Presentation/Social；Cosmetics: Costumes(时装品牌)/Cosmetics system；System: PvE/PvP/Seasonal/Jini Base Stats/Growth/Traits/Combat/Evolution/Personality/Rank Tags；Map: Functional Area/Administrative Region/Macro Region/Urban Area/Settlement/Wilderness

## 译名速查（摘自 Lore；设定正文见 NRC_extract_Lore.md，官方EN以 Glossary 为准）
精灵=Jini（复数 Jinies）、洛克=Roco(s)、卡洛西亚=Caeroxia、洛克星=planet Roco、咕噜球=Buddy Pod、星之结=Star Nexus、契约=Pact、愿力共鸣=Wishpower Resonance、愿力魔法=Wishborne Magic、愿力=Wishpower、魇力=Malforce、黑魔法=Dark Magic/Forbidden Arts/Nightmare Power、传说精灵=Legendary Jini、精灵王=Jini Sovereign（翼王=King of Flight、幻系精灵王=King of Stars、毒之精灵王=Jini Queen of Poisons）、精灵对决=Jini Duel、共鸣魔法=Resonance Rituals、风眠省=Windrest Province、王国城堡=The Citadel（光之城=City of Light）、洛克里安=Rocarian、彼得大道=Petiapolis（彼得=Petyr、斯诺克公司=Sennoc Corporation）、亚瑟王=King Arthiel、圣安德鲁=King Aindreas、紫雀花王朝=Violaethran Dynasty、紫雀花战争=Violetfinch War、玛丽女王=Dread Empress Marethis、毒法师=Maleficars、黑暗星盘=Dark Stardials、白银骑士团=Argent Knights、圆桌骑士团=Knights of the Round Table、噩梦教团=Nightmare Cult（黑巫师=Dark Wizards）、四大分院=School of Jini/Combat/Alchemy/Rituals、炫彩球=Iridescent Pod、四大家族=House of Mozard/Pierre/Skyden/Drakeford、愿晶=Wishing Crystals、玄玉=Xuanyu、索米亚草原=Somia Grasslands、帝达尔圣城=Holy City of Didar
**18 元素系别官方EN**：普通Common 草Flora 火Fire 水Water 光Light 地Earth 冰Ice 龙Dragon 电Electro 毒Poison 虫Bug 武Fighting 翼Wing 萌Charm 幽Shadow 恶Havoc 机械Mech 幻Stella

## Project information
Code: NRC；品类 Open World/Creature Collection/PVP；语言对 ZHCN-EN、ZHCN-JA、EN-ESLA、EN-DE、EN-FR（TH 不在此表但 Glossary 有 TH 列）；平台 Mobile/PC/Steam；参考：biligame 107079、B站官号 626796832、世界观私戳 yelin
