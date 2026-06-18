# RAG / TM 接入设计（LQE Translator）

> 状态：草案 v0.1（2026-06-18）｜待确认「宗旨」与文末开放问题后定稿
> 读者：开发／维护本 skill 的人

## 0. 宗旨（请确认 — 全文的锚）

待质检文件**没有 match 列**，而 LQE 既有的「RAG 100% match 保护」（SKILL.md Step 1.2）本要靠输入文件自带的 match 列才能跑。本功能就是**用项目 TM（`.sdltm`）在本地把"每段是否命中既有译法"算出来，补上那条缺失信息**，不依赖 AIPE。

由此质检能：
1. **认出已审定/既有译法的段 → 保护**：不重判、不改写。避免假错、避免越权改动已定稿内容，把人力聚焦真正要审的新译；
2. 把权威译法当**参照**喂 AI，让判断与改译贴着项目先例，而非凭空另造。

**主线 = protect（保护）。** enforce（命中但译不符就判错）列为**可选 Phase 2，默认关**，待宗旨确认再定。

## 1. 范围

**做（Phase 1 / MVP）**
- `.sdltm` → 本地索引（源→译，附库与可信层标记）
- 输入段按**源精确匹配**查索引
- 命中且**译文也一致** → 锁定（接现有 `--locked-file`，标 `RAG_100_MATCH`）
- 命中的**库译文作为参照证据**输出，供 Step 2 评估参考

**默认不做 / 关**
- 模糊匹配（fuzzy）——1:n 仅 0.1%，精确匹配已足够（见 §4.2）
- enforce 强制判错（Phase 2，§4.5）
- 修正回流 TM（AIPE `ingest-corpus` 的反向，与本功能无关）
- AIPE 依赖

## 2. 输入：TM 库与可信度分层

| 库 | 条数 | 角色 | 状态 |
|---|---|---|---|
| CQA | 16,750 | 权威：protect（+ 可选 enforce） | ✅ 已定 |
| Designer | 20,766 | 权威：protect（+ 可选 enforce） | ✅ 已定 |
| GT | 264,324 | 待定（疑泛翻/机翻 → 倾向 hint 或弃用） | ❓ 开放#1 |
| LQA | 9,734 | 待定（疑 LQA 审定 → 可 protect） | ❓ 开放#1 |
| ST | 12,044 | 待定 | ❓ 开放#1 |

**安全红线**：protect / enforce **只能用可信库**。拿机翻/泛翻大库锁定 = 替错译护短、反而查不出，违背宗旨。低可信库最多当 hint。

语言对：`zh-CN → en-US`（与 wwm/en 档案 `ZHCN-EN` 一致）。

**源文件易失**：5 个 `.sdltm` 现在企业微信缓存目录（`…/Caches/…`），随时可能被清。**build 前必须先拷到项目目录固化**（§5）。

## 3. 架构与数据流

三段式，build 一次、match 每 job：

```
[一次性] CQA/Designer.sdltm ──build──▶ rag_index.json   (projects/wwm/common/rag/)
                                          │
[每 job]  jobs/<n>/state.json ──rag-match─┼──▶ rag_locked.json   ─▶ apply-fixes --locked-file（现成）
                                          ├──▶ rag_evidence.json  ─▶ Step 2 AI 评估参照
                                          └──(Phase2 可选)──▶ 注入 errors.json（enforce）
```

**方案选型（match 步放哪）**
- **A（推荐）独立子命令 `rag-match`**：在 `read` 之后、`pre-check` 之前跑，产出 locked + evidence 两个 sidecar。优点：与现有 `--locked-file` 无缝对接，零侵入 pre-check；缺点：流程多一步。
- B 折进 `pre-check`：少一步，但把"匹配"与"确定性检查"耦合，且 pre-check 仅首轮跑、语义不符。
- C 纯独立脚本（不进 lqe_io）：最松耦合，但与 state/locked 约定重复造轮子。

→ 选 **A**：匹配是独立关注点，sidecar 干净，复用现成锁定口。

## 4. 组件

### 4.1 sdltm 提取
- `.sdltm` = SQLite；`translation_units.source_segment / target_segment` 是 XML。
- 取所有 `<Value>…</Value>` 内文按序拼接，`html.unescape`。
- 内联标签 `<Tag>`（变量/格式）：Phase 1 **忽略 Tag、只取 Value 文本**（足够做源匹配）；需更严可后续把 Tag 转占位符。

### 4.2 归一化与匹配（口径待定，给默认 — 开放#3）
- 默认 `norm(s)` = 去首尾空白 + 内部空白折叠为单空格 + Unicode NFC。
- **源**：`norm(source)` 作匹配键。
- **译**：锁定判定 = `norm(input_target) == norm(tm_target)`。
- **精确匹配**：CQA+Designer 合并 37,273 distinct 源中仅 26（0.1%）一源多译；按**可接受变体集**处理——`norm(input_target)` ∈ 该源任一库译文即视为一致。
- 注：折叠空白意味着仅空白/换行差异也判一致而锁定——对"保护"可接受；若要连 `\n` 数卡死可调严（取舍见开放#3）。

### 4.3 索引格式
- `rag_index.json`：`{ "<src_norm>": {"targets": ["<tgt_norm>", …], "tier": "authoritative", "libs": ["CQA","Designer"]}, … }`
- 仅权威库 ~37k 键，JSON 够。若纳入 GT(264k) 改 SQLite（开放#4）。

### 4.4 匹配步 `rag-match`
对 `state.json` 每段：
1. `key = norm(source)`，查索引。
2. 未命中 → 跳过（无副作用）。
3. 命中且 `norm(target)` ∈ targets → **lock**：写入 `rag_locked.json`。
4. 命中但译不符 →
   - Phase 1：写 `rag_evidence.json`（`{id, source, tm_target, libs}`）作参照，**不判错**。
   - Phase 2（可选 enforce）：另注入 `errors.json`（见 §4.5）。

### 4.5 接入 LQE 既有流程
- **锁定**：`rag_locked.json` = `{"locked_ids":[…]}`，直接喂 `apply-fixes --locked-file`（`_locked_ids()` 已支持）。/loop Step 1.2 由「猜输入列」改为「读 `rag-match` 结果」。
- **参照**：Step 2 评估把该段 `rag_evidence` 注入上下文（"项目权威库此句译为 X，仅供参照"）。
- **enforce（Phase 2，默认关）**：命中且译不符 → 生成 `{category, severity, comment, corrected: tm_target}` 注入 `errors.json`。归类/严重度 = 开放#2。

## 5. 文件布局与配置
```
projects/wwm/
├── common/rag/
│   ├── sources/              # 从企微缓存拷出的 .sdltm（固化、可入私有仓）
│   │   ├── CQA库0605.sdltm
│   │   └── Designer库0605.sdltm
│   └── rag_index.json        # build 产物
└── en/profile.json           # 增 rag 配置块
```
profile.json 新增：
```json
"rag": {
  "libraries": [
    {"file": "../common/rag/sources/CQA库0605.sdltm", "tier": "authoritative"},
    {"file": "../common/rag/sources/Designer库0605.sdltm", "tier": "authoritative"}
  ],
  "index": "../common/rag/rag_index.json",
  "match": {"mode": "exact", "enforce": false}
}
```
job 内产物：`jobs/<n>/rag_locked.json`、`jobs/<n>/rag_evidence.json`。

## 6. 命令行与流程改动
- 新 `rag_index.py build --libraries <a.sdltm> <b.sdltm> --tier authoritative --out rag_index.json`。
- 新 `lqe_io.py rag-match --state state.json --index rag_index.json --out-locked rag_locked.json --out-evidence rag_evidence.json [--enforce]`。
- SKILL.md：
  - 首次启动加「（项目带 rag 配置时）build 索引」一次性步骤。
  - Step 1.2 改写：从「读输入 match 列」→「读 `rag-match` 产出的 locked/evidence」（输入自带 match 列时仍兼容）。

## 7. 错误处理与边界
- 索引缺失/路径错 → 明确报错并指引先 build。
- sdltm 解析失败/无 `<Value>` → 跳过该 unit + 计数告警。
- 企微缓存源易失 → build 前强制拷出；source 不存在则 fail-fast。
- 1:n 变体 → 见 §4.2。
- 无命中段 → 原样走正常评估。
- GT 体量大 → 默认不纳入；若纳入走 SQLite + 流式。

## 8. 数据模型
- `rag_locked.json`：`{"locked_ids": [int,…]}`（兼容 `_locked_ids`）。
- `rag_evidence.json`：`[{"id":int,"source":str,"tm_target":str,"libs":[str]}]`。
- state 段（apply-fixes 已写）：命中锁定后 `locked:true, lock_reason:"RAG_100_MATCH"`。

## 9. 测试
- 单元：Value 提取（多 Value/含 Tag/实体转义）、`norm`、精确匹配、1:n 变体集、lock 判定、enforce 注入格式。
- 集成：构造极小 fixture `.sdltm`（几条）+ 小输入 → build→rag-match→apply-fixes，断言 locked/evidence 正确、locked 段不被改。
- 回归：纳入 `scripts/run_tests.py`。

## 10. 开放问题（标注是否阻塞）
1. **[阻塞分层] GT/LQA/ST 各是什么、进哪层**（authoritative/protect/hint/discard）。
2. **[阻塞 Phase 2] enforce 是否做**；若做，命中译不符归 `Inconsistency` 还是 `Terminology`、何严重度（建议 Inconsistency/Major，因是"与权威译法不一致"，非术语级）。
3. **[非阻塞] 归一化激进度**：是否连 `\n`/标签/大小写都卡（默认折叠空白、忽略 Tag）。
4. **[非阻塞] 索引格式**：JSON（仅权威库）vs SQLite（含 GT）。

## 附：与 AIPE 的对应
AIPE 路线里参照语料来自 AIPE 服务（`from-aipe` 拉术语/SG；`ingest-corpus` 是把修正**回流** AIPE，方向相反）。本功能把"权威语料库做参照/保护"搬到**本地、以 `.sdltm` 为源**实现，逻辑同构、去掉 AIPE 依赖。
