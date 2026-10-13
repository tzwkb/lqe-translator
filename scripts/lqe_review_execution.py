"""Publish automatic-stage drafts only after every precheck has been accounted for."""
from __future__ import annotations

import argparse
from pathlib import Path

from lqe_workflow_core.review_execution import validate_draft_decisions, validate_execution
from lqe_workflow_core.review_task import bind_worker, validate_bound_worker
from lqe_workflow_core.review_response import submit_response, validate_response_binding
from lqe_workflow_native import invoke


def publish(job: Path, directory: Path) -> None:
    validate_bound_worker(job, directory)
    validate_draft_decisions(job, directory)
    validate_response_binding(job, directory)
    invoke(job, "lqe_review.py", "publish-directory", "--job", job, "--input-dir", directory)
    validate_execution(job)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["publish", "bind-worker", "submit-response", "model-task"])
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--worker-id")
    args = parser.parse_args()
    job = args.job.resolve()
    directory = args.input_dir.resolve() if args.input_dir else job / "worker_drafts"
    if args.command == "model-task":
        from lqe_workflow_core.model_tasks import review_prompt
        print(review_prompt(job))
    elif args.command in {"bind-worker", "submit-response"}:
        if not args.worker_id:
            parser.error(f"{args.command} requires --worker-id from the actual delegation result")
        if args.command == "submit-response":
            submit_response(job, args.worker_id)
        else:
            bind_worker(job, directory, args.worker_id)
    else:
        publish(job, directory)
