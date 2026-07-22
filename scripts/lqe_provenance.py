"""Render trusted issue provenance for user-facing reports."""

from __future__ import annotations


AUDIT_HEADER_BASES = {
    "segment_id": "LQE Segment ID",
    "issue_number": "LQE 错误序号",
    "review_status": "LQE AI 复核状态",
    "edit_status": "LQE AI 编辑状态",
    "check_source": "LQE 检查来源",
}


def issue_review_columns(
    issue: dict | None,
    segment_id: int | None = None,
) -> tuple[str, str, str]:
    if issue is None:
        return "不适用", "不适用", "不适用"
    provenance = issue.get("review_provenance")
    if not isinstance(provenance, dict):
        return (
            "未知（旧流程未记录）",
            "未知（旧流程未记录）",
            "旧流程（来源未记录）",
        )

    ai_reviewed = provenance.get("ai_reviewed") is True
    ai_edited = ai_reviewed and provenance.get("ai_edited") is True
    reviewed_segment_id = provenance.get("reviewed_segment_id")
    if ai_reviewed and (
        type(reviewed_segment_id) is int
        and segment_id is not None
        and reviewed_segment_id != segment_id
    ):
        review_status = (
            f"已复核（复用 Segment {reviewed_segment_id}；AI 模块记录）"
        )
    elif ai_reviewed:
        review_status = "已复核（AI 模块记录）"
    elif provenance.get("finding_origin") == "machine_precheck":
        review_status = "未确认（机器预检保留）"
    elif provenance.get("finding_origin") == "script_derived":
        review_status = "未由 AI 复核（脚本规则）"
    else:
        review_status = "未由 AI 复核"

    if ai_edited:
        edit_status = "已生成并验证建议（AI 模块记录）"
    elif ai_reviewed:
        edit_status = "已复核、未生成 AI 建议"
    else:
        edit_status = "未由 AI 编辑"

    finding_origin = provenance.get("finding_origin")
    module = provenance.get("review_module")
    module_label = (
        f"AI 模块：{module.strip()}"
        if isinstance(module, str) and module.strip()
        else "AI 模块（名称未记录）"
    )
    if finding_origin == "machine_precheck" and ai_reviewed:
        source = f"机器预检 → {module_label}"
    elif finding_origin == "machine_precheck":
        source = "机器预检"
    elif finding_origin == "ai_module":
        source = module_label
    elif finding_origin == "script_derived":
        source = "脚本规则"
    else:
        source = "来源未记录"
    return review_status, edit_status, source


def issue_detail(issue: dict | None) -> str:
    if issue is None:
        return ""
    return (
        f"[{issue.get('category', '?')} · {issue.get('severity', '?')}] "
        f"{issue.get('comment', '')}"
    )
