import copy
import unittest

from scripts.lqe_corrections import (
    CheckFormatError,
    build_results,
    build_segment_result,
    normalize_check_entries,
)


def issue(edit=None, **overrides):
    value = {
        "category": "Grammar",
        "severity": "Minor",
        "comment": "fix",
        "needs_confirmation": False,
    }
    if edit is not None:
        value["edit"] = edit
    value.update(overrides)
    return value


def edit(frm, to, start=None, end=None, evidence=None):
    value = {"from": frm, "to": to, "evidence": evidence}
    if start is not None or end is not None:
        value["start"] = start
        value["end"] = end
    return value


class CorrectionBuilderTests(unittest.TestCase):
    def test_rejects_model_corrected(self):
        with self.assertRaisesRegex(CheckFormatError, "corrected"):
            normalize_check_entries(
                [{"id": 1, "issues": [], "corrected": "x"}], label="T"
            )

    def test_safe_edit_builds_full_corrected(self):
        seg = {"id": 1, "target": "A“B”C", "kind": "desc", "term_hits": []}
        issues = [
            {
                "category": "Punctuation",
                "severity": "Minor",
                "comment": "引号格式",
                "needs_confirmation": False,
                "edit": {
                    "from": "“B”",
                    "to": '"B"',
                    "evidence": None,
                },
            }
        ]
        self.assertEqual(build_segment_result(seg, issues)["corrected"], 'A"B"C')

    def test_confirmation_issue_cannot_carry_edit(self):
        pending_issue = {
            "category": "Terminology",
            "severity": "Major",
            "comment": "需确认",
            "needs_confirmation": True,
            "edit": {"from": "旧", "to": "新", "evidence": None},
        }
        with self.assertRaisesRegex(CheckFormatError, "edit"):
            build_segment_result(
                {"id": 1, "target": "旧", "kind": "name", "term_hits": []},
                [pending_issue],
            )

    def test_normalize_rejects_invalid_entry_shapes(self):
        invalid_cases = [
            (None, "array"),
            ({}, "array"),
            ([None], "object"),
            ([{}], "id"),
            ([{"id": "1", "issues": []}], "id"),
            ([{"id": 1}], "issues"),
            ([{"id": 1, "issues": {}}], "issues"),
            ([{"id": 1, "issues": [None]}], "issue"),
            (
                [
                    {
                        "id": 1,
                        "issues": [
                            {
                                "category": "Grammar",
                                "severity": "Minor",
                                "comment": "fix",
                                "needs_confirmation": 1,
                            }
                        ],
                    }
                ],
                "needs_confirmation",
            ),
            (
                [
                    {
                        "id": 1,
                        "issues": [
                            {
                                "category": "Grammar",
                                "severity": "Minor",
                                "comment": "fix",
                                "needs_confirmation": False,
                                "edit": [],
                            }
                        ],
                    }
                ],
                "edit",
            ),
        ]
        for entries, message in invalid_cases:
            with self.subTest(entries=entries):
                with self.assertRaisesRegex(CheckFormatError, message):
                    normalize_check_entries(entries, label="T")

    def test_normalize_rejects_duplicate_ids(self):
        entries = [{"id": 1, "issues": []}, {"id": 1, "issues": []}]
        with self.assertRaisesRegex(CheckFormatError, "duplicate.*id"):
            normalize_check_entries(entries, label="T")

    def test_normalize_returns_fresh_canonical_data(self):
        entries = [
            {
                "id": 1,
                "issues": [
                    {
                        "category": "Grammar",
                        "severity": "Minor",
                        "comment": "fix",
                        "repeated": True,
                        "needs_confirmation": False,
                        "edit": edit("a", "b"),
                        "ignored": "drop",
                    }
                ],
                "ignored": "drop",
            }
        ]
        before = copy.deepcopy(entries)

        result = normalize_check_entries(entries, label="T")

        self.assertEqual(entries, before)
        self.assertEqual(
            result,
            [
                {
                    "id": 1,
                    "issues": [
                        {
                            "category": "Grammar",
                            "severity": "Minor",
                            "comment": "fix",
                            "repeated": True,
                            "needs_confirmation": False,
                            "edit": edit("a", "b"),
                        }
                    ],
                }
            ],
        )
        result[0]["issues"][0]["edit"]["to"] = "changed"
        self.assertEqual(entries, before)

    def test_normalize_requires_core_issue_fields(self):
        base = {
            "category": "Grammar",
            "severity": "Minor",
            "comment": "fix",
            "needs_confirmation": False,
            "edit": None,
        }
        for field in ("category", "severity", "comment", "needs_confirmation"):
            malformed = dict(base)
            del malformed[field]
            with self.subTest(field=field):
                with self.assertRaisesRegex(CheckFormatError, field):
                    normalize_check_entries(
                        [{"id": 1, "issues": [malformed]}], label="T"
                    )

    def test_normalize_accepts_null_edit(self):
        pending = {
            "category": "Terminology",
            "severity": "Major",
            "comment": "confirm",
            "needs_confirmation": True,
            "edit": None,
        }
        self.assertEqual(
            normalize_check_entries([{"id": 1, "issues": [pending]}], label="T"),
            [{"id": 1, "issues": [pending]}],
        )

    def test_repeated_from_without_position_is_rejected(self):
        seg = {"id": 1, "target": "foo foo", "kind": "desc", "term_hits": []}
        with self.assertRaisesRegex(CheckFormatError, "unique"):
            build_segment_result(seg, [issue(edit("foo", "bar"))])

    def test_overlapping_repeated_from_without_position_is_rejected(self):
        seg = {"id": 1, "target": "aaa", "kind": "desc", "term_hits": []}
        with self.assertRaisesRegex(CheckFormatError, "unique"):
            build_segment_result(seg, [issue(edit("aa", "b"))])

    def test_start_end_must_match_from(self):
        seg = {"id": 1, "target": "abcdef", "kind": "desc", "term_hits": []}
        with self.assertRaisesRegex(CheckFormatError, "start/end.*from"):
            build_segment_result(seg, [issue(edit("bc", "BC", 2, 4))])

    def test_start_and_end_must_be_provided_together(self):
        malformed = {"from": "a", "to": "b", "start": 0, "evidence": None}
        with self.assertRaisesRegex(CheckFormatError, "start/end"):
            build_segment_result(
                {"id": 1, "target": "a", "kind": "desc", "term_hits": []},
                [issue(malformed)],
            )

    def test_invalid_edit_shape_is_rejected(self):
        invalid_edits = [
            {"from": "a", "to": "b"},
            {"from": "", "to": "b", "evidence": None},
            {"from": "a", "to": 1, "evidence": None},
            {"from": "a", "to": "b", "evidence": None, "extra": True},
        ]
        for bad_edit in invalid_edits:
            with self.subTest(edit=bad_edit):
                with self.assertRaisesRegex(CheckFormatError, "edit"):
                    build_segment_result(
                        {
                            "id": 1,
                            "target": "a",
                            "kind": "desc",
                            "term_hits": [],
                        },
                        [issue(bad_edit)],
                    )

    def test_edits_that_damage_protected_content_are_not_applied(self):
        cases = [
            (
                {"target": "bad {count} now"},
                edit("{count}", "count"),
                "good {count} now",
            ),
            (
                {"target": "bad <b>now</b>"},
                edit("<b>", "<i>"),
                "good <b>now</b>",
            ),
            (
                {"target": "bad\nSecond"},
                edit("\n", " "),
                "good\nSecond",
            ),
            (
                {"target": "bad BRAND now", "protected_texts": ["BRAND"]},
                edit("BRAND", "Brand"),
                "good BRAND now",
            ),
        ]
        for segment_fields, unsafe_edit, expected in cases:
            with self.subTest(target=segment_fields["target"]):
                seg = {
                    "id": 1,
                    "kind": "desc",
                    "term_hits": [],
                    **segment_fields,
                }
                result = build_segment_result(
                    seg,
                    [
                        issue(unsafe_edit, comment="unsafe"),
                        issue(edit("bad", "good"), comment="safe"),
                    ],
                )
                self.assertEqual(result["corrected"], expected)
                self.assertTrue(result["errors"][0]["needs_confirmation"])
                self.assertIsNone(result["errors"][0]["edit"])
                self.assertFalse(result["errors"][1]["needs_confirmation"])
                self.assertIsNotNone(result["errors"][1]["edit"])

    def test_safe_edit_can_span_unchanged_protected_content(self):
        seg = {
            "id": 1,
            "target": "Use <b>bad</b> now",
            "kind": "desc",
            "term_hits": [],
        }
        result = build_segment_result(
            seg, [issue(edit("Use <b>bad</b>", "Show <b>good</b>"))]
        )
        self.assertEqual(result["corrected"], "Show <b>good</b> now")

    def test_identical_overlapping_edits_are_deduplicated(self):
        seg = {"id": 1, "target": "abcdef", "kind": "desc", "term_hits": []}
        same_edit = edit("bcd", "BCD", 1, 4)

        result = build_segment_result(
            seg,
            [
                issue(copy.deepcopy(same_edit), comment="first"),
                issue(copy.deepcopy(same_edit), comment="second"),
            ],
        )

        self.assertEqual(result["corrected"], "aBCDef")
        self.assertEqual(len(result["errors"]), 2)
        self.assertTrue(
            all(not error["needs_confirmation"] for error in result["errors"])
        )

    def test_conflicting_overlaps_become_confirmation_and_other_edits_apply(self):
        seg = {"id": 1, "target": "abcdef", "kind": "desc", "term_hits": []}
        result = build_segment_result(
            seg,
            [
                issue(edit("bc", "BC", 1, 3), comment="first conflict"),
                issue(edit("cd", "XX", 2, 4), comment="second conflict"),
                issue(edit("f", "F", 5, 6), comment="safe"),
            ],
        )

        self.assertEqual(result["corrected"], "abcdeF")
        for error in result["errors"][:2]:
            self.assertTrue(error["needs_confirmation"])
            self.assertIsNone(error["edit"])
        self.assertFalse(result["errors"][2]["needs_confirmation"])
        self.assertIsNotNone(result["errors"][2]["edit"])

    def test_noop_edit_returns_no_corrected(self):
        seg = {"id": 1, "target": "same", "kind": "desc", "term_hits": []}
        self.assertIsNone(
            build_segment_result(seg, [issue(edit("same", "same"))])["corrected"]
        )

    def test_name_edit_requires_matching_confirmed_term_evidence(self):
        segment = {
            "id": 1,
            "target": "Old Name",
            "kind": "name",
            "term_hits": [
                {"source": "旧名", "target": "New Name", "confirmed": True}
            ],
        }
        valid_evidence = {
            "type": "confirmed_term",
            "source": "旧名",
            "target": "New Name",
        }
        result = build_segment_result(
            segment,
            [issue(edit("Old Name", "New Name", evidence=valid_evidence))],
        )
        self.assertEqual(result["corrected"], "New Name")

        for invalid_evidence in (
            None,
            {**valid_evidence, "target": "Other"},
            {**valid_evidence, "type": "guess"},
        ):
            with self.subTest(evidence=invalid_evidence):
                unsafe_result = build_segment_result(
                    segment,
                    [
                        issue(
                            edit(
                                "Old Name",
                                "New Name",
                                evidence=invalid_evidence,
                            )
                        )
                    ],
                )
                self.assertIsNone(unsafe_result["corrected"])
                self.assertTrue(unsafe_result["errors"][0]["needs_confirmation"])
                self.assertIsNone(unsafe_result["errors"][0]["edit"])

    def test_unconfirmed_term_evidence_becomes_confirmation(self):
        segment = {
            "id": 1,
            "target": "Old Name",
            "kind": "name",
            "term_hits": [
                {"source": "旧名", "target": "New Name", "confirmed": False}
            ],
        }
        evidence = {
            "type": "confirmed_term",
            "source": "旧名",
            "target": "New Name",
        }
        result = build_segment_result(
            segment, [issue(edit("Old Name", "New Name", evidence=evidence))]
        )
        self.assertIsNone(result["corrected"])
        self.assertTrue(result["errors"][0]["needs_confirmation"])
        self.assertIsNone(result["errors"][0]["edit"])

    def test_desc_edit_touching_term_requires_matching_confirmed_evidence(self):
        segment = {
            "id": 1,
            "target": "Meet Old Name today.",
            "kind": "desc",
            "term_hits": [
                {"source": "旧名", "target": "Old Name", "confirmed": True}
            ],
        }
        result = build_segment_result(
            segment,
            [
                issue(edit("Old Name", "New Name", 5, 13), comment="term"),
                issue(edit("today", "now"), comment="safe"),
            ],
        )
        self.assertEqual(result["corrected"], "Meet Old Name now.")
        self.assertTrue(result["errors"][0]["needs_confirmation"])
        self.assertIsNone(result["errors"][0]["edit"])
        self.assertFalse(result["errors"][1]["needs_confirmation"])

    def test_build_results_preserves_segment_order_and_fills_missing_checks(self):
        segments = [
            {"id": 2, "target": "two", "kind": "desc", "term_hits": []},
            {"id": 1, "target": "one", "kind": "desc", "term_hits": []},
        ]
        checks = [
            {
                "id": 1,
                "issues": [issue(edit("one", "ONE"))],
            }
        ]

        self.assertEqual(
            build_results(segments, checks),
            [
                {"id": 2, "errors": [], "corrected": None},
                {
                    "id": 1,
                    "errors": [issue(edit("one", "ONE"))],
                    "corrected": "ONE",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
