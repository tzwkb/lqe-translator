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
USER_DOCUMENTS = ("SKILL.md",)
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
EXPECTED_TERM_CONFIRMATION_CONTRACT = {
    "trigger": "terminology has no explicit confirmation field (confirmed/approved) OR has a status column but no status->confirmed/protection mapping supplied",
    "required_action": "ask_user_or_supply_mapping_before_initialization",
    "status_column_detection": "RULE-BASED, not enumerative: a column is a status column if its header CONTAINS the token 'status' or '状态' (case-insensitive, any position, regardless of prefixes/suffixes/brackets). This catches future renames/relocations automatically. If MULTIPLE columns match, the converter MUST SystemExit and require --status-col to disambiguate (it never guesses).",
    "fail_closed": "converter MUST SystemExit in EITHER case below; it must NEVER emit terms with confirmed silently defaulted to false: (a) a status column is detected but no confirmation decision was supplied — a confirmation decision is --approved-statuses (values / '*' / '') and --protected-statuses ALONE is NOT enough; (b) NO status column is detected and --no-status was NOT passed (the column may have been renamed/relocated). It must print the distinct detected/unmapped status values for audit.",
    "mapping_channels": [
        "converter arg: --approved-statuses 'Approved,合规审核通过'  (status values are compared CASE-INSENSITIVELY — a rule, not per-value casing)",
        "converter arg: --approved-statuses '*' to treat the whole glossary as confirmed (choice 1)",
        "converter arg: --approved-statuses '' (empty) to explicitly treat all as unconfirmed (choice 2)",
        "converter arg: --protected-statuses '<status>' to mark those senses protected (NOT a confirmation decision on its own)",
        "converter arg: --exclude-statuses '<status>' to additionally drop rejected terms entirely (not checked, not flagged). NOTE: status 'Denied' is ALWAYS excluded by default (case-insensitive) — no flag needed (standing rule: client-rejected terms never enter the glossary)",
        "converter arg: --status-col '<header>' to disambiguate when multiple status-keyword columns exist",
        "converter arg: --no-status to assert the glossary has NO confirmation info at all (required when no status column is detected)",
        "profile.term_status_map: {\"Approved\": \"confirmed\"}  (use for status->confirmed/protection; 'Denied' must not be mapped since it is unconditionally excluded)",
    ],
    "forbidden_defaults": ["all_confirmed", "all_unconfirmed", "infer_from_unmapped_status", "silently_proceed_when_status_column_undetected"],
    "choices_when_asking": [
        "treat_entire_glossary_as_confirmed",
        "treat_as_unconfirmed_reference",
        "provide_row_or_status_mapping",
    ],
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


def parse_term_confirmation_contract(content: str) -> dict:
    blocks = re.findall(
        r"<pre(?=[^>]*\bdata-lqe-term-confirmation-contract\b)[^>]*>(.*?)</pre>",
        content,
        re.DOTALL,
    )
    if len(blocks) != 1:
        raise AssertionError(
            "expected one visible data-lqe-term-confirmation-contract block, "
            f"found {len(blocks)}"
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
        cls.skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        cls.common = (ROOT / "references/check_modules/common.md").read_text(
            encoding="utf-8"
        )

    def test_skill_states_top_level_check_contract(self):
        self.assertIn(
            "固定接口为 `{id, issues:[{category,severity,comment,needs_confirmation,edit}]}`",
            self.skill,
        )

    def test_skill_confirmation_issue_has_null_edit(self):
        self.assertIn(
            "`needs_confirmation: true` 和 `edit: null`",
            self.skill,
        )

    def test_skill_assigns_full_suggested_text_to_program(self):
        self.assertIn("检查模块不得输出 corrected", self.skill)
        self.assertIn("`lqe_corrections.py` 验证局部修改", self.skill)

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

    def test_skill_requires_user_decision_when_term_confirmation_is_absent(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(
            parse_term_confirmation_contract(skill),
            EXPECTED_TERM_CONFIRMATION_CONTRACT,
        )
        self.assertIn("必须在初始化前询问用户", skill)
        self.assertIn("不得默认全部已确认，也不得默认全部未确认", skill)

    def test_skill_requires_escalation_when_subagents_are_blocked(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("流程要求 subagent", skill)
        self.assertIn("必须主动询问用户", skill)
        self.assertIn("不得静默回退", skill)

    def test_run_tests_t25_discovers_every_regression_suite(self):
        runner = load_test_runner()
        try:
            completed = SimpleNamespace(returncode=0, stdout="", stderr="")
            with mock.patch.object(
                runner.subprocess, "run", return_value=completed
            ) as run_mock:
                runner.t25()

            argv = run_mock.call_args.args[0]
            self.assertEqual(
                argv,
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests",
                    "-p",
                    "test_*.py",
                    "-v",
                ],
            )
            self.assertEqual(run_mock.call_args.kwargs["cwd"], ROOT)
            self.assertIn("every tests/test_*.py regression suite", runner.__doc__)
            self.assertEqual(
                runner.PASS,
                ["T25 all test_*.py suites discovered"],
            )
        finally:
            shutil.rmtree(runner.TMP, ignore_errors=True)

    def test_run_tests_t25_pattern_covers_all_test_modules_on_disk(self):
        runner = load_test_runner()
        try:
            completed = SimpleNamespace(returncode=0, stdout="", stderr="")
            with mock.patch.object(
                runner.subprocess, "run", return_value=completed
            ) as run_mock:
                runner.t25()
            argv = run_mock.call_args.args[0]
            pattern = argv[argv.index("-p") + 1]
            discovered = sorted(path.name for path in (ROOT / "tests").glob(pattern))
            self.assertIn("test_excel_diff_highlighting.py", discovered)
            self.assertIn("test_iteration_state.py", discovered)
            self.assertIn("test_terminology_read_contract.py", discovered)
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

    def test_skill_documents_sdlxliff_profile_rules(self):
        text = self.skill
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
            "处理方式、LQE Segment ID、LQE 错误序号、LQE AI 复核状态、"
            "LQE AI 编辑状态、LQE 检查来源、错误详情、Protected、"
            "Protection Evidence、LQE_Iter"
        )
        expected_export = "来源文件、TU ID、SDL Segment ID、原文、译文"
        for path in USER_DOCUMENTS:
            with self.subTest(path=path):
                content = (ROOT / path).read_text(encoding="utf-8")
                self.assertIn(expected_report, content)
                self.assertIn(expected_export, content)

    def test_skill_publishes_rich_diff_scope(self):
        for phrase in (
            "原译中删除或替换的内容显示为红色删除线",
            "建议译文中新增或替换的内容显示为红色字体",
            "corrected 文件不添加差异样式",
            "openpyxl>=3.1",
            'openpyxl>=3.1" regex',
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.skill)


if __name__ == "__main__":
    unittest.main()
