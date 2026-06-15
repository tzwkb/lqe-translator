#!/usr/bin/env python3
"""Convert a ROCO Master TB workbook to the LQE terms_*.json format.

The master TB layout: a title/blank band on top, then a header row that
contains "术语 ZHCN" (source). The target language and its status live in
their own columns. Because the sheet repeats the header "术语状态 Status"
for every language, the status column is resolved POSITIONALLY as the first
status header located AFTER the chosen target column.

Output: list of {"source","target"[,"status"]}; blank status -> field omitted.
Rows with an empty target are dropped (untranslated, cannot serve as a term).
Identical-target duplicates of the same source are collapsed (status-bearing
entry preferred); differing-target duplicates are kept-first with a warning.
"""
import argparse
import json
import sys
from pathlib import Path

import openpyxl

ZW = {0x200b: None, 0x200c: None, 0x200d: None, 0xfeff: None, 0x2060: None}
SRC_HDR = "术语 ZHCN"
STATUS_HDRS = {"术语状态 status", "status", "术语状态"}


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

    by_src = {}
    diff_warn = []
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
        st = clean(r[sti]) if (sti is not None and sti < len(r)) else ""
        if src in by_src:
            prev = by_src[src]
            if prev["target"] != tgt:
                diff_warn.append((src, prev["target"], tgt))
                continue  # keep first
            if not prev.get("status") and st:  # upgrade to status-bearing
                prev["status"] = st
            continue
        item = {"source": src, "target": tgt}
        if st:
            item["status"] = st
        by_src[src] = item

    backfilled = 0
    if args.backfill:
        old = json.loads(Path(args.backfill).read_text(encoding="utf-8"))
        for t in old:
            s = clean(t.get("source"))
            g = clean(t.get("target"))
            # only fill master's 待填充 holes; never resurrect dropped concepts
            if s and g and s in empty_src and s not in by_src:
                item = {"source": s, "target": g}
                st = clean(t.get("status"))
                if st:
                    item["status"] = st
                by_src[s] = item
                backfilled += 1

    terms = list(by_src.values())
    Path(args.out).write_text(
        json.dumps(terms, ensure_ascii=False, indent=1), encoding="utf-8")

    n_status = sum(1 for t in terms if t.get("status"))
    from collections import Counter
    dist = Counter(t.get("status", "(none)") for t in terms)
    print(f"[ok] wrote {len(terms)} unique terms -> {args.out}")
    print(f"     master-filled: {len(terms) - backfilled}  backfilled (待填充 gap): {backfilled}")
    print(f"     master empty-target rows: {dropped_empty}")
    print(f"     with status: {n_status}  dist: {dict(dist)}")
    if diff_warn:
        print(f"[warn] {len(diff_warn)} same-source DIFFERENT-target (kept first):", file=sys.stderr)
        for s, a, b in diff_warn[:20]:
            print(f"        {s}: kept {a!r}  dropped {b!r}", file=sys.stderr)


if __name__ == "__main__":
    main()
