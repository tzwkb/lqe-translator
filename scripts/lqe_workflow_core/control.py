"""Shared stage decisions and acceptance rules; execution stays in adapters."""
from __future__ import annotations

import math

from .issues import CLOSED, blocks_dispute, summary
from .store import fingerprint


def policy(*, threshold=98.0, audit_rate=1.0, max_cycles=None, max_seconds=None,
           acceptance_mode="strict") -> dict:
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 98 <= threshold <= 100:
        raise ValueError("自动达标门槛必须在98到100之间")
    if type(audit_rate) not in (int, float) or not 0 < audit_rate <= 1:
        raise ValueError("抽查比例必须大于0且不超过1")
    if max_cycles is not None and (type(max_cycles) is not int or max_cycles < 2):
        raise ValueError("执行上限至少为2，必须保留独立终审")
    if acceptance_mode not in {"strict", "score_threshold"}:
        raise ValueError("未知验收策略")
    if max_seconds is not None and (type(max_seconds) not in (int, float)
            or not math.isfinite(max_seconds) or max_seconds <= 0):
        raise ValueError("任务总时间上限必须是正数")
    return {"schema_version": 2, "workflow_mode": "incremental_v2", "threshold": float(threshold),
            "review_strategy": "module_batches",
            "critical_gate": True, "audit_rate": audit_rate, "max_cycles": max_cycles,
            "acceptance_mode": acceptance_mode, "max_seconds": max_seconds,
            **({"execution_policy_version": 1} if acceptance_mode == "score_threshold" else {}),
            "max_no_progress_cycles": 3, "max_repair_attempts_per_issue": 3, "max_workers": 4}


def blocking_disputes(issues, rules):
    return [i for i in issues if i["status"] == "disputed"
            and blocks_dispute(i, rules.get("acceptance_mode", "strict"))]


def actionable_issues(issues, rules):
    """Keep deferred disagreements in history without spending more repair work on them."""
    return [i for i in issues if i["status"] not in CLOSED
            and (i["status"] != "disputed" or blocks_dispute(i, rules.get("acceptance_mode", "strict")))]


def next_action(kind: str, *, working_ready: bool, final_pass: bool, disputed: bool) -> str:
    if kind not in {"baseline", "incremental", "final"}:
        raise ValueError("未知审校阶段")
    if kind == "final":
        return "deliver" if final_pass and not disputed else "repair"
    return "final" if working_ready and not disputed else "repair"


def review_budget_exhausted(action: str, *, completed: int, maximum: int | None) -> bool:
    """Reserve a local review and a full final audit before spending on another repair."""
    required = {"deliver": 0, "final": 1, "repair": 2}[action]
    return required > 0 and maximum is not None and maximum - completed < required


def check_acceptance(*, kind, revision, reviewed_revision, keys, reviewed_keys,
                     score, threshold, status, critical, pending_changes, disputed,
                     structure_ok, fresh_review) -> None:
    if kind != "final" or revision != reviewed_revision or list(keys) != list(reviewed_keys):
        raise ValueError("最终验收必须覆盖当前完整版本")
    if (type(score) not in (int, float) or not math.isfinite(score) or score < threshold
            or score > 100 or status != "PASS" or critical):
        raise ValueError("最终审校未通过分数或严重错误门槛")
    if pending_changes or disputed or not structure_ok or not fresh_review:
        raise ValueError("仍有未验证修改、争议或结构问题，或终审复用了旧判断")


def state_signature(segments, issues, kind):
    return fingerprint({"targets": [(s["segment_key"], s["target"]) for s in segments],
                        "issues": sorted((i["issue_id"], i["status"], i.get("severity")) for i in issues),
                        "kind": kind})


def has_progress(previous, current):
    resolved = {i["issue_id"] for i in current if i["status"] in CLOSED}
    old = {i["issue_id"] for i in previous if i["status"] in CLOSED}
    return bool(not previous or resolved - old or summary(current)["active"] < summary(previous)["active"])
