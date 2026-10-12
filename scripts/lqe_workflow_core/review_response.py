"""Expand model judgments into native drafts without authoring or modifying judgments."""
from __future__ import annotations

from pathlib import Path
import copy

from .review_audit import validate_decisions
from .store import atomic, read


def grouped_findings(entries: list) -> list:
    """Accept a flat issue transport without changing any semantic issue field."""
    if not entries or any(not isinstance(e, dict) or "issues" in e for e in entries):
        return entries
    groups = {}
    for entry in entries:
        if (type(entry.get("id")) is not int
                or not {"category", "severity", "comment"}.issubset(entry)):
            return entries  # Normal validation rejects malformed data, never fills a judgment.
        groups.setdefault(entry["id"], []).append({k: v for k, v in entry.items() if k != "id"})
    return [{"id": key, "issues": issues} for key, issues in groups.items()]


def compile_hint_judgments(response: dict, packets: list) -> dict:
    """A hint has one semantic judgment; native duplicates/offsets are program work."""
    if response.get("version") != 2:
        return response
    result = copy.deepcopy(response)
    findings = result["findings_by_module"]
    hints = {(p["module"], p["chunk_id"], s["id"], h.get("precheck_ref")): h
             for p in packets for s in p["segments"] for h in s.get("precheck", [])}
    for module, entries in findings.items():
        if not isinstance(entries, list):
            raise ValueError("模块问题必须是列表")
        findings[module] = grouped_findings(entries)
        for entry in findings[module]:
            if isinstance(entry, dict) and isinstance(entry.get("issues"), list):
                if any(isinstance(issue, dict) and "precheck_ref" in issue for issue in entry["issues"]):
                    raise ValueError("预检问题只在对应decision的finding中填写，不能重复上报")
    if not isinstance(result["decisions"], list):
        raise ValueError("预检逐项判断必须是列表")
    canonical = []
    for decision in result["decisions"]:
        if not isinstance(decision, dict):
            raise ValueError("预检逐项判断格式无效")
        if set(decision) - {"module", "chunk_id", "id", "precheck_ref", "decision", "applicability", "reason", "target_quote", "finding"}:
            raise ValueError("预检逐项判断包含未知字段")
        key = tuple(decision.get(k) for k in ("module", "chunk_id", "id", "precheck_ref"))
        if (not isinstance(key[0], str) or type(key[1]) is not int
                or type(key[2]) is not int or not isinstance(key[3], str)):
            raise ValueError("预检提示编号格式无效")
        if key not in hints:
            raise ValueError("预检逐项判断包含未知提示")
        verdict = decision.get("decision")
        if verdict not in {"confirmed_error", "no_error"}:
            raise ValueError("decision只能是confirmed_error或no_error；正确匹配术语是no_error")
        finding = decision.get("finding")
        if verdict == "no_error" and finding is not None:
            raise ValueError("no_error不能包含finding")
        if verdict == "confirmed_error":
            if not isinstance(finding, dict) or not {"category", "severity", "comment", "needs_confirmation", "edit"}.issubset(finding):
                raise ValueError("confirmed_error必须包含完整的finding判断")
            if finding["needs_confirmation"] is not True or finding["edit"] is not None:
                raise ValueError("本阶段只检测问题，finding必须needs_confirmation=true且edit=null")
            if any(k in finding for k in ("precheck_ref", "term_source", "expected_targets", "term_spans")):
                raise ValueError("预检finding不能重复填写冻结事实或字符位置")
            issue = finding | {"precheck_ref": key[3]}
            if finding["category"] == "Terminology":
                hint = hints[key]
                for field in ("term_source", "expected_targets", "term_spans"):
                    if field not in hint:
                        raise ValueError("冻结术语提示缺少事实字段：" + field)
                    issue[field] = copy.deepcopy(hint[field])
            if key[0] not in findings:
                raise ValueError("预检问题不属于本次指定模块")
            rows = findings[key[0]]
            existing = next((r for r in rows if isinstance(r, dict) and r.get("id") == key[2]), None)
            if existing is None:
                rows.append({"id": key[2], "issues": [issue]})
            elif not isinstance(existing.get("issues"), list):
                raise ValueError("模块问题格式无效")
            else:
                existing["issues"].append(issue)
        canonical.append({k: v for k, v in decision.items() if k != "finding"} |
                         {"decision": "retained" if verdict == "confirmed_error" else "dismissed"})
    result["decisions"] = canonical
    return result


def response_drafts(job: Path, response: dict | None = None, *, check_decisions: bool = True) -> tuple[dict, dict]:
    from .review_execution import inventory, validate_prepared_execution
    execution = read(job / "review_execution.json")
    validate_prepared_execution(job, execution)
    if not execution.get("checker_view_sha256"):
        raise ValueError("本阶段未启用结构化审校响应")
    response = read(job / "review_response.json") if response is None else response
    template = read(job / "review_response.template.json")
    if (set(response) != set(template) or any(response.get(k) != template[k]
            for k in ("schema", "version", "assignment_id", "reviewed_ids_by_module"))):
        raise ValueError("审校响应的任务绑定或完整覆盖不一致")
    findings = response["findings_by_module"]
    if not isinstance(findings, dict) or set(findings) != set(template["findings_by_module"]):
        raise ValueError("审校响应必须包含每个指定模块")
    packed = read(job / "review_reading.json")
    _, _, packets = inventory(job)
    response = compile_hint_judgments(response, packets)
    findings = response["findings_by_module"]
    hints = {(p["module"], s["id"], h.get("precheck_ref")): h for p in packets
             for s in p["segments"] for h in s.get("precheck", [])}
    drafts, checked = {}, {}
    for module, entries in findings.items():
        if not isinstance(entries, list):
            raise ValueError("模块问题必须是列表")
        entries = copy.deepcopy(grouped_findings(entries))
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("issues"), list):
                for issue in entry["issues"]:
                    if isinstance(issue, dict) and issue.get("category") == "Terminology":
                        hint = hints.get((module, entry.get("id"), issue.get("precheck_ref")), {})
                        for field in ("term_source", "expected_targets", "term_spans"):
                            if field not in issue and field in hint:
                                issue[field] = copy.deepcopy(hint[field])
        draft = packed["output_templates"][module] | {"findings": entries}
        seen = set()
        for entry in entries:
            if (not isinstance(entry, dict) or set(entry) != {"id", "issues"}
                    or type(entry["id"]) is not int or entry["id"] not in draft["reviewed_ids"]
                    or entry["id"] in seen or not isinstance(entry["issues"], list) or not entry["issues"]
                    or any(not isinstance(i, dict) for i in entry["issues"])):
                raise ValueError("模块问题包含未知、重复或无效的分段")
            seen.add(entry["id"])
            checked[module, draft["chunk_id"], entry["id"]] = entry["issues"]
        drafts[module] = draft
    if check_decisions:
        validate_decisions(packets, response["decisions"], checked)
    return drafts, response


def submit_response(job: Path, worker_id: str) -> dict:
    from .review_task import bind_worker
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise ValueError("必须使用实际委派返回的 checker 身份")
    drafts, response = response_drafts(job)
    identity = job / "checker_identity.json"
    if identity.exists() and read(identity)["worker_id"] != worker_id:
        raise ValueError("不能重新绑定已经记录的 checker 身份")
    # Validate the entire response before touching drafts or decisions. Published
    # native receipts may never be rewritten by a resubmitted model response.
    paths, published = {}, False
    for module, draft in drafts.items():
        path = job / "worker_drafts" / module / f"chunk_{draft['chunk_id']:02d}.json"
        if identity.exists():
            draft["worker_receipt"] = read(identity)
        receipt = job / "chunks" / f"chunk_{draft['chunk_id']:02d}.{module}.receipt.json"
        published = published or receipt.exists()
        if receipt.exists() and (not path.exists() or read(path) != draft):
            raise ValueError("不能用新响应改写已发布的原生回执")
        paths[path] = draft
    decisions = {"decisions": response["decisions"]}
    decisions_path = job / "precheck_decisions.json"
    if published and decisions_path.exists() and read(decisions_path) != decisions:
        raise ValueError("不能改写已发布审校的预检判断")
    for path, draft in paths.items():
        atomic(path, draft)
    atomic(decisions_path, decisions)
    return bind_worker(job, job / "worker_drafts", worker_id)


def validate_response_binding(job: Path, directory: Path) -> None:
    if not (job / "review_execution.json").is_file() or not read(job / "review_execution.json").get("checker_view_sha256"):
        return
    if not (job / "checker_identity.json").is_file():
        raise ValueError("结构化响应尚未绑定实际 checker 身份")
    drafts, response = response_drafts(job)
    actual = {}
    for path in directory.rglob("*.json"):
        draft = read(path)
        module = draft["module"]
        if module in actual:
            raise ValueError("结构化响应存在重复模块草稿")
        actual[module] = draft
    if set(actual) != set(drafts) or any({k: v for k, v in actual[m].items() if k != "worker_receipt"}
            != {k: v for k, v in drafts[m].items() if k != "worker_receipt"} for m in drafts):
        raise ValueError("原生草稿与审校员的结构化响应不一致")
    if read(job / "precheck_decisions.json") != {"decisions": response["decisions"]}:
        raise ValueError("预检判断与审校员的结构化响应不一致")
