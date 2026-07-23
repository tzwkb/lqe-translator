#!/usr/bin/env python3
"""Build compact, module-specific review packets and publish sparse AI drafts.

The formal module artifacts are unchanged. Compact drafts prove which packet was
reviewed, list every reviewed id, and include only ids with findings. This script
expands them to the complete ``{id, issues}`` array before delegating publication
to ``lqe_chunk.py``.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile

from lqe_chunk import (
    _MODULE_ALLOWED_CATEGORIES,
    _load_verified_generation_unlocked,
    _normalize_module_output,
    cmd_publish_module,
)
from lqe_engine import read_json as load, required_modules
from lqe_paths import write_json_atomic
from lqe_split_contract import canonical_digest, generation_lock, publish_generation


PACKET_SCHEMA = "lqe.review-packet"
PACKET_VERSION = 1
PACKET_MANIFEST_SCHEMA = "lqe.review-packet-manifest"
BATCH_PLAN_SCHEMA = "lqe.review-worker-batch-plan"
COMPACT_DRAFT_SCHEMA = "lqe.compact-module-draft"
COMPACT_DRAFT_VERSION = 1
MAX_PACKETS_PER_WORKER = 4
MAX_REVIEW_TEXT_CHARS_PER_WORKER = 25_000
MAX_PACKET_BYTES_PER_WORKER = 100_000

_BASE_FIELDS = (
    "id",
    "source",
    "target",
    "content_type",
    "text_type_context",
    "context_note",
    "kind",
    "protected_texts",
)
_TERM_MODULES = {"terminology"}
_PRECHECK_MODULES = {"terminology", "precheck_review"}
_SUPPORTED_MODULES = {
    "terminology",
    "precheck_review",
    "accuracy",
    "grammar",
    "naturalness",
}


def _json_bytes(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _with_digest(payload: dict, field: str) -> dict:
    output = copy.deepcopy(payload)
    output.pop(field, None)
    output[field] = canonical_digest(output)
    return output


def _nonempty(value: object) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _owned_precheck(segment: dict, module: str) -> list[dict]:
    allowed = _MODULE_ALLOWED_CATEGORIES[module]
    raw = segment.get("precheck")
    if not isinstance(raw, list):
        return []
    return [
        copy.deepcopy(issue)
        for issue in raw
        if isinstance(issue, dict) and issue.get("category") in allowed
    ]


def _project_segment(segment: dict, module: str) -> dict | None:
    if segment.get("protected") is True:
        return None

    precheck = _owned_precheck(segment, module)
    if module == "precheck_review" and not precheck:
        return None

    projected = {}
    for field in _BASE_FIELDS:
        value = segment.get(field)
        if field in {"id", "source", "target", "kind"} or _nonempty(value):
            projected[field] = copy.deepcopy(value)

    if module in _PRECHECK_MODULES and precheck:
        projected["precheck"] = precheck
    if module in _TERM_MODULES:
        for field in ("term_hits", "term_near"):
            value = segment.get(field)
            if _nonempty(value):
                projected[field] = copy.deepcopy(value)
    return projected


def build_review_packet(base: dict, module: str) -> dict:
    if module not in _SUPPORTED_MODULES:
        raise ValueError(f"compact review does not support module {module!r}")

    segments = []
    protected = 0
    not_applicable = 0
    for segment in base["segments"]:
        if segment.get("protected") is True:
            protected += 1
            continue
        projected = _project_segment(segment, module)
        if projected is None:
            not_applicable += 1
            continue
        segments.append(projected)

    reviewed_ids = [segment["id"] for segment in segments]
    review_text_chars = sum(
        len(segment.get("source") or "") + len(segment.get("target") or "")
        for segment in segments
    )
    payload = {
        "schema": PACKET_SCHEMA,
        "version": PACKET_VERSION,
        "module": module,
        "chunk_id": base["chunk_id"],
        "iteration": base.get("iteration", 0),
        "split_fingerprint": base["split_fingerprint"],
        "chunk_payload_digest": base["payload_digest"],
        "reviewed_ids": reviewed_ids,
        "review_text_chars": review_text_chars,
        "segments": segments,
        "auto_empty": {
            "protected": protected,
            "not_applicable": not_applicable,
        },
        "requires_ai": bool(reviewed_ids),
    }
    return _with_digest(payload, "packet_digest")


def _packet_name(packet: dict) -> str:
    return f"{packet['module']}/chunk_{packet['chunk_id']:02d}.json"


def build_worker_batch_plan(
    split_manifest: dict,
    modules: list[str],
    packets: list[dict],
) -> dict:
    batches_by_module = {}
    for module in modules:
        module_packets = sorted(
            (
                packet
                for packet in packets
                if packet["module"] == module and packet["requires_ai"]
            ),
            key=lambda packet: packet["chunk_id"],
        )
        batches = []
        current = []
        current_chars = 0
        current_bytes = 0

        def flush() -> None:
            nonlocal current, current_chars, current_bytes
            if not current:
                return
            batches.append(
                {
                    "batch_id": len(batches),
                    "packet_count": len(current),
                    "review_text_chars": current_chars,
                    "packet_bytes": current_bytes,
                    "packets": current,
                }
            )
            current = []
            current_chars = 0
            current_bytes = 0

        for packet in module_packets:
            packet_chars = packet["review_text_chars"]
            packet_bytes = _json_bytes(packet)
            would_exceed = current and (
                len(current) >= MAX_PACKETS_PER_WORKER
                or current_chars + packet_chars
                > MAX_REVIEW_TEXT_CHARS_PER_WORKER
                or current_bytes + packet_bytes > MAX_PACKET_BYTES_PER_WORKER
            )
            if would_exceed:
                flush()
            current.append(
                {
                    "path": _packet_name(packet),
                    "chunk_id": packet["chunk_id"],
                    "packet_digest": packet["packet_digest"],
                    "review_text_chars": packet_chars,
                    "packet_bytes": packet_bytes,
                }
            )
            current_chars += packet_chars
            current_bytes += packet_bytes
        flush()
        batches_by_module[module] = batches

    payload = {
        "schema": BATCH_PLAN_SCHEMA,
        "version": PACKET_VERSION,
        "split_fingerprint": split_manifest["split_fingerprint"],
        "policy": {
            "max_packets_per_worker": MAX_PACKETS_PER_WORKER,
            "max_review_text_chars_per_worker": (
                MAX_REVIEW_TEXT_CHARS_PER_WORKER
            ),
            "max_packet_bytes_per_worker": MAX_PACKET_BYTES_PER_WORKER,
            "oversized_single_packet_runs_alone": True,
        },
        "modules": batches_by_module,
    }
    return _with_digest(payload, "batch_plan_digest")


def _build_cost_report(
    bases: list[dict],
    modules: list[str],
    packets: list[dict],
    batch_plan: dict,
) -> dict:
    full_bytes = sum(_json_bytes(base) for base in bases) * len(modules)
    packet_bytes = sum(_json_bytes(packet) for packet in packets)
    reviews_before = (
        sum(len(base.get("segments", [])) for base in bases) * len(modules)
    )
    reviews_after = sum(len(packet["reviewed_ids"]) for packet in packets)
    reduction = 0.0 if full_bytes == 0 else (1 - packet_bytes / full_bytes) * 100
    return {
        "basis": "canonical JSON payload bytes; excludes shared project context",
        "required_modules": modules,
        "chunks": len(bases),
        "full_chunk_input_bytes": full_bytes,
        "review_packet_input_bytes": packet_bytes,
        "input_reduction_percent": round(reduction, 1),
        "segment_reviews_before": reviews_before,
        "segment_reviews_after": reviews_after,
        "segment_review_reduction": reviews_before - reviews_after,
        "no_ai_packets": sum(not packet["requires_ai"] for packet in packets),
        "worker_batches": sum(
            len(batches) for batches in batch_plan["modules"].values()
        ),
    }


def _build_packet_manifest(
    split_manifest: dict,
    modules: list[str],
    packets: list[dict],
    batch_plan: dict,
) -> dict:
    payload = {
        "schema": PACKET_MANIFEST_SCHEMA,
        "version": PACKET_VERSION,
        "split_fingerprint": split_manifest["split_fingerprint"],
        "split_manifest_digest": split_manifest["manifest_digest"],
        "required_modules": modules,
        "batch_plan_digest": batch_plan["batch_plan_digest"],
        "packets": {
            _packet_name(packet): packet["packet_digest"] for packet in packets
        },
    }
    return _with_digest(payload, "manifest_digest")


def _packet_tree_is_current(
    active: Path,
    packet_manifest: dict,
    packets: list[dict],
    cost_report: dict,
    batch_plan: dict,
) -> bool:
    try:
        if load(active / "manifest.json") != packet_manifest:
            return False
        if load(active / "cost_report.json") != cost_report:
            return False
        if load(active / "batch_plan.json") != batch_plan:
            return False
        for packet in packets:
            if load(active / _packet_name(packet)) != packet:
                return False
    except (OSError, ValueError):
        return False
    return True


def cmd_prepare(args) -> None:
    job = Path(args.job)
    chunks = job / "chunks"
    with generation_lock(chunks, exclusive=False):
        state = load(job / "state.json")
        split_manifest, bases, _, _, _ = _load_verified_generation_unlocked(
            job / "state.json",
            job / "errors_precheck.json",
            chunks,
            state=state,
        )
        modules = required_modules(state)
        unsupported = sorted(set(modules) - _SUPPORTED_MODULES)
        if unsupported:
            raise SystemExit(
                "[review-prepare] unsupported required modules: "
                + ", ".join(unsupported)
            )
        packets = [
            build_review_packet(base, module)
            for module in modules
            for base in bases
        ]
        batch_plan = build_worker_batch_plan(
            split_manifest,
            modules,
            packets,
        )
        cost_report = _build_cost_report(
            bases,
            modules,
            packets,
            batch_plan,
        )
        packet_manifest = _build_packet_manifest(
            split_manifest,
            modules,
            packets,
            batch_plan,
        )
        active = job / "review_packets"
        if _packet_tree_is_current(
            active,
            packet_manifest,
            packets,
            cost_report,
            batch_plan,
        ):
            print(f"[review-prepare] existing packets are current: {active}")
            print(
                "[review-prepare] input payload reduction "
                f"{cost_report['input_reduction_percent']}%"
            )
            return

        with tempfile.TemporaryDirectory(
            dir=job,
            prefix=".review_packets.generation.",
        ) as staging_name:
            staging = Path(staging_name)
            for packet in packets:
                write_json_atomic(staging / _packet_name(packet), packet)
            write_json_atomic(staging / "manifest.json", packet_manifest)
            write_json_atomic(staging / "cost_report.json", cost_report)
            write_json_atomic(staging / "batch_plan.json", batch_plan)
            publish_generation(
                staging,
                active,
                archive_label=split_manifest["split_fingerprint"][:12],
            )

    print(
        f"[review-prepare] {len(packets)} packets -> {active}; "
        f"input payload reduction {cost_report['input_reduction_percent']}%"
    )
    print(
        "[review-prepare] AI segment reviews "
        f"{cost_report['segment_reviews_before']} -> "
        f"{cost_report['segment_reviews_after']}; "
        f"no-AI packets {cost_report['no_ai_packets']}; "
        f"worker batches {cost_report['worker_batches']}"
    )


def _live_review_packet(
    job: Path,
    chunk_id: int,
    module: str,
) -> tuple[dict, dict]:
    chunks = job / "chunks"
    with generation_lock(chunks, exclusive=False):
        state = load(job / "state.json")
        _, bases, _, _, _ = _load_verified_generation_unlocked(
            job / "state.json",
            job / "errors_precheck.json",
            chunks,
            state=state,
        )
        if module not in required_modules(state):
            raise SystemExit(
                f"[review-publish] module {module!r} is not required by scope"
            )
        base = next(
            (item for item in bases if item["chunk_id"] == chunk_id),
            None,
        )
        if base is None:
            raise SystemExit(
                f"[review-publish] chunk {chunk_id} is not in the live generation"
            )
        return base, build_review_packet(base, module)


def _load_compact_draft(
    path: Path,
    packet: dict,
) -> list[dict]:
    raw = load(path)
    if not isinstance(raw, dict):
        raise ValueError("compact draft must be an object")
    expected_fields = {
        "schema",
        "version",
        "module",
        "chunk_id",
        "packet_digest",
        "reviewed_ids",
        "findings",
    }
    if set(raw) != expected_fields:
        raise ValueError("compact draft fields are invalid")
    expected_bindings = {
        "schema": COMPACT_DRAFT_SCHEMA,
        "version": COMPACT_DRAFT_VERSION,
        "module": packet["module"],
        "chunk_id": packet["chunk_id"],
        "packet_digest": packet["packet_digest"],
    }
    for field, value in expected_bindings.items():
        if raw.get(field) != value:
            raise ValueError(f"compact draft {field} mismatch")
    reviewed_ids = raw.get("reviewed_ids")
    if reviewed_ids != packet["reviewed_ids"]:
        raise ValueError(
            "compact draft reviewed_ids must exactly match the review packet"
        )

    findings = _normalize_module_output(raw.get("findings"), path)
    reviewed_set = set(reviewed_ids)
    for entry in findings:
        if entry["id"] not in reviewed_set:
            raise ValueError(
                f"compact draft finding id {entry['id']} was not reviewed"
            )
        if not entry["issues"]:
            raise ValueError(
                f"compact draft finding id {entry['id']} has no issues; omit it"
            )
    return findings


def _publish_full_entries(
    job: Path,
    base: dict,
    module: str,
    entries: list[dict],
) -> None:
    with tempfile.TemporaryDirectory(
        dir=job,
        prefix=".compact-module-draft.",
    ) as temp_name:
        expanded = Path(temp_name) / "expanded.json"
        write_json_atomic(expanded, entries)
        cmd_publish_module(
            SimpleNamespace(
                job=str(job),
                chunk=base["chunk_id"],
                module=module,
                input=str(expanded),
                split_fingerprint=base["split_fingerprint"],
                chunk_payload_digest=base["payload_digest"],
            )
        )


def _expand_findings(base: dict, findings: list[dict]) -> list[dict]:
    issues_by_id = {entry["id"]: entry["issues"] for entry in findings}
    return [
        {
            "id": segment["id"],
            "issues": issues_by_id.get(segment["id"], []),
        }
        for segment in base["segments"]
    ]


def cmd_publish(args) -> None:
    job = Path(args.job)
    base, packet = _live_review_packet(job, args.chunk, args.module)
    try:
        findings = _load_compact_draft(Path(args.input), packet)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"[review-publish] {exc}") from exc
    entries = _expand_findings(base, findings)
    _publish_full_entries(job, base, args.module, entries)
    print(
        f"[review-publish] reviewed {len(packet['reviewed_ids'])}, "
        f"findings {len(findings)}, formal coverage {len(entries)}"
    )


def cmd_auto_publish(args) -> None:
    job = Path(args.job)
    chunks = job / "chunks"
    with generation_lock(chunks, exclusive=False):
        state = load(job / "state.json")
        _, bases, _, _, _ = _load_verified_generation_unlocked(
            job / "state.json",
            job / "errors_precheck.json",
            chunks,
            state=state,
        )
        pending = [
            (base, module)
            for module in required_modules(state)
            for base in bases
            if not build_review_packet(base, module)["requires_ai"]
        ]

    for base, module in pending:
        entries = [
            {"id": segment["id"], "issues": []}
            for segment in base["segments"]
        ]
        _publish_full_entries(job, base, module, entries)
    print(f"[review-auto-publish] published {len(pending)} no-AI packets")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--job", required=True)
    prepare.set_defaults(function=cmd_prepare)

    publish = sub.add_parser("publish")
    publish.add_argument("--job", required=True)
    publish.add_argument("--chunk", required=True, type=int)
    publish.add_argument("--module", required=True)
    publish.add_argument("--input", required=True)
    publish.set_defaults(function=cmd_publish)

    auto_publish = sub.add_parser("auto-publish")
    auto_publish.add_argument("--job", required=True)
    auto_publish.set_defaults(function=cmd_auto_publish)

    args = parser.parse_args()
    args.function(args)


if __name__ == "__main__":
    main()
