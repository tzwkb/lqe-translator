#!/usr/bin/env python3
"""Split a job for subagent fan-out, then merge subagent outputs back.

split: state.json + errors.json(pre-check) + terms.json -> chunks/chunk_NN.json
       each segment carries {id, source, target, precheck[], term_hits[], term_near[]}
merge: chunks/chunk_NN.out.json (list of {id, errors, corrected}) -> errors.json
       validates every state id is covered; missing ids fall back to pre-check.
"""
import argparse
import json
import re
import sys
from pathlib import Path


from lqe_engine import read_json as load, group_terms, resolve_corrected
from term_suggest import build_index as _tn_build, suggest as _tn_suggest


def _term_hits(src_txt, titems, cap=15):
    """Longest-match, coverage-filtered term hits. Keep a TB term only if it has
    an occurrence NOT fully inside a longer term's occurrence — so 优优 inside
    绒光优优 is dropped (the longer term already covers it), but a separate
    standalone 优优 elsewhere in the segment is still kept. `th` is always the
    full candidate-senses list (len 1 for an ordinary singleton source)."""
    occ = []  # (start, end, src, senses)
    for ts, senses in titems:               # titems is sorted longest-first
        i = src_txt.find(ts)
        while i >= 0:
            occ.append((i, i + len(ts), ts, senses))
            i = src_txt.find(ts, i + 1)
    occ.sort(key=lambda o: -(o[1] - o[0]))  # longest span first
    accepted = []                           # spans claimed by longer terms
    kept = {}                               # src -> hit (one entry per term)
    for s, e, ts, senses in occ:
        if any(a <= s and e <= b for a, b in accepted):
            continue                        # covered by a longer term -> drop
        accepted.append((s, e))
        if ts not in kept:
            kept[ts] = {"src": ts, "th": senses}
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
    grouped = group_terms(terms)
    titems = [(src, senses) for src, senses in grouped.items() if len(src) >= 2]
    titems.sort(key=lambda x: -len(x[0]))

    # near-term suggester (TF-IDF over TB)：精确匹配漏的"差一两字"变体名 → term_near 参考
    # 多义词条取第一个候选译法作代表值（term_near 只是参考线索，不需要区分语义）
    tn_pairs = [(src, senses[0]["target"]) for src, senses in grouped.items() if senses]
    tn_idx = _tn_build([p[0] for p in tn_pairs], [p[1] for p in tn_pairs]) if tn_pairs else None

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
    budget = getattr(a, "char_budget", 0) or 0
    # partition reps into chunks. --char-budget>0: cut by source+target char volume
    # (评估负载代理)，密集段→更小的块；--size 同时作硬上限。否则固定 --size 段数。
    # 块越小 → 单 agent 负载有上限 + 失败/中断的 blast-radius 越小 + 续跑更细
    # （断点优先按 chunk_NN.<L>.json 跳过已完成块）。
    if budget > 0:
        parts, cur, curv = [], [], 0
        for rep in reps:
            w = len(rep.get("source", "")) + len(rep.get("target", ""))
            if cur and (curv + w > budget or len(cur) >= size):
                parts.append(cur)
                cur, curv = [], 0
            cur.append(rep)
            curv += w
        if cur:
            parts.append(cur)
    else:
        parts = [reps[i:i + size] for i in range(0, len(reps), size)]
    nchunks = len(parts)
    vols = []
    for ci, part in enumerate(parts):
        rows = []
        for seg in part:
            src_txt = seg.get("source", "")
            hits = _term_hits(src_txt, titems)
            near = _tn_suggest(tn_idx, src_txt, exclude={h["src"] for h in hits}) \
                if tn_idx else []
            rows.append({
                "id": seg["id"],
                "source": src_txt,
                "target": seg.get("target", ""),
                "content_type": seg.get("content_type"),
                "text_type_context": seg.get("text_type_context"),
                "kind": _seg_kind(src_txt),
                "precheck": pre_by_id.get(seg["id"], []),
                "term_hits": hits,
                "term_near": near,
            })
        vols.append(sum(len(r["source"]) + len(r["target"]) for r in rows))
        (outdir / f"chunk_{ci:02d}.json").write_text(
            json.dumps({"chunk_id": ci, "segments": rows},
                       ensure_ascii=False, indent=1), encoding="utf-8")
    dup = len(segs) - len(reps)
    mode = f"char-budget {budget} (cap {size})" if budget > 0 else f"size {size}"
    print(f"[split] {len(segs)} segments -> {len(reps)} unique (deduped {dup}) "
          f"-> {nchunks} chunks ({mode}) in {outdir}")
    print(f"[split] seg-counts: {[len(p) for p in parts]}")
    print(f"[split] src+tgt chars/chunk: {vols}")


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
                    merged[i] = {**v, "id": i, "errors": list(v["errors"])}
    # 保留 pre-check 的确定性硬错——空译文/中文残留 Untranslated 是确定性 Major，
    # 却易落在 T（划归 A）与 A（沉默推回 pre-check）的职责缝隙里被丢（实证：
    # 2026-06-23 nrc/th 10 段空译文漏计、分数虚高 97.98 vs 实际 97.09）。
    # A lens 沉默 ≠ 甄别为 FP，故从基底补回；在 reconcile 之后注入以绕过其
    # 「A 未确认即剔 A_OWNED」（否则刚补就被剔）。
    reinstated = 0
    for i in ids:
        if i not in merged:
            continue
        have = {e.get("category") for e in merged[i]["errors"]}
        for pe in pre_by_id.get(i, []):
            if pe.get("category") in _DETERMINISTIC_PRECHECK and pe.get("category") not in have:
                merged[i]["errors"].append(pe)
                reinstated += 1
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
    if reinstated:
        print(f"[merge] reinstated {reinstated} deterministic Untranslated from pre-check baseline")
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
# pre-check 确定性硬错中，必须无条件从基底保留的类别（lens 不做语义判断、
# 易落职责缝隙）。仅 Untranslated：空译文/中文残留是确定性 Major，FP 极罕见；
# Markup/Length 留给 lens 甄别透传（有分词/CJK 长度等 FP，T 已有效剔除）。
_DETERMINISTIC_PRECHECK = {"Untranslated"}


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


_LENS_ADD = ["N", "A", "G", "R"]   # additive lenses unioned onto the T spine
                                   # N=专名音译(术语自审用; 句子流不产 N 文件→跳过, 零影响)


def cmd_merge_lenses(a):
    """Union per-lens outputs into chunk_NN.out.json (the input to `merge`).
      spine   = chunk_NN.T.json   (all segments, pre-check triaged; terminology axis)
      additive= chunk_NN.{A,G,R}.json (only flagged segments)
    T carries every id + clean verdicts; A/G/R append their findings. A segment
    flagged by >1 lens takes the highest-priority non-null corrected (A>T>G>R) as floor
    + stashes all candidates in corr_candidates (Suggest translation never empty)."""
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
        # base chunk 的原译文，供 resolve_corrected 把 lens 给的补丁({"patches":[...]})
        # 还原成完整句——旧格式(直接给完整字符串/None)原样透传，向后兼容。
        tgt_by_id = {s["id"]: s.get("target", "") for s in load(outdir / f"chunk_{ci:02d}.json")["segments"]}
        used.add("T")
        by_id, flags = {}, {}
        for e in _norm_lens(load(spine), spine):
            corr = resolve_corrected(e.get("corrected"), tgt_by_id.get(e["id"], ""))
            by_id[e["id"]] = {"errors": list(e.get("errors", [])),
                              "corr": {"T": corr}}
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
                slot["corr"][L] = resolve_corrected(e.get("corrected"), tgt_by_id.get(e["id"], ""))
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
            cands = {L: c for L, c in slot["corr"].items() if c}  # 非空候选
            entry = {"id": sid, "errors": errs, "corrected": None}
            if errs:
                if len(cands) <= 1:
                    entry["corrected"] = next(iter(cands.values()), None)
                else:
                    # 多 lens 各修各的错(同一基底)：取优先级最高的非空候选作底
                    # (A 准确>T 术语>G 语法>R 语域),保证 Suggest translation 永不空
                    # (PM 0622 两度反馈「没有AI改的译文」);全部候选存入 corr_candidates,
                    # 供 SKILL 大文件流程的可选整合步合并多处修正。
                    entry["corrected"] = next((cands[L] for L in ("N", "A", "T", "G", "R") if L in cands), None)
                    entry["corr_candidates"] = cands
                    multi += 1
            out.append(entry)
        (outdir / f"chunk_{ci:02d}.out.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        total += len(out)
    print(f"[merge-lenses] lenses {sorted(used)} × {len(idxs)} chunks -> chunk_NN.out.json")
    print(f"[merge-lenses] {total} seg-entries; {multi} multi-lens segs -> priority-pick floor + corr_candidates (integrate optional)")


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
        for L in ("T", "A", "G", "R", "N"):   # N=专名音译, 仅术语自审产出 → 可选
            p = outdir / f"chunk_{ci:02d}.{L}.json"
            if not p.exists():
                if L != "N":          # 句子流不产 N, 缺 N 不算问题
                    problems.append(f"chunk_{ci:02d}.{L}: MISSING")
                continue
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


def cmd_split_half(a):
    """单个 chunk×lens 单元反复失败(超时/64K)时，把该 chunk 原地二分成两个更小的
    dispatch 目标——不重新走 pre-check/term_hits(已在原 chunk 里算好，直接继承)。
    产出 chunk_NN_p1.json / chunk_NN_p2.json，各自当正常 chunk 派发单个 lens。
    --lens 可选：若该 chunk 该 lens 已有 ckpt.jsonl(断了之前攒过一些断点进度)，
    按 id 归属把已判条目分别转给 p1/p2 的 ckpt.jsonl——已判过的不会因为二分而白费，
    新派的两个小 agent 一开局查断点就会跳过这些、只接着判各自剩下的。"""
    outdir = Path(a.outdir)
    ci = int(a.chunk)
    data = load(outdir / f"chunk_{ci:02d}.json")
    segs = data["segments"]
    mid = len(segs) // 2
    parts = [segs[:mid], segs[mid:]]
    id_sets = [{s["id"] for s in part} for part in parts]
    for i, part in enumerate(parts, start=1):
        p = outdir / f"chunk_{ci:02d}_p{i}.json"
        p.write_text(json.dumps({"chunk_id": data["chunk_id"], "segments": part},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[split-half] chunk_{ci:02d}（{len(segs)}段）-> "
          + " + ".join(f"chunk_{ci:02d}_p{i}({len(p)}段)" for i, p in enumerate(parts, start=1)))

    if getattr(a, "lens", None):
        L = a.lens
        old_ckpt = outdir / f"chunk_{ci:02d}.{L}.ckpt.jsonl"
        if old_ckpt.exists():
            carried = [0, 0]
            buckets = [[], []]
            for line in old_ckpt.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                e = json.loads(line)
                idx = 0 if e["id"] in id_sets[0] else 1
                buckets[idx].append(line)
            for i in (1, 2):
                new_ckpt = outdir / f"chunk_{ci:02d}_p{i}.{L}.ckpt.jsonl"
                lines = buckets[i - 1]
                if lines:
                    new_ckpt.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    carried[i - 1] = len(lines)
            print(f"[split-half] 继承 {L} 断点：p1 带 {carried[0]} 条、p2 带 {carried[1]} 条"
                  f"（原 {old_ckpt.name} 共 {carried[0] + carried[1]} 条）")
        else:
            print(f"[split-half] {L} 无既有断点（{old_ckpt.name} 不存在），两个新 part 从零开始")


def cmd_join_parts(a):
    """split-half 派发的两个 part 各自出结果后，拼回该 chunk×lens 原本该有的单一
    输出文件（如 chunk_00.T.json），后续 merge-lenses 无需知道这段发生过二分。"""
    combined = []
    for p in a.parts:
        combined.extend(load(p))
    Path(a.out).write_text(json.dumps(combined, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[join-parts] {len(a.parts)} 份 -> {len(combined)} 条 -> {a.out}")


def cmd_ckpt_append(a):
    """lens agent 判完 1 段就调一次——脚本负责校验+追加，agent 不用自己攒/重写整个
    JSON（手写JSON漏转义就是真实事故的成因）。一行一条，agent 中途断线只丢当前
    这一段，不丢已经追加过的。"""
    entry = json.loads(a.entry)  # 校验合法 JSON，非法直接报错，不静默写坏数据
    if "id" not in entry:
        print(f"[ckpt-append] entry 缺 'id': {a.entry[:80]}", file=sys.stderr)
        sys.exit(1)
    p = Path(a.file)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[ckpt-append] id={entry['id']} -> {p}")


def cmd_ckpt_finalize(a):
    """全部段判完后调一次：把 ckpt.jsonl 去重(同 id 取最后一次出现，处理断点重叠)、
    按 id 排序，合并成下游 merge-lenses 认的标准 JSON 数组，写到正式目标路径。"""
    p = Path(a.jsonl)
    by_id = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            by_id[e["id"]] = e
    out = [by_id[i] for i in sorted(by_id)]
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[ckpt-finalize] {len(out)} 条（去重前 {sum(1 for _ in p.read_text(encoding='utf-8').splitlines() if _.strip())}）-> {a.out}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("split")
    s.add_argument("--state", required=True)
    s.add_argument("--errors", required=True)
    s.add_argument("--terms", required=True)
    s.add_argument("--outdir", required=True)
    s.add_argument("--size", type=int, default=100)
    s.add_argument("--char-budget", type=int, default=0,
                   help="cut chunks by source+target char volume (评估负载代理); "
                        "0=off → 固定 --size（向后兼容）. --size 仍作段数硬上限.")
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
    sh = sub.add_parser("split-half")       # 单元反复失败 -> 原地二分成更小 dispatch 目标
    sh.add_argument("--outdir", required=True)
    sh.add_argument("--chunk", required=True, help="原 chunk 序号（如 0、3）")
    sh.add_argument("--lens", default=None, help="若该 chunk 该 lens 已有 ckpt.jsonl，一并按 id 拆给 p1/p2 继承")
    sh.set_defaults(fn=cmd_split_half)
    jp = sub.add_parser("join-parts")       # 二分后的两份结果拼回单一 chunk_NN.<L>.json
    jp.add_argument("--parts", required=True, nargs="+", help="两个 part 的输出文件路径")
    jp.add_argument("--out", required=True)
    jp.set_defaults(fn=cmd_join_parts)
    ca = sub.add_parser("ckpt-append")      # lens agent 判完1段就调1次，脚本负责校验+追加
    ca.add_argument("--file", required=True, help="ckpt jsonl 路径")
    ca.add_argument("--entry", required=True, help="单条结果的 JSON 字符串 {id,errors,corrected}")
    ca.set_defaults(fn=cmd_ckpt_append)
    cf = sub.add_parser("ckpt-finalize")    # 全部段判完后调1次，去重+排序+转成正式 JSON 数组
    cf.add_argument("--jsonl", required=True)
    cf.add_argument("--out", required=True)
    cf.set_defaults(fn=cmd_ckpt_finalize)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
