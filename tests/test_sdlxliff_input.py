import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURES = ROOT / "tests" / "fixtures" / "sdlxliff"
RECURSIVE_FIXTURES = FIXTURES / "recursive"

sys.path.insert(0, str(SCRIPTS))

from lqe_inputs import detect_input_format
from lqe_inputs.sdlxliff import (
    SDLXLIFFImportError,
    SDLXLIFFOptions,
    SerializedMixedContent,
    read_sdlxliff,
    serialize_mixed,
)


XLIFF_NS = "urn:oasis:names:tc:xliff:document:1.2"
SDL_NS = "http://sdl.com/FileTypes/SdlXliff/1.0"
XLIFF_QNAME = "{" + XLIFF_NS + "}"
EXPECTED_SIGNATURE = (
    (XLIFF_QNAME + "g", (("id", "g1"),)),
    (XLIFF_QNAME + "x", (("id", "x1"),)),
    (XLIFF_QNAME + "bx", (("id", "bx1"),)),
    (XLIFF_QNAME + "ex", (("id", "ex1"),)),
    (XLIFF_QNAME + "ph", (("id", "ph1"),)),
    (XLIFF_QNAME + "bpt", (("id", "bpt1"),)),
    (XLIFF_QNAME + "ept", (("id", "ept1"),)),
    (XLIFF_QNAME + "it", (("id", "it1"),)),
    (XLIFF_QNAME + "sub", ()),
    (XLIFF_QNAME + "mrk", (("mid", "inner1"), ("mtype", "protected"))),
)
EXPECTED_SOURCE_PLAIN = " 前组尾子内值尾末 后 "
SOURCE_REF_KEYS = (
    "relative_path",
    "file_index",
    "tu_id",
    "tu_index",
    "sdl_segment_id",
    "segment_index",
)


class SDLXLIFFFormatDetectionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def touch(self, relative_path: str) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
        return path

    def copy_sdl(self, relative_path: str) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(FIXTURES / "multi_segment.sdlxliff", path)
        return path

    def test_single_file_auto_and_explicit_formats(self):
        sdl = self.copy_sdl("sample.sdlxliff")
        csv = self.touch("sample.csv")

        self.assertEqual(detect_input_format(sdl, "auto"), "sdlxliff")
        self.assertEqual(detect_input_format(csv, "auto"), "tabular")
        self.assertEqual(detect_input_format(sdl, "sdlxliff"), "sdlxliff")
        self.assertEqual(detect_input_format(csv, "tabular"), "tabular")

    def test_invalid_request_unknown_suffix_and_explicit_mismatch_fail(self):
        sdl = self.copy_sdl("sample.sdlxliff")
        unknown = self.touch("sample.txt")

        with self.assertRaisesRegex(ValueError, "requested"):
            detect_input_format(sdl, "xml")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            detect_input_format(unknown, "auto")
        with self.assertRaisesRegex(ValueError, "does not match"):
            detect_input_format(sdl, "tabular")

    def test_auto_directory_requires_only_sdlxliff(self):
        self.copy_sdl("a/dialogs.sdlxliff")
        self.copy_sdl("b.sdlxliff")

        self.assertEqual(detect_input_format(self.root, "auto"), "sdlxliff")

        self.touch("notes.csv")
        with self.assertRaisesRegex(ValueError, "mixed"):
            detect_input_format(self.root, "auto")

    def test_empty_and_tabular_directories_are_not_supported(self):
        with self.assertRaisesRegex(ValueError, "no supported"):
            detect_input_format(self.root, "auto")

        self.touch("only.csv")
        with self.assertRaisesRegex(ValueError, "tabular director"):
            detect_input_format(self.root, "auto")
        with self.assertRaisesRegex(ValueError, "tabular director"):
            detect_input_format(self.root, "tabular")

    def test_explicit_sdl_directory_allows_unselected_supported_files(self):
        self.copy_sdl("a/dialogs.sdlxliff")
        self.touch("notes.csv")

        self.assertEqual(detect_input_format(self.root, "sdlxliff"), "sdlxliff")
        result = read_sdlxliff(self.root, options=SDLXLIFFOptions())
        self.assertEqual(result.manifest["unselected_supported_files"], ["notes.csv"])


class SDLXLIFFParserTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def temp_fixture(self, name: str, content: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def document(self, body: str, *, version: str = "1.2", namespace: str = XLIFF_NS) -> str:
        return (
            f'<xliff version="{version}" xmlns="{namespace}" xmlns:sdl="{SDL_NS}">'
            f'<file original="anonymous.xml" source-language="zh-CN" target-language="en-US">'
            f"<body>{body}</body></file></xliff>"
        )

    def test_imports_all_files_and_multiple_mrk_in_order(self):
        result = read_sdlxliff(
            FIXTURES / "multi_segment.sdlxliff", options=SDLXLIFFOptions()
        )

        self.assertEqual([segment["id"] for segment in result.segments], [0, 1, 2])
        self.assertEqual(
            [segment["source_ref"]["sdl_segment_id"] for segment in result.segments],
            ["1", "2", "3"],
        )
        self.assertEqual(
            result.segments[0]["source_ref"]["relative_path"],
            "multi_segment.sdlxliff",
        )
        self.assertEqual(
            [segment["metadata"]["sdlxliff"]["file_original"] for segment in result.segments],
            ["dialogs.xml", "dialogs.xml", "ui.xml"],
        )
        self.assertEqual(result.source_lang, "zh-CN")
        self.assertEqual(result.target_lang, "en-US")
        self.assertEqual(
            result.headers,
            ["来源文件", "TU ID", "SDL Segment ID", "原文", "译文"],
        )
        self.assertEqual(len(result.rows_raw), 3)

    def test_recursive_directory_order_and_missing_ids_are_stable(self):
        first = read_sdlxliff(RECURSIVE_FIXTURES, options=SDLXLIFFOptions())
        second = read_sdlxliff(RECURSIVE_FIXTURES, options=SDLXLIFFOptions())
        first_refs = [segment["source_ref"] for segment in first.segments]
        second_refs = [segment["source_ref"] for segment in second.segments]

        self.assertEqual(first_refs, second_refs)
        relative_paths = [ref["relative_path"] for ref in first_refs]
        self.assertEqual(relative_paths, sorted(relative_paths))
        self.assertEqual(len(first_refs), len({tuple(ref.values()) for ref in first_refs}))
        self.assertTrue(any(ref["tu_id"] is None for ref in first_refs))
        self.assertTrue(any(ref["sdl_segment_id"] is None for ref in first_refs))
        self.assertTrue(all(tuple(ref) == SOURCE_REF_KEYS for ref in first_refs))
        self.assertTrue(all(isinstance(ref["tu_index"], int) for ref in first_refs))
        self.assertEqual(
            first.input_paths,
            [
                str((RECURSIVE_FIXTURES / "a" / "dialogs.sdlxliff").resolve()),
                str((RECURSIVE_FIXTURES / "b.sdlxliff").resolve()),
            ],
        )

    def test_reads_status_comment_modifier_empty_target_and_tm_metadata(self):
        result = read_sdlxliff(RECURSIVE_FIXTURES, options=SDLXLIFFOptions())
        by_tu = {
            (segment["source_ref"]["relative_path"], segment["source_ref"]["tu_id"]): segment
            for segment in result.segments
        }
        metadata = by_tu[("a/dialogs.sdlxliff", "shared-tu")]["metadata"]["sdlxliff"]

        self.assertEqual(metadata["confirmation"], "Translated")
        self.assertEqual(metadata["comment"], "Anonymous review note")
        self.assertEqual(metadata["last_modified_by"], "AnonymousUser")
        self.assertEqual(by_tu[("b.sdlxliff", "empty-target")]["target_plain"], "")
        self.assertEqual(by_tu[("b.sdlxliff", "blank-both")]["source_plain"], "")
        self.assertEqual(by_tu[("b.sdlxliff", "blank-both")]["target_plain"], "")
        self.assertEqual(
            by_tu[("b.sdlxliff", "tm-negative-origin")]["metadata"]["sdlxliff"]["origin"],
            "machine",
        )
        self.assertEqual(
            by_tu[("b.sdlxliff", "tm-negative-percent")]["metadata"]["sdlxliff"]["match_percent"],
            "99",
        )
        self.assertEqual(
            by_tu[("b.sdlxliff", "tm-negative-match")]["metadata"]["sdlxliff"]["text_match"],
            "Fuzzy",
        )

    def test_missing_target_node_produces_an_empty_target(self):
        fixture = self.temp_fixture(
            "missing-target.sdlxliff",
            self.document(
                '<trans-unit id="tu"><source>甲</source>'
                '<sdl:seg-defs><sdl:seg id="1"/></sdl:seg-defs></trans-unit>'
            ),
        )

        result = read_sdlxliff(fixture, options=SDLXLIFFOptions())

        self.assertEqual(result.segments[0]["target"], "")
        self.assertEqual(result.segments[0]["target_plain"], "")

    def test_mixed_content_preserves_tags_tails_whitespace_and_extensions(self):
        result = read_sdlxliff(
            FIXTURES / "extensions.sdlxliff", options=SDLXLIFFOptions()
        )
        segment = result.segments[0]
        metadata = segment["metadata"]["sdlxliff"]

        self.assertTrue(segment["source"].startswith(" "))
        self.assertTrue(segment["source"].endswith(" "))
        self.assertIn('<g id="g1">', segment["source"])
        self.assertIn("尾</g>", segment["source"])
        self.assertEqual(segment["source_plain"], EXPECTED_SOURCE_PLAIN)
        self.assertEqual(metadata["source_tag_signature"], EXPECTED_SIGNATURE)
        self.assertIn("urn:vendor:test", metadata["source_raw_xml"])
        self.assertIn("urn:vendor:test", metadata["extension_xml"][0])
        self.assertIn("urn:vendor:test", result.manifest["extension_namespaces"])
        self.assertNotIn(
            "QUJDREVGR0g=",
            json.dumps(
                {"manifest": result.manifest, "segments": result.segments},
                ensure_ascii=False,
            ),
        )
        self.assertEqual(
            result.manifest["files"][0]["internal_file"],
            {"present": True, "size": 12},
        )

    def test_public_serializer_has_literal_display_plain_raw_and_signature(self):
        element = ET.fromstring(
            f'<source xmlns="{XLIFF_NS}" xmlns:v="urn:vendor:test"> '
            '<g id="g1">甲<x id="x1"/>乙</g><v:meta code="m">丙</v:meta> '
            "</source>"
        )

        serialized = serialize_mixed(
            element,
            {"": XLIFF_NS, "v": "urn:vendor:test"},
        )

        self.assertIsInstance(serialized, SerializedMixedContent)
        self.assertEqual(
            serialized.display,
            ' <g id="g1">甲<x id="x1"/>乙</g><v:meta code="m">丙</v:meta> ',
        )
        self.assertEqual(serialized.plain, " 甲乙丙 ")
        self.assertIn('xmlns="urn:oasis:names:tc:xliff:document:1.2"', serialized.raw_xml)
        self.assertIn('xmlns:v="urn:vendor:test"', serialized.raw_xml)
        self.assertEqual(
            serialized.tag_signature,
            (
                (XLIFF_QNAME + "g", (("id", "g1"),)),
                (XLIFF_QNAME + "x", (("id", "x1"),)),
            ),
        )

    def test_plain_excludes_native_inline_code_but_keeps_subflow_text(self):
        element = ET.fromstring(
            f'<source xmlns="{XLIFF_NS}">甲'
            '<bpt id="b1">&lt;b&gt;</bpt>乙<sub>丙</sub>'
            '<ept id="e1">&lt;/b&gt;</ept>丁<ph id="p1">{{0}}</ph>戊'
            "</source>"
        )

        serialized = serialize_mixed(element, {"": XLIFF_NS})

        self.assertEqual(serialized.plain, "甲乙丙丁戊")

    def test_xliff2_and_ambiguous_mid_fail_with_file_context(self):
        xliff2 = self.temp_fixture(
            "xliff2.xlf",
            self.document(
                '<trans-unit id="tu"><source>A</source><target>B</target></trans-unit>',
                version="2.0",
                namespace="urn:oasis:names:tc:xliff:document:2.0",
            ),
        )
        bad_mid = self.temp_fixture(
            "bad_mid.sdlxliff",
            self.document(
                '<trans-unit id="tu"><seg-source><mrk mtype="seg" mid="1">A</mrk></seg-source>'
                '<target><mrk mtype="seg" mid="2">B</mrk></target>'
                '<sdl:seg-defs><sdl:seg id="1"/></sdl:seg-defs></trans-unit>'
            ),
        )

        for fixture, message in ((xliff2, "XLIFF 1.2"), (bad_mid, "mid")):
            with self.subTest(fixture=fixture.name):
                with self.assertRaisesRegex(SDLXLIFFImportError, message) as caught:
                    read_sdlxliff(fixture, options=SDLXLIFFOptions())
                self.assertIn(fixture.name, str(caught.exception))

    def test_invalid_xml_namespace_and_missing_source_fail_fast(self):
        invalid = self.temp_fixture("invalid.sdlxliff", "<xliff>")
        fake = self.temp_fixture(
            "fake.sdlxliff",
            '<xliff version="1.2" xmlns:sdl="http://example.invalid/sdl"/>',
        )
        missing = self.temp_fixture(
            "missing-source.sdlxliff",
            self.document('<trans-unit id="tu"><target>B</target></trans-unit>'),
        )

        cases = (
            (invalid, "line"),
            (fake, "XLIFF 1.2"),
            (missing, "source"),
        )
        for fixture, message in cases:
            with self.subTest(fixture=fixture.name):
                with self.assertRaisesRegex(SDLXLIFFImportError, message) as caught:
                    read_sdlxliff(fixture, options=SDLXLIFFOptions())
                self.assertIn(fixture.name, str(caught.exception))

    def test_duplicate_business_key_duplicate_mid_and_unbounded_seg_defs_fail(self):
        duplicate_key = self.temp_fixture(
            "duplicate-key.sdlxliff",
            self.document(
                '<trans-unit id="same"><source>A</source><target>B</target>'
                '<sdl:seg-defs><sdl:seg id="1"/></sdl:seg-defs></trans-unit>'
                '<trans-unit id="same"><source>C</source><target>D</target>'
                '<sdl:seg-defs><sdl:seg id="1"/></sdl:seg-defs></trans-unit>'
            ),
        )
        duplicate_mid = self.temp_fixture(
            "duplicate-mid.sdlxliff",
            self.document(
                '<trans-unit id="tu"><seg-source>'
                '<mrk mtype="seg" mid="1">A</mrk><mrk mtype="seg" mid="1">B</mrk>'
                '</seg-source><target><mrk mtype="seg" mid="1">C</mrk></target>'
                '<sdl:seg-defs><sdl:seg id="1"/></sdl:seg-defs></trans-unit>'
            ),
        )
        unbounded = self.temp_fixture(
            "unbounded.sdlxliff",
            self.document(
                '<trans-unit id="tu"><source>A</source><target>B</target><sdl:seg-defs>'
                '<sdl:seg id="1"/><sdl:seg id="2"/></sdl:seg-defs></trans-unit>'
            ),
        )

        for fixture, message in (
            (duplicate_key, "duplicate"),
            (duplicate_mid, "duplicate mid"),
            (unbounded, "seg-def"),
        ):
            with self.subTest(fixture=fixture.name):
                with self.assertRaisesRegex(SDLXLIFFImportError, message):
                    read_sdlxliff(fixture, options=SDLXLIFFOptions())

    def test_segmented_content_requires_matching_seg_definitions(self):
        fixture = self.temp_fixture(
            "missing-seg-defs.sdlxliff",
            self.document(
                '<trans-unit id="tu"><seg-source>'
                '<mrk mtype="seg" mid="1">A</mrk><mrk mtype="seg" mid="2">B</mrk>'
                '</seg-source><target><mrk mtype="seg" mid="1">C</mrk>'
                '<mrk mtype="seg" mid="2">D</mrk></target></trans-unit>'
            ),
        )

        with self.assertRaisesRegex(SDLXLIFFImportError, "seg-def"):
            read_sdlxliff(fixture, options=SDLXLIFFOptions())

    def test_structural_unknown_extension_fails_instead_of_guessing_boundaries(self):
        fixture = self.temp_fixture(
            "ambiguous-extension.sdlxliff",
            f'<xliff version="1.2" xmlns="{XLIFF_NS}" xmlns:sdl="{SDL_NS}" '
            'xmlns:v="urn:vendor:ambiguous"><file original="anonymous.xml"><body>'
            '<trans-unit id="tu"><seg-source><v:segments>'
            '<mrk mtype="seg" mid="1">A</mrk></v:segments></seg-source>'
            '<target><mrk mtype="seg" mid="1">B</mrk></target>'
            '<sdl:seg-defs><sdl:seg id="1"/></sdl:seg-defs>'
            "</trans-unit></body></file></xliff>",
        )

        with self.assertRaisesRegex(SDLXLIFFImportError, "urn:vendor:ambiguous"):
            read_sdlxliff(fixture, options=SDLXLIFFOptions())


if __name__ == "__main__":
    unittest.main()
