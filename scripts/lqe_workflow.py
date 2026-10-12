"""Automatic LQE controller CLI; supports one persistent JSONL model-worker process."""
from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import threading
import subprocess
import sys
from pathlib import Path

import lqe_workflow_session as session
from lqe_workflow_core.store import execution_lease, load, read
from lqe_workflow_core.budget import remaining_seconds


def run(root: Path):
    """Keep orchestration/model setup alive; require fresh review workers per request."""
    config = read(root / "runtime_config.json")
    command = config.get("worker_command")
    if not isinstance(command, list) or not command or any(not isinstance(s, str) or not s for s in command):
        raise ValueError("运行配置缺少 worker_command 参数数组；也可以用 next/submit 接入现有 Agent")
    timeout = config.get("request_timeout_seconds", 1800)
    if type(timeout) not in (int, float) or not 1 <= timeout <= 86400:
        raise ValueError("request_timeout_seconds 必须在1到86400之间")
    request = session.next_request(root)
    if "request_id" not in request:
        return request
    with (root / "worker.log").open("a", encoding="utf-8") as log:
        worker = subprocess.Popen(command, cwd=root, text=True, encoding="utf-8", bufsize=1,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                  start_new_session=os.name != "nt")
        try:
            responses = queue.Queue()
            def read_responses():
                try:
                    for line in worker.stdout:
                        responses.put(line)
                finally:
                    responses.put(None)
            reader = threading.Thread(target=read_responses, daemon=True)
            reader.start()
            while "request_id" in request:
                remaining = remaining_seconds(load(root))
                if remaining is not None and remaining < 1:
                    return session.next_request(root)
                worker.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                worker.stdin.flush()
                try:
                    line = responses.get(timeout=min(timeout, remaining) if remaining is not None else timeout)
                except queue.Empty as exc:
                    remaining = remaining_seconds(load(root))
                    if remaining is not None and remaining < 1:
                        return session.next_request(root)
                    raise ValueError("模型响应超时；请求与已完成检查已保留，可恢复") from exc
                if line is None:
                    raise ValueError("模型执行进程提前退出；请求与已完成检查已保留，可恢复")
                response = json.loads(line)
                if not isinstance(response, dict):
                    raise ValueError("模型响应必须为JSON对象")
                result = session.submit(root, response)
                print(json.dumps(result, ensure_ascii=False), file=sys.stderr, flush=True)
                request = session.next_request(root)
            return request
        finally:
            try:
                worker.stdin.close()
            except BrokenPipeError:
                pass
            if os.name != "nt":
                try:
                    os.killpg(worker.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            elif worker.poll() is None:
                subprocess.run(["taskkill", "/PID", str(worker.pid), "/T", "/F"],
                               capture_output=True, timeout=10)
            if worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=5)
            if os.name != "nt":
                try:
                    os.killpg(worker.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if 'reader' in locals():
                reader.join(timeout=2)
                if not reader.is_alive():
                    worker.stdout.close()
            else:
                worker.stdout.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "next", "submit", "status", "verify", "run", "report"):
        command = sub.add_parser(name)
        command.add_argument("--workdir", type=Path, required=True)
        if name == "init":
            command.add_argument("--state", type=Path, required=True)
            command.add_argument("--runtime-config", type=Path, required=True)
            command.add_argument("--threshold", type=float, default=98)
            command.add_argument("--audit-rate", type=float, default=.1)
            command.add_argument("--max-cycles", type=int, default=6)
            command.add_argument("--max-seconds", type=int, default=5400)
            command.add_argument("--acceptance-mode", choices=["score_threshold", "strict"], default="score_threshold")
        if name == "submit":
            command.add_argument("--response", type=Path, required=True)
    args = parser.parse_args()
    root = args.workdir.resolve()
    try:
        with execution_lease(root):
            if args.command == "init":
                result = session.initialize(root, args.state.resolve(), args.runtime_config.resolve(),
                    threshold=args.threshold, audit_rate=args.audit_rate, max_cycles=args.max_cycles,
                    max_seconds=args.max_seconds, acceptance_mode=args.acceptance_mode)
            elif args.command == "next":
                result = session.next_request(root)
            elif args.command == "submit":
                result = session.submit(root, read(args.response))
            elif args.command == "run":
                result = run(root)
            elif args.command == "verify":
                result = session.verify(root)
            elif args.command == "report":
                from lqe_workflow_report import write_report
                result = write_report(root)
            else:
                state = load(root)
                if not state:
                    raise ValueError("工作流不存在")
                result = session.status(state)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f"[workflow] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
