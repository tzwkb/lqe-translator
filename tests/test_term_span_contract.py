import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lqe_corrections import (
    CheckFormatError,
    build_segment_result,
    normalize_check_entries,
)


def terminology_issue(*, source_spans=None, target_spans=None):
    return {
        "category": "Terminology",
        "severity": "Major",
        "comment": "The project term is not used.",
        "term_source": "督管案台",
        "expected_targets": ["Supervisor's Counter"],
        "term_spans": {
            "source": (
                source_spans
                if source_spans is not None
                else [{"start": 2, "end": 6, "text": "督管案台"}]
            ),
            "target": (
                target_spans
                if target_spans is not None
                else [{"start": 10, "end": 22, "text": "control desk"}]
            ),
        },
        "needs_confirmation": True,
        "edit": None,
    }


class TermSpanContractTests(unittest.TestCase):
    def setUp(self):
        self.segment = {
            "id": 7,
            "source": "查看督管案台",
            "target": "Check the control desk",
        }

    def test_valid_spans_survive_result_build(self):
        result = build_segment_result(self.segment, [terminology_issue()])

        self.assertEqual(
            result["errors"][0]["term_spans"]["target"][0]["text"],
            "control desk",
        )

    def test_target_spans_may_be_empty_for_omission(self):
        result = build_segment_result(
            self.segment,
            [terminology_issue(target_spans=[])],
        )

        self.assertEqual(result["errors"][0]["term_spans"]["target"], [])

    def test_legacy_terminology_issue_without_spans_is_rejected(self):
        legacy = terminology_issue()
        legacy.pop("term_spans")

        with self.assertRaisesRegex(
            CheckFormatError,
            "requires term_source, expected_targets, and term_spans",
        ):
            normalize_check_entries(
                [{"id": 7, "issues": [legacy]}],
                label="legacy",
            )

    def test_span_shape_requires_exact_keys(self):
        value = terminology_issue()
        value["term_spans"]["extra"] = []

        with self.assertRaisesRegex(CheckFormatError, "exactly source and target"):
            normalize_check_entries(
                [{"id": 7, "issues": [value]}],
                label="draft",
            )

    def test_spans_must_be_sorted_and_non_overlapping(self):
        cases = (
            (
                [
                    {"start": 2, "end": 6, "text": "督管案台"},
                    {"start": 0, "end": 1, "text": "查"},
                ],
                "sorted",
            ),
            (
                [
                    {"start": 0, "end": 3, "text": "查看督"},
                    {"start": 2, "end": 6, "text": "督管案台"},
                ],
                "must not overlap",
            ),
        )
        for spans, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(CheckFormatError, message):
                    normalize_check_entries(
                        [
                            {
                                "id": 7,
                                "issues": [terminology_issue(source_spans=spans)],
                            }
                        ],
                        label="draft",
                    )

    def test_span_slice_must_match_live_segment_text(self):
        value = terminology_issue(
            target_spans=[{"start": 10, "end": 22, "text": "wrong target"}]
        )

        with self.assertRaisesRegex(CheckFormatError, "does not match segment target"):
            build_segment_result(self.segment, [value])

    def test_source_span_text_must_equal_term_source(self):
        value = terminology_issue(
            source_spans=[{"start": 0, "end": 2, "text": "查看"}]
        )

        with self.assertRaisesRegex(CheckFormatError, "must equal term_source"):
            build_segment_result(self.segment, [value])

    def test_term_metadata_on_related_category_is_also_slice_validated(self):
        value = terminology_issue(
            target_spans=[{"start": 10, "end": 22, "text": "wrong target"}]
        )
        value["category"] = "Inconsistency"

        with self.assertRaisesRegex(CheckFormatError, "does not match segment target"):
            build_segment_result(self.segment, [value])


if __name__ == "__main__":
    unittest.main()
