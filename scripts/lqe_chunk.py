#!/usr/bin/env python3
"""Split a job for subagent fan-out, then merge subagent outputs back.

split: state.json + errors.json(pre-check) + terms.json -> chunks/chunk_NN.json
       each segment carries {id, source, target, precheck[], term_hits[]}
merge: chunks/chunk_NN.out.json (list of {id, errors, corrected}) -> errors.json
       validates every state id is covered; missing ids fall back to pre-check.
"""
import argparse
import json
import sys
from pathlib import Path


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _term_hits(src_txt, titems, cap=15):
    """Longest-match, coverage-filtered term hits. Keep a TB term only if it has
    an occurrence NOT fully inside a longer term's occurrence — so 优优 inside
    绒光优优 is dropped (the longer term already covers it), but a separate
    standalone 优优 elsewhere in the segment is still kept."""
    occ = []  # (start, end, src, th, status)
    for ts, th, st in titems:               # titems is sorted longest-first
        i = src_txt.find(ts)
        while i >= 0:
            occ.append((i, i + len(ts), ts, th, st))
            i = src_txt.find(ts, i + 1)
    occ.sort(key=lambda o: -(o[1] - o[0]))  # longest span first
    accepted = []                           # spans claimed by longer terms
    kept = {}                               # src -> hit (one entry per term)
    for s, e, ts, th, st in occ:
        if any(a <= s and e <= b for a, b in accepted):
            continue                        # covered by a longer term -> drop
        accepted.append((s, e))
        if ts not in kept:
            h = {"src": ts, "th": th}
            if st:
                h["status"] = st
            kept[ts] = h
    return list(kept.values())[:cap]


def cmd_split(a):
    state = load(a.state)
    pre = load(a.errors)
    terms = load(a.terms)
    segs = state["segments"]
    pre_by_id = {e["id"]: e.get("errors", []) for e in pre}
    titems = [(t["source"], t.get("target", ""), t.get("status", ""))
              for t in terms if len(t.get("source", "")) >= 2]
    titems.sort(key=lambda x: -len(x[0]))

    # dedup identical (source,target): evaluate each unique pair once;
    # merge broadcasts the verdict back to every id in the group.
    seg_by_id = {s["id"]: s for s in segs}
    groups = {}
    for seg in segs:
        groups.setdefault((seg.get("source", ""), seg.get("target", "")), []).append(seg["id"])
    reps, dedup_map, seen = [], {}, set()
    for seg in segs:
        key = (seg.get("source", ""), seg.get("target", ""))
        if key in seen:
            continue
        seen.add(key)
        rep = min(groups[key])
        reps.append(rep)
        dedup_map[rep] = groups[key]

    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "dedup_map.json").write_text(
        json.dumps({str(k): v for k, v in dedup_map.items()}, ensure_ascii=False),
        encoding="utf-8")

    size = a.size
    nchunks = (len(reps) + size - 1) // size
    for ci in range(nchunks):
        rows = []
        for rid in reps[ci * size:(ci + 1) * size]:
            seg = seg_by_id[rid]
            src_txt = seg.get("source", "")
            rows.append({
                "id": rid,
                "source": src_txt,
                "target": seg.get("target", ""),
                "precheck": pre_by_id.get(rid, []),
                "term_hits": _term_hits(src_txt, titems),
            })
        (outdir / f"chunk_{ci:02d}.json").write_text(
            json.dumps({"chunk_id": ci, "segments": rows},
                       ensure_ascii=False, indent=1), encoding="utf-8")
    dup = len(segs) - len(reps)
    print(f"[split] {len(segs)} segments -> {len(reps)} unique (deduped {dup}) "
          f"-> {nchunks} chunks (size {size}) in {outdir}")


def cmd_merge(a):
    state = load(a.state)
    pre = load(a.errors)
    ids = [s["id"] for s in state["segments"]]
    pre_by_id = {e["id"]: e.get("errors", []) for e in pre}
    merged = {}
    files = sorted(Path(a.outdir).glob("chunk_*.out.json"))
    for f in files:
        for e in load(f):
            merged[e["id"]] = {
                "id": e["id"],
                "errors": e.get("errors", []),
                "corrected": e.get("corrected"),
            }
    # broadcast each representative's verdict to all ids in its dedup group
    dmap_path = Path(a.outdir) / "dedup_map.json"
    if dmap_path.exists():
        for rep_str, group in load(dmap_path).items():
            rep = int(rep_str)
            if rep in merged:
                v = merged[rep]
                for i in group:
                    merged[i] = {"id": i, "errors": v["errors"], "corrected": v["corrected"]}
    missing = [i for i in ids if i not in merged]
    out = []
    for i in ids:
        if i in merged:
            out.append(merged[i])
        else:  # subagent didn't cover it -> keep pre-check errors, no corrected
            out.append({"id": i, "errors": pre_by_id.get(i, []), "corrected": None})
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    cov = sum(1 for i in ids if i in merged)
    print(f"[merge] {len(files)} chunk outputs -> {a.out}")
    print(f"[merge] covered {cov}/{len(ids)} ids (after broadcast); MISSING {len(missing)}: {missing[:20]}")
    if missing:
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("split")
    s.add_argument("--state", required=True)
    s.add_argument("--errors", required=True)
    s.add_argument("--terms", required=True)
    s.add_argument("--outdir", required=True)
    s.add_argument("--size", type=int, default=200)
    s.set_defaults(fn=cmd_split)
    m = sub.add_parser("merge")
    m.add_argument("--state", required=True)
    m.add_argument("--errors", required=True)
    m.add_argument("--outdir", required=True)
    m.add_argument("--out", required=True)
    m.set_defaults(fn=cmd_merge)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
