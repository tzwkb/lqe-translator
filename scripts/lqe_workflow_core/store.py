"""Immutable workflow commits; a single execution lease protects each job."""
from __future__ import annotations

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
try:
    import msvcrt
except ImportError:  # POSIX
    msvcrt = None
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path

from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def atomic(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    if os.name != "nt":
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def immutable(path: Path, value) -> None:
    if path.exists():
        if read(path) != value:
            raise ValueError(f"不可覆盖已发布的工作流证据：{path.name}")
        return
    atomic(path, value)


@contextmanager
def execution_lease(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".workflow.lock").open("a+b") as stream:
        if fcntl is None and msvcrt is not None:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
        try:
            if fcntl is not None:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif msvcrt is not None:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                raise ValueError("当前平台不支持任务锁")
        except OSError as exc:
            raise ValueError("本任务已有执行进程，不能重复恢复") from exc
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(stream, fcntl.LOCK_UN)
            elif msvcrt is not None:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def load(root: Path) -> dict | None:
    events = sorted((root / "workflow_events").glob("*.json"))
    if not events:
        return None
    # Each event contains the complete committed projection. The pointer is
    # deliberately not authoritative: a crash may occur before it is updated.
    event = read(events[-1])
    state = event["state"]
    if event["digest"] != fingerprint(state):
        raise ValueError("工作流记录摘要不一致")
    if [p.name for p in events] != [f"{i:06d}.json" for i in range(1, state["sequence"] + 1)]:
        raise ValueError("工作流事件序号不连续")
    return state


def commit(root: Path, state: dict, reason: str) -> None:
    # A crash after publishing an event but before updating its projection must
    # not make recovery overwrite that already committed event.
    previous = load(root)
    state["sequence"] = (previous["sequence"] if previous else 0) + 1
    state["updated_at"] = utc_now()
    event = {"reason": reason, "state": state, "digest": fingerprint(state)}
    immutable(root / "workflow_events" / f"{state['sequence']:06d}.json", event)
    atomic(root / "workflow_snapshot.json", state)
