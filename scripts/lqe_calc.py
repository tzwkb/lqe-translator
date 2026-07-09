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
    apply_severity, load_scorecard_profile, normalize_category_for_profile,
    scorecard_category_weight, scorecard_severity_points,
)


def _parse_locked_ids(text: str | None) -> set[int]:
    return {int(x.strip()) for x in (text or "").split(",") if x.strip()}


def _load_locked_file(path: str | None) -> set[int]:
    ids: set[int] = set()
    if not path:
        return ids
    data = read_json(path)
    if isinstance(data, dict):
        data = data.get("locked_ids") or data.get("segments") or []
    for item in data:
        if isinstance(item, int):
            ids.add(item)
        elif isinstance(item, str) and item.strip():
            ids.add(int(item.strip()))
        elif isinstance(item, dict):
            sid = item.get("id", item.get("seg_id", item.get("segment_id")))
            if sid is not None:
                ids.add(int(sid))
    return ids


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--state",  required=True)
    p.add_argument("--errors", required=True)
    p.add_argument("--threshold", type=float, default=98)
    p.add_argument("--critical-gate", action="store_true", dest="critical_gate",
                   help="任一 Critical 错误直接 FAIL（MQM/ISO 5060/LISA 行业硬规则）；默认关，向后兼容")
    p.add_argument("--severity-scale", choices=["lisa", "mqm"], default="lisa",
                   help="严重度乘数档：lisa=0/1/5/10（默认）；mqm=0/1/5/25（指数间距）")
    p.add_argument("--scorecard-profile", default="legacy", dest="scorecard_profile",
                   help="评分卡 profile id/目录/profile.json 路径；默认 legacy（当前原有评分标准）")
    p.add_argument("--locked-ids", default=None, dest="locked_ids",
                   help="逗号分隔的 locked seg id，其错误不计入 Critical 门")
    p.add_argument("--locked-file", default=None, dest="locked_file",
                   help="locked ids JSON 文件（如 {\"locked_ids\":[...]}），其错误不计分")
    p.add_argument("--no-repeat-dedup", action="store_true", dest="no_repeat_dedup",
                   help="关闭 N4 重复错误去重（重复全额计分，旧行为）。默认：相同源译文段的同类同级错误仅首段计分，其余标 repeated（客户评分卡口径）")
    p.add_argument("--json", action="store_true",
                   help="只输出结构化 JSON（score/status/…）供编排脚本解析，不打印人读行")
    args = p.parse_args()

    scorecard_profile = load_scorecard_profile(args.scorecard_profile)
    sev_points = scorecard_severity_points(scorecard_profile, args.severity_scale)

    state  = read_json(args.state)
    errors = read_json(args.errors)
    locked = _parse_locked_ids(args.locked_ids)
    locked.update(_load_locked_file(args.locked_file))
    locked.update(s["id"] for s in state.get("segments", []) if s.get("locked"))

    wordcount = state["wordcount"]
    if wordcount == 0:
        print(json.dumps({"score": 100.0, "status": "PASS", "errors": 0, "wordcount": 0,
                          "critical": 0, "repeated": 0, "npt": 0.0, "critical_gate": False})
              if args.json else "SCORE=100.00 STATUS=PASS CRITICAL=0")
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
            cat = normalize_category_for_profile(raw_cat, scorecard_profile)
            sev = apply_severity(cat, str(e.get("severity", "Minor")), scorecard_profile)
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

    total_weighted = sum(scorecard_category_weight(cat, scorecard_profile) * raw for cat, raw in cat_raw.items())
    score  = max((1 - total_weighted / wordcount) * 100, 0)
    npt    = total_weighted * 1000 / wordcount  # 每千词惩罚分 (MQM RWC=1000)
    gate_fail = args.critical_gate and critical_count > 0
    status = "FAIL" if (gate_fail or score < args.threshold) else "PASS"

    if args.json:
        print(json.dumps({"score": round(score, 2), "status": status, "errors": total_errors,
                          "wordcount": wordcount, "critical": critical_count,
                          "repeated": repeated_count, "npt": round(npt, 2),
                          "critical_gate": gate_fail}, ensure_ascii=False))
        return
    gate_note = " (CRITICAL_GATE)" if gate_fail else ""
    print(f"SCORE={score:.2f} STATUS={status}{gate_note} ERRORS={total_errors} "
          f"WORDCOUNT={wordcount} CRITICAL={critical_count} REPEATED={repeated_count} NPT/1000={npt:.2f}")
    for k, v in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"  {v:>4}x  {k}")


if __name__ == "__main__":
    main()
