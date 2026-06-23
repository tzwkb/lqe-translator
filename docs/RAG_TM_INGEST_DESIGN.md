# RAG / TM 接入设计（LQE Translator）

> 状态：草案 v0.2（精简版，砍掉过度设计）

## 0. 目的

待质检文件**没有 match 列**，而 LQE 的「100% match 保护」（SKILL.md Step 1.2）本要靠这列。本功能用项目 TM（`.sdltm`）在本地算出哪些段是 100% 匹配，补上这信息，**锁定保护已审定的既有译法**（不重判、不改）。不依赖 AIPE。

就是把 skill 现成的 Step 1.2 保护机制，喂料从"读输入文件的列"换成"本地查 TM"。

## 1. 范围

**做**
- `.sdltm` → 本地"源→译"索引（来自 **CQA + Designer** 权威库）
- 待质检每段：**源精确命中 且 译文=库译 → 锁定**（接现有 `--locked-file`）
- 解析层留薄接口：一个格式一个解析函数、按扩展名挑；本期只实现 `.sdltm`

**不做**
- 模糊匹配（精确足够，1:n 仅 0.1%）
- 其他 TM 格式（`.tmx`/`.xlsx`/csv）——**留接口、不实现**
- 强制判错、参照注入、库信任分层——**不在目的内**
- AIPE 依赖；embedding / 外部 API（**全本地，源文不出本机**）

## 2. 句段两态

| 状态 | 条件 | 处理 |
|---|---|---|
| **命中** | 源精确命中 **且** `norm(译) ∈ 库译`（含 0.1% 一源多译的变体集） | **锁定（RAG protected）**：跳过打分、不改、原样保留 |
| **其余** | 未命中，或源命中但译被改过 | 正常质检（TM 零影响） |

锁定为何要"源+译都对上"：这是**质检场景，译文可能被译员改过**；只凭源命中就锁，会把被改坏的译文也保护掉、漏审。

## 3. 数据流

```
[一次性] CQA/Designer.sdltm ──build──▶ rag_index.json   (projects/wwm/common/rag/)
[每 job]  jobs/<n>/state.json ──rag-match──▶ rag_locked.json ──▶ apply-fixes --locked-file（现成）
```

## 4. 组件

### 4.1 解析（格式可插拔，薄）
- 一个格式一个 loader 函数：`iter_units(path) -> (源文本, 译文本)`；按扩展名挑，`--format` 可覆盖。**加格式 = 加一个函数 + 注册一行**，不动 index/match。
- `SdltmLoader`（本期）：SQLite 读 `translation_units.source_segment / target_segment`（XML）→ 取所有 `<Value>` 文本拼接、`html.unescape`、忽略 `<Tag>`。
- 其他（`.tmx`/`.xlsx`/csv）：**预留、不实现**。xlsx/csv 非自描述、需列映射，可复用现有 `_pick_col` 自动认列。

### 4.2 归一化 + 匹配
- `norm(s)` = 去首尾空白 + 内部空白折叠为单空格 + Unicode NFC。
- 索引键 = `norm(源)`；值 = 该源的 `norm(译)` **集合**（CQA+Designer 合并仅 0.1% 一源多译 → 当变体集，`norm(段.译) ∈ 集合` 即视为对上）。
- **全本地、零 API、零 embedding**——精确字符串等值，不是向量检索。

### 4.3 build & rag-match
- `rag_index.py build --libraries CQA.sdltm Designer.sdltm --out rag_index.json`（按扩展名选 loader）。
- `rag_index.py rag-match --state state.json --index rag_index.json --out-locked rag_locked.json`：每段 `norm(源)` 查索引，命中且 `norm(译) ∈ 集合` → 写入 `locked_ids`。
- 跑位：`read` 之后、`pre-check` 之前。

### 4.4 接入 LQE
- `rag_locked.json` = `{"locked_ids":[…]}`，直接喂 `apply-fixes --locked-file`（`_locked_ids()` 已支持）。
- /loop **Step 1.2**：由"猜输入列"改为"读 `rag_locked.json`"（输入自带 match 列时仍兼容）。
- 锁定段：`apply-fixes` 标 `locked / RAG_100_MATCH`，成品标 `RAG Protected`（均现成）。

## 5. 文件布局与配置
```
projects/wwm/
├── common/rag/sources/      # 从企微缓存拷出的 .sdltm（固化、可入私有仓）
│   ├── CQA库0605.sdltm
│   └── Designer库0605.sdltm
├── common/rag/rag_index.json
└── en/profile.json          # 增 rag 配置
```
profile.json 新增（极简——全是权威库，无需 per-库配置）：
```json
"rag": {
  "libraries": [
    "../common/rag/sources/CQA库0605.sdltm",
    "../common/rag/sources/Designer库0605.sdltm"
  ],
  "index": "../common/rag/rag_index.json"
}
```
（将来若加非自描述格式，条目可升级为带 `format`/列映射的对象。）
job 产物：`jobs/<n>/rag_locked.json`。

## 6. 命令与流程改动
- 新脚本 `rag_index.py`，含子命令 `build` 与 `rag-match`（lqe_io.py 不改动）。
- SKILL.md：首次启动加「（项目带 rag 配置时）build 索引一次」；Step 1.2 改读 `rag_locked.json`。

## 7. 错误处理与边界
- 索引缺失/路径错 → 报错并指引先 build。
- `.sdltm` 缺失/解析失败 → fail-fast 或跳过该 unit + 计数告警。
- 企微缓存源易失 → build 前必须拷到项目目录固化。
- 1:n 一源多译 → 变体集（§4.2）。
- 全程本地、零外部调用。

## 8. 数据模型
- `rag_index.json`：`{ "<norm_src>": ["<norm_tgt>", …] }`。
- `rag_locked.json`：`{"locked_ids": [int, …]}`（兼容 `_locked_ids`）。
- state 段锁定后：`locked:true, lock_reason:"RAG_100_MATCH"`（apply-fixes 已写）。

## 9. 测试
- 单元：`<Value>` 提取（多 Value/含 Tag/实体转义）、`norm`、精确匹配、变体集、锁定判定。
- 集成：极小 fixture `.sdltm` + 小输入 → build→rag-match→apply-fixes，断言锁定正确、锁定段不被改。
- 纳入 `scripts/run_tests.py`。

## 附：与 AIPE 的对应
把"权威语料做 100% 保护"搬到**本地、以 `.sdltm` 为源**实现，逻辑同构、去掉 AIPE 依赖。
