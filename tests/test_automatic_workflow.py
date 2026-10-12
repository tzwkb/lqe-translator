"""Deterministic model fixtures exercising real native CLI/IO; NOT a model benchmark."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import lqe_workflow_session as flow
import lqe_workflow_native as native
from lqe_workflow_core.store import atomic, load, read
from lqe_workflow_core.issues import ingest, record_repair_attempt, repair_attempts, validate_verdicts
from lqe_workflow_core.control import check_acceptance, next_action
from tests.runtime_helpers import compact_draft


def call(script, *args):
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout
    return result


def setup_job(tmp_path, count=20, input_file=None, runtime_config=None, **policy):
    source = input_file or tmp_path / "input.csv"
    if input_file is None:
        source.write_text("Source,Target\n" + "\n".join(f"中文{i},Target{i}" for i in range(count)), encoding="utf-8")
    base = tmp_path / "base" / "state.json"
    args = ["read", "--input", source, "--source-lang", "zh", "--target-lang", "en",
            "--no-terminology", "--review-mode", "full", "--out", base]
    if source.suffix == ".csv":
        args += ["--source-col", "Source", "--target-col", "Target"]
    call("lqe_io.py", *args)
    config = tmp_path / "model.json"
    atomic(config, runtime_config or {"model": "TEST_FIXTURE_NOT_REAL_MODEL"})
    work = tmp_path / "workflow"
    work.mkdir()
    flow.initialize(work, base, config, **({"acceptance_mode": "strict", "max_cycles": None} | policy))
    return work


def major():
    return {"category": "Grammar", "severity": "Major", "comment": "Fixture: wrong grammatical construction.",
            "needs_confirmation": True, "edit": None}


def publish(request, errors=None, *, identity=None):
    job = Path(request["job"])
    if read(job / "review_execution.json").get("checker_view_sha256"):
        response = read(job / "review_response.template.json")
        response["findings_by_module"]["grammar"] = [{"id": sid, "issues": value}
            for sid, value in (errors or {}).items() if sid in response["reviewed_ids_by_module"]["grammar"]]
        atomic(job / "review_response.json", response)
        call("lqe_review_execution.py", "submit-response", "--job", job,
             "--worker-id", "fixture." + (identity or request["request_id"]))
        call("lqe_review_execution.py", "publish", "--job", job)
        return
    for path in sorted((job / "review_packets").glob("*/chunk_*.json")):
        packet = read(path)
        if not packet["requires_ai"]:
            continue
        findings = [{"id": sid, "issues": value} for sid, value in (errors or {}).items()
                    if sid in packet["reviewed_ids"]] if packet["module"] == "grammar" else []
        draft = compact_draft(packet, findings)
        prefix = identity or request["request_id"]
        draft["worker_receipt"] = {"worker_id": f"fixture.{prefix}.{packet['module']}.{packet['chunk_id']}",
                                   "run_id": f"run.{prefix}.{packet['module']}.{packet['chunk_id']}"}
        output = job / f"fixture-{packet['module']}-{packet['chunk_id']}.json"
        atomic(output, draft)
        call("lqe_review.py", "publish", "--job", job, "--chunk", packet["chunk_id"],
             "--module", packet["module"], "--input", output)


def submit_review(work, errors=None, **kwargs):
    request = flow.next_request(work)
    assert request["kind"] == "review"
    publish(request, errors, **kwargs)
    return flow.submit(work, {"request_id": request["request_id"]})


def repair(work, key, target):
    request = flow.next_request(work)
    assert request["kind"] == "repair"
    response = {"request_id": request["request_id"], "worker": {
        "worker_id": "repair." + request["request_id"], "run_id": "run." + request["request_id"]},
        "repairs": [{"segment_key": key, "target": target, "reason": "Fixture correction",
                     "addresses": [i["issue_ref"] for s in request["repair_targets"] if s["segment_key"] == key for i in s["issues"]]}]}
    flow.submit(work, response)
    return response


def reconcile(work, decision="resolved"):
    request = flow.next_request(work)
    assert request["kind"] == "reconcile"
    by_key = {s["segment_key"]: s for s in request["segments"]}
    verdicts = [{"issue_id": i["issue_id"], "decision": decision, "evidence": "Fixture re-evaluation of the sentence",
                 "rule_basis": "Fixture grammar rule", "target_quote": by_key[i["segment_key"]]["target"]}
                for i in request["issues"]]
    return flow.submit(work, {"request_id": request["request_id"], "worker": {
        "worker_id": "judge." + request["request_id"], "run_id": "judge-run." + request["request_id"]}, "verdicts": verdicts})


def test_baseline_100_requires_full_final_and_exact_native_delivery(tmp_path):
    work = setup_job(tmp_path, 3)
    result = submit_review(work)
    assert result["status"] == "running" and result["final_score"] is None
    final = flow.next_request(work)
    assert final["review_kind"] == "final" and len(final["selected_keys"]) == 3
    execution = read(Path(final["execution"]))
    assert execution["mode"] == "small_multi_module" and execution["worker_count"] == 1
    assert execution["reading_bytes"] < execution["original_worker_input_bytes"]
    publish(final)
    result = flow.submit(work, {"request_id": final["request_id"]})
    assert result["status"] == "delivered" and result["final_score"]["score"] == 100
    assert flow.verify(work)["status"] == "delivered"
    exported = next((work / "delivery").glob("*_corrected.csv"))
    assert "Target0" in exported.read_text(encoding="utf-8-sig")
    exported.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="交付文件"):
        flow.verify(work)


def test_threshold_mode_skips_noncritical_adjudication_then_stops_after_final(tmp_path):
    work = setup_job(tmp_path, acceptance_mode="score_threshold", max_cycles=3)
    submit_review(work, {0: [major()]})
    key = flow.next_request(work)["segments"][0]["segment_key"]
    repair(work, key, "Repaired target0")
    result = submit_review(work)
    assert result["next_action"] == "final"  # No separate reconcile request.
    assert load(work)["issues"][0]["status"] == "disputed"
    result = submit_review(work)
    assert result["status"] == "delivered" and result["rounds"] == 3
    assert result["next_action"] is None and result["issues"]["disputed"] == 1
    assert flow.next_request(work)["status"] == "delivered"
    assert flow.verify(work)["status"] == "delivered"


def test_persisted_time_budget_does_not_restart_after_interruption(tmp_path):
    from lqe_workflow_core.store import commit
    work = setup_job(tmp_path, acceptance_mode="score_threshold", max_seconds=20)
    state = load(work)
    state["started_at"] = "2020-01-01T00:00:00+00:00"
    commit(work, state, "fixture_interruption")
    result = flow.next_request(work)
    assert result["status"] == "stopped" and result["rounds"] == 0
    assert result["next_action"] is None and "总时间" in result["stop_reason"]


def test_insufficient_stages_stop_before_second_repair_or_unusable_review(tmp_path):
    work = setup_job(tmp_path, acceptance_mode="score_threshold", max_cycles=3)
    submit_review(work, {0: [major()]})
    key = flow.next_request(work)["segments"][0]["segment_key"]
    repair(work, key, "Repaired target0")
    result = submit_review(work, {0: [major()]})
    assert result["status"] == "stopped" and result["rounds"] == 2
    assert result["next_action"] is None and "剩余审校阶段不足" in result["stop_reason"]
    assert load(work)["revision"] == 1 and result["final_score"] is None
    assert flow.next_request(work)["status"] == "stopped"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process ownership check")
def test_whole_budget_terminates_owned_worker_without_model_calls(tmp_path):
    import os
    worker = tmp_path / "sleeping_fixture.py"
    worker.write_text("import os,time\nfrom pathlib import Path\nPath('fixture.pid').write_text(str(os.getpid()))\ntime.sleep(60)\n")
    work = setup_job(tmp_path, acceptance_mode="score_threshold", max_seconds=8,
        runtime_config={"model": "TEST_FIXTURE_NO_MODEL", "worker_command": [sys.executable, str(worker)],
                        "request_timeout_seconds": 60})
    result = subprocess.run([sys.executable, str(ROOT / "scripts/lqe_workflow.py"), "run", "--workdir", str(work)],
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "stopped"
    pid = int((work / "fixture.pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_repair_scoped_review_explicit_resolution_and_new_final_error_loop(tmp_path):
    work = setup_job(tmp_path)
    submit_review(work, {0: [major()]})
    key = read(work / "revisions/0000.json")["segments"][0]["segment_key"]
    response = repair(work, key, "Corrected0")
    assert flow.submit(work, response)["revision"] == 1  # idempotent response
    request = flow.next_request(work)
    assert 0 < len(request["selected_keys"]) < 20
    publish(request)
    flow.submit(work, {"request_id": request["request_id"]})
    assert load(work)["issues"][0]["status"] == "open"  # absence is not resolution
    reconcile(work)
    submit_review(work, {10: [major()]})  # a previously missed issue in the full final review
    assert flow.next_request(work)["kind"] == "repair"
    key10 = read(work / "revisions/0001.json")["segments"][10]["segment_key"]
    repair(work, key10, "Corrected10")
    submit_review(work)
    reconcile(work)
    assert submit_review(work)["status"] == "delivered"
    state = load(work)
    assert len(state["changes"]) == 2
    assert [r["kind"] for r in state["rounds"]] == ["baseline", "incremental", "final", "incremental", "final"]
    assert all(i["status"] == "resolved_verified" for i in state["issues"])
    assert all(c["status"] == "reviewed" for c in state["changes"])


def test_old_checker_identity_rejected_in_final(tmp_path):
    work = setup_job(tmp_path, 3)
    submit_review(work, identity="same")
    request = flow.next_request(work)
    publish(request, identity="same")
    with pytest.raises(ValueError, match="独立执行身份"):
        flow.submit(work, {"request_id": request["request_id"]})
    assert load(work)["final_score"] is None


def test_configuration_and_source_drift_block_resume(tmp_path):
    work = setup_job(tmp_path)
    request = flow.next_request(work)
    assert flow.next_request(work) == request
    config = read(work / "runtime_config.json")
    atomic(work / "runtime_config.json", {"model": "DIFFERENT"})
    with pytest.raises(ValueError, match="配置"):
        flow.next_request(work)
    atomic(work / "runtime_config.json", config)
    (tmp_path / "input.csv").write_text("Source,Target\nchanged,changed")
    with pytest.raises(ValueError, match="原稿"):
        flow.next_request(work)


def test_repair_protection_and_no_silent_policy_change(tmp_path):
    work = setup_job(tmp_path)
    doc = read(work / "revisions/0000.json")
    segment = doc["segments"][0]
    key = segment["segment_key"]
    segment["protected"] = True
    with pytest.raises(ValueError, match="锁定"):
        native.apply_repairs(doc, [{"segment_key": key, "target": "Other", "reason": "fixture"}], {key})
    segment["protected"] = False
    segment["target"] = "Hello {name}"
    with pytest.raises(ValueError, match="protected content"):
        native.apply_repairs(doc, [{"segment_key": key, "target": "Hello", "reason": "fixture"}], {key})
    from lqe_engine import build_review_policy
    base = read(tmp_path / "base/state.json")
    base["review_policy"] = build_review_policy("optimized")
    atomic(tmp_path / "base/state.json", base)
    with pytest.raises(ValueError, match="full"):
        native.initialize_state(tmp_path / "base/state.json", 98)


def test_issue_absence_false_positive_and_recurrence():
    segments = [{"segment_key": "a", "source": "源文", "target": "same text"}]
    issues = ingest([], segments, {"a": [major()]}, "r1", 0)
    verdict = {"issue_id": issues[0]["issue_id"], "decision": "resolved", "evidence": "checked",
               "rule_basis": "rule", "target_quote": "same text"}
    with pytest.raises(ValueError, match="原译文未变"):
        validate_verdicts(issues, segments, [verdict])
    disputed = ingest(issues, segments, {"a": []}, "r2", 0)
    assert disputed[0]["status"] == "disputed"
    verdict["decision"] = "dismissed"
    closed = ingest(issues, segments, {"a": []}, "r2", 0, validate_verdicts(issues, segments, [verdict]))
    assert closed[0]["status"] == "dismissed_with_evidence"
    assert ingest(closed, segments, {"a": [major()]}, "r3", 0)[0]["status"] == "reopened"


@pytest.mark.parametrize("decision", ["resolved", "dismissed"])
def test_repair_budget_restarts_only_after_evidenced_closure(decision):
    segments = [{"segment_key": "a", "source": "源文", "target": "old text"}]
    issues = ingest([], segments, {"a": [major()]}, "r1", 0)
    record_repair_attempt(issues[0])
    iid = issues[0]["issue_id"]
    current = [segments[0] | {"target": "revised text"}]
    disputed = ingest(issues, current, {"a": []}, "r2", 1)
    assert repair_attempts(disputed[0]) == 1  # Silence never resets a budget.
    verdict = {"issue_id": iid, "decision": decision, "evidence": "Independent source check",
               "rule_basis": "Frozen rule", "target_quote": "revised text"}
    closed = ingest(disputed, current, {"a": []}, "r3", 1,
                    validate_verdicts(disputed, current, [verdict]))
    reopened = ingest(closed, current, {"a": [major()]}, "r4", 1)[0]
    assert reopened["issue_id"] == iid and reopened["status"] == "reopened"
    assert reopened["attempts"] == 1 and repair_attempts(reopened) == 0
    record_repair_attempt(reopened)
    assert reopened["attempts"] == 2 and repair_attempts(reopened) == 1
    assert closed[0]["attempts"] == 1
    assert repair_attempts({"attempts": 3}) == 3  # Missing legacy data stays conservative.


def test_standalone_recurrence_preserves_lifetime_history_without_false_exhaustion(tmp_path):
    work = setup_job(tmp_path, 3)
    key = read(work / "revisions/0000.json")["segments"][0]["segment_key"]
    for episode in range(4):
        submit_review(work, {0: [major()]})
        repair(work, key, f"Corrected {episode}")
        submit_review(work)
        reconcile(work)
    result = submit_review(work)
    issue = load(work)["issues"][0]
    assert result["status"] == "delivered" and flow.verify(work)["status"] == "delivered"
    assert issue["attempts"] == 4 and repair_attempts(issue) == 1
    assert sum(event["to"] == "reopened" for event in issue["events"]) == 3


@pytest.mark.parametrize("decision", ["retained", "inconclusive"])
def test_repeated_dispute_keeps_each_independent_judgment(decision):
    segments = [{"segment_key": "a", "source": "源文", "target": "same text"}]
    issues = ingest([], segments, {"a": [major()]}, "r1", 0)
    iid = issues[0]["issue_id"]
    for review in ("r2", "r3"):
        verdict = {"issue_id": iid, "decision": decision, "evidence": f"Evidence from {review}",
                   "rule_basis": "Frozen contextual rule", "target_quote": "same text"}
        verdicts = validate_verdicts(issues, segments, [verdict])
        issues = ingest(issues, segments, {"a": []}, review, 0, verdicts)
        verdicts[iid]["evidence"] = "caller changed its response object"
    assert issues[0]["status"] == "disputed"
    events = issues[0]["events"]
    assert [event["review_id"] for event in events] == ["r1", "r2", "r3"]
    assert [event["evidence"]["evidence"] for event in events[1:]] == ["Evidence from r2", "Evidence from r3"]
    assert events[-1]["from"] == events[-1]["to"] == "disputed"


def test_partial_scope_cannot_export_complete_file(tmp_path):
    work = setup_job(tmp_path)
    submit_review(work, {0: [major()]})
    key = read(work / "revisions/0000.json")["segments"][0]["segment_key"]
    repair(work, key, "Corrected0")
    request = flow.next_request(work)
    with pytest.raises(ValueError, match="局部审校"):
        native.invoke(Path(request["job"]), "lqe_io.py", "export", "--state", request["state"])


def test_xliff_repair_preserves_tags_locked_text_and_source(tmp_path):
    from xml.etree import ElementTree as ET
    source = tmp_path / "game.xliff"
    source.write_text('''<?xml version="1.0"?>
<xliff xmlns="urn:oasis:names:tc:xliff:document:2.0" version="2.0" srcLang="zh" trgLang="en">
 <file id="game"><unit id="a"><segment id="one"><source>你好 <ph id="1"/></source>
 <target>Hello <ph id="1"/></target></segment></unit>
 <unit id="b" translate="no"><segment id="two"><source>锁定</source><target>Locked</target></segment></unit>
 </file></xliff>''', encoding="utf-8")
    original = source.read_bytes()
    work = setup_job(tmp_path, input_file=source)
    submit_review(work, {0: [major()]})
    doc = read(work / "revisions/0000.json")
    first, locked = doc["segments"]
    assert locked["protected"]
    repair(work, first["segment_key"], first["target"].replace("Hello", "Welcome"))
    submit_review(work)
    reconcile(work)
    assert submit_review(work)["status"] == "delivered"
    assert flow.verify(work)["status"] == "delivered"
    corrected = next((work / "delivery").glob("*_corrected.xliff"))
    xml = ET.fromstring(corrected.read_bytes())
    ns = {"x": "urn:oasis:names:tc:xliff:document:2.0"}
    targets = xml.findall(".//x:target", ns)
    assert targets[0].text == "Welcome " and targets[0][0].attrib["id"] == "1"
    assert targets[1].text == "Locked"
    assert source.read_bytes() == original


def test_interrupted_repair_replays_saved_response_without_duplicate_change(tmp_path, monkeypatch):
    work = setup_job(tmp_path)
    submit_review(work, {0: [major()]})
    key = read(work / "revisions/0000.json")["segments"][0]["segment_key"]
    commit = flow.commit
    def crash(root, state, reason):
        if reason == "repair_accepted":
            raise OSError("fixture interruption after revision write")
        return commit(root, state, reason)
    monkeypatch.setattr(flow, "commit", crash)
    with pytest.raises(OSError, match="fixture interruption"):
        repair(work, key, "Corrected0")
    assert load(work)["revision"] == 0
    monkeypatch.setattr(flow, "commit", commit)
    request = flow.next_request(work)
    assert request["kind"] == "review" and request["revision"] == 1
    assert len(load(work)["changes"]) == 1


def test_revision_and_review_receipt_tampering_fail_closed(tmp_path):
    work = setup_job(tmp_path, 3)
    submit_review(work)
    version = work / "revisions/0000.json"
    original = read(version)
    changed = copy.deepcopy(original)
    changed["segments"][0]["current_target"] = "not reviewed"
    atomic(version, changed)
    with pytest.raises(ValueError, match="译文版本"):
        flow.next_request(work)
    atomic(version, original)
    receipt = work / "rounds/0001/workflow_review.json"
    value = read(receipt)
    value["workers"] = []
    atomic(receipt, value)
    with pytest.raises(ValueError, match="凭据"):
        flow._validate_coverage(work, load(work), original)


def test_context_pool_retains_unselected_neighbors_and_is_bound(tmp_path):
    from lqe_context_bundle import build_context_bundle
    from lqe_split_contract import state_fingerprint
    work = setup_job(tmp_path, 5)
    doc = read(work / "revisions/0000.json")
    doc["module_context_views"] = {"accuracy": {"neighbors": {"before": 2, "after": 2, "include_target": True}}}
    segment = doc["segments"][2]
    plan = {"kind": "incremental", "selected_keys": [segment["segment_key"]]}
    scoped = native.prepare(tmp_path / "scope", doc, plan, 1, "test-scope")
    context = build_context_bundle(scoped, scoped["segments"][0], "accuracy")
    assert len(context["neighbors"]) == 4
    before = state_fingerprint(scoped)
    scoped["workflow_context_segments"][0]["current_target"] = "new neighbor target"
    assert state_fingerprint(scoped) != before


@pytest.mark.parametrize("field,value", [("kind", "incremental"), ("reviewed_revision", 0),
    ("score", 97.99), ("score", float("nan")), ("critical", 1), ("pending_changes", True),
    ("disputed", True), ("fresh_review", False), ("structure_ok", False), ("reviewed_keys", ["a"])])
def test_acceptance_requires_exact_current_full_independent_review(field, value):
    evidence = dict(kind="final", revision=1, reviewed_revision=1, keys=["a", "b"], reviewed_keys=["a", "b"],
        score=98, threshold=98, status="PASS", critical=0, pending_changes=False, disputed=False,
        structure_ok=True, fresh_review=True)
    evidence[field] = value
    with pytest.raises(ValueError):
        check_acceptance(**evidence)


def test_cli_persistent_worker_and_process_report(tmp_path):
    work = setup_job(tmp_path, 3, runtime_config={"model": "TEST_FIXTURE_NOT_REAL_MODEL",
        "worker_command": [sys.executable, str(ROOT / "tests/workflow_fixture_worker.py")],
        "request_timeout_seconds": 90})
    result = call("lqe_workflow.py", "run", "--workdir", work)
    assert json.loads(result.stdout)["status"] == "delivered"
    pids = [json.loads(line)["pid"] for line in (work / "fixture-pids.jsonl").read_text().splitlines()]
    assert len(pids) == 2 and len(set(pids)) == 1
    assert json.loads(call("lqe_workflow.py", "verify", "--workdir", work).stdout)["status"] == "delivered"
    report = json.loads(call("lqe_workflow.py", "report", "--workdir", work).stdout)
    import zipfile
    with zipfile.ZipFile(report["bundle"]) as archive:
        assert "process_report.xlsx" in archive.namelist()
        assert any(name.startswith("delivery/") for name in archive.namelist())
        assert "runtime_config.json" not in archive.namelist()


def test_native_wordcount_keeps_tabular_markup_and_xml_code_rules(tmp_path):
    from lqe_io import _segment_revision
    from tests.runtime_helpers import bind_empty_runtime_context
    state = bind_empty_runtime_context({"source_lang": "zh", "target_lang": "en", "wordcount_basis": "target-words",
        "input_format": "tabular", "segments": [{"id": 0, "source": "测试", "target": "Hello <sprite id=1> world"}]})
    native.refresh(state)
    assert state["wordcount"] == 4  # Native tabular read counts the literal target.
    manifest = tmp_path / "source_manifest.json"
    atomic(manifest, {"files": [{"relative_path": "a.sdlxliff", "namespaces": {
        "": "urn:oasis:names:tc:xliff:document:1.2"}}]})
    segment = state["segments"][0]
    segment.update(source_ref={"relative_path": "a.sdlxliff"},
        target='Hello <bpt id="1">&lt;b&gt;two code words</bpt> world', target_plain="Hello  world",
        current_target='Welcome <bpt id="1">&lt;b&gt;two code words</bpt> world')
    state.update(input_format="sdlxliff", source_manifest_path=str(manifest))
    native.refresh(state)
    assert state["wordcount"] == 2 and segment["target_plain"] == "Welcome  world"


def test_native_initialization_never_lowers_project_threshold(tmp_path):
    work = setup_job(tmp_path, 3)
    base = read(tmp_path / "base/state.json")
    base["scoring_policy"]["threshold"] = 99
    atomic(tmp_path / "base/state.json", base)
    assert native.initialize_state(tmp_path / "base/state.json", 98)["scoring_policy"]["threshold"] == 99


def test_interrupted_delivery_replays_without_deleting_unrelated_files(tmp_path, monkeypatch):
    work = setup_job(tmp_path, 3)
    submit_review(work)
    request = flow.next_request(work)
    publish(request)
    invoke = native.invoke
    def crash(job, script, *args):
        if job.name == "delivery" and args[0] == "export":
            raise OSError("fixture export interrupted")
        return invoke(job, script, *args)
    monkeypatch.setattr(native, "invoke", crash)
    with pytest.raises(OSError, match="interrupted"):
        flow.submit(work, {"request_id": request["request_id"]})
    note = work / "delivery/user-note.txt"
    note.write_text("Keep this note", encoding="utf-8")
    monkeypatch.setattr(native, "invoke", invoke)
    assert flow.next_request(work)["status"] == "delivered"
    assert note.read_text() == "Keep this note"
    assert "user-note.txt" not in load(work)["artifacts"]
    assert flow.verify(work)["status"] == "delivered"


def test_timeout_preserves_pending_request_and_executor_drift_blocks_resume(tmp_path):
    driver = tmp_path / "silent-worker.py"
    driver.write_text("import sys,time\nsys.stdin.readline()\ntime.sleep(60)\n")
    work = setup_job(tmp_path, 3, runtime_config={"model": "TEST_FIXTURE_NOT_REAL_MODEL",
        "worker_command": [sys.executable, str(driver)], "request_timeout_seconds": 1})
    result = subprocess.run([sys.executable, str(ROOT / "scripts/lqe_workflow.py"), "run", "--workdir", str(work)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and "超时" in result.stderr
    request = load(work)["pending"]
    assert flow.next_request(work)["request_id"] == request["request_id"]
    driver.write_text("raise RuntimeError('changed worker')\n")
    with pytest.raises(ValueError, match="执行器"):
        flow.next_request(work)


def test_journal_recovers_after_projection_failure_and_rejects_parallel_execution(tmp_path, monkeypatch):
    from lqe_workflow_core import store
    state = {"sequence": 0, "value": "first"}
    store.commit(tmp_path, state, "first")
    original = store.atomic
    def crash(path, value):
        if path.name == "workflow_snapshot.json":
            raise OSError("fixture projection failure")
        return original(path, value)
    monkeypatch.setattr(store, "atomic", crash)
    with pytest.raises(OSError):
        store.commit(tmp_path, {"value": "second"}, "second")
    assert store.load(tmp_path)["value"] == "second"
    with store.execution_lease(tmp_path):
        with pytest.raises(ValueError, match="已有执行进程"):
            with store.execution_lease(tmp_path):
                pass
