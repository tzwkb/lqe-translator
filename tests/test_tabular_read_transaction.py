import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
IO_SCRIPT = ROOT / "scripts" / "lqe_io.py"
sys.path.insert(0, str(ROOT / "scripts"))

import lqe_paths


class TabularReadPathSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.source = self.root / "source.csv"
        self.original = b"Source,Target\nA,Alpha\n"
        self.source.write_bytes(self.original)

    def tearDown(self):
        self.tempdir.cleanup()

    def run_read(self, out: Path, *extra: object) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(IO_SCRIPT),
                "read",
                "--input",
                str(self.source),
                "--source-col",
                "Source",
                "--target-col",
                "Target",
                "--no-terminology",
                "--out",
                str(out),
                *map(str, extra),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def assert_alias_rejected_without_mutation(self, out: Path) -> None:
        result = self.run_read(out)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--out path conflicts with --input", result.stderr)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(out.read_bytes(), self.original)
        self.assertFalse((out.parent / "scope.json").exists())

    def test_read_rejects_out_aliasing_input(self):
        self.assert_alias_rejected_without_mutation(self.source)

    def test_read_rejects_symlink_aliasing_input(self):
        alias = self.root / "state.json"
        alias.symlink_to(self.source)

        self.assert_alias_rejected_without_mutation(alias)
        self.assertTrue(alias.is_symlink())

    def test_read_rejects_hardlink_aliasing_input(self):
        alias = self.root / "state.json"
        os.link(self.source, alias)

        self.assert_alias_rejected_without_mutation(alias)

    def test_read_rejects_state_asset_collision_before_writing(self):
        style_guide = self.root / "guide.txt"
        style_guide.write_text("Keep terms consistent.", encoding="utf-8")
        out = self.root / "job" / "sg.txt"

        result = self.run_read(out, "--style-guide", style_guide)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--out path conflicts with generated asset", result.stderr)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(out.exists())
        self.assertFalse((out.parent / "scope.json").exists())

    def test_publish_transaction_rolls_back_on_base_exception(self):
        job = self.root / "job"
        staging = job / ".staging"
        staging.mkdir(parents=True)
        destinations = [job / "sg.txt", job / "scope.json", job / "state.json"]
        originals = {}
        replacements = []
        for index, destination in enumerate(destinations):
            original = f"old-{index}".encode()
            destination.write_bytes(original)
            originals[destination] = original
            staged = staging / destination.name
            staged.write_bytes(f"new-{index}".encode())
            replacements.append((staged, destination))

        real_replace = lqe_paths._replace_staged

        def fail_before_state(source: Path, destination: Path) -> None:
            if destination == destinations[-1]:
                raise KeyboardInterrupt("injected publication failure")
            real_replace(source, destination)

        with mock.patch.object(lqe_paths, "_replace_staged", fail_before_state):
            with self.assertRaises(KeyboardInterrupt):
                lqe_paths.publish_replacement_transaction(replacements)

        for destination, original in originals.items():
            self.assertEqual(destination.read_bytes(), original)
        self.assertEqual(
            sorted(path.name for path in job.iterdir()),
            [".staging", "scope.json", "sg.txt", "state.json"],
        )

    def test_tabular_read_publishes_scope_assets_and_state_consistently(self):
        style_guide = self.root / "guide.txt"
        style_guide.write_text("Keep terms consistent.", encoding="utf-8")
        out = self.root / "job" / "state.json"

        result = self.run_read(out, "--style-guide", style_guide)

        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(out.read_text(encoding="utf-8"))
        scope = json.loads((out.parent / "scope.json").read_text(encoding="utf-8"))
        self.assertEqual(scope, state["check_scope"])
        self.assertEqual(Path(state["sg_path"]), out.parent / "sg.txt")
        self.assertEqual((out.parent / "sg.txt").read_text(encoding="utf-8"), "Keep terms consistent.")
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(any(path.name.startswith(".read-assets.") for path in out.parent.iterdir()))


if __name__ == "__main__":
    unittest.main()
