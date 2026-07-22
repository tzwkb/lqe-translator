"""Validate local correction edits and build complete corrected translations."""

from __future__ import annotations

import copy
import re

from lqe_engine import current_target


class CheckFormatError(ValueError):
    pass


_ISSUE_FIELDS = (
    "category",
    "severity",
    "comment",
    "protected",
    "repeated",
)
_EDIT_REQUIRED_FIELDS = {"from", "to", "evidence"}
_EDIT_OPTIONAL_FIELDS = {"start", "end"}
_PROVENANCE_FIELDS = {
    "finding_origin",
    "ai_reviewed",
    "review_module",
    "reviewed_segment_id",
    "edit_origin",
    "ai_edited",
}
_PROVENANCE_ORIGINS = {"ai_module", "machine_precheck", "script_derived"}
_VARIABLE_RE = re.compile(r"\{[^{}]*\}|%(?:\d+\$)?[sd]")
_TAG_RE = re.compile(
    r"<[^<>]+>|\[[^\[\]]+\]|#(?:G|C|Y|E)(?=$|[^A-Za-z])"
)


def _canonical_review_provenance(value: object, *, label: str) -> dict:
    if not isinstance(value, dict):
        raise CheckFormatError(f"{label}: review_provenance must be an object")
    if set(value) != _PROVENANCE_FIELDS:
        raise CheckFormatError(f"{label}: review_provenance has invalid fields")

    ai_reviewed = value["ai_reviewed"]
    if type(ai_reviewed) is not bool:
        raise CheckFormatError(f"{label}: ai_reviewed must be boolean")
    if type(value["ai_edited"]) is not bool:
        raise CheckFormatError(f"{label}: ai_edited must be boolean")

    finding_origin = value["finding_origin"]
    if finding_origin not in _PROVENANCE_ORIGINS:
        raise CheckFormatError(
            f"{label}: review_provenance finding_origin is invalid"
        )
    edit_origin = value["edit_origin"]
    if edit_origin is not None and edit_origin not in _PROVENANCE_ORIGINS:
        raise CheckFormatError(
            f"{label}: review_provenance edit_origin is invalid"
        )
    review_module = value["review_module"]
    if review_module is not None and (
        not isinstance(review_module, str) or not review_module.strip()
    ):
        raise CheckFormatError(
            f"{label}: review_provenance review_module is invalid"
        )
    reviewed_segment_id = value["reviewed_segment_id"]
    if reviewed_segment_id is not None and type(reviewed_segment_id) is not int:
        raise CheckFormatError(
            f"{label}: review_provenance reviewed_segment_id is invalid"
        )

    if ai_reviewed:
        if review_module is None or reviewed_segment_id is None:
            raise CheckFormatError(
                f"{label}: AI-reviewed provenance requires review_module and "
                "reviewed_segment_id"
            )
    elif review_module is not None or reviewed_segment_id is not None:
        raise CheckFormatError(
            f"{label}: unreviewed provenance cannot name a review module or segment"
        )
    if finding_origin == "ai_module" and not ai_reviewed:
        raise CheckFormatError(
            f"{label}: AI-origin finding must be AI-reviewed"
        )
    if finding_origin == "ai_module" and edit_origin == "machine_precheck":
        raise CheckFormatError(
            f"{label}: AI-origin finding cannot claim a machine edit"
        )
    if edit_origin == "ai_module" and not ai_reviewed:
        raise CheckFormatError(
            f"{label}: AI-origin edit requires AI review"
        )

    return {
        "finding_origin": finding_origin,
        "ai_reviewed": ai_reviewed,
        "ai_edited": False,
        "review_module": review_module,
        "reviewed_segment_id": reviewed_segment_id,
        "edit_origin": edit_origin,
    }


def _canonical_issue(
    value: object,
    *,
    label: str,
    allow_internal_provenance: bool = False,
    require_internal_provenance: bool = False,
) -> dict:
    if not isinstance(value, dict):
        raise CheckFormatError(f"{label}: issue must be an object")

    for field in ("category", "severity", "comment"):
        if field not in value or not isinstance(value[field], str):
            raise CheckFormatError(f"{label}: {field} must be a string")
    if not value["comment"].strip():
        raise CheckFormatError(f"{label}: comment must be non-empty")
    if "needs_confirmation" not in value:
        raise CheckFormatError(f"{label}: needs_confirmation is required")
    needs_confirmation = value["needs_confirmation"]
    if type(needs_confirmation) is not bool:
        raise CheckFormatError(f"{label}: needs_confirmation must be boolean")
    for field in ("protected", "repeated"):
        if field in value and type(value[field]) is not bool:
            raise CheckFormatError(f"{label}: {field} must be boolean")

    if "edit" in value:
        edit = value["edit"]
        if edit is not None and not isinstance(edit, dict):
            raise CheckFormatError(f"{label}: edit must be an object or null")
        edit = copy.deepcopy(edit) if edit is not None else None
    else:
        edit = None

    result = {
        key: copy.deepcopy(value[key]) for key in _ISSUE_FIELDS if key in value
    }
    if "precheck_ref" in value:
        precheck_ref = value["precheck_ref"]
        if not isinstance(precheck_ref, str) or not precheck_ref.strip():
            raise CheckFormatError(f"{label}: precheck_ref must be a non-empty string")
        result["precheck_ref"] = precheck_ref
    if require_internal_provenance and "review_provenance" not in value:
        raise CheckFormatError(f"{label}: review_provenance is required")
    if allow_internal_provenance and "review_provenance" in value:
        result["review_provenance"] = _canonical_review_provenance(
            value["review_provenance"], label=label
        )
        edit_origin = result["review_provenance"]["edit_origin"]
        if (edit is None) != (edit_origin is None):
            raise CheckFormatError(
                f"{label}: edit_origin must be null exactly when edit is null"
            )
    result["needs_confirmation"] = needs_confirmation
    result["edit"] = edit
    return result


def normalize_check_entries(
    entries: object,
    *,
    label: str,
    allow_internal_provenance: bool = False,
    require_internal_provenance: bool = False,
) -> list[dict]:
    if require_internal_provenance and not allow_internal_provenance:
        raise CheckFormatError(
            f"{label}: requiring provenance also requires internal provenance mode"
        )
    if not isinstance(entries, list):
        raise CheckFormatError(f"{label}: check entries must be an array")

    normalized = []
    seen_ids = set()
    for index, entry in enumerate(entries):
        entry_label = f"{label}[{index}]"
        if not isinstance(entry, dict):
            raise CheckFormatError(f"{entry_label}: entry must be an object")
        if "id" not in entry or type(entry["id"]) is not int:
            raise CheckFormatError(f"{entry_label}: id must be an integer")
        segment_id = entry["id"]
        if segment_id in seen_ids:
            raise CheckFormatError(f"{label}: duplicate id {segment_id}")
        seen_ids.add(segment_id)
        if "corrected" in entry:
            raise CheckFormatError(f"{entry_label}: corrected is not allowed")
        issues = entry.get("issues")
        if not isinstance(issues, list):
            raise CheckFormatError(f"{entry_label}: issues must be an array")
        normalized.append(
            {
                "id": segment_id,
                "issues": [
                    _canonical_issue(
                        issue,
                        label=f"{entry_label}.issues[{issue_index}]",
                        allow_internal_provenance=allow_internal_provenance,
                        require_internal_provenance=require_internal_provenance,
                    )
                    for issue_index, issue in enumerate(issues)
                ],
            }
        )
    return normalized


def _validate_evidence(value: object, *, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise CheckFormatError(f"{label}: edit evidence must be an object or null")
    if set(value) != {"type", "source", "target"}:
        raise CheckFormatError(f"{label}: edit evidence has invalid fields")
    if not all(isinstance(value.get(field), str) for field in value):
        raise CheckFormatError(f"{label}: edit evidence fields must be strings")


def _occurrence_starts(text: str, value: str) -> list[int]:
    starts = []
    start = text.find(value)
    while start >= 0:
        starts.append(start)
        start = text.find(value, start + 1)
    return starts


def _resolve_edit(value: dict, original: str, *, label: str) -> dict:
    fields = set(value)
    if not _EDIT_REQUIRED_FIELDS.issubset(fields) or not fields.issubset(
        _EDIT_REQUIRED_FIELDS | _EDIT_OPTIONAL_FIELDS
    ):
        raise CheckFormatError(f"{label}: edit has invalid fields")

    frm = value["from"]
    to = value["to"]
    if not isinstance(frm, str) or not frm or not isinstance(to, str):
        raise CheckFormatError(f"{label}: edit from/to must be non-empty/string")
    _validate_evidence(value["evidence"], label=label)

    has_start = "start" in value
    has_end = "end" in value
    if has_start != has_end:
        raise CheckFormatError(f"{label}: edit start/end must be provided together")
    if has_start:
        start = value["start"]
        end = value["end"]
        if type(start) is not int or type(end) is not int:
            raise CheckFormatError(f"{label}: edit start/end must be integers")
        if start < 0 or end < start or end > len(original) or original[start:end] != frm:
            raise CheckFormatError(f"{label}: edit start/end does not match from")
    else:
        starts = _occurrence_starts(original, frm)
        if len(starts) != 1:
            raise CheckFormatError(f"{label}: edit from must be unique without start/end")
        start = starts[0]
        end = start + len(frm)

    return {
        "from": frm,
        "to": to,
        "start": start,
        "end": end,
        "evidence": copy.deepcopy(value["evidence"]),
    }


def _overlaps(left: dict, right: dict) -> bool:
    return left["start"] < right["end"] and right["start"] < left["end"]


def _same_edit(left: dict, right: dict) -> bool:
    return all(left[key] == right[key] for key in ("start", "end", "from", "to"))


def _term_spans(original: str, term_hits: object) -> list[tuple[int, int]]:
    spans = []
    if not isinstance(term_hits, list):
        return spans
    for hit in term_hits:
        if not isinstance(hit, dict):
            continue
        matched_text = hit.get("matched_text")
        value = (
            matched_text
            if isinstance(matched_text, str) and matched_text
            else hit.get("target")
        )
        if not isinstance(value, str) or not value:
            continue
        start = original.find(value)
        while start >= 0:
            spans.append((start, start + len(value)))
            start = original.find(value, start + 1)
    return spans


def _requires_term_evidence(segment: dict, resolved: dict, original: str) -> bool:
    if segment.get("kind") == "name":
        return True
    if any(
        resolved["start"] < end and start < resolved["end"]
        for start, end in _term_spans(original, segment.get("term_hits"))
    ):
        return True
    targets = [
        hit.get("target")
        for hit in segment.get("term_hits", [])
        if isinstance(hit, dict) and isinstance(hit.get("target"), str)
    ]
    return any(target and target in resolved["to"] for target in targets)


def _has_matching_confirmed_term(
    segment: dict, resolved: dict, original: str
) -> bool:
    evidence = resolved["evidence"]
    if not isinstance(evidence, dict) or evidence.get("type") != "confirmed_term":
        return False
    if evidence.get("target") != resolved["to"]:
        return False
    term_hits = segment.get("term_hits")
    if not isinstance(term_hits, list):
        return False
    if segment.get("kind") == "name":
        if resolved["start"] != 0 or resolved["end"] != len(original):
            return False
        confirmed_hits = [
            hit
            for hit in term_hits
            if isinstance(hit, dict) and hit.get("confirmed") is True
        ]
        if len(confirmed_hits) != 1:
            return False
        hit = confirmed_hits[0]
        return (
            hit.get("source") == evidence.get("source")
            and hit.get("target") == evidence.get("target")
        )
    for hit in term_hits:
        if not isinstance(hit, dict):
            continue
        if not (
            hit.get("source") == evidence.get("source")
            and hit.get("target") == evidence.get("target")
            and hit.get("confirmed") is True
        ):
            continue
        matched_text = hit.get("matched_text")
        if matched_text is not None and matched_text != resolved["from"]:
            # The hit records the exact rendering found in the target; an edit
            # that cites this confirmed term but rewrites a different surface
            # form is misattributed and must not be auto-applied.
            continue
        return True
    return False


def _protection_signature(text: str, protected_texts: object) -> tuple:
    protected = []
    if isinstance(protected_texts, list):
        protected = [value for value in protected_texts if isinstance(value, str) and value]
    return (
        tuple(_VARIABLE_RE.findall(text)),
        tuple(_TAG_RE.findall(text)),
        text.count("\n"),
        text.count(r"\n"),
        tuple((value, text.count(value)) for value in protected),
    )


def _damages_protected_text(segment: dict, original: str, resolved: dict) -> bool:
    candidate = (
        original[: resolved["start"]]
        + resolved["to"]
        + original[resolved["end"] :]
    )
    return _protection_signature(candidate, segment.get("protected_texts")) != (
        _protection_signature(original, segment.get("protected_texts"))
    )


def build_segment_result(
    segment: dict,
    issues: list[dict],
    *,
    allow_internal_provenance: bool = False,
    require_internal_provenance: bool = False,
) -> dict:
    if require_internal_provenance and not allow_internal_provenance:
        raise CheckFormatError(
            "requiring provenance also requires internal provenance mode"
        )
    if not isinstance(segment, dict) or type(segment.get("id")) is not int:
        raise CheckFormatError("segment id must be an integer")
    original = current_target(segment)
    if not isinstance(original, str):
        raise CheckFormatError(f"segment {segment['id']}: target must be a string")
    if not isinstance(issues, list):
        raise CheckFormatError(f"segment {segment['id']}: issues must be an array")

    errors = [
        _canonical_issue(
            value,
            label=f"segment {segment['id']}.issues[{index}]",
            allow_internal_provenance=allow_internal_provenance,
            require_internal_provenance=require_internal_provenance,
        )
        for index, value in enumerate(issues)
    ]
    resolved_by_index = {}
    for index, error in enumerate(errors):
        edit = error["edit"]
        if error["needs_confirmation"] and edit is not None:
            raise CheckFormatError(
                f"segment {segment['id']}.issues[{index}]: confirmation issue cannot carry edit"
            )
        if edit is None:
            continue
        resolved = _resolve_edit(
            edit, original, label=f"segment {segment['id']}.issues[{index}]"
        )
        evidence = resolved["evidence"]
        evidence_target_mismatch = (
            isinstance(evidence, dict) and evidence.get("target") != resolved["to"]
        )
        has_confirmed_term_evidence = (
            isinstance(evidence, dict) and evidence.get("type") == "confirmed_term"
        )
        requires_term_evidence = _requires_term_evidence(segment, resolved, original)
        if evidence_target_mismatch or (
            (requires_term_evidence or has_confirmed_term_evidence)
            and not _has_matching_confirmed_term(segment, resolved, original)
        ):
            error["needs_confirmation"] = True
            error["edit"] = None
            if "review_provenance" in error:
                error["review_provenance"]["edit_origin"] = None
            continue
        if _damages_protected_text(segment, original, resolved):
            error["needs_confirmation"] = True
            error["edit"] = None
            if "review_provenance" in error:
                error["review_provenance"]["edit_origin"] = None
            continue
        resolved_by_index[index] = resolved

    conflicts = set()
    resolved_items = list(resolved_by_index.items())
    for left_position, (left_index, left) in enumerate(resolved_items):
        for right_index, right in resolved_items[left_position + 1 :]:
            if _overlaps(left, right) and not _same_edit(left, right):
                conflicts.update((left_index, right_index))
    for index in conflicts:
        errors[index]["needs_confirmation"] = True
        errors[index]["edit"] = None
        if "review_provenance" in errors[index]:
            errors[index]["review_provenance"]["edit_origin"] = None

    unique_edits = {}
    for index, resolved in resolved_items:
        if index in conflicts:
            continue
        key = (resolved["start"], resolved["end"], resolved["from"], resolved["to"])
        unique_edits.setdefault(key, resolved)

    corrected = original
    for resolved in sorted(
        unique_edits.values(), key=lambda value: value["start"], reverse=True
    ):
        corrected = (
            corrected[: resolved["start"]]
            + resolved["to"]
            + corrected[resolved["end"] :]
        )

    for index, error in enumerate(errors):
        provenance = error.get("review_provenance")
        resolved = resolved_by_index.get(index)
        if not isinstance(provenance, dict) or resolved is None:
            continue
        provenance["ai_edited"] = bool(
            provenance["ai_reviewed"]
            and provenance["edit_origin"] == "ai_module"
            and index not in conflicts
            and resolved["from"] != resolved["to"]
        )

    return {
        "id": segment["id"],
        "errors": errors,
        "corrected": corrected if corrected != original else None,
    }


def verify_results(
    segments: list[dict],
    results: object,
    label: str,
    *,
    allow_internal_provenance: bool = False,
    require_internal_provenance: bool = False,
) -> list[dict]:
    if not isinstance(results, list):
        raise CheckFormatError(f"{label}: results must be an array")

    required = {"id", "errors", "corrected"}
    result_ids = []
    for index, entry in enumerate(results):
        entry_label = f"{label}[{index}]"
        if not isinstance(entry, dict):
            raise CheckFormatError(f"{entry_label}: result must be an object")
        missing_fields = sorted(required - entry.keys())
        if missing_fields:
            raise CheckFormatError(
                f"{entry_label}: missing fields: {missing_fields}"
            )
        if type(entry["id"]) is not int:
            raise CheckFormatError(f"{entry_label}: id must be an integer")
        result_ids.append(entry["id"])

    segment_ids = [segment.get("id") for segment in segments]
    missing = sorted(set(segment_ids) - set(result_ids))
    extra = sorted(set(result_ids) - set(segment_ids))
    duplicate_ids = sorted(
        {result_id for result_id in result_ids if result_ids.count(result_id) > 1}
    )
    if missing or extra or duplicate_ids:
        details = [f"missing={missing}", f"extra={extra}"]
        if duplicate_ids:
            details.append(f"duplicates={duplicate_ids}")
        raise CheckFormatError(f"{label} id coverage: {' '.join(details)}")

    by_id = {entry["id"]: entry for entry in results}
    verified = []
    for segment in segments:
        entry = by_id[segment["id"]]
        rebuilt = build_segment_result(
            segment,
            entry["errors"],
            allow_internal_provenance=allow_internal_provenance,
            require_internal_provenance=require_internal_provenance,
        )
        if entry["corrected"] != rebuilt["corrected"]:
            raise CheckFormatError(
                f"{label} segment {segment['id']}: corrected mismatch"
            )
        verified.append(rebuilt)
    return verified


def build_results(
    segments: list[dict],
    check_entries: list[dict],
    *,
    allow_internal_provenance: bool = False,
    require_internal_provenance: bool = False,
) -> list[dict]:
    normalized = normalize_check_entries(
        check_entries,
        label="checks",
        allow_internal_provenance=allow_internal_provenance,
        require_internal_provenance=require_internal_provenance,
    )
    issues_by_id = {entry["id"]: entry["issues"] for entry in normalized}
    return [
        build_segment_result(
            segment,
            issues_by_id.get(segment.get("id"), []),
            allow_internal_provenance=allow_internal_provenance,
            require_internal_provenance=require_internal_provenance,
        )
        for segment in segments
    ]
