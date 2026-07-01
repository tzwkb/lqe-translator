#!/usr/bin/env python3
"""Convert a ROCO Master TB workbook to the LQE terms_*.json format.

The master TB layout: a title/blank band on top, then a header row that
contains "术语 ZHCN" (source). The target language lives in its own column;
status/category/definition columns are detected best-effort by header text
(their position and header wording drift between master versions).

Output: list of terms — {"source","target"[,"status"]} for a source with a
single known translation, or {"source","senses":[{"target"[,"status"]
[,"category"][,"definition"]}, ...]} when the SAME source legitimately has
more than one translation (e.g. a name reused for both a Species and a
Creature Individual, or a verb/noun pair) — a real, client-intended polysemy,
not a data error. Rows with an empty target are dropped (untranslated,
cannot serve as a term) unless --backfill recovers an old translation for
that exact gap; concepts absent from the master entirely are NOT backfilled.
`<out>.multisense.json` is always (re)written with every source that ended
up with >1 sense in this run, for a human to eyeball.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from lqe_engine import read_json

import openpyxl

ZW = {0x200b: None, 0x200c: None, 0x200d: None, 0xfeff: None, 0x2060: None}
SRC_HDR = "术语 ZHCN"
STATUS_HDRS = {"术语状态 status", "status", "术语状态"}
CATEGORY_HDRS = {"术语类别 category", "术语类别", "subject", "category"}
DEFINITION_HDRS = {"术语定义 definition", "definition", "note", "术语定义"}


def clean(v) -> str:
    if v is None:
        return ""
    return str(v).translate(ZW).strip()


def find_header_row(rows, src_hdr):
    for i, r in enumerate(rows):
        if any(clean(c) == src_hdr for c in r):
            return i
    raise SystemExit(f"[err] header row containing {src_hdr!r} not found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--target-col", default="TH", help="target language header (e.g. TH/EN)")
    ap.add_argument("--source-hdr", default=SRC_HDR)
    ap.add_argument("--backfill", default=None,
                    help="old terms json: carry over translations for sources the "
                         "master left blank (待填充 gap-fill); concepts absent from "
                         "the master are NOT backfilled")
    args = ap.parse_args()

    wb = openpyxl.load_workbook(args.input, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    h = find_header_row(rows, args.source_hdr)
    hdr = [clean(c) for c in rows[h]]
    try:
        si = hdr.index(args.source_hdr)
        ti = hdr.index(args.target_col)
    except ValueError:
        raise SystemExit(f"[err] columns not found. headers={hdr}")
    # status header is the first status column AFTER the target column
    sti = next((j for j, c in enumerate(hdr) if j > ti and c.lower() in STATUS_HDRS), None)
    # category/definition headers: best-effort, anywhere (position drifts across master versions)
    ci = next((j for j, c in enumerate(hdr) if c.lower() in CATEGORY_HDRS), None)
    di = next((j for j, c in enumerate(hdr) if c.lower() in DEFINITION_HDRS), None)

    by_src: dict[str, list[dict]] = {}
    dropped_empty = 0
    empty_src = set()  # sources present in master with a blank target (待填充)
    for r in rows[h + 1:]:
        src = clean(r[si]) if si < len(r) else ""
        if not src or src == args.source_hdr:
            continue
        tgt = clean(r[ti]) if ti < len(r) else ""
        if not tgt:
            dropped_empty += 1
            empty_src.add(src)
            continue

        cand = {"target": tgt}
        st = clean(r[sti]) if (sti is not None and sti < len(r)) else ""
        if st:
            cand["status"] = st
        cat = clean(r[ci]) if (ci is not None and ci < len(r)) else ""
        if cat:
            cand["category"] = cat
        defn = clean(r[di]) if (di is not None and di < len(r)) else ""
        if defn:
            cand["definition"] = defn

        existing = by_src.setdefault(src, [])
        dup = next((c for c in existing if c["target"] == tgt), None)
        if dup is None:
            existing.append(cand)
        else:
            for k in ("status", "category", "definition"):  # 补全：先出现的行缺、后出现的行有
                if k in cand and k not in dup:
                    dup[k] = cand[k]

    backfilled = 0
    if args.backfill:
        old = read_json(args.backfill)
        for t in old:
            s = clean(t.get("source"))
            g = clean(t.get("target"))
            # only fill master's 待填充 holes; never resurrect dropped concepts
            if s and g and s in empty_src and s not in by_src:
                item = {"target": g}
                st = clean(t.get("status"))
                if st:
                    item["status"] = st
                by_src[s] = [item]
                backfilled += 1

    terms = []
    multisense = []
    for src, cands in by_src.items():
        if len(cands) == 1:
            c = cands[0]
            item = {"source": src, "target": c["target"]}
            if c.get("status"):
                item["status"] = c["status"]
            terms.append(item)
        else:
            terms.append({"source": src, "senses": cands})
            multisense.append({"source": src,
                                "senses": [{"target": c["target"], "category": c.get("category", "")}
                                           for c in cands]})

    Path(args.out).write_text(
        json.dumps(terms, ensure_ascii=False, indent=1), encoding="utf-8")

    multisense_path = Path(args.out).with_suffix("")
    multisense_path = multisense_path.with_name(multisense_path.name + ".multisense.json")
    if multisense:
        multisense_path.write_text(
            json.dumps(multisense, ensure_ascii=False, indent=1), encoding="utf-8")
    elif multisense_path.exists():
        multisense_path.unlink()  # 上一轮遗留、这轮已经没有多义分组了

    dist = Counter(c.get("status", "(none)") for cands in by_src.values() for c in cands)
    n_status = sum(v for k, v in dist.items() if k != "(none)")
    print(f"[ok] wrote {len(terms)} sources ({sum(len(v) for v in by_src.values())} total senses) -> {args.out}")
    print(f"     master-filled sources: {len(by_src) - backfilled}  backfilled (待填充 gap): {backfilled}")
    print(f"     master empty-target rows: {dropped_empty}")
    print(f"     with status: {n_status}  dist: {dict(dist)}")
    print(f"     multi-sense sources: {len(multisense)}" +
          (f" -> {multisense_path}" if multisense else ""))


if __name__ == "__main__":
    main()
