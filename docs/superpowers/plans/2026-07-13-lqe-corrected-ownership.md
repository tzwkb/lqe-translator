# LQE `corrected` 单一写入者实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让检查模块只报问题和局部修改，由确定性 Python 程序唯一生成 `corrected`，并保持现有计分与标准 Excel 产物。

**Architecture:** 新建 `scripts/lqe_corrections.py` 作为唯一修改合成器，所有单文件、分块、批处理和 MasterTB 路径都调用它。检查模块统一输出 `{id, issues}`，顶层 `corrected` 直接使结构检查失败；局部修改经唯一定位、保护内容、已确认术语和冲突检查后，再以原译为底生成完整建议译文。

**Tech Stack:** Python 3.14.5，标准库 `json/pathlib/re/subprocess/unittest`，`openpyxl`，shell。

## Global Constraints

- 不改问题类型、严重程度、重复段分组、扣分公式、通过阈值或积分规则。
- `corrected` 只由 Python 合并程序生成；主 agent、子任务模型和检查模块都不得输出或改写该字段。
- 检查模块只输出问题、可选局部修改和 `needs_confirmation`；顶层 `corrected` 立即报错并停止后续流程。
- 专名修改只能由明确含 `confirmed: true` 的术语条目授权；无该标记时只作参考。
- 局部修改的 `from` 必须在原译中唯一出现，或同时给出 0-based、左闭右开的 `start/end`。
- 需要人工确认的问题必须 `edit: null`；冲突修改不执行，不冲突修改继续执行。
- 标准任务只生成 `*_lqe.xlsx` 和 `*_corrected.xlsx`；`_corrected.xlsx` 不新增列，保持输入工作簿结构。
- 不重新处理现有 Excel，不迁移旧检查输出，不改写历史任务产物。
- 不保留旧模块名、旧命令或旧状态字段的兼容层。
- 用户可见文案只使用“检查模块、术语表、已保护、建议修改、需要人工确认、项目负责人、确认规则”等普通用词。

---

### Task 1: 唯一修改合成器

**Files:**
- Create: `scripts/lqe_corrections.py`
- Create: `tests/test_correction_builder.py`
- Modify: `scripts/lqe_engine.py:157-181`

**Interfaces:**
- Produces: `CheckFormatError(ValueError)`。
- Produces: `normalize_check_entries(entries: object, *, label: str) -> list[dict]`。
- Produces: `build_segment_result(segment: dict, issues: list[dict]) -> dict`，返回 `{"id": int, "errors": list[dict], "corrected": str | None}`。
- Produces: `build_results(segments: list[dict], check_entries: list[dict]) -> list[dict]`。
- Removes: `lqe_engine.apply_patches()` 和 `lqe_engine.resolve_corrected()`。

- [ ] **Step 1: 写合成器失败测试**

```python
class CorrectionBuilderTests(unittest.TestCase):
    def test_rejects_model_corrected(self):
        with self.assertRaisesRegex(CheckFormatError, "corrected"):
            normalize_check_entries([{"id": 1, "issues": [], "corrected": "x"}], label="T")

    def test_safe_edit_builds_full_corrected(self):
        seg = {"id": 1, "target": "A“B”C", "kind": "desc", "term_hits": []}
        issues = [{"category": "Punctuation", "severity": "Minor", "comment": "引号格式", "needs_confirmation": False,
                   "edit": {"from": "“B”", "to": "\"B\"", "evidence": None}}]
        self.assertEqual(build_segment_result(seg, issues)["corrected"], 'A"B"C')

    def test_confirmation_issue_cannot_carry_edit(self):
        issue = {"category": "Terminology", "severity": "Major", "comment": "需确认", "needs_confirmation": True,
                 "edit": {"from": "旧", "to": "新", "evidence": None}}
        with self.assertRaisesRegex(CheckFormatError, "edit"):
            build_segment_result({"id": 1, "target": "旧", "kind": "name", "term_hits": []}, [issue])
```

同文件还要以实际断言覆盖：重复 `from` 未给位置时报错；`start/end` 与 `from` 不一致时报错；变量、标签、换行或 `protected_texts` 受损时不执行；完全相同的重叠修改去重；不同的重叠修改转为 `needs_confirmation: true`；非冲突修改仍生效；修改结果等于原译时 `corrected is None`。

- [ ] **Step 2: 运行测试并确认红灯**

Run: `python3 -m unittest -v tests.test_correction_builder`

Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.lqe_corrections'`.

- [ ] **Step 3: 实现严格结构验证**

`normalize_check_entries()` 必须拒绝非数组、非对象项、缺失/重复 `id`、顶层 `corrected`、非数组 `issues`、非布尔 `needs_confirmation`、非对象/`null` 的 `edit`。每个 issue 保留现有 `category/severity/comment/repeated`，附加 `needs_confirmation/edit`。

新模块定义 `class CheckFormatError(ValueError)`，并以精确签名
`normalize_check_entries(entries: object, *, label: str) -> list[dict]`
实现上述检查；函数返回全新列表，不改写调用者传入对象。

- [ ] **Step 4: 实现局部修改检查和合成**

`edit` 结构固定为：

```json
{
  "from": "原译子串",
  "to": "建议子串",
  "start": 0,
  "end": 5,
  "evidence": {"type": "confirmed_term", "source": "奇丽花", "target": "ดอกบ้องแบ๊ว"}
}
```

`start/end` 可整组省略；省略时 `from` 必须唯一。专名段 (`segment.kind == "name"`) 或命中专名术语的修改，其 evidence 必须与 `segment.term_hits[].source/target/confirmed` 完全相符。将可执行修改按 `start` 倒序应用，再生成完整 `corrected`。

- [ ] **Step 5: 删除旧的模型修改直通函数**

在 `scripts/lqe_engine.py` 删除 `apply_patches()` 和 `resolve_corrected()`，不设置兼容别名；保留计分和术语分组函数原样。

- [ ] **Step 6: 运行单元测试并确认绿灯**

Run: `python3 -m unittest -v tests.test_correction_builder`

Expected: all correction-builder tests `OK`.

- [ ] **Step 7: 提交**

```bash
git add scripts/lqe_corrections.py scripts/lqe_engine.py tests/test_correction_builder.py
git commit -m "feat: centralize corrected generation"
```

### Task 2: 检查模块与分块合并协议

**Files:**
- Modify: `scripts/lqe_checks.py:190-260`
- Modify: `scripts/lqe_chunk.py:1-570`
- Create: `tests/test_corrected_ownership.py`
- Delete: `tests/test_pending_adjudication.py`

**Interfaces:**
- Consumes: `normalize_check_entries()` and `build_segment_result()` from Task 1.
- Produces CLI: `merge-checks`, `validate-checks`, `split-half --module`, `ckpt-append`.
- Produces check files: `chunk_NN.terminology.json`, `.accuracy.json`, `.grammar.json`, `.naturalness.json`, optional `.proper_names.json`.

- [ ] **Step 1: 写分块协议失败测试**

```python
def test_validate_checks_rejects_top_level_corrected(self):
    job = make_chunk_job()
    write_json(job / "chunks/chunk_00.terminology.json",
               [{"id": 0, "issues": [], "corrected": "model text"}])
    result = run_chunk("validate-checks", "--job", job)
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("corrected", result.stderr)

def test_mixed_row_only_applies_safe_edit(self):
    # 专名问题 edit=null，空格问题带局部 edit。
    merged = merge_fixture("mixed_proper_name_and_spacing")
    self.assertEqual(merged[0]["corrected"], "สไตล์ฟลอโรรา - รองเท้า")
    self.assertTrue(any(e["needs_confirmation"] for e in merged[0]["errors"]))
```

同文件覆盖：`validate-checks`、`ckpt-append`、`merge-checks` 三入口均拒绝顶层 `corrected`；`深蓝鲸/伊里斯/星光狮` 不生成新译名；`魔草巫灵/奇丽花` 只有 `confirmed: true` 才可替换；`花衣蝶` 冲突修改不落地；广播重复段后 `errors/corrected` 不丢失。

- [ ] **Step 2: 运行指定测试并确认红灯**

Run: `python3 -m unittest -v tests.test_corrected_ownership.CorrectedOwnershipChunkTests`

Expected: FAIL because `merge-checks` and `validate-checks` do not exist.

- [ ] **Step 3: 改造确定性预检查输出**

`scripts/lqe_checks.py::run_pre_check()` 为每段输出 `{id, issues}`；可唯一确定的标点/Markup 问题写 `edit`，只能提醒的问题写 `edit: null`，不写 `corrected`。

- [ ] **Step 4: 替换分块检查合并命令**

在 `scripts/lqe_chunk.py` 完成以下替换：

`_normalize_module_output(arr, path)` 只调用
`normalize_check_entries(arr, label=Path(path).name)`。`cmd_merge_checks(args)`
按段号汇总全部模块的 `issues`，以 `(category, severity, comment, edit)` 去重，
执行现有准确性问题归属过滤，然后写出只含 `{id, issues}` 的
`chunk_NN.out.json`；该命令不生成 `corrected`。
`cmd_validate_checks(args)` 遍历当前 job 的所有 chunk 和适用模块文件，对每个文件调用
`_normalize_module_output()`，缺失必需模块、缺失段号或结构错误均以非零状态退出。

删除 `_norm_lens/_LENS_ADD/corr_candidates/correction_status`、`merge-lenses/validate-lenses`、`--lens`；不保留旧 CLI 别名。`cmd_reconcile()` 只删除不应保留的 issue，仍写出 `{id, issues}`；它不生成 `corrected`。`cmd_ckpt_append()` 也通过同一结构验证。

- [ ] **Step 5: 改造最终分块合并**

`cmd_merge()` 在补回确定性预检查、广播重复段后，对每段以原始 `target/term_hits/kind/protected_texts` 调用 `build_segment_result()`。`_term_hits()` 必须把术语 sense 的 `confirmed` 布尔值一并写入 chunk。这是分块路径唯一生成 `corrected` 的地方。

- [ ] **Step 6: 删除旧状态测试并运行新协议测试**

Run: `python3 -m unittest -v tests.test_corrected_ownership.CorrectedOwnershipChunkTests`

Expected: all chunk ownership tests `OK`.

- [ ] **Step 7: 提交**

```bash
git add scripts/lqe_checks.py scripts/lqe_chunk.py tests/test_corrected_ownership.py
git rm tests/test_pending_adjudication.py
git commit -m "refactor: replace model corrections with checked edits"
```

### Task 3: 单文件、批处理与 MasterTB 共用合成路径

**Files:**
- Modify: `scripts/lqe_io.py:628-764`
- Modify: `scripts/lqe_batch.py:1-150`
- Modify: `scripts/mastertb_prep.py:150-500`
- Modify: `scripts/aggregate_sheets.py:1-160`
- Modify: `scripts/finalize_job.sh`
- Test: `tests/test_corrected_ownership.py`

**Interfaces:**
- Consumes: `normalize_check_entries()` and `build_results()` from Task 1.
- Produces CLI: `lqe_io.py build-results --state STATE --checks CHECKS --out ERRORS`.
- Produces only program-built `errors.json` entries containing `errors` and `corrected`.

- [ ] **Step 1: 写四条路径的失败测试**

```python
def test_build_results_is_required_before_apply(self):
    result = run_io("build-results", "--state", state, "--checks", checks, "--out", errors)
    self.assertEqual(result.returncode, 0)
    self.assertEqual(read_json(errors)[0]["corrected"], 'A"B"C')

def test_batch_merge_rejects_model_corrected(self):
    result = run_batch_merge([{"id": 0, "issues": [], "corrected": "model text"}])
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("corrected", result.stderr)

def test_mastertb_merge_rejects_model_corrected(self):
    result = run_mastertb_merge([{"id": 0, "issues": [], "corrected": "model text"}])
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("corrected", result.stderr)

def test_aggregate_applies_only_non_null_program_result(self):
    output = run_aggregate_fixture([{"id": 0, "errors": [], "corrected": None}])
    self.assertEqual(output["Sheet1"]["B2"].value, "原译")
```

同文件断言 `finalize_job.sh` 只调用 `validate-checks/merge-checks`，不再出现旧命令。

- [ ] **Step 2: 运行路径测试并确认红灯**

Run: `python3 -m unittest -v tests.test_corrected_ownership.CorrectedOwnershipPipelineTests`

Expected: FAIL because `build-results` is absent and old merge paths still accept `corrected`.

- [ ] **Step 3: 增加单文件程序入口**

```python
def cmd_build_results(args):
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    entries = normalize_check_entries(json.loads(Path(args.checks).read_text(encoding="utf-8")), label=args.checks)
    results = build_results(state["segments"], entries)
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
```

将该命令注册到 `lqe_io.py` CLI。主 agent 只能写 `checks.json`，不得直接写最终 `errors.json`。

- [ ] **Step 4: 统一其他合并旁路**

`lqe_batch.py::cmd_merge()` 和 `mastertb_prep.py::cmd_merge()` 先调用 `normalize_check_entries()`，再调用 `build_results()`；删除选择整句候选译文的分支。`mastertb_prep.RUBRIC` 改为 `issues/edit` 协议。

- [ ] **Step 5: 简化多 Sheet 和收尾路径**

`aggregate_sheets.py` 删除状态判断，只应用结果中非空 `corrected`；复制源工作簿后只改目标单元格。`finalize_job.sh` 改用新检查命令和普通终端文案。

- [ ] **Step 6: 运行路径测试并确认绿灯**

Run: `python3 -m unittest -v tests.test_corrected_ownership.CorrectedOwnershipPipelineTests`

Expected: all pipeline ownership tests `OK`.

- [ ] **Step 7: 提交**

```bash
git add scripts/lqe_io.py scripts/lqe_batch.py scripts/mastertb_prep.py scripts/aggregate_sheets.py scripts/finalize_job.sh tests/test_corrected_ownership.py
git commit -m "refactor: route all LQE merges through correction builder"
```

### Task 4: 报告、建议译文工作簿与终端输出

**Files:**
- Modify: `scripts/lqe_io.py:724-1380`
- Modify: `scripts/aggregate_sheets.py`
- Modify: `scripts/gen_checklist_xlsx.py`
- Modify: `scripts/gen_pm_feedback_report_xlsx.py`
- Test: `tests/test_corrected_ownership.py`

**Interfaces:**
- Consumes: program-built `{id, errors, corrected}`.
- Produces report column `处理方式` with fixed values `建议修改/需要人工确认/仅提醒/无需修改/已保护，不修改`.
- Produces `_corrected.xlsx` with exactly the source workbook's sheets, dimensions, columns and non-target cell values.

- [ ] **Step 1: 写报告和工作簿失败测试**

```python
def test_report_uses_plain_processing_labels(self):
    wb = build_report_fixture()
    headers = [c.value for c in wb["LQE"][1]]
    self.assertIn("处理方式", headers)
    self.assertIn("建议译文", headers)

def test_corrected_workbook_has_source_structure(self):
    before = workbook_signature(source_path)
    export_corrected(source_path, results_path, output_path)
    after = workbook_signature(output_path)
    self.assertEqual(after["sheetnames"], before["sheetnames"])
    self.assertEqual(after["dimensions"], before["dimensions"])
    self.assertEqual(after["headers"], before["headers"])
```

额外断言建议译文工作簿没有额外状态列；`corrected is None` 保留原译；混合行只写程序生成的安全修改。

- [ ] **Step 2: 运行报告测试并确认红灯**

Run: `python3 -m unittest -v tests.test_corrected_ownership.CorrectedOwnershipOutputTests`

Expected: FAIL because the old status column and old wording remain.

- [ ] **Step 3: 删除状态字段和待处理分支**

从 `lqe_io.py` 删除 `_CORRECTION_STATUSES/_correction_status/_is_pending_correction/_validate_correction_statuses`，以及 `cmd_apply_fixes()`、`_validate_errors()`、`_build_xlsx()`、`cmd_export()` 中所有状态分支。`errors` 非空但 `corrected: null` 是合法结果。

- [ ] **Step 4: 从 issue 内元数据生成处理方式**

```python
def _processing_label(entry: dict) -> str:
    errors = entry.get("errors") or []
    if any(e.get("protected") for e in errors):
        return "已保护，不修改"
    if any(e.get("needs_confirmation") for e in errors):
        return "需要人工确认"
    if entry.get("corrected") is not None:
        return "建议修改"
    if errors:
        return "仅提醒"
    return "无需修改"
```

报告栏位使用“原译、建议译文、处理方式”。终端只打印“建议修改、需要人工确认、保持原译、已保护”四类数量。

- [ ] **Step 5: 保持建议译文工作簿原结构**

`cmd_export()` 复制原工作簿，仅对有非空 `corrected` 的段落写回原目标列；删除新增状态列、状态颜色和任何额外 sheet。

- [ ] **Step 6: 运行输出测试并确认绿灯**

Run: `python3 -m unittest -v tests.test_corrected_ownership.CorrectedOwnershipOutputTests`

Expected: all output tests `OK`.

- [ ] **Step 7: 提交**

```bash
git add scripts/lqe_io.py scripts/aggregate_sheets.py scripts/gen_checklist_xlsx.py scripts/gen_pm_feedback_report_xlsx.py tests/test_corrected_ownership.py
git commit -m "fix: keep LQE outputs standard and plain"
```

### Task 5: 已确认术语和确认规则数据

**Files:**
- Modify: `scripts/lqe_io.py:360-520`
- Modify: `scripts/lqe_engine.py:186-210`
- Modify: `scripts/mastertb_to_terms.py`
- Modify: `scripts/lqe_calc.py`
- Modify: `scripts/lqe_chunk.py`
- Modify: `scripts/lqe_checks.py`
- Modify: `scripts/tm_index.py`
- Modify: `scripts/tm_index_test.py`
- Rename: `projects/nrc/common/adjudications_common.md` → `projects/nrc/common/confirmed_rules_common.md`
- Rename: `projects/nrc/zh-en/adjudications.md` → `projects/nrc/zh-en/confirmed_rules.md`
- Rename: `projects/nrc/zh-th/adjudications.md` → `projects/nrc/zh-th/confirmed_rules.md`
- Rename: `projects/wwm/zh-en/adjudications.md` → `projects/wwm/zh-en/confirmed_rules.md`
- Rename: `projects/nrc/zh-th/locked_terms_batch4.json` → `projects/nrc/zh-th/protected_terms_batch4.json`
- Modify: `projects/nrc/zh-en/profile.json`
- Modify: `projects/nrc/zh-th/profile.json`
- Modify: `projects/wwm/zh-en/profile.json`
- Test: `tests/test_correction_builder.py`
- Test: `tests/test_corrected_ownership.py`

**Interfaces:**
- Term sense schema requires `{source: str, target: str, confirmed: bool, protected: bool}` and may retain existing descriptive metadata.
- Profile key: `confirmed_rules`; task state key: `confirmed_rules_path`.
- Profile protection key: `protected_term_statuses`; state segment flag: `protected`.
- Protection CLI: `protect-segments --protected-ids/--protected-file`; TM output: `tm_protected.json`.
- Removes: `adjudications/adjudications_path/lock_statuses/locked/lock-segments/--locked-*` from the active workflow.

- [ ] **Step 1: 写已确认术语和路径失败测试**

```python
def test_unmarked_term_cannot_authorize_name_edit(self):
    result = build_segment_result(name_segment(confirmed=False), [name_replacement_issue()])
    self.assertIsNone(result["corrected"])
    self.assertTrue(result["errors"][0]["needs_confirmation"])

def test_confirmed_term_authorizes_exact_name_edit(self):
    result = build_segment_result(name_segment(confirmed=True), [name_replacement_issue()])
    self.assertEqual(result["corrected"], "ดอกบ้องแบ๊ว")
def test_read_state_uses_confirmed_rules_path(self):
    state = run_read_fixture(profile={"confirmed_rules": "confirmed_rules.md"})
    self.assertTrue(state["confirmed_rules_path"].endswith("confirmed_rules.md"))
    self.assertNotIn("adjudications_path", state)

def test_protected_segment_keeps_scoring_behavior(self):
    score = run_score_fixture(segment={"id": 0, "protected": True}, protected_ids=[0])
    self.assertEqual(score["errors"], 0)
```

- [ ] **Step 2: 运行数据协议测试并确认红灯**

Run: `python3 -m unittest -v tests.test_correction_builder tests.test_corrected_ownership.CorrectedOwnershipProjectTests`

Expected: FAIL because confirmation metadata is dropped and old path keys remain.

- [ ] **Step 3: 保留术语元数据**

`lqe_io._clean_terms()` 和 `lqe_engine.term_senses()` 必须保留显式 `confirmed/protected` 布尔值；两者缺失时均补 `False`，不从旧字段推断。`mastertb_to_terms.py` 输出每个 sense 时显式写两个字段。

- [ ] **Step 4: 替换项目确认记录命名**

用 `git mv` 执行四个确认规则文件重命名，然后将 profile 中的 `adjudications` 改为 `confirmed_rules`。`lqe_io.cmd_read()` 合并共通与语言规则后，在 job 目录写 `confirmed_rules.md`，并返回 `confirmed_rules_path`。

- [ ] **Step 5: 统一“已保护”机器命名**

用 `git mv` 将 `locked_terms_batch4.json` 改为 `protected_terms_batch4.json`。将 profile 的 `lock_statuses` 改为 `protected_term_statuses`，术语和段落字段的 `locked` 改为 `protected`。在 `lqe_io.py/lqe_calc.py/lqe_chunk.py/lqe_checks.py/tm_index.py` 中同步改为 `protect-segments`、`--protected-ids`、`--protected-file`、`--out-protected`、`tm_protected.json`；旧命令和旧参数不保留。保护段仍按原有规则不计分、不修改，只更名，不改行为。

- [ ] **Step 6: 运行数据协议测试并确认绿灯**

Run: `python3 -m unittest -v tests.test_correction_builder tests.test_corrected_ownership.CorrectedOwnershipProjectTests && python3 scripts/tm_index_test.py`

Expected: all term-confirmation, project-path and protected-segment tests `OK`.

- [ ] **Step 7: 提交**

```bash
git add scripts/lqe_io.py scripts/lqe_engine.py scripts/mastertb_to_terms.py scripts/lqe_calc.py scripts/lqe_chunk.py scripts/lqe_checks.py scripts/tm_index.py scripts/tm_index_test.py projects tests/test_correction_builder.py tests/test_corrected_ownership.py
git commit -m "refactor: make term confirmation explicit"
```

### Task 6: 检查模块文档与普通用词

**Files:**
- Create: `docs/check_modules/common.md`
- Create: `docs/check_modules/terminology.md`
- Create: `docs/check_modules/accuracy.md`
- Create: `docs/check_modules/grammar.md`
- Create: `docs/check_modules/naturalness.md`
- Create: `docs/check_modules/proper_names.md`
- Create: `docs/check_modules/term_audit.md`
- Delete: `docs/lenses/`
- Delete: `docs/superpowers/plans/2026-07-12-lqe-pending-adjudication.md`
- Delete: `docs/superpowers/specs/2026-07-12-lqe-pending-adjudication-design.md`
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `README_ZH.md`
- Modify: `PM_GUIDE.html`
- Modify: `projects/README.md`
- Modify: `.gitignore`
- Modify: `scripts/term_suggest.py`
- Modify: `scripts/tm_index.py`
- Modify: `scripts/lqe_calc.py`
- Modify: `scripts/lqe_io.py`
- Modify: `scripts/lqe_chunk.py`
- Modify: `scripts/lqe_batch.py`
- Modify: `scripts/lqe_checks.py`
- Modify: `scripts/mastertb_prep.py`
- Modify: `scripts/aggregate_sheets.py`
- Modify: `scripts/finalize_job.sh`
- Modify: `scripts/run_tests.py`
- Create: `tests/test_plain_language.py`

**Interfaces:**
- Check-module prompt output is exactly `{id, issues:[{category,severity,comment,needs_confirmation,edit}]}`.
- User-visible fixed terms are those listed in Global Constraints.

- [ ] **Step 1: 写可见文案和模块协议失败测试**

```python
USER_FACING = [
    "SKILL.md", "README.md", "README_ZH.md", "PM_GUIDE.html", "projects/README.md",
    "docs/check_modules", "scripts/finalize_job.sh", "scripts/mastertb_prep.py",
    "scripts/gen_checklist_xlsx.py", "scripts/gen_pm_feedback_report_xlsx.py",
    "scripts/term_suggest.py", "scripts/tm_index.py",
]
BANNED = [
    "lens", "adjudication", "pending_adjudication", "correction_status", "corr_candidates",
    "locked_ids", "lock_statuses", "lock-segments", "tm_locked", "[locked]", "ai correction",
]

def test_user_facing_sources_use_plain_language(self):
    text = read_all(USER_FACING).lower()
    for word in BANNED:
        self.assertNotIn(word, text)

def test_check_modules_never_request_corrected(self):
    for path in CHECK_MODULE_FILES:
        self.assertNotIn('"corrected"', path.read_text(encoding="utf-8"))
        self.assertIn('"issues"', path.read_text(encoding="utf-8"))
```

中文禁用词包含用来表示人工确认的法律式用词、“AI 修正”、“修正状态”、“透镜”、“锁定段”；测试中以 Unicode code point 数组组装后检查，避免测试文件本身命中扫描。范围仅限当前用户可见流程文件，不扫描 Git 历史、旧产物和本实施计划。

- [ ] **Step 2: 运行文案测试并确认红灯**

Run: `python3 -m unittest -v tests.test_plain_language`

Expected: FAIL listing current old module names and old user-visible wording.

- [ ] **Step 3: 重建检查模块文档**

将旧 A/G/N/R/T 职责分别改为术语、语法、专名、自然度、准确性，共享规则放入 `common.md`。每个模块只要求 `issues/edit`，明确“不得输出 `corrected`”。安全局部修改给 `edit`，新译名、术语表错误或缺词给 `edit: null` 与 `needs_confirmation: true`。

- [ ] **Step 4: 更新技能文档和用户文案**

`SKILL.md` 明确主 agent/子任务模型只产出检查结果，最终 `corrected` 由脚本生成；所有命令、路径、检查模块名与项目确认规则路径同步新协议。README、PM 指南、项目说明和终端文案使用普通用词。删除与新流程相冲突的 2026-07-12 旧方案文档。

- [ ] **Step 5: 更新统一测试入口**

`scripts/run_tests.py` 中的 T4/T7/T10/T20/T22 改用新 key、新模块名、新报告栏位；T25 运行 `tests/test_correction_builder.py`、`tests/test_corrected_ownership.py`、`tests/test_plain_language.py`。保留现有 T13/T14 计分测试断言不变。

- [ ] **Step 6: 运行文案测试并确认绿灯**

Run: `python3 -m unittest -v tests.test_plain_language`

Expected: all plain-language and check-module contract tests `OK`.

- [ ] **Step 7: 提交**

```bash
git add -A SKILL.md README.md README_ZH.md PM_GUIDE.html .gitignore docs projects scripts tests
git commit -m "docs: replace LQE workflow jargon and module names"
```

### Task 7: 计分同等、全量回归与安装同步

**Files:**
- Modify: `tests/test_corrected_ownership.py`
- Modify: `scripts/run_tests.py`
- Sync after verification: `/Users/spellbook/.codex/skills/lqe-translator/`

**Interfaces:**
- Score fixture exact result: `{"score": 91.5, "status": "FAIL", "errors": 2, "wordcount": 100, "critical": 0, "repeated": 0, "npt": 85.0, "critical_gate": false}`.
- Deployment source: current worktree HEAD.
- Deployment destination: `/Users/spellbook/.codex/skills/lqe-translator/`.

- [ ] **Step 1: 写计分同等和产物边界测试**

```python
def test_scoring_is_identical_when_only_correction_metadata_changes(self):
    expected = {"score": 91.5, "status": "FAIL", "errors": 2, "wordcount": 100,
                "critical": 0, "repeated": 0, "npt": 85.0, "critical_gate": False}
    self.assertEqual(run_score(score_fixture(with_edit_metadata=False)), expected)
    self.assertEqual(run_score(score_fixture(with_edit_metadata=True)), expected)

def test_standard_job_has_only_two_xlsx_outputs(self):
    names = sorted(p.name for p in output_dir.glob("*.xlsx"))
    self.assertEqual(names, ["fixture_corrected.xlsx", "fixture_lqe.xlsx"])
```

- [ ] **Step 2: 运行计分与产物测试**

Run: `python3 -m unittest -v tests.test_corrected_ownership.CorrectedOwnershipRegressionTests`

Expected: all regression tests `OK` and both score dictionaries exactly match.

- [ ] **Step 3: 运行全部回归**

Run: `python3 scripts/run_tests.py`

Expected: exit 0; every T-test reports PASS, including unchanged T13/T14 score checks and new T25 ownership suite.

- [ ] **Step 4: 运行语法和静态扫描**

```bash
python3 -m py_compile scripts/*.py tests/*.py
rg -n 'pending_adjudication|correction_status|corr_candidates|merge-lenses|validate-lenses|docs/lenses|adjudications_path|locked_ids|lock_statuses|lock-segments|tm_locked|\[LOCKED\]' SKILL.md README.md README_ZH.md PM_GUIDE.html docs projects scripts tests
```

Expected: `py_compile` exit 0; `rg` exit 1 with no matches.

- [ ] **Step 5: 验证未触碰历史任务和用户 Excel**

Run: `git diff --name-only "$(git merge-base main HEAD)"..HEAD | rg '(^|/)outputs/|LOC_FILE-20260420'`

Expected: `rg` exit 1 with no output. 不对用户 Excel 或现有 job 目录执行任何生成或改写命令。

- [ ] **Step 6: 提交最终回归测试**

```bash
git add tests/test_corrected_ownership.py scripts/run_tests.py
git commit -m "test: lock corrected ownership and score parity"
```

- [ ] **Step 7: 独立整体审查后同步安装技能**

审查范围为 `git merge-base main HEAD..HEAD`，必须确认全部 Global Constraints 均满足，且无 Critical/Important 问题。审查通过后，执行：

```bash
rsync -a --delete --exclude='.git/' --exclude='.superpowers/' --exclude='__pycache__/' --exclude='*.pyc' ./ /Users/spellbook/.codex/skills/lqe-translator/
cd /Users/spellbook/.codex/skills/lqe-translator
python3 -m unittest -v tests.test_correction_builder tests.test_corrected_ownership tests.test_plain_language
python3 scripts/run_tests.py
```

Expected: both commands exit 0. 不复制 Git 元数据、工作记录或历史产物。

---

## 自检结果

- 规格覆盖：12 条验收用例分别落在 Task 1–7；四条合并路径都调用同一合成器。
- 类型一致：全计划只使用 `issues/edit/needs_confirmation/confirmed_rules/confirmed`；最终结果只使用 `errors/corrected`。
- 边界一致：检查模块不写 `corrected`，Python 程序不信任模型的可修改判断，报告可显示需要人工确认，建议译文文件只收安全修改。
- 步骤完整性：每个任务都给出测试、失败信号、实现边界、通过信号和提交范围。
