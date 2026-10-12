"""Export process records separately from the signed native final workbook."""
from pathlib import Path
import json
import zipfile

from openpyxl import Workbook

from lqe_workflow_core.store import load


def write_report(root: Path) -> dict:
    state = load(root)
    if not state:
        raise ValueError("工作流不存在")
    if state["status"] == "delivered":
        from lqe_workflow_session import verify
        verify(root)
    output = root / "process_report.xlsx"
    workbook = Workbook()
    overview = workbook.active
    overview.title = "过程说明"
    overview.append(["状态", state["status"]])
    overview.append(["最终分数", (state.get("final_score") or {}).get("score")])
    overview.append(["说明", "中间分数仅用于决定下一步；未通过全量终审不能交付。"])
    overview.append(["停止原因", state.get("stop_reason")])
    sheets = [("问题记录", state["issues"], ["issue_id", "segment_key", "status", "first_seen", "last_seen", "events"]),
              ("修改记录", state["changes"], ["segment_key", "revision", "before", "after", "reason", "status", "issue_ids"]),
              ("阶段用时", state["rounds"], ["kind", "revision", "status", "started_at", "completed_at", "score", "metrics", "plan"])]
    for name, rows, headers in sheets:
        sheet = workbook.create_sheet(name)
        sheet.append(headers)
        for row in rows:
            sheet.append([json.dumps(row.get(h), ensure_ascii=False) if isinstance(row.get(h), (dict, list))
                          else row.get(h) for h in headers])
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
    for sheet in workbook:
        for row in sheet:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = 25
    temporary = output.with_suffix(".tmp")
    workbook.save(temporary)
    workbook.close()
    temporary.replace(output)
    bundle = root / "workflow_audit.zip"
    with zipfile.ZipFile(bundle.with_suffix(".tmp"), "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(output, output.name)
        archive.writestr("workflow_snapshot.json", json.dumps(state, ensure_ascii=False, indent=2))
        for folder in ("requests", "responses", "workflow_events"):
            for path in sorted((root / folder).glob("*.json")):
                archive.write(path, str(path.relative_to(root)))
        if state["status"] == "delivered":
            for name in state["artifacts"]:
                archive.write(root / "delivery" / name, "delivery/" + name)
    bundle.with_suffix(".tmp").replace(bundle)
    return {"status": state["status"], "report": str(output), "bundle": str(bundle)}
