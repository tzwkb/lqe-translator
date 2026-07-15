"""Build paired Excel rich text for original and suggested translations."""

from __future__ import annotations

from difflib import SequenceMatcher

import regex

from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont


_RED = "FFFF0000"
_EXCEL_CELL_LIMIT = 32767
_SEQUENCE_MATCHER_PRODUCT_LIMIT = 4_000_000
_BOUNDED_EDIT_LIMIT = 256
_GRAPHEME_PATTERN = regex.compile(r"\X")


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


def _append(runs: list[tuple[str, bool]], text: str, changed: bool) -> None:
    if not text:
        return
    if runs and runs[-1][1] == changed:
        previous, _ = runs[-1]
        runs[-1] = (previous + text, changed)
    else:
        runs.append((text, changed))


def _to_excel_text(runs: list[tuple[str, bool]], *, strike: bool):
    if not any(changed for _, changed in runs):
        return "".join(text for text, _ in runs)
    values = []
    for text, changed in runs:
        if changed:
            values.append(
                TextBlock(InlineFont(color=_RED, strike=strike or None), text)
            )
        else:
            values.append(text)
    return CellRichText(values)


def build_rich_diff(
    original: str,
    suggested: str,
) -> tuple[str | CellRichText, str | CellRichText]:
    if original == suggested:
        return original, suggested
    if len(original) > _EXCEL_CELL_LIMIT or len(suggested) > _EXCEL_CELL_LIMIT:
        return original, suggested

    original_graphemes = _split_graphemes(original)
    suggested_graphemes = _split_graphemes(suggested)
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

    original_runs: list[tuple[str, bool]] = []
    suggested_runs: list[tuple[str, bool]] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag in {"equal", "delete", "replace"}:
            _append(
                original_runs,
                "".join(original_graphemes[i1:i2]),
                tag != "equal",
            )
        if tag in {"equal", "insert", "replace"}:
            _append(
                suggested_runs,
                "".join(suggested_graphemes[j1:j2]),
                tag != "equal",
            )
    original_value = _to_excel_text(original_runs, strike=True)
    suggested_value = _to_excel_text(suggested_runs, strike=False)
    if isinstance(original_value, str) and original_value.startswith("="):
        original_value = CellRichText([original_value])
    if isinstance(suggested_value, str) and suggested_value.startswith("="):
        suggested_value = CellRichText([suggested_value])
    return original_value, suggested_value
