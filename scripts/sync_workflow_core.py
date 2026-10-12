"""Publish/check a pinned copy of the shared core in the integration service."""
import argparse
import hashlib
import json
from pathlib import Path

from lqe_workflow_core import __version__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration-root", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent / "lqe_workflow_core"
    app = args.integration_root.resolve() / "backend/lqe/app"
    if not (app / "services/workflow_v2.py").is_file():
        raise SystemExit("Target is not the LQE integration service")
    destination = app / "_vendor/lqe_workflow_core"
    files = {p.name: p.read_bytes() for p in sorted(source.glob("*.py"))}
    manifest = {"source": "lqe-translator/scripts/lqe_workflow_core", "version": __version__,
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    files["SOURCE.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    if args.check:
        stale = [name for name, data in files.items()
                 if not (destination / name).is_file() or (destination / name).read_bytes() != data]
        extra = {p.name for p in destination.glob("*.py")} - files.keys()
        if stale or extra:
            raise SystemExit(f"Shared core differs: changed={stale}, extra={sorted(extra)}")
        print("Shared core source and integration copy match")
        return
    destination.mkdir(parents=True, exist_ok=True)
    for old in destination.glob("*.py"):
        if old.name not in files:
            raise SystemExit("Refusing to delete an unknown vendored file; inspect the version change")
    for name, data in files.items():
        temporary = destination / (name + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(destination / name)
    print(f"Published shared core {__version__} to {destination}")


if __name__ == "__main__":
    main()
