import json
from pathlib import Path
import sys
import tempfile
import unittest

import openpyxl


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from lqe_checks import run_pre_check
from lqe_chunk import _mark_ai_reviewed
from lqe_corrections import CheckFormatError, normalize_check_entries
from lqe_engine import build_check_scope
from lqe_io import _build_xlsx
from lqe_terms import parse_terminology_comment, terminology_issue_fields


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class TerminologyReportMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_precheck_emits_full_structured_term_with_apostrophe(self):
        state_path = self.root / "state.json"
        output_path = self.root / "errors_precheck.json"
        write_json(
            state_path,
            {
                "source_lang": "zh",
                "target_lang": "en",
                "check_scope": build_check_scope(False, "test"),
                "segments": [
                    {
                        "id": 0,
                        "source": "查看督管案台",
                        "target": "Check the control desk",
                    }
                ],
                "terminology": [
                    {
                        "source": "督管案台",
                        "target": "Supervisor's Counter",
                        "confirmed": True,
                        "protected": False,
                    }
                ],
            },
        )

        run_pre_check(state_path, output_path)

        entries = json.loads(output_path.read_text(encoding="utf-8"))
        issue = next(
            issue
            for issue in entries[0]["issues"]
            if issue["category"] == "Terminology"
        )
        self.assertEqual(issue["term_source"], "督管案台")
        self.assertEqual(issue["expected_targets"], ["Supervisor's Counter"])
        normalized = normalize_check_entries(entries, label="precheck")
        self.assertEqual(
            normalized[0]["issues"][0]["expected_targets"],
            ["Supervisor's Counter"],
        )

    def test_legacy_comment_parser_does_not_treat_apostrophe_as_closing_quote(self):
        cases = [
            (
                "'督管案台' → expected 'Supervisor's Counter'",
                ["Supervisor's Counter"],
            ),
            (
                "'百佬会' → expected 'Masters' Assembly'[TB:New]",
                ["Masters' Assembly"],
            ),
            (
                "'设施' → expected "
                "'Captain O'Brien's Counter (East/West), Mk. II!'",
                ["Captain O'Brien's Counter (East/West), Mk. II!"],
            ),
            (
                "'称号' → expected 'King's Counter'[TB:New] or "
                "'Master's Desk'(UI)[TB:Approved]",
                ["King's Counter", "Master's Desk"],
            ),
        ]
        for comment, expected in cases:
            with self.subTest(comment=comment):
                parsed = parse_terminology_comment(comment)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed["expected_targets"], expected)

    def test_structured_fields_override_legacy_comment_parsing(self):
        parsed = terminology_issue_fields(
            {
                "category": "Terminology",
                "comment": "'督管案台' → expected 'Wrong'",
                "term_source": "督管案台",
                "expected_targets": ["Supervisor's Counter"],
            }
        )
        self.assertEqual(parsed["expected_targets"], ["Supervisor's Counter"])

    def test_issue_contract_rejects_partial_term_metadata(self):
        entries = [
            {
                "id": 0,
                "issues": [
                    {
                        "category": "Terminology",
                        "severity": "Major",
                        "comment": "Mismatch",
                        "term_source": "督管案台",
                        "needs_confirmation": True,
                        "edit": None,
                    }
                ],
            }
        ]
        with self.assertRaisesRegex(
            CheckFormatError,
            "term_source and expected_targets must be provided together",
        ):
            normalize_check_entries(entries, label="precheck")

    def test_ai_review_preserves_machine_term_metadata(self):
        original = {
            "category": "Terminology",
            "severity": "Major",
            "comment": "'督管案台' → expected 'Supervisor's Counter'",
            "term_source": "督管案台",
            "expected_targets": ["Supervisor's Counter"],
            "needs_confirmation": True,
            "edit": None,
            "precheck_ref": "precheck:0:test",
        }
        reviewed = {
            "category": "Terminology",
            "severity": "Major",
            "comment": "Confirmed terminology mismatch.",
            "needs_confirmation": True,
            "edit": None,
            "precheck_ref": "precheck:0:test",
        }

        result = _mark_ai_reviewed(reviewed, "terminology", 0, [original])

        self.assertEqual(result["term_source"], "督管案台")
        self.assertEqual(result["expected_targets"], ["Supervisor's Counter"])

    def test_report_hidden_term_column_preserves_full_legacy_value(self):
        output = self.root / "term-report_lqe.xlsx"
        state = {
            "input_path": str(self.root / "term-report.xlsx"),
            "headers": ["原文", "译文"],
            "rows_raw": [["查看督管案台", "Check the control desk"]],
            "source_col": 0,
            "target_col": 1,
            "source_lang": "zh",
            "target_lang": "en",
            "check_scope": build_check_scope(False, "test"),
            "segments": [
                {
                    "id": 0,
                    "source": "查看督管案台",
                    "target": "Check the control desk",
                    "kind": "desc",
                }
            ],
            "wordcount": 4,
        }
        issue = {
            "category": "Terminology",
            "severity": "Major",
            "comment": "'督管案台' → expected 'Supervisor's Counter'",
            "needs_confirmation": True,
            "edit": None,
        }
        history = [
            {
                "iteration": 0,
                "errors": [{"id": 0, "errors": [issue], "corrected": None}],
            }
        ]

        _build_xlsx(state, history, 99, 98, output, announce=False)

        workbook = openpyxl.load_workbook(output, data_only=True)
        try:
            results = workbook["LQE Results"]
            headers = [cell.value for cell in results[1]]
            source_column = headers.index("术语原文（结构化）") + 1
            target_column = headers.index("术语库译文（结构化）") + 1
            self.assertEqual(results.cell(2, source_column).value, "督管案台")
            self.assertEqual(
                results.cell(2, target_column).value,
                "Supervisor's Counter",
            )
            self.assertTrue(
                results.column_dimensions[
                    results.cell(1, target_column).column_letter
                ].hidden
            )
        finally:
            workbook.close()
