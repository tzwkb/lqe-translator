# 术语库多义（一对多）映射设计

## 背景

0630 Master TB 导入（ROCO nrc/th）发现：里奥/伊贝儿/裘卡/黄蜂后/呱呱 在「物种 Species」与「个体/NPC」两个分类下被故意给出不同泰语译法；克制在动词/名词两种词性下译法不同（这两行 Category 字段相同，区分靠 Definition 文本）。0629 版两个分类译法一致，无冲突；0630 起故意拆开，说明客户已经在用「同一中文词、不同语境不同译法」这种真实存在的多义关系。

现有 `terms_*.json` 是扁平列表，每条 `{source,target}`；全链路（`mastertb_to_terms.py` 转换、`lqe_checks.py`/`lqe_chunk.py`/`lqe_io.py` 的匹配逻辑）都隐含「一个 source 只有一个 target」，多份代码各自用 `{t["source"]:t for t in terms}` 之类的写法坍缩重复 source，行为是「按行序取一个、静默丢弃其余」。0630 这次坍缩会把 5/6 词条的译法错误翻转（取到物种译法覆盖掉正在用的个体译法），当场用 `--override` 手动压平止血，未解决根因。

## 目标 / 非目标

**目标**：terms.json 原生支持「一个 source 对应多个 target（按语境区分）」，全链路消费点正确处理，不再有静默坍缩。

**非目标**：
- 多对一（多个 source 收敛同一 target）——现有扁平结构已经天然支持（不同 source 各自一行，从不冲突），且目前项目里没有具体案例，本轮不动
- pre-check 自动判断某段该用哪个语义——job 的 Excel 通常只有原文/译文两列，没有 Category 之类的语境字段，硬猜是新的误判来源；语境判断留给读得懂上下文的 AI 评估层
- 反向查询（给 target 找 source）——没有具体需求，不做

## 数据结构

```json
{"source": "马尔文", "target": "มาร์วิน", "status": "New"}
```
单义词条不变，占绝大多数（当前 terms_th.json 4314 条里仅 6 条涉及多义）。

```json
{"source": "里奥", "senses": [
  {"target": "ลีโอ", "category": "Creature Individual", "status": "New"},
  {"target": "ไลเอล", "category": "Creature Species", "status": "New"}
]}
{"source": "克制", "senses": [
  {"target": "ชนะทาง", "category": "Jini Combat System",
   "definition": "动词版本的克制，不应直接用于组合术语或关键词，仅用于句子中表达克制关系"},
  {"target": "ข่ม", "category": "Jini Combat System",
   "definition": "名词版本的克制，不应直接用于表达克制关系的句子中，可作单独出现的关键词"}
]}
```
多义词条改用 `senses` 数组，每项可选 `status`/`locked`/`category`/`definition`，缺省即省略。`category` 和 `definition` 都只是「消歧提示」，不参与匹配判定（判定见下）。

顶层 `source` 保证全局唯一——这是本设计要建立的不变量，取代"重复 source 到底是故意还是手滑"这种要靠人脑补的歧义状态。

## 共用读取层（`lqe_engine.py` 新增）

```python
def term_senses(entry: dict) -> list[dict]:
    """把单义/多义两种形状统一拍平成候选列表，每项含 target 及可选 status/locked/category/definition。
    是所有脚本读取术语候选的唯一入口，不允许绕过它直接读 entry["target"]。"""
    if "senses" in entry:
        return entry["senses"]
    return [{k: entry[k] for k in ("target", "status", "locked", "category", "definition") if k in entry}]


def group_terms(terms: list[dict]) -> dict[str, list[dict]]:
    """source -> 候选列表，供匹配逻辑直接使用。"""
    out: dict[str, list[dict]] = {}
    for t in terms:
        src = (t.get("source") or "").strip()
        if src:
            out.setdefault(src, []).extend(term_senses(t))
    return out
```

## 消费端改动

**`lqe_checks.py`**（`run_pre_check`）
- `term_map` 改用 `group_terms(terms)`，值从 4 元 tuple 改成候选列表
- 命中判定：`matched = next((s for s in senses if s["target"].strip().lower() in tgt_lower), None)`；命中任一候选即视为正确
- 未命中时报错列出全部候选：`"'里奥' → expected 'ลีโอ'(Creature Individual) or 'ไลเอล'(Creature Species)"`
- `locked` 语义调整为「候选全部 locked 才整体视为 locked」（只锁其中一个候选不构成强制指定用哪个）
- 复合术语「覆盖」判定（跳过被更长词条包含的子词）：改成检查 `other` 的任一候选是否已在 `tgt_lower` 中
- N8 大小写豁免表 `term_tokens`：遍历改成对每个 source 的每个候选取 `target`

**`lqe_chunk.py`**（`cmd_split` / `_term_hits`）
- `titems` 从 `(source,target,status)` 三元组改成 `(source, senses)`，`_term_hits` 返回结构里 `th` 字段从单一字符串改成候选列表（含 category/definition），写进 chunk 文件供 subagent 读取

**`lqe_io.py`**（`cmd_lookup_terms`）
- 同样改用 `group_terms`；命中展示多义词条时列出全部候选

**`mastertb_prep.py`**（Master TB 自审工具）不改。它的 `inc_src`（同 source 多 target）本来就是"发现潜在多义/数据问题"的审计产出，跟 terms.json 该不该原生支持多义是两件事，继续按现状跑。

## AI 侧改动（消歧提示怎么喂给 AI）

pre-check 只做「命中候选之一即通过」，真正判断某段该用哪个语义、揪出「用错语义」这种更细的 Terminology 错误，靠 AI 读段落上下文——前提是 AI 能看到全部候选和消歧线索。三处格式需要同步改：

- **SKILL.md「术语注入」**：多义词条渲染成 `里奥 → ลีโอ(Creature Individual) | ไลเอล(Creature Species)`，补一句「多候选时结合段落语境判断该用哪个，译文都不匹配才报 Terminology」
- **`docs/lenses/T.md`**（大文件多 agent 分块路径的 Terminology lens 规范）：同步上面这条判断规则
- **`docs/EVAL_SPEC.md`**（小文件单 agent 路径模板）：第 16 行「整词命中 term_hits 即对」同步改成多候选判断规则

## `mastertb_to_terms.py` 改动

- 去重键从 `source` 改成 `(source, target)`：同一 source 下不同 target 不再触发「留第一个丢其余」，全部保留
- 新增/沿用的 `category`/`definition` best-effort 列检测：某 source 最终有 >1 个不同 target 时，才把每个候选的 category/definition 一并写入；只有 1 个 target 时保持 singleton 形状，不带 category/definition（避免给 4308 条单义词条塞无用字段）
- 输出决策：分组后每个 source 若剩 1 个 target → 输出 `{"source","target",...}`；若剩 >1 个 → 输出 `{"source","senses":[...]}`
- **撤销 `--override`**：它存在的唯一理由是"schema 装不下多义、只能强制收敛成一个"，这次 senses 数组已经能装下多义，`--override` 的合理用途随之消失；若未来客户真决定两个语义不再区分，正确做法是改 Master TB 本身（上游权威源），不是在转换脚本里加暗补丁
- `<out>.conflicts.json` 侧输出（自动派生路径，非 CLI flag，原「同源不同译冲突」告警）保留但改名换含义：无条件输出本次导入「新出现/消失的多义分组」清单，纯提示给人核对是不是真的有意为之，不再是「未解决冲突需要人工介入」的强提示，不影响转换结果

## 迁移现有数据（nrc/th）

1. 删除 `projects/nrc/th/overrides_th.json`（临时方案，不再需要）
2. 用改造后的 `mastertb_to_terms.py` 重新跑一遍 0630 导入（`--backfill` 仍用 `terms_th_pre0630.bak.json`，去掉 `--override`）
3. 验证：里奥/伊贝儿/裘卡/黄蜂后/呱呱/克制 六条在新 `terms_th.json` 里变成 `senses` 形状，且两个语义都在（例如里奥同时有 `ลีโอ` 和 `ไลเอล`，克制同时有 `ชนะทาง` 和 `ข่ม`）
4. `adjudications.md` 里 2026-06-30 那条相应更新——不再是"保留个体译法、物种译法暂时丢失"，而是"两个语义都收进 TB，靠 AI 结合语境判断"

## 测试（`run_tests.py`）

新增一组用例：TB 含一条多义词条（两个候选 target），三个段落——分别用候选 A、候选 B、两者都不用——跑 `lqe_io.py pre-check`：
- 用候选 A 的段落：无 Terminology 报错
- 用候选 B 的段落：无 Terminology 报错
- 两者都不用的段落：报 Terminology，comment 里能同时看到两个候选

再加一条 singleton 词条的既有用例保持不变，确认单义路径零回归。

## 影响范围说明

`lqe_checks.py`/`lqe_chunk.py`/`lqe_io.py` 是 nrc/th、nrc/en、wwm/en 共用脚本，但改动是纯粹的能力扩展：当 source 只有一个候选时，`group_terms`/匹配逻辑的行为和现在完全一致。nrc/en、wwm/en 目前没有任何多义词条，这次改动对它们零行为变化。

## 开发/同步流程

本仓（Langlobal/lqe-translator，GitHub tzwkb/lqe-translator）是开发源；`~/.claude/skills/lqe-translator` 是运行副本。改动在本仓完成、验证后，把改动到的脚本/docs 同步过去（`projects/` 各自独立、彼此不通过 git 同步，两边都是本地实际数据）。
