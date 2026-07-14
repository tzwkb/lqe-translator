import hashlib
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
    is_exact_tm,
    match_content_type,
    match_exclusions,
    read_sdlxliff,
    serialize_mixed,
    validate_options,
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

    def test_rows_raw_uses_empty_strings_for_missing_business_ids(self):
        result = read_sdlxliff(RECURSIVE_FIXTURES, options=SDLXLIFFOptions())
        missing_id_indexes = [
            index
            for index, segment in enumerate(result.segments)
            if segment["source_ref"]["tu_id"] is None
            or segment["source_ref"]["sdl_segment_id"] is None
        ]

        self.assertTrue(missing_id_indexes)
        self.assertTrue(
            all(isinstance(cell, str) for row in result.rows_raw for cell in row)
        )
        for index in missing_id_indexes:
            source_ref = result.segments[index]["source_ref"]
            row = result.rows_raw[index]
            self.assertEqual(row[1], source_ref["tu_id"] or "")
            self.assertEqual(row[2], source_ref["sdl_segment_id"] or "")

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
        self.assertNotIn(("b.sdlxliff", "blank-both"), by_tu)
        self.assertEqual(
            result.manifest["excluded"][0]["source_ref"]["tu_id"], "blank-both"
        )
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

    def test_tu_extension_cannot_hide_a_second_structural_boundary(self):
        fixture = self.temp_fixture(
            "hidden-tu-boundary.sdlxliff",
            f'<xliff version="1.2" xmlns="{XLIFF_NS}" xmlns:sdl="{SDL_NS}" '
            'xmlns:v="urn:vendor:ambiguous"><file original="anonymous.xml"><body>'
            '<trans-unit id="outer"><source>A</source><target>B</target>'
            '<v:wrapper><source>Hidden</source></v:wrapper>'
            '<sdl:seg-defs><sdl:seg id="1"/></sdl:seg-defs>'
            "</trans-unit></body></file></xliff>",
        )

        with self.assertRaisesRegex(
            SDLXLIFFImportError, "urn:vendor:ambiguous"
        ) as caught:
            read_sdlxliff(fixture, options=SDLXLIFFOptions())
        self.assertIn("hidden-tu-boundary.sdlxliff", str(caught.exception))
        self.assertIn("TU 'outer'", str(caught.exception))

    def test_vendor_inline_cannot_hide_nested_segmentation_boundary(self):
        fixture = self.temp_fixture(
            "nested-segment-boundary.sdlxliff",
            f'<xliff version="1.2" xmlns="{XLIFF_NS}" xmlns:sdl="{SDL_NS}" '
            'xmlns:v="urn:vendor:inline"><file original="anonymous.xml"><body>'
            '<trans-unit id="outer"><seg-source><mrk mtype="seg" mid="1">'
            'A<v:inline><mrk mtype="seg" mid="hidden">B</mrk></v:inline>'
            '</mrk></seg-source><target><mrk mtype="seg" mid="1">C</mrk></target>'
            '<sdl:seg-defs><sdl:seg id="1"/></sdl:seg-defs>'
            "</trans-unit></body></file></xliff>",
        )

        with self.assertRaisesRegex(SDLXLIFFImportError, "nested.*segmentation") as caught:
            read_sdlxliff(fixture, options=SDLXLIFFOptions())
        self.assertIn("nested-segment-boundary.sdlxliff", str(caught.exception))
        self.assertIn("TU 'outer'", str(caught.exception))

    def test_nested_vendor_metadata_is_preserved_once_outside_mixed_content(self):
        fixture = self.temp_fixture(
            "nested-metadata.sdlxliff",
            f'<xliff version="1.2" xmlns="{XLIFF_NS}" xmlns:sdl="{SDL_NS}" '
            'xmlns:v="urn:vendor:metadata"><file original="anonymous.xml"><body>'
            '<trans-unit id="tu"><source>A<v:inline>Visible</v:inline></source>'
            '<target>B</target><sdl:seg-defs><sdl:seg id="1"><sdl:values>'
            '<v:note code="anonymous"><v:item>Nested anonymous metadata</v:item></v:note>'
            '</sdl:values></sdl:seg></sdl:seg-defs></trans-unit>'
            "</body></file></xliff>",
        )

        result = read_sdlxliff(fixture, options=SDLXLIFFOptions())
        extension_xml = result.segments[0]["metadata"]["sdlxliff"]["extension_xml"]

        self.assertEqual(len(extension_xml), 1)
        self.assertIn("urn:vendor:metadata", extension_xml[0])
        self.assertEqual(extension_xml[0].count("Nested anonymous metadata"), 1)
        self.assertNotIn("v:inline", extension_xml[0])
        self.assertIn("v:inline", result.segments[0]["source"])

    def test_segment_extensions_keep_seg_def_ownership(self):
        result = read_sdlxliff(
            FIXTURES / "segmented_extensions.sdlxliff",
            options=SDLXLIFFOptions(),
        )
        first = "\n".join(
            result.segments[0]["metadata"]["sdlxliff"]["extension_xml"]
        )
        second = "\n".join(
            result.segments[1]["metadata"]["sdlxliff"]["extension_xml"]
        )

        self.assertIn("Shared anonymous metadata", first)
        self.assertIn("First segment metadata", first)
        self.assertNotIn("Second segment metadata", first)
        self.assertIn("Shared anonymous metadata", second)
        self.assertIn("Second segment metadata", second)
        self.assertNotIn("First segment metadata", second)

    def test_direct_boundaries_are_unique_but_source_and_seg_source_can_coexist(self):
        legal = self.temp_fixture(
            "source-and-seg-source.sdlxliff",
            self.document(
                '<trans-unit id="legal"><source>Full source</source><seg-source>'
                '<mrk mtype="seg" mid="1">Segment source</mrk></seg-source>'
                '<target><mrk mtype="seg" mid="1">Target</mrk></target>'
                '<sdl:seg-defs><sdl:seg id="1"/></sdl:seg-defs></trans-unit>'
            ),
        )
        legal_result = read_sdlxliff(legal, options=SDLXLIFFOptions())
        self.assertEqual(legal_result.segments[0]["source_plain"], "Segment source")

        duplicate_nodes = {
            "source": (
                '<source>A</source><source>B</source><target>C</target>'
                '<sdl:seg-defs><sdl:seg id="1"/></sdl:seg-defs>'
            ),
            "target": (
                '<source>A</source><target>B</target><target>C</target>'
                '<sdl:seg-defs><sdl:seg id="1"/></sdl:seg-defs>'
            ),
            "seg-source": (
                '<seg-source><mrk mtype="seg" mid="1">A</mrk></seg-source>'
                '<seg-source><mrk mtype="seg" mid="2">B</mrk></seg-source>'
                '<target><mrk mtype="seg" mid="1">C</mrk></target>'
                '<sdl:seg-defs><sdl:seg id="1"/></sdl:seg-defs>'
            ),
        }
        for name, content in duplicate_nodes.items():
            with self.subTest(name=name):
                fixture = self.temp_fixture(
                    f"duplicate-{name}.sdlxliff",
                    self.document(f'<trans-unit id="duplicate">{content}</trans-unit>'),
                )
                with self.assertRaisesRegex(
                    SDLXLIFFImportError, f"multiple direct {name}"
                ) as caught:
                    read_sdlxliff(fixture, options=SDLXLIFFOptions())
                self.assertIn(fixture.name, str(caught.exception))
                self.assertIn("TU 'duplicate'", str(caught.exception))

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


class SDLXLIFFRuleTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def temp_fixture(self, relative_path: str, body: str) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f'<xliff version="1.2" xmlns="{XLIFF_NS}" xmlns:sdl="{SDL_NS}">'
            '<file original="anonymous.xml" source-language="zh-CN" target-language="en-US">'
            f"<body>{body}</body></file></xliff>",
            encoding="utf-8",
        )
        return path

    def copy_fixture(self, source: Path, relative_path: str) -> Path:
        target = self.root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return target

    def test_profile_rules_are_strict_and_auditable(self):
        self.temp_fixture(
            "story/dialog_main.sdlxliff",
            '<trans-unit id="keep"><source>甲</source><target>Alpha</target>'
            '<sdl:seg-defs><sdl:seg id="1" conf="Translated"/></sdl:seg-defs>'
            '</trans-unit><trans-unit id="drop"><source>乙</source><target>Beta</target>'
            '<sdl:seg-defs><sdl:seg id="2" conf="Rejected"/></sdl:seg-defs></trans-unit>',
        )
        options = validate_options(
            {
                "tm_protection": "candidate-only",
                "content_type_rules": [
                    {
                        "id": "dialog",
                        "glob": "**/dialog*.sdlxliff",
                        "content_type": "剧情/对话",
                    }
                ],
                "exclude_rules": [
                    {
                        "id": "rejected",
                        "field": "confirmation",
                        "equals": "Rejected",
                        "reason": "Client excluded",
                    }
                ],
            }
        )

        result = read_sdlxliff(self.root, options=options)

        self.assertEqual([segment["id"] for segment in result.segments], [0])
        self.assertEqual(result.segments[0]["content_type"], "剧情/对话")
        self.assertEqual(result.segments[0]["content_type_rule_id"], "dialog")
        self.assertEqual(result.manifest["excluded"][0]["rule_ids"], ["rejected"])
        self.assertEqual(result.manifest["excluded"][0]["reasons"], ["Client excluded"])
        self.assertEqual(result.manifest["counts"]["included_segments"], 1)
        self.assertEqual(result.manifest["counts"]["excluded_segments"], 1)

    def test_options_schema_rejects_unknown_invalid_and_ambiguous_rules(self):
        cases = (
            ([], "object"),
            ({"unknown": True}, "unknown"),
            ({"tm_protection": "always"}, "tm_protection"),
            ({"tm_protection": []}, "tm_protection"),
            ({"content_type_rules": {}}, "content_type_rules"),
            ({"content_type_rules": ["not-an-object"]}, "object"),
            (
                {"content_type_rules": [{"id": " ", "glob": "*.sdlxliff", "content_type": "UI"}]},
                "id",
            ),
            (
                {"content_type_rules": [{"id": "x", "glob": "*.sdlxliff", "content_type": "UI", "extra": True}]},
                "extra",
            ),
            (
                {"content_type_rules": [{"id": "x", "glob": "[bad", "content_type": "UI"}]},
                "glob",
            ),
            (
                {"content_type_rules": [{"id": "x", "glob": "*.sdlxliff", "content_type": ""}]},
                "content_type",
            ),
            (
                {"exclude_rules": [{"id": "bad", "field": "segment.id", "equals": 1, "reason": "unstable"}]},
                "segment.id",
            ),
            (
                {"exclude_rules": [{"id": "x", "field": "source", "reason": "missing matcher"}]},
                "exactly one",
            ),
            (
                {"exclude_rules": [{"id": "x", "field": "source", "equals": "A", "regex": "A", "reason": "two"}]},
                "exactly one",
            ),
            (
                {"exclude_rules": [{"id": "x", "field": "source", "regex": "(", "reason": "bad regex"}]},
                "regex",
            ),
            (
                {"exclude_rules": [{"id": "x", "field": "source", "equals": "A", "reason": " "}]},
                "reason",
            ),
            (
                {"exclude_rules": [{"id": "x", "field": "source", "equals": float("nan"), "reason": "non-finite"}]},
                "equals",
            ),
            (
                {"exclude_rules": [{"id": "x", "field": "source", "equals": float("inf"), "reason": "non-finite"}]},
                "equals",
            ),
            (
                {
                    "content_type_rules": [{"id": "same", "glob": "*.sdlxliff", "content_type": "UI"}],
                    "exclude_rules": [{"id": "same", "field": "source", "equals": "A", "reason": "duplicate"}],
                },
                "same",
            ),
            (
                {"exclude_rules": [{"id": "blank-both-sides", "field": "source", "equals": "", "reason": "collision"}]},
                "blank-both-sides",
            ),
        )
        for raw, message in cases:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(SDLXLIFFImportError, message):
                    validate_options(raw)

    def test_cli_exact_tm_flag_overrides_profile_policy(self):
        options = validate_options(
            {"tm_protection": "candidate-only"}, cli_protect_exact_tm=True
        )

        self.assertEqual(options.tm_protection, "protect-exact-source-and-target")

    def test_rule_matchers_are_ordered_case_sensitive_and_complete(self):
        content_rules = validate_options(
            {
                "content_type_rules": [
                    {"id": "first", "glob": "**/dialog*.sdlxliff", "content_type": "Dialogue"},
                    {"id": "second", "glob": "**/*.sdlxliff", "content_type": "Fallback"},
                ]
            }
        ).content_type_rules
        self.assertEqual(
            match_content_type("story/dialog_main.sdlxliff", content_rules),
            ("Dialogue", "first"),
        )
        self.assertEqual(
            match_content_type("dialog_root.sdlxliff", content_rules),
            ("Dialogue", "first"),
        )
        self.assertEqual(
            match_content_type("story/Dialog_main.sdlxliff", content_rules),
            ("Fallback", "second"),
        )

        exclusion_rules = validate_options(
            {
                "exclude_rules": [
                    {"id": "locked", "field": "locked", "equals": True, "reason": "Locked"},
                    {"id": "target", "field": "target", "regex": "^Skip", "glob": "**/*.sdlxliff", "reason": "Target"},
                    {"id": "other", "field": "target", "equals": "Skip me", "glob": "other/**", "reason": "Other"},
                ]
            }
        ).exclude_rules
        matches = match_exclusions(
            {
                "relative_path": "story/dialog_main.sdlxliff",
                "file_original": "dialog.xml",
                "confirmation": "Translated",
                "origin": None,
                "locked": True,
                "source": "甲",
                "target": "Skip me",
            },
            exclusion_rules,
        )
        self.assertEqual([match["id"] for match in matches], ["locked", "target"])

    def test_exact_tm_requires_all_three_case_insensitive_conditions(self):
        self.assertTrue(
            is_exact_tm(
                {"origin": "TM", "match_percent": "100.0", "text_match": "sourceandtarget"}
            )
        )
        for metadata in (
            {"origin": "tm", "match_percent": "100"},
            {"origin": "machine", "match_percent": "100", "text_match": "SourceAndTarget"},
            {"origin": "tm", "match_percent": "99.999", "text_match": "SourceAndTarget"},
            {"origin": "tm", "match_percent": "not-a-number", "text_match": "SourceAndTarget"},
            {"origin": "tm", "match_percent": "100", "text_match": "Fuzzy"},
        ):
            with self.subTest(metadata=metadata):
                self.assertFalse(is_exact_tm(metadata))

    def test_tm_candidate_and_locked_protection_are_separate(self):
        default = read_sdlxliff(
            FIXTURES / "multi_segment.sdlxliff", options=SDLXLIFFOptions()
        )
        self.assertFalse(default.segments[0].get("protected", False))
        self.assertEqual(default.tm_candidates["candidate_ids"], [0])
        self.assertEqual(default.segments[1]["protected_reason"], "SOURCE_LOCKED")
        self.assertNotIn("protected_ids", default.tm_candidates)

        strict = read_sdlxliff(
            FIXTURES / "multi_segment.sdlxliff",
            options=SDLXLIFFOptions(
                tm_protection="protect-exact-source-and-target"
            ),
        )
        self.assertEqual(strict.segments[0]["protected_reason"], "TM_100_MATCH")
        self.assertEqual(strict.segments[1]["protected_reason"], "SOURCE_LOCKED")

        filtered_fixture = self.temp_fixture(
            "filtered-candidate.sdlxliff",
            '<trans-unit id="blank"><source/><target/>'
            '<sdl:seg-defs><sdl:seg id="1"/></sdl:seg-defs></trans-unit>'
            '<trans-unit id="candidate"><source>甲</source><target>Alpha</target>'
            '<sdl:seg-defs><sdl:seg id="2" origin="tm" percent="100" '
            'text-match="SourceAndTarget"/></sdl:seg-defs></trans-unit>',
        )
        filtered = read_sdlxliff(filtered_fixture, options=SDLXLIFFOptions())
        self.assertEqual(filtered.tm_candidates["candidate_ids"], [0])
        self.assertEqual(filtered.segments[0]["source_ref"]["tu_id"], "candidate")

    def test_locked_wins_but_exact_tm_evidence_remains_candidate(self):
        fixture = self.temp_fixture(
            "both.sdlxliff",
            '<trans-unit id="both"><source>甲</source><target>Alpha</target>'
            '<sdl:seg-defs><sdl:seg id="1" locked="true" origin="tm" percent="100" '
            'text-match="SourceAndTarget"/></sdl:seg-defs></trans-unit>',
        )
        result = read_sdlxliff(
            fixture,
            options=SDLXLIFFOptions(
                tm_protection="protect-exact-source-and-target"
            ),
        )

        self.assertEqual(result.segments[0]["protected_reason"], "SOURCE_LOCKED")
        self.assertEqual(result.tm_candidates["candidate_ids"], [0])
        evidence = result.manifest["protection_evidence"][0]
        self.assertTrue(evidence["locked"]["matched"])
        self.assertTrue(evidence["tm"]["candidate"])
        self.assertTrue(evidence["tm"]["protected_by_policy"])
        self.assertEqual(evidence["effective_reason"], "SOURCE_LOCKED")

    def test_100_percent_alone_is_not_an_exact_tm_candidate(self):
        fixture = self.temp_fixture(
            "negative.sdlxliff",
            '<trans-unit id="negative"><source>甲</source><target>Alpha</target>'
            '<sdl:seg-defs><sdl:seg id="1" origin="machine" percent="100" '
            'text-match="SourceAndTarget"/></sdl:seg-defs></trans-unit>',
        )
        result = read_sdlxliff(
            fixture,
            options=SDLXLIFFOptions(
                tm_protection="protect-exact-source-and-target"
            ),
        )

        self.assertEqual(result.tm_candidates["candidate_ids"], [])
        self.assertFalse(any(segment.get("protected") for segment in result.segments))

    def test_blank_both_is_excluded_but_single_blank_is_kept(self):
        result = read_sdlxliff(RECURSIVE_FIXTURES, options=SDLXLIFFOptions())
        by_tu = {segment["source_ref"]["tu_id"]: segment for segment in result.segments}

        self.assertIn("empty-target", by_tu)
        self.assertNotIn("blank-both", by_tu)
        blank = next(
            item
            for item in result.manifest["excluded"]
            if item["source_ref"]["tu_id"] == "blank-both"
        )
        self.assertEqual(blank["rule_ids"], ["blank-both-sides"])
        self.assertEqual([segment["id"] for segment in result.segments], list(range(len(result.segments))))
        self.assertEqual(len(result.rows_raw), len(result.segments))
        self.assertEqual(
            by_tu["tm-negative-origin"]["source_ref"]["tu_index"], 3
        )

    def test_inline_only_segment_is_not_treated_as_blank(self):
        fixture = self.temp_fixture(
            "inline-only.sdlxliff",
            '<trans-unit id="inline"><source><ph id="source-placeholder"/></source>'
            '<target><ph id="target-placeholder"/></target>'
            '<sdl:seg-defs><sdl:seg id="1"/></sdl:seg-defs></trans-unit>',
        )

        result = read_sdlxliff(fixture, options=SDLXLIFFOptions())

        self.assertEqual(len(result.segments), 1)
        self.assertEqual(result.manifest["excluded"], [])

    def test_exclusion_preserves_segment_extension_ownership(self):
        options = validate_options(
            {
                "exclude_rules": [
                    {
                        "id": "drop-first",
                        "field": "source",
                        "equals": "甲",
                        "reason": "Drop first segment",
                    }
                ]
            }
        )

        result = read_sdlxliff(
            FIXTURES / "segmented_extensions.sdlxliff", options=options
        )

        self.assertEqual(len(result.segments), 1)
        extension_xml = "\n".join(
            result.segments[0]["metadata"]["sdlxliff"]["extension_xml"]
        )
        self.assertIn("Shared anonymous metadata", extension_xml)
        self.assertIn("Second segment metadata", extension_xml)
        self.assertNotIn("First segment metadata", extension_xml)

    def test_no_filename_or_directory_content_type_inference(self):
        self.copy_fixture(
            FIXTURES / "multi_segment.sdlxliff",
            "CC/FF/dialogs.sdlxliff",
        )

        result = read_sdlxliff(self.root, options=SDLXLIFFOptions())

        self.assertTrue(all(not segment.get("content_type") for segment in result.segments))
        self.assertEqual(result.manifest["content_type_matches"], [])

    def test_manifest_is_json_serializable_and_has_file_hashes(self):
        selected = self.copy_fixture(
            FIXTURES / "extensions.sdlxliff", "nested/extensions.sdlxliff"
        )
        (self.root / "notes.csv").write_text("source,target\n", encoding="utf-8")

        result = read_sdlxliff(self.root, options=SDLXLIFFOptions())
        encoded = json.dumps(
            result.manifest, ensure_ascii=False, sort_keys=True, allow_nan=False
        )
        manifest_file = result.manifest["files"][0]

        self.assertEqual(result.manifest["schema"], "lqe.sdlxliff.import-manifest")
        self.assertEqual(result.manifest["version"], 1)
        self.assertEqual(manifest_file["relative_path"], "nested/extensions.sdlxliff")
        self.assertEqual(
            manifest_file["sha256"], hashlib.sha256(selected.read_bytes()).hexdigest()
        )
        self.assertEqual(len(manifest_file["sha256"]), 64)
        self.assertEqual(result.manifest["tm_protection"], "candidate-only")
        self.assertEqual(result.manifest["unselected_supported_files"], ["notes.csv"])
        self.assertIn("urn:vendor:test", result.manifest["extension_namespaces"])
        self.assertNotIn("QUJDREVGR0g=", encoded)
        self.assertEqual(manifest_file["internal_file"], {"present": True, "size": 12})
        self.assertEqual(
            result.manifest["counts"],
            {
                "selected_files": 1,
                "unselected_supported_files": 1,
                "parsed_segments": 1,
                "included_segments": 1,
                "excluded_segments": 0,
                "content_type_matches": 0,
                "tm_candidates": 0,
                "locked_segments": 0,
                "protected_segments": 0,
            },
        )
        self.assertEqual(len(result.manifest["protection_evidence"]), 1)
        evidence = result.manifest["protection_evidence"][0]
        self.assertTrue(evidence["included"])
        self.assertFalse(evidence["locked"]["matched"])
        self.assertFalse(evidence["tm"]["candidate"])


if __name__ == "__main__":
    unittest.main()
