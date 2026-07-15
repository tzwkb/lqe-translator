# LQE Excel 修改差异标红 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在所有新生成的 `*_lqe.xlsx` 报告中，对原译与建议译文的实际差异使用红色 Excel 富文本，同时保持 corrected 交付文件不变。

**Architecture:** 新建 `scripts/lqe_excel_diff.py`，以 `SequenceMatcher(autojunk=False)` 将完整原译和建议译文转换成一对 Excel 富文本。`lqe_io.py` 负责单任务两张报告表的接入，`aggregate_sheets.py` 负责聚合报告接入；corrected 导出路径不调用该模块。

**Tech Stack:** Python 3.14、标准库 `difflib/unittest/tempfile/pathlib`、`regex` 的 Unicode `\X` 字素边界、`openpyxl>=3.1` 的 `CellRichText/TextBlock/InlineFont`。

## Global Constraints

- 仅修改未来生成的 `*_lqe.xlsx`；不自动重写历史报告。
- 原译删除/替换部分使用 `#FF0000` 红色删除线；建议译文新增/替换部分使用 `#FF0000` 红色字体。
- 未改变文本、无建议译文、受保护段、仅需人工确认且无安全修改的段保持普通文本。
- `*_corrected.xlsx`、CSV、TSV 和原始输入文件不得增加差异样式。
- 报告列名、顺序、评分、处理方式、保护逻辑和现有行底色不得改变。
- 最低依赖为 `openpyxl>=3.1`。
- `/Users/spellbook/.codex/skills/lqe-translator` 不是 Git 仓库；不得擅自执行 `git init`。每个任务以测试通过和明确的文件清单作为检查点，不创建虚假提交。

---

## File Structure

- Create: `scripts/lqe_excel_diff.py` — 唯一负责文本差异计算与 Excel 富文本构建。
- Create: `tests/test_excel_diff_highlighting.py` — 富文本算法、单任务报告和聚合报告的专项回归测试。
- Modify: `scripts/lqe_io.py` — 在 `LQA Scorecard` 和 `LQE Results` 写入富文本差异。
- Modify: `scripts/aggregate_sheets.py` — 在父级聚合 LQE 报告中重建富文本差异。
- Modify: `scripts/run_tests.py` — 将新专项测试加入 T25 全量入口。
- Modify: `tests/test_documented_contract.py` — 锁定用户文档中的标红范围和 corrected 不变合同。
- Modify: `SKILL.md`, `README.md`, `README_ZH.md`, `PM_GUIDE.html` — 说明报告富文本和 `openpyxl>=3.1` 依赖。

---

### Task 1: 富文本差异核心

**Files:**
- Create: `scripts/lqe_excel_diff.py`
- Create: `tests/test_excel_diff_highlighting.py`

**Interfaces:**
- Consumes: `original: str`, `suggested: str`。
- Produces: `build_rich_diff(original: str, suggested: str) -> tuple[str | CellRichText, str | CellRichText]`。

- [ ] **Step 1: 写入算法失败测试**

在 `tests/test_excel_diff_highlighting.py` 写入导入、辅助函数和以下测试：

```python
from pathlib import Path
import sys
import tempfile
import unittest

import openpyxl
from openpyxl.cell.rich_text import CellRichText, TextBlock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from lqe_excel_diff import build_rich_diff


def changed_blocks(value):
    return [run for run in value if isinstance(run, TextBlock)]


class RichDiffUnitTests(unittest.TestCase):
    def assert_red(self, block, *, strike):
        self.assertEqual(block.font.color.type, "rgb")
        self.assertEqual(block.font.color.rgb, "FFFF0000")
        self.assertEqual(bool(block.font.strike), strike)

    def test_replace_marks_both_sides(self):
        original, suggested = build_rich_diff("Save old file", "Save new file")
        self.assertIsInstance(original, CellRichText)
        self.assertIsInstance(suggested, CellRichText)
        self.assertEqual(str(original), "Save old file")
        self.assertEqual(str(suggested), "Save new file")
        self.assertEqual([block.text for block in changed_blocks(original)], ["old"])
        self.assertEqual([block.text for block in changed_blocks(suggested)], ["new"])
        self.assert_red(changed_blocks(original)[0], strike=True)
        self.assert_red(changed_blocks(suggested)[0], strike=False)

    def test_insert_marks_only_suggestion(self):
        original, suggested = build_rich_diff("Save file", "Save new file")
        self.assertEqual(original, "Save file")
        self.assertEqual([block.text for block in changed_blocks(suggested)], ["new "])
        self.assert_red(changed_blocks(suggested)[0], strike=False)

    def test_delete_marks_only_original(self):
        original, suggested = build_rich_diff("Save old file", "Save file")
        self.assertEqual([block.text for block in changed_blocks(original)], ["old "])
        self.assertEqual(suggested, "Save file")
        self.assert_red(changed_blocks(original)[0], strike=True)

    def test_equal_text_stays_plain(self):
        self.assertEqual(build_rich_diff("same", "same"), ("same", "same"))

    def test_multilingual_and_repeated_text_preserves_exact_strings(self):
        cases = [
            ("保存旧文件", "保存新文件"),
            ("บันทึกไฟล์เก่า", "บันทึกไฟล์ใหม่"),
            ("aaaa old aaaa old", "aaaa new aaaa old"),
        ]
        for original_text, suggested_text in cases:
            with self.subTest(original=original_text):
                original, suggested = build_rich_diff(original_text, suggested_text)
                self.assertEqual(str(original), original_text)
                self.assertEqual(str(suggested), suggested_text)
                self.assertTrue(changed_blocks(original))
                self.assertTrue(changed_blocks(suggested))

    def test_formula_like_rich_text_round_trips_as_text(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "formula.xlsx"
            original, suggested = build_rich_diff("=SUM(1,2)", "=SUM(1,3)")
            workbook = openpyxl.Workbook()
            workbook.active["A1"] = original
            workbook.active["B1"] = suggested
            workbook.save(path)
            workbook.close()

            loaded = openpyxl.load_workbook(path, rich_text=True, data_only=False)
            try:
                self.assertEqual(str(loaded.active["A1"].value), "=SUM(1,2)")
                self.assertEqual(str(loaded.active["B1"].value), "=SUM(1,3)")
                self.assertEqual(loaded.active["A1"].data_type, "s")
                self.assertEqual(loaded.active["B1"].data_type, "s")
            finally:
                loaded.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试并确认正确失败**

Run:

```bash
python3 -m unittest -v tests.test_excel_diff_highlighting.RichDiffUnitTests
```

Expected: FAIL with `ModuleNotFoundError: No module named 'lqe_excel_diff'`。

- [ ] **Step 3: 实现最小富文本模块**

创建 `scripts/lqe_excel_diff.py`：

```python
"""Build paired Excel rich text for original and suggested translations."""

from __future__ import annotations

from difflib import SequenceMatcher

from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont


_RED = "FFFF0000"


def _append(runs: list[tuple[str, bool]], text: str, changed: bool) -> None:
    if not text:
        return
    if runs and runs[-1][1] == changed:
        previous, _ = runs[-1]
        runs[-1] = (previous + text, changed)
    else:
        runs.append((text, changed))


def _to_excel_text(runs: list[tuple[str, bool]], *, strike: bool):
    if not any(changed for _, changed in runs):
        return "".join(text for text, _ in runs)
    values = []
    for text, changed in runs:
        if changed:
            values.append(
                TextBlock(InlineFont(color=_RED, strike=strike or None), text)
            )
        else:
            values.append(text)
    return CellRichText(values)


def build_rich_diff(
    original: str,
    suggested: str,
) -> tuple[str | CellRichText, str | CellRichText]:
    original_runs: list[tuple[str, bool]] = []
    suggested_runs: list[tuple[str, bool]] = []
    matcher = SequenceMatcher(None, original, suggested, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"equal", "delete", "replace"}:
            _append(original_runs, original[i1:i2], tag != "equal")
        if tag in {"equal", "insert", "replace"}:
            _append(suggested_runs, suggested[j1:j2], tag != "equal")
    return (
        _to_excel_text(original_runs, strike=True),
        _to_excel_text(suggested_runs, strike=False),
    )
```

- [ ] **Step 4: 运行专项测试并确认通过**

Run:

```bash
python3 -m unittest -v tests.test_excel_diff_highlighting.RichDiffUnitTests
```

Expected: 6 tests, `OK`。

- [ ] **Step 5: 记录文件检查点**

Run:

```bash
python3 -m py_compile scripts/lqe_excel_diff.py tests/test_excel_diff_highlighting.py
```

Expected: exit 0。记录本任务新增 `scripts/lqe_excel_diff.py` 与 `tests/test_excel_diff_highlighting.py`；不初始化 Git 仓库。

---

### Task 2: 单任务报告接入

**Files:**
- Modify: `scripts/lqe_io.py:23-25, 1819-1847, 1873-1922`
- Modify: `tests/test_excel_diff_highlighting.py`

**Interfaces:**
- Consumes: `build_rich_diff(original: str, suggested: str)` from Task 1。
- Produces: `LQA Scorecard` 和 `LQE Results` 中的双列富文本差异。

- [ ] **Step 1: 写入单任务报告失败测试**

在 `tests/test_excel_diff_highlighting.py` 增加：

```python
import lqe_io


def issue(*, protected=False, needs_confirmation=False):
    value = {
        "category": "Grammar",
        "severity": "Minor",
        "comment": "Replace the outdated word.",
        "needs_confirmation": needs_confirmation,
        "edit": None,
    }
    if protected:
        value["protected"] = True
    return value


class RichDiffReportTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def build_report(self):
        output = self.root / "sample_lqe.xlsx"
        state = {
            "input_path": str(self.root / "sample.xlsx"),
            "headers": ["原文", "译文"],
            "rows_raw": [
                ["Source 0", "Save old file"],
                ["Source 1", "Keep text"],
                ["Source 2", "Protected text"],
            ],
            "target_col": 1,
            "segments": [
                {"id": 0, "source": "Source 0", "target": "Save old file", "kind": "desc"},
                {"id": 1, "source": "Source 1", "target": "Keep text", "kind": "desc"},
                {"id": 2, "source": "Source 2", "target": "Protected text", "kind": "desc"},
            ],
            "wordcount": 3,
        }
        protected_issue = issue(protected=True)
        history = [{
            "iteration": 0,
            "errors": [
                {"id": 0, "errors": [issue()], "corrected": "Save new file"},
                {"id": 1, "errors": [issue(needs_confirmation=True)], "corrected": None},
                {"id": 2, "errors": [protected_issue], "corrected": None},
            ],
        }]
        lqe_io._build_xlsx(state, history, 99, 98, output)
        return output

    def test_both_report_sheets_render_paired_rich_diffs(self):
        output = self.build_report()
        workbook = openpyxl.load_workbook(output, rich_text=True)
        try:
            scorecard = workbook["LQA Scorecard"]
            header_row = next(
                row for row in range(1, scorecard.max_row + 1)
                if scorecard.cell(row=row, column=1).value == "File name"
            )
            score_original = scorecard.cell(header_row + 1, 4).value
            score_suggested = scorecard.cell(header_row + 1, 5).value
            self.assertEqual([block.text for block in changed_blocks(score_original)], ["old"])
            self.assertEqual([block.text for block in changed_blocks(score_suggested)], ["new"])

            results = workbook["LQE Results"]
            headers = [cell.value for cell in results[1]]
            original_col = headers.index("原译") + 1
            suggested_col = headers.index("建议译文") + 1
            result_original = results.cell(2, original_col).value
            result_suggested = results.cell(2, suggested_col).value
            self.assertEqual([block.text for block in changed_blocks(result_original)], ["old"])
            self.assertEqual([block.text for block in changed_blocks(result_suggested)], ["new"])
            self.assertEqual(results.cell(2, original_col).fill.fgColor.rgb, "00FCE5CD")
            self.assertEqual(results.cell(2, suggested_col).fill.fgColor.rgb, "00FCE5CD")
            self.assertIsInstance(results.cell(3, original_col).value, str)
            self.assertNotIsInstance(results.cell(3, suggested_col).value, CellRichText)
            self.assertIsInstance(results.cell(4, original_col).value, str)
            self.assertNotIsInstance(results.cell(4, suggested_col).value, CellRichText)
        finally:
            workbook.close()

    def test_normal_load_keeps_complete_plain_values(self):
        output = self.build_report()
        workbook = openpyxl.load_workbook(output, rich_text=False, data_only=False)
        try:
            results = workbook["LQE Results"]
            headers = [cell.value for cell in results[1]]
            self.assertEqual(results.cell(2, headers.index("原译") + 1).value, "Save old file")
            self.assertEqual(results.cell(2, headers.index("建议译文") + 1).value, "Save new file")
        finally:
            workbook.close()
```

- [ ] **Step 2: 运行报告测试并确认正确失败**

Run:

```bash
python3 -m unittest -v tests.test_excel_diff_highlighting.RichDiffReportTests
```

Expected: FAIL because report cells contain plain `str` values and `changed_blocks()` cannot find red runs。

- [ ] **Step 3: 接入 `LQA Scorecard`**

在 `scripts/lqe_io.py` 导入：

```python
from lqe_excel_diff import build_rich_diff
```

在 `for dr in detail_rows:` 循环开始处计算：

```python
        rich_pair = (
            build_rich_diff(dr["original"], dr["corrected"])
            if isinstance(dr["corrected"], str) and dr["corrected"]
            else None
        )
```

在写单元格前仅替换第 4、5 列的显示值：

```python
            if rich_pair and col == 4:
                val = rich_pair[0]
            elif rich_pair and col == 5:
                val = rich_pair[1]
            c = ws.cell(row=cur_row, column=col)
            _set_excel_text(c, val)
```

- [ ] **Step 4: 接入 `LQE Results`**

在计算 `suggestion` 后增加：

```python
        rich_pair = (
            build_rich_diff(seg["target"], suggestion)
            if isinstance(suggestion, str) and suggestion
            else None
        )
        suggestion_column = len(report_headers) + 1
```

在 `for ci, val in enumerate(row_data, start=1):` 中写入前增加：

```python
            if rich_pair and ci == target_index + 1:
                val = rich_pair[0]
            elif rich_pair and ci == suggestion_column:
                val = rich_pair[1]
```

继续使用 `_set_excel_text()`，不得更改行底色和对齐方式。

- [ ] **Step 5: 运行专项及既有输出测试**

Run:

```bash
python3 -m unittest -v \
  tests.test_excel_diff_highlighting.RichDiffReportTests \
  tests.test_corrected_ownership.CorrectedOwnershipOutputTests \
  tests.test_sdlxliff_input.SDLXLIFFOutputTests
```

Expected: all tests `OK`。现有普通加载值、公式样字符串、SDL 固定列及 corrected 输出断言不变。

- [ ] **Step 6: 记录文件检查点**

Run:

```bash
python3 -m py_compile scripts/lqe_io.py tests/test_excel_diff_highlighting.py
```

Expected: exit 0。记录本任务修改 `scripts/lqe_io.py` 与 `tests/test_excel_diff_highlighting.py`；不初始化 Git 仓库。

---

### Task 3: 多工作表聚合报告接入

**Files:**
- Modify: `scripts/aggregate_sheets.py:18-24, 184-194`
- Modify: `tests/test_excel_diff_highlighting.py`

**Interfaces:**
- Consumes: `build_rich_diff(original: str, suggested: str)` from Task 1。
- Produces: 父级 `*_lqe.xlsx` 中每个 `<sheet> Results` 的双列富文本；父级 corrected 工作簿保持原样。

- [ ] **Step 1: 写入聚合失败测试**

在 `tests/test_excel_diff_highlighting.py` 增加：

```python
import json
import subprocess


class RichDiffAggregateTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_aggregate_report_rebuilds_diff_but_corrected_stays_plain(self):
        job = self.root / "multi"
        child = job / "Sheet1"
        child.mkdir(parents=True)
        source = self.root / "source.xlsx"
        workbook = openpyxl.Workbook()
        workbook.active.title = "Sheet1"
        workbook.active.append(["Source", "Target"])
        workbook.active.append(["Save", "Save old file"])
        workbook.save(source)
        workbook.close()

        state = {
            "input_path": str(source),
            "target_col": 1,
            "headers": ["Source", "Target"],
            "wordcount": 3,
            "segments": [{
                "id": 0,
                "row_index": 0,
                "source": "Save",
                "target": "Save old file",
                "kind": "desc",
                "term_hits": [],
                "protected_texts": [],
            }],
        }
        errors = [{
            "id": 0,
            "errors": [{
                "category": "Grammar",
                "severity": "Minor",
                "comment": "Replace the outdated word.",
                "needs_confirmation": False,
                "edit": {
                    "from": "old",
                    "to": "new",
                    "start": 5,
                    "end": 8,
                    "evidence": None,
                },
            }],
            "corrected": "Save new file",
        }]
        (child / "state.json").write_text(json.dumps(state), encoding="utf-8")
        (child / "errors.json").write_text(json.dumps(errors), encoding="utf-8")

        child_report = openpyxl.Workbook()
        child_report.active.title = "LQE Results"
        child_report.active.append(["原译", "建议译文"])
        child_report.active.append(["Save old file", "Save new file"])
        child_report.save(child / "Sheet1_lqe.xlsx")
        child_report.close()

        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "aggregate_sheets.py"), "--job", str(job)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        report = openpyxl.load_workbook(job / "multi_lqe.xlsx", rich_text=True)
        try:
            sheet = report["Sheet1 Results"]
            self.assertEqual([block.text for block in changed_blocks(sheet["A2"].value)], ["old"])
            self.assertEqual([block.text for block in changed_blocks(sheet["B2"].value)], ["new"])
        finally:
            report.close()

        corrected = openpyxl.load_workbook(job / "multi_corrected.xlsx", rich_text=True)
        try:
            self.assertEqual(corrected["Sheet1"]["B2"].value, "Save new file")
            self.assertIsInstance(corrected["Sheet1"]["B2"].value, str)
        finally:
            corrected.close()
```

- [ ] **Step 2: 运行聚合测试并确认正确失败**

Run:

```bash
python3 -m unittest -v tests.test_excel_diff_highlighting.RichDiffAggregateTests
```

Expected: FAIL because aggregate report copies plain values without rich text。

- [ ] **Step 3: 实现聚合报告富文本重建**

在 `scripts/aggregate_sheets.py` 导入：

```python
from lqe_excel_diff import build_rich_diff  # noqa: E402
```

在复制每个 `LQE Results` 后增加：

```python
            headers = [cell.value for cell in ws2[1]]
            if "原译" in headers and "建议译文" in headers:
                original_column = headers.index("原译") + 1
                suggested_column = headers.index("建议译文") + 1
                for row_number in range(2, ws2.max_row + 1):
                    original_cell = ws2.cell(row_number, original_column)
                    suggested_cell = ws2.cell(row_number, suggested_column)
                    original_text = original_cell.value
                    suggested_text = suggested_cell.value
                    if isinstance(original_text, str) and isinstance(suggested_text, str) and suggested_text:
                        original_cell.value, suggested_cell.value = build_rich_diff(
                            original_text,
                            suggested_text,
                        )
```

不得修改此前生成 `corr_out` 的代码。

- [ ] **Step 4: 运行聚合及既有结构测试**

Run:

```bash
python3 -m unittest -v \
  tests.test_excel_diff_highlighting.RichDiffAggregateTests \
  tests.test_corrected_ownership.CorrectedOwnershipPipelineTests
```

Expected: all tests `OK`，包括源工作簿样式、公式、合并单元格和 corrected 结构断言。

- [ ] **Step 5: 记录文件检查点**

Run:

```bash
python3 -m py_compile scripts/aggregate_sheets.py tests/test_excel_diff_highlighting.py
```

Expected: exit 0。记录本任务修改 `scripts/aggregate_sheets.py` 与 `tests/test_excel_diff_highlighting.py`；不初始化 Git 仓库。

---

### Task 4: 文档合同、依赖和全量验证

**Files:**
- Modify: `tests/test_documented_contract.py`
- Modify: `scripts/run_tests.py`
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `README_ZH.md`
- Modify: `PM_GUIDE.html`

**Interfaces:**
- Consumes: Task 1–3 的最终行为。
- Produces: 用户可见标红合同、`openpyxl>=3.1` 依赖合同和标准全量回归入口。

- [ ] **Step 1: 写入文档与测试入口失败测试**

在 `tests/test_documented_contract.py` 增加：

```python
    def test_user_documents_publish_rich_diff_scope(self):
        contracts = {
            "SKILL.md": (
                "原译中删除或替换的内容显示为红色删除线",
                "建议译文中新增或替换的内容显示为红色字体",
                "corrected 文件不添加差异样式",
                "openpyxl>=3.1",
            ),
            "README_ZH.md": (
                "原译中删除或替换的内容显示为红色删除线",
                "建议译文中新增或替换的内容显示为红色字体",
                "corrected 文件不添加差异样式",
                "openpyxl>=3.1",
            ),
            "README.md": (
                "removed or replaced text in the original translation uses red strikethrough",
                "inserted or replaced text in the suggested translation uses red font",
                "Corrected files do not receive diff styling",
                "openpyxl>=3.1",
            ),
            "PM_GUIDE.html": (
                "原译中删除或替换的内容显示为红色删除线",
                "建议译文中新增或替换的内容显示为红色字体",
                "corrected 文件不添加差异样式",
                "openpyxl&gt;=3.1",
            ),
        }
        for path, phrases in contracts.items():
            content = (ROOT / path).read_text(encoding="utf-8")
            for phrase in phrases:
                with self.subTest(path=path, phrase=phrase):
                    self.assertIn(phrase, content)

    def test_run_tests_t25_invokes_rich_diff_suite(self):
        runner = load_test_runner()
        try:
            completed = SimpleNamespace(returncode=0, stdout="", stderr="")
            with mock.patch.object(runner.subprocess, "run", return_value=completed) as run_mock:
                runner.t25()
            argv = run_mock.call_args.args[0]
            self.assertEqual(argv.count("tests.test_excel_diff_highlighting"), 1)
        finally:
            shutil.rmtree(runner.TMP, ignore_errors=True)
```

- [ ] **Step 2: 运行合同测试并确认正确失败**

Run:

```bash
python3 -m unittest -v \
  tests.test_documented_contract.DocumentedContractTests.test_user_documents_publish_rich_diff_scope \
  tests.test_documented_contract.DocumentedContractTests.test_run_tests_t25_invokes_rich_diff_suite
```

Expected: FAIL because documents and T25 do not yet mention the new contract。

- [ ] **Step 3: 更新测试入口**

在 `scripts/run_tests.py::t25()` 的 unittest 参数中加入：

```python
            "tests.test_excel_diff_highlighting",
```

同步把文件顶部说明和 T25 检查标签改为包含 `rich-diff`，并更新现有 `test_run_tests_t25_invokes_required_regression_suites` 对标签的精确断言。

- [ ] **Step 4: 更新安装依赖和报告合同**

将四份用户文档中的安装命令统一为：

```text
pip install "openpyxl>=3.1" requests python-docx -q
```

在 `SKILL.md`、`README_ZH.md` 和 `PM_GUIDE.html` 的报告说明附近加入以下完整合同：

```text
LQE 报告使用富文本显示修改差异：原译中删除或替换的内容显示为红色删除线，建议译文中新增或替换的内容显示为红色字体。corrected 文件不添加差异样式。
```

在 `README.md` 对应位置加入：

```text
LQE reports use rich text for translation diffs: removed or replaced text in the original translation uses red strikethrough, and inserted or replaced text in the suggested translation uses red font. Corrected files do not receive diff styling.
```

确保 PM HTML 中依赖字符串编码为 `openpyxl&gt;=3.1`，可见文本与测试一致。

- [ ] **Step 5: 运行文档合同和专项测试**

Run:

```bash
python3 -m unittest -v \
  tests.test_documented_contract \
  tests.test_excel_diff_highlighting
```

Expected: all tests `OK`。

- [ ] **Step 6: 运行完整 skill 验证清单**

Run:

```bash
python3 -m unittest -v tests.test_correction_builder
python3 -m unittest -v tests.test_corrected_ownership
python3 -m unittest -v tests.test_no_terminology_mode
python3 -m unittest -v tests.test_sdlxliff_input
python3 -m unittest -v tests.test_documented_contract
python3 -m unittest -v tests.test_plain_language
python3 -m unittest -v tests.test_excel_diff_highlighting
python3 scripts/run_tests.py
```

Expected: every command exits 0; the final runner reports all checks green with no failed check names。

- [ ] **Step 7: 实际 OOXML 冒烟检查**

建立固定路径的最小夹具，检查报告 XML 中包含富文本运行及红色字体属性，同时 corrected 文件中没有新增红色富文本运行：

```bash
rm -rf /tmp/lqe-rich-diff-smoke
mkdir -p /tmp/lqe-rich-diff-smoke
python3 - <<'PY'
import sys
from pathlib import Path

import openpyxl

root = Path("/Users/spellbook/.codex/skills/lqe-translator")
sys.path.insert(0, str(root / "scripts"))
from lqe_excel_diff import build_rich_diff

out = Path("/tmp/lqe-rich-diff-smoke")
original, suggested = build_rich_diff("Save old file", "Save new file")
report = openpyxl.Workbook()
report.active["A1"] = original
report.active["B1"] = suggested
report.save(out / "report.xlsx")
report.close()
corrected = openpyxl.Workbook()
corrected.active["A1"] = "Save new file"
corrected.save(out / "corrected.xlsx")
corrected.close()
PY
unzip -p /tmp/lqe-rich-diff-smoke/report.xlsx xl/worksheets/sheet1.xml | rg '<rPr>.*<color rgb="FFFF0000"'
if unzip -p /tmp/lqe-rich-diff-smoke/corrected.xlsx xl/worksheets/sheet1.xml | rg -q '<rPr>.*<color rgb="FFFF0000"'; then exit 1; fi
rm -rf /tmp/lqe-rich-diff-smoke
```

Expected: 第一条命令至少匹配一次；第二条命令无匹配。

- [ ] **Step 8: 记录最终文件检查点**

Run:

```bash
git -C /Users/spellbook/.codex/skills/lqe-translator rev-parse --show-toplevel
```

Expected: exit non-zero with `not a git repository`。不得初始化仓库；最终交付列出所有新增和修改文件及完整验证结果。
