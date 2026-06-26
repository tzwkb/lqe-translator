# 术语表自审 · lens 拆分设计

术语表/glossary 自审（目标语译文本身是审校对象、无外部 TB 可比）的多 lens 方案。取代旧的"单套 RUBRIC × 双遍(p1∪p2)"。

## 背景

旧路径：`mastertb_prep.py` 用一个合并 `_RUBRIC.md`，对每块派 1 agent 判全部错误类型，再跑第二遍 `p2`、按 id 取 `set(p1)|set(p2)` 并集。

0626 ROCO MasterTB 阿珠版实测暴露两个问题：

- 单 agent 既判专名音译又判描述词义，注意力被显眼错（垃圾值、名字译错）锚定，放过细的（词义漂移、不地道、缺字符）。被限流逼成单遍后召回 ~14%（0624 双遍 210 条，本轮命中 29、漏 135）。
- 双遍 = 相同规则重复跑，堆召回也堆假阳、收益递减、费 token。

结论：召回靠**按错误类型拆分工**，不靠重复遍数。删双遍。

## 原则

- lens 文件项目/语言中立（同 `docs/lenses/_common.md`）。判法通用；题材/受众/语气走 `background` 注入，目标语正字/语域/音译惯例走 `lang_notes` 注入，逐条裁决走 `adjudications` 注入。lens 文件内禁出现具体语种（泰文/RTGS）或具体游戏名。
- 复用现有 `T/A/G/R`，仅新增 `N`（专名音译），并把 `A` 限定到 `desc`。
- 术语特有上下文（EN/类别/性别/定义）由 `mastertb_prep.py chunks` 注入 chunk，供 `N`（音译对 EN 锚）和 `A`（语义对中文）使用。

## lens 集（5）

| lens | owner 类别 | 跑哪些段（kind） | 查什么 | 中立·靠注入 |
|---|---|---|---|---|
| T | Inconsistency, Company style, 占位/垃圾值甄别 | 全部（基准轴，含无错段） | 同源异译、同译异源、统一译名违规、禁名、占位/垃圾值（如义=「动物」的通用词顶替专名） | 裁决/统一译名走 adjudications |
| N | Mistranslation, Culture specific reference（专名） | name | 音译是否对 EN 锚；丢音节、整名认不出、撞真实品牌、人名/地名张冠李戴；EN 缺时据源读音判 | 音译惯例(罗马化/声调位置)走 lang_notes |
| A | Mistranslation, Omission, Addition, Untranslated | desc | 译文义 vs 中文义：词义漂移/反义、漏加意义成分、占位未译、误填他值 | — |
| G | Spelling, Grammar, Punctuation | 全部 | 目标文字正字：缺/错字符、附加符号(声调/元音)位置、拼写 | 目标文字正字细则走 lang_notes |
| R | Unidiomatic, Audience appropriateness, Culture specific reference | desc | 是否合题材语域：生硬、粗俗、过度正式 | 题材/语气走 background |

地盘互斥：每 lens 只报自己 owner 的类别，非己类别留给对应 lens（防重防漏，同 `_common.md`）。

## kind 路由

`mastertb_prep.py chunks` 给每条加 `kind`，由 `category` 推：

- `name` = Named NPC / Creature Species / Creature Individual / Settlement / Wilderness / Macro Region / Administrative Region / Urban Area / Functional Area（专名类）
- `desc` = Generic NPC（描述短语）/ Core Lore / Narrative Element / Jini Combat System（技能）/ Jini Traits System / Jini Personality System / Interactive Narrative Object / 道具描述 / Cosmetics（描述性时装名）

推导规则：category 命中 name 集 → name；否则 desc。存疑偏 desc（多一道 A/R 覆盖）。
Creature Individual 多为描述短语（如「愤怒的海豹战士」），按是否含描述词细分；无法判定归 desc。

派发门控：N 只跑 name；A、R 只跑 desc；T、G 跑全部。

## 数据契约

chunk 段（`mastertb_prep.py chunks` 产出，已带上下文）：

```
{"id":422,"zhcn":"伊贝儿","en":"Mossip","definition":"J0055 1/2",
 "category":"Creature Species","gender":"","th":"อีเบย์",
 "th_comment":"","kind":"name","auto_flags":[]}
```

lens 输出 `chunk_NN.<L>.json`，L ∈ {T,N,A,G,R}：

```
{"chunk":1,"reviewed_first":300,"reviewed_last":599,"reviewed_count":300,
 "findings":[{"id":422,"errors":[{"category":"Mistranslation","severity":"Major",
   "comment":"中文'伊贝儿'/EN'Mossip'/泰译'อีเบย์'(读作品牌eBay)…"}],
   "corrected":"มอสซิป"}]}
```

`zhcn` 进 lens 时映射为 `source`、`th` 为 `target`，与句子流 lens schema 对齐；额外 `en/definition/category/gender` 随 chunk 附带，N/A 读取。

## merge 与 corrected 优先级

复用 `lqe_chunk.py merge-lenses`，扩 lens key 集到 {T,N,A,G,R}：

- T 为基准轴（全 id + 无错段）。
- N/A/G/R union 进来。
- 同段多 lens 命中，corrected 取优先级最高的非空：**N > A > T > G > R**（专名以 N 的音译为准）。全部候选存 `corr_candidates`。

删旧 `mastertb_prep.py merge` 的 `set(p1)|set(p2)` 双遍并集逻辑。

跨词条一致性仍由 `consistency.json` 折叠进 T（同源异译/同译异源），非 lens 内判。

## 召回闸（verdict gate）改造

现 `recall_status.json` 的 `single_pass` 判据是「每块是否有 `.p2.json`」。删双遍后迁移为「每块各适用 lens 是否齐」：

```
required(chunk) = {T,G} ∪ ({N} if 含 name 段) ∪ ({A,R} if 含 desc 段)
complete = ∀chunk: required(chunk) 的 lens 文件均合法落盘
verdict_allowed = complete
```

任一适用 lens 缺失 → `verdict_allowed=false`、分数只作"临时下限"、产物标红、不出 PASS/FAIL（同 SKILL.md step 3「降级不出裁决」）。

## 实现改动清单（已实现）

共用文件安全：`A.md`/`G.md`/`R.md`/`T.md` 与 `lqe_chunk.py` 同时服务句子流 LQE（A.md 明文「跑全部段含 name 短词」）。本次**不改其内容/行为**——术语模式的差异（A 只判 desc、name 归 N、外部 TB 关）全走 `_term_audit.md` 注入覆盖；对 `lqe_chunk.py` 只做**向后兼容的增量**（句子流不产 N 文件 → 跳过/不校验）。

`docs/lenses/`（新增，不动 A/G/R/T 内容）
- 新增 `N.md`：专名音译 lens，中立。
- 新增 `_term_audit.md`：术语自审附录——A 限 desc、name 归 N、门控、外部 TB 关、占位/垃圾值与系列上下文提醒。
- `_common.md`：地盘表加 N 行 + 指向 `_term_audit.md`；corrected 优先级注记改 N>A>T>G>R。

`scripts/lqe_chunk.py`（增量、向后兼容）
- `merge-lenses`：`_LENS_ADD` 加 N（缺文件即跳过）；corrected 优先级 `("N","A","T","G","R")`。
- `validate-lenses`：枚举含 N 但 **N 可选**（缺 N 不报，句子流不受影响）。

`scripts/mastertb_prep.py`
- `chunks`：`_kind(category, zhcn)` 推导写入每段 `kind`（name 类目→name；Creature Individual 按 的/们/长度细分；余 desc）；退役 `_RUBRIC.md` 产出。
- `merge`：召回闸由「缺 p2」迁到「缺适用 lens」——按各 chunk 的 kind 推 `required = {T,G} ∪ {N if name} ∪ {A,R if desc}`，缺即 `verdict_allowed=false` + 横幅 + `recall_status.json`。
- `report`：汇总页降级戳改读 `verdict_allowed`。
- 仍负责 prep/chunks/report/view；派发（按 lens×kind 门控、≤5–6 并发波次、断点优先、存活只认落盘）由编排层执行。

回归：`scripts/run_tests.py` 59/59 绿；`validate-lenses` 对 T/A/G/R-only（无 N）夹具 exit 0（句子流未破）。

注：`mastertb_prep.py` 仍负责 prep（clean_input/context/consistency/missing）、chunks（context-rich + kind）、report、view；只是 judge 从单规则改为 lens、merge 改走 merge-lenses。

## 删除项

- 第二遍 p2：不再派、不再产 `chunk_NN.p2.json`、merge 不再取并集。
- 单合并 `_RUBRIC.md`（被 5 个 lens 文件取代）。

## 成本

门控后 agent 数 ≈ `15×2`(T,G 全块) + `name 块数 ×1`(N) + `desc 块数 ×2`(A,R)，约 50–60 个窄 agent（旧双遍 30 个宽 agent）。每 agent 只报一类、更窄更省 token。须配并发波次闸，否则重蹈限流。

## 验证：lens ↔ 0626 实漏

| 漏项(本轮单遍漏、0624 标了) | 归属 lens |
|---|---|
| 艾普鲁→Applewood(人名安成地名)、Wilkes→Vespera、Trinity→Trista | N |
| 疑惑的男人→「可疑」(反义)、爱好者→收集者、漏译「大」 | A |
| 音碟吼→「动物」占位、同源异译、金牌向导/信使未统一 | T |
| 喵呜缺 ห、ลดคความ 多字符 | G |
| 黑巫师/黑衣人不地道、超耐力→粗俗 | R |

5 个 lens 各自盯死一类，结构上不再有"一个 agent 顾此失彼"的缝。
