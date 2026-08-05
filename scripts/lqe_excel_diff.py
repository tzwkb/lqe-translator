"""Build paired Excel rich text for original and suggested translations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from difflib import SequenceMatcher

import regex

from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont


_RED = "FFFF0000"
_EXCEL_CELL_LIMIT = 32767
_SEQUENCE_MATCHER_PRODUCT_LIMIT = 4_000_000
_BOUNDED_EDIT_LIMIT = 256
_GRAPHEME_PATTERN = regex.compile(r"\X")
_PLAIN = 0
_RED_TEXT = 1
_RED_STRIKE = 2


def _split_graphemes(text: str) -> list[str]:
    return _GRAPHEME_PATTERN.findall(text)


def _tags_to_opcodes(tags: list[str]) -> list[tuple[str, int, int, int, int]]:
    opcodes = []
    original_index = suggested_index = 0
    for tag in tags:
        next_original = original_index + (tag != "insert")
        next_suggested = suggested_index + (tag != "delete")
        if opcodes and opcodes[-1][0] == tag:
            _, i1, _, j1, _ = opcodes[-1]
            opcodes[-1] = (tag, i1, next_original, j1, next_suggested)
        else:
            opcodes.append(
                (
                    tag,
                    original_index,
                    next_original,
                    suggested_index,
                    next_suggested,
                )
            )
        original_index = next_original
        suggested_index = next_suggested
    return opcodes


def _backtrack_myers(
    trace: list[dict[int, int]],
    original: list[str],
    suggested: list[str],
) -> list[tuple[str, int, int, int, int]]:
    original_index = len(original)
    suggested_index = len(suggested)
    tags = []
    for distance in range(len(trace) - 1, 0, -1):
        previous = trace[distance - 1]
        diagonal = original_index - suggested_index
        if diagonal == -distance or (
            diagonal != distance
            and previous.get(diagonal - 1, -1) < previous.get(diagonal + 1, -1)
        ):
            previous_diagonal = diagonal + 1
        else:
            previous_diagonal = diagonal - 1
        previous_original = previous[previous_diagonal]
        previous_suggested = previous_original - previous_diagonal
        while (
            original_index > previous_original
            and suggested_index > previous_suggested
        ):
            tags.append("equal")
            original_index -= 1
            suggested_index -= 1
        if original_index == previous_original:
            tags.append("insert")
            suggested_index -= 1
        else:
            tags.append("delete")
            original_index -= 1
    while original_index > 0 and suggested_index > 0:
        tags.append("equal")
        original_index -= 1
        suggested_index -= 1
    while original_index > 0:
        tags.append("delete")
        original_index -= 1
    while suggested_index > 0:
        tags.append("insert")
        suggested_index -= 1
    tags.reverse()
    return _tags_to_opcodes(tags)


def _bounded_myers_opcodes(
    original: list[str],
    suggested: list[str],
) -> list[tuple[str, int, int, int, int]] | None:
    if not original:
        if not suggested:
            return []
        if len(suggested) > _BOUNDED_EDIT_LIMIT:
            return None
        return [("insert", 0, 0, 0, len(suggested))]
    if not suggested:
        if len(original) > _BOUNDED_EDIT_LIMIT:
            return None
        return [("delete", 0, len(original), 0, 0)]
    if abs(len(original) - len(suggested)) > _BOUNDED_EDIT_LIMIT:
        return None
    previous = {1: 0}
    trace = []
    max_distance = min(len(original) + len(suggested), _BOUNDED_EDIT_LIMIT)
    for distance in range(max_distance + 1):
        current = {}
        for diagonal in range(-distance, distance + 1, 2):
            if diagonal == -distance or (
                diagonal != distance
                and previous.get(diagonal - 1, -1)
                < previous.get(diagonal + 1, -1)
            ):
                original_index = previous.get(diagonal + 1, 0)
            else:
                original_index = previous.get(diagonal - 1, 0) + 1
            suggested_index = original_index - diagonal
            while (
                original_index < len(original)
                and suggested_index < len(suggested)
                and original[original_index] == suggested[suggested_index]
            ):
                original_index += 1
                suggested_index += 1
            current[diagonal] = original_index
            if (
                original_index >= len(original)
                and suggested_index >= len(suggested)
            ):
                trace.append(current)
                return _backtrack_myers(trace, original, suggested)
        trace.append(current)
        previous = current
    return None


def _middle_opcodes(
    original: list[str],
    suggested: list[str],
) -> list[tuple[str, int, int, int, int]]:
    if len(original) * len(suggested) <= _SEQUENCE_MATCHER_PRODUCT_LIMIT:
        return SequenceMatcher(
            None,
            original,
            suggested,
            autojunk=False,
        ).get_opcodes()
    opcodes = _bounded_myers_opcodes(original, suggested)
    if opcodes is not None:
        return opcodes
    return [("replace", 0, len(original), 0, len(suggested))]


def _append(runs: list[tuple[str, int]], text: str, style: int) -> None:
    if not text:
        return
    if runs and runs[-1][1] == style:
        previous, _ = runs[-1]
        runs[-1] = (previous + text, style)
    else:
        runs.append((text, style))


def _to_excel_text(runs: list[tuple[str, int]]):
    if not any(style for _, style in runs):
        return "".join(text for text, _ in runs)
    values = []
    for text, style in runs:
        if style:
            values.append(
                TextBlock(
                    InlineFont(
                        color=_RED,
                        strike=True if style == _RED_STRIKE else None,
                    ),
                    text,
                )
            )
        else:
            values.append(text)
    return CellRichText(values)


def _span_bounds(
    text: str,
    spans: Iterable[Mapping[str, object] | tuple[int, int]],
) -> list[tuple[int, int]]:
    bounds = []
    for index, span in enumerate(spans):
        if isinstance(span, Mapping):
            start = span.get("start")
            end = span.get("end")
            expected = span.get("text")
        elif isinstance(span, (tuple, list)) and len(span) == 2:
            start, end = span
            expected = None
        else:
            raise ValueError(f"span {index} must define start and end")
        if type(start) is not int or type(end) is not int:
            raise ValueError(f"span {index} start/end must be integers")
        if start < 0 or end <= start or end > len(text):
            raise ValueError(
                f"span {index} [{start}, {end}) is outside text length {len(text)}"
            )
        if expected is not None and (
            not isinstance(expected, str) or text[start:end] != expected
        ):
            raise ValueError(f"span {index} text does not match [{start}, {end})")
        bounds.append((start, end))
    return bounds


def _span_mask(
    text: str,
    graphemes: list[str],
    spans: Iterable[Mapping[str, object] | tuple[int, int]],
) -> list[bool]:
    bounds = _span_bounds(text, spans)
    if not bounds:
        return [False] * len(graphemes)
    changes = [0] * (len(text) + 1)
    for start, end in bounds:
        changes[start] += 1
        changes[end] -= 1
    covered = []
    active = 0
    for index in range(len(text)):
        active += changes[index]
        covered.append(active > 0)
    mask = []
    offset = 0
    for grapheme in graphemes:
        end = offset + len(grapheme)
        mask.append(any(covered[offset:end]))
        offset = end
    return mask


def _styled_graphemes(
    graphemes: list[str],
    styles: list[int],
) -> str | CellRichText:
    runs: list[tuple[str, int]] = []
    for grapheme, style in zip(graphemes, styles):
        _append(runs, grapheme, style)
    return _to_excel_text(runs)


def build_rich_highlights(
    text: str,
    spans: Iterable[Mapping[str, object] | tuple[int, int]] = (),
) -> str | CellRichText:
    """Render validated character spans as red text without strike-through."""
    if len(text) > _EXCEL_CELL_LIMIT:
        return text
    graphemes = _split_graphemes(text)
    mask = _span_mask(text, graphemes, spans)
    return _styled_graphemes(
        graphemes,
        [_RED_TEXT if highlighted else _PLAIN for highlighted in mask],
    )


def _diff_opcodes(
    original_graphemes: list[str],
    suggested_graphemes: list[str],
) -> list[tuple[str, int, int, int, int]]:
    prefix = 0
    while (
        prefix < min(len(original_graphemes), len(suggested_graphemes))
        and original_graphemes[prefix] == suggested_graphemes[prefix]
    ):
        prefix += 1

    suffix = 0
    max_suffix = min(
        len(original_graphemes) - prefix,
        len(suggested_graphemes) - prefix,
    )
    while (
        suffix < max_suffix
        and original_graphemes[-1 - suffix] == suggested_graphemes[-1 - suffix]
    ):
        suffix += 1

    original_end = len(original_graphemes) - suffix if suffix else len(original_graphemes)
    suggested_end = len(suggested_graphemes) - suffix if suffix else len(suggested_graphemes)
    opcodes = []
    if prefix:
        opcodes.append(("equal", 0, prefix, 0, prefix))
    middle_opcodes = _middle_opcodes(
        original_graphemes[prefix:original_end],
        suggested_graphemes[prefix:suggested_end],
    )
    opcodes.extend(
        (tag, prefix + i1, prefix + i2, prefix + j1, prefix + j2)
        for tag, i1, i2, j1, j2 in middle_opcodes
    )
    if suffix:
        opcodes.append(
            (
                "equal",
                original_end,
                len(original_graphemes),
                suggested_end,
                len(suggested_graphemes),
            )
        )
    return opcodes


def _formula_safe(value: str | CellRichText) -> str | CellRichText:
    if isinstance(value, str) and value.startswith("="):
        return CellRichText([value])
    return value


def build_review_rich_texts(
    source: str,
    original: str,
    suggested: str | None,
    *,
    source_spans: Iterable[Mapping[str, object] | tuple[int, int]] = (),
    target_spans: Iterable[Mapping[str, object] | tuple[int, int]] = (),
) -> tuple[
    str | CellRichText,
    str | CellRichText,
    str | CellRichText | None,
]:
    """Build source/translation rich text with terminology and diff styles merged."""
    source_value = _formula_safe(build_rich_highlights(source, source_spans))
    target_spans = tuple(target_spans)
    if suggested is None:
        return source_value, build_rich_highlights(original, target_spans), None

    if len(original) > _EXCEL_CELL_LIMIT or len(suggested) > _EXCEL_CELL_LIMIT:
        return source_value, build_rich_highlights(original, target_spans), suggested

    original_graphemes = _split_graphemes(original)
    suggested_graphemes = _split_graphemes(suggested)
    original_changed = [False] * len(original_graphemes)
    suggested_changed = [False] * len(suggested_graphemes)
    opcodes = []
    if original != suggested:
        opcodes = _diff_opcodes(
            original_graphemes,
            suggested_graphemes,
        )
        for tag, i1, i2, j1, j2 in opcodes:
            if tag != "equal":
                original_changed[i1:i2] = [True] * (i2 - i1)
                suggested_changed[j1:j2] = [True] * (j2 - j1)

    term_mask = _span_mask(original, original_graphemes, target_spans)
    for target_span in target_spans:
        span_mask = _span_mask(
            original,
            original_graphemes,
            (target_span,),
        )
        if any(
            changed and inside
            for changed, inside in zip(original_changed, span_mask)
        ):
            span_start = span_mask.index(True)
            span_end = len(span_mask) - list(reversed(span_mask)).index(True)
            original_changed = [
                changed or inside
                for changed, inside in zip(original_changed, span_mask)
            ]
            for tag, i1, i2, j1, _ in opcodes:
                if tag != "equal":
                    continue
                overlap_start = max(i1, span_start)
                overlap_end = min(i2, span_end)
                if overlap_start < overlap_end:
                    mapped_start = j1 + overlap_start - i1
                    mapped_end = j1 + overlap_end - i1
                    suggested_changed[mapped_start:mapped_end] = [True] * (
                        mapped_end - mapped_start
                    )
    original_styles = [
        _RED_STRIKE if changed else _RED_TEXT if term else _PLAIN
        for changed, term in zip(original_changed, term_mask)
    ]
    suggested_styles = [
        _RED_TEXT if changed else _PLAIN
        for changed in suggested_changed
    ]
    return (
        source_value,
        _formula_safe(_styled_graphemes(original_graphemes, original_styles)),
        _formula_safe(_styled_graphemes(suggested_graphemes, suggested_styles)),
    )


def build_rich_diff(
    original: str,
    suggested: str,
) -> tuple[str | CellRichText, str | CellRichText]:
    if original == suggested:
        return original, suggested
    _, original_value, suggested_value = build_review_rich_texts(
        "",
        original,
        suggested,
    )
    return original_value, suggested_value
