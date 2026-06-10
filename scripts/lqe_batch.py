"""
LQE 批次编排 + 断点续跑。

子命令：
  plan     state.json → batches/batch_NN.txt（按输出体量自适应分批 + manifest.json）
  merge    evals/*.json → errors.json（断点：缺批占位，报告完成度）

设计原则（吸取 64K 超限教训）：
  - 按"输出 token 体量"分批，不是按段数均分。剧情/对话段每段产出完整修正泰文，体量大。
  - 每批落独立 eval_NN.json（实时写入由评审 agent 完成）。批级失败只重跑该批，不连累整体。
  - merge 幂等：随时可跑，缺批用空错占位并列出，齐批后再跑得最终分。
"""
import argparse
import json
import re
from pathlib import Path

_RE_CJK = re.compile(r'[一-鿿]')


def _est_output_chars(seg, term_hits):
    """估算该段评审输出体量：有修正时≈源长×3(泰文)，叠加术语命中注记。"""
    src_len = len(seg["source"])
    base = 60                      # JSON 骨架 + 空错
    correction = src_len * 3       # 可能的完整泰文修正
    terms = term_hits * 25         # 每条命中注记
    return base + correction + terms


def cmd_plan(args):
    job = Path(args.job)
    state = json.loads((job / "state.json").read_text(encoding="utf-8"))
    segs = state["segments"]
    terms = json.loads((job / "terms.json").read_text(encoding="utf-8")) if (job / "terms.json").exists() else []
    tlist = [(t["source"], t["target"], t.get("status", "")) for t in terms if len(t["source"]) >= 2]
    pre = {}
    pc = job / "errors_precheck.json"
    if pc.exists():
        pre = {r["id"]: r["errors"] for r in json.loads(pc.read_text(encoding="utf-8"))}

    bdir = job / "batches"
    bdir.mkdir(exist_ok=True)
    budget = args.output_budget      # 每批输出 char 上限，默认 24000（≈安全 < 64K token）

    batches, cur, cur_cost = [], [], 0
    for s in segs:
        hits = [(ts, tt, st) for ts, tt, st in tlist if ts in s["source"]]
        cost = _est_output_chars(s, len(hits))
        if cur and cur_cost + cost > budget:
            batches.append(cur)
            cur, cur_cost = [], 0
        cur.append((s, hits))
        cur_cost += cost
    if cur:
        batches.append(cur)

    manifest = []
    for i, batch in enumerate(batches):
        lines = []
        for s, hits in batch:
            sid, src, tgt = s["id"], s["source"], s["target"]
            hh = [f"{ts}={tt}[{st}]" for ts, tt, st in hits]
            flags = '; '.join(f"{e['category']}:{e['comment'][:60]}" for e in pre.get(sid, []))
            block = f"#{sid}\nSRC: {src}\nTGT: {tgt}"
            if hh:
                block += f"\nTERMS: {' | '.join(hh[:8])}"
            if flags:
                block += f"\nPRECHECK: {flags}"
            lines.append(block)
        (bdir / f"batch_{i:02d}.txt").write_text('\n---\n'.join(lines), encoding="utf-8")
        ids = [s["id"] for s, _ in batch]
        manifest.append({"batch": i, "n": len(batch), "id_min": ids[0], "id_max": ids[-1],
                          "est_output_chars": sum(_est_output_chars(s, len(h)) for s, h in batch)})

    (job / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[plan] {len(segs)} segs → {len(batches)} batches (budget {budget} chars/batch)")
    big = [m for m in manifest if m["est_output_chars"] > budget * 1.1]
    for m in manifest:
        flag = "  ⚠large" if m in big else ""
        print(f"  batch_{m['batch']:02d}: {m['n']:>3} segs  ids {m['id_min']}-{m['id_max']}  ~{m['est_output_chars']//1000}k chars{flag}")


def cmd_merge(args):
    job = Path(args.job)
    state = json.loads((job / "state.json").read_text(encoding="utf-8"))
    evals = sorted((job / "evals").glob("eval_*.json"))
    merged = {}
    for f in evals:
        try:
            for r in json.loads(f.read_text(encoding="utf-8")):
                merged[r["id"]] = r          # 后到覆盖：子批(04a)覆盖原批(04)残留
        except json.JSONDecodeError as e:
            print(f"[warn] skip malformed {f.name}: {e}")

    seg_ids = [s["id"] for s in state["segments"]]
    missing = [i for i in seg_ids if i not in merged]
    out = []
    for s in state["segments"]:
        out.append(merged.get(s["id"], {"id": s["id"], "errors": [], "corrected": None}))
    (job / "errors.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    done = len(seg_ids) - len(missing)
    print(f"[merge] {len(evals)} eval files → {done}/{len(seg_ids)} segs covered → errors.json")
    if missing:
        # 压缩成区间显示
        runs, a = [], missing[0]
        for x, y in zip(missing, missing[1:] + [None]):
            if y != (x + 1):
                runs.append(f"{a}-{x}" if a != x else f"{a}")
                a = y
        print(f"[merge] MISSING {len(missing)} segs (空错占位，分数偏高): {', '.join(runs)}")
    else:
        print("[merge] complete — 全段覆盖，可出最终分")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("--job", required=True); p.add_argument("--output-budget", type=int, default=24000)
    m = sub.add_parser("merge"); m.add_argument("--job", required=True)
    args = ap.parse_args()
    {"plan": cmd_plan, "merge": cmd_merge}[args.cmd](args)


if __name__ == "__main__":
    main()
