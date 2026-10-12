"""Lossless small-review reading packs; native packets remain authoritative."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .review_audit import DECISION_SCHEMA, STRUCTURED_DECISION_SCHEMA, REVIEW_GUIDANCE, precheck_items, validate_decisions
from .review_task import FINDING_CONTRACT, checker_task, validate_bound_worker
from .store import fingerprint, immutable, read

MAX_SEGMENTS = 30
MAX_TEXT_CHARS = 6000
MAX_READING_BYTES = 250_000
MODULES = {"terminology", "precheck_review", "accuracy", "grammar", "naturalness"}


def factor(records: dict[str, dict]) -> dict:
    values = list(records.values())
    common = {k: v for k, v in values[0].items() if all(k in x and x[k] == v for x in values)}
    return {"common": common, "by_module": {m: {k: v for k, v in x.items() if k not in common}
                                              for m, x in records.items()}}


def expand(value: dict) -> dict:
    return {m: value["common"] | fields for m, fields in value["by_module"].items()}


def factor_collection(records: dict[str, dict], field: str, key) -> dict:
    """Factor a keyed row collection and preserve each module's row order."""
    bases = {m: {k: v for k, v in x.items() if k != field} for m, x in records.items()}
    rows = {}
    for module, record in records.items():
        for row in record[field]:
            rows.setdefault(str(key(row)), {})[module] = row
    return {"base": factor(bases), "field": field,
            "order": {m: [str(key(r)) for r in x[field]] for m, x in records.items()},
            "rows": {k: factor(v) for k, v in rows.items()}}


def expand_collection(value: dict) -> dict:
    records = expand(value["base"])
    rows = {k: expand(v) for k, v in value["rows"].items()}
    return {m: base | {value["field"]: [rows[k][m] for k in value["order"][m]]}
            for m, base in records.items()}


def _within(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("审校资料路径超出绑定范围或文件缺失")
    return path


def _bound_json(path: Path, field: str, expected: str | None = None) -> dict:
    value = read(path)
    actual = fingerprint({k: v for k, v in value.items() if k != field})
    if value.get(field) != actual or (expected is not None and actual != expected):
        raise ValueError(f"审校资料摘要不一致：{path.name}")
    return value


def inventory(job: Path) -> tuple[dict, dict, list[dict]]:
    directory = job / "review_packets"
    manifest = _bound_json(directory / "manifest.json", "manifest_digest")
    plan = _bound_json(directory / "batch_plan.json", "batch_plan_digest", manifest["batch_plan_digest"])
    packets = [_bound_json(_within(directory, name), "packet_digest", digest)
               for name, digest in manifest["packets"].items()]
    return manifest, plan, packets


def _small_inputs(job: Path, runtime: Path, plan: dict, packets: list[dict]) -> tuple[dict | None, str]:
    active = [p for p in packets if p["requires_ai"]]
    modules = {p["module"] for p in active}
    if (not {"accuracy", "grammar", "naturalness"}.issubset(modules)
            or not modules.issubset(MODULES) or len(active) != len(modules)):
        return None, "multiple_packets_or_custom_modules"
    segments = {s["id"]: s for p in active for s in p["segments"]}
    if any(s.get("context_projection", {}).get("extensions") for p in active for s in p["segments"]):
        return None, "specialized_context"
    if len(segments) > MAX_SEGMENTS or sum(len(s["source"]) + len(s["target"]) for s in segments.values()) > MAX_TEXT_CHARS:
        return None, "text_budget"
    contexts, manifests, resources = {}, {}, {}
    directory = job / "review_packets"
    for module in sorted(modules):
        batches = plan["modules"][module]
        if len(batches) != 1:
            return None, "multiple_batches"
        batch = batches[0]
        wm = _bound_json(_within(directory, batch["worker_context_manifest_path"]),
                         "worker_context_manifest_digest", batch["worker_context_manifest_digest"])
        bundles = _bound_json(_within(directory, batch["context_bundle_set_path"]),
                              "context_bundle_set_digest", batch["context_bundle_set_digest"])
        # Custom/strict module projections must retain their separate evidence boundary.
        if (set(bundles["capabilities"]["enabled"]) - {"context.core@1", "source_provenance@1"}
                or any(bundles["shared_context_assets"].values())):
            return None, "specialized_context"
        for bundle in bundles["bundles"]:
            if (bundle["neighbors"] or bundle["resolved_constraints"] or bundle["runtime_example_ids"]
                    or bundle["entity_fact_ids"] or bundle["relation_ids"] or bundle["term_evidence_ids"]):
                return None, "specialized_context"
        for resource in [wm.get("language_notes"), *wm["worker_documents"], *wm["instructions"].values()]:
            if not resource:
                continue
            locator = resource["locator"]
            if locator["kind"] == "embedded_text":
                data = locator["content"].encode("utf-8")
            elif locator["kind"] in {"job_relative", "skill_relative"}:
                root = job if locator["kind"] == "job_relative" else runtime
                path = _within(root, locator["path"])
                data = path.read_bytes()
            else:
                return None, "unsupported_resource_locator"
            if hashlib.sha256(data).hexdigest() != resource["sha256"]:
                raise ValueError("审校资源在准备期间发生变化")
            resources.setdefault(resource["sha256"], {"sha256": resource["sha256"], "text": data.decode("utf-8")})
        manifests[module], contexts[module] = wm, bundles
    packet_records = {p["module"]: p for p in active}
    selected = _bound_json(directory / "selected_evidence_index.json", "index_digest")
    selected_rows = {m: {"entries": [r for r in selected["entries"] if r["module"] == m]}
                     for m in selected["modules"]}
    selected_view = {"header": {k: v for k, v in selected.items() if k != "entries"},
        "entries": factor_collection(selected_rows, "entries", lambda r: r["segment_id"]),
        "order": [[r["module"], str(r["segment_id"])] for r in selected["entries"]]}
    output_fields = ("module", "chunk_id", "packet_digest", "worker_batch_id", "worker_packet_basis_digest",
        "context_bundle_set_digest", "worker_context_manifest_digest", "selected_evidence_index_path",
        "selected_evidence_index_digest", "reviewed_ids")
    packed = {"guidance": REVIEW_GUIDANCE.replace("record retained/dismissed", "record confirmed_error/no_error"),
        "decision_schema": STRUCTURED_DECISION_SCHEMA, "response_transport_version": 2,
        "finding_contract": FINDING_CONTRACT | {"retained_precheck":
            "For confirmed_error embed the finding only in that hint's decision. Do not repeat it in findings_by_module. Frozen term facts and offsets are joined by the program from precheck_ref."},
        "resources": list(resources.values()),
        "manifests": factor(manifests),
        "packets": factor_collection(packet_records, "segments", lambda s: s["id"]),
        "contexts": factor_collection(contexts, "bundles", lambda b: b["segment"]["identity"]["id"]),
        "selected_evidence": selected_view,
        "related_context": read(job / "scoped_context.json") if (job / "scoped_context.json").is_file() else {},
        "output_templates": {m: {"schema": "lqe.compact-module-draft", "version": 1,
            **{k: p[k] for k in output_fields}, "findings": [],
            "worker_receipt": {"worker_id": "ACTUAL_WORKER_ID", "run_id": "FRESH_RUN_ID"}}
            for m, p in packet_records.items()},
        "format": "Merge common with by_module[module] (shallow override). Rebuild collections in order[module] from rows. This exactly reconstructs every native packet, context bundle and worker manifest. Apply module-specific fields only to that module. Read shared resources once. Produce a separate compact draft for every module and precheck_decisions.json for all hints. Use one actual fresh worker identity for this assignment; never fabricate identities."}
    terms_path = job / "terms.json"
    if terms_path.is_file():
        terms = read(terms_path)
        # This is a literal candidate lookup, never a terminology verdict. Keep
        # full entries/notes so workers need not query the entire project again.
        packed["term_candidates"] = {"applies_to_modules": sorted(modules & {"terminology", "precheck_review"}),
            "rule": "Literal source matches only. Check each sense in context; a match is not proof of an error.",
            "entries": [term for term in terms if isinstance(term, dict)
                and isinstance(term.get("source"), str) and term["source"]
                and any(term["source"].casefold() in s["source"].casefold() for s in segments.values())]}
    if (expand(packed["manifests"]) != manifests
            or expand_collection(packed["packets"]) != packet_records
            or expand_collection(packed["contexts"]) != contexts):
        raise ValueError("阅读包无法无损还原原生审校资料")
    unpacked_rows = {m: {str(r["segment_id"]): r for r in rows["entries"]}
                     for m, rows in expand_collection(selected_view["entries"]).items()}
    if selected_view["header"] | {"entries": [unpacked_rows[m][sid] for m, sid in selected_view["order"]]} != selected:
        raise ValueError("阅读包无法无损还原绑定证据索引")
    return packed, "small_flat_document"


def prepare_execution(job: Path, runtime: Path) -> dict:
    if (job / "review_execution.json").is_file():
        execution = read(job / "review_execution.json")
        validate_prepared_execution(job, execution)
        return execution  # Resume the frozen contract, never silently upgrade it.
    manifest, plan, packets = inventory(job)
    packed, reason = _small_inputs(job, runtime, plan, packets)
    # Common module rules are overridden only for the explicitly assigned set:
    # each module still has its own original packet, scope and formal receipt.
    if packed and len(json.dumps(packed, ensure_ascii=False, separators=(",", ":")).encode()) > MAX_READING_BYTES:
        packed, reason = None, "reading_budget"
    before = sum(b["worker_input_bytes"] for batches in plan["modules"].values() for b in batches)
    if packed:
        reading = job / "review_reading.json"
        text = json.dumps(packed, ensure_ascii=False, separators=(",", ":"))
        if reading.exists():
            if reading.read_text() != text:
                raise ValueError("不能覆盖已有的审校阅读包")
        else:
            reading.write_text(text, encoding="utf-8")
    view = template = None
    if packed:
        import uuid
        from .review_view import render_view, response_template
        view = render_view(packed)
        template_path = job / "review_response.template.json"
        assignment = read(template_path)["assignment_id"] if template_path.exists() else str(uuid.uuid4())
        template = response_template(packed, assignment)
        path = job / "checker_view.md"
        if path.exists() and path.read_text(encoding="utf-8") != view:
            raise ValueError("不能覆盖已有的审校阅读视图")
        if not path.exists():
            path.write_text(view, encoding="utf-8")
        immutable(job / "review_response.template.json", template)
    task = checker_task(structured_response=True) if packed else None
    if task is not None:
        path = job / "checker_task.md"
        if path.exists() and path.read_text(encoding="utf-8") != task:
            raise ValueError("不能覆盖已有的 checker 任务")
        if not path.exists():
            path.write_text(task, encoding="utf-8")
    execution = {"version": 2, "mode": "small_multi_module" if packed else "module_batches",
        "reason": reason, "packet_manifest_digest": manifest["manifest_digest"],
        "worker_count": 1 if packed else sum(len(x) for x in plan["modules"].values()),
        "original_worker_input_bytes": before,
        "reading_bytes": len(text.encode()) if packed else None,
        "reading_sha256": hashlib.sha256(text.encode()).hexdigest() if packed else None,
        "checker_task_path": "checker_task.md" if task else None,
        "checker_task_sha256": hashlib.sha256(task.encode()).hexdigest() if task else None,
        "checker_view_sha256": hashlib.sha256(view.encode()).hexdigest() if view else None,
        "checker_view_bytes": len(view.encode()) if view else None,
        "response_template_sha256": hashlib.sha256((job / "review_response.template.json").read_bytes()).hexdigest() if template else None,
        "term_candidates_source_sha256": hashlib.sha256((job / "terms.json").read_bytes()).hexdigest()
            if packed and "term_candidates" in packed else None,
        "precheck_items": precheck_items(packets), "guidance": packed["guidance"] if packed else REVIEW_GUIDANCE,
        "decision_schema": packed["decision_schema"] if packed else DECISION_SCHEMA}
    immutable(job / "review_execution.json", execution)
    if not execution["precheck_items"]:
        immutable(job / "precheck_decisions.json", {"decisions": []})
    return execution


def validate_prepared_execution(job: Path, execution: dict) -> None:
    for field, name in (("checker_task_sha256", "checker_task.md"),
                        ("reading_sha256", "review_reading.json"),
                        ("checker_view_sha256", "checker_view.md"),
                        ("term_candidates_source_sha256", "terms.json"),
                        ("response_template_sha256", "review_response.template.json")):
        if execution.get(field) and hashlib.sha256((job / name).read_bytes()).hexdigest() != execution[field]:
            raise ValueError(f"冻结的审校输入发生变化：{name}")
    manifest, _, packets = inventory(job)
    if manifest["manifest_digest"] != execution["packet_manifest_digest"] or precheck_items(packets) != execution["precheck_items"]:
        raise ValueError("审校执行计划与当前原生检查不一致")


def validate_execution(job: Path) -> None:
    from .review_response import validate_response_binding
    validate_prepared_execution(job, read(job / "review_execution.json"))
    validate_bound_worker(job, job / "worker_drafts")
    validate_response_binding(job, job / "worker_drafts")
    _, _, packets = inventory(job)
    findings = {}
    for packet in packets:
        path = job / "chunks" / f"chunk_{packet['chunk_id']:02d}.{packet['module']}.json"
        module = read(path)
        entries = module["entries"] if isinstance(module, dict) else module
        for row in entries:
            findings[packet["module"], packet["chunk_id"], row["id"]] = row["issues"]
    validate_decisions(packets, read(job / "precheck_decisions.json")["decisions"], findings)


def validate_draft_decisions(job: Path, directory: Path) -> None:
    """Reject inconsistent judgments before the immutable native publications."""
    _, _, packets = inventory(job)
    expected = {(p["module"], p["chunk_id"]) for p in packets if p["requires_ai"]}
    seen, findings = set(), {}
    for path in directory.rglob("*.json"):
        draft = read(path)
        key = (draft.get("module"), draft.get("chunk_id"))
        if key not in expected or key in seen:
            raise ValueError("审校草稿包含未知或重复模块批次")
        seen.add(key)
        for entry in draft["findings"]:
            findings[key + (entry["id"],)] = entry["issues"]
    if seen != expected:
        raise ValueError("checker 草稿尚未全部完成")
    validate_decisions(packets, read(job / "precheck_decisions.json")["decisions"], findings)
