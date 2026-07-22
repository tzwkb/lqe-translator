import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
MASTERTB = SCRIPTS / "mastertb_prep.py"
LQE_CHUNK = SCRIPTS / "lqe_chunk.py"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class MasterTBModuleContractTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.job = Path(self.tempdir.name) / "mastertb"
        write_json(
            self.job / "state.json",
            {
                "segments": [
                    {"id": 0, "source": "花衣蝶", "target": "ผีเสื้อบุปผา"}
                ]
            },
        )
        write_json(
            self.job / "context.json",
            {
                "0": {
                    "zhcn": "花衣蝶",
                    "en": "Floral Butterfly",
                    "definition": "Named creature",
                    "category": "Creature Species",
                    "gender": "",
                    "former": "",
                    "th": "ผีเสื้อบุปผา",
                    "th_comment": "",
                    "th_status": "Approved",
                    "scope": "Creatures",
                }
            },
        )
        self.precheck_issue = {
            "category": "Punctuation",
            "severity": "Minor",
            "comment": "Check punctuation",
            "needs_confirmation": True,
            "edit": None,
        }
        write_json(
            self.job / "errors_precheck.json",
            [{"id": 0, "issues": [self.precheck_issue]}],
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def run_script(self, script: Path, *args):
        return subprocess.run(
            [sys.executable, str(script), *map(str, args)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def test_chunks_use_current_check_module_contract(self):
        result = self.run_script(
            MASTERTB,
            "chunks",
            "--job-dir",
            self.job,
            "--size",
            "10",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        chunk = json.loads(
            (self.job / "chunks" / "chunk_00.json").read_text(encoding="utf-8")
        )
        self.assertIn("chunk_id", chunk)
        self.assertEqual(chunk["chunk_id"], 0)
        self.assertNotIn("terms", chunk)
        segment = chunk["segments"][0]
        precheck = dict(segment["precheck"][0])
        precheck_ref = precheck.pop("precheck_ref")
        self.assertTrue(precheck_ref.startswith("precheck:0:"))
        segment = {**segment, "precheck": [precheck]}
        self.assertEqual(
            segment,
            {
                "id": 0,
                "source": "花衣蝶",
                "target": "ผีเสื้อบุปผา",
                "kind": "name",
                "precheck": [self.precheck_issue],
                "term_hits": [],
                "term_near": [],
                "protected": False,
                "protected_texts": [],
                "en": "Floral Butterfly",
                "definition": "Named creature",
                "category": "Creature Species",
                "gender": "",
                "former": "",
                "target_comment": "",
                "target_status": "Approved",
                "scope": "Creatures",
            },
        )
        for module in ("terminology", "accuracy", "grammar", "naturalness"):
            self.assertIn(f"chunk_NN.{module}.json", result.stdout)
        self.assertIn("chunk_NN.proper_names.json", result.stdout)
        self.assertIn("validate-checks --job", result.stdout)
        self.assertIn("merge-checks --job", result.stdout)

    def test_current_modules_validate_merge_and_mark_complete(self):
        chunks = self.run_script(
            MASTERTB,
            "chunks",
            "--job-dir",
            self.job,
            "--size",
            "10",
        )
        self.assertEqual(chunks.returncode, 0, chunks.stderr)
        for module in ("terminology", "accuracy", "grammar", "naturalness"):
            write_json(
                self.job / "chunks" / f"chunk_00.{module}.json",
                [{"id": 0, "issues": []}],
            )

        validated = self.run_script(
            LQE_CHUNK, "validate-checks", "--job", self.job
        )
        self.assertEqual(validated.returncode, 0, validated.stderr)
        merged_modules = self.run_script(
            LQE_CHUNK, "merge-checks", "--job", self.job
        )
        self.assertEqual(merged_modules.returncode, 0, merged_modules.stderr)
        self.assertFalse(
            (self.job / "chunks" / "chunk_00.proper_names.json").exists()
        )

        merged_job = self.run_script(
            MASTERTB,
            "merge",
            "--job-dir",
            self.job,
            "--no-consistency",
        )

        self.assertEqual(merged_job.returncode, 0, merged_job.stderr)
        status = json.loads(
            (self.job / "recall_status.json").read_text(encoding="utf-8")
        )
        self.assertTrue(status["checks_complete"])
        self.assertTrue(status["verdict_allowed"])
        self.assertEqual(status["incomplete_chunks"], [])
        errors = json.loads(
            (self.job / "errors.json").read_text(encoding="utf-8")
        )
        self.assertEqual(errors, [{"id": 0, "errors": [], "corrected": None}])

    def test_chunks_write_current_check_context(self):
        result = self.run_script(
            MASTERTB,
            "chunks",
            "--job-dir",
            self.job,
            "--size",
            "10",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        context_path = self.job / "chunks" / "_CHECK_CONTEXT.md"
        self.assertTrue(context_path.is_file())
        context = context_path.read_text(encoding="utf-8")
        self.assertIn("`segments[]`", context)
        self.assertIn("references/check_modules/common.md", context)
        self.assertIn("references/check_modules/term_audit.md", context)
        self.assertIn('"issues"', context)
        self.assertIn('"needs_confirmation"', context)
        self.assertIn('"edit"', context)
        self.assertNotIn("`terms[]`", context)
        self.assertNotIn('"findings"', context)
        self.assertNotIn("reviewed_first", context)

    def test_merge_stops_when_merge_checks_was_not_run(self):
        chunks = self.run_script(
            MASTERTB,
            "chunks",
            "--job-dir",
            self.job,
            "--size",
            "10",
        )
        self.assertEqual(chunks.returncode, 0, chunks.stderr)
        for module in ("terminology", "accuracy", "grammar", "naturalness"):
            write_json(
                self.job / "chunks" / f"chunk_00.{module}.json",
                [{"id": 0, "issues": []}],
            )

        result = self.run_script(
            MASTERTB,
            "merge",
            "--job-dir",
            self.job,
            "--no-consistency",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("merge-checks", result.stderr)
        self.assertFalse((self.job / "errors.json").exists())

    def test_merge_stops_when_merged_output_has_missing_ids(self):
        chunks = self.run_script(
            MASTERTB,
            "chunks",
            "--job-dir",
            self.job,
            "--size",
            "10",
        )
        self.assertEqual(chunks.returncode, 0, chunks.stderr)
        for module in ("terminology", "accuracy", "grammar", "naturalness"):
            write_json(
                self.job / "chunks" / f"chunk_00.{module}.json",
                [{"id": 0, "issues": []}],
            )
        write_json(self.job / "chunks" / "chunk_00.out.json", [])

        result = self.run_script(
            MASTERTB,
            "merge",
            "--job-dir",
            self.job,
            "--no-consistency",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing=[0]", result.stderr)
        self.assertFalse((self.job / "errors.json").exists())

    def test_merge_rejects_legacy_findings_wrapper(self):
        chunks = self.run_script(
            MASTERTB,
            "chunks",
            "--job-dir",
            self.job,
            "--size",
            "10",
        )
        self.assertEqual(chunks.returncode, 0, chunks.stderr)
        for module in ("terminology", "accuracy", "grammar", "naturalness"):
            write_json(
                self.job / "chunks" / f"chunk_00.{module}.json",
                [{"id": 0, "issues": []}],
            )
        write_json(
            self.job / "chunks" / "chunk_00.out.json",
            {"findings": [{"id": 0, "issues": []}]},
        )

        result = self.run_script(
            MASTERTB,
            "merge",
            "--job-dir",
            self.job,
            "--no-consistency",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("module output envelope fields are invalid", result.stderr)
        self.assertFalse((self.job / "errors.json").exists())


if __name__ == "__main__":
    unittest.main()
