# WWM（燕云十六声）裁决与经验 — 评估前必读
来源: WWM 历史 LQE 实操（Pet System 260601 首评 77.77 → 迭代 100 通过）+ 权威 SG（sg.txt 整合版，与桌面 LQE工作文件/styleguide.txt 有出入，以 sg.txt 为准）

## 术语匹配原则
- 28,534 条官方术语库（中文/英文/分类），专有名词（角色/地名/武学/技能）**严格一致**
- **泛词命中按语境甄别勿硬判 Terminology**（小猫咪、河边石头等日常词条命中≠错误）
- 文化术语强制映射: 枪→Spear、火药→Explosive Powder、师傅/公子→Master、龙/凤/蛟→Dragon/Phoenix/Serpent、笔→Brush、火铳→Fire Lance、侠→Hero、大侠→Great Hero、少侠→Young Hero

## 硬规则（部分已由 builtin/custom 检查覆盖）
- **非代码内容禁用 `< >`，改半角直引号**（代码标签 <desc_id=…> 合法——需人工区分，勿确定性硬判）
- 禁破折号 `—` → ` - `（builtin em_dash 开）；中文 `·` → ` - `（custom）
- 全部半角标点；严格对齐原文标点（原文无句号译文不加）
- 千位分隔符 2,000；物品数量 Item ×N（× 前空格后无空格）
- 颜色标签 #G/#C/#Y…#E 保持相对位置；变量 {} %s {slot_name} 原样、前后加空格；\n 保留
- 大小写: UI/技能/道具/地名/角色/成就=Title Mode；对话/描述/提示=Sentence Mode

## RAG/TM 保护
输入若含 rag/tm/memory/match/score/locked 列且为 100%/exact/locked → 不修改、不计分、corrected=null、export 保留原译文
