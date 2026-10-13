"""Native scoped jobs retain the complete context pool and original file identity."""
from __future__ import annotations


def context_segments(state: dict) -> list[dict]:
    scope = state.get("workflow_scope")
    if scope is None:
        return state.get("segments", [])
    if not isinstance(scope, dict) or scope.get("version") != 1:
        raise ValueError("unsupported workflow scope")
    pool = state.get("workflow_context_segments")
    if not isinstance(pool, list) or not pool:
        raise ValueError("workflow context pool is missing")
    by_key = {s["segment_key"]: s for s in pool}
    if len(by_key) != len(pool) or len({s["id"] for s in pool}) != len(pool):
        raise ValueError("workflow context pool contains duplicate identities")
    keys = [s["segment_key"] for s in state["segments"]]
    if keys != scope.get("selected_keys") or len(set(keys)) != len(keys):
        raise ValueError("workflow selected segment coverage differs")
    if scope.get("kind") not in {"baseline", "incremental", "final"}:
        raise ValueError("invalid workflow review kind")
    if scope["kind"] != "incremental" and keys != list(by_key):
        raise ValueError("baseline and final reviews require the full document")
    if any(by_key.get(s["segment_key"]) != s for s in state["segments"]):
        raise ValueError("scoped text differs from the complete document")
    return pool


def require_full_export(state: dict) -> None:
    if state.get("workflow_scope") is not None:
        context_segments(state)
        if state["workflow_scope"]["kind"] == "incremental":
            raise ValueError("局部审校只能生成过程记录，不能导出为完整交付稿")
