"""Cross-review issues: absence is a dispute, never automatic resolution."""
from __future__ import annotations

import copy

from .store import fingerprint

CLOSED = {"resolved_verified", "dismissed_with_evidence"}


def repair_attempts(issue: dict) -> int:
    """Count the current unresolved episode; old records stay conservative."""
    return issue.get("attempts_since_resolution", issue.get("attempts", 0))


def record_repair_attempt(issue: dict) -> None:
    issue["attempts_since_resolution"] = repair_attempts(issue) + 1
    issue["attempts"] = issue.get("attempts", 0) + 1


def identity(key: str, error: dict) -> str:
    # Native findings do not always have spans. Ambiguous same-category findings
    # are grouped conservatively and must be resolved together with explicit evidence.
    return "issue_" + fingerprint([key, error.get("category"), error.get("rule_id"),
                                   error.get("term_source"), error.get("source_span")
                                   or (error.get("term_spans") or {}).get("source")])[:20]


def ingest(previous: list[dict], segments: list[dict], findings: dict[str, list[dict]],
           review_id: str, revision: int, verdicts: dict[str, dict] | None = None) -> list[dict]:
    items = {item["issue_id"]: copy.deepcopy(item) for item in previous}
    current = {s["segment_key"]: s for s in segments}
    observed = {}
    for key, errors in findings.items():
        if key not in current:
            raise ValueError("问题引用了未知分段")
        for error in errors:
            iid = identity(key, error)
            observed.setdefault(iid, []).append(copy.deepcopy(error))
            if iid not in items:
                items[iid] = {"issue_id": iid, "segment_key": key, "category": error["category"],
                    "source": current[key]["source"],
                    "term_source": error.get("term_source"), "first_seen": review_id,
                    "status": "open", "events": [], "attempts": 0, "attempts_since_resolution": 0}
    for iid, item in items.items():
        key = item["segment_key"]
        if key not in findings:
            continue
        old = item["status"]
        errors = observed.get(iid)
        if errors:
            item["status"] = "reopened" if old in CLOSED else "open"
            if old in CLOSED:
                # A verified repair is not a failed attempt at a later recurrence.
                # Preserve lifetime attempts and the same issue/event identity.
                item["attempts_since_resolution"] = 0
            item["findings"] = errors
            item["severity"] = max((e["severity"] for e in errors),
                                  key=lambda s: {"Neutral": 0, "Minor": 1, "Major": 2, "Critical": 3}[s])
            item["last_target"] = current[key]["target"]
            item["last_seen"] = review_id
        elif old not in CLOSED:
            verdict = (verdicts or {}).get(iid)
            if verdict is None or verdict["decision"] in {"retained", "inconclusive"}:
                item["status"] = "disputed"
            elif verdict["decision"] == "resolved":
                if item["last_target"] == current[key]["target"]:
                    raise ValueError("未修改的原问题只能经明确裁决撤销，不能标为已修复")
                item["status"] = "resolved_verified"
            elif verdict["decision"] == "dismissed":
                item["status"] = "dismissed_with_evidence"
            else:
                raise ValueError("无效的问题裁决")
        # A repeated retained/inconclusive verdict is still new review evidence,
        # even when the issue remains disputed. Keep every explicit adjudication.
        if errors or old != item["status"] or iid in (verdicts or {}):
            item["events"].append({"review_id": review_id, "revision": revision,
                "from": old, "to": item["status"], "evidence": copy.deepcopy((verdicts or {}).get(iid)),
                "target": current[key]["target"], "findings": copy.deepcopy(errors or []),
                "attempts": item.get("attempts", 0), "attempts_since_resolution": repair_attempts(item)})
    return list(items.values())


def blocks_dispute(issue: dict, acceptance_mode: str = "strict") -> bool:
    if acceptance_mode not in {"strict", "score_threshold"}:
        raise ValueError("未知验收策略")
    # Unknown severity is never silently treated as harmless.
    return acceptance_mode == "strict" or issue.get("severity") not in {"Major", "Minor", "Neutral"}


def reconciliation_needed(previous: list[dict], findings: dict[str, list[dict]], *,
                          acceptance_mode: str = "strict") -> list[dict]:
    observed = {identity(key, error) for key, errors in findings.items() for error in errors}
    return [item for item in previous if item["status"] not in CLOSED
            and item["segment_key"] in findings and item["issue_id"] not in observed
            and blocks_dispute(item, acceptance_mode)]


def summary(items: list[dict], delivered: bool = False) -> dict[str, int]:
    return {"active": sum(i["status"] not in CLOSED for i in items),
            "resolved": sum(i["status"] == "resolved_verified" for i in items),
            "dismissed": sum(i["status"] == "dismissed_with_evidence" for i in items),
            "disputed": sum(i["status"] == "disputed" for i in items),
            "reopened": sum(i["status"] == "reopened" for i in items),
            "residual": sum(i["status"] not in CLOSED for i in items) if delivered else 0}


def validate_verdicts(issues: list[dict], segments: list[dict], verdicts: list[dict]) -> dict:
    """Absence alone never closes an issue; bind an explicit verdict to current text."""
    if not isinstance(verdicts, list):
        raise ValueError("历史问题裁决必须是列表")
    requested = {i["issue_id"]: i for i in issues}
    current = {s["segment_key"]: s["target"] for s in segments}
    result = {}
    for verdict in verdicts:
        if not isinstance(verdict, dict):
            raise ValueError("历史问题裁决无效")
        iid = verdict.get("issue_id")
        if iid not in requested or iid in result:
            raise ValueError("历史裁决包含未知或重复问题")
        if verdict.get("decision") not in {"resolved", "dismissed", "retained", "inconclusive"}:
            raise ValueError("历史问题裁决无效")
        for field in ("evidence", "rule_basis", "target_quote"):
            if not isinstance(verdict.get(field), str) or not verdict[field].strip():
                raise ValueError("历史问题裁决缺少具体证据")
        target = current[requested[iid]["segment_key"]]
        if verdict["target_quote"] not in target:
            raise ValueError("裁决引用的译文不在当前版本中")
        if verdict["decision"] == "resolved" and target == requested[iid]["last_target"]:
            raise ValueError("原译文未变，不能把旧判断标记为已修复")
        result[iid] = copy.deepcopy(verdict)
    if set(result) != set(requested):
        raise ValueError("历史活跃问题未全部核对")
    return result
