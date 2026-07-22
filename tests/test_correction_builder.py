import copy
import unittest

from scripts.lqe_corrections import (
    CheckFormatError,
    build_results,
    build_segment_result,
    normalize_check_entries,
    verify_results,
)
from scripts.lqe_engine import term_senses


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
    provenance = value.get("review_provenance")
    if (
        edit is not None
        and isinstance(provenance, dict)
        and provenance.get("edit_origin") is None
    ):
        provenance["edit_origin"] = (
            "ai_module"
            if provenance.get("ai_reviewed") is True
            else "machine_precheck"
        )
    return value


def edit(frm, to, start=None, end=None, evidence=None):
    value = {"from": frm, "to": to, "evidence": evidence}
    if start is not None or end is not None:
        value["start"] = start
        value["end"] = end
    return value


def ai_provenance(module="grammar", *, ai_edited=False):
    return {
        "finding_origin": "ai_module",
        "ai_reviewed": True,
        "ai_edited": ai_edited,
        "review_module": module,
        "reviewed_segment_id": 1,
        "edit_origin": None,
    }


def machine_provenance(*, ai_edited=False):
    return {
        "finding_origin": "machine_precheck",
        "ai_reviewed": False,
        "ai_edited": ai_edited,
        "review_module": None,
        "reviewed_segment_id": None,
        "edit_origin": None,
    }


class CorrectionBuilderTests(unittest.TestCase):
    def test_term_senses_defaults_flags_and_preserves_multisense_values(self):
        self.assertEqual(
            term_senses(
                {
                    "source": "未标记",
                    "target": "Unmarked",
                    "status": "Approved",
                    "locked": True,
                }
            ),
            [
                {
                    "target": "Unmarked",
                    "status": "Approved",
                    "confirmed": False,
                    "protected": False,
                }
            ],
        )
        self.assertEqual(
            term_senses(
                {
                    "source": "多义",
                    "senses": [
                        {"target": "A", "confirmed": True},
                        {"target": "B", "protected": True},
                    ],
                }
            ),
            [
                {"target": "A", "confirmed": True, "protected": False},
                {"target": "B", "confirmed": False, "protected": True},
            ],
        )

    def test_confirmed_term_sense_authorizes_exact_name_edit(self):
        entry = {
            "source": "小花仙",
            "target": "ดอกบ้องแบ๊ว",
            "confirmed": True,
            "protected": False,
        }
        segment = {
            "id": 1,
            "target": "ภูตดอกไม้",
            "kind": "name",
            "term_hits": [
                {"source": entry["source"], **term_senses(entry)[0]}
            ],
        }
        evidence = {
            "type": "confirmed_term",
            "source": entry["source"],
            "target": entry["target"],
        }

        result = build_segment_result(
            segment,
            [issue(edit(segment["target"], entry["target"], evidence=evidence))],
        )

        self.assertEqual(result["corrected"], entry["target"])

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

    def test_untrusted_model_output_cannot_claim_ai_provenance(self):
        claimed = issue(
            edit("a", "b"),
            review_provenance=ai_provenance(ai_edited=True),
        )

        normalized = normalize_check_entries(
            [{"id": 1, "issues": [claimed]}], label="model"
        )
        built = build_segment_result(
            {"id": 1, "target": "a", "kind": "desc", "term_hits": []},
            [claimed],
        )

        self.assertNotIn("review_provenance", normalized[0]["issues"][0])
        self.assertNotIn("review_provenance", built["errors"][0])

    def test_internal_provenance_is_canonical_and_rejects_invalid_combinations(self):
        claimed = issue(review_provenance=ai_provenance(ai_edited=True))
        normalized = normalize_check_entries(
            [{"id": 1, "issues": [claimed]}],
            label="internal",
            allow_internal_provenance=True,
        )
        self.assertEqual(
            normalized[0]["issues"][0]["review_provenance"],
            ai_provenance(ai_edited=False),
        )

        invalid = (
            {"ai_reviewed": False, "origin": "ai_module", "module": "grammar"},
            {"ai_reviewed": True, "origin": "ai_module", "module": None},
            {
                "ai_reviewed": True,
                "origin": "machine_precheck",
                "module": None,
            },
            {
                "ai_reviewed": False,
                "origin": "machine_precheck",
                "module": "grammar",
            },
            {"ai_reviewed": True, "origin": "other", "module": "grammar"},
            {"ai_reviewed": True, "origin": [], "module": "grammar"},
            {
                "ai_reviewed": True,
                "origin": "ai_module",
                "module": "grammar",
                "extra": True,
            },
        )
        for provenance in invalid:
            with self.subTest(provenance=provenance):
                with self.assertRaisesRegex(CheckFormatError, "provenance"):
                    normalize_check_entries(
                        [
                            {
                                "id": 1,
                                "issues": [
                                    issue(review_provenance=provenance)
                                ],
                            }
                        ],
                        label="internal",
                        allow_internal_provenance=True,
                    )

        with self.assertRaisesRegex(CheckFormatError, "provenance is required"):
            normalize_check_entries(
                [{"id": 1, "issues": [issue()]}],
                label="current",
                allow_internal_provenance=True,
                require_internal_provenance=True,
            )

    def test_ai_edited_is_true_only_for_a_verified_applied_ai_edit(self):
        segment = {
            "id": 1,
            "target": "bad {count}",
            "kind": "desc",
            "term_hits": [],
        }
        issues = [
            issue(
                edit("bad", "good"),
                comment="safe AI edit",
                review_provenance=ai_provenance(ai_edited=False),
            ),
            issue(
                edit("{count}", "count"),
                comment="unsafe AI edit",
                review_provenance=ai_provenance(ai_edited=True),
            ),
            issue(
                comment="reviewed without edit",
                review_provenance=ai_provenance(ai_edited=True),
            ),
        ]

        result = build_segment_result(
            segment, issues, allow_internal_provenance=True
        )

        self.assertEqual(result["corrected"], "good {count}")
        self.assertTrue(
            result["errors"][0]["review_provenance"]["ai_edited"]
        )
        self.assertFalse(
            result["errors"][1]["review_provenance"]["ai_edited"]
        )
        self.assertTrue(result["errors"][1]["needs_confirmation"])
        self.assertIsNone(result["errors"][1]["edit"])
        self.assertFalse(
            result["errors"][2]["review_provenance"]["ai_edited"]
        )

    def test_noop_conflict_and_machine_edits_do_not_claim_ai_editing(self):
        segment = {
            "id": 1,
            "target": "abcdef",
            "kind": "desc",
            "term_hits": [],
        }
        issues = [
            issue(
                edit("a", "a", 0, 1),
                comment="AI no-op",
                review_provenance=ai_provenance(ai_edited=True),
            ),
            issue(
                edit("bc", "BC", 1, 3),
                comment="first conflict",
                review_provenance=ai_provenance(ai_edited=True),
            ),
            issue(
                edit("cd", "XX", 2, 4),
                comment="second conflict",
                review_provenance=ai_provenance(ai_edited=True),
            ),
            issue(
                edit("f", "F", 5, 6),
                comment="machine edit",
                review_provenance=machine_provenance(ai_edited=True),
            ),
        ]

        result = build_segment_result(
            segment, issues, allow_internal_provenance=True
        )

        self.assertEqual(result["corrected"], "abcdeF")
        self.assertTrue(all(
            not error["review_provenance"]["ai_edited"]
            for error in result["errors"]
        ))

    def test_verify_results_recomputes_ai_edited_instead_of_trusting_input(self):
        segment = {"id": 1, "target": "bad", "kind": "desc", "term_hits": []}
        result = {
            "id": 1,
            "errors": [
                issue(
                    edit("bad", "good"),
                    review_provenance=ai_provenance(ai_edited=False),
                )
            ],
            "corrected": "good",
        }

        verified = verify_results(
            [segment],
            [result],
            "results",
            allow_internal_provenance=True,
        )

        self.assertTrue(
            verified[0]["errors"][0]["review_provenance"]["ai_edited"]
        )

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

    def test_normalize_rejects_blank_comment(self):
        pending = {
            "category": "Grammar",
            "severity": "Minor",
            "comment": "  \n",
            "needs_confirmation": True,
            "edit": None,
        }

        with self.assertRaisesRegex(CheckFormatError, "comment.*non-empty"):
            normalize_check_entries([{"id": 1, "issues": [pending]}], label="T")

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

    def test_desc_confirmed_term_evidence_cannot_authorize_a_different_term(self):
        segment = {
            "id": 1,
            "target": "Old A and Old B today.",
            "kind": "desc",
            "term_hits": [
                {
                    "source": "术语A",
                    "target": "New A",
                    "confirmed": True,
                    "matched_text": "Old A",
                }
            ],
        }
        evidence = {
            "type": "confirmed_term",
            "source": "术语A",
            "target": "New A",
        }

        result = build_segment_result(
            segment,
            [
                issue(edit("Old B", "New A", evidence=evidence), comment="unsafe"),
                issue(edit("today", "now"), comment="safe"),
            ],
        )

        self.assertEqual(result["corrected"], "Old A and Old B now.")
        self.assertTrue(result["errors"][0]["needs_confirmation"])
        self.assertIsNone(result["errors"][0]["edit"])
        self.assertFalse(result["errors"][1]["needs_confirmation"])
        self.assertIsNotNone(result["errors"][1]["edit"])

    def test_desc_confirmed_term_without_matched_text_authorizes_edit(self):
        segment = {
            "id": 1,
            "target": "Old Name",
            "kind": "desc",
            "term_hits": [
                {"source": "旧名", "target": "New Name", "confirmed": True}
            ],
        }
        evidence = {
            "type": "confirmed_term",
            "source": "旧名",
            "target": "New Name",
        }

        result = build_segment_result(
            segment,
            [issue(edit("Old Name", "New Name", evidence=evidence))],
        )

        self.assertEqual(result["corrected"], "New Name")
        self.assertFalse(result["errors"][0]["needs_confirmation"])
        self.assertIsNotNone(result["errors"][0]["edit"])

    def test_confirmed_term_evidence_target_must_equal_edit_replacement(self):
        segment = {
            "id": 1,
            "target": "Old Name",
            "kind": "name",
            "term_hits": [
                {"source": "旧名", "target": "Canonical Name", "confirmed": True}
            ],
        }
        evidence = {
            "type": "confirmed_term",
            "source": "旧名",
            "target": "Canonical Name",
        }

        result = build_segment_result(
            segment,
            [issue(edit("Old Name", "Different Name", evidence=evidence))],
        )

        self.assertIsNone(result["corrected"])
        self.assertTrue(result["errors"][0]["needs_confirmation"])
        self.assertIsNone(result["errors"][0]["edit"])

    def test_name_confirmed_term_evidence_requires_full_target_edit(self):
        segment = {
            "id": 1,
            "target": "The Old Name",
            "kind": "name",
            "term_hits": [
                {"source": "旧名", "target": "New Name", "confirmed": True}
            ],
        }
        evidence = {
            "type": "confirmed_term",
            "source": "旧名",
            "target": "New Name",
        }

        result = build_segment_result(
            segment,
            [issue(edit("Old Name", "New Name", evidence=evidence))],
        )

        self.assertIsNone(result["corrected"])
        self.assertTrue(result["errors"][0]["needs_confirmation"])
        self.assertIsNone(result["errors"][0]["edit"])

    def test_name_confirmed_term_evidence_requires_unique_hit(self):
        confirmed_hit = {
            "source": "旧名",
            "target": "New Name",
            "confirmed": True,
        }
        segment = {
            "id": 1,
            "target": "Old Name",
            "kind": "name",
            "term_hits": [confirmed_hit, copy.deepcopy(confirmed_hit)],
        }
        evidence = {
            "type": "confirmed_term",
            "source": "旧名",
            "target": "New Name",
        }

        result = build_segment_result(
            segment,
            [issue(edit("Old Name", "New Name", evidence=evidence))],
        )

        self.assertIsNone(result["corrected"])
        self.assertTrue(result["errors"][0]["needs_confirmation"])
        self.assertIsNone(result["errors"][0]["edit"])

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
