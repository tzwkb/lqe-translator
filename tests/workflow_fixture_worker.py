"""TEST ONLY: deterministic clean check responses, not a model or performance benchmark."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_automatic_workflow import publish

for line in sys.stdin:
    request = json.loads(line)
    with Path("fixture-pids.jsonl").open("a") as stream:
        stream.write(json.dumps({"pid": os.getpid(), "kind": request["kind"]}) + "\n")
    if request["kind"] != "review":
        raise ValueError("This fixture only produces clean reviews")
    publish(request)
    print(json.dumps({"request_id": request["request_id"]}), flush=True)
