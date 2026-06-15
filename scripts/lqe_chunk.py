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


def cmd_split(a):
    state = load(a.state)
    pre = load(a.errors)
    terms = load(a.terms)
    segs = state["segments"]
    pre_by_id = {e["id"]: e.get("errors", []) for e in pre}
    # term hits: longest source-substring matches present in each segment source
    titems = [(t["source"], t.get("target", ""), t.get("status", ""))
              for t in terms if len(t.get("source", "")) >= 2]
    titems.sort(key=lambda x: -len(x[0]))
    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    size = a.size
    n = len(segs)
    nchunks = (n + size - 1) // size
    for ci in range(nchunks):
        rows = []
        for seg in segs[ci * size:(ci + 1) * size]:
            sid = seg["id"]
            src = seg.get("corrected") or seg.get("source") or ""
            src_txt = seg.get("source", "")
            tgt = seg.get("target", "")
            hits = []
            for ts, th, st in titems:
                if ts in src_txt:
                    h = {"src": ts, "th": th}
                    if st:
                        h["status"] = st
                    hits.append(h)
                    if len(hits) >= 15:
                        break
            rows.append({
                "id": sid,
                "source": src_txt,
                "target": tgt,
                "precheck": pre_by_id.get(sid, []),
                "term_hits": hits,
            })
        (outdir / f"chunk_{ci:02d}.json").write_text(
            json.dumps({"chunk_id": ci, "segments": rows},
                       ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[split] {n} segments -> {nchunks} chunks (size {size}) in {outdir}")


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
    missing = [i for i in ids if i not in merged]
    out = []
    for i in ids:
        if i in merged:
            out.append(merged[i])
        else:  # subagent didn't cover it -> keep pre-check errors, no corrected
            out.append({"id": i, "errors": pre_by_id.get(i, []), "corrected": None})
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    print(f"[merge] {len(files)} chunk outputs -> {a.out}")
    print(f"[merge] covered {len(merged)}/{len(ids)} ids; MISSING {len(missing)}: {missing[:20]}")
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
