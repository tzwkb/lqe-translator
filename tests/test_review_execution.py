"""Offline contract regressions; no model calls and no quality/speed benchmark."""
import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lqe_workflow_core.review_audit import pending_history, repair_spec, validate_decisions, validate_repair_coverage
from lqe_workflow_core.review_execution import _small_inputs, expand_collection, factor_collection


def packets():
    return [{"module": "terminology", "chunk_id": 0, "segments": [{"id": 0,
        "source": "打开目标", "target": "Open target", "precheck": [{"precheck_ref": "precheck:0:term",
            "category": "Terminology", "severity": "Major", "term_source": "目标", "expected_targets": ["Targets"]}]}]}]


def test_json_transport_rejects_explanations_and_non_object_responses():
    from lqe_workflow_core.model_tasks import json_response
    assert json_response('```json\n{"findings": []}\n```') == {"findings": []}
    for value in ('[]', '{"findings": []}\nI am done.', 'No errors found.'):
        with pytest.raises(ValueError):
            json_response(value)


def hint_response(*, verdict="confirmed_error", finding=None):
    from tests.test_automatic_workflow import major
    p = packets()
    p[0]["segments"][0]["precheck"][0]["term_spans"] = {
        "source": [{"start": 2, "end": 4, "text": "目标"}], "target": []}
    issue = major() | {"category": "Terminology", "resolution_status": "reference_allowed"}
    d = decision(decision=verdict, applicability="same_sense", reason="Fixture: same applicable term sense.")
    d["finding"] = finding if finding is not None else (issue if verdict == "confirmed_error" else None)
    return {"version": 2, "findings_by_module": {"terminology": []}, "decisions": [d]}, p


def test_hint_judgment_is_compiled_once_with_frozen_facts_and_original_semantics():
    from lqe_workflow_core.review_response import compile_hint_judgments
    response, p = hint_response()
    response["decisions"][0]["finding"]["severity"] = "Minor"
    before = copy.deepcopy(response)
    expanded = compile_hint_judgments(response, p)
    issue = expanded["findings_by_module"]["terminology"][0]["issues"][0]
    assert response == before
    hint = p[0]["segments"][0]["precheck"][0]
    assert issue == response["decisions"][0]["finding"] | {k: hint[k] for k in
        ("precheck_ref", "term_source", "expected_targets", "term_spans")}
    assert expanded["decisions"][0] == {k: v for k, v in response["decisions"][0].items() if k != "finding"} | {"decision": "retained"}
    validate_decisions(p, expanded["decisions"], {("terminology", 0, 0): [issue]})
    legacy = response | {"version": 1}
    assert compile_hint_judgments(legacy, p) == legacy


def test_correct_or_inapplicable_hint_does_not_generate_a_reported_error():
    from lqe_workflow_core.review_response import compile_hint_judgments
    response, p = hint_response(verdict="no_error")
    expanded = compile_hint_judgments(response, p)
    assert expanded["findings_by_module"] == {"terminology": []}
    assert expanded["decisions"][0]["decision"] == "dismissed"
    validate_decisions(p, expanded["decisions"], {})


@pytest.mark.parametrize("bad", ["missing_finding", "finding_on_no_error", "duplicate", "metadata", "unknown", "inline_edit"])
def test_hint_transport_rejects_ambiguous_judgments_or_model_owned_offsets(bad):
    from lqe_workflow_core.review_response import compile_hint_judgments
    response, p = hint_response()
    d = response["decisions"][0]
    if bad == "missing_finding":
        d.pop("finding")
    elif bad == "finding_on_no_error":
        d["decision"] = "no_error"
    elif bad == "duplicate":
        response["findings_by_module"]["terminology"] = [{"id": 0, "issues": [d["finding"] | {"precheck_ref": d["precheck_ref"]}]}]
    elif bad == "metadata":
        d["finding"]["term_spans"] = {"source": [], "target": []}
    elif bad == "unknown":
        d["precheck_ref"] = "unknown"
    else:
        d["finding"]["edit"] = {"from": "target", "to": "Targets"}
    with pytest.raises(ValueError):
        compile_hint_judgments(response, p)


def test_flat_issue_transport_is_losslessly_grouped(response_job):
    from tests.test_automatic_workflow import major
    from lqe_workflow_core.review_response import submit_response, validate_response_binding
    from lqe_workflow_core.store import atomic, read
    response = read(response_job / 'review_response.template.json')
    issues = [major(), major() | {'comment': 'Second concrete finding'}]
    response['findings_by_module']['grammar'] = [dict(id=0, **issue) for issue in issues]
    atomic(response_job / 'review_response.json', response)
    raw = (response_job / 'review_response.json').read_bytes()
    submit_response(response_job, 'actual-session')
    draft = read(response_job / 'worker_drafts/grammar/chunk_00.json')
    assert draft['findings'] == [{'id': 0, 'issues': issues}]
    assert (response_job / 'review_response.json').read_bytes() == raw
    validate_response_binding(response_job, response_job / 'worker_drafts')


def test_model_task_preserves_full_bound_view_and_template(response_job):
    from lqe_workflow_core.model_tasks import review_prompt
    from lqe_workflow_core.store import read
    import json
    prompt = review_prompt(response_job)
    assert (response_job / 'checker_view.md').read_text() in prompt
    assert json.dumps(read(response_job / 'review_response.template.json'), ensure_ascii=False, indent=2) in prompt
    (response_job / 'checker_view.md').write_text('changed')
    with pytest.raises(ValueError):
        review_prompt(response_job)


def test_native_preflight_publishes_nothing_and_rejects_invalid_edit(response_job):
    from lqe_workflow_core.response_validation import ResponseContractError, validate_response
    from lqe_workflow_core.store import read
    from tests.test_automatic_workflow import major
    runtime = Path(__file__).resolve().parents[1]
    response = read(response_job / 'review_response.template.json')
    before = {p.name: p.read_bytes() for p in (response_job / 'chunks').glob('*receipt.json')}
    state_before = (response_job / 'state.json').read_bytes()
    validate_response(response_job, response, 'offline.actual-worker', runtime)
    assert {p.name: p.read_bytes() for p in (response_job / 'chunks').glob('*receipt.json')} == before
    assert (response_job / 'state.json').read_bytes() == state_before
    assert not (response_job / 'checker_identity.json').exists()
    issue = major() | {'needs_confirmation': False,
        'edit': {'from': 'Target', 'to': 'Candidate', 'evidence': 'invalid free text'}}
    response['findings_by_module']['grammar'] = [{'id': 0, 'issues': [issue]}]
    with pytest.raises(ResponseContractError):
        validate_response(response_job, response, 'offline.actual-worker', runtime)
    assert not (response_job / 'worker_drafts').exists()


def decision(**overrides):
    return {"module": "terminology", "chunk_id": 0, "id": 0, "precheck_ref": "precheck:0:term",
        "decision": "dismissed", "applicability": "grammar_variant", "target_quote": "Open target",
        "reason": "This action selects one target; the glossary plural is not an exact UI label requirement."} | overrides


def test_lossless_pack_preserves_module_fields_and_each_modules_order():
    records = {"accuracy": {"segments": [{"id": 2, "source": "Second", "target": "Two", "context": None},
                                           {"id": 1, "source": "First", "target": "One", "context": {"speaker": "A"}}]},
               "terminology": {"segments": [{"id": 1, "source": "First", "target": "One", "context": {},
                                               "term_hits": [{"source": "First", "target": "One"}]}]}}
    before = copy.deepcopy(records)
    packed = factor_collection(records, "segments", lambda r: r["id"])
    assert expand_collection(packed) == before and records == before
    assert "term_hits" not in expand_collection(packed)["accuracy"]["segments"][1]


def test_silent_precheck_omission_is_rejected():
    with pytest.raises(ValueError, match="全部说明"):
        validate_decisions(packets(), [], {})
    validate_decisions(packets(), [decision()], {})


def test_an_inapplicable_term_cannot_be_retained_as_confirmed_error():
    findings = {("terminology", 0, 0): [{"precheck_ref": "precheck:0:term"}]}
    with pytest.raises(ValueError, match="不能当作已确认错误"):
        validate_decisions(packets(), [decision(decision="retained", applicability="different_sense")], findings)
    validate_decisions(packets(), [decision(decision="retained", applicability="same_sense",
        reason="The applicable project rule requires this exact label in this UI context.")], findings)
    validate_decisions(packets(), [decision(decision="retained", applicability="confirmed",
        reason="The reviewer confirms the same term sense and the required UI label.")], findings)
    with pytest.raises(ValueError, match="不能当作已确认错误"):
        validate_decisions(packets(), [decision(decision="retained", applicability="insufficient_context")], findings)


def test_one_compound_issue_covers_nested_confirmed_hints_without_duplicate_penalty():
    import copy
    short = {'precheck_ref': 'short', 'category': 'Terminology', 'term_source': '金刚',
        'expected_targets': ['Vajra'], 'term_spans': {'source': [{'start': 0, 'end': 2, 'text': '金刚'}], 'target': []}}
    full = {'precheck_ref': 'full', 'category': 'Terminology', 'term_source': '金刚橛',
        'expected_targets': ['Vajra Phurba'], 'term_spans': {'source': [{'start': 0, 'end': 3, 'text': '金刚橛'}], 'target': []}}
    p = [{'module': 'terminology', 'chunk_id': 0, 'segments': [{'id': 0, 'source': '金刚橛',
        'target': 'Phurba', 'precheck': [short, full]}]}]
    ds = [decision(precheck_ref=ref, decision='retained', applicability='same_sense', target_quote='Phurba')
          for ref in ('short', 'full')]
    findings = {('terminology', 0, 0): [{'precheck_ref': 'full', 'category': 'Terminology'}]}
    validate_decisions(p, ds, findings)
    assert len(findings['terminology', 0, 0]) == 1
    other = copy.deepcopy(p)
    other[0]['segments'][0]['precheck'][0]['expected_targets'] = ['Unrelated target']
    with pytest.raises(ValueError, match='不一致'):
        validate_decisions(other, ds, findings)


def test_json_transport_allows_one_fenced_response_with_prose_but_not_ambiguous_blocks():
    from lqe_workflow_core.model_tasks import json_response
    assert json_response('I will provide the final review.\n```json\n{"findings": []}\n```\n') == {"findings": []}
    for raw in ('```json\n{}\n```\n```json\n{}\n```',
                '{}\n```json\n{}\n```', '```json\n{}\n```\n[]',
                'First {} then {}', '```json\n[]\n```'):
        with pytest.raises(ValueError):
            json_response(raw)


@pytest.mark.parametrize("bad", [decision(target_quote="Unrelated text"), decision(reason=""), decision(precheck_ref="unknown")])
def test_precheck_requires_bound_quote_reason_and_identity(bad):
    with pytest.raises(ValueError):
        validate_decisions(packets(), [bad], {})


def test_disposition_must_match_the_actual_native_findings():
    with pytest.raises(ValueError, match="不一致"):
        validate_decisions(packets(), [decision()], {("terminology", 0, 0): [{"precheck_ref": "precheck:0:term"}]})


def test_one_candidate_must_address_all_penalized_findings_and_segments():
    segments = [{"id": n, "segment_key": str(n), "source": "Source", "target": "Original"} for n in (0, 1)]
    errors = [{"id": 0, "errors": [{"category": "Grammar", "severity": "Minor"},
                                   {"category": "Mistranslation", "severity": "Major"},
                                   {"category": "Unidiomatic", "severity": "Neutral"}]},
              {"id": 1, "errors": [{"category": "Grammar", "severity": "Minor"}]}]
    spec = repair_spec(segments, errors)
    candidates = [{"id": s["id"], "addresses": [i["issue_ref"] for i in s["issues"]]} for s in spec]
    validate_repair_coverage(spec, candidates)
    assert len(candidates[0]["addresses"]) == 2
    with pytest.raises(ValueError, match="遗漏"):
        validate_repair_coverage(spec, candidates[:1])
    candidates[0]["addresses"].pop()
    with pytest.raises(ValueError, match="全部扣分"):
        validate_repair_coverage(spec, candidates)


def test_resolved_critical_history_is_not_repaired_again():
    history = [{"issue_id": "c", "severity": "Critical"}, {"issue_id": "m", "severity": "Major"}]
    assert pending_history(history, [{"issue_id": "c", "decision": "resolved"},
                                     {"issue_id": "m", "decision": "retained"}]) == []
    assert pending_history(history, [{"issue_id": "c", "decision": "inconclusive"}]) == history[:1]


@pytest.mark.parametrize("count,extensions,expected", [(31, {}, "text_budget"), (2, {"strict": {}}, "specialized_context")])
def test_large_or_specialized_jobs_keep_module_evidence_boundaries(tmp_path, count, extensions, expected):
    rows = [{"id": n, "source": "Source", "target": "Target", "context_projection": {"extensions": extensions}}
            for n in range(count)]
    active = [{"module": m, "requires_ai": True, "segments": rows}
              for m in ("accuracy", "grammar", "naturalness", "terminology")]
    packed, reason = _small_inputs(tmp_path, tmp_path, {}, active)
    assert packed is None and reason == expected


def test_automatic_publisher_validates_before_native_and_keeps_full_final_gate(tmp_path):
    from tests.test_automatic_workflow import setup_job, call
    from lqe_workflow_core.store import atomic, read
    import lqe_workflow_session as flow
    work = setup_job(tmp_path, 3, acceptance_mode="score_threshold", max_cycles=3)
    for number in (1, 2):
        request = flow.next_request(work)
        assert request["review_kind"] == ("baseline" if number == 1 else "final")
        job = Path(request["job"])
        assert (job / "checker_task.md").is_file()
        directory = job / "worker_drafts"
        response = read(job / "review_response.template.json")
        atomic(job / "review_response.json", response)
        call("lqe_review_execution.py", "submit-response", "--job", job,
             "--worker-id", f"offline.matrix.{number}")
        before = {p: read(p) for p in directory.rglob("*.json")}
        call("lqe_review_execution.py", "bind-worker", "--job", job,
             "--worker-id", f"offline.matrix.{number}")
        identity = read(job / "checker_identity.json")
        assert identity["worker_id"] == f"offline.matrix.{number}"
        for path, original in before.items():
            assert read(path) == original | {"worker_receipt": identity}
        call("lqe_review_execution.py", "bind-worker", "--job", job,
             "--worker-id", f"offline.matrix.{number}")
        assert read(job / "checker_identity.json") == identity
        assert read(job / "review_response.json") == response
        call("lqe_review_execution.py", "publish", "--job", job, "--input-dir", directory)
        result = flow.submit(work, {"request_id": request["request_id"]})
        assert result["status"] == ("running" if number == 1 else "delivered")
    assert flow.verify(work)["status"] == "delivered"
    baseline_view = next((work / "rounds").glob("*/checker_view.md"))
    baseline_view.write_text("changed after completed review", encoding="utf-8")
    with pytest.raises(ValueError, match="历史审校证据"):
        flow.verify(work)


@pytest.fixture
def response_job(tmp_path):
    from tests.test_automatic_workflow import setup_job
    import lqe_workflow_session as flow
    work = setup_job(tmp_path, 3, acceptance_mode="score_threshold", max_cycles=3)
    return Path(flow.next_request(work)["job"])


@pytest.mark.parametrize("corruption", ["wrong_assignment", "missing_reviewed_id", "missing_module", "unknown_segment"])
def test_invalid_response_does_not_write_any_worker_draft(response_job, corruption):
    from lqe_workflow_core.review_response import submit_response
    from lqe_workflow_core.store import atomic, read
    job = response_job
    response = read(job / "review_response.template.json")
    if corruption == "wrong_assignment":
        response["assignment_id"] = "previous-stage"
    elif corruption == "missing_reviewed_id":
        response["reviewed_ids_by_module"]["accuracy"].pop()
    elif corruption == "missing_module":
        response["findings_by_module"].pop("accuracy")
    else:
        response["findings_by_module"]["accuracy"] = [{"id": 999, "issues": [{"comment": "Unknown segment"}]}]
    atomic(job / "review_response.json", response)
    with pytest.raises(ValueError):
        submit_response(job, "actual-checker")
    assert not list((job / "worker_drafts").rglob("*.json"))
    assert not (job / "checker_identity.json").exists()


def test_response_preserves_findings_and_rejects_later_draft_or_input_tampering(response_job):
    from tests.test_automatic_workflow import major
    from lqe_workflow_core.review_response import submit_response, validate_response_binding
    from lqe_workflow_core.store import atomic, read
    job = response_job
    response = read(job / "review_response.template.json")
    response["findings_by_module"]["grammar"] = [{"id": 0, "issues": [major()]}]
    atomic(job / "review_response.json", response)
    identity = submit_response(job, "actual-checker")
    draft_path = job / "worker_drafts/grammar/chunk_00.json"
    draft = read(draft_path)
    assert draft["findings"] == response["findings_by_module"]["grammar"]
    assert draft["worker_receipt"] == identity
    validate_response_binding(job, job / "worker_drafts")
    atomic(draft_path, draft | {"findings": []})
    with pytest.raises(ValueError, match="不一致"):
        validate_response_binding(job, job / "worker_drafts")
    submit_response(job, "actual-checker")  # An unpublished formatting retry is allowed.
    (job / "checker_view.md").write_text("modified materials", encoding="utf-8")
    with pytest.raises(ValueError, match="冻结.*发生变化"):
        submit_response(job, "actual-checker")


def test_resubmission_cannot_overwrite_published_native_judgments(response_job):
    from tests.test_automatic_workflow import call, major
    from lqe_workflow_core.review_response import submit_response
    from lqe_workflow_core.store import atomic, read
    job = response_job
    response = read(job / "review_response.template.json")
    atomic(job / "review_response.json", response)
    submit_response(job, "actual-checker")
    call("lqe_review_execution.py", "publish", "--job", job)
    draft_path = job / "worker_drafts/grammar/chunk_00.json"
    original = draft_path.read_bytes()
    response["findings_by_module"]["grammar"] = [{"id": 0, "issues": [major()]}]
    atomic(job / "review_response.json", response)
    with pytest.raises(ValueError, match="已发布"):
        submit_response(job, "actual-checker")
    assert draft_path.read_bytes() == original


def test_readable_view_keeps_full_resources_terms_and_unknown_semantic_fields(response_job):
    from lqe_workflow_core.review_view import render_view, semantic_view
    from lqe_workflow_core.store import read
    packed = read(response_job / "review_reading.json")
    packed["resources"][0]["text"] += "\nA complete style rule with a custom spelling."
    first = next(iter(packed["packets"]["rows"].values()))
    first["common"]["future_semantic_constraint"] = {"protect_phrase": "UNCHANGED"}
    view = semantic_view(packed)
    rendered = render_view(packed)
    assert all(r["text"] in rendered for r in packed["resources"])
    assert "future_semantic_constraint" in rendered and "UNCHANGED" in rendered
    assert "module_review_equivalence_keys" not in rendered
    assert len(view["segments"]) == 3
    assert all(v["packet_rules"]["reviewed_ids"] == [0, 1, 2] for v in view["modules"].values())


def test_nested_review_evidence_is_not_hidden_by_reader_line_truncation(response_job):
    from lqe_workflow_core.review_view import render_view
    from lqe_workflow_core.store import read
    packed = read(response_job / "review_reading.json")
    first = next(iter(packed["packets"]["rows"].values()))
    first["common"]["additional_evidence"] = [{"fact": "Term fact " + str(n)} for n in range(200)]
    rendered = render_view(packed)
    assert "Term fact 199" in rendered
    assert max(map(len, rendered.splitlines())) < 2000


def test_readable_view_retains_full_candidate_entries_and_module_scope(response_job):
    from lqe_workflow_core.review_view import render_view, semantic_view
    from lqe_workflow_core.store import read
    packed = read(response_job / "review_reading.json")
    entry = {"source": "名词", "target": "Term", "notes": "A particular sense only", "custom": "retained"}
    packed["term_candidates"] = {"applies_to_modules": ["terminology"], "entries": [entry]}
    view = semantic_view(packed)
    assert view["term_candidates"] == packed["term_candidates"]
    rendered = render_view(packed)
    assert "A particular sense only" in rendered and '"custom": "retained"' in rendered


def test_resume_preserves_old_frozen_execution_task(response_job):
    import hashlib
    from lqe_workflow_core.review_execution import prepare_execution
    from lqe_workflow_core.review_task import checker_task
    from lqe_workflow_core.store import atomic, read
    job = response_job
    execution = read(job / "review_execution.json")
    for field in ("checker_view_sha256", "checker_view_bytes", "response_template_sha256"):
        execution.pop(field)
    execution["version"] = 1
    original_task = checker_task()
    (job / "checker_task.md").write_text(original_task, encoding="utf-8")
    execution["checker_task_sha256"] = hashlib.sha256(original_task.encode()).hexdigest()
    atomic(job / "review_execution.json", execution)
    assert prepare_execution(job, job / "unused-runtime") == execution
    assert (job / "checker_task.md").read_text(encoding="utf-8") == original_task


@pytest.mark.parametrize("status", ["reference_allowed", "human_choice_required", "conflict"])
def test_supplied_terminology_confirmation_choices_pass_the_native_contract(status):
    from lqe_chunk import _module_issue_problem
    from lqe_corrections import _canonical_issue
    from lqe_engine import build_review_policy
    from lqe_workflow_core.review_task import FINDING_CONTRACT
    assert status in FINDING_CONTRACT["terminology_confirmation"]["choices"]
    issue = {"category": "Terminology", "severity": "Major", "comment": "Applicable project evidence.",
        "needs_confirmation": True, "edit": None, "resolution_status": status,
        "term_source": "目标", "expected_targets": ["Target"],
        "term_spans": {"source": [{"start": 0, "end": 2, "text": "目标"}], "target": []}}
    policy = build_review_policy("full", "test")
    normalized = _canonical_issue(issue, label="fixture", review_policy=policy)
    state = {"job_runtime_contract_version": 2, "review_policy": policy}
    assert _module_issue_problem(state, "terminology", normalized) is None
    normalized.pop("resolution_status")
    assert "must declare whether" in _module_issue_problem(state, "terminology", normalized)


def test_worker_binding_rejects_an_external_draft_directory(tmp_path):
    from lqe_workflow_core.review_task import bind_worker
    with pytest.raises(ValueError, match="当前任务内"):
        bind_worker(tmp_path / "job", tmp_path / "external", "actual-returned-worker")
