import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
IO_SCRIPT = SCRIPTS / "lqe_io.py"
CHUNK_SCRIPT = SCRIPTS / "lqe_chunk.py"
BATCH_SCRIPT = SCRIPTS / "lqe_batch.py"

sys.path.insert(0, str(SCRIPTS))

from lqe_engine import (
    NO_TERMINOLOGY_REQUIRED_MODULES,
    OPTIONAL_MODULES,
    STANDARD_REQUIRED_MODULES,
    build_check_scope,
    disabled_modules,
    get_check_scope,
    load_terms,
    optional_modules,
    required_modules,
    scope_issue_problem,
    terminology_enabled,
    validate_scope_entries,
)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def flatten_issues(entries):
    return [issue for entry in entries for issue in entry.get("issues", [])]


class NoTerminologyScopeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.source = self.root / "source.csv"
        self.source.write_text("Source,Target\nA,Alpha\n", encoding="utf-8")
        self.terms = self.root / "project" / "terms.json"
        write_json(self.terms, [{"source": "A", "target": "Alpha"}])
        self.profile = self.root / "project" / "profile.json"
        write_json(
            self.profile,
            {
                "name": "fixture/zh-en",
                "language_pair": "zh-en",
                "source_lang": "zh",
                "target_lang": "en",
                "terminology": "terms.json",
            },
        )
        self.state = self.root / "job" / "state.json"

    def tearDown(self):
        self.tempdir.cleanup()

    def run_io(self, *args):
        return subprocess.run(
            [sys.executable, str(IO_SCRIPT), *map(str, args)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def test_build_check_scope_uses_fixed_module_contracts(self):
        self.assertEqual(
            build_check_scope(False),
            {
                "mode": "standard",
                "terminology_enabled": True,
                "enabled_modules": list(STANDARD_REQUIRED_MODULES),
                "disabled_modules": [],
                "source": "runtime",
            },
        )
        self.assertEqual(
            build_check_scope(True, "test"),
            {
                "mode": "no-terminology",
                "terminology_enabled": False,
                "enabled_modules": list(NO_TERMINOLOGY_REQUIRED_MODULES),
                "disabled_modules": ["terminology", "proper_names", "term_audit"],
                "source": "test",
            },
        )

    def test_profile_terms_are_not_loaded_when_disabled(self):
        result = self.run_io(
            "read",
            "--input",
            self.source,
            "--project",
            self.profile,
            "--source-col",
            "Source",
            "--target-col",
            "Target",
            "--no-terminology",
            "--out",
            self.state,
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
        self.assertEqual(
            read_json(self.state.parent / "scope.json"), state["check_scope"]
        )


        self.assertIn(
            "profile terminology overridden by --no-terminology", result.stdout
        )

    def test_explicit_terms_conflict_with_no_terminology(self):
        result = self.run_io(
            "read",
            "--input",
            self.source,
            "--source-col",
            "Source",
            "--target-col",
            "Target",
            "--terminology",
            self.terms,
            "--no-terminology",
            "--out",
            self.state,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not allowed with argument", result.stderr)
        self.assertFalse(self.state.exists())

    def test_out_cannot_replace_reserved_scope_artifact(self):
        scope_path = self.state.parent / "scope.json"
        scope_path.parent.mkdir(parents=True)
        original = b'{"keep": "original"}\n'
        scope_path.write_bytes(original)

        result = self.run_io(
            "read",
            "--input",
            self.source,
            "--source-col",
            "Source",
            "--target-col",
            "Target",
            "--no-terminology",
            "--out",
            scope_path,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "--out path conflicts with reserved scope artifact", result.stderr
        )
        self.assertEqual(scope_path.read_bytes(), original)
        self.assertEqual(
            {path.name for path in scope_path.parent.iterdir()}, {"scope.json"}
        )

    def test_out_case_variant_cannot_replace_reserved_scope_artifact(self):
        scope_path = self.state.parent / "scope.json"
        scope_path.parent.mkdir(parents=True)
        original = b'{"keep": "original"}\n'
        scope_path.write_bytes(original)

        result = self.run_io(
            "read",
            "--input",
            self.source,
            "--source-col",
            "Source",
            "--target-col",
            "Target",
            "--no-terminology",
            "--out",
            scope_path.with_name("SCOPE.JSON"),
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "--out path conflicts with reserved scope artifact", result.stderr
        )
        self.assertEqual(scope_path.read_bytes(), original)
        self.assertEqual(
            {path.name for path in scope_path.parent.iterdir()}, {"scope.json"}
        )

    def test_load_terms_cannot_bypass_disabled_scope(self):
        state = {
            "check_scope": build_check_scope(True),
            "terms_path": str(self.terms),
            "terminology": [{"source": "A", "target": "B"}],
        }

        self.assertEqual(load_terms(state), [])

    def test_malformed_scope_fails_with_contract_error(self):
        with self.assertRaisesRegex(ValueError, "state must be an object"):
            get_check_scope([])
        with self.assertRaisesRegex(ValueError, "check_scope must be an object"):
            get_check_scope({"check_scope": []})

    def test_scope_mode_rejects_unknown_or_conflicting_values(self):
        with self.assertRaisesRegex(ValueError, "unsupported check_scope mode"):
            get_check_scope({"check_scope": {"mode": "custom"}})

        for key, value in (
            ("terminology_enabled", False),
            ("enabled_modules", ["accuracy"]),
            ("disabled_modules", ["terminology"]),
        ):
            with self.subTest(key=key):
                raw = build_check_scope(False)
                raw[key] = value
                with self.assertRaisesRegex(ValueError, f"check_scope {key} conflicts"):
                    get_check_scope({"check_scope": raw})

    def test_legacy_state_uses_standard_scope_without_rewrite(self):
        state = {"segments": []}

        self.assertEqual(
            required_modules(state),
            ("terminology", "accuracy", "grammar", "naturalness"),
        )
        self.assertEqual(optional_modules(state), OPTIONAL_MODULES)
        self.assertEqual(disabled_modules(state), ())
        self.assertTrue(terminology_enabled(state))
        self.assertEqual(get_check_scope(state)["source"], "legacy-default")
        self.assertNotIn("check_scope", state)

    def test_no_terminology_scope_accessors_are_consistent(self):
        state = {"check_scope": build_check_scope(True)}

        self.assertEqual(required_modules(state), NO_TERMINOLOGY_REQUIRED_MODULES)
        self.assertEqual(optional_modules(state), ())
        self.assertEqual(
            disabled_modules(state), ("terminology", "proper_names", "term_audit")
        )
        self.assertFalse(terminology_enabled(state))

    def test_scope_issue_problem_rejects_all_terminology_evidence(self):
        state = {"check_scope": build_check_scope(True)}
        cases = (
            (None, "issue must be an object"),
            ({"category": "Terminology"}, "Terminology issue is disabled"),
            (
                {"category": "Other", "comment": "  TERM REVIEW: verify"},
                "TERM REVIEW evidence is disabled",
            ),
            (
                {
                    "category": "Other",
                    "edit": {"evidence": {"type": "confirmed_term"}},
                },
                "confirmed_term edit evidence is disabled",
            ),
        )
        for issue, message in cases:
            with self.subTest(message=message):
                self.assertIn(message, scope_issue_problem(state, issue))

        self.assertIsNone(
            scope_issue_problem(state, {"category": "Grammar", "comment": "Review"})
        )
        self.assertIsNone(scope_issue_problem({}, {"category": "Terminology"}))

    def test_validate_scope_entries_supports_check_and_final_shapes(self):
        state = {"check_scope": build_check_scope(True)}
        validate_scope_entries(
            state,
            [{"id": 0, "issues": [{"category": "Grammar"}]}],
            issues_key="issues",
            label="check",
        )

        for issues_key, issue in (
            ("issues", {"category": "Terminology"}),
            ("errors", {"comment": "TERM REVIEW: verify"}),
        ):
            with self.subTest(issues_key=issues_key):
                with self.assertRaisesRegex(
                    ValueError, rf"{issues_key}: scope conflict:"
                ):
                    validate_scope_entries(
                        state,
                        [{"id": 0, issues_key: [issue]}],
                        issues_key=issues_key,
                        label=issues_key,
                    )

        with self.assertRaisesRegex(ValueError, "unsupported issues key"):
            validate_scope_entries(state, [], issues_key="findings", label="bad")

    def test_standard_mode_still_loads_profile_terminology(self):
        result = self.run_io(
            "read",
            "--input",
            self.source,
            "--project",
            self.profile,
            "--source-col",
            "Source",
            "--target-col",
            "Target",
            "--out",
            self.state,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        state = read_json(self.state)
        self.assertTrue(terminology_enabled(state))
        self.assertTrue(load_terms(state))
        self.assertEqual(required_modules(state), STANDARD_REQUIRED_MODULES)
        self.assertEqual(state["check_scope"], build_check_scope(False))
        self.assertEqual(
            read_json(self.state.parent / "scope.json"), state["check_scope"]
        )


class NoTerminologyPrecheckTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.job = self.root / "job"
        self.state = self.job / "state.json"
        self.terms = self.job / "terms.json"
        self.read_no_term_job(
            [("生命值", "Health")],
            terms=[{"source": "生命值", "target": "HP", "confirmed": True}],
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def read_no_term_job(self, rows, *, terms=None):
        terms = terms or []
        write_json(self.terms, terms)
        segments = [
            {"id": index, "source": source, "target": target}
            for index, (source, target) in enumerate(rows)
        ]
        write_json(
            self.state,
            {
                "source_lang": "zh",
                "target_lang": "en",
                "segments": segments,
                "check_scope": build_check_scope(True, "test"),
                "terms_path": str(self.terms),
                "terminology": terms,
            },
        )
        write_json(
            self.job / "errors_precheck.json",
            [{"id": segment["id"], "issues": []} for segment in segments],
        )

    def run_script(self, script, *args):
        return subprocess.run(
            [sys.executable, str(script), *map(str, args)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def run_precheck(self, *, out=None):
        return self.run_script(
            IO_SCRIPT,
            "pre-check",
            "--state",
            self.state,
            "--out",
            out or self.job / "errors_precheck.json",
        )

    def run_chunk(self, *args):
        return self.run_script(CHUNK_SCRIPT, *args)

    def run_batch(self, *args):
        return self.run_script(BATCH_SCRIPT, *args)

    def write_batch_eval(self, *, category="Grammar", comment="check", edit=None):
        segments = read_json(self.state)["segments"]
        rows = [{"id": segment["id"], "issues": []} for segment in segments]
        rows[0]["issues"] = [
            {
                "category": category,
                "severity": "Major" if category == "Terminology" else "Minor",
                "comment": comment,
                "needs_confirmation": edit is None,
                "edit": edit,
            }
        ]
        write_json(self.job / "evals" / "eval_00.json", rows)

    def test_precheck_omits_terms_but_keeps_non_term_checks(self):
        self.read_no_term_job(
            [
                ("生命值", "Health"),
                ("<b>你好</b>", "Hello"),
                ("获得 100 金币 {0}", "Get 10 coins"),
                ("点击开始", "Click Start"),
                ("点击开始", "Tap Begin"),
            ],
            terms=[{"source": "生命值", "target": "HP", "confirmed": True}],
        )

        result = self.run_precheck()

        self.assertEqual(result.returncode, 0, result.stderr)
        issues = flatten_issues(read_json(self.job / "errors_precheck.json"))
        self.assertFalse(any(issue["category"] == "Terminology" for issue in issues))
        self.assertFalse(
            any(issue["comment"].startswith("TERM REVIEW:") for issue in issues)
        )
        self.assertTrue(any(issue["category"] == "Markup" for issue in issues))
        self.assertTrue(any(issue["category"] == "Inconsistency" for issue in issues))
        self.assertTrue(
            any("100" in issue["comment"] or "{0}" in issue["comment"] for issue in issues)
        )

    def test_precheck_rejects_scope_forbidden_custom_issue_before_write(self):
        checks = self.job / "checks.json"
        write_json(
            checks,
            {
                "custom": [
                    {
                        "id": "forbidden-term",
                        "pattern": "Health",
                        "where": "target",
                        "category": "Terminology",
                        "comment": "forbidden custom terminology issue",
                    }
                ]
            },
        )
        state = read_json(self.state)
        state["checks_path"] = str(checks)
        write_json(self.state, state)
        output = self.job / "forbidden_precheck.json"

        result = self.run_precheck(out=output)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scope conflict", result.stderr)
        self.assertFalse(output.exists())

    def test_split_without_terms_writes_empty_term_context(self):
        result = self.run_chunk(
            "split",
            "--state",
            self.state,
            "--errors",
            self.job / "errors_precheck.json",
            "--outdir",
            self.job / "chunks",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        segment = read_json(self.job / "chunks" / "chunk_00.json")["segments"][0]
        self.assertEqual(segment["term_hits"], [])
        self.assertEqual(segment["term_near"], [])

    def test_split_rejects_explicit_terms_in_disabled_scope(self):
        result = self.run_chunk(
            "split",
            "--state",
            self.state,
            "--errors",
            self.job / "errors_precheck.json",
            "--terms",
            self.terms,
            "--outdir",
            self.job / "chunks",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scope conflict", result.stderr)

    def test_batch_plan_ignores_residual_terms_file(self):
        write_json(self.job / "terms.json", [{"source": "生命值", "target": "HP"}])

        result = self.run_batch("plan", "--job", self.job)

        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = (self.job / "batches" / "batch_00.txt").read_text(encoding="utf-8")
        self.assertNotIn("TERMS:", prompt)
        self.assertIn("Terminology check: disabled", prompt)

    def test_batch_merge_rejects_terminology_issue(self):
        self.write_batch_eval(category="Terminology", comment="forbidden")

        result = self.run_batch("merge", "--job", self.job)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scope conflict", result.stderr)
        self.assertFalse((self.job / "errors.json").exists())

    def test_batch_merge_rejects_other_disabled_term_evidence(self):
        cases = (
            {"comment": "TERM REVIEW: forbidden", "edit": None},
            {
                "comment": "forbidden evidence",
                "edit": {
                    "from": "Health",
                    "to": "HP",
                    "start": 0,
                    "end": 6,
                    "evidence": {
                        "type": "confirmed_term",
                        "source": "生命值",
                        "target": "HP",
                    },
                },
            },
        )
        for case in cases:
            with self.subTest(comment=case["comment"]):
                self.write_batch_eval(comment=case["comment"], edit=case["edit"])
                result = self.run_batch("merge", "--job", self.job)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("scope conflict", result.stderr)
                self.assertFalse((self.job / "errors.json").exists())


if __name__ == "__main__":
    unittest.main()
