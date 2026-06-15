#!/usr/bin/env python3
"""Aggregate identical (source,target) segments to ONE verdict, and report the
groups whose independent AI verdicts disagreed → human ruling.

注：lqe_chunk 现已在 split 阶段按 (source,target) 去重、merge 阶段广播，相同句段
只评一次——分块管线本身就不再产生「同句异判」。本脚本用于对**未经去重**评出的
errors.json 做事后归一 + 出「待人工裁决」分歧报告（与 lqe_chunk 的去重共用同一
(source,target) 分组语义）。

  1. 每个 (source,target) 组取一个代表判定（penalty 最高，并列取最小 id）广播到全组；
  2. 出 待人工裁决 xlsx，列出有分歧的组及每个竞争版本，供人工定后回填术语库。
"""
import argparse
import json
from pathlib import Path
from collections import defaultdict

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill

from lqe_engine import read_json, WEIGHTS, SEVERITY_POINTS   # 评分权威表，勿在此重抄


def penalty(errs):
    return sum(WEIGHTS.get(e.get("category"), 1.0) * SEVERITY_POINTS.get(e.get("severity"), 0)
               for e in errs)


def esig(errs):
    return tuple(sorted((e.get("category", ""), e.get("severity", "")) for e in errs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--errors", required=True)
    ap.add_argument("--out", required=True)       # consistent errors.json
    ap.add_argument("--report", required=True)    # 待人工裁决 xlsx
    a = ap.parse_args()

    state = read_json(a.state)
    emap = {e["id"]: e for e in read_json(a.errors)}
    groups = defaultdict(list)
    for s in state["segments"]:
        groups[(s.get("source", ""), s.get("target", ""))].append(s["id"])

    out_by_id = {}
    divergent = []
    for (src, tgt), ids in groups.items():
        rep_e = emap.get(max(ids, key=lambda i: (penalty(emap.get(i, {}).get("errors", [])), -i)), {})
        rep_errs = [dict(e) for e in rep_e.get("errors", [])]   # 组内共享一份（只读，待序列化）
        rep_corr = rep_e.get("corrected")
        for i in ids:
            out_by_id[i] = {"id": i, "errors": rep_errs, "corrected": rep_corr}
        versions = defaultdict(list)                            # 同一签名只算一遍
        for i in ids:
            e = emap.get(i, {})
            versions[(esig(e.get("errors", [])), e.get("corrected") or None)].append(i)
        if len(ids) > 1 and len(versions) > 1:                  # 同句判出多版本 = 分歧
            comp = [("; ".join(f"{c}/{s}" for c, s in sg) if sg else "（无错）", corr, len(vids))
                    for (sg, corr), vids in sorted(versions.items(), key=lambda kv: -len(kv[1]))]
            divergent.append({"source": src, "target": tgt, "count": len(ids),
                              "adopted_corr": rep_corr, "versions": comp})

    out = [out_by_id[s["id"]] for s in state["segments"]]
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── 待人工裁决 report ──
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "待人工裁决"
    hdr = ["源文", "原译文", "出现次数", "竞争判定（各版本：类别/严重度 → 修正）",
           "已自动归一采用", "人工裁决（请填最终译法）"]
    ws.append(hdr)
    fill = PatternFill("solid", fgColor="2B3A2E")
    for ci in range(1, len(hdr) + 1):
        c = ws.cell(1, ci); c.font = Font(bold=True, color="FFFFFF"); c.fill = fill
    for d in sorted(divergent, key=lambda x: -x["count"]):
        vers = "\n".join(f"[{n}段] {cats}" + (f" → {corr}" if corr else "")
                         for cats, corr, n in d["versions"])
        ws.append([d["source"], d["target"], d["count"], vers,
                   d["adopted_corr"] or "（判为正确/未改）", ""])
    for col, w in zip("ABCDEF", [26, 30, 8, 52, 30, 28]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    wb.save(a.report)

    print(f"[aggregate] groups={len(groups)} | divergent(需裁决)={len(divergent)} → {a.out}")
    print(f"[aggregate] 待人工裁决报告 → {a.report}")


if __name__ == "__main__":
    main()
