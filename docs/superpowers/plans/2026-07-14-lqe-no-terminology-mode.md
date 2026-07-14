# LQE 无术语检查模式实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让普通 LQE job 原生支持不加载术语表、不运行术语/专名模块，同时保留非术语预检复核、评分、报告和历史 state 兼容。

**Architecture:** 在 `lqe_engine.py` 建立唯一的检查范围解析接口，`read` 将实时要求固化到 `state.check_scope`，所有术语读取、预检、分块、批处理、模块校验、合并和报告都只读取该状态。无术语模式以真实的 `precheck_review` 替代 `terminology`，避免伪造空术语输出或按类别事后过滤。

**Tech Stack:** Python 3.14，标准库 `argparse/json/pathlib/subprocess/tempfile/unittest`，`openpyxl`，POSIX shell。

## Global Constraints

- 实时 `--no-terminology` 高于 profile 术语配置；与同一命令显式 `--terminology` 互斥。
- 无术语模式不得读取 `terms_path`、内嵌 `terminology` 或 job 残留 `terms.json`。
- 无术语模式必需模块固定为 `precheck_review/accuracy/grammar/naturalness`。
- 标准模式继续要求 `terminology/accuracy/grammar/naturalness`，`proper_names` 仍为可选模块。
- 历史 state 缺少 `check_scope` 时按原标准四模块工作，不自动重写历史 state。
- Markup、Length、Locale convention、Company style、非术语 Inconsistency 和 Other 必须经过 `precheck_review`，不能直接把机器预检透传计分。
- 无术语模式不得产生或合并 Terminology 类别、`TERM REVIEW:` 或 confirmed-term 修改证据。
- `lqe_chunk`、`lqe_batch`、`lqe_calc`、`build-results`、报告和 export 入口都必须复用同一范围防线；任何旁路在计分或交付前失败。
- 不改变评分权重、严重度、阈值、重复段规则、修订写入权或 MasterTB 自检流程。
- `lqe-translator` 目录当前不是 Git 仓库；不得擅自初始化仓库。每个任务以定向测试和文件校验作为检查点，无法执行 commit 步骤。

---

### Task 1: 检查范围模型、CLI 和术语读取总闸

**Files:**
- Modify: `scripts/lqe_engine.py:154-165`
- Modify: `scripts/lqe_io.py:298-548`
- Modify: `scripts/lqe_io.py:1322-1340`
- Create: `tests/test_no_terminology_mode.py`

**Interfaces:**
- Produces: `build_check_scope(no_terminology: bool, source: str = "runtime") -> dict`。
- Produces: `get_check_scope(state: dict) -> dict`。
- Produces: `required_modules(state: dict) -> tuple[str, ...]`、`optional_modules(state: dict) -> tuple[str, ...]`、`disabled_modules(state: dict) -> tuple[str, ...]`、`terminology_enabled(state: dict) -> bool`。
- Produces: `scope_issue_problem(state: dict, issue: dict) -> str | None`，供所有合并、计分和报告入口共享。
- Produces: `validate_scope_entries(state: dict, entries: list[dict], *, issues_key: str, label: str) -> None`，统一校验 check/final 两种结果形状。
- Changes: `load_terms(state: dict) -> list[dict]` 在禁用时固定返回空列表。
- Produces CLI: `lqe_io.py read --no-terminology`。
- Produces artifact: `<job>/scope.json`，内容与解析后的 `state.check_scope` 一致。

- [ ] **Step 1: 写范围和 CLI 失败测试**

在 `tests/test_no_terminology_mode.py` 建立临时 profile、术语 JSON 和 CSV，加入以下核心测试：

```python
def test_profile_terms_are_not_loaded_when_disabled(self):
    result = self.run_io(
        "read", "--input", self.source, "--project", self.profile,
        "--source-col", "Source", "--target-col", "Target",
        "--no-terminology", "--out", self.state,
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    state = read_json(self.state)
    self.assertEqual(state["terms_path"], "")
    self.assertEqual(state["terminology"], [])
    self.assertEqual(
        state["check_scope"]["enabled_modules"],
        ["precheck_review", "accuracy", "grammar", "naturalness"],
    )
    self.assertFalse((self.state.parent / "terms.json").exists())
    self.assertEqual(read_json(self.state.parent / "scope.json"), state["check_scope"])
    self.assertIn("profile terminology overridden by --no-terminology", result.stdout)

def test_explicit_terms_conflict_with_no_terminology(self):
    result = self.run_io(
        "read", "--input", self.source,
        "--source-col", "Source", "--target-col", "Target",
        "--terminology", self.terms, "--no-terminology", "--out", self.state,
    )
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("not allowed with argument", result.stderr)

def test_load_terms_cannot_bypass_disabled_scope(self):
    state = {
        "check_scope": build_check_scope(True),
        "terms_path": str(self.terms),
        "terminology": [{"source": "A", "target": "B"}],
    }
    self.assertEqual(load_terms(state), [])

def test_malformed_scope_fails_with_contract_error(self):
    with self.assertRaisesRegex(ValueError, "check_scope must be an object"):
        get_check_scope({"check_scope": []})

def test_legacy_state_uses_standard_scope_without_rewrite(self):
    state = {"segments": []}
    self.assertEqual(
        required_modules(state),
        ("terminology", "accuracy", "grammar", "naturalness"),
    )
    self.assertNotIn("check_scope", state)

def test_standard_mode_still_loads_profile_terminology(self):
    result = self.run_io(
        "read", "--input", self.source, "--project", self.profile,
        "--source-col", "Source", "--target-col", "Target", "--out", self.state,
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    state = read_json(self.state)
    self.assertTrue(terminology_enabled(state))
    self.assertTrue(load_terms(state))
    self.assertEqual(required_modules(state), STANDARD_REQUIRED_MODULES)
```

- [ ] **Step 2: 运行测试并确认红灯**

Run from repository root: `python3 -m unittest -v tests.test_no_terminology_mode`

Expected: FAIL because `build_check_scope` and `--no-terminology` do not exist.

- [ ] **Step 3: 在 engine 建立唯一范围接口**

在 `scripts/lqe_engine.py` 使用以下固定契约；`get_check_scope()` 只接受 `standard` 或 `no-terminology`，并根据 mode 重新构造模块列表，不能信任 state 中任意自定义模块名：

```python
STANDARD_REQUIRED_MODULES = ("terminology", "accuracy", "grammar", "naturalness")
NO_TERMINOLOGY_REQUIRED_MODULES = ("precheck_review", "accuracy", "grammar", "naturalness")
OPTIONAL_MODULES = ("proper_names",)
TERMINOLOGY_MODULES = ("terminology", "proper_names", "term_audit")

def build_check_scope(no_terminology: bool, source: str = "runtime") -> dict:
    if no_terminology:
        return {
            "mode": "no-terminology",
            "terminology_enabled": False,
            "enabled_modules": list(NO_TERMINOLOGY_REQUIRED_MODULES),
            "disabled_modules": list(TERMINOLOGY_MODULES),
            "source": source,
        }
    return {
        "mode": "standard",
        "terminology_enabled": True,
        "enabled_modules": list(STANDARD_REQUIRED_MODULES),
        "disabled_modules": [],
        "source": source,
    }

def get_check_scope(state: dict) -> dict:
    if not isinstance(state, dict):
        raise ValueError("state must be an object")
    raw = state.get("check_scope")
    if raw is None:
        return build_check_scope(False, "legacy-default")
    if not isinstance(raw, dict):
        raise ValueError("check_scope must be an object")
    mode = raw.get("mode")
    if mode not in {"standard", "no-terminology"}:
        raise ValueError(f"unsupported check_scope mode: {mode!r}")
    resolved = build_check_scope(mode == "no-terminology", raw.get("source") or "state")
    for key in ("terminology_enabled", "enabled_modules", "disabled_modules"):
        if key in raw and raw[key] != resolved[key]:
            raise ValueError(f"check_scope {key} conflicts with mode {mode}")
    return resolved

def required_modules(state: dict) -> tuple[str, ...]:
    return tuple(get_check_scope(state)["enabled_modules"])

def optional_modules(state: dict) -> tuple[str, ...]:
    return OPTIONAL_MODULES if get_check_scope(state)["mode"] == "standard" else ()

def disabled_modules(state: dict) -> tuple[str, ...]:
    return tuple(get_check_scope(state)["disabled_modules"])

def terminology_enabled(state: dict) -> bool:
    return bool(get_check_scope(state)["terminology_enabled"])

def scope_issue_problem(state: dict, issue: dict) -> str | None:
    if terminology_enabled(state):
        return None
    if not isinstance(issue, dict):
        return "issue must be an object"
    if issue.get("category") == "Terminology":
        return "Terminology issue is disabled by check scope"
    if str(issue.get("comment") or "").lstrip().startswith("TERM REVIEW:"):
        return "TERM REVIEW evidence is disabled by check scope"
    edit = issue.get("edit")
    evidence = edit.get("evidence") if isinstance(edit, dict) else None
    if isinstance(evidence, dict) and evidence.get("type") == "confirmed_term":
        return "confirmed_term edit evidence is disabled by check scope"
    return None

def validate_scope_entries(
    state: dict,
    entries: list[dict],
    *,
    issues_key: str,
    label: str,
) -> None:
    if issues_key not in {"issues", "errors"}:
        raise ValueError(f"unsupported issues key: {issues_key!r}")
    for entry in entries:
        for issue in entry.get(issues_key, []):
            problem = scope_issue_problem(state, issue)
            if problem:
                raise ValueError(f"{label}: scope conflict: {problem}")
```

`get_check_scope()` 先验证 `check_scope` 是 object、mode 是允许值，且布尔值和模块数组与 mode 一致；畸形 state 给出 `ValueError`，不得用 `AttributeError` 泄漏实现细节。`scope_issue_problem()` 在无术语模式拒绝 Terminology 类别、`TERM REVIEW:` comment，以及 `edit.evidence.type == "confirmed_term"`。`validate_scope_entries()` 只接受已由现有 normalizer 验证的数组，并为错误加统一 `scope conflict` 上下文。`load_terms()` 的第一条分支必须是 `if not terminology_enabled(state): return []`。

- [ ] **Step 4: 增加 CLI、优先级和原子 scope 输出**

在 `read` parser 中用互斥组声明 `--terminology` 与 `--no-terminology`。`cmd_read()` 先解析 scope；禁用时不继承 profile 术语，标准模式才执行现有 profile 回填。profile 有术语而 CLI 禁用时打印固定覆盖日志 `profile terminology overridden by --no-terminology`。增加 `_write_json_atomic(path: Path, value: object) -> None`，先写同目录临时文件再 `replace()`，并用它发布 `scope.json` 和最终 `state.json`。

- [ ] **Step 5: 运行定向测试并确认绿灯**

Run: `python3 -m unittest -v tests.test_no_terminology_mode.NoTerminologyScopeTests`

Expected: all scope tests `OK`.

- [ ] **Step 6: 非 Git 检查点**

Run: `python3 -m py_compile scripts/lqe_engine.py scripts/lqe_io.py tests/test_no_terminology_mode.py`

Expected: exit code 0.

### Task 2: 预检、分块和批处理统一服从 scope

**Files:**
- Modify: `scripts/lqe_checks.py:217-548`
- Modify: `scripts/lqe_chunk.py:85-177`
- Modify: `scripts/lqe_chunk.py:500-510`
- Modify: `scripts/lqe_batch.py:25-105`
- Test: `tests/test_no_terminology_mode.py`

**Interfaces:**
- Consumes: `terminology_enabled()` and `load_terms()` from Task 1.
- Changes CLI: `lqe_chunk.py split --terms` becomes optional.
- Guarantees: disabled jobs always produce `term_hits=[]` and `term_near=[]`.
- Guarantees: batch prompts cannot read a residual `job/terms.json` when terminology is disabled.

- [ ] **Step 1: 写预检、split 和 batch 旁路失败测试**

```python
def test_precheck_omits_terms_but_keeps_non_term_checks(self):
    self.read_no_term_job([
        ("生命值", "Health"),
        ("<b>你好</b>", "Hello"),
        ("获得 100 金币 {0}", "Get 10 coins"),
        ("点击开始", "Click Start"),
        ("点击开始", "Tap Begin"),
    ], terms=[{"source": "生命值", "target": "HP", "confirmed": True}])
    self.run_precheck()
    issues = flatten_issues(read_json(self.job / "errors_precheck.json"))
    self.assertFalse(any(i["category"] == "Terminology" for i in issues))
    self.assertFalse(any(i["comment"].startswith("TERM REVIEW:") for i in issues))
    self.assertTrue(any(i["category"] == "Markup" for i in issues))
    self.assertTrue(any(i["category"] == "Inconsistency" for i in issues))
    self.assertTrue(any("100" in i["comment"] or "{0}" in i["comment"] for i in issues))

def test_split_without_terms_writes_empty_term_context(self):
    result = self.run_chunk(
        "split", "--state", self.job / "state.json",
        "--errors", self.job / "errors_precheck.json",
        "--outdir", self.job / "chunks",
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    segment = read_json(self.job / "chunks/chunk_00.json")["segments"][0]
    self.assertEqual(segment["term_hits"], [])
    self.assertEqual(segment["term_near"], [])

def test_split_rejects_explicit_terms_in_disabled_scope(self):
    result = self.run_chunk(
        "split", "--state", self.job / "state.json",
        "--errors", self.job / "errors_precheck.json",
        "--terms", self.terms,
        "--outdir", self.job / "chunks",
    )
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("scope conflict", result.stderr)

def test_batch_plan_ignores_residual_terms_file(self):
    write_json(self.job / "terms.json", [{"source": "生命值", "target": "HP"}])
    result = self.run_batch("plan", "--job", self.job)
    self.assertEqual(result.returncode, 0, result.stderr)
    prompt = (self.job / "batches/batch_00.txt").read_text()
    self.assertNotIn("TERMS:", prompt)
    self.assertIn("Terminology check: disabled", prompt)

def test_batch_merge_rejects_terminology_issue(self):
    self.write_batch_eval(category="Terminology", comment="forbidden")
    result = self.run_batch("merge", "--job", self.job)
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("scope conflict", result.stderr)
    self.assertFalse((self.job / "errors.json").exists())
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `python3 -m unittest -v tests.test_no_terminology_mode.NoTerminologyPrecheckTests`

Expected: FAIL because split requires `--terms` and batch reads `terms.json` directly.

- [ ] **Step 3: 修改预检和分块术语来源**

`run_pre_check()` 继续通过 `load_terms(state)` 建立 term map；当 scope 禁用时显式把 `terminology`、`term_case` toggle 设为 `False`。写输出前扫描结果，若禁用模式出现 Terminology 或 `TERM REVIEW:`，以内部范围错误退出，不写结果文件。

`cmd_split()` 先处理兼容参数，但读取仍统一经过 engine：

```python
if a.terms and not terminology_enabled(state):
    raise SystemExit("[split] scope conflict: --terms is disabled by check scope")
term_state = state
if a.terms:
    terms_path = Path(a.terms)
    if not terms_path.is_file():
        raise SystemExit(f"[split] terminology file not found: {terms_path}")
    term_state = {**state, "terms_path": str(terms_path), "terminology": []}
terms = load_terms(term_state)
```

parser 改为 `s.add_argument("--terms", default=None)`。保留标准模式显式 `--terms` 的旧命令兼容，但任何实际文件读取仍由 `load_terms()` 完成。

- [ ] **Step 4: 修复 batch 术语旁路**

`lqe_batch.cmd_plan()` 不再读取 `job/terms.json`，改为 `terms = load_terms(state)`。prompt 从 canonical scope 写入启用模块；无术语模式固定写 `Terminology check: disabled`，并明确禁止 Terminology、proper-name 和 confirmed-term 证据。`cmd_merge()` 在写 `errors.json` 前执行与 chunk 相同的范围校验，发现禁用类别、`TERM REVIEW:` 或 confirmed-term edit evidence 时失败。预算和其余 merge 协议保持不变。

- [ ] **Step 5: 运行定向测试并确认绿灯**

Run: `python3 -m unittest -v tests.test_no_terminology_mode.NoTerminologyPrecheckTests`

Expected: all pre-check, split and batch tests `OK`.

- [ ] **Step 6: 非 Git 检查点**

Run: `python3 -m py_compile scripts/lqe_checks.py scripts/lqe_chunk.py scripts/lqe_batch.py`

Expected: exit code 0.

### Task 3: 动态检查模块、precheck_review 和合并防线

**Files:**
- Modify: `scripts/lqe_engine.py:154-190`
- Modify: `scripts/lqe_chunk.py:257-413`
- Modify: `scripts/lqe_calc.py:1-120`
- Create: `docs/check_modules/precheck_review.md`
- Modify: `docs/check_modules/common.md`
- Modify: `tests/test_plain_language.py:20-100`
- Test: `tests/test_no_terminology_mode.py`

**Interfaces:**
- Consumes: `required_modules()`、`optional_modules()`、`disabled_modules()`、`terminology_enabled()`。
- Consumes: `scope_issue_problem()` and `validate_scope_entries()` from Task 1。
- Changes: `_check_modules(job: Path) -> tuple[dict, list[str], tuple[str, ...], tuple[str, ...]]`。
- Produces check file: `chunk_NN.precheck_review.json`。
- Allowed `precheck_review` categories: Markup, Length, Locale convention, Company style, Inconsistency, Other。

- [ ] **Step 1: 写动态模块失败测试**

```python
def test_validate_requires_precheck_review_not_terminology(self):
    self.make_no_term_chunk_job()
    self.write_modules(("precheck_review", "accuracy", "grammar", "naturalness"))
    result = self.run_chunk("validate-checks", "--job", self.job)
    self.assertEqual(result.returncode, 0, result.stderr)

def test_validate_fails_when_precheck_review_is_missing(self):
    self.make_no_term_chunk_job()
    self.write_modules(("accuracy", "grammar", "naturalness"))
    result = self.run_chunk("validate-checks", "--job", self.job)
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("precheck_review", result.stderr)

def test_validate_rejects_disabled_module_file(self):
    self.make_no_term_chunk_job()
    self.write_modules(("precheck_review", "accuracy", "grammar", "naturalness", "terminology"))
    result = self.run_chunk("validate-checks", "--job", self.job)
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("scope conflict", result.stderr)

def test_validate_rejects_terminology_category(self):
    self.make_no_term_chunk_job()
    self.write_modules(("precheck_review", "accuracy", "grammar", "naturalness"))
    write_json(self.job / "chunks/chunk_00.precheck_review.json", [{
        "id": 0,
        "issues": [{"category": "Terminology", "severity": "Major", "comment": "forbidden", "needs_confirmation": True, "edit": None}],
    }])
    result = self.run_chunk("merge-checks", "--job", self.job)
    self.assertNotEqual(result.returncode, 0)
    self.assertFalse((self.job / "chunks/chunk_00.out.json").exists())

def test_legacy_state_still_requires_standard_four_modules(self):
    self.make_legacy_chunk_job()
    self.write_modules(("accuracy", "grammar", "naturalness"))
    result = self.run_chunk("validate-checks", "--job", self.job)
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("terminology", result.stderr)

def test_calc_rejects_forbidden_issue_before_scoring(self):
    self.write_complete_no_term_errors(
        category="Other",
        comment="forbidden",
        edit={"from": "A", "to": "B", "evidence": {"type": "confirmed_term"}},
    )
    result = self.run_calc()
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("scope conflict", result.stderr)
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `python3 -m unittest -v tests.test_no_terminology_mode.NoTerminologyModuleTests`

Expected: FAIL because `lqe_chunk.py` still uses fixed module tuples.

- [ ] **Step 3: 动态解析、验证和合并模块**

把 `_check_modules(outdir)` 改为接收 job，读取 `state.json` 后取得 canonical required/optional/disabled 模块。每个 chunk 先拒绝已禁用模块文件，再验证必需文件及 ID 覆盖。返回 module order 给 `cmd_merge_checks()`，禁止再遍历全局固定常量。

加入：

```python
_PRECHECK_REVIEW_CATEGORIES = {
    "Markup", "Length", "Locale convention", "Company style", "Inconsistency", "Other",
}

def _module_issue_problem(module: str, issue: dict, *, terminology_on: bool) -> str | None:
    category = issue.get("category")
    if not terminology_on and category == "Terminology":
        return "Terminology issue is disabled by check scope"
    if module == "precheck_review" and category not in _PRECHECK_REVIEW_CATEGORIES:
        return f"precheck_review cannot own category {category!r}"
    return None
```

`_module_issue_problem()` 先调用 `scope_issue_problem()`，再执行模块类别所有权检查。在 `cmd_merge()` 写 `errors.json` 前对 module `issues` 和最终 `errors` 调用 `validate_scope_entries()`，保证旧 `.out.json` 不能绕过校验；`lqe_calc.py` 在任何计分和重复标记写回前也校验最终 `errors`，保证其他入口无法计分禁用问题。

- [ ] **Step 4: 新增模块说明并更新公共契约**

`precheck_review.md` 必须明确全 ID 覆盖、只复核 chunk 中非术语 precheck、允许类别、误报可删除、不得创建新术语/专名判断，并含以下协议示例：

```json
[{"id": 0, "issues": [{"category": "Markup", "severity": "Major", "comment": "The target drops one inline tag.", "needs_confirmation": true, "edit": null}]}]
```

`common.md` 同时列出标准模式和无术语模式。`test_plain_language.py::CHECK_MODULE_NAMES` 增加 `precheck_review.md`。

- [ ] **Step 5: 运行动态模块与文档测试**

Run: `python3 -m unittest -v tests.test_no_terminology_mode.NoTerminologyModuleTests tests.test_plain_language`

Expected: all selected tests `OK`.

- [ ] **Step 6: 非 Git 检查点**

Run: `python3 scripts/lqe_chunk.py --help >/dev/null && python3 -m unittest -v tests.test_corrected_ownership.CorrectedOwnershipChunkTests`

Expected: help exits 0 and existing chunk tests remain `OK`.

### Task 4: 范围报告与无术语端到端收尾

**Files:**
- Modify: `scripts/lqe_io.py:548-798`
- Modify: `scripts/lqe_io.py:799-1148`
- Modify: `scripts/lqe_io.py:1200-1315`
- Modify: `scripts/finalize_job.sh:1-40`
- Test: `tests/test_no_terminology_mode.py`
- Modify: `tests/test_corrected_ownership.py:1170-1278`

**Interfaces:**
- Consumes: `get_check_scope(state)`。
- Produces report text: `Terminology check: Disabled by runtime request`。
- Preserves: Scorecard 中 Terminology 行保留且计数为零。
- Preserves finalize order: validate-checks → merge-checks → reconcile → merge → calc → write/apply → export。

- [ ] **Step 1: 写报告与 finalize 失败测试**

```python
def test_no_terminology_finalize_produces_report_without_term_files(self):
    self.build_complete_no_term_job()
    result = subprocess.run(
        ["bash", str(FINALIZE_SCRIPT), str(self.job), "1", "single"],
        cwd=ROOT, text=True, capture_output=True,
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertTrue((self.job / "errors.json").exists())
    self.assertFalse(any(self.job.glob("chunks/*.terminology.json")))
    self.assertTrue(list(self.job.glob("*_lqe.xlsx")))
    self.assertTrue(list(self.job.glob("*_corrected.xlsx")))

def test_report_records_disabled_terminology_and_enabled_modules(self):
    report = next(self.job.glob("*_lqe.xlsx"))
    workbook = openpyxl.load_workbook(report, data_only=True)
    try:
        values = [str(cell.value) for sheet in workbook for row in sheet for cell in row if cell.value is not None]
    finally:
        workbook.close()
    joined = "\n".join(values)
    self.assertIn("Terminology check: Disabled by runtime request", joined)
    self.assertIn("precheck_review, accuracy, grammar, naturalness", joined)

def test_write_rejects_forbidden_issue_even_when_called_directly(self):
    self.write_complete_no_term_errors(category="Terminology", comment="forbidden")
    result = self.run_io("write", "--state", self.job / "state.json", "--errors", self.job / "errors.json", "--score", "100")
    self.assertNotEqual(result.returncode, 0)
    self.assertFalse(list(self.job.glob("*_lqe.xlsx")))

def test_build_results_and_export_reject_forbidden_issue(self):
    self.write_raw_checks(category="Terminology", comment="forbidden")
    built = self.run_io(
        "build-results", "--state", self.job / "state.json",
        "--checks", self.job / "checks.json", "--out", self.job / "errors.json",
    )
    self.assertNotEqual(built.returncode, 0)
    self.assertFalse((self.job / "errors.json").exists())

    self.write_complete_no_term_errors(category="Terminology", comment="forbidden")
    exported = self.run_io(
        "export", "--state", self.job / "state.json", "--errors", self.job / "errors.json",
    )
    self.assertNotEqual(exported.returncode, 0)
    self.assertFalse(list(self.job.glob("*_corrected.xlsx")))
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `python3 -m unittest -v tests.test_no_terminology_mode.NoTerminologyFinalizeTests`

Expected: FAIL because reports do not expose scope.

- [ ] **Step 3: 把 scope 写入导读和计分卡**

`cmd_build_results()` 在构造 final results 前校验 `issues`；`cmd_write()`、`cmd_apply_fixes()` 和带 `--errors` 的 `cmd_export()` 在改 state 或生成工作簿前校验 `errors`。随后 `_build_xlsx()` 解析 canonical scope：导读新增一行 `Check scope`，内容为术语状态和启用模块；计分卡 Date 行右侧现有空位写 `Terminology check` 及状态，避免移动固定版式。标准模式显示 `Enabled`，无术语模式显示精确固定文案。

- [ ] **Step 4: 保持 finalize 单一路径并输出范围**

`finalize_job.sh` 只更新注释和开始日志，通过读取 state 打印 enabled modules；不得增加两套收尾分支。更新现有 stub 测试，继续断言四个 chunk 命令顺序不变。

- [ ] **Step 5: 运行端到端测试并确认绿灯**

Run: `python3 -m unittest -v tests.test_no_terminology_mode.NoTerminologyFinalizeTests tests.test_corrected_ownership.CorrectedOwnershipPipelineTests`

Expected: all selected tests `OK`.

- [ ] **Step 6: shell 与产物检查点**

Run: `bash -n scripts/finalize_job.sh`

Expected: exit code 0.

### Task 5: 用户文档和完整回归

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `README_ZH.md`
- Modify: `PM_GUIDE.html`
- Modify: `projects/README.md`
- Modify: `tests/test_documented_contract.py`
- Modify: `scripts/run_tests.py:760-785`

**Interfaces:**
- Documents: `--no-terminology`、双模式必需模块、`precheck_review`、`scope.json`。
- Adds regression suite: `tests.test_no_terminology_mode` to `run_tests.py::t25()`。

- [ ] **Step 1: 写文档契约失败测试**

```python
def test_common_documents_both_module_sets(self):
    self.assertIn("precheck_review", self.common)
    self.assertIn("state.check_scope", self.common)

def test_skill_documents_no_terminology_cli(self):
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    self.assertIn("--no-terminology", skill)
    self.assertIn("scope.json", skill)

def test_run_tests_t25_includes_no_terminology_suite(self):
    runner = (ROOT / "scripts/run_tests.py").read_text(encoding="utf-8")
    self.assertIn('"tests.test_no_terminology_mode"', runner)
```

- [ ] **Step 2: 运行文档测试并确认红灯**

Run: `python3 -m unittest -v tests.test_documented_contract`

Expected: FAIL because the user-facing workflow still describes one fixed four-module set.

- [ ] **Step 3: 同步用户文档和总测试入口**

更新初始化、预检、模块、分块、文件结构和验证章节。明确“不检查术语”只关闭术语/专名，不关闭文件内一致性、Markup、数字等检查。`run_tests.py::t25()` 加入 `tests.test_no_terminology_mode`。

- [ ] **Step 4: 运行定向文档与协议回归**

Run: `python3 -m unittest -v tests.test_no_terminology_mode tests.test_documented_contract tests.test_plain_language tests.test_corrected_ownership tests.test_mastertb_module_contract`

Expected: all selected tests `OK`; MasterTB 仍使用原标准四模块。

- [ ] **Step 5: 运行完整回归**

Run: `python3 scripts/run_tests.py`

Expected: all checks pass；文档契约测试确认 T25 的 subprocess argv 包含 `tests.test_no_terminology_mode`。`run_tests.py` 的顶层计数按 check group 计，不要求因同一 T25 内增加 unittest 模块而大于当前 151。

- [ ] **Step 6: 最终非 Git 检查点**

Run: `rg -n "create_skipped_terminology_outputs|skip_terminology|filter_precheck" SKILL.md README.md README_ZH.md scripts docs/check_modules`

Expected: no workflow instruction requires any job-local skip/filter script.
