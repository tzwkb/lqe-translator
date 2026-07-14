import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
IO_SCRIPT = SCRIPTS / "lqe_io.py"

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


if __name__ == "__main__":
    unittest.main()
