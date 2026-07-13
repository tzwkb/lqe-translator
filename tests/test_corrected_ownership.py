import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CHUNK_SCRIPT = SCRIPTS / "lqe_chunk.py"
REQUIRED_MODULES = ("terminology", "accuracy", "grammar", "naturalness")

sys.path.insert(0, str(SCRIPTS))

from lqe_checks import run_pre_check
import lqe_chunk


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def check_issue(
    category="Grammar",
    severity="Minor",
    comment="check",
    *,
    needs_confirmation=False,
    edit=None,
):
    return {
        "category": category,
        "severity": severity,
        "comment": comment,
        "needs_confirmation": needs_confirmation,
        "edit": edit,
    }


def replacement(frm, to, *, evidence=None, start=None, end=None):
    value = {"from": frm, "to": to, "evidence": evidence}
    if start is not None or end is not None:
        value["start"] = start
        value["end"] = end
    return value


def confirmed_evidence(source, target):
    return {"type": "confirmed_term", "source": source, "target": target}


def call_quietly(function, *args, **kwargs):
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        return function(*args, **kwargs)


class CorrectedOwnershipChunkTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.job = Path(self.tempdir.name) / "job"
        self.chunks = self.job / "chunks"
        self.chunks.mkdir(parents=True)

    def tearDown(self):
        self.tempdir.cleanup()

    def run_chunk(self, *args):
        return subprocess.run(
            [sys.executable, str(CHUNK_SCRIPT), *map(str, args)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def make_job(self, segments, *, representatives=None, dedup_map=None, pre=None):
        write_json(self.job / "state.json", {"segments": segments})
        if pre is None:
            pre = [{"id": segment["id"], "issues": []} for segment in segments]
        write_json(self.job / "errors_precheck.json", pre)

        chunk_segments = representatives if representatives is not None else segments
        write_json(
            self.chunks / "chunk_00.json",
            {"chunk_id": 0, "segments": chunk_segments},
        )
        if dedup_map is None:
            dedup_map = {str(segment["id"]): [segment["id"]] for segment in chunk_segments}
        write_json(self.chunks / "dedup_map.json", dedup_map)

    def write_modules(self, ids, *, issues_by_module=None):
        issues_by_module = issues_by_module or {}
        for module in REQUIRED_MODULES:
            rows = [
                {
                    "id": segment_id,
                    "issues": issues_by_module.get(module, {}).get(segment_id, []),
                }
                for segment_id in ids
            ]
            write_json(self.chunks / f"chunk_00.{module}.json", rows)

    def merge_checks(self):
        result = self.run_chunk("merge-checks", "--job", self.job)
        self.assertEqual(result.returncode, 0, result.stderr)
        return read_json(self.chunks / "chunk_00.out.json")

    def merge_final(self):
        output = self.job / "errors.json"
        result = self.run_chunk(
            "merge",
            "--state",
            self.job / "state.json",
            "--errors",
            self.job / "errors_precheck.json",
            "--outdir",
            self.chunks,
            "--out",
            output,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return read_json(output)

    def test_validate_checks_rejects_top_level_corrected(self):
        self.make_job([{"id": 0, "source": "x", "target": "x"}])
        self.write_modules([0])
        path = self.chunks / "chunk_00.terminology.json"
        write_json(path, [{"id": 0, "issues": [], "corrected": "model text"}])

        result = self.run_chunk("validate-checks", "--job", self.job)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("corrected is not allowed", result.stderr)

    def test_ckpt_append_rejects_top_level_corrected(self):
        checkpoint = self.chunks / "chunk_00.terminology.ckpt.jsonl"
        entry = json.dumps(
            {"id": 0, "issues": [], "corrected": "model text"},
            ensure_ascii=False,
        )

        result = self.run_chunk(
            "ckpt-append", "--file", checkpoint, "--entry", entry
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("corrected is not allowed", result.stderr)
        self.assertFalse(checkpoint.exists())

    def test_merge_checks_rejects_top_level_corrected(self):
        self.make_job([{"id": 0, "source": "x", "target": "x"}])
        self.write_modules([0])
        path = self.chunks / "chunk_00.naturalness.json"
        write_json(path, [{"id": 0, "issues": [], "corrected": "model text"}])

        result = self.run_chunk("merge-checks", "--job", self.job)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("corrected is not allowed", result.stderr)
        self.assertFalse((self.chunks / "chunk_00.out.json").exists())

    def test_validate_checks_requires_modules_and_complete_ids(self):
        segments = [
            {"id": 0, "source": "a", "target": "a"},
            {"id": 1, "source": "b", "target": "b"},
        ]
        self.make_job(segments)
        self.write_modules([0, 1])
        (self.chunks / "chunk_00.grammar.json").unlink()
        write_json(
            self.chunks / "chunk_00.terminology.json",
            [{"id": 0, "issues": []}],
        )

        result = self.run_chunk("validate-checks", "--job", self.job)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("grammar", result.stderr)
        self.assertIn("1", result.stderr)

    def test_merge_checks_unions_deduplicates_and_filters_accuracy_owned_issues(self):
        self.make_job([{"id": 0, "source": "x", "target": "x"}])
        punctuation = check_issue(
            category="Punctuation",
            comment="same",
            edit=replacement("x", "X"),
        )
        unconfirmed_accuracy = check_issue(
            category="Mistranslation",
            severity="Major",
            comment="terminology guessed",
            needs_confirmation=True,
        )
        accuracy = check_issue(
            category="Omission",
            severity="Major",
            comment="accuracy confirmed",
            needs_confirmation=True,
        )
        self.write_modules(
            [0],
            issues_by_module={
                "terminology": {0: [punctuation, unconfirmed_accuracy]},
                "accuracy": {0: [accuracy]},
                "grammar": {0: [punctuation]},
            },
        )

        merged = self.merge_checks()

        self.assertEqual(merged, [{"id": 0, "issues": [punctuation, accuracy]}])
        self.assertNotIn("corrected", merged[0])
        self.assertNotIn("errors", merged[0])

    def test_accuracy_owned_issue_uses_only_accuracy_module_edit(self):
        segment = {
            "id": 0,
            "source": "source",
            "target": "bad",
            "kind": "desc",
            "term_hits": [],
            "protected_texts": [],
        }
        terminology_issue = check_issue(
            category="Mistranslation",
            severity="Major",
            comment="terminology rewrite",
            edit=replacement("bad", "term guess"),
        )
        accuracy_issue = check_issue(
            category="Mistranslation",
            severity="Major",
            comment="accuracy rewrite",
            edit=replacement("bad", "accurate"),
        )
        self.make_job([segment])
        self.write_modules(
            [0],
            issues_by_module={
                "terminology": {0: [terminology_issue]},
                "accuracy": {0: [accuracy_issue]},
            },
        )

        checks = self.merge_checks()
        merged = self.merge_final()

        self.assertEqual(checks, [{"id": 0, "issues": [accuracy_issue]}])
        self.assertEqual(merged[0]["errors"], [accuracy_issue])
        self.assertEqual(merged[0]["corrected"], "accurate")

    def test_precheck_emits_issues_and_a_local_deterministic_edit(self):
        state_path = self.job / "state.json"
        output_path = self.job / "errors_precheck.json"
        write_json(
            state_path,
            {
                "source_lang": "en",
                "target_lang": "en",
                "segments": [{"id": 0, "source": "A-B", "target": "A—B"}],
            },
        )

        call_quietly(run_pre_check, state_path, output_path)
        result = read_json(output_path)

        self.assertEqual(set(result[0]), {"id", "issues"})
        em_dash = next(
            issue for issue in result[0]["issues"] if "Em dash" in issue["comment"]
        )
        self.assertFalse(em_dash["needs_confirmation"])
        self.assertEqual(
            em_dash["edit"],
            {
                "from": "—",
                "to": " - ",
                "start": 1,
                "end": 2,
                "evidence": None,
            },
        )

    def test_em_dash_edit_absorbs_adjacent_spaces(self):
        variants = ("A—B", "A — B", "A— B", "A —B")
        for target in variants:
            with self.subTest(target=target):
                state_path = self.job / "state.json"
                output_path = self.job / "errors_precheck.json"
                write_json(
                    state_path,
                    {
                        "source_lang": "en",
                        "target_lang": "en",
                        "segments": [
                            {"id": 0, "source": "A-B", "target": target}
                        ],
                    },
                )
                call_quietly(run_pre_check, state_path, output_path)
                issues = read_json(output_path)[0]["issues"]

                result = lqe_chunk.build_segment_result(
                    {
                        "id": 0,
                        "target": target,
                        "kind": "desc",
                        "term_hits": [],
                        "protected_texts": [],
                    },
                    issues,
                )

                self.assertEqual(result["corrected"], "A - B")

    def test_precheck_issue_schema_is_complete_for_all_output_modes(self):
        cases = (
            ("empty", "Text", ""),
            ("reminder", "Hello {name}", "Hello"),
            ("double_space", "A B", "A  B"),
            ("fullwidth", "A,B", "A，B"),
        )
        required = {
            "category",
            "severity",
            "comment",
            "needs_confirmation",
            "edit",
        }
        for label, source, target in cases:
            with self.subTest(case=label):
                state_path = self.job / "state.json"
                output_path = self.job / "errors_precheck.json"
                write_json(
                    state_path,
                    {
                        "source_lang": "en",
                        "target_lang": "en",
                        "segments": [
                            {"id": 0, "source": source, "target": target}
                        ],
                    },
                )

                call_quietly(run_pre_check, state_path, output_path)
                issues = read_json(output_path)[0]["issues"]

                self.assertTrue(issues)
                for issue in issues:
                    self.assertTrue(required.issubset(issue))
                    self.assertTrue(
                        issue["edit"] is None or isinstance(issue["edit"], dict)
                    )

    def test_locked_segment_still_uses_correction_builder(self):
        segment = {
            "id": 0,
            "source": "protected",
            "target": "original",
            "locked": True,
            "kind": "desc",
            "term_hits": [],
            "protected_texts": ["original"],
        }
        self.make_job([segment])
        output = self.job / "errors.json"

        with mock.patch.object(
            lqe_chunk,
            "build_segment_result",
            wraps=lqe_chunk.build_segment_result,
        ) as builder:
            call_quietly(
                lqe_chunk.cmd_merge,
                SimpleNamespace(
                    state=str(self.job / "state.json"),
                    errors=str(self.job / "errors_precheck.json"),
                    outdir=str(self.chunks),
                    out=str(output),
                ),
            )

        builder.assert_called_once()
        called_segment, called_issues = builder.call_args.args
        self.assertEqual(called_segment["id"], 0)
        self.assertEqual(called_issues, [])
        self.assertEqual(
            read_json(output),
            [{"id": 0, "errors": [], "corrected": None}],
        )

    def test_term_hits_flatten_senses_and_preserve_explicit_confirmation(self):
        from lqe_chunk import _term_hits

        hits = _term_hits(
            "魔草巫灵",
            [
                (
                    "魔草巫灵",
                    [
                        {"target": "Verdrel", "confirmed": True},
                        {"target": "Reference", "confirmed": False},
                    ],
                )
            ],
        )

        self.assertEqual(
            hits,
            [
                {"source": "魔草巫灵", "target": "Verdrel", "confirmed": True},
                {
                    "source": "魔草巫灵",
                    "target": "Reference",
                    "confirmed": False,
                },
            ],
        )

    def test_unconfirmed_names_do_not_generate_new_translations(self):
        cases = [
            ("深蓝鲸", "ธาลูน", "Thalune"),
            ("伊里斯", "Iris", "Irys"),
            ("星光狮", "Old Lion", "Blitzmane"),
        ]
        segments = []
        terminology = {}
        for segment_id, (source, original, proposed) in enumerate(cases):
            segments.append(
                {
                    "id": segment_id,
                    "source": source,
                    "target": original,
                    "kind": "name",
                    "term_hits": [
                        {
                            "source": source,
                            "target": proposed,
                            "confirmed": False,
                        }
                    ],
                    "protected_texts": [],
                }
            )
            terminology[segment_id] = [
                check_issue(
                    category="Terminology",
                    severity="Major",
                    comment=f"{source} proposed name",
                    edit=replacement(
                        original,
                        proposed,
                        evidence=confirmed_evidence(source, proposed),
                    ),
                )
            ]
        self.make_job(segments)
        self.write_modules(range(len(segments)), issues_by_module={"terminology": terminology})

        self.merge_checks()
        merged = self.merge_final()

        self.assertEqual([row["corrected"] for row in merged], [None, None, None])
        for row in merged:
            self.assertTrue(row["errors"][0]["needs_confirmation"])
            self.assertIsNone(row["errors"][0]["edit"])

    def test_term_replacement_requires_confirmed_true(self):
        terms = [
            ("魔草巫灵", "Old Verdrel", "Verdrel"),
            ("奇丽花", "Old Florora", "Florora"),
        ]
        segments = []
        terminology = {}
        expected = []
        segment_id = 0
        for source, original, target in terms:
            for confirmed in (False, True):
                segments.append(
                    {
                        "id": segment_id,
                        "source": source,
                        "target": original,
                        "kind": "name",
                        "term_hits": [
                            {
                                "source": source,
                                "target": target,
                                "confirmed": confirmed,
                            }
                        ],
                        "protected_texts": [],
                    }
                )
                terminology[segment_id] = [
                    check_issue(
                        category="Terminology",
                        severity="Major",
                        comment="use confirmed term",
                        edit=replacement(
                            original,
                            target,
                            evidence=confirmed_evidence(source, target),
                        ),
                    )
                ]
                expected.append(target if confirmed else None)
                segment_id += 1
        self.make_job(segments)
        self.write_modules(range(len(segments)), issues_by_module={"terminology": terminology})

        self.merge_checks()
        merged = self.merge_final()

        self.assertEqual([row["corrected"] for row in merged], expected)

    def test_conflicting_flower_butterfly_edits_do_not_land(self):
        source = "花衣蝶登场"
        original = "Old Butterfly appears"
        first = "Sprigella"
        second = "Hanagoromia"
        segment = {
            "id": 0,
            "source": source,
            "target": original,
            "kind": "desc",
            "term_hits": [
                {
                    "source": "花衣蝶",
                    "target": first,
                    "confirmed": True,
                    "matched_text": "Old Butterfly",
                },
                {
                    "source": "花衣蝶",
                    "target": second,
                    "confirmed": True,
                    "matched_text": "Old Butterfly",
                },
            ],
            "protected_texts": [],
        }
        first_issue = check_issue(
            category="Terminology",
            severity="Major",
            comment="first name",
            edit=replacement(
                "Old Butterfly",
                first,
                evidence=confirmed_evidence("花衣蝶", first),
            ),
        )
        second_issue = check_issue(
            category="Terminology",
            severity="Major",
            comment="second name",
            edit=replacement(
                "Old Butterfly",
                second,
                evidence=confirmed_evidence("花衣蝶", second),
            ),
        )
        self.make_job([segment])
        self.write_modules(
            [0],
            issues_by_module={
                "terminology": {0: [first_issue]},
                "proper_names": {0: [second_issue]},
            },
        )
        write_json(
            self.chunks / "chunk_00.proper_names.json",
            [{"id": 0, "issues": [second_issue]}],
        )

        self.merge_checks()
        merged = self.merge_final()

        self.assertIsNone(merged[0]["corrected"])
        self.assertEqual(len(merged[0]["errors"]), 2)
        self.assertTrue(
            all(issue["needs_confirmation"] for issue in merged[0]["errors"])
        )
        self.assertTrue(all(issue["edit"] is None for issue in merged[0]["errors"]))

    def test_mixed_row_only_applies_safe_edit(self):
        original = "สไตล์ฟลอโรรา- รองเท้า"
        segment = {
            "id": 0,
            "source": "奇丽花印象-鞋子",
            "target": original,
            "kind": "desc",
            "term_hits": [
                {"source": "奇丽花", "target": "Florora", "confirmed": False}
            ],
            "protected_texts": [],
        }
        pending_name = check_issue(
            category="Terminology",
            severity="Major",
            comment="proper name needs confirmation",
            needs_confirmation=True,
        )
        spacing = check_issue(
            category="Punctuation",
            comment="space before hyphen",
            edit=replacement("-", " -"),
        )
        self.make_job([segment])
        self.write_modules(
            [0],
            issues_by_module={"terminology": {0: [pending_name]}, "grammar": {0: [spacing]}},
        )

        self.merge_checks()
        merged = self.merge_final()

        self.assertEqual(merged[0]["corrected"], "สไตล์ฟลอโรรา - รองเท้า")
        self.assertTrue(
            any(issue["needs_confirmation"] for issue in merged[0]["errors"])
        )

    def test_duplicate_broadcast_keeps_errors_and_generated_corrected(self):
        segments = [
            {"id": 0, "source": "same", "target": "bad-text"},
            {"id": 1, "source": "same", "target": "bad-text"},
        ]
        representative = {
            "id": 0,
            "source": "same",
            "target": "bad-text",
            "kind": "desc",
            "term_hits": [],
            "protected_texts": [],
        }
        safe = check_issue(
            category="Punctuation",
            comment="replace hyphen",
            edit=replacement("-", " "),
        )
        self.make_job(
            segments,
            representatives=[representative],
            dedup_map={"0": [0, 1]},
        )
        self.write_modules([0], issues_by_module={"grammar": {0: [safe]}})

        self.merge_checks()
        merged = self.merge_final()

        self.assertEqual([row["id"] for row in merged], [0, 1])
        self.assertEqual([row["corrected"] for row in merged], ["bad text", "bad text"])
        self.assertEqual(merged[0]["errors"], merged[1]["errors"])

    def test_reconcile_writes_only_id_and_issues(self):
        self.make_job([{"id": 0, "source": "x", "target": "x"}])
        accuracy_issue = check_issue(
            category="Mistranslation",
            severity="Major",
            comment="confirmed by accuracy",
            edit=replacement("x", "accurate"),
        )
        dropped_issue = check_issue(
            category="Mistranslation",
            severity="Major",
            comment="other module guess",
            edit=replacement("x", "guess"),
        )
        self.write_modules([0], issues_by_module={"accuracy": {0: [accuracy_issue]}})
        write_json(
            self.chunks / "chunk_00.out.json",
            [{"id": 0, "issues": [accuracy_issue, dropped_issue]}],
        )

        result = self.run_chunk("reconcile", "--job", self.job)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            read_json(self.chunks / "chunk_00.out.json"),
            [{"id": 0, "issues": [accuracy_issue]}],
        )

    def test_split_half_uses_module_checkpoint_name(self):
        self.make_job(
            [
                {"id": 0, "source": "a", "target": "a"},
                {"id": 1, "source": "b", "target": "b"},
            ]
        )
        checkpoint = self.chunks / "chunk_00.grammar.ckpt.jsonl"
        checkpoint.write_text(
            json.dumps({"id": 0, "issues": []})
            + "\n"
            + json.dumps({"id": 1, "issues": []})
            + "\n",
            encoding="utf-8",
        )

        result = self.run_chunk(
            "split-half",
            "--job",
            self.job,
            "--chunk",
            "0",
            "--module",
            "grammar",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.chunks / "chunk_00_p1.grammar.ckpt.jsonl").exists())
        self.assertTrue((self.chunks / "chunk_00_p2.grammar.ckpt.jsonl").exists())

    def test_old_check_command_names_and_lens_flag_are_removed(self):
        source = CHUNK_SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("merge-lenses", source)
        self.assertNotIn("validate-lenses", source)
        self.assertNotIn('"--lens"', source)


if __name__ == "__main__":
    unittest.main()
