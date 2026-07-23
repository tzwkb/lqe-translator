#!/usr/bin/env python3
"""Prepare and publish report-only reference translation suggestions."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

from lqe_chunk import verification_generation_lease
from lqe_corrections import (
    CheckFormatError,
    validate_reference_target,
    verify_results,
)
from lqe_engine import (
    VALID_CATEGORIES,
    current_target,
    read_json,
    requires_bound_artifacts,
)
from lqe_paths import write_json_atomic
from lqe_result_contract import result_contract_path, validate_result_contract
from lqe_split_contract import canonical_digest


PACKET_SCHEMA = "lqe.reference-suggestion-packet"
PACKET_VERSION = 1
DRAFT_SCHEMA = "lqe.reference-suggestion-draft"
DRAFT_VERSION = 1
ARTIFACT_SCHEMA = "lqe.reference-suggestions"
ARTIFACT_VERSION = 1
PACKET_NAME = "reference_suggestions.packet.json"
ARTIFACT_NAME = "reference_suggestions.json"


def _with_digest(payload: dict, field: str) -> dict:
    output = copy.deepcopy(payload)
    output.pop(field, None)
    output[field] = canonical_digest(output)
    return output


def _results_basis(results: list[dict]) -> list[dict]:
    """Ignore score-only repeated annotations when binding suggestions."""
    basis = copy.deepcopy(results)
    for entry in basis:
        for issue in entry.get("errors", []):
            issue.pop("repeated", None)
    return basis


def _issue_projection(issue: dict) -> dict:
    return {
        key: copy.deepcopy(issue.get(key))
        for key in (
            "category",
            "severity",
            "comment",
            "needs_confirmation",
            "protected",
        )
        if key in issue
    }


def _normalize_selection(selection: object | None) -> dict:
    if selection is None:
        return {"categories": [], "only_missing": False}
    if not isinstance(selection, dict) or set(selection) != {
        "categories",
        "only_missing",
    }:
        raise ValueError("reference suggestion selection is invalid")
    categories = selection["categories"]
    only_missing = selection["only_missing"]
    if (
        not isinstance(categories, list)
        or any(
            not isinstance(category, str) or not category.strip()
            for category in categories
        )
        or len(categories) != len(set(categories))
    ):
        raise ValueError("reference suggestion categories are invalid")
    unknown = sorted(set(categories) - set(VALID_CATEGORIES))
    if unknown:
        raise ValueError(
            f"reference suggestion categories are unknown: {unknown}"
        )
    if type(only_missing) is not bool:
        raise ValueError("reference suggestion only_missing must be boolean")
    return {
        "categories": sorted(categories),
        "only_missing": only_missing,
    }


def build_suggestion_packet(
    segments: list[dict],
    manifest: dict | None,
    results: list[dict],
    *,
    selection: object | None = None,
) -> dict:
    selection = _normalize_selection(selection)
    selected_categories = set(selection["categories"])
    by_id = {entry["id"]: entry for entry in results}
    projected = []
    for segment in segments:
        entry = by_id[segment["id"]]
        errors = entry.get("errors") or []
        if segment.get("protected") is True or not errors:
            continue
        if selection["only_missing"] and entry.get("corrected") is not None:
            continue
        if selected_categories and not any(
            issue.get("category") in selected_categories
            for issue in errors
        ):
            continue
        item = {
            "id": segment["id"],
            "source": segment.get("source", ""),
            "target": current_target(segment),
            "validated_target": entry.get("corrected"),
            "errors": [_issue_projection(issue) for issue in errors],
        }
        for field in (
            "content_type",
            "text_type_context",
            "context_note",
            "kind",
            "protected_texts",
        ):
            value = segment.get(field)
            if value not in (None, "", [], {}):
                item[field] = copy.deepcopy(value)
        projected.append(item)

    payload = {
        "schema": PACKET_SCHEMA,
        "version": PACKET_VERSION,
        "manifest_digest": (
            manifest.get("manifest_digest") if isinstance(manifest, dict) else None
        ),
        "state_fingerprint": (
            manifest.get("state_fingerprint") if isinstance(manifest, dict) else None
        ),
        "selection": selection,
        "results_basis_digest": canonical_digest(_results_basis(results)),
        "reviewed_ids": [item["id"] for item in projected],
        "segments": projected,
        "instructions": {
            "purpose": "report_only_reference_translation",
            "sparse_suggestions_allowed": True,
            "preserve": [
                "variables",
                "tags",
                "line_breaks",
                "protected_texts",
            ],
            "do_not_apply_to_corrected_export": True,
        },
    }
    return _with_digest(payload, "packet_digest")


def _verify_results(
    job: Path,
    state: dict,
    segments: list[dict],
    manifest: dict | None,
    errors_path: Path,
) -> list[dict]:
    results = read_json(errors_path)
    bound = requires_bound_artifacts(state)
    if bound:
        contract_path = result_contract_path(errors_path)
        if manifest is None or not contract_path.is_file():
            raise CheckFormatError(
                f"{errors_path.name}: bound result contract is required"
            )
        validate_result_contract(
            read_json(contract_path),
            manifest,
            results,
            label=errors_path.name,
        )
    return verify_results(
        segments,
        results,
        str(errors_path),
        allow_internal_provenance=bound,
        require_internal_provenance=bound,
    )


def _load_live(
    job: Path,
    *,
    state_name: str = "state.json",
    errors_name: str = "errors.json",
) -> tuple[dict, list[dict], dict | None, list[dict]]:
    state_path = job / state_name
    errors_path = job / errors_name
    if not state_path.is_file():
        raise FileNotFoundError(f"state is missing: {state_path}")
    if not errors_path.is_file():
        raise FileNotFoundError(f"errors are missing: {errors_path}")
    with verification_generation_lease(
        state_path,
        exclusive=False,
    ) as (state, segments, manifest, _):
        results = _verify_results(job, state, segments, manifest, errors_path)
        return state, segments, manifest, results


def validate_suggestion_artifact(
    artifact: object,
    packet: dict,
    segments: list[dict],
) -> dict[int, str]:
    if not isinstance(artifact, dict):
        raise ValueError("reference suggestion artifact must be an object")
    if artifact.get("schema") != ARTIFACT_SCHEMA:
        raise ValueError("reference suggestion artifact schema is invalid")
    if artifact.get("version") != ARTIFACT_VERSION:
        raise ValueError("reference suggestion artifact version is invalid")
    if artifact.get("packet_digest") != packet["packet_digest"]:
        raise ValueError("reference suggestion artifact is stale")
    if artifact.get("selection") != packet["selection"]:
        raise ValueError("reference suggestion artifact selection is stale")
    if artifact.get("manifest_digest") != packet["manifest_digest"]:
        raise ValueError("reference suggestion artifact manifest is stale")
    if artifact.get("results_basis_digest") != packet["results_basis_digest"]:
        raise ValueError("reference suggestion artifact results are stale")
    if artifact.get("reviewed_ids") != packet["reviewed_ids"]:
        raise ValueError("reference suggestion artifact reviewed ids are stale")

    entries = artifact.get("entries")
    if not isinstance(entries, list):
        raise ValueError("reference suggestion artifact entries must be an array")
    if artifact.get("entries_digest") != canonical_digest(entries):
        raise ValueError("reference suggestion artifact entries digest is invalid")
    expected_artifact = _with_digest(
        {
            key: copy.deepcopy(value)
            for key, value in artifact.items()
            if key != "artifact_digest"
        },
        "artifact_digest",
    )
    if artifact != expected_artifact:
        raise ValueError("reference suggestion artifact digest is invalid")

    segment_map = {segment["id"]: segment for segment in segments}
    allowed = set(packet["reviewed_ids"])
    output = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {
            "id",
            "reference_target",
        }:
            raise ValueError(
                f"reference suggestion entries[{index}] has invalid fields"
            )
        segment_id = entry["id"]
        if type(segment_id) is not int or segment_id not in allowed:
            raise ValueError(
                f"reference suggestion entries[{index}] has invalid id"
            )
        if segment_id in output:
            raise ValueError(
                f"reference suggestion artifact has duplicate id {segment_id}"
            )
        output[segment_id] = validate_reference_target(
            segment_map[segment_id],
            entry["reference_target"],
            label=f"reference suggestion entries[{index}]",
        )
    return output


def load_reference_suggestions(
    job: Path,
    segments: list[dict],
    manifest: dict | None,
    results: list[dict],
) -> dict[int, str]:
    artifact_path = Path(job) / ARTIFACT_NAME
    if not artifact_path.is_file():
        return {}
    artifact = read_json(artifact_path)
    if not isinstance(artifact, dict):
        raise ValueError("reference suggestion artifact must be an object")
    selection = _normalize_selection(artifact.get("selection"))
    packet = build_suggestion_packet(
        segments,
        manifest,
        results,
        selection=selection,
    )
    return validate_suggestion_artifact(
        artifact,
        packet,
        segments,
    )


def cmd_prepare(args) -> None:
    job = Path(args.job).resolve()
    _, segments, manifest, results = _load_live(
        job,
        state_name=args.state,
        errors_name=args.errors,
    )
    categories = [
        category.strip()
        for category in (args.categories or "").split(",")
        if category.strip()
    ]
    packet = build_suggestion_packet(
        segments,
        manifest,
        results,
        selection={
            "categories": categories,
            "only_missing": args.only_missing,
        },
    )
    output = Path(args.out) if args.out else job / PACKET_NAME
    write_json_atomic(output, packet)
    print(
        f"[lqe_suggestions] Packet → {output} "
        f"({len(packet['reviewed_ids'])} segment(s))"
    )


def cmd_publish(args) -> None:
    job = Path(args.job).resolve()
    _, segments, manifest, results = _load_live(
        job,
        state_name=args.state,
        errors_name=args.errors,
    )
    draft = read_json(Path(args.input))
    if not isinstance(draft, dict):
        raise ValueError("reference suggestion draft must be an object")
    if draft.get("schema") != DRAFT_SCHEMA or draft.get("version") != DRAFT_VERSION:
        raise ValueError("reference suggestion draft schema/version is invalid")
    selection = _normalize_selection(draft.get("selection"))
    packet = build_suggestion_packet(
        segments,
        manifest,
        results,
        selection=selection,
    )
    if draft.get("packet_digest") != packet["packet_digest"]:
        raise ValueError("reference suggestion draft is stale")
    if draft.get("reviewed_ids") != packet["reviewed_ids"]:
        raise ValueError("reference suggestion draft reviewed ids are incomplete or stale")
    suggestions = draft.get("suggestions")
    if not isinstance(suggestions, list):
        raise ValueError("reference suggestion draft suggestions must be an array")

    segment_map = {segment["id"]: segment for segment in segments}
    allowed = set(packet["reviewed_ids"])
    entries = []
    seen = set()
    for index, suggestion in enumerate(suggestions):
        if not isinstance(suggestion, dict) or set(suggestion) != {
            "id",
            "reference_target",
        }:
            raise ValueError(
                f"reference suggestion draft suggestions[{index}] has invalid fields"
            )
        segment_id = suggestion["id"]
        if type(segment_id) is not int or segment_id not in allowed:
            raise ValueError(
                f"reference suggestion draft suggestions[{index}] has invalid id"
            )
        if segment_id in seen:
            raise ValueError(
                f"reference suggestion draft has duplicate id {segment_id}"
            )
        seen.add(segment_id)
        reference_target = validate_reference_target(
            segment_map[segment_id],
            suggestion["reference_target"],
            label=f"reference suggestion draft suggestions[{index}]",
        )
        entries.append(
            {"id": segment_id, "reference_target": reference_target}
        )

    order = {segment_id: index for index, segment_id in enumerate(packet["reviewed_ids"])}
    entries.sort(key=lambda entry: order[entry["id"]])
    artifact = {
        "schema": ARTIFACT_SCHEMA,
        "version": ARTIFACT_VERSION,
        "packet_digest": packet["packet_digest"],
        "manifest_digest": packet["manifest_digest"],
        "selection": packet["selection"],
        "results_basis_digest": packet["results_basis_digest"],
        "reviewed_ids": packet["reviewed_ids"],
        "entries": entries,
        "entries_digest": canonical_digest(entries),
    }
    artifact = _with_digest(artifact, "artifact_digest")
    output = Path(args.out) if args.out else job / ARTIFACT_NAME
    write_json_atomic(output, artifact)
    print(
        f"[lqe_suggestions] Artifact → {output} "
        f"({len(entries)} suggestion(s))"
    )


def cmd_validate(args) -> None:
    job = Path(args.job).resolve()
    _, segments, manifest, results = _load_live(
        job,
        state_name=args.state,
        errors_name=args.errors,
    )
    artifact_path = Path(args.input) if args.input else job / ARTIFACT_NAME
    artifact = read_json(artifact_path)
    if not isinstance(artifact, dict):
        raise ValueError("reference suggestion artifact must be an object")
    selection = _normalize_selection(artifact.get("selection"))
    packet = build_suggestion_packet(
        segments,
        manifest,
        results,
        selection=selection,
    )
    suggestions = validate_suggestion_artifact(
        artifact,
        packet,
        segments,
    )
    print(
        f"[lqe_suggestions] Valid → {artifact_path} "
        f"({len(suggestions)} suggestion(s))"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage report-only reference translation suggestions."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "publish", "validate"):
        command = subparsers.add_parser(name)
        command.add_argument("--job", required=True)
        command.add_argument("--state", default="state.json")
        command.add_argument("--errors", default="errors.json")
        if name == "prepare":
            command.add_argument("--out")
            command.add_argument(
                "--categories",
                help="Comma-separated issue categories to include.",
            )
            command.add_argument(
                "--only-missing",
                action="store_true",
                help="Include only segments without a validated local suggestion.",
            )
            command.set_defaults(func=cmd_prepare)
        elif name == "publish":
            command.add_argument("--input", required=True)
            command.add_argument("--out")
            command.set_defaults(func=cmd_publish)
        else:
            command.add_argument("--input")
            command.set_defaults(func=cmd_validate)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except (CheckFormatError, OSError, ValueError) as exc:
        raise SystemExit(f"[lqe_suggestions] {exc}") from exc


if __name__ == "__main__":
    main()
