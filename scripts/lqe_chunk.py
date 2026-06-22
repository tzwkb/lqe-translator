#!/usr/bin/env python3
"""Split a job for subagent fan-out, then merge subagent outputs back.

split: state.json + errors.json(pre-check) + terms.json -> chunks/chunk_NN.json
       each segment carries {id, source, target, precheck[], term_hits[]}
merge: chunks/chunk_NN.out.json (list of {id, errors, corrected}) -> errors.json
       validates every state id is covered; missing ids fall back to pre-check.
"""
import argparse
import json
import re
import sys
from pathlib import Path


from lqe_engine import read_json as load


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


def _seg_kind(src):
    """Tag content surface so lenses can be gated.
      name = short single-token entry (terminology/spelling surface only)
      desc = has semantic surface (sentence / markup / placeholder / compound)
    Bias toward 'desc': a misrouted desc only costs tokens, a misrouted name
    loses recall (e.g. 典藏赛季徽章礼盒 hides an Omission). Threshold is tunable."""
    if len(src) > 6:
        return "desc"
    if any(p in src for p in "，。！？、；：,.!?;:「」“”\"'"):
        return "desc"
    if any(m in src for m in ("<", "{", "#", "%", "\\", " ")):
        return "desc"
    return "name"


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
    groups = {}
    for seg in segs:
        groups.setdefault((seg.get("source", ""), seg.get("target", "")), []).append(seg)
    reps, dedup_map = [], {}
    for gsegs in groups.values():          # dict 保序：组按首次出现序
        rep = min(gsegs, key=lambda s: s["id"])
        reps.append(rep)                    # 存 seg 本身，省一张 id→seg 表
        dedup_map[rep["id"]] = [s["id"] for s in gsegs]

    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "dedup_map.json").write_text(
        json.dumps({str(k): v for k, v in dedup_map.items()}, ensure_ascii=False),
        encoding="utf-8")

    size = a.size
    nchunks = (len(reps) + size - 1) // size
    for ci in range(nchunks):
        rows = []
        for seg in reps[ci * size:(ci + 1) * size]:
            src_txt = seg.get("source", "")
            rows.append({
                "id": seg["id"],
                "source": src_txt,
                "target": seg.get("target", ""),
                "kind": _seg_kind(src_txt),
                "precheck": pre_by_id.get(seg["id"], []),
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
                    merged[i] = {**v, "id": i}
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


_ALL_CATS = {
    "Mistranslation", "Omission", "Addition", "Untranslated", "Grammar",
    "Inconsistency", "Company style", "Unidiomatic", "Terminology", "Markup",
    "Culture specific reference", "Audience appropriateness", "Punctuation",
    "Spelling", "Locale convention", "Length", "Other", "Neutral",
}
_A_OWNED = {"Mistranslation", "Omission", "Addition", "Untranslated"}


def _chunk_idxs(outdir: Path):
    return sorted(int(re.fullmatch(r"chunk_(\d+)", p.stem).group(1))
                  for p in outdir.glob("chunk_*.json")
                  if re.fullmatch(r"chunk_(\d+)", p.stem))


def _norm_lens(arr, path):
    """规范化 lens 输出为嵌套 schema [{id, errors:[{category,severity,comment}], corrected}]。
    自动归并扁平 schema（{id,category,severity,comment,corrected} 每错一对象）——历史上
    merge-lenses 见不到 'errors' 键即静默跳过，整份发现被丢（2026-06-22 chunk_02/03.A 26 条）。
    缺 'id' 直接报错（不静默）。"""
    out, order, flat_n = {}, [], 0
    for e in arr:
        if not isinstance(e, dict) or "id" not in e:
            raise ValueError(f"{Path(path).name}: lens entry missing 'id': {str(e)[:80]}")
        i = e["id"]
        if i not in out:
            out[i] = {"id": i, "errors": [], "corrected": e.get("corrected")}
            order.append(i)
        if isinstance(e.get("errors"), list):
            out[i]["errors"].extend(e["errors"])
        elif "category" in e:                      # 扁平 schema → 归并
            flat_n += 1
            out[i]["errors"].append({"category": e.get("category"),
                                     "severity": e.get("severity", "Major"),
                                     "comment": e.get("comment", "")})
        if not out[i]["corrected"] and e.get("corrected"):
            out[i]["corrected"] = e["corrected"]
    if flat_n:
        print(f"[lens] {Path(path).name}: 归并 {flat_n} 条扁平 schema → 嵌套", file=sys.stderr)
    return [out[i] for i in order]


_LENS_ADD = ["A", "G", "R"]   # additive lenses unioned onto the T spine


def cmd_merge_lenses(a):
    """Union per-lens outputs into chunk_NN.out.json (the input to `merge`).
      spine   = chunk_NN.T.json   (all segments, pre-check triaged; terminology axis)
      additive= chunk_NN.{A,G,R}.json (only flagged segments)
    T carries every id + clean verdicts; A/G/R append their findings. A segment
    flagged by >1 lens gets corrected=null (multiple fixes — leave to manual integrate)."""
    outdir = Path(a.outdir)
    idxs = sorted(int(re.fullmatch(r"chunk_(\d+)", p.stem).group(1))
                  for p in outdir.glob("chunk_*.json")
                  if re.fullmatch(r"chunk_(\d+)", p.stem))
    used, total, multi = set(), 0, 0
    for ci in idxs:
        spine = outdir / f"chunk_{ci:02d}.T.json"
        if not spine.exists():
            print(f"[merge-lenses] MISSING spine {spine.name} — run lens T first")
            sys.exit(3)
        used.add("T")
        by_id, flags = {}, {}
        for e in _norm_lens(load(spine), spine):
            by_id[e["id"]] = {"errors": list(e.get("errors", [])),
                              "corr": {"T": e.get("corrected")}}
            flags[e["id"]] = {"T"} if e.get("errors") else set()
        for L in _LENS_ADD:
            f = outdir / f"chunk_{ci:02d}.{L}.json"
            if not f.exists():
                continue
            used.add(L)
            for e in _norm_lens(load(f), f):
                if not e.get("errors"):
                    continue
                slot = by_id.setdefault(e["id"], {"errors": [], "corr": {}})
                slot["errors"].extend(e["errors"])
                slot["corr"][L] = e.get("corrected")
                flags.setdefault(e["id"], set()).add(L)
        out = []
        for sid in sorted(by_id):
            slot = by_id[sid]
            seen, errs = set(), []
            for er in slot["errors"]:
                k = (er.get("category"), er.get("severity"), (er.get("comment") or "")[:40])
                if k in seen:
                    continue
                seen.add(k)
                errs.append(er)
            lset = flags.get(sid, set())
            if not errs:
                corr = None
            elif len(lset) == 1:
                corr = slot["corr"].get(next(iter(lset)))
            else:
                corr, multi = None, multi + 1   # multi-lens -> manual integrate
            out.append({"id": sid, "errors": errs, "corrected": corr})
        (outdir / f"chunk_{ci:02d}.out.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        total += len(out)
    print(f"[merge-lenses] lenses {sorted(used)} × {len(idxs)} chunks -> chunk_NN.out.json")
    print(f"[merge-lenses] {total} seg-entries; {multi} multi-lens segs -> corrected=null (manual integrate)")


def cmd_validate_lenses(a):
    """合并前结构守门：每 chunk 的 T/A/G/R 文件结构合规 + T 脊柱满覆盖 + 类别白名单。
    扁平 schema 仅告警（merge-lenses 会归并）；缺 id / 坏类别 / 脊柱不全 → 非零退出（不静默）。"""
    outdir = Path(a.outdir)
    idxs = _chunk_idxs(outdir)
    if not idxs:
        print("[validate-lenses] no chunks found", file=sys.stderr); sys.exit(4)
    problems = []
    for ci in idxs:
        base = load(outdir / f"chunk_{ci:02d}.json")
        ids = {s["id"] for s in base["segments"]}
        for L in ("T", "A", "G", "R"):
            p = outdir / f"chunk_{ci:02d}.{L}.json"
            if not p.exists():
                problems.append(f"chunk_{ci:02d}.{L}: MISSING"); continue
            try:
                arr = load(p)
            except Exception as e:
                problems.append(f"{p.name}: invalid JSON ({e})"); continue
            if not isinstance(arr, list):
                problems.append(f"{p.name}: top-level not a list"); continue
            try:
                norm = _norm_lens(arr, p)
            except ValueError as e:
                problems.append(str(e)); continue
            for e in norm:
                for er in e["errors"]:
                    for k in ("category", "severity", "comment"):
                        if k not in er:
                            problems.append(f"{p.name} id{e['id']}: error missing '{k}'")
                    if er.get("category") not in _ALL_CATS:
                        problems.append(f"{p.name} id{e['id']}: unknown category {er.get('category')!r}")
            if L == "T":
                miss = ids - {e["id"] for e in norm}
                if miss:
                    problems.append(f"chunk_{ci:02d}.T spine gap: {len(miss)} ids missing e.g. {sorted(miss)[:5]}")
    if problems:
        print(f"[validate-lenses] FAIL ({len(problems)} problems):", file=sys.stderr)
        for pr in problems[:50]:
            print("  " + pr, file=sys.stderr)
        sys.exit(4)
    print(f"[validate-lenses] OK: {len(idxs)} chunks × T/A/G/R structurally valid, T spine complete")


def cmd_reconcile(a):
    """归属权威化：A_OWNED 类（Mistranslation/Omission/Addition/Untranslated）仅当 A lens
    确认该 (id,类别) 才保留；剔除 T 透传等非 A 确认项并存档（不静默删）。
    在 merge-lenses 之后、merge 之前运行；改写 chunk_NN.out.json。"""
    outdir = Path(a.outdir)
    dropped = []
    for ci in _chunk_idxs(outdir):
        ap = outdir / f"chunk_{ci:02d}.A.json"
        a_set = set()
        if ap.exists():
            for e in _norm_lens(load(ap), ap):
                for er in e["errors"]:
                    a_set.add((e["id"], er.get("category")))
        op = outdir / f"chunk_{ci:02d}.out.json"
        if not op.exists():
            continue
        out = load(op); changed = False
        for seg in out:
            new = []
            for er in seg.get("errors", []):
                if er.get("category") in _A_OWNED and (seg["id"], er.get("category")) not in a_set:
                    dropped.append({"chunk": ci, "id": seg["id"], **er}); changed = True
                else:
                    new.append(er)
            if len(new) != len(seg.get("errors", [])):
                seg["errors"] = new
                if not new:
                    seg["corrected"] = None
        if changed:
            op.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    arch = outdir.parent / "reconcile_dropped.json"
    arch.write_text(json.dumps(dropped, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[reconcile] dropped {len(dropped)} non-A-confirmed A-owned errors -> {arch}")


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
    ml = sub.add_parser("merge-lenses")   # union chunk_NN.{T,A,G,R}.json -> chunk_NN.out.json
    ml.add_argument("--outdir", required=True)
    ml.set_defaults(fn=cmd_merge_lenses)
    vl = sub.add_parser("validate-lenses")  # 合并前结构守门（缺 id/坏类别/脊柱不全→非零退出）
    vl.add_argument("--outdir", required=True)
    vl.set_defaults(fn=cmd_validate_lenses)
    rc = sub.add_parser("reconcile")        # A_OWNED 归属权威化 + 存档 dropped
    rc.add_argument("--outdir", required=True)
    rc.set_defaults(fn=cmd_reconcile)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
