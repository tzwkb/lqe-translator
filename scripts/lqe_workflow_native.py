"""Native adapter for automatic acceptance. Existing CLI contracts stay authoritative."""
from __future__ import annotations

import copy
import re
import subprocess
import sys
from pathlib import Path

from lqe_engine import current_target, get_review_policy, require_current_job_runtime, required_modules
from lqe_paths import file_sha256, state_reference_paths
from lqe_scoring import resolve_scoring_policy, score_errors
from lqe_workflow_core.store import fingerprint, immutable, read

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent


def invoke(job: Path, script: str, *args) -> str:
    result = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                            cwd=job, text=True, capture_output=True, timeout=180)
    with (job / "native.log").open("a", encoding="utf-8") as log:
        log.write(f"{script} {' '.join(map(str, args))}\n{result.stdout}{result.stderr}\n")
    if result.returncode:
        raise ValueError(f"{script} failed: {(result.stderr or result.stdout)[-2500:]}")
    return result.stdout


def runtime_digest() -> str:
    files = []
    for directory in ("scripts", "references", "scorecard_profiles", "target_languages"):
        files.extend(p for p in (ROOT / directory).rglob("*")
                     if p.is_file() and p.suffix in {".py", ".sh", ".json", ".md"})
    files.append(ROOT / "SKILL.md")
    return fingerprint({str(p.relative_to(ROOT)): file_sha256(p) for p in sorted(files)})


def resource_files(state: dict) -> dict:
    files = {}
    for path in state_reference_paths(state).values():
        if not path.is_absolute():
            raise ValueError(f"任务资料必须使用绝对路径：{path}")
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    files[str(child.resolve())] = file_sha256(child)
        elif path.is_file():
            files[str(path.resolve())] = file_sha256(path)
        else:
            raise ValueError(f"任务资料缺失：{path}")
    return files


def executor_files(config: dict) -> dict:
    """Freeze the configured entry point and explicit local script/config arguments."""
    import shutil
    command = config.get("worker_command", [])
    if not isinstance(command, list) or any(not isinstance(arg, str) or not arg for arg in command):
        raise ValueError("worker_command 必须是非空字符串参数数组")
    files = {}
    for index, argument in enumerate(command):
        value = shutil.which(argument) if index == 0 else argument
        path = Path(value) if value else None
        if path and path.is_absolute() and path.is_file():
            files[str(path.resolve())] = file_sha256(path)
    return files


def initialize_state(path: Path, threshold: float) -> dict:
    state = read(path)
    require_current_job_runtime(state, "workflow-init")
    if get_review_policy(state)["mode"] != "full":
        raise ValueError("自动达标需要新建 --review-mode full 任务；不能改变已有降本任务的规则")
    if state.get("workflow_scope") or state.get("error_history") or state.get("iteration", 0):
        raise ValueError("请从新的原生 read 任务初始化，不能把历史审校冒充新基线")
    segments = state["segments"]
    if not segments or any(s.get("input_status") == "blocked" for s in segments):
        raise ValueError("输入为空或包含无法审校的内容")
    keys = [s.get("segment_key") for s in segments]
    if any(not isinstance(k, str) or not k for k in keys) or len(set(keys)) != len(keys):
        raise ValueError("输入缺少唯一的分段编号")
    if any(current_target(s) != s["target"] or s.get("corrected") for s in segments):
        raise ValueError("新基线不能携带未审校修改")
    threshold = max(threshold, resolve_scoring_policy(state)["threshold"])
    state["scoring_policy"] = resolve_scoring_policy(state, {"threshold": threshold, "critical_gate": True})
    state["threshold"] = threshold
    return refresh(state)


def refresh(state: dict) -> dict:
    """Recompute current text/context identities and the native score denominator."""
    from lqe_context import module_review_equivalence_key
    from lqe_io import _segment_revision
    xml_files = ({f["relative_path"]: f for f in read(Path(state["source_manifest_path"]))["files"]}
                 if state.get("input_format") == "sdlxliff" else None)
    for segment in state["segments"]:
        target = current_target(segment)
        if xml_files is None:
            # Tabular read counts the literal translation, including any inline markup.
            segment["target_plain"] = target
        elif target != segment["target"] or "target_plain" not in segment:
            from lqe_inputs.sdlxliff import (
                _fragment_root, _serialize_xliff2_mixed, serialize_mixed, XLIFF_NS, XLIFF2_NS,
            )
            file_info = xml_files[segment["source_ref"]["relative_path"]]
            ns = file_info["namespaces"]
            xliff2 = file_info.get("format") == "xliff2"
            element = _fragment_root(target, namespace_map=ns,
                                     default_namespace=XLIFF2_NS if xliff2 else XLIFF_NS)
            serializer = _serialize_xliff2_mixed if xliff2 else serialize_mixed
            segment["target_plain"] = serializer(element, ns).plain
        segment["segment_revision_digest"] = _segment_revision(segment, state)
        segment["module_review_equivalence_keys"] = {
            m: module_review_equivalence_key(segment, m, state["resolved_context_descriptors"])
            for m in required_modules(state)}
    if state["wordcount_basis"] == "source-chars":
        words = sum(len(re.findall(r"[一-鿿]|[A-Za-z0-9]+", s.get("source_plain", s["source"])))
                    for s in state["segments"])
    else:
        words = sum(len(s["target_plain"].split()) for s in state["segments"])
    state.update(wordcount=words, review_wordcount=words)
    state["review_wordcount_basis_digest"] = fingerprint({
        "wordcount": words, "review_wordcount": words, "blocked_ids": []})
    return state


def document(state: dict) -> list[dict]:
    from lqe_context_bundle import normalize_module_view
    registry = state["resolved_context_descriptors"]
    views = [normalize_module_view(state, m, registry) for m in required_modules(state)]
    before = max((v["neighbors"]["before"] for v in views), default=1)
    after = max((v["neighbors"]["after"] for v in views), default=1)
    result = copy.deepcopy(state["segments"])
    for i, s in enumerate(result):
        s["target"] = current_target(s)
        s["dependency_keys"] = [x["segment_key"] for x in result[max(0, i-before):i+after+1]]
    return result


def prepare(job: Path, canonical: dict, plan: dict, revision: int, request_id: str) -> dict:
    native = copy.deepcopy(canonical)
    native.update(job_id=job.name, iteration=revision, error_history=[], pending_recheck=False)
    pool = copy.deepcopy(native["segments"])
    selected = set(plan["selected_keys"])
    native["segments"] = [s for s in pool if s["segment_key"] in selected]
    native["workflow_scope"] = {"version": 1, "kind": plan["kind"], "revision": revision,
        "request_id": request_id, "plan_digest": fingerprint(plan), "selected_keys": plan["selected_keys"]}
    native["workflow_context_segments"] = pool
    refresh(native)
    # Refresh does not change text; the pool must bind identical selected records.
    by_id = {s["id"]: s for s in native["segments"]}
    native["workflow_context_segments"] = [copy.deepcopy(by_id.get(s["id"], s)) for s in pool]
    job.mkdir(parents=True, exist_ok=True)
    immutable(job / "state.json", native)
    invoke(job, "lqe_io.py", "pre-check", "--state", job / "state.json")
    invoke(job, "lqe_chunk.py", "split", "--state", job / "state.json", "--errors", job / "errors_precheck.json",
           "--outdir", job / "chunks")
    invoke(job, "lqe_review.py", "prepare", "--job", job)
    invoke(job, "lqe_review.py", "auto-publish", "--job", job)
    from lqe_workflow_core.review_execution import prepare_execution
    prepare_execution(job, ROOT)
    return native


def finish_review(job: Path, expected: dict) -> dict:
    if read(job / "state.json") != expected:
        raise ValueError("审校进程改变了受检文本或冻结策略")
    from lqe_workflow_core.review_execution import validate_execution
    validate_execution(job)
    for command in ("validate-checks", "merge-checks", "reconcile"):
        invoke(job, "lqe_chunk.py", command, "--job", job)
    invoke(job, "lqe_chunk.py", "merge", "--state", job / "state.json", "--errors", job / "errors_precheck.json",
           "--outdir", job / "chunks", "--out", job / "errors.json")
    invoke(job, "lqe_calc.py", "--state", job / "state.json", "--errors", job / "errors.json", "--json")
    errors = read(job / "errors.json")
    by_id = {s["id"]: s["segment_key"] for s in expected["segments"]}
    if len(errors) != len(by_id) or {r["id"] for r in errors} != set(by_id):
        raise ValueError("本轮问题结果没有覆盖全部计划句段")
    workers = []
    for path in sorted((job / "chunks").glob("*.receipt.json")):
        receipt = read(path)
        provenance = receipt.get("review_provenance") or {}
        if provenance.get("migration_receipt"):
            raise ValueError("自动工作流要求本轮真实检查，不能导入历史草稿")
        if provenance.get("worker_receipt"):
            workers.append(provenance["worker_receipt"])
    files = [p for p in job.glob("*.json") if p.name != "workflow_review.json"]
    files.extend(job / name for name in ("checker_task.md", "checker_view.md") if (job / name).is_file())
    files.extend(p for directory in ("chunks", "review_packets") for p in (job / directory).rglob("*.json"))
    receipt = {"findings": {by_id[r["id"]]: r["errors"] for r in errors}, "workers": workers,
               "bindings": {str(p.relative_to(job)): file_sha256(p) for p in files},
               "scoring": score_errors(expected, errors, resolve_scoring_policy(expected))["output"]}
    immutable(job / "workflow_review.json", receipt)
    return receipt


def verify_review(job: Path) -> dict:
    receipt = read(job / "workflow_review.json")
    for name, digest in receipt["bindings"].items():
        path = (job / name).resolve()
        if not path.is_relative_to(job.resolve()) or file_sha256(path) != digest:
            raise ValueError("历史审校证据已改变，不能复用")
    return receipt


def score_document(canonical: dict, coverage: dict) -> dict:
    errors = [{"id": s["id"], "errors": coverage[s["segment_key"]]["errors"], "corrected": None}
              for s in canonical["segments"]]
    return score_errors(canonical, errors, resolve_scoring_policy(canonical))["output"]


def apply_repairs(canonical: dict, repairs: list, allowed: set[str]) -> tuple[dict, list]:
    from lqe_corrections import validate_reference_target
    from lqe_target_form import load_target_form_policy
    if not isinstance(repairs, list):
        raise ValueError("修正必须是列表")
    updated = copy.deepcopy(canonical)
    segments = {s["segment_key"]: s for s in updated["segments"]}
    changes, seen = [], set()
    for repair in repairs:
        key = repair.get("segment_key")
        if key not in allowed or key not in segments or key in seen:
            raise ValueError("修正包含未知、无活跃问题或重复句段")
        seen.add(key)
        s = segments[key]
        if s.get("protected") or s.get("protected_reason") or s.get("input_status") == "blocked":
            raise ValueError("不能修改锁定或受保护的句段")
        if not isinstance(repair.get("reason"), str) or not repair["reason"].strip():
            raise ValueError("修正缺少依据")
        target = validate_reference_target(s, repair.get("target"), target_form_policy=load_target_form_policy(updated))
        changes.append({"segment_key": key, "before": current_target(s), "after": target,
                        "reason": repair["reason"], "status": "pending_verification"})
        s["current_target"] = target
        s["corrected"] = None
    return refresh(updated), changes


def deliver(job: Path, score: float) -> dict:
    """Build a separate final artifact job so the review receipt stays immutable."""
    output = job.parent.parent / "delivery"
    import shutil
    origin = {"review": job.name, "receipt_digest": file_sha256(job / "workflow_review.json")}
    if output.is_symlink() or (output.exists() and (
            not (output / "workflow_delivery_origin.json").is_file()
            or read(output / "workflow_delivery_origin.json") != origin)):
        raise ValueError("交付目录不属于本轮任务，不能覆盖")
    output.mkdir(exist_ok=True)
    immutable(output / "workflow_delivery_origin.json", origin)
    if any(p.is_symlink() for p in output.rglob("*")):
        raise ValueError("交付目录包含外部链接，不能覆盖")
    shutil.copytree(job, output, dirs_exist_ok=True)
    # Split manifests use job-relative paths; job_id/report labels remain explicit.
    invoke(output, "lqe_io.py", "write", "--state", output / "state.json", "--errors", output / "errors.json", "--score", score)
    invoke(output, "lqe_io.py", "verify-output", "--state", output / "state.json", "--errors", output / "errors.json")
    # Never overlay proposed edits from errors.json: export only the audited revision.
    invoke(output, "lqe_io.py", "export", "--state", output / "state.json")
    state = read(job / "state.json")
    source = Path(state["input_path"])
    artifacts = [output / f"{output.name}_lqe.xlsx"]
    if state.get("input_format") == "sdlxliff":
        artifacts.append(output / f"{output.name}_corrected.xlsx")
        if source.is_dir():
            artifacts.extend(output / f"{output.name}_corrected_xliff" / f["relative_path"]
                             for f in read(Path(state["source_manifest_path"]))["files"])
        else:
            artifacts.append(output / f"{output.name}_corrected{source.suffix.lower()}")
    else:
        suffix = source.suffix.lower() if source.suffix.lower() in {".csv", ".tsv"} else ".xlsx"
        artifacts.append(output / f"{output.name}_corrected{suffix}")
    return {str(p.relative_to(output)): file_sha256(p) for p in artifacts}
