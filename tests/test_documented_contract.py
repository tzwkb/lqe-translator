import html
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
USER_DOCUMENTS = (
    "SKILL.md",
    "README.md",
    "README_ZH.md",
    "PM_GUIDE.html",
    "projects/README.md",
)
EXPECTED_SCOPE_CONTRACT = {
    "mode_flag": "--no-terminology",
    "standard": {
        "required": ["terminology", "accuracy", "grammar", "naturalness"],
        "optional": ["proper_names"],
    },
    "no-terminology": {
        "required": ["precheck_review", "accuracy", "grammar", "naturalness"],
        "optional": [],
        "disabled": ["terminology", "proper_names", "term_audit"],
    },
    "scope_artifact": {
        "path": "scope.json",
        "state_field": "state.check_scope",
        "relation": "same resolved scope",
    },
    "kept_checks": ["file-wide consistency", "Markup", "numeric checks"],
}


def scope_contract_blocks(content: str) -> list[str]:
    return re.findall(
        r"<pre(?=[^>]*\bdata-lqe-scope-contract\b)[^>]*>(.*?)</pre>",
        content,
        re.DOTALL,
    )


def parse_scope_contract(content: str) -> dict:
    blocks = scope_contract_blocks(content)
    if len(blocks) != 1:
        raise AssertionError(
            f"expected one visible data-lqe-scope-contract block, found {len(blocks)}"
        )
    return json.loads(html.unescape(blocks[0]))


def load_test_runner():
    path = ROOT / "scripts/run_tests.py"
    spec = importlib.util.spec_from_file_location("lqe_contract_test_runner", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot import test runner: {path}")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


class DocumentedContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pm_guide = (ROOT / "PM_GUIDE.html").read_text(encoding="utf-8")
        cls.common = (ROOT / "docs/check_modules/common.md").read_text(
            encoding="utf-8"
        )

    def test_pm_guide_states_top_level_check_contract(self):
        self.assertIn(
            "子任务顶层只输出 <code>{id, issues}</code>", self.pm_guide
        )

    def test_pm_guide_confirmation_issue_has_null_edit(self):
        self.assertIn(
            "<code>needs_confirmation: true</code> 和 <code>edit: null</code>",
            self.pm_guide,
        )

    def test_pm_guide_assigns_full_suggested_text_to_program(self):
        self.assertIn("完整建议译文只由程序生成", self.pm_guide)

    def test_common_marks_proper_names_optional(self):
        self.assertIn("`proper_names` 是可选模块", self.common)

    def test_common_preserves_empty_issue_entry_for_every_id(self):
        self.assertIn(
            '每个 id 无问题时也输出 `{"id": 0, "issues": []}`', self.common
        )

    def test_common_documents_both_module_sets(self):
        self.assertIn(
            "标准模式要求 `terminology`、`accuracy`、`grammar`、`naturalness` 四个模块",
            self.common,
        )
        self.assertIn(
            "无术语模式要求 `precheck_review`、`accuracy`、`grammar`、`naturalness` 四个模块",
            self.common,
        )
        self.assertIn("当前模式和必需模块以 `state.check_scope` 为准", self.common)

    def test_user_documents_publish_complete_scope_contract(self):
        for path in USER_DOCUMENTS:
            with self.subTest(path=path):
                content = (ROOT / path).read_text(encoding="utf-8")
                self.assertEqual(
                    parse_scope_contract(content), EXPECTED_SCOPE_CONTRACT
                )

    def test_user_documents_publish_one_scope_contract(self):
        for path in USER_DOCUMENTS:
            with self.subTest(path=path):
                content = (ROOT / path).read_text(encoding="utf-8")
                self.assertEqual(len(scope_contract_blocks(content)), 1)

    def test_run_tests_t25_invokes_no_terminology_suite(self):
        runner = load_test_runner()
        try:
            completed = SimpleNamespace(returncode=0, stdout="", stderr="")
            with mock.patch.object(
                runner.subprocess, "run", return_value=completed
            ) as run_mock:
                runner.t25()

            argv = run_mock.call_args.args[0]
            self.assertEqual(argv[:4], [sys.executable, "-m", "unittest", "-v"])
            self.assertEqual(argv.count("tests.test_no_terminology_mode"), 1)
            self.assertEqual(argv.count("tests.test_sdlxliff_input"), 1)
            self.assertEqual(run_mock.call_args.kwargs["cwd"], ROOT)
        finally:
            shutil.rmtree(runner.TMP, ignore_errors=True)

    def test_skill_documents_sdlxliff_input_and_boundaries(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "SDLXLIFF 1.2",
            "--input-format sdlxliff",
            "--protect-exact-tm",
            "source_manifest.json",
            "tm_candidates.json",
            "SOURCE_LOCKED",
            "XLIFF 2.0",
            "第一版不回写 SDLXLIFF XML",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)

    def test_projects_readme_documents_sdlxliff_rules(self):
        text = (ROOT / "projects/README.md").read_text(encoding="utf-8")
        for phrase in (
            '"sdlxliff"',
            '"tm_protection"',
            '"content_type_rules"',
            '"exclude_rules"',
            "candidate-only",
            "protect-exact-source-and-target",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_sdlxliff_report_and_export_columns_are_documented(self):
        expected_report = (
            "来源文件、TU ID、SDL Segment ID、原文、原译、建议译文、"
            "处理方式、错误详情、LQE_Iter、Protected、Protection Evidence"
        )
        expected_export = "来源文件、TU ID、SDL Segment ID、原文、译文"
        for path in ("SKILL.md", "README_ZH.md", "PM_GUIDE.html"):
            with self.subTest(path=path):
                content = (ROOT / path).read_text(encoding="utf-8")
                self.assertIn(expected_report, content)
                self.assertIn(expected_export, content)

    def test_pm_guide_separates_tabular_and_sdlxliff_delivery_checks(self):
        self.assertIn(
            "CSV/XLSX 表格任务：工作表、空行、列顺序和格式保持",
            self.pm_guide,
        )
        self.assertIn(
            "SDLXLIFF 任务：corrected Excel 为新建固定 5 列表",
            self.pm_guide,
        )


if __name__ == "__main__":
    unittest.main()
