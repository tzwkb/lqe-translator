# NRC 裁决记录（EN 轨）— 评估前必读，防止把已裁决项判成错误
来源: NRC-Mastersheet_LB (2026-06-10)。效力顺序: **CN-EN更新要求 > Query 裁决 > EN-SG**（实证: 6/1 press 废止 Query 的 Click/Tap）。
全量参考: `../nrc-common/NRC_extract_rules_all.md`

## 术语状态语义（terms_en.json）
Approved=严格执行(偏离=Major)；New=待审核(soft，按语境甄别)；Updated=按新译统改；Pending/Denied=不可硬判；?=列对齐噪音忽略

## 已裁决（不是错误）
- {name} 可去掉（若更流畅，不报错）；{gender:a,b}→{gender:he,she}
- 「」专有名词强调: EN=首字母大写；**禁止目标语添加源语没有的代码**（ruotong 裁决）
- 老师→Professor（魔法学院无 Teacher/Professor 之分）
- 噜噜口癖 咕=hoo（非 coo）；麦克达克=公鸭；Most impressive 英美通用可用
- 洛克复数=Rocos；Jini 复数=Jinies（changelog 已定）；咕噜球=buddy pod、xx球=xx pod
- xx系: 名词=xx Class、形容词=xx-class（标题也小写c）；18系官方名: Common/Flora/Fire/Water/Light/Earth/Ice/Dragon/Electro/Poison/Bug/Fighting/Wing/Charm/Shadow/Havoc/Mech/Stella
- 阿卡系=Arca（阿卡原浆 Arca Juice）；嘟嘟锅=Brewbane；原野空径=Wildway；契约印记=Starseal；贤者碎晶=Philosopher's Shard
- 小X精灵名: 禁 Little+X/拼音，参考 小沃Wade/小宝Bo/小洛Logan/小冰Ben/小雪Sean
- 中文typo正字: 伊里斯/莫里亚克/岚语峰/出战；薛定量子猫→魔盒猫；金牌向导=金牌信使（统一）
- 异色同名精灵无需区分译名；场下精灵=队伍已编入未派出；本期=赛季周期
- 「废弃」物品/配置测试文本（布石、UIi编辑器、俯仰值、"请在文本秒内"）→ 不用翻，勿判 Untranslated
- 玄玉中国风内容不能变（case by case）；/// 与 ### = 断句符=分行；1357号=1、3、5、7
- 精灵代词一律 it；粗斜体不得自加；NPC 人名避亚洲/印度/非洲名
- 待确认中（勿硬判）: ///前侧空格（规则文本"无空格"vs官方示例"! /// We"矛盾）、维奥拉/薇奥拉、武系=Martial?、多多=toto(暂)

## 计数制评分卡映射（LQA template，若客户要求该格式）
Omission/Addition 10 | Mistranslation 20 | Untranslation 20 | Punctuation&Formatting 5 | Spelling 10 | Grammar 10 | Term Consistency 10 | Style/Tone 5 | Word Choice 5 | Naturalness 5；阶梯见 LQA_template_extract.txt；Preferential 不扣分
