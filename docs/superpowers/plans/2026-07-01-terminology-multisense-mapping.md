# 术语库多义（一对多）映射 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** terms.json 原生支持「同一 source 对应多个 target」（按 category/definition 消歧），替换掉全链路里「同 source 撞车就静默取第一个丢其余」的坍缩行为。

**Architecture:** terms.json 条目允许两种形状——`{source,target,status?}`（单义，不变）或 `{source,senses:[{target,status?,category?,definition?}, ...]}`（多义）。`lqe_engine.py` 新增 `term_senses()`/`group_terms()` 作为唯一读取入口，把两种形状拍平成统一的候选列表；三个消费脚本（`lqe_checks.py` pre-check 匹配、`lqe_chunk.py` chunk 拆分、`lqe_io.py` lookup-terms）改用该层，命中判定从"等于这一个 target"改成"命中候选列表任意一个"。`mastertb_to_terms.py` 改成按 `(source,target)` 去重、自动决定输出单义/多义形状，撤销本轮之前加的 `--override` 逃生舱。AI 侧三处文档（SKILL.md、docs/lenses/T.md、docs/EVAL_SPEC.md）同步说明多候选的消歧提示格式。

**Tech Stack:** Python 3.14, openpyxl；测试用 `scripts/run_tests.py`（自包含、subprocess 驱动真实 CLI，写临时目录，无网络依赖）。

## Global Constraints

- 开发目录：`/Users/spellbook/Desktop/Langlobal/lqe-translator`（GitHub `tzwkb/lqe-translator`，任务 1-7 全部在这里进行）。运行副本：`~/.claude/skills/lqe-translator`（任务 8 才同步过去）。两边 `projects/`/`jobs/` 各自本地、彼此不通过 git 同步。
- 每个任务改完在 Langlobal 仓库本地 commit；**不 push**（push 前必须问用户）。
- Spec：`docs/TERM_MULTISENSE_DESIGN.md`（同仓库，已提交 commit a92969b）。
- 已知但本计划不处理的仓库漂移：Langlobal 缺 `scripts/term_suggest.py`（任务 3 会补）；另外 Langlobal 还没同步 skills/ 那边已完成的 RAG→TM 改名（`rag_index.py`/`test_rag.py` vs `tm_index.py`/`tm_index_test.py`），跟本次改动无关，不在本计划范围内，任务 8 不处理这个漂移。
- 起手前 baseline：`cd /Users/spellbook/Desktop/Langlobal/lqe-translator && python3 scripts/run_tests.py` → `59/59 passed`。每个任务完成后必须重新跑这个命令，确认之前的用例连同新用例全绿，不得净减少通过数。

---

### Task 1: `lqe_engine.py` — 共用的多义读取层

**Files:**
- Modify: `scripts/lqe_engine.py:71-77`（`load_terms` 函数之后插入新函数）
- Modify: `scripts/run_tests.py:9-256`（新增测试 + 注册进主运行列表）

**Interfaces:**
- Produces: `term_senses(entry: dict) -> list[dict]`——把单义 `{source,target,status?,locked?}` 或多义 `{source,senses:[...]}` 两种形状统一拍平成候选列表，每项最多含 `target`(必有)/`status`/`locked`/`category`/`definition`。`group_terms(terms: list[dict]) -> dict[str, list[dict]]`——source → 候选列表（跨条目累加）。后续任务全部通过这两个函数读取术语，禁止再手写 `entry["target"]`。

- [ ] **Step 1: 写失败测试**

在 `scripts/run_tests.py` 里，`t7()` 函数结束之后（第 245 行 `check("T7 merge content", ...)` 那行之后、`if __name__ == "__main__":` 之前）插入：

```python

# ── T8: lqe_engine term_senses / group_terms ──────────────────────────────────
def t8():
    sys.path.insert(0, str(SCRIPTS))
    from lqe_engine import term_senses, group_terms

    singleton = {"source": "马尔文", "target": "มาร์วิน", "status": "New"}
    check("T8 singleton term_senses",
          term_senses(singleton) == [{"target": "มาร์วิน", "status": "New"}])

    multi = {"source": "里奥", "senses": [
        {"target": "ลีโอ", "category": "Creature Individual"},
        {"target": "ไลเอล", "category": "Creature Species"},
    ]}
    check("T8 multi term_senses passthrough", term_senses(multi) == multi["senses"])

    grouped = group_terms([singleton, multi])
    check("T8 group_terms keys", set(grouped.keys()) == {"马尔文", "里奥"})
    check("T8 group_terms multi count", len(grouped["里奥"]) == 2)
    check("T8 group_terms singleton count", len(grouped["马尔文"]) == 1)
```

再把文件最下面的注册行

```python
    for t in (t1, t2, t3, t4, t5, t6, t7):
```

改成

```python
    for t in (t1, t2, t3, t4, t5, t6, t7, t8):
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/spellbook/Desktop/Langlobal/lqe-translator && python3 scripts/run_tests.py`
Expected: 崩在 `ImportError: cannot import name 'term_senses' from 'lqe_engine'`（因为函数还不存在）

- [ ] **Step 3: 实现**

在 `scripts/lqe_engine.py` 里，`load_terms` 函数（第 71-77 行）之后插入：

```python


def term_senses(entry: dict) -> list[dict]:
    """把单义 {source,target,...} / 多义 {source,senses:[...]} 两种形状统一拍平
    成候选列表，每项最多含 target(必有)/status/locked/category/definition。
    是所有脚本读取术语候选译法的唯一入口——不允许绕过它直接读 entry["target"]，
    多义条目没有这个 key。"""
    if "senses" in entry:
        return entry["senses"]
    return [{k: entry[k] for k in ("target", "status", "locked", "category", "definition") if k in entry}]


def group_terms(terms: list[dict]) -> dict[str, list[dict]]:
    """source -> 候选列表（见 term_senses），跨条目累加。"""
    out: dict[str, list[dict]] = {}
    for t in terms:
        src = (t.get("source") or "").strip()
        if src:
            out.setdefault(src, []).extend(term_senses(t))
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /Users/spellbook/Desktop/Langlobal/lqe-translator && python3 scripts/run_tests.py`
Expected: `60/60 passed  — all green`（原 59 条 + T8 的新增用例；T8 内部 5 个 `check` 只占 1 次 pass/fail 计数是错的说法——实际每个 `check()` 调用各自计入 PASS/FAIL，所以总数会比 59 多 5，实际看到的数字以终端输出为准，只要 `FAILED:` 不出现即算过）

- [ ] **Step 5: Commit**

```bash
cd /Users/spellbook/Desktop/Langlobal/lqe-translator
git add scripts/lqe_engine.py scripts/run_tests.py
git commit -m "$(cat <<'EOF'
lqe_engine: 加 term_senses/group_terms 多义读取层

单义{source,target}和多义{source,senses:[...]}两种形状统一
拍平成候选列表，后续消费脚本改用它读术语，不再各自坍缩重复source。
EOF
)"
```

---

### Task 2: `lqe_checks.py` — pre-check 多义匹配

**Files:**
- Modify: `scripts/lqe_checks.py:14-17`（import）
- Modify: `scripts/lqe_checks.py:181-203`（term_map 构建 + term_tokens）
- Modify: `scripts/lqe_checks.py:302-324`（术语命中判定）
- Modify: `scripts/run_tests.py`（新增测试 + 注册）

**Interfaces:**
- Consumes: Task 1 的 `group_terms(terms) -> dict[str, list[dict]]`
- Produces: pre-check 报错时列出全部候选的格式 `"'{source}' → expected 'A'(catA) or 'B'(catB)"`，供 Task 6 的 AI 侧文档描述一致引用

- [ ] **Step 1: 写失败测试**

在 `scripts/run_tests.py` 里 T8 之后插入：

```python

# ── T9: lqe_checks pre-check 多义术语命中 ─────────────────────────────────────
def t9():
    rows = [
        ('看到一只里奥。', 'Saw a ลีโอ.'),      # 0 命中 Individual 候选 -> 不报
        ('看到一只里奥。', 'Saw a ไลเอล.'),      # 1 命中 Species 候选 -> 不报
        ('看到一只里奥。', 'Saw a Rio.'),        # 2 两个候选都不匹配 -> 报错，列出两个候选
        ('马尔文来了。', 'มาร์วิน is here.'),    # 3 单义词条回归检查
    ]
    make_xlsx(TMP / "t9.xlsx", rows)
    (TMP / "t9_tb.json").write_text(json.dumps([
        {"source": "里奥", "senses": [
            {"target": "ลีโอ", "category": "Creature Individual"},
            {"target": "ไลเอล", "category": "Creature Species"},
        ]},
        {"source": "马尔文", "target": "มาร์วิน", "status": "New"},
    ], ensure_ascii=False), encoding="utf-8")
    r = run("lqe_io.py", "read", "--input", str(TMP / "t9.xlsx"),
            "--source-col", "原文", "--target-col", "译文", "--target-lang", "th",
            "--wordcount-basis", "source-chars",
            "--terminology", str(TMP / "t9_tb.json"), "--out", str(TMP / "j9/state.json"))
    check("T9 read rc", r.returncode == 0, r.stderr[-200:])
    r = run("lqe_io.py", "pre-check", "--state", str(TMP / "j9/state.json"), "--out", str(TMP / "j9/pc.json"))
    check("T9 pre-check rc", r.returncode == 0, r.stderr[-200:])
    res = load_errs(TMP / "j9/pc.json")
    check("T9 sense A no Terminology error", not has(res, 0, "里奥"))
    check("T9 sense B no Terminology error", not has(res, 1, "里奥"))
    check("T9 neither-sense reports both candidates", has(res, 2, "ลีโอ") and has(res, 2, "ไลเอล"))
    check("T9 singleton regression unaffected", not has(res, 3, "马尔文"))
```

注册行改成：

```python
    for t in (t1, t2, t3, t4, t5, t6, t7, t8, t9):
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/spellbook/Desktop/Langlobal/lqe-translator && python3 scripts/run_tests.py`
Expected: `T9 sense B no Terminology error` 失败（现有代码只认 term_map 里存的第一个候选 `ลีโอ`，段 1 用 `ไลเอล` 会被判 Terminology 错）

- [ ] **Step 3: 实现**

`scripts/lqe_checks.py` 第 14-17 行，import 块：

旧：
```python
from lqe_engine import (
    read_json, load_terms as _load_terms,
    RE_CJK as _RE_CJK, _target_lang, _load_lang, _lang_toggle_defaults,
)
```
新：
```python
from lqe_engine import (
    read_json, load_terms as _load_terms, group_terms as _group_terms,
    RE_CJK as _RE_CJK, _target_lang, _load_lang, _lang_toggle_defaults,
)
```

在 `_RE_CASE_EXEMPT`（或任何模块级正则常量定义完、`def run_pre_check` 之前的位置——即第 181 行之前）插入一个新的模块级函数：

```python
def _fmt_sense(s: dict) -> str:
    parts = [f"'{s['target']}'"]
    if s.get("category"):
        parts.append(f"({s['category']})")
    if s.get("status"):
        parts.append(f"[TB:{s['status']}]")
    return "".join(parts)


```

`run_pre_check` 里第 185-191 行：

旧：
```python
    terms = _load_terms(state)
    term_map = {
        t["source"].strip(): (t["target"].strip(), t["target"].strip().lower(), t.get("status", ""), bool(t.get("locked")))
        for t in terms
        if t.get("source") and t.get("target")
        and len(t["source"].strip()) >= (2 if _RE_CJK.search(t["source"]) else 3)
    }
```
新：
```python
    terms = _load_terms(state)
    term_map: dict[str, list[dict]] = {}
    for src, senses in _group_terms(terms).items():
        valid = [{**s, "_target_lower": s["target"].strip().lower()}
                 for s in senses if s.get("target")]
        if valid and len(src) >= (2 if _RE_CJK.search(src) else 3):
            term_map[src] = valid
```

第 199 行（N8 豁免词表）：

旧：
```python
    term_tokens = {w for orig, *_ in term_map.values() for w in re.findall(r'[A-Za-z]+', orig)}
```
新：
```python
    term_tokens = {w for senses in term_map.values() for s in senses
                   for w in re.findall(r'[A-Za-z]+', s["target"])}
```

第 302-324 行（术语命中判定块）：

旧：
```python
        tgt_lower = tgt.lower()
        if on("terminology"):
            hit_srcs = [ts for ch in set(src) for ts in term_first.get(ch, ()) if ts in src]
            for term_src in hit_srcs:
                term_orig, term_tgt, term_status, term_locked = term_map[term_src]
                # 复合术语优先：更长词条命中且其译法已在译文中 → 跳过被包含的子词条
                covered = any(other != term_src and term_src in other
                              and term_map[other][1] in tgt_lower for other in hit_srcs)
                if covered:
                    continue
                if term_tgt not in tgt_lower:
                    note = f" [TB:{term_status}]" if term_status else ""
                    if term_locked:
                        note += " [LOCKED]"
                    errs.append({"category": "Terminology", "severity": "Major",
                                 "comment": f"'{term_src}' → expected '{term_orig}'{note}"})
                elif on("term_case"):
                    # #7: 全大写缩写词条精确大小写（PM 2026-06-12：仅查缩写、判严重）
                    for acro in re.findall(r'\b[A-Z]{2,}\b', term_orig):
                        if acro.lower() in tgt_lower and acro not in tgt:
                            errs.append({"category": "Company style", "severity": "Major",
                                         "comment": f"Acronym case: expected '{acro}' ('{term_src}' → '{term_orig}')"})
                            break
```
新：
```python
        tgt_lower = tgt.lower()
        if on("terminology"):
            hit_srcs = [ts for ch in set(src) for ts in term_first.get(ch, ()) if ts in src]
            for term_src in hit_srcs:
                senses = term_map[term_src]
                # 复合术语优先：更长词条命中且其任一候选译法已在译文中 → 跳过被包含的子词条
                covered = any(other != term_src and term_src in other
                              and any(s["_target_lower"] in tgt_lower for s in term_map[other])
                              for other in hit_srcs)
                if covered:
                    continue
                matched = next((s for s in senses if s["_target_lower"] in tgt_lower), None)
                if matched is None:
                    cands = " or ".join(_fmt_sense(s) for s in senses)
                    note = " [LOCKED]" if all(s.get("locked") for s in senses) else ""
                    errs.append({"category": "Terminology", "severity": "Major",
                                 "comment": f"'{term_src}' → expected {cands}{note}"})
                elif on("term_case"):
                    # #7: 全大写缩写词条精确大小写（PM 2026-06-12：仅查缩写、判严重）
                    for acro in re.findall(r'\b[A-Z]{2,}\b', matched["target"]):
                        if acro.lower() in tgt_lower and acro not in tgt:
                            errs.append({"category": "Company style", "severity": "Major",
                                         "comment": f"Acronym case: expected '{acro}' ('{term_src}' → '{matched['target']}')"})
                            break
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /Users/spellbook/Desktop/Langlobal/lqe-translator && python3 scripts/run_tests.py`
Expected: 全绿，无 `FAILED:`

- [ ] **Step 5: Commit**

```bash
cd /Users/spellbook/Desktop/Langlobal/lqe-translator
git add scripts/lqe_checks.py scripts/run_tests.py
git commit -m "$(cat <<'EOF'
lqe_checks: pre-check 术语匹配支持多义候选

term_map 改存候选列表(group_terms)，命中判定从"等于唯一target"
改成"命中候选任意一个"；不命中时报错列出全部候选(带category/status)，
不再只认第一个候选、静默漏判另一个合法语境。
EOF
)"
```

---

### Task 3: `lqe_chunk.py` — chunk 拆分携带多义候选

**Files:**
- Create（复制）: `scripts/term_suggest.py`（Langlobal 缺失的既有依赖，从 skills/ 拷贝，跟本次设计无关但会阻断本任务的测试）
- Modify: `scripts/lqe_chunk.py:16-17`（import）
- Modify: `scripts/lqe_chunk.py:20-43`（`_term_hits`）
- Modify: `scripts/lqe_chunk.py:61-73`（`cmd_split` 里 `titems`/`tn_pairs` 构建）
- Modify: `scripts/run_tests.py`（新增测试 + 注册）

**Interfaces:**
- Consumes: Task 1 的 `group_terms`
- Produces: chunk 文件里每段 `term_hits[].th` 字段——**总是列表**（哪怕只有 1 个候选），每项含 `target`/可选 `category`/`definition`/`status`。Task 6 的 `docs/lenses/T.md` 按这个形状描述给 subagent

- [ ] **Step 1: 补缺失依赖**

```bash
cp ~/.claude/skills/lqe-translator/scripts/term_suggest.py \
   /Users/spellbook/Desktop/Langlobal/lqe-translator/scripts/term_suggest.py
cd /Users/spellbook/Desktop/Langlobal/lqe-translator
python3 -c "import sys; sys.path.insert(0,'scripts'); import term_suggest; print('import ok')"
git add scripts/term_suggest.py
git commit -m "$(cat <<'EOF'
补齐 scripts/term_suggest.py（lqe_chunk.py 既有依赖，Langlobal 此前缺失）

TB 近似术语建议模块，skills/ 副本已有、Langlobal 没同步过；
lqe_chunk.py 一直 import 它，缺失会导致 split 命令直接崩，
跟本次多义映射改动无关，只是本任务测试的前置阻断项。
EOF
)"
```

- [ ] **Step 2: 写失败测试**

在 `scripts/run_tests.py` 里 T9 之后插入：

```python

# ── T10: lqe_chunk split 多义 term_hits ───────────────────────────────────────
def t10():
    job = TMP / "j10"
    job.mkdir(parents=True, exist_ok=True)
    state = {"segments": [
        {"id": 0, "source": "看到一只里奥。", "target": "Saw a ลีโอ."},
        {"id": 1, "source": "马尔文来了。", "target": "มาร์วิน is here."},
    ]}
    (job / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    (job / "errors_precheck.json").write_text(json.dumps(
        [{"id": 0, "errors": []}, {"id": 1, "errors": []}], ensure_ascii=False), encoding="utf-8")
    (job / "terms.json").write_text(json.dumps([
        {"source": "里奥", "senses": [
            {"target": "ลีโอ", "category": "Creature Individual"},
            {"target": "ไลเอล", "category": "Creature Species"},
        ]},
        {"source": "马尔文", "target": "มาร์วิน", "status": "New"},
    ], ensure_ascii=False), encoding="utf-8")
    outdir = job / "chunks"
    r = run("lqe_chunk.py", "split", "--state", str(job / "state.json"),
            "--errors", str(job / "errors_precheck.json"),
            "--terms", str(job / "terms.json"),
            "--outdir", str(outdir), "--size", "10")
    check("T10 split rc", r.returncode == 0, r.stderr[-300:])
    chunk = json.loads((outdir / "chunk_00.json").read_text(encoding="utf-8"))
    seg0 = next(s for s in chunk["segments"] if s["id"] == 0)
    seg1 = next(s for s in chunk["segments"] if s["id"] == 1)
    hit0 = next(h for h in seg0["term_hits"] if h["src"] == "里奥")
    check("T10 multi-sense th is list of 2", isinstance(hit0["th"], list) and len(hit0["th"]) == 2)
    check("T10 multi-sense categories present",
          {s.get("category") for s in hit0["th"]} == {"Creature Individual", "Creature Species"})
    hit1 = next(h for h in seg1["term_hits"] if h["src"] == "马尔文")
    check("T10 singleton th is list of 1",
          isinstance(hit1["th"], list) and len(hit1["th"]) == 1 and hit1["th"][0]["target"] == "มาร์วิน")
```

注册行改成：

```python
    for t in (t1, t2, t3, t4, t5, t6, t7, t8, t9, t10):
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd /Users/spellbook/Desktop/Langlobal/lqe-translator && python3 scripts/run_tests.py`
Expected: `T10 multi-sense th is list of 2` 失败（现有 `_term_hits` 每个 source 只保留一个 `th` 字符串）

- [ ] **Step 4: 实现**

`scripts/lqe_chunk.py` 第 16-17 行：

旧：
```python
from lqe_engine import read_json as load
from term_suggest import build_index as _tn_build, suggest as _tn_suggest
```
新：
```python
from lqe_engine import read_json as load, group_terms
from term_suggest import build_index as _tn_build, suggest as _tn_suggest
```

第 20-43 行（`_term_hits`）：

旧：
```python
def _term_hits(src_txt, titems, cap=15):
    """Longest-match, coverage-filtered term hits. Keep a TB term only if it has
    an occurrence NOT fully inside a longer term's occurrence — so 优优 inside
    绒光优优 is dropped (the longer term already covers it), but a separate
    standalone 优优 elsewhere in the segment is still kept."""
    occ = []  # (start, end, src, th, status)
    for ts, th, st in titems:               # titems is sorted longest-first
        i = src_txt.find(ts)
        while i >= 0:
            occ.append((i, i + len(ts), ts, th, st))
            i = src_txt.find(ts, i + 1)
    occ.sort(key=lambda o: -(o[1] - o[0]))  # longest span first
    accepted = []                           # spans claimed by longer terms
    kept = {}                               # src -> hit (one entry per term)
    for s, e, ts, th, st in occ:
        if any(a <= s and e <= b for a, b in accepted):
            continue                        # covered by a longer term -> drop
        accepted.append((s, e))
        if ts not in kept:
            h = {"src": ts, "th": th}
            if st:
                h["status"] = st
            kept[ts] = h
    return list(kept.values())[:cap]
```
新：
```python
def _term_hits(src_txt, titems, cap=15):
    """Longest-match, coverage-filtered term hits. Keep a TB term only if it has
    an occurrence NOT fully inside a longer term's occurrence — so 优优 inside
    绒光优优 is dropped (the longer term already covers it), but a separate
    standalone 优优 elsewhere in the segment is still kept. `th` is always the
    full candidate-senses list (len 1 for an ordinary singleton source)."""
    occ = []  # (start, end, src, senses)
    for ts, senses in titems:               # titems is sorted longest-first
        i = src_txt.find(ts)
        while i >= 0:
            occ.append((i, i + len(ts), ts, senses))
            i = src_txt.find(ts, i + 1)
    occ.sort(key=lambda o: -(o[1] - o[0]))  # longest span first
    accepted = []                           # spans claimed by longer terms
    kept = {}                               # src -> hit (one entry per term)
    for s, e, ts, senses in occ:
        if any(a <= s and e <= b for a, b in accepted):
            continue                        # covered by a longer term -> drop
        accepted.append((s, e))
        if ts not in kept:
            kept[ts] = {"src": ts, "th": senses}
    return list(kept.values())[:cap]
```

第 61-73 行（`cmd_split` 里 titems/tn_pairs 构建）：

旧：
```python
    titems = [(t["source"], t.get("target", ""), t.get("status", ""))
              for t in terms if len(t.get("source", "")) >= 2]
    titems.sort(key=lambda x: -len(x[0]))

    # near-term suggester (TF-IDF over TB)：精确匹配漏的"差一两字"变体名 → term_near 参考
    tn_pairs = [(t["source"], t.get("target", "")) for t in terms if t.get("source")]
    tn_idx = _tn_build([p[0] for p in tn_pairs], [p[1] for p in tn_pairs]) if tn_pairs else None
```
新：
```python
    grouped = group_terms(terms)
    titems = [(src, senses) for src, senses in grouped.items() if len(src) >= 2]
    titems.sort(key=lambda x: -len(x[0]))

    # near-term suggester (TF-IDF over TB)：精确匹配漏的"差一两字"变体名 → term_near 参考
    # 多义词条取第一个候选译法作代表值（term_near 只是参考线索，不需要区分语义）
    tn_pairs = [(src, senses[0]["target"]) for src, senses in grouped.items() if senses]
    tn_idx = _tn_build([p[0] for p in tn_pairs], [p[1] for p in tn_pairs]) if tn_pairs else None
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd /Users/spellbook/Desktop/Langlobal/lqe-translator && python3 scripts/run_tests.py`
Expected: 全绿，无 `FAILED:`

- [ ] **Step 6: Commit**

```bash
cd /Users/spellbook/Desktop/Langlobal/lqe-translator
git add scripts/lqe_chunk.py scripts/run_tests.py
git commit -m "$(cat <<'EOF'
lqe_chunk: split 携带多义候选列表进 chunk 文件

titems 从(source,target,status)三元组改成(source,senses)；
_term_hits 的 th 字段统一为候选列表(单义也是长度1的列表)，
subagent 能看到全部候选和消歧信息(category/definition)。
EOF
)"
```

---

### Task 4: `lqe_io.py` — lookup-terms 多义展示

**Files:**
- Modify: `scripts/lqe_io.py:25-31`（import）
- Modify: `scripts/lqe_io.py:522-554`（`cmd_lookup_terms`）
- Modify: `scripts/run_tests.py`（新增测试 + 注册）

**Interfaces:**
- Consumes: Task 1 的 `group_terms`
- Produces: 无（`lookup-terms` 是诊断用命令，无下游任务依赖它的输出格式）

- [ ] **Step 1: 写失败测试**

在 `scripts/run_tests.py` 里 T10 之后插入：

```python

# ── T11: lookup-terms 多义展示 ────────────────────────────────────────────────
def t11():
    rows = [('里奥出现了。', 'placeholder')]
    make_xlsx(TMP / "t11.xlsx", rows)
    (TMP / "t11_tb.json").write_text(json.dumps([
        {"source": "里奥", "senses": [
            {"target": "ลีโอ", "category": "Creature Individual"},
            {"target": "ไลเอล", "category": "Creature Species"},
        ]},
    ], ensure_ascii=False), encoding="utf-8")
    r = run("lqe_io.py", "read", "--input", str(TMP / "t11.xlsx"),
            "--source-col", "原文", "--target-col", "译文", "--target-lang", "th",
            "--wordcount-basis", "source-chars",
            "--terminology", str(TMP / "t11_tb.json"), "--out", str(TMP / "j11/state.json"))
    check("T11 read rc", r.returncode == 0, r.stderr[-200:])
    r = run("lqe_io.py", "lookup-terms", "--state", str(TMP / "j11/state.json"))
    check("T11 lookup rc", r.returncode == 0, r.stderr[-200:])
    check("T11 shows both candidates", "ลีโอ" in r.stdout and "ไลเอล" in r.stdout)
```

注册行改成：

```python
    for t in (t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11):
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/spellbook/Desktop/Langlobal/lqe-translator && python3 scripts/run_tests.py`
Expected: `T11 shows both candidates` 失败（现有 `cmd_lookup_terms` 直接 `t["target"]`，多义条目没有这个 key 会抛 `KeyError`，`r.returncode != 0`）

- [ ] **Step 3: 实现**

`scripts/lqe_io.py` 第 25-31 行：

旧：
```python
from lqe_engine import (
    read_json, RE_CJK as _RE_CJK, _target_lang, _load_lang, _LANG_DIR, _SKILL_ROOT,
    CATEGORY_ORDER as _ALL_CATS, CATEGORY_PARENT as _PARENT,
    VALID_CATEGORIES as _VALID_CATEGORIES, VALID_SEVERITIES as _VALID_SEVERITIES,
    apply_severity, load_terms as _load_terms,
    raw_points, weighted_points,
)
```
新：
```python
from lqe_engine import (
    read_json, RE_CJK as _RE_CJK, _target_lang, _load_lang, _LANG_DIR, _SKILL_ROOT,
    CATEGORY_ORDER as _ALL_CATS, CATEGORY_PARENT as _PARENT,
    VALID_CATEGORIES as _VALID_CATEGORIES, VALID_SEVERITIES as _VALID_SEVERITIES,
    apply_severity, load_terms as _load_terms, group_terms as _group_terms,
    raw_points, weighted_points,
)
```

第 522-554 行（`cmd_lookup_terms`）：

旧：
```python
def cmd_lookup_terms(args):
    state = read_json(args.state)
    terms = _load_terms(state)
    if not terms:
        print("[lqe_io] no terminology available.", file=sys.stderr)
        return

    term_map = {t["source"].strip(): t["target"].strip() for t in terms if t.get("source")}

    segs = state["segments"]
    if args.ids:
        id_set = set(int(x) for x in args.ids.split(","))
        segs = [s for s in segs if s["id"] in id_set]

    # 逐段匹配，避免跨段拼接产生误命中
    hits: dict[str, dict] = {}  # term_source → {target, seg_ids}
    for seg in segs:
        src_text = seg["source"]
        for term_src, term_tgt in term_map.items():
            if term_src in src_text:
                if term_src not in hits:
                    hits[term_src] = {"target": term_tgt, "seg_ids": []}
                hits[term_src]["seg_ids"].append(seg["id"])

    if not hits:
        print("[lookup-terms] no terminology matches found.")
        return

    print(f"[lookup-terms] {len(hits)} matches:\n")
    for src, info in sorted(hits.items(), key=lambda x: -len(x[0])):
        seg_ids = info["seg_ids"]
        id_str = f"  (segs: {seg_ids})" if len(seg_ids) <= 5 else f"  ({len(seg_ids)} segs)"
        print(f"  {src} → {info['target']}{id_str}")
```
新：
```python
def cmd_lookup_terms(args):
    state = read_json(args.state)
    terms = _load_terms(state)
    if not terms:
        print("[lqe_io] no terminology available.", file=sys.stderr)
        return

    term_map = _group_terms(terms)

    segs = state["segments"]
    if args.ids:
        id_set = set(int(x) for x in args.ids.split(","))
        segs = [s for s in segs if s["id"] in id_set]

    # 逐段匹配，避免跨段拼接产生误命中
    hits: dict[str, dict] = {}  # term_source → {senses, seg_ids}
    for seg in segs:
        src_text = seg["source"]
        for term_src, senses in term_map.items():
            if term_src in src_text:
                if term_src not in hits:
                    hits[term_src] = {"senses": senses, "seg_ids": []}
                hits[term_src]["seg_ids"].append(seg["id"])

    if not hits:
        print("[lookup-terms] no terminology matches found.")
        return

    print(f"[lookup-terms] {len(hits)} matches:\n")
    for src, info in sorted(hits.items(), key=lambda x: -len(x[0])):
        seg_ids = info["seg_ids"]
        id_str = f"  (segs: {seg_ids})" if len(seg_ids) <= 5 else f"  ({len(seg_ids)} segs)"
        tgt_str = " | ".join(s["target"] for s in info["senses"])
        print(f"  {src} → {tgt_str}{id_str}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /Users/spellbook/Desktop/Langlobal/lqe-translator && python3 scripts/run_tests.py`
Expected: 全绿，无 `FAILED:`

- [ ] **Step 5: Commit**

```bash
cd /Users/spellbook/Desktop/Langlobal/lqe-translator
git add scripts/lqe_io.py scripts/run_tests.py
git commit -m "$(cat <<'EOF'
lqe_io: lookup-terms 改用 group_terms，多义词条列出全部候选

原实现直接读 entry["target"]，多义条目没有这个 key 会直接崩；
改用 group_terms 后统一按候选列表处理，展示用" | "连接全部候选译法。
EOF
)"
```

---

### Task 5: `mastertb_to_terms.py` — 产出多义 senses 数组、撤销 `--override`

**Files:**
- Modify: `scripts/mastertb_to_terms.py`（整体重写，见下方完整新内容）
- Modify: `scripts/run_tests.py`（新增测试 + 注册）

**Interfaces:**
- Consumes: 无（本任务不依赖 Task 1-4，只读 `lqe_engine.read_json`，跟之前一样）
- Produces: `terms_*.json` 文件（Task 2/3/4 消费的格式）；`<out 去掉扩展名>.multisense.json` 侧输出——本次转换里所有 senses 数量 >1 的 source 清单，给人核对

- [ ] **Step 1: 写失败测试**

在 `scripts/run_tests.py` 里 T11 之后插入：

```python

# ── T12: mastertb_to_terms 多义输出 + 去重键改 (source,target) ────────────────
def t12():
    job = TMP / "j12"
    job.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["术语类别 Category", "术语 ZHCN", "术语定义 Definition", "TH"])
    for r in [
        ("NPC", "张三", "张三定义", "ซาน"),
        ("Species", "里奥", "物种定义", "ไลเอล"),
        ("Individual", "里奥", "个体定义", "ลีโอ"),
        ("NPC", "李四", "", ""),
        ("NPC", "王五", "", ""),
        ("NPC", "张三", "张三定义", "ซาน"),  # 完全重复行，应合并不产生第二候选
    ]:
        ws.append(list(r))
    wb.save(job / "master.xlsx")
    (job / "backfill.json").write_text(json.dumps(
        [{"source": "李四", "target": "หลี่ซื่อ"}], ensure_ascii=False), encoding="utf-8")

    r = run("mastertb_to_terms.py", "--input", str(job / "master.xlsx"),
            "--target-col", "TH", "--backfill", str(job / "backfill.json"),
            "--out", str(job / "terms.json"))
    check("T12 rc", r.returncode == 0, r.stderr[-300:])

    terms = {t["source"]: t for t in json.loads((job / "terms.json").read_text(encoding="utf-8"))}
    check("T12 sources (王五 blank+无回填 -> 丢弃)", set(terms.keys()) == {"张三", "里奥", "李四"})
    check("T12 singleton shape 不带 category", terms["张三"] == {"source": "张三", "target": "ซาน"})
    check("T12 回填出的单义 shape", terms["李四"] == {"source": "李四", "target": "หลี่ซื่อ"})
    senses = terms["里奥"]["senses"]
    check("T12 多义候选数", len(senses) == 2)
    check("T12 多义候选 target", {s["target"] for s in senses} == {"ไลเอล", "ลีโอ"})
    check("T12 多义候选 category 带出", {s["category"] for s in senses} == {"Species", "Individual"})

    multisense = json.loads((job / "terms.multisense.json").read_text(encoding="utf-8"))
    check("T12 multisense.json 只列里奥", len(multisense) == 1 and multisense[0]["source"] == "里奥")
```

注册行改成：

```python
    for t in (t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11, t12):
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/spellbook/Desktop/Langlobal/lqe-translator && python3 scripts/run_tests.py`
Expected: `T12 多义候选数` 等多条失败（现有脚本按 source 去重，「里奥」只会剩一条，也不产出 `terms.multisense.json`）

- [ ] **Step 3: 实现**

整体替换 `scripts/mastertb_to_terms.py` 全文为：

```python
#!/usr/bin/env python3
"""Convert a ROCO Master TB workbook to the LQE terms_*.json format.

The master TB layout: a title/blank band on top, then a header row that
contains "术语 ZHCN" (source). The target language lives in its own column;
status/category/definition columns are detected best-effort by header text
(their position and header wording drift between master versions).

Output: list of terms — {"source","target"[,"status"]} for a source with a
single known translation, or {"source","senses":[{"target"[,"status"]
[,"category"][,"definition"]}, ...]} when the SAME source legitimately has
more than one translation (e.g. a name reused for both a Species and a
Creature Individual, or a verb/noun pair) — a real, client-intended polysemy,
not a data error. Rows with an empty target are dropped (untranslated,
cannot serve as a term) unless --backfill recovers an old translation for
that exact gap; concepts absent from the master entirely are NOT backfilled.
`<out>.multisense.json` is always (re)written with every source that ended
up with >1 sense in this run, for a human to eyeball.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from lqe_engine import read_json

import openpyxl

ZW = {0x200b: None, 0x200c: None, 0x200d: None, 0xfeff: None, 0x2060: None}
SRC_HDR = "术语 ZHCN"
STATUS_HDRS = {"术语状态 status", "status", "术语状态"}
CATEGORY_HDRS = {"术语类别 category", "术语类别", "subject", "category"}
DEFINITION_HDRS = {"术语定义 definition", "definition", "note", "术语定义"}


def clean(v) -> str:
    if v is None:
        return ""
    return str(v).translate(ZW).strip()


def find_header_row(rows, src_hdr):
    for i, r in enumerate(rows):
        if any(clean(c) == src_hdr for c in r):
            return i
    raise SystemExit(f"[err] header row containing {src_hdr!r} not found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--target-col", default="TH", help="target language header (e.g. TH/EN)")
    ap.add_argument("--source-hdr", default=SRC_HDR)
    ap.add_argument("--backfill", default=None,
                    help="old terms json: carry over translations for sources the "
                         "master left blank (待填充 gap-fill); concepts absent from "
                         "the master are NOT backfilled")
    args = ap.parse_args()

    wb = openpyxl.load_workbook(args.input, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    h = find_header_row(rows, args.source_hdr)
    hdr = [clean(c) for c in rows[h]]
    try:
        si = hdr.index(args.source_hdr)
        ti = hdr.index(args.target_col)
    except ValueError:
        raise SystemExit(f"[err] columns not found. headers={hdr}")
    # status header is the first status column AFTER the target column
    sti = next((j for j, c in enumerate(hdr) if j > ti and c.lower() in STATUS_HDRS), None)
    # category/definition headers: best-effort, anywhere (position drifts across master versions)
    ci = next((j for j, c in enumerate(hdr) if c.lower() in CATEGORY_HDRS), None)
    di = next((j for j, c in enumerate(hdr) if c.lower() in DEFINITION_HDRS), None)

    by_src: dict[str, list[dict]] = {}
    dropped_empty = 0
    empty_src = set()  # sources present in master with a blank target (待填充)
    for r in rows[h + 1:]:
        src = clean(r[si]) if si < len(r) else ""
        if not src or src == args.source_hdr:
            continue
        tgt = clean(r[ti]) if ti < len(r) else ""
        if not tgt:
            dropped_empty += 1
            empty_src.add(src)
            continue

        cand = {"target": tgt}
        st = clean(r[sti]) if (sti is not None and sti < len(r)) else ""
        if st:
            cand["status"] = st
        cat = clean(r[ci]) if (ci is not None and ci < len(r)) else ""
        if cat:
            cand["category"] = cat
        defn = clean(r[di]) if (di is not None and di < len(r)) else ""
        if defn:
            cand["definition"] = defn

        existing = by_src.setdefault(src, [])
        dup = next((c for c in existing if c["target"] == tgt), None)
        if dup is None:
            existing.append(cand)
        else:
            for k in ("status", "category", "definition"):  # 补全：先出现的行缺、后出现的行有
                if k in cand and k not in dup:
                    dup[k] = cand[k]

    backfilled = 0
    if args.backfill:
        old = read_json(args.backfill)
        for t in old:
            s = clean(t.get("source"))
            g = clean(t.get("target"))
            # only fill master's 待填充 holes; never resurrect dropped concepts
            if s and g and s in empty_src and s not in by_src:
                item = {"target": g}
                st = clean(t.get("status"))
                if st:
                    item["status"] = st
                by_src[s] = [item]
                backfilled += 1

    terms = []
    multisense = []
    for src, cands in by_src.items():
        if len(cands) == 1:
            c = cands[0]
            item = {"source": src, "target": c["target"]}
            if c.get("status"):
                item["status"] = c["status"]
            terms.append(item)
        else:
            terms.append({"source": src, "senses": cands})
            multisense.append({"source": src,
                                "senses": [{"target": c["target"], "category": c.get("category", "")}
                                           for c in cands]})

    Path(args.out).write_text(
        json.dumps(terms, ensure_ascii=False, indent=1), encoding="utf-8")

    multisense_path = Path(args.out).with_suffix("")
    multisense_path = multisense_path.with_name(multisense_path.name + ".multisense.json")
    if multisense:
        multisense_path.write_text(
            json.dumps(multisense, ensure_ascii=False, indent=1), encoding="utf-8")
    elif multisense_path.exists():
        multisense_path.unlink()  # 上一轮遗留、这轮已经没有多义分组了

    dist = Counter(c.get("status", "(none)") for cands in by_src.values() for c in cands)
    n_status = sum(v for k, v in dist.items() if k != "(none)")
    print(f"[ok] wrote {len(terms)} sources ({sum(len(v) for v in by_src.values())} total senses) -> {args.out}")
    print(f"     master-filled sources: {len(by_src) - backfilled}  backfilled (待填充 gap): {backfilled}")
    print(f"     master empty-target rows: {dropped_empty}")
    print(f"     with status: {n_status}  dist: {dict(dist)}")
    print(f"     multi-sense sources: {len(multisense)}" +
          (f" -> {multisense_path}" if multisense else ""))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /Users/spellbook/Desktop/Langlobal/lqe-translator && python3 scripts/run_tests.py`
Expected: 全绿，无 `FAILED:`

- [ ] **Step 5: Commit**

```bash
cd /Users/spellbook/Desktop/Langlobal/lqe-translator
git add scripts/mastertb_to_terms.py scripts/run_tests.py
git commit -m "$(cat <<'EOF'
mastertb_to_terms: 产出多义 senses 数组，撤销 --override

去重键从 source 改成 (source,target)：同源不同译法不再"留第一个
丢其余"，全部保留成 senses 数组，自动带上检测到的 category/definition。
--override 存在的唯一理由(schema 装不下多义)已经不成立，撤销；
未来若要收敛某个多义词条，正确做法是改 Master TB 本身。
新增 <out>.multisense.json 无条件侧输出，列出本次多义分组给人核对。
EOF
)"
```

---

### Task 6: AI 侧文档 — 消歧提示格式

**Files:**
- Modify: `SKILL.md:181-189`
- Modify: `docs/lenses/T.md:7`
- Modify: `docs/EVAL_SPEC.md:16`

**Interfaces:**
- Consumes: Task 2/3 确定的候选展示格式（`target(category)`，多个候选用竖线或 "or" 连接）
- Produces: 无下游任务依赖

- [ ] **Step 1: 修改 SKILL.md**

第 181-189 行：

旧：
```
#### 术语注入

从 `terms_path` 加载术语表，格式化注入评估上下文：
```
=== MANDATORY TERMINOLOGY (deviation = Terminology [Major]) ===
长鸣玉    → Echo Jade
师傅/公子 → Master
...
```
```
新：
```
#### 术语注入

从 `terms_path` 加载术语表，格式化注入评估上下文；多义词条（同一 source 有多个候选译法）列出全部候选 + 消歧信息，结合段落语境判断该用哪个，译文都不匹配才报 Terminology：
```
=== MANDATORY TERMINOLOGY (deviation = Terminology [Major]) ===
长鸣玉    → Echo Jade
师傅/公子 → Master
里奥      → ลีโอ（Creature Individual） | ไลเอล（Creature Species）
...
```
```

- [ ] **Step 2: 修改 docs/lenses/T.md**

第 7 行：

旧：
```
2. **术语**：整词命中 `term_hits` 即对；偏离报 Terminology + 给 TB 译法。status：**Approved/WorkingTB=硬 Major**；**New=软**（报但按语境甄别）；最长匹配——被更长术语覆盖的子词不单报。整词不在 TB→标「TB 未收录」，关键专名/分歧→标交人工，勿硬猜。
```
新：
```
2. **术语**：`term_hits[].th` 是候选列表（可能不止一个）；命中任一候选（结合段落语境 + category/definition 消歧信息判断该用哪个）即对，都不匹配才报 Terminology + 列出全部候选。status：**Approved/WorkingTB=硬 Major**；**New=软**（报但按语境甄别）；最长匹配——被更长术语覆盖的子词不单报。整词不在 TB→标「TB 未收录」，关键专名/分歧→标交人工，勿硬猜。
```

- [ ] **Step 3: 修改 docs/EVAL_SPEC.md**

第 16 行：

旧：
```
C. **术语**：整词命中 term_hits 即对；偏离报 Terminology + 给 TB 译法。**最长匹配**——被更长术语覆盖的子词不单独报（子词与整词译法不一属客户库问题，不报）
```
新：
```
C. **术语**：`term_hits[].th` 是候选列表；命中任一候选（结合语境判断该用哪个）即对，都不匹配才报 Terminology + 列出全部候选。**最长匹配**——被更长术语覆盖的子词不单独报（子词与整词译法不一属客户库问题，不报）
```

- [ ] **Step 4: 验证**

Run:
```bash
cd /Users/spellbook/Desktop/Langlobal/lqe-translator
grep -c "候选" SKILL.md docs/lenses/T.md docs/EVAL_SPEC.md
grep "term_hits 即对；偏离报" SKILL.md docs/lenses/T.md docs/EVAL_SPEC.md
```
Expected: 第一条三个文件都 `>=1`；第二条（旧措辞）三个文件都无输出（说明旧句式已经被替换掉，不是被追加）

- [ ] **Step 5: Commit**

```bash
cd /Users/spellbook/Desktop/Langlobal/lqe-translator
git add SKILL.md docs/lenses/T.md docs/EVAL_SPEC.md
git commit -m "$(cat <<'EOF'
文档同步多义术语的消歧提示格式

SKILL.md 术语注入示例、docs/lenses/T.md(大文件多agent路径)、
docs/EVAL_SPEC.md(小文件单agent路径)三处都改成"候选列表+结合
语境判断"的描述，跟 lqe_checks.py/lqe_chunk.py 的新行为对齐。
EOF
)"
```

---

### Task 7: 迁移 nrc/th 真实数据

**Files:**
- Delete: `projects/nrc/th/overrides_th.json`
- Delete: `projects/nrc/th/terms_th.conflicts.json`（旧概念，被 `terms_th.multisense.json` 取代）
- Modify（脚本产出，非手写）: `projects/nrc/th/terms_th.json`
- Create（脚本产出）: `projects/nrc/th/terms_th.multisense.json`
- Modify: `projects/nrc/th/adjudications.md:29-34`

**Interfaces:**
- Consumes: Task 5 的新 `mastertb_to_terms.py`
- Produces: nrc/th 项目现在能真实体现 6 个多义词条的两个语义（原来 `--override` 只保留一个）

- [ ] **Step 1: 删除临时方案文件**

```bash
cd /Users/spellbook/Desktop/Langlobal/lqe-translator
rm projects/nrc/th/overrides_th.json
rm -f projects/nrc/th/terms_th.conflicts.json
```

- [ ] **Step 2: 用新脚本重新跑 0630 导入**

```bash
python3 scripts/mastertb_to_terms.py \
  --input projects/nrc/common/ROCO_MasterTB_0630.xlsx \
  --target-col TH --source-hdr "术语 ZHCN" \
  --backfill projects/nrc/th/terms_th_pre0630.bak.json \
  --out projects/nrc/th/terms_th.json
```
Expected: 打印里 `multi-sense sources: 6`（或更多，如果扫到其他此前没发现的多义组也一并出现，属正常）

- [ ] **Step 3: 验证 6 个已知多义词条两个语义都在**

```bash
python3 -c "
import json
terms = {t['source']: t for t in json.load(open('projects/nrc/th/terms_th.json', encoding='utf-8'))}
expect = {
    '里奥': {'ลีโอ', 'ไลเอล'},
    '伊贝儿': {'อีเบย์', 'ไอเบอร์รี'},
    '裘卡': {'จูคา', 'เฟลวาร์ด'},
    '黄蜂后': {'นางพญาผึ้ง', 'บัมเบล'},
    '呱呱': {'ก๊าบก๊าบ', 'บันนี่'},
    '克制': {'ชนะทาง', 'ข่ม'},
}
for src, want in expect.items():
    got = {s['target'] for s in terms[src]['senses']}
    assert got == want, (src, got, want)
print('OK: 6 个多义词条两个语义都已找回')
print('总source数:', len(terms))
"
```
Expected: `OK: 6 个多义词条两个语义都已找回`，`总source数: 4314`（跟改动前一致，只是形状变了，没多没少）

- [ ] **Step 4: 更新 adjudications.md**

`projects/nrc/th/adjudications.md` 第 32-34 行：

旧：
```
- **同名多义**：伊贝儿/里奥/裘卡/黄蜂后/呱呱/克制 在「物种 Species」与「个体/NPC」两分类下译法被 0630 故意拆开（0629 两分类译法一致，无冲突）。terms_th.json 扁平结构一个源词只存一条，裁决**保留个体/NPC/动词译法**（与更新前一致）；物种语境若用到这几个词，按新表物种译法判断，勿因 TB 命中个体译法而误报 Terminology
  - 分歧详情（双方 category+译法）见 `terms_th.conflicts.json`；裁决落 `overrides_th.json`，`--override` 每次重新导入自动重新生效，防止被行序静默翻转。以后新出现的分歧、或这几条分歧消失，脚本会在 conflicts.json 里报出未被 override 覆盖的部分
  - 根因是 schema 无 category 维度；此类词条量大再考虑术语表加 category 字段做分场景匹配
```
新：
```
- **同名多义**：伊贝儿/里奥/裘卡/黄蜂后/呱呱/克制 在「物种 Species」与「个体/NPC」两分类下译法被 0630 故意拆开（0629 两分类译法一致，无冲突）。terms_th.json 现已支持一个 source 挂多个 `senses`（见 `docs/TERM_MULTISENSE_DESIGN.md`），两个语义都已收进 TB，不再只保留一个——评估时 AI 结合段落语境（个体/角色 vs 物种）判断该用哪个，都不匹配才报 Terminology
  - 全部多义分组清单见 `terms_th.multisense.json`（每次重新导入自动重新生成，供人核对是不是真的有意为之）
```

- [ ] **Step 5: Commit**

```bash
cd /Users/spellbook/Desktop/Langlobal/lqe-translator
git add projects/nrc/th/adjudications.md
git status --short projects/nrc/th/
git commit -m "$(cat <<'EOF'
nrc/th: 迁移到多义 senses 结构，找回被 override 压掉的物种译法

删 overrides_th.json/terms_th.conflicts.json(临时方案)，
terms_th.json/terms_th.multisense.json 是脚本产出不进 git
(projects/ 已 gitignore)，adjudications.md 记录更新。
EOF
)"
```

（`projects/` 目录被 `.gitignore` 排除，`git status --short projects/nrc/th/` 应该只显示 `adjudications.md` 有变化，`terms_th.json` 等不会出现——这一步是确认这件事，不是遗漏。）

---

### Task 8: 同步到 skills/lqe-translator，全量验证

**Files:**
- Modify: `~/.claude/skills/lqe-translator/scripts/lqe_engine.py`（覆盖为 Langlobal 版本）
- Modify: `~/.claude/skills/lqe-translator/scripts/lqe_checks.py`（同上）
- Modify: `~/.claude/skills/lqe-translator/scripts/lqe_chunk.py`（同上）
- Modify: `~/.claude/skills/lqe-translator/scripts/lqe_io.py`（同上）
- Modify: `~/.claude/skills/lqe-translator/scripts/mastertb_to_terms.py`（同上）
- Modify: `~/.claude/skills/lqe-translator/scripts/run_tests.py`（同上）
- Modify: `~/.claude/skills/lqe-translator/SKILL.md`（同上）
- Modify: `~/.claude/skills/lqe-translator/docs/lenses/T.md`（同上）
- Modify: `~/.claude/skills/lqe-translator/docs/EVAL_SPEC.md`（同上）
- Modify: `~/.claude/skills/lqe-translator/projects/nrc/th/*`（terms_th.json/multisense.json/adjudications.md，覆盖为 Langlobal 版本；删 overrides_th.json/terms_th.conflicts.json）

**Interfaces:**
- Consumes: Task 1-7 在 Langlobal 完成且测试全绿的最终版本
- Produces: 两边运行副本行为一致

- [ ] **Step 1: 同步脚本 + 文档**

```bash
SK=~/.claude/skills/lqe-translator
LL=/Users/spellbook/Desktop/Langlobal/lqe-translator

for f in scripts/lqe_engine.py scripts/lqe_checks.py scripts/lqe_chunk.py \
         scripts/lqe_io.py scripts/mastertb_to_terms.py scripts/run_tests.py \
         scripts/term_suggest.py SKILL.md docs/lenses/T.md docs/EVAL_SPEC.md; do
  cp "$LL/$f" "$SK/$f"
done
```

- [ ] **Step 2: 同步 nrc/th 项目数据**

```bash
SK=~/.claude/skills/lqe-translator/projects/nrc/th
LL=/Users/spellbook/Desktop/Langlobal/lqe-translator/projects/nrc/th

rm -f "$SK/overrides_th.json" "$SK/terms_th.conflicts.json"
cp "$LL/terms_th.json" "$SK/terms_th.json"
cp "$LL/terms_th.multisense.json" "$SK/terms_th.multisense.json"
cp "$LL/adjudications.md" "$SK/adjudications.md"
```

- [ ] **Step 3: 两边跑全量测试**

```bash
cd /Users/spellbook/Desktop/Langlobal/lqe-translator && python3 scripts/run_tests.py
cd ~/.claude/skills/lqe-translator && python3 scripts/run_tests.py
```
Expected: 两边都全绿、无 `FAILED:`，通过数一致

- [ ] **Step 4: 验证两份 terms_th.json 内容一致**

```bash
python3 -c "
import json
a = json.load(open('/Users/spellbook/Desktop/Langlobal/lqe-translator/projects/nrc/th/terms_th.json', encoding='utf-8'))
b = json.load(open('/Users/spellbook/.claude/skills/lqe-translator/projects/nrc/th/terms_th.json', encoding='utf-8'))
assert a == b, 'terms_th.json 两边不一致'
print('OK: 两边 terms_th.json 完全一致，', len(a), '条')
"
```

- [ ] **Step 5: Commit（两个仓库分别 commit，都不 push）**

```bash
cd ~/.claude/skills
git add lqe-translator/scripts/lqe_engine.py lqe-translator/scripts/lqe_checks.py \
        lqe-translator/scripts/lqe_chunk.py lqe-translator/scripts/lqe_io.py \
        lqe-translator/scripts/mastertb_to_terms.py lqe-translator/scripts/run_tests.py \
        lqe-translator/scripts/term_suggest.py lqe-translator/SKILL.md \
        lqe-translator/docs/lenses/T.md lqe-translator/docs/EVAL_SPEC.md
git status --short lqe-translator/ | head -20
git commit -m "$(cat <<'EOF'
lqe-translator: 同步术语库多义映射改动(源自 Langlobal 开发仓)

lqe_engine 加 term_senses/group_terms 多义读取层；lqe_checks/
lqe_chunk/lqe_io 三个消费点改用它做"命中任意候选"判定；
mastertb_to_terms 产出 senses 数组、撤销 --override；SKILL.md/
docs/lenses/T.md/docs/EVAL_SPEC.md 同步消歧提示格式。
详细设计见 Desktop/Langlobal/lqe-translator/docs/TERM_MULTISENSE_DESIGN.md，
实现按同仓库 docs/superpowers/plans/2026-07-01-terminology-multisense-mapping.md 执行。
EOF
)"
```

**Step 5 前必须先跑 `git status --short lqe-translator/`，确认只有上面列出的文件在变化——`~/.claude` 仓库根还有很多跟这次任务无关的其他文件（backups/、cache/、file-history/ 等），只能用具体文件名 `git add`，绝不能用 `git add -A`/`git add .`。**

```bash
cd /Users/spellbook/Desktop/Langlobal/lqe-translator
git add projects/nrc/th/terms_th.json projects/nrc/th/terms_th.multisense.json
git commit -m "$(cat <<'EOF'
nrc/th: terms_th.json 产出物快照(仅记录，projects/已gitignore不追踪)
EOF
)"
```

（这一步大概率是空提交——`projects/` 已被 Langlobal 仓库的 `.gitignore` 排除，`git add` 不会真的加进去；写这条只是确认一遍，不必强求成功。）

---

## Self-Review 记录

- **Spec 覆盖**：`TERM_MULTISENSE_DESIGN.md` 的「数据结构」「共用读取层」「消费端改动」「AI侧改动」「mastertb_to_terms.py改动」「迁移现有数据」「测试」七节分别对应 Task 1/1/2-4/6/5/7/(贯穿全部任务)，「影响范围说明」体现在每个任务测试都跑全量回归、单义路径零改动的断言（T9 第 3 条、T12 前两条）。「非目标」三条（多对一、pre-check自动判语境、反向查询）本计划没有任何任务触碰，符合预期。
- **占位符扫描**：全文没有 TBD/待补/"类似 Task N 处理"这类占位，`mastertb_to_terms.py` 是整体重写、给了完整文件内容，不是"在 xx 基础上改"。
- **类型一致性**：`term_senses`/`group_terms` 的签名在 Task 1 定义后，Task 2/3/4 的 import 别名（`_group_terms` in lqe_checks.py/lqe_io.py，`group_terms` in lqe_chunk.py——两种别名是因为三个文件各自的既有 import 风格不同，各自内部前后一致）、调用方式在各任务里都对得上。`_fmt_sense`/`multisense_path` 等新增名字只在各自任务内使用，没有跨任务改名不一致的情况。
