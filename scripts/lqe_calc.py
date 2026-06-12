"""
Score calculator. Reads state.json + errors.json, prints score and PASS/FAIL.
Usage: python lqe_calc.py --state jobs/<name>/state.json --errors jobs/<name>/errors.json [--threshold 98]
"""
import argparse
import json
from pathlib import Path
from collections import defaultdict

from lqe_engine import (
    read_json,
    WEIGHTS, SEVERITY_POINTS, SEVERITY_POINTS_MQM,
    apply_severity, normalize_category,
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--state",  required=True)
    p.add_argument("--errors", required=True)
    p.add_argument("--threshold", type=float, default=98)
    p.add_argument("--critical-gate", action="store_true", dest="critical_gate",
                   help="任一 Critical 错误直接 FAIL（MQM/ISO 5060/LISA 行业硬规则）；默认关，向后兼容")
    p.add_argument("--severity-scale", choices=["lisa", "mqm"], default="lisa",
                   help="严重度乘数档：lisa=0/1/5/10（默认）；mqm=0/1/5/25（指数间距）")
    p.add_argument("--locked-ids", default=None, dest="locked_ids",
                   help="逗号分隔的 locked seg id，其错误不计入 Critical 门")
    p.add_argument("--no-repeat-dedup", action="store_true", dest="no_repeat_dedup",
                   help="关闭 N4 重复错误去重（重复全额计分，旧行为）。默认：相同源译文段的同类同级错误仅首段计分，其余标 repeated（客户评分卡口径）")
    args = p.parse_args()

    sev_points = SEVERITY_POINTS_MQM if args.severity_scale == "mqm" else SEVERITY_POINTS
    locked = set()
    if args.locked_ids:
        locked = {int(x.strip()) for x in args.locked_ids.split(",") if x.strip()}

    state  = read_json(args.state)
    errors = read_json(args.errors)

    wordcount = state["wordcount"]
    if wordcount == 0:
        print("SCORE=100.00 STATUS=PASS CRITICAL=0")
        return

    cat_raw = defaultdict(float)
    dist    = defaultdict(int)
    total_errors = 0
    critical_count = 0
    # N4: 重复错误仅首次计分（key=源文+译文+类别+严重度，跨段判定；同段多错不互判重复）
    seg_map = {s["id"]: (s["source"].strip(), (s.get("corrected") or s["target"]).strip())
               for s in state.get("segments", [])}
    seen: dict = {}
    repeated_count = 0

    for entry in errors:
        if entry.get("id") in locked:
            continue
        sid = entry.get("id")
        for e in entry.get("errors", []):
            raw_cat = e.get("category", "Other")
            cat = normalize_category(raw_cat)
            sev = apply_severity(cat, str(e.get("severity", "Minor")))
            if not args.no_repeat_dedup and sid in seg_map:
                key = seg_map[sid] + (cat, sev)
                if seen.setdefault(key, sid) != sid:
                    e["repeated"] = True
                    repeated_count += 1
                    continue
            cat_raw[cat] += sev_points.get(sev, 0)
            dist[f"{raw_cat} [{sev}]"] += 1
            total_errors += 1
            if sev == "Critical":
                critical_count += 1

    if repeated_count:
        Path(args.errors).write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")

    total_weighted = sum(WEIGHTS.get(cat, 1.0) * raw for cat, raw in cat_raw.items())
    score  = max((1 - total_weighted / wordcount) * 100, 0)
    npt    = total_weighted * 1000 / wordcount  # 每千词惩罚分 (MQM RWC=1000)
    gate_fail = args.critical_gate and critical_count > 0
    status = "FAIL" if (gate_fail or score < args.threshold) else "PASS"

    gate_note = " (CRITICAL_GATE)" if gate_fail else ""
    print(f"SCORE={score:.2f} STATUS={status}{gate_note} ERRORS={total_errors} "
          f"WORDCOUNT={wordcount} CRITICAL={critical_count} REPEATED={repeated_count} NPT/1000={npt:.2f}")
    for k, v in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"  {v:>4}x  {k}")


if __name__ == "__main__":
    main()
