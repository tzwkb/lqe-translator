# NRC EN Style Guide（NRC-Mastersheet_LB [EN-SG] 全量转录 2026-06-10，维护人 Harry Leung）

## 核心风格
- **英语标准**：北美起点延伸全球，美式英语。Color（非 Colour）/ Defense（非 Defence）/ Center（非 Centre）
- **轻奇幻**：非黑暗史诗/高诗性。禁过度古英语（thee/thy/hath）；不堆砌华丽修辞；不用过长复合词；不刻意史诗感；避免亚瑟王过度联想（相关人名已做变体：亚瑟=Arthiel）。✔The wind feels strange here ✘The zephyrs whisper of forgotten destinies。补充：白树类古代角色台词故作神秘——EN 应"更清晰但用词高级"（未必古英语）；中文语义模糊勿直译，与项目组沟通；翻译保证 clean and clear
- **自然现代英语**：像原生英文写作。避中文语序/逐字对应/四字词堆叠/书面僵硬。命运交织的羁绊 ✘The intertwined bonds of fate ✔A bond shaped by fate；我一定要守护这片土地 ✘I must protect this land at all costs! ✔I won't let anything happen to this place.
- **沉浸感优先**：禁 UI 说明语气进剧情、过度解释世界观、破第四面墙、明显翻译痕迹
- **IP 规避**：避开宝可梦词汇（玩法/精灵名/独有物品名），且避免显出规避意图。草系 ✘Grass Type ✔Flora Type；火系水系不能为区分而区分 ✔Fire Type ✔Water Type

## 命名规则
- **地名**：城镇可创译，不必加 Village/Town；自然地貌可用 Valley/Cliffs/Cove/Pass/Mesa/Hollow/Bay/Plains/Harbor
- **道具**：[核心词]+类型名（Wish Crystal / Bloodline Elixir）；禁完整句、长修饰
- **精灵命名 9 条**：
  1. 压缩成专名勿描述句（✘Fire Lizard ✔Charmander=Char+Salamander）
  2. 意象融合非直译（Pikachu/Butterfree/Snorlax=Snore+Relax）
  3. 2-3 音节可读可念（Eevee/Lucario/Garchomp）
  4. 进化线家族感：共享词根渐进增势（Totodile→Croconaw→Feraligatr）
  5. 词根暗示属性不直写（Charizard 的 Char 暗示火）
  6. 可爱型圆润重复（Togepi/Jigglypuff）vs 强势型爆破硬辅音（Tyranitar）
  7. 禁明显影射现有名（✘Aquachu ✘Flamizard）
  8. 禁以黑/白等颜色为名字核心（异色版本联想+种族联想，✘Black Cat Jini）
  9. 禁体型评价词 fat/skinny/thin/chubby/massive/oversize/overweight（→fluffy/streamlined 等中性表达）
- **命名指南 5 步**（参考非强制）：外观可爱vs酷定音感长度→判断可否音译意译→习性入手（LOC_FILE 筛 PETBASE_CONF 查描述）→形态共享词缀做轴心（Pidgey→Pidgeotto→Pidgeot：幼=小型尾音/中=展开尾音/终=精炼尾音）→或风格/文化锁定家族感（Abra→Kadabra→Alakazam 咒语系；Ralts→Kirlia→Gardevoir 优雅系）
- **人物称呼**：NPC 标签=形容词+名词（Cruel Dark Wizard / Diligent Student / Young Onlooker / Wizard Lackey / Coven Member）；性别不明用 Youth/Youngster/Kid/Child/Onlooker（不用 young person）；禁外形词 fat/chubby/short/stout → cruel/gruff/rough/guard/gate/smaller figure
- **人名**：NPC 全欧美外观，避亚洲（尤其日本）/印度/非洲人名（除非设定支持）

## 本地化
- **文化处理**：不保留中文结构（成语/四字词/对仗不对应）；先理解功能（情绪/气氛/态度/信息）再用自然英语表达；英文无自然对应不硬造；可改写但不改设定含义；**禁拼音表达语气词**，感叹/犹豫/语气词全部转自然英语
- **幽默**：中文谐音/字面双关多数不能直接保留；优先保留角色语气；可重写同语气效果英文；尽量避免现代互联网用语（bro/sus/no cap）；幽默自然嵌入勿成焦点。（表内备注：举例类待补充，如精灵名"上岸蛙"的梗；客户标注"待补充案例"）
- **敏感内容**：避现实宗教/政治/国家结构对应词；明显现实含义词换中性奇幻表达；避现实群体负面描述；不确定就标记讨论勿自行决定

## 翻译方法
- **直译**：数值/属性/UI 按钮/系统提示/教程——标准术语对应标准表达（Health、Physical Attack），不发挥
- **意译**：诗意地名/世界观/抽象能量体系（愿力、魇力）/拟声——定核心含义气氛后自然英语重构，不改设定逻辑
- **混合**：直译生硬时保核心语义调整；核心设定必须保留、机制含义不变、语气可优化、表达可重构；自然度>一致性>形式对齐
- **通配符**：%s、{0}、{name}、尖括号/代码标签=程序变量，原样保留；语序可调但不得改通配符拼写/顺序/符号结构
- **UI 文本**：功能表达，简洁直接无情绪。按钮=动词原形/短名词（Save/Confirm/Start Battle）；禁完整礼貌句（✘Please confirm your selection）；系统提示短自然（Inventory Full / Not enough Mana / Quest Updated）

## 排版
- **大小写**：专有/系统/道具/技能名=Title Case；叙述/说明/对话=sentence case；the player/the crystal 一般叙述不大写
- **粗斜体**：原文没有不得自加（2026/3/21）
- **代名词**：精灵一律 it，无视性别（2026/5/12）
