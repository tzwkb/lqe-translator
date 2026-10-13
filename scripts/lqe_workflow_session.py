"""Resumable standalone controller. Model work is an explicit request/response boundary."""
from __future__ import annotations

import copy
import time
from datetime import datetime
from pathlib import Path

import lqe_workflow_native as native
from lqe_workflow_core.control import actionable_issues, blocking_disputes, check_acceptance, has_progress, next_action, policy, review_budget_exhausted, state_signature
from lqe_workflow_core.budget import remaining_seconds
from lqe_workflow_core.review_audit import repair_spec, validate_repair_coverage
from lqe_workflow_core.issues import (
    CLOSED, ingest, reconciliation_needed, record_repair_attempt, repair_attempts, summary, validate_verdicts,
)
from lqe_workflow_core.planning import context_digest, make_plan
from lqe_workflow_core.store import commit, fingerprint, immutable, load, read, utc_now


def initialize(root: Path, source: Path, config: Path, *, threshold=98.0, audit_rate=1.0, max_cycles=None,
               max_seconds=None, acceptance_mode="strict"):
    if acceptance_mode != "strict":
        raise ValueError("独立LQE新任务使用质量优先的strict策略，不能放宽历史争议门槛")
    if load(root) is not None or any(p.name != ".workflow.lock" for p in root.iterdir()):
        raise ValueError("工作流目录必须为空；恢复已有任务请使用 next 或 run")
    rules = policy(threshold=threshold, audit_rate=audit_rate, max_cycles=max_cycles,
                   max_seconds=max_seconds, acceptance_mode=acceptance_mode)
    canonical = native.initialize_state(source, threshold)
    rules["threshold"] = canonical["scoring_policy"]["threshold"]
    for path in native.state_reference_paths(canonical).values():
        if path.is_dir() and root.resolve().is_relative_to(path.resolve()):
            raise ValueError("工作流输出目录不能位于原稿或项目资料目录内")
    runtime_config = read(config)
    if (not isinstance(runtime_config, dict) or not isinstance(runtime_config.get("model"), str)
            or not runtime_config["model"].strip()):
        raise ValueError("运行配置必须记录 model；执行命令可通过 worker_command 配置")
    immutable(root / "runtime_config.json", runtime_config)
    immutable(root / "revisions/0000.json", canonical)
    assets = native.resource_files(canonical)
    bindings = {"files": assets, "runtime": native.runtime_digest(), "config": fingerprint(runtime_config),
                "executor_files": native.executor_files(runtime_config)}
    state = {"version": 1, "sequence": 0, "status": "running", "policy": rules, "bindings": bindings,
        "resources": fingerprint(bindings), "revision": 0, "revision_digest": fingerprint(canonical),
        "cycle": 0, "rounds": [], "issues": [],
        "changes": [], "coverage": {}, "workers": [], "seen_states": [], "no_progress": 0,
        "next_kind": "baseline", "pending": None, "accepted": {}, "started_at": utc_now(),
        "working_score": None, "final_score": None, "stop_reason": None}
    commit(root, state, "initialized")
    return status(state)


def canonical(root, state):
    document = read(root / "revisions" / f"{state['revision']:04d}.json")
    if fingerprint(document) != state["revision_digest"]:
        raise ValueError("已提交的译文版本发生变化")
    return document


def check_bindings(root: Path, state: dict):
    if native.runtime_digest() != state["bindings"]["runtime"]:
        raise ValueError("运行库已经变化；不能把旧证据用于新版本")
    config = read(root / "runtime_config.json")
    if fingerprint(config) != state["bindings"]["config"]:
        raise ValueError("模型运行配置已经变化")
    if native.executor_files(config) != state["bindings"]["executor_files"]:
        raise ValueError("模型执行器或其脚本已经变化")
    if native.resource_files(canonical(root, state)) != state["bindings"]["files"]:
        raise ValueError("原稿或项目资料已经变化；请建立新任务")


def _job(root, state):
    return root / "rounds" / f"{len(state['rounds']):04d}"


def _pending(state, kind, body):
    request_id = f"{len(state['rounds']):04d}-{kind}-r{state['revision']:04d}"
    state["pending"] = {"request_id": request_id, "kind": kind, "revision": state["revision"],
                        "created_at": utc_now(), **body}


def next_request(root: Path) -> dict:
    state = load(root)
    if not state:
        raise ValueError("请先初始化工作流")
    check_bindings(root, state)
    if state["status"] != "running":
        return status(state)
    remaining = remaining_seconds(state)
    if remaining is not None and remaining < 1:
        _stop(state, "已到任务总时间上限，停止自动调用；尚未达标")
        commit(root, state, "time_budget")
        return status(state)
    if state["pending"]:
        response = root / "responses" / f"{state['pending']['request_id']}.json"
        if response.exists():
            # A validated response was durably recorded before publishing its effects.
            submit(root, read(response))
            return next_request(root)
    if state["pending"] is None:
        kind = state["next_kind"]
        state["cycle"] += kind == "incremental"
        doc = canonical(root, state)
        plan = make_plan(native.document(doc), state["coverage"], actionable_issues(state["issues"], state["policy"]), kind=kind,
                         cycle=state["cycle"], resource_digest=state["resources"], audit_rate=state["policy"]["audit_rate"])
        if state["policy"].get("review_strategy") is not None:
            plan["review_strategy"] = state["policy"]["review_strategy"]
        state["rounds"].append({"kind": kind, "revision": state["revision"], "plan": plan,
                               "started_at": utc_now(), "status": "preparing", "metrics": {}})
        _pending(state, "review", {"review_kind": kind, "selected_keys": plan["selected_keys"],
            "requires_fresh_workers": True, "instructions": str(ROOT_INSTRUCTIONS),
            "worker_id_prefix": f"review-{len(state['rounds']):04d}"})
        commit(root, state, "review_planned")
    request = state["pending"]
    job = _job(root, state)
    if request["kind"] == "review" and state["rounds"][-1]["status"] == "preparing":
        started = time.monotonic()
        expected = native.prepare(job, canonical(root, state), state["rounds"][-1]["plan"],
                                  state["revision"], request["request_id"])
        immutable(job / "expected_state.json", expected)
        state["rounds"][-1]["expected_state_digest"] = fingerprint(expected)
        request.update(job=str(job), state=str(job / "state.json"),
                       manifest=str(job / "review_packets/manifest.json"),
                       execution=str(job / "review_execution.json"))
        state["rounds"][-1]["status"] = "reviewing"
        state["rounds"][-1]["metrics"]["prepare_seconds"] = round(time.monotonic() - started, 3)
        commit(root, state, "review_prepared")
    immutable(root / "requests" / f"{request['request_id']}.json", request)
    return copy.deepcopy(request)


ROOT_INSTRUCTIONS = native.ROOT / "references/automatic_workflow.md"


def _worker(response, existing):
    worker = response.get("worker")
    if not isinstance(worker, dict) or set(worker) != {"worker_id", "run_id"}:
        raise ValueError("模型结果必须记录 worker_id 与 run_id")
    if any(not isinstance(v, str) or not v.strip() for v in worker.values()):
        raise ValueError("模型执行身份为空")
    if any(worker["worker_id"] == w["worker_id"] or worker["run_id"] == w["run_id"] for w in existing):
        raise ValueError("新的判断必须使用独立执行身份，不能复用旧判断")
    return worker


def _validate_coverage(root, state, doc):
    receipts = {}
    segments = native.document(doc)
    for i, s in enumerate(segments):
        old = state["coverage"].get(s["segment_key"])
        if not old or (old["source"], old["target"]) != (s["source"], s["target"]):
            raise ValueError("当前版本还有未复审修改")
        if old["context_digest"] != context_digest(segments, i, state["resources"]):
            raise ValueError("上下文改变后仍在使用旧结果")
        rid = old["review_id"]
        if not isinstance(rid, str) or not rid.isdigit() or len(rid) != 4:
            raise ValueError("无效的历史审校位置")
        if rid not in receipts:
            receipts[rid] = native.verify_review(root / "rounds" / rid)
        if native.file_sha256(root / "rounds" / rid / "workflow_review.json") != old["receipt_digest"]:
            raise ValueError("历史审校凭据与已提交记录不一致")
        if receipts[rid]["findings"].get(s["segment_key"]) != old["errors"]:
            raise ValueError("复用的问题与原始审校证据不同")


def _stop(state, reason):
    state.update(status="stopped", stop_reason=reason, pending=None)


def _accept_review(root, state, verdicts):
    job = _job(root, state)
    receipt = native.verify_review(job)
    doc = canonical(root, state)
    segments = native.document(doc)
    row = state["rounds"][-1]
    row["receipt_digest"] = native.file_sha256(job / "workflow_review.json")
    previous = state["issues"]
    state["issues"] = ingest(previous, segments, receipt["findings"], job.name, state["revision"], verdicts)
    for segment in segments:
        key = segment["segment_key"]
        if key in receipt["findings"]:
            state["coverage"][key] = {"source": segment["source"], "target": segment["target"],
                "errors": receipt["findings"][key], "review_id": job.name, "receipt_digest": row["receipt_digest"],
                "context_digest": row["plan"]["contexts"][key], "last_sample_cycle": state["cycle"]}
    for change in state["changes"]:
        if change["status"] == "pending_verification" and change["segment_key"] in receipt["findings"]:
            current = next(s for s in segments if s["segment_key"] == change["segment_key"])
            if current["target"] == change["after"]:
                change["status"] = "reviewed"
                change["verification_review"] = job.name
    _validate_coverage(root, state, doc)
    score = native.score_document(doc, state["coverage"])
    state["working_score"] = score
    state["no_progress"] = 0 if has_progress(previous, state["issues"]) else state["no_progress"] + 1
    row.update(status="completed", completed_at=utc_now(), score=score)
    disputed = bool(blocking_disputes(state["issues"], state["policy"]))
    passed = (score["status"] == "PASS" and score["score"] >= state["policy"]["threshold"]
              and not score["critical"] and structure_ok(doc))
    action = next_action(row["kind"], working_ready=passed, final_pass=passed, disputed=disputed)
    if action == "deliver":
        check_acceptance(kind=row["kind"], revision=state["revision"], reviewed_revision=row["revision"],
            keys=[s["segment_key"] for s in segments], reviewed_keys=row["plan"]["selected_keys"],
            score=score["score"], threshold=state["policy"]["threshold"], status=score["status"], critical=score["critical"],
            pending_changes=any(c["status"] == "pending_verification" for c in state["changes"]),
            disputed=disputed, structure_ok=structure_ok(doc), fresh_review=True)
        state["artifacts"] = native.deliver(job, score["score"])
        state.update(status="delivered", final_score=score, pending=None, final_round=job.name)
        return
    remaining = remaining_seconds(state)
    if remaining is not None and remaining < 1:
        return _stop(state, "已到任务总时间上限，停止自动调用；尚未达标")
    signature = state_signature(segments, state["issues"], row["kind"])
    maximum = state["policy"]["max_cycles"]
    if maximum is not None and len(state["rounds"]) >= maximum:
        return _stop(state, "已到执行上限，未通过全量终审")
    if review_budget_exhausted(action, completed=len(state["rounds"]), maximum=maximum):
        return _stop(state, "剩余审校阶段不足以完成修正复查和全量终审，停止自动调用；尚未达标")
    if signature in state["seen_states"]:
        return _stop(state, "译文和问题状态重复，未达标")
    state["seen_states"].append(signature)
    if action == "final":
        state.update(next_kind="final", pending=None)
        return
    if state["no_progress"] >= state["policy"]["max_no_progress_cycles"]:
        return _stop(state, "连续循环没有验证出有效进展，未达标")
    active = actionable_issues(state["issues"], state["policy"])
    if any(repair_attempts(i) >= state["policy"]["max_repair_attempts_per_issue"] for i in active):
        return _stop(state, "问题的自动修正策略已耗尽，未达标")
    active_keys = {i["segment_key"] for i in active}
    repairs = repair_spec(segments, read(job / "errors.json"), active)
    _pending(state, "repair", {"issues": active, "segments": [s for s in segments if s["segment_key"] in active_keys], "job": str(job),
        "repair_targets": repairs,
        "instructions": str(ROOT_INSTRUCTIONS), "response_schema": {
            "worker": {"worker_id": "unique", "run_id": "unique"},
            "repairs": [{"segment_key": "active issue key", "target": "candidate text", "reason": "evidence", "addresses": ["all issue_refs for this segment"]}]}})


def structure_ok(doc):
    from collections import Counter
    import re
    from lqe_corrections import _VARIABLE_RE
    def tokens(text):
        return Counter(_VARIABLE_RE.findall(text) + re.findall(r"</?[A-Za-z][^>]*>", text))
    return all(tokens(s["source"]) == tokens(native.current_target(s))
               for s in doc["segments"] if not s.get("protected"))


def submit(root: Path, response: dict) -> dict:
    state = load(root)
    if not state:
        raise ValueError("请先初始化工作流")
    check_bindings(root, state)
    rid = response.get("request_id")
    if not isinstance(rid, str):
        raise ValueError("响应缺少 request_id")
    digest = fingerprint(response)
    if rid in state["accepted"]:
        if state["accepted"][rid] != digest:
            raise ValueError("已处理请求不能提交不同响应")
        return status(state)
    pending = state["pending"]
    if state["status"] != "running" or not pending or rid != pending["request_id"]:
        raise ValueError("响应不属于当前请求")
    job = _job(root, state)
    started = time.monotonic()
    if pending["kind"] == "review":
        if state["rounds"][-1]["status"] != "reviewing":
            raise ValueError("审校准备未完成，请先执行 next")
        expected = read(job / "expected_state.json")
        if fingerprint(expected) != state["rounds"][-1]["expected_state_digest"]:
            raise ValueError("本轮受检版本记录发生变化")
        receipt = native.finish_review(job, expected)
        # The process orchestrator may persist; every check generation must be fresh.
        for worker in receipt["workers"]:
            _worker({"worker": worker}, state["workers"])
        immutable(root / "responses" / f"{rid}.json", response)
        state["workers"].extend(receipt["workers"])
        missing = reconciliation_needed(state["issues"], receipt["findings"],
            acceptance_mode=state["policy"].get("acceptance_mode", "strict"))
        if missing:
            missing_keys = {i["segment_key"] for i in missing}
            _pending(state, "reconcile", {"issues": missing,
                "segments": [s for s in native.document(canonical(root, state)) if s["segment_key"] in missing_keys],
                "job": str(job), "instructions": str(ROOT_INSTRUCTIONS), "response_schema": {
                    "worker": {"worker_id": "unique", "run_id": "unique"},
                    "verdicts": [{"issue_id": "requested id", "decision": "resolved|dismissed|retained|inconclusive",
                                  "evidence": "specific evidence", "rule_basis": "rule", "target_quote": "exact current quote"}]}})
        else:
            _accept_review(root, state, {})
    elif pending["kind"] == "reconcile":
        worker = _worker(response, state["workers"])
        verdicts = validate_verdicts(pending["issues"], pending["segments"], response.get("verdicts"))
        immutable(root / "responses" / f"{rid}.json", response)
        state["workers"].append(worker)
        _accept_review(root, state, verdicts)
    else:
        worker = _worker(response, state["workers"])
        allowed = {i["segment_key"] for i in actionable_issues(state["issues"], state["policy"])}
        if response.get("repairs"):
            validate_repair_coverage(pending["repair_targets"], response["repairs"], key_field="segment_key")
        updated, changes = native.apply_repairs(canonical(root, state), response.get("repairs"), allowed)
        immutable(root / "responses" / f"{rid}.json", response)
        state["workers"].append(worker)
        if not changes:
            _stop(state, "没有可验证的新修改，未达标")
        else:
            state["revision"] += 1
            for change in changes:
                change.update(revision=state["revision"], issue_ids=[])
                for issue in state["issues"]:
                    if issue["segment_key"] == change["segment_key"] and issue["status"] not in CLOSED:
                        record_repair_attempt(issue)
                        change["issue_ids"].append(issue["issue_id"])
            immutable(root / "revisions" / f"{state['revision']:04d}.json", updated)
            state["revision_digest"] = fingerprint(updated)
            state["changes"].extend(changes)
            state.update(next_kind="incremental", pending=None, working_score=None)
    check_bindings(root, state)
    immutable(root / "responses" / f"{rid}.json", response)
    state["accepted"][rid] = digest
    state["rounds"][-1]["metrics"][pending["kind"] + "_validation_seconds"] = round(time.monotonic() - started, 3)
    state["rounds"][-1]["metrics"][pending["kind"] + "_completed_at"] = utc_now()
    state["rounds"][-1]["metrics"][pending["kind"] + "_elapsed_seconds"] = round(
        (datetime.fromisoformat(utc_now()) - datetime.fromisoformat(pending["created_at"])).total_seconds(), 3)
    commit(root, state, f"{pending['kind']}_accepted")
    return status(state)


def verify(root: Path) -> dict:
    state = load(root)
    if not state or state["status"] != "delivered":
        raise ValueError("工作流未完成最终验收")
    check_bindings(root, state)
    _validate_coverage(root, state, canonical(root, state))
    if any(c["review_id"] != state["final_round"] for c in state["coverage"].values()):
        raise ValueError("最终验收不能复用中间结果")
    for name, digest in state["artifacts"].items():
        path = (root / "delivery" / name).resolve()
        if not path.is_relative_to((root / "delivery").resolve()) or native.file_sha256(path) != digest:
            raise ValueError("交付文件与最终验收版本不一致")
    native.invoke(root / "delivery", "lqe_io.py", "verify-output", "--state", root / "delivery/state.json",
                  "--errors", root / "delivery/errors.json")
    return status(state)


def status(state):
    return {"status": state["status"], "revision": state["revision"], "rounds": len(state["rounds"]),
            "working_score": state["working_score"], "final_score": state["final_score"],
            "issues": summary(state["issues"], state["status"] == "delivered"),
            "next_action": (state["pending"]["kind"] if state["pending"] else state["next_kind"])
                           if state["status"] == "running" else None,
            "stop_reason": state["stop_reason"]}
