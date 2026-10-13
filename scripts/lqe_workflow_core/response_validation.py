"""Preflight the original native publication contract without publishing any module."""
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid


class ResponseContractError(ValueError):
    pass


def validate_response(job: Path, response: dict, worker: str, runtime: Path) -> None:
    from .review_execution import validate_prepared_execution
    from .review_response import response_drafts
    from .store import atomic, read
    validate_prepared_execution(job, read(job / "review_execution.json"))
    errors = []
    try:
        drafts, _ = response_drafts(job, response)
    except ValueError as exc:
        errors.append(str(exc))
        try:
            # Read-only diagnostics collect native contract defects too. Formal
            # submit/publication always uses check_decisions=True.
            drafts, _ = response_drafts(job, response, check_decisions=False)
        except ValueError:
            raise ResponseContractError("\n".join(errors)) from exc
    with tempfile.TemporaryDirectory(prefix=".response-validation-", dir=job) as temporary:
        directory = Path(temporary)
        identity = {"worker_id": worker, "run_id": str(uuid.uuid4())}
        for module, draft in drafts.items():
            atomic(directory / f"{module}.json", draft | {"worker_receipt": identity})
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(job),
            str(directory), str(runtime)], capture_output=True, text=True, timeout=90)
        if result.returncode:
            detail = (result.stderr or result.stdout)[-2400:]
            if any(text in detail for text in ("invalid correction contract", "compact draft", "precheck",
                    "invalid fields", "not allowed", "needs_confirmation", "issue")):
                errors.append(detail)
            else:
                raise RuntimeError("原生预发布校验失败：" + detail)
    if errors:
        raise ResponseContractError("\n".join(errors))


def _native_preflight(job: Path, directory: Path, runtime: Path) -> None:
    sys.path.insert(0, str(runtime / "scripts"))
    import lqe_review as native
    with native.generation_lock(job / "chunks", exclusive=False):
        state, manifest, bases, packets = native._live_review_generation_unlocked(job)
        bases = {b["chunk_id"]: b for b in bases}
        packets = {(p["module"], p["chunk_id"]): p for p in packets}
        errors = []
        for path in sorted(directory.glob("*.json")):
            try:
                raw = native.load(path)
                packet = packets[raw["module"], raw["chunk_id"]]
                base = bases[raw["chunk_id"]]
                findings, receipt, migration = native._load_compact_draft(path, packet,
                    target_job=job, target_state=state)
                native._validate_full_entries_for_publication(job, state, manifest, base, raw["module"],
                    native._expand_findings(base, findings), packet, draft_path=path,
                    worker_receipt=receipt, migration_receipt=migration)
            except (ValueError, SystemExit) as exc:
                errors.append(str(exc))
        if errors:
            raise ValueError("\n".join(errors))


if __name__ == "__main__":
    _native_preflight(*map(Path, sys.argv[1:]))
