# RAG 100% Match Protection 实现计划

## 目标

当上游翻译工作流产出的译文来自历史记忆库/RAG 100% 匹配时，LQE Agent 不修改该句段译文，只做保护性记录。

核心原则：

- RAG 检索与 100% match 判定由上游 AIPE 翻译 pipeline 完成。
- LQE Agent 不接入 Qdrant，不启动 Docker，不实现 RAG 检索。
- LQE Agent 只读取上游输出中的 RAG/TM/memory match 信息，并在评估时保护对应句段。

---

## 背景

当前 AIPE 上游 RAG 库位于：

```text
/Users/spellbook/Desktop/Langlobal/AIPEMVP_0526/aipe
```

其 RAG 后端使用 Qdrant：

```yaml
qdrant:
  image: qdrant/qdrant:latest
  ports:
    - "6333:6333"
```

因此如果在 LQE Agent 中直接复用 RAG 检索，会引入：

- Docker/Qdrant 依赖
- 上游 RAG 数据结构耦合
- 重复检索逻辑
- 更高维护成本

所以本需求不在 LQE 中新增 RAG 模块。

---

## 推荐架构

```text
AIPE 翻译 pipeline
  ↓
调用 RAG / TM / memory 检索
  ↓
若 source 100% exact match：在输出文件中写入 match 标记
  ↓
LQE Agent 读取输出文件
  ↓
Agent 自行识别 RAG 100% match 列和值
  ↓
对应 segment locked，不修改译文
  ↓
只优化非 locked segment
```

职责分工：

| 模块 | 职责 |
|---|---|
| AIPE / 上游 pipeline | RAG 检索、match score、exact match 判定、输出标记 |
| LQE Agent | 读取列名和值、识别 locked segment、跳过修正、输出报告 |
| LQE 脚本 | 保持通用 I/O、计分、导出能力，不接入 RAG |

---

## 上游输出建议

不强制字段名，但建议上游尽量输出以下字段，便于识别：

| 字段 | 示例 | 说明 |
|---|---|---|
| `rag_locked` | `true` | 是否锁定 |
| `rag_score` | `1.0` / `100%` | RAG 匹配度 |
| `rag_match_type` | `exact` | 匹配类型 |
| `rag_source` | 原文 | 命中的历史源文 |
| `rag_target` | 历史译文 | 命中的历史译文 |

但 LQE Agent 不依赖固定列头，会通过列名和样例值自行判断。

---

## LQE Agent 行为规则

新增到 `SKILL.md` 的规则：

```md
## RAG 100% Match Protection

Before evaluating a file, inspect input headers and sample values for columns related to RAG/TM/memory match status.

Potential signals include:
- header contains: RAG, TM, memory, match, score, exact, locked, 100%
- value contains: 100%, 1.0, exact, locked, true, yes

If a segment is clearly marked as RAG/TM/memory 100% match:
- Do not modify its target translation.
- Do not provide corrected text.
- Do not apply fixes to this segment.
- Preserve the original target in final export.
- If a potential issue is noticed, record it as a protected note, not an actionable correction.
```

---

## Agent 执行流程

### Step 1：读取输入文件结构

Agent 先查看：

- 表头/自动列名
- 前 10-20 行样例值
- 是否存在 RAG/TM/memory/match/score/locked 相关字段

### Step 2：识别 locked segment

Agent 根据字段语义和值判断：

```text
rag_score = 1 / 1.0 / 100 / 100% → locked
rag_match_type = exact / 100% / perfect → locked
rag_locked = true / yes / 1 / locked → locked
```

若列名不明确，Agent 必须在报告中说明识别依据。

### Step 3：LQE 评估

对 locked segment：

- 不输出 `corrected`
- 不纳入 apply-fixes 修正
- 不改 final/export 译文

对非 locked segment：

- 正常执行 pre-check
- 正常执行语义/风格/地道性判断
- 正常给 corrected

### Step 4：报告显示

LQE 报告中建议加入人工可读标记：

| 字段 | 含义 |
|---|---|
| `RAG Protected` | Yes/No |
| `RAG Evidence` | 识别依据，如 `rag_score=100%` |

短期内可先不改脚本，只在 LQE Report 的 error comment 或 review note 中说明。

---

## 不做的事情

明确不做：

- 不在 LQE Agent 中连接 Qdrant
- 不在 LQE Agent 中加载 AIPE RAG 数据库
- 不在 LQE Agent 中实现 embedding/fuzzy search
- 不要求安装 Docker 才能跑 LQE
- 不把 RAG match 判断写死到某个固定列名

---

## 分阶段实施

### Phase 1：文档和 Agent 规则

改动：

- 更新 `SKILL.md`
- 要求 Agent 在每次 LQE 前检查 RAG/TM/memory match 字段
- locked segment 不提供 corrected

产出：

- 不改脚本
- 不影响现有 LQE 流程
- 立即可用

### Phase 2：报告可视化

可选改动：

- 在 LQE Results sheet 增加：
  - `RAG Protected`
  - `RAG Evidence`

产出：

- 报告更清楚
- 仍不接入 RAG 后端

### Phase 3：上游 AIPE 配合

建议小罗学长在翻译 pipeline 输出中增加 match 标记：

- `rag_locked`
- `rag_score`
- `rag_match_type`
- `rag_target`

产出：

- LQE Agent 更容易稳定识别
- 上游 RAG 能力复用，不重复建设

---

## 验收标准

1. 输入文件含 RAG 100% match 标记时，Agent 能识别 locked segment。
2. locked segment 即使存在可优化表达，也不输出 corrected。
3. `apply-fixes` 后 locked segment 译文保持原样。
4. `*_corrected.xlsx` 中 locked segment target 与输入 target 一致。
5. LQE 报告中能说明该 segment 被 RAG 100% match 保护。
6. 不需要 Docker/Qdrant 即可完成 LQE。

---

## 推荐结论

本需求应作为 **Agent 规则 + 上游标记协作** 实现，而不是在 LQE Agent 中增加 RAG 模块。

原因：

- 上游已经拥有完整 RAG 检索上下文。
- LQE 只需要知道“是否 100% match”。
- 这样能避免 Qdrant/Docker 依赖进入 LQE。
- 模块职责清晰，维护成本最低。
