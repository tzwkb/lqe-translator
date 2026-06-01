# 主观质量权重与精细化优化实现计划

## 目标

补齐两个需求：

1. 显著提升主观判断因素权重：地道性、流畅度、译文贴合度、风格自然度。
2. 在基准译文之上做精细化调整：先保证硬规则和历史译文边界，再优化非锁定句段的表达质量。

---

## 需求 1：提升主观判断因素权重

### 当前状态

当前 LQE 权重是标准模式：

| Category | 当前权重 |
|---|---:|
| Mistranslation | 1.5 |
| Omission | 1.5 |
| Addition | 1.5 |
| Grammar | 1.5 |
| Company style | 1.5 |
| Unidiomatic | 1.5 |
| Culture specific reference | 1.5 |
| Terminology | 1.5 |

主观质量相关项没有被额外突出。

### 实现方案

不要直接覆盖现有标准权重，而是新增 **weight profile**。

```text
standard        = 当前 LQE 标准
strict-polish   = 主观质量增强模式
```

新增到 `lqe_engine.py`：

```python
WEIGHT_PROFILES = {
    "standard": WEIGHTS,
    "strict-polish": {
        **WEIGHTS,
        "Unidiomatic": 2.0,
        "Company style": 2.0,
        "Grammar": 2.0,
        "Mistranslation": 2.0,
        "Culture specific reference": 2.0,
    },
}
```

`lqe_calc.py` 增加参数：

```bash
--profile standard|strict-polish
```

计分时：

```python
weights = get_weights(args.profile)
```

`lqe_io.py write/apply-fixes` 也记录 profile：

```json
{
  "score_profile": "strict-polish"
}
```

LQE 报告中显示：

| 字段 | 示例 |
|---|---|
| Score profile | strict-polish |
| Threshold | 98 |

### 推荐权重

| Category | standard | strict-polish | 原因 |
|---|---:|---:|---|
| Unidiomatic | 1.5 | 2.0 | 地道性核心指标 |
| Company style | 1.5 | 2.0 | 风格一致性核心指标 |
| Grammar | 1.5 | 2.0 | 流畅度基础 |
| Mistranslation | 1.5 | 2.0 | 译文贴合度核心 |
| Culture specific reference | 1.5 | 2.0 | 游戏本地化关键 |
| Terminology | 1.5 | 1.5 | 已有 Major 强制，不再叠加 |
| Markup | 1.5 | 1.5 | 硬规则，不属于主观优化 |

---

## 需求 2：基准线之上的精细化调整

### 当前状态

当前流程是错误驱动：

```text
发现错误 → corrected → apply-fixes → 复评
```

不足：

- 没有明确区分硬错误、语义错误、润色建议。
- 已达 PASS 的译文不会进入精细化优化。
- 地道性/流畅度检查依赖 Agent 自觉。

### 实现方案

把评估拆成 3 层。

```text
Layer 0: Protection
  - RAG 100% match / exact TM / locked segment
  - 不修改

Layer 1: Hard QA
  - Terminology
  - Markup
  - Untranslated
  - Length
  - Punctuation / Locale convention
  - 必须修

Layer 2: Polish QA
  - Unidiomatic
  - Company style
  - Grammar
  - Mistranslation nuance
  - Culture specific reference
  - 重点优化
```

### Agent 执行规则

新增到 `SKILL.md`：

```md
## Strict Polish Mode

After hard QA, evaluate every non-locked segment for:
1. naturalness / idiomatic English
2. fluency and readability
3. source-target fit
4. game UI tone consistency
5. style-guide compliance

If a translation is acceptable but can be materially improved, mark it as:
- Unidiomatic [Minor]
- Company style [Minor]
- Grammar [Minor]
- Mistranslation [Minor] if source-target nuance is off

Do not polish RAG/TM 100% locked segments.
```

### 错误记录方式

增加区分字段（可选）：

```json
{
  "category": "Unidiomatic",
  "severity": "Minor",
  "stage": "polish",
  "comment": "Naturalness issue..."
}
```

短期可以不改 JSON schema，只在 comment 中写：

```text
[Polish] Expression is understandable but not idiomatic.
```

### LQE 报告显示

建议增加/复用：

| 字段 | 含义 |
|---|---|
| Error category | 原分类 |
| Error sub-category | 原分类 |
| Iteration | 轮次 |
| Fixed | 是否已修正 |
| Comment | 标注 `[Hard QA]` 或 `[Polish]` |

---

## 推荐实施顺序

### Phase 1：只改 SKILL.md

内容：

- 加 `Strict Polish Mode`
- 加三层评估顺序
- 明确 non-locked segment 必须做主观质量检查

优点：

- 立即生效
- 不影响脚本
- 不影响旧报告

### Phase 2：加 score profile

改动：

- `lqe_engine.py`：新增 `WEIGHT_PROFILES`
- `lqe_calc.py`：新增 `--profile`
- `lqe_io.py`：报告显示 profile
- `SKILL.md`：默认 strict-polish

优点：

- 主观质量项在分数上真实加权
- 可保留 standard 兼容模式

### Phase 3：报告结构增强

改动：

- LQA Scorecard 增加 `Score profile`
- Error Detail 中 comment 统一加 `[Hard QA]` / `[Polish]`
- 可选增加 `QA Layer` 列

优点：

- 客户/PM 能看出哪些是硬错误，哪些是精细化优化

---

## 不建议做的事

- 不建议把所有主观优化都自动化成脚本规则。
- 不建议让脚本自动判断“地道性”。
- 不建议直接修改原标准权重，避免历史报告不可比。
- 不建议对 locked segment 做润色。

---

## 验收标准

1. Agent 每轮评估时明确区分 Protection / Hard QA / Polish QA。
2. 非 locked segment 即使硬错误为 0，也会检查地道性、流畅度、贴合度。
3. `strict-polish` 模式下，主观质量类错误权重高于标准模式。
4. 报告中能看出 score profile。
5. RAG/TM 100% locked segment 不参与 polish。
6. 最终 `*_corrected.xlsx` 只修改非 locked 且确有优化必要的句段。

---

## 推荐结论

这两个需求应分开实现：

- “主观因素权重提升”用 `score profile` 工程化。
- “基准线之上的精细化调整”用 Agent 评估流程和 `SKILL.md` 规则工程化。

这样既能保持 LQE 标准模式可复用，又能为高质量本地化交付提供严格优化模式。
