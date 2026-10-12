"""Dependency-aware scoped reviews, with rotating discovery and full final audits."""
from __future__ import annotations

import math

from .store import fingerprint


def dependencies(segments: list[dict], index: int) -> set[str]:
    segment = segments[index]
    core = (segment.get("context") or {}).get("core") or {}
    group = core.get("group_id") or segment.get("group")
    keys = {item["segment_key"] for item in segments[max(0, index - 1):index + 2]}
    keys.update(segment.get("dependency_keys", []))
    if group:
        keys.update(item["segment_key"] for item in segments
                    if (((item.get("context") or {}).get("core") or {}).get("group_id")
                        or item.get("group")) == group)
    return keys


def context_digest(segments: list[dict], index: int, resource_digest: str) -> str:
    dependent = dependencies(segments, index)
    return fingerprint({"resources": resource_digest,
        "context": segments[index].get("context"), "constraints": segments[index].get("resolved_constraints"),
        "dependencies": [[item["segment_key"], item["source"], item["target"]]
                         for item in segments if item["segment_key"] in dependent]})


def make_plan(segments: list[dict], coverage: dict, issues: list[dict], *,
              kind: str, cycle: int, resource_digest: str, audit_rate: float = .1) -> dict:
    if not isinstance(audit_rate, (int, float)) or not 0 < audit_rate <= 1:
        raise ValueError("抽查比例必须大于0且不超过1")
    keys = [s["segment_key"] for s in segments]
    if len(keys) != len(set(keys)):
        raise ValueError("分段编号不唯一，不能增量审校")
    if kind not in {"baseline", "incremental", "final"}:
        raise ValueError("未知审校阶段")
    contexts = {s["segment_key"]: context_digest(segments, i, resource_digest)
                for i, s in enumerate(segments)}
    changed, affected = set(), set()
    for s in segments:
        key = s["segment_key"]
        old = coverage.get(key)
        if not old or old["target"] != s["target"] or old["source"] != s["source"]:
            changed.add(key)
        elif old["context_digest"] != contexts[key]:
            affected.add(key)
    active = [item for item in issues if item["status"] not in {"resolved_verified", "dismissed_with_evidence"}]
    unresolved = {item["segment_key"] for item in active}
    # A terminology decision affects every occurrence, including unchanged rows.
    terms = {item.get("term_source") for item in active if item.get("term_source")}
    affected.update(s["segment_key"] for s in segments
                    if any(term in s["source"] for term in terms))
    required = changed | affected | unresolved
    remainder = [key for key in keys if key not in required]
    # Oldest reviewed first; deterministic tie-break makes a resumed plan stable.
    remainder.sort(key=lambda key: (coverage.get(key, {}).get("last_sample_cycle", -1),
                                    fingerprint([key, cycle])))
    count = min(len(remainder), max(1, math.ceil(len(remainder) * audit_rate))) if remainder else 0
    sampled = set(remainder[:count])
    selected = set(keys) if kind != "incremental" else required | sampled
    return {"schema_version": 2, "kind": kind, "cycle": cycle,
            "document_digest": fingerprint([[s["segment_key"], s["source"], s["target"]] for s in segments]),
            "resource_digest": resource_digest, "selected_keys": [k for k in keys if k in selected],
            "contexts": contexts, "changed_keys": sorted(changed), "affected_keys": sorted(affected),
            "unresolved_keys": sorted(unresolved), "sampled_keys": sorted(sampled) if kind == "incremental" else [],
            "reused_keys": [k for k in keys if k not in selected],
            "total_segments": len(keys), "reviewed_segments": len(selected)}
