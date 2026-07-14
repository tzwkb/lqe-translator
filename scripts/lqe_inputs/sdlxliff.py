from dataclasses import dataclass
from html import escape
from pathlib import Path
import re
from xml.etree import ElementTree as ET


XLIFF_NS = "urn:oasis:names:tc:xliff:document:1.2"
SDL_NS = "http://sdl.com/FileTypes/SdlXliff/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"

_X = "{" + XLIFF_NS + "}"
_SDL = "{" + SDL_NS + "}"
_INLINE_NAMES = {"g", "x", "bx", "ex", "ph", "bpt", "ept", "it", "sub", "mrk"}
_NATIVE_CODE_NAMES = {"bpt", "ept", "it", "ph"}
_TABULAR_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xlsm"}
_TRUE_VALUES = {"1", "true", "yes"}


class SDLXLIFFImportError(ValueError):
    pass


@dataclass(frozen=True)
class SDLXLIFFOptions:
    tm_protection: str = "candidate-only"
    content_type_rules: tuple[dict, ...] = ()
    exclude_rules: tuple[dict, ...] = ()


@dataclass(frozen=True)
class SerializedMixedContent:
    display: str
    plain: str
    raw_xml: str
    tag_signature: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]


@dataclass
class SDLXLIFFImportResult:
    headers: list[str]
    rows_raw: list[list[str]]
    segments: list[dict]
    source_lang: str
    target_lang: str
    input_paths: list[str]
    manifest: dict
    tm_candidates: dict


def _split_qname(value: str) -> tuple[str | None, str]:
    if value.startswith("{") and "}" in value:
        namespace, local = value[1:].split("}", 1)
        return namespace, local
    return None, value


class _QNameFormatter:
    def __init__(self, namespace_map: dict[str, str]):
        self._prefixes_by_uri: dict[str, list[str]] = {}
        for prefix, uri in namespace_map.items():
            self._prefixes_by_uri.setdefault(uri, []).append(prefix or "")
        for prefixes in self._prefixes_by_uri.values():
            prefixes.sort(key=lambda prefix: (prefix != "", prefix))
        self._assigned: dict[tuple[str, bool], str] = {}
        self._used_prefixes = set(namespace_map)
        self.declarations: dict[str, str] = {}
        self._fallback_index = 0

    def _fallback(self) -> str:
        while True:
            prefix = f"ns{self._fallback_index}"
            self._fallback_index += 1
            if prefix not in self._used_prefixes:
                self._used_prefixes.add(prefix)
                return prefix

    def _prefix(self, uri: str, *, attribute: bool) -> str:
        key = (uri, attribute)
        if key in self._assigned:
            return self._assigned[key]
        if uri == XML_NS:
            prefix = "xml"
        else:
            candidates = self._prefixes_by_uri.get(uri, [])
            if attribute:
                prefix = next((candidate for candidate in candidates if candidate), "")
            else:
                prefix = candidates[0] if candidates else ""
            if not prefix and (attribute or not candidates):
                prefix = self._fallback()
            if not attribute and uri == XLIFF_NS and "" in candidates:
                prefix = ""
        self._assigned[key] = prefix
        if prefix != "xml":
            existing = self.declarations.get(prefix)
            if existing is not None and existing != uri:
                prefix = self._fallback()
                self._assigned[key] = prefix
            self.declarations[prefix] = uri
        return prefix

    def qname(self, value: str, *, attribute: bool = False) -> str:
        uri, local = _split_qname(value)
        if uri is None:
            return local
        prefix = self._prefix(uri, attribute=attribute)
        return f"{prefix}:{local}" if prefix else local

    def scan(self, element: ET.Element) -> None:
        self.qname(element.tag)
        for name in sorted(element.attrib):
            self.qname(name, attribute=True)
        for child in element:
            self.scan(child)


def _render_element(
    element: ET.Element,
    formatter: _QNameFormatter,
    *,
    declare_root: bool,
) -> str:
    if declare_root:
        formatter.scan(element)
    name = formatter.qname(element.tag)
    pieces = ["<", name]
    if declare_root:
        for prefix, uri in sorted(
            formatter.declarations.items(), key=lambda item: (item[0] != "", item[0])
        ):
            declaration = "xmlns" if not prefix else f"xmlns:{prefix}"
            pieces.extend([" ", declaration, '="', escape(uri, quote=True), '"'])
    for attr_name, value in sorted(element.attrib.items(), key=lambda item: item[0]):
        pieces.extend(
            [
                " ",
                formatter.qname(attr_name, attribute=True),
                '="',
                escape(str(value), quote=True),
                '"',
            ]
        )
    if len(element) == 0 and not element.text:
        pieces.append("/>")
    else:
        pieces.append(">")
        if element.text:
            pieces.append(escape(element.text, quote=False))
        for child in element:
            pieces.append(_render_element(child, formatter, declare_root=False))
        pieces.extend(["</", name, ">"])
    if element.tail:
        pieces.append(escape(element.tail, quote=False))
    return "".join(pieces)


def _content_xml(element: ET.Element, namespace_map: dict[str, str], *, raw: bool) -> str:
    pieces = [escape(element.text, quote=False) if element.text else ""]
    if raw:
        for child in element:
            formatter = _QNameFormatter(namespace_map)
            pieces.append(_render_element(child, formatter, declare_root=True))
    else:
        formatter = _QNameFormatter(namespace_map)
        for child in element:
            pieces.append(_render_element(child, formatter, declare_root=False))
    return "".join(pieces)


def _tag_signature(
    element: ET.Element,
) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    signature: list[tuple[str, tuple[tuple[str, str], ...]]] = []

    def visit(parent: ET.Element) -> None:
        for child in parent:
            namespace, local = _split_qname(child.tag)
            if namespace == XLIFF_NS and local in _INLINE_NAMES:
                signature.append(
                    (
                        child.tag,
                        tuple(
                            (name, str(value))
                            for name, value in sorted(
                                child.attrib.items(), key=lambda item: item[0]
                            )
                        ),
                    )
                )
            visit(child)

    visit(element)
    return tuple(signature)


def _plain_text(element: ET.Element) -> str:
    pieces: list[str] = []

    def visit(parent: ET.Element, translatable: bool) -> None:
        if translatable and parent.text:
            pieces.append(parent.text)
        for child in parent:
            namespace, local = _split_qname(child.tag)
            child_translatable = (
                True
                if namespace == XLIFF_NS and local == "sub"
                else translatable
                and not (namespace == XLIFF_NS and local in _NATIVE_CODE_NAMES)
            )
            visit(child, child_translatable)
            if translatable and child.tail:
                pieces.append(child.tail)

    visit(element, True)
    return "".join(pieces)


def serialize_mixed(
    element: ET.Element,
    namespace_map: dict[str, str],
) -> SerializedMixedContent:
    return SerializedMixedContent(
        display=_content_xml(element, namespace_map, raw=False),
        plain=_plain_text(element),
        raw_xml=_content_xml(element, namespace_map, raw=True),
        tag_signature=_tag_signature(element),
    )


def _serialize_full(element: ET.Element, namespace_map: dict[str, str]) -> str:
    formatter = _QNameFormatter(namespace_map)
    return _render_element(element, formatter, declare_root=True)


def _context(
    relative_path: str,
    *,
    file_index: int | None = None,
    tu_id: str | None = None,
    tu_index: int | None = None,
    segment_id: str | None = None,
    segment_index: int | None = None,
    element: ET.Element | None = None,
) -> str:
    parts = [relative_path]
    if file_index is not None:
        parts.append(f"file[{file_index}]")
    if tu_index is not None:
        parts.append(f"TU {tu_id!r} (index {tu_index})")
    if segment_index is not None:
        parts.append(f"segment {segment_id!r} (index {segment_index})")
    line = getattr(element, "sourceline", None) if element is not None else None
    if line is not None:
        parts.append(f"line {line}")
    return ", ".join(parts)


def _fail(message: str, context: str) -> None:
    raise SDLXLIFFImportError(f"{context}: {message}")


def _parse_xml(path: Path, relative_path: str) -> tuple[ET.Element, dict[str, str]]:
    namespace_map: dict[str, str] = {}
    try:
        parser = ET.iterparse(path, events=("start-ns", "end"))
        for event, value in parser:
            if event == "start-ns":
                prefix, uri = value
                namespace_map.setdefault(prefix or "", uri)
        root = parser.root
    except ET.ParseError as exc:
        line, column = getattr(exc, "position", (None, None))
        location = (
            f"line {line}, column {column}" if line is not None else "unknown location"
        )
        raise SDLXLIFFImportError(
            f"{relative_path}: {location}: invalid XML: {exc}"
        ) from exc
    if root.tag != _X + "xliff" or root.get("version") != "1.2":
        _fail("expected XLIFF 1.2 root namespace and version", relative_path)
    if SDL_NS not in namespace_map.values():
        _fail(f"supported SDL namespace {SDL_NS!r} is required", relative_path)
    return root, namespace_map


def _selected_files(path: Path) -> tuple[list[tuple[Path, str]], list[str]]:
    if not path.exists():
        raise SDLXLIFFImportError(f"input path does not exist: {path}")
    if path.is_file():
        return [(path, path.name)], []
    selected = sorted(
        (
            candidate
            for candidate in path.rglob("*")
            if candidate.is_file() and candidate.suffix.casefold() == ".sdlxliff"
        ),
        key=lambda candidate: candidate.relative_to(path).as_posix(),
    )
    if not selected:
        raise SDLXLIFFImportError(f"no SDLXLIFF files found in directory: {path}")
    unselected = sorted(
        candidate.relative_to(path).as_posix()
        for candidate in path.rglob("*")
        if candidate.is_file() and candidate.suffix.casefold() in _TABULAR_SUFFIXES
    )
    return [
        (candidate, candidate.relative_to(path).as_posix()) for candidate in selected
    ], unselected


def _local_attribute(element: ET.Element, name: str) -> str | None:
    if name in element.attrib:
        return element.attrib[name]
    for attr_name, value in element.attrib.items():
        if _split_qname(attr_name)[1] == name:
            return value
    return None


def _comment_definitions(file_element: ET.Element) -> dict[str, str]:
    definitions: dict[str, str] = {}
    for element in file_element.iter():
        namespace, local = _split_qname(element.tag)
        if namespace != SDL_NS or local not in {"cmt-def", "comment-def"}:
            continue
        comment_id = _local_attribute(element, "id")
        text = "".join(element.itertext()).strip()
        if comment_id and text:
            definitions[comment_id] = text
    return definitions


def _segment_definitions(tu: ET.Element) -> list[ET.Element]:
    container = tu.find(_SDL + "seg-defs")
    if container is None:
        return []
    return [child for child in container if child.tag == _SDL + "seg"]


def _last_modified_by(seg_def: ET.Element | None) -> str | None:
    if seg_def is None:
        return None
    direct = _local_attribute(seg_def, "last_modified_by")
    if direct:
        return direct
    for element in seg_def.iter():
        if _split_qname(element.tag)[1] != "value":
            continue
        if _local_attribute(element, "key") == "last_modified_by":
            value = "".join(element.itertext()).strip()
            return value or None
    return None


def _segment_comment(
    seg_def: ET.Element | None,
    definitions: dict[str, str],
) -> str | None:
    if seg_def is None:
        return None
    references: list[str] = []
    for name in ("comments", "comment", "comment-id", "cmt-id"):
        value = _local_attribute(seg_def, name)
        if value:
            references.extend(part for part in re.split(r"[,;\s]+", value) if part)
    inline: list[str] = []
    for element in seg_def.iter():
        if element is seg_def:
            continue
        local = _split_qname(element.tag)[1]
        if local not in {"cmt", "comment"}:
            continue
        reference = _local_attribute(element, "id") or _local_attribute(element, "ref")
        if reference:
            references.append(reference)
        else:
            value = "".join(element.itertext()).strip()
            if value:
                inline.append(value)
    resolved = [definitions[reference] for reference in references if reference in definitions]
    values = resolved + inline
    return "\n".join(dict.fromkeys(values)) or None


def _metadata(
    *,
    file_original: str | None,
    source_language: str | None,
    target_language: str | None,
    seg_def: ET.Element | None,
    comments: dict[str, str],
    source: SerializedMixedContent,
    target: SerializedMixedContent,
    extension_xml: list[str],
) -> dict:
    return {
        "file_original": file_original,
        "source_language": source_language,
        "target_language": target_language,
        "confirmation": _local_attribute(seg_def, "conf") if seg_def is not None else None,
        "origin": _local_attribute(seg_def, "origin") if seg_def is not None else None,
        "match_percent": _local_attribute(seg_def, "percent") if seg_def is not None else None,
        "text_match": _local_attribute(seg_def, "text-match") if seg_def is not None else None,
        "locked": (
            (_local_attribute(seg_def, "locked") or "").casefold() in _TRUE_VALUES
            if seg_def is not None
            else False
        ),
        "last_modified_by": _last_modified_by(seg_def),
        "comment": _segment_comment(seg_def, comments),
        "source_raw_xml": source.raw_xml,
        "target_raw_xml": target.raw_xml,
        "source_tag_signature": source.tag_signature,
        "target_tag_signature": target.tag_signature,
        "extension_xml": list(extension_xml),
    }


def _has_boundary_descendant(element: ET.Element) -> bool:
    boundary_tags = {
        _X + "trans-unit",
        _X + "source",
        _X + "seg-source",
        _X + "target",
        _X + "mrk",
    }
    return any(descendant.tag in boundary_tags for descendant in element.iter())


def _iter_trans_units(body: ET.Element, context: str):
    for child in body:
        if child.tag == _X + "trans-unit":
            yield child
            continue
        if child.tag == _X + "group":
            yield from _iter_trans_units(child, context)
            continue
        if _has_boundary_descendant(child):
            namespace, _ = _split_qname(child.tag)
            _fail(
                f"unsupported structural extension namespace {namespace or '<none>'}",
                context,
            )


def _segmentation_markers(container: ET.Element, context: str) -> list[ET.Element]:
    if container.text and container.text.strip():
        _fail("text outside segmentation mrk boundaries", context)
    markers: list[ET.Element] = []
    for child in container:
        if child.tag != _X + "mrk" or _local_attribute(child, "mtype") != "seg":
            namespace, _ = _split_qname(child.tag)
            _fail(
                f"unsupported structural extension {child.tag!r} ({namespace or '<none>'})",
                context,
            )
        markers.append(child)
        if child.tail and child.tail.strip():
            _fail("text outside segmentation mrk boundaries", context)
    if not markers:
        _fail("segmented content requires top-level mrk mtype='seg'", context)
    return markers


def _markers_by_mid(markers: list[ET.Element], context: str) -> dict[str, ET.Element]:
    by_mid: dict[str, ET.Element] = {}
    for marker in markers:
        mid = _local_attribute(marker, "mid")
        if not mid:
            _fail("segmentation mrk is missing mid", context)
        if mid in by_mid:
            _fail(f"duplicate mid {mid!r}", context)
        by_mid[mid] = marker
    return by_mid


_EMPTY_MIXED = SerializedMixedContent("", "", "", ())


def _pair_tu(
    tu: ET.Element,
    *,
    namespace_map: dict[str, str],
    context: str,
) -> list[tuple[SerializedMixedContent, SerializedMixedContent, str | None, ET.Element | None]]:
    seg_source = tu.find(_X + "seg-source")
    source_element = tu.find(_X + "source")
    target_element = tu.find(_X + "target")
    seg_defs = _segment_definitions(tu)

    if seg_source is not None:
        source_markers = _segmentation_markers(seg_source, context)
        source_by_mid = _markers_by_mid(source_markers, context)
        target_by_mid: dict[str, ET.Element] = {}
        if target_element is not None:
            target_markers = _segmentation_markers(target_element, context)
            target_by_mid = _markers_by_mid(target_markers, context)
            if set(target_by_mid) != set(source_by_mid):
                _fail(
                    "source/target mid sets do not match: "
                    f"source={sorted(source_by_mid)} target={sorted(target_by_mid)}",
                    context,
                )

        defs_by_id: dict[str, ET.Element] = {}
        for seg_def in seg_defs:
            seg_id = _local_attribute(seg_def, "id")
            if not seg_id:
                _fail("seg-def is missing id for segmented content", context)
            if seg_id in defs_by_id:
                _fail(f"duplicate seg-def id {seg_id!r}", context)
            defs_by_id[seg_id] = seg_def
        if set(defs_by_id) != set(source_by_mid):
            _fail(
                "mrk mid and seg-def id sets do not match: "
                f"mid={sorted(source_by_mid)} seg-def={sorted(defs_by_id)}",
                context,
            )

        pairs = []
        for source_marker in source_markers:
            mid = _local_attribute(source_marker, "mid")
            target_marker = target_by_mid.get(mid) if target_element is not None else None
            pairs.append(
                (
                    serialize_mixed(source_marker, namespace_map),
                    serialize_mixed(target_marker, namespace_map)
                    if target_marker is not None
                    else _EMPTY_MIXED,
                    mid,
                    defs_by_id.get(mid),
                )
            )
        return pairs

    if source_element is None:
        _fail("trans-unit is missing source or seg-source", context)
    if any(
        element.tag == _X + "mrk" and _local_attribute(element, "mtype") == "seg"
        for element in source_element.iter()
    ):
        _fail("segmentation mrk requires seg-source", context)
    if target_element is not None and any(
        element.tag == _X + "mrk" and _local_attribute(element, "mtype") == "seg"
        for element in target_element.iter()
    ):
        _fail("target segmentation mrk has no seg-source boundary", context)
    if len(seg_defs) > 1:
        _fail("multiple seg-def entries have no segmentation boundaries", context)
    seg_def = seg_defs[0] if seg_defs else None
    seg_id = _local_attribute(seg_def, "id") if seg_def is not None else None
    return [
        (
            serialize_mixed(source_element, namespace_map),
            serialize_mixed(target_element, namespace_map)
            if target_element is not None
            else _EMPTY_MIXED,
            seg_id,
            seg_def,
        )
    ]


def _tu_extensions(tu: ET.Element, namespace_map: dict[str, str]) -> list[str]:
    values = []
    for child in tu:
        namespace, _ = _split_qname(child.tag)
        if namespace not in {XLIFF_NS, SDL_NS}:
            values.append(_serialize_full(child, namespace_map))
    return values


def _internal_file_summary(root: ET.Element) -> dict[str, int | bool]:
    payloads = [
        "".join(element.itertext()).strip()
        for element in root.iter(_X + "internal-file")
    ]
    return {
        "present": bool(payloads),
        "size": sum(len(payload) for payload in payloads),
    }


def read_sdlxliff(
    path: Path,
    *,
    options: SDLXLIFFOptions,
) -> SDLXLIFFImportResult:
    if not isinstance(options, SDLXLIFFOptions):
        raise SDLXLIFFImportError("options must be SDLXLIFFOptions")
    selected, unselected = _selected_files(Path(path))
    segments: list[dict] = []
    rows_raw: list[list[str]] = []
    manifest_files: list[dict] = []
    declared_languages: list[dict[str, str | None]] = []
    extension_namespaces: set[str] = set()

    for input_path, relative_path in selected:
        root, namespace_map = _parse_xml(input_path, relative_path)
        extension_namespaces.update(
            uri
            for uri in namespace_map.values()
            if uri not in {XLIFF_NS, SDL_NS, XML_NS}
        )
        input_language_declarations: list[dict[str, str | None]] = []
        internal_summary = _internal_file_summary(root)
        file_elements = [child for child in root if child.tag == _X + "file"]
        if not file_elements:
            _fail("document contains no XLIFF file elements", relative_path)

        for file_index, file_element in enumerate(file_elements):
            file_context = _context(relative_path, file_index=file_index)
            file_original = _local_attribute(file_element, "original")
            source_language = _local_attribute(file_element, "source-language")
            target_language = _local_attribute(file_element, "target-language")
            declaration = {
                "source_language": source_language,
                "target_language": target_language,
            }
            declared_languages.append(declaration)
            input_language_declarations.append(declaration)
            comments = _comment_definitions(file_element)
            body = file_element.find(_X + "body")
            if body is None:
                _fail("XLIFF file is missing body", file_context)
            seen_business_keys: set[tuple[str | None, str | None]] = set()

            for tu_index, tu in enumerate(_iter_trans_units(body, file_context)):
                tu_id = _local_attribute(tu, "id") or None
                tu_context = _context(
                    relative_path,
                    file_index=file_index,
                    tu_id=tu_id,
                    tu_index=tu_index,
                    element=tu,
                )
                pairs = _pair_tu(tu, namespace_map=namespace_map, context=tu_context)
                extension_xml = _tu_extensions(tu, namespace_map)
                for segment_index, (source, target, sdl_segment_id, seg_def) in enumerate(pairs):
                    business_key = (tu_id, sdl_segment_id)
                    if (tu_id is not None or sdl_segment_id is not None) and business_key in seen_business_keys:
                        segment_context = _context(
                            relative_path,
                            file_index=file_index,
                            tu_id=tu_id,
                            tu_index=tu_index,
                            segment_id=sdl_segment_id,
                            segment_index=segment_index,
                        )
                        _fail(
                            f"duplicate TU/segment business key {business_key!r}",
                            segment_context,
                        )
                    if tu_id is not None or sdl_segment_id is not None:
                        seen_business_keys.add(business_key)

                    source_ref = {
                        "relative_path": relative_path,
                        "file_index": file_index,
                        "tu_id": tu_id,
                        "tu_index": tu_index,
                        "sdl_segment_id": sdl_segment_id,
                        "segment_index": segment_index,
                    }
                    segment_id = len(segments)
                    metadata = _metadata(
                        file_original=file_original,
                        source_language=source_language,
                        target_language=target_language,
                        seg_def=seg_def,
                        comments=comments,
                        source=source,
                        target=target,
                        extension_xml=extension_xml,
                    )
                    segment = {
                        "id": segment_id,
                        "source_ref": source_ref,
                        "source": source.display,
                        "target": target.display,
                        "source_plain": source.plain,
                        "target_plain": target.plain,
                        "corrected": None,
                        "metadata": {"sdlxliff": metadata},
                    }
                    segments.append(segment)
                    rows_raw.append(
                        [
                            relative_path,
                            tu_id,
                            sdl_segment_id,
                            source.display,
                            target.display,
                        ]
                    )

        manifest_files.append(
            {
                "relative_path": relative_path,
                "namespaces": dict(sorted(namespace_map.items())),
                "languages": input_language_declarations,
                "internal_file": internal_summary,
            }
        )

    source_lang = next(
        (
            declaration["source_language"]
            for declaration in declared_languages
            if declaration["source_language"]
        ),
        "",
    )
    target_lang = next(
        (
            declaration["target_language"]
            for declaration in declared_languages
            if declaration["target_language"]
        ),
        "",
    )
    manifest = {
        "input_format": "sdlxliff",
        "files": manifest_files,
        "languages": declared_languages,
        "extension_namespaces": sorted(extension_namespaces),
        "unselected_supported_files": unselected,
    }
    return SDLXLIFFImportResult(
        headers=["来源文件", "TU ID", "SDL Segment ID", "原文", "译文"],
        rows_raw=rows_raw,
        segments=segments,
        source_lang=source_lang,
        target_lang=target_lang,
        input_paths=[str(input_path.resolve()) for input_path, _ in selected],
        manifest=manifest,
        tm_candidates={"candidate_ids": [], "segments": []},
    )
