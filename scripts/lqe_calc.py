"""
Score calculator. Reads state.json + errors.json, prints score and PASS/FAIL.
Usage: python lqe_calc.py --state jobs/<name>/state.json --errors jobs/<name>/errors.json [--threshold 98]
"""
import argparse
import json
from pathlib import Path
from collections import defaultdict

from lqe_engine import WEIGHTS, SEVERITY_POINTS, apply_severity, normalize_category


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--state",  required=True)
    p.add_argument("--errors", required=True)
    p.add_argument("--threshold", type=float, default=98)
    args = p.parse_args()

    state  = json.loads(Path(args.state).read_text(encoding="utf-8"))
    errors = json.loads(Path(args.errors).read_text(encoding="utf-8"))

    wordcount = state["wordcount"]
    if wordcount == 0:
        print("SCORE=100.00 STATUS=PASS")
        return

    cat_raw = defaultdict(float)
    dist    = defaultdict(int)
    total_errors = 0

    for entry in errors:
        for e in entry.get("errors", []):
            raw_cat = e.get("category", "Other")
            cat = normalize_category(raw_cat)
            sev = apply_severity(cat, str(e.get("severity", "Minor")))
            cat_raw[cat] += SEVERITY_POINTS.get(sev, 0)
            dist[f"{raw_cat} [{sev}]"] += 1
            total_errors += 1

    total_weighted = sum(WEIGHTS.get(cat, 1.0) * raw for cat, raw in cat_raw.items())
    score  = max((1 - total_weighted / wordcount) * 100, 0)
    status = "PASS" if score >= args.threshold else "FAIL"

    print(f"SCORE={score:.2f} STATUS={status} ERRORS={total_errors} WORDCOUNT={wordcount}")
    for k, v in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"  {v:>4}x  {k}")


if __name__ == "__main__":
    main()
