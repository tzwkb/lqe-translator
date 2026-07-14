#!/usr/bin/env python3
"""把任务拆分给各检查模块，再合并问题与安全局部修改。

split: state.json + errors.json(pre-check) + terms.json -> chunks/chunk_NN.json
       each segment carries {id, source, target, precheck[], term_hits[], term_near[]}
merge-checks: check-module files -> chunk_NN.out.json ({id, issues} only)
merge: chunks/chunk_NN.out.json -> errors.json ({id, errors, corrected})
       validates every state id is covered; missing ids fall back to pre-check.
"""
import argparse
import copy
import json
import re
import sys
from pathlib import Path


from lqe_corrections import build_segment_result, normalize_check_entries
from lqe_engine import (
    disabled_modules,
    load_terms,
    optional_modules,
    read_json as load,
    required_modules,
    scope_issue_problem,
    terminology_enabled,
    validate_scope_entries,
)
from term_suggest import build_index as _tn_build, suggest as _tn_suggest


def _group_chunk_terms(terms):
    grouped = {}
    for entry in terms:
        source = (entry.get("source") or "").strip()
        if not source:
            continue
        raw_senses = entry.get("senses") if "senses" in entry else [entry]
        if not isinstance(raw_senses, list):
            continue
        for raw in raw_senses:
            if not isinstance(raw, dict) or "target" not in raw:
                continue
            sense = {
                key: value
                for key, value in raw.items()
                if key not in {"source", "senses"}
            }
            sense["confirmed"] = raw.get("confirmed") is True
            sense["protected"] = raw.get("protected") is True
            grouped.setdefault(source, []).append(sense)
    return grouped


def _term_hits(src_txt, titems, cap=15):
    """Longest-match, coverage-filtered term hits. Keep a TB term only if it has
    an occurrence NOT fully inside a longer term's occurrence — so 优优 inside
    绒光优优 is dropped (the longer term already covers it), but a separate
    standalone 优优 elsewhere in the segment is still kept. Each retained term
    is flattened to one hit per sense for deterministic correction checks."""
    occ = []  # (start, end, src, senses)
    for ts, senses in titems:               # titems is sorted longest-first
        i = src_txt.find(ts)
        while i >= 0:
            occ.append((i, i + len(ts), ts, senses))
            i = src_txt.find(ts, i + 1)
    occ.sort(key=lambda o: -(o[1] - o[0]))  # longest span first
    accepted = []                           # spans claimed by longer terms
    kept = {}                               # src -> senses (one entry per term)
    for s, e, ts, senses in occ:
        if any(a <= s and e <= b for a, b in accepted):
            continue                        # covered by a longer term -> drop
        accepted.append((s, e))
        if ts not in kept:
            kept[ts] = senses
    hits = []
    for source, senses in list(kept.items())[:cap]:
        for sense in senses:
            hit = {"source": source, **sense}
            hit["confirmed"] = sense.get("confirmed") is True
            hit["protected"] = sense.get("protected") is True
            hits.append(hit)
    return hits


def _seg_kind(src):
    """标记内容类型，供检查模块确定适用范围。

    name 是短的单一名称；desc 是句子、复合词或含标记和占位符的内容。
    不确定时归为 desc，以免漏掉复合名称中的含义问题。
    """
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
    if a.terms and not terminology_enabled(state):
        raise SystemExit("[split] scope conflict: --terms is disabled by check scope")
    term_state = state
    if a.terms:
        terms_path = Path(a.terms)
        if not terms_path.is_file():
            raise SystemExit(f"[split] terminology file not found: {terms_path}")
        term_state = {**state, "terms_path": str(terms_path), "terminology": []}
    terms = load_terms(term_state)
    segs = state["segments"]
    pre_by_id = {e["id"]: e.get("issues", []) for e in pre}
    grouped = _group_chunk_terms(terms)
    titems = [(src, senses) for src, senses in grouped.items() if len(src) >= 2]
    titems.sort(key=lambda x: -len(x[0]))

    # near-term suggester (TF-IDF over TB)：精确匹配漏的"差一两字"变体名 → term_near 参考
    # 多义词条取第一个候选译法作代表值（term_near 只是参考线索，不需要区分语义）
    tn_pairs = [(src, senses[0]["target"]) for src, senses in grouped.items() if senses]
    tn_idx = _tn_build([p[0] for p in tn_pairs], [p[1] for p in tn_pairs]) if tn_pairs else None

    # 相同源文和译文只检查一次；合并时把结果复制到组内每个 id
    groups = {}
    for seg in segs:
        groups.setdefault(
            (
                seg.get("source", ""),
                seg.get("target", ""),
                bool(seg.get("protected")),
                seg.get("content_type"),
                seg.get("text_type_context"),
                seg.get("context_note"),
            ),
            [],
        ).append(seg)
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
    # 将代表段分块。--char-budget>0 时按源文和译文总字符数切分，--size 仍是段数上限；
    # 否则按固定段数切分。较小的块可限制单次检查量、缩小失败影响并细化续跑。
    # 断点按 chunk_NN.<module>.json 跳过已完成块。
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
            near = _tn_suggest(tn_idx, src_txt, exclude={h["source"] for h in hits}) \
                if tn_idx else []
            rows.append({
                "id": seg["id"],
                "source": src_txt,
                "target": seg.get("target", ""),
                "content_type": seg.get("content_type"),
                "text_type_context": seg.get("text_type_context"),
                "context_note": seg.get("context_note"),
                "source_ref": seg.get("source_ref"),
                "protected": bool(seg.get("protected")),
                "protected_reason": seg.get("protected_reason"),
                "kind": _seg_kind(src_txt),
                "precheck": pre_by_id.get(seg["id"], []),
                "term_hits": hits,
                "term_near": near,
                "protected_texts": seg.get("protected_texts", []),
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
    state_segments = state["segments"]
    state_by_id = {segment["id"]: segment for segment in state_segments}
    ids = [segment["id"] for segment in state_segments]
    protected_ids = {segment["id"] for segment in state_segments if segment.get("protected")}
    pre = normalize_check_entries(load(a.errors), label=Path(a.errors).name)
    validate_scope_entries(
        state, pre, issues_key="issues", label=Path(a.errors).name
    )
    pre_by_id = {entry["id"]: entry["issues"] for entry in pre}
    outdir = Path(a.outdir)

    chunk_contexts = {}
    for ci in _chunk_idxs(outdir):
        base = load(outdir / f"chunk_{ci:02d}.json")
        for segment in base["segments"]:
            chunk_contexts[segment["id"]] = segment

    merged = {}
    files = sorted(outdir.glob("chunk_*.out.json"))
    for f in files:
        entries = _normalize_module_output(load(f), f)
        validate_scope_entries(
            state, entries, issues_key="issues", label=f.name
        )
        for entry in entries:
            merged[entry["id"]] = copy.deepcopy(entry["issues"])

    representative_by_id = {}
    dmap_path = outdir / "dedup_map.json"
    if dmap_path.exists():
        for rep_str, group in load(dmap_path).items():
            rep = int(rep_str)
            if rep in merged:
                for segment_id in group:
                    merged[segment_id] = copy.deepcopy(merged[rep])
                    representative_by_id[segment_id] = rep

    reinstated = 0
    for i in ids:
        if i in protected_ids:
            continue
        if i not in merged:
            continue
        have = {issue.get("category") for issue in merged[i]}
        for issue in pre_by_id.get(i, []):
            if (
                issue.get("category") in _DETERMINISTIC_PRECHECK
                and issue.get("category") not in have
            ):
                merged[i].append(copy.deepcopy(issue))
                reinstated += 1

    missing = [i for i in ids if i not in merged and i not in protected_ids]
    out = []
    for i in ids:
        representative = representative_by_id.get(i, i)
        context = chunk_contexts.get(representative, {})
        original = state_by_id[i]
        protected_texts = original.get(
            "protected_texts", context.get("protected_texts", [])
        )
        segment = {
            "id": i,
            "target": original.get("target", context.get("target", "")),
            "kind": context.get("kind", _seg_kind(original.get("source", ""))),
            "term_hits": context.get("term_hits", []),
            "protected_texts": protected_texts,
        }
        issues = (
            []
            if i in protected_ids
            else merged.get(i, copy.deepcopy(pre_by_id.get(i, [])))
        )
        out.append(build_segment_result(segment, issues))

    validate_scope_entries(state, out, issues_key="errors", label=Path(a.out).name)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    cov = sum(1 for i in ids if i in merged)
    print(f"[merge] {len(files)} chunk outputs -> {a.out}")
    if reinstated:
        print(f"[merge] restored {reinstated} required machine pre-check issues")
    print(f"[merge] covered {cov}/{len(ids)} ids after copying duplicate results; MISSING {len(missing)}: {missing[:20]}")
    if missing:
        sys.exit(2)


_ACCURACY_OWNED = {"Mistranslation", "Omission", "Addition", "Untranslated"}
_DETERMINISTIC_PRECHECK = {"Untranslated"}
_PRECHECK_REVIEW_CATEGORIES = {
    "Markup",
    "Length",
    "Locale convention",
    "Company style",
    "Inconsistency",
    "Other",
}


def _chunk_idxs(outdir: Path):
    return sorted(int(re.fullmatch(r"chunk_(\d+)", p.stem).group(1))
                  for p in outdir.glob("chunk_*.json")
                  if re.fullmatch(r"chunk_(\d+)", p.stem))


def _normalize_module_output(arr, path):
    return normalize_check_entries(arr, label=Path(path).name)


def _module_issue_problem(state: dict, module: str, issue: dict) -> str | None:
    problem = scope_issue_problem(state, issue)
    if problem:
        return problem
    category = issue.get("category")
    if module == "precheck_review" and category not in _PRECHECK_REVIEW_CATEGORIES:
        return f"precheck_review cannot own category {category!r}"
    return None


def _precheck_provenance_problem(
    original_issues: list[dict], reviewed_issues: list[dict]
) -> str | None:
    used: set[int] = set()
    for reviewed in reviewed_issues:
        match = None
        for index, original in enumerate(original_issues):
            if index in used:
                continue
            if original.get("category") != reviewed.get("category"):
                continue
            reviewed_edit = reviewed.get("edit")
            if reviewed_edit is not None and reviewed_edit != original.get("edit"):
                continue
            match = index
            break
        if match is None:
            return (
                "precheck provenance mismatch for category "
                f"{reviewed.get('category')!r}"
            )
        used.add(match)
    return None


def _check_modules(
    job: Path,
) -> tuple[dict, list[str], tuple[str, ...], tuple[str, ...]]:
    state = load(job / "state.json")
    outdir = job / "chunks"
    required = required_modules(state)
    optional = optional_modules(state)
    disabled = disabled_modules(state)
    chunks = {}
    problems = []
    idxs = _chunk_idxs(outdir)
    if not idxs:
        return chunks, ["no chunks found"], required, optional

    for ci in idxs:
        base_path = outdir / f"chunk_{ci:02d}.json"
        try:
            base = load(base_path)
            ids = [segment["id"] for segment in base["segments"]]
            precheck_by_id = {
                segment["id"]: (
                    segment.get("precheck")
                    if isinstance(segment.get("precheck"), list)
                    else []
                )
                for segment in base["segments"]
            }
        except Exception as error:
            problems.append(f"{base_path.name}: invalid chunk ({error})")
            continue

        expected = set(ids)
        module_entries = {}
        for module in disabled:
            path = outdir / f"chunk_{ci:02d}.{module}.json"
            if path.exists():
                problems.append(
                    f"{path.name}: scope conflict: module {module!r} is disabled"
                )
        for module in required + optional:
            path = outdir / f"chunk_{ci:02d}.{module}.json"
            if not path.exists():
                if module in required:
                    problems.append(f"{path.name}: MISSING")
                continue
            try:
                entries = _normalize_module_output(load(path), path)
            except Exception as error:
                problems.append(str(error))
                continue

            actual = {entry["id"] for entry in entries}
            missing = expected - actual
            unexpected = actual - expected
            if module in required and missing:
                problems.append(
                    f"{path.name}: missing ids {sorted(missing)[:10]}"
                )
            if unexpected:
                problems.append(
                    f"{path.name}: unexpected ids {sorted(unexpected)[:10]}"
                )
            for entry in entries:
                if module == "precheck_review":
                    provenance_problem = _precheck_provenance_problem(
                        precheck_by_id.get(entry["id"], []),
                        entry["issues"],
                    )
                    if provenance_problem:
                        problems.append(
                            f"{path.name}: {provenance_problem} "
                            f"for id {entry['id']}"
                        )
                for issue in entry["issues"]:
                    problem = _module_issue_problem(state, module, issue)
                    if problem:
                        problems.append(f"{path.name}: scope conflict: {problem}")
            module_entries[module] = entries
        chunks[ci] = (ids, module_entries)
    return chunks, problems, required, optional


def _exit_check_problems(command: str, problems: list[str]):
    if not problems:
        return
    print(f"[{command}] FAIL ({len(problems)} problems):", file=sys.stderr)
    for problem in problems[:50]:
        print(f"  {problem}", file=sys.stderr)
    sys.exit(4)


def _issue_key(issue):
    return (
        issue.get("category"),
        issue.get("severity"),
        issue.get("comment"),
        json.dumps(issue.get("edit"), ensure_ascii=False, sort_keys=True),
    )


def cmd_merge_checks(a):
    job = Path(a.job)
    outdir = job / "chunks"
    chunks, problems, required, optional = _check_modules(job)
    _exit_check_problems("merge-checks", problems)

    total = 0
    for ci, (ids, module_entries) in chunks.items():
        entries_by_module = {
            module: {entry["id"]: entry["issues"] for entry in entries}
            for module, entries in module_entries.items()
        }
        output = []
        for segment_id in ids:
            seen = set()
            issues = []
            for module in required + optional:
                for issue in entries_by_module.get(module, {}).get(segment_id, []):
                    category = issue.get("category")
                    if category in _ACCURACY_OWNED and module != "accuracy":
                        continue
                    key = _issue_key(issue)
                    if key in seen:
                        continue
                    seen.add(key)
                    issues.append(issue)
            output.append({"id": segment_id, "issues": issues})
        (outdir / f"chunk_{ci:02d}.out.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        total += len(output)
    print(f"[merge-checks] {len(chunks)} chunks / {total} segments merged")


def cmd_validate_checks(a):
    chunks, problems, _, _ = _check_modules(Path(a.job))
    _exit_check_problems("validate-checks", problems)
    print(f"[validate-checks] OK: {len(chunks)} chunks")


def cmd_reconcile(a):
    job = Path(a.job)
    outdir = job / "chunks"
    dropped = []
    for ci in _chunk_idxs(outdir):
        accuracy_path = outdir / f"chunk_{ci:02d}.accuracy.json"
        accuracy_issues = set()
        if accuracy_path.exists():
            for entry in _normalize_module_output(load(accuracy_path), accuracy_path):
                for issue in entry["issues"]:
                    if issue.get("category") in _ACCURACY_OWNED:
                        accuracy_issues.add((entry["id"], _issue_key(issue)))

        output_path = outdir / f"chunk_{ci:02d}.out.json"
        if not output_path.exists():
            continue
        output = _normalize_module_output(load(output_path), output_path)
        for entry in output:
            kept = []
            for issue in entry["issues"]:
                if (
                    issue.get("category") in _ACCURACY_OWNED
                    and (entry["id"], _issue_key(issue)) not in accuracy_issues
                ):
                    dropped.append({"chunk": ci, "id": entry["id"], **issue})
                else:
                    kept.append(issue)
            entry["issues"] = kept
        output_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    archive = job / "reconcile_dropped.json"
    archive.write_text(
        json.dumps(dropped, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[reconcile] dropped {len(dropped)} unconfirmed accuracy issues")


def cmd_split_half(a):
    """单个 chunk×module 反复失败时，把 chunk 二分成更小的检查任务。

    不重新运行 pre-check 或 term_hits，直接继承原 chunk 的结果。
    产出 chunk_NN_p1.json / chunk_NN_p2.json，并按模块继承断点。
    按 id 归属把已判条目分别转给 p1/p2 的 ckpt.jsonl——已判过的不会因为二分而白费，
    两个新任务读取断点后会跳过已完成条目，只检查各自剩余内容。"""
    outdir = Path(a.job) / "chunks"
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

    if a.module:
        module = a.module
        old_ckpt = outdir / f"chunk_{ci:02d}.{module}.ckpt.jsonl"
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
                new_ckpt = outdir / f"chunk_{ci:02d}_p{i}.{module}.ckpt.jsonl"
                lines = buckets[i - 1]
                if lines:
                    new_ckpt.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    carried[i - 1] = len(lines)
            print(f"[split-half] 继承 {module} 断点：p1 带 {carried[0]} 条、p2 带 {carried[1]} 条"
                  f"（原 {old_ckpt.name} 共 {carried[0] + carried[1]} 条）")
        else:
            print(f"[split-half] {module} 无既有断点（{old_ckpt.name} 不存在）")


def cmd_join_parts(a):
    """Combine checked part outputs into one module output file."""
    combined = []
    for p in a.parts:
        combined.extend(_normalize_module_output(load(p), p))
    Path(a.out).write_text(json.dumps(combined, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[join-parts] {len(a.parts)} 份 -> {len(combined)} 条 -> {a.out}")


def cmd_ckpt_append(a):
    """Validate and append one check entry to a JSONL checkpoint."""
    p = Path(a.file)
    entry = _normalize_module_output([json.loads(a.entry)], p)[0]
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[ckpt-append] id={entry['id']} -> {p}")


def cmd_ckpt_finalize(a):
    """全部段判完后调一次：把 ckpt.jsonl 去重(同 id 取最后一次出现，处理断点重叠)、
    按 id 排序，合并成标准 JSON 数组。"""
    p = Path(a.jsonl)
    by_id = {}
    line_count = 0
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            line_count += 1
            e = _normalize_module_output([json.loads(line)], p)[0]
            by_id[e["id"]] = e
    out = [by_id[i] for i in sorted(by_id)]
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[ckpt-finalize] {len(out)} 条（去重前 {line_count}）-> {a.out}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("split")
    s.add_argument("--state", required=True)
    s.add_argument("--errors", required=True)
    s.add_argument("--terms", default=None)
    s.add_argument("--outdir", required=True)
    s.add_argument("--size", type=int, default=100)
    s.add_argument("--char-budget", type=int, default=0,
                   help="按源文和译文总字符数分块；0 表示固定按 --size 分块，--size 始终是段数上限")
    s.set_defaults(fn=cmd_split)
    m = sub.add_parser("merge")
    m.add_argument("--state", required=True)
    m.add_argument("--errors", required=True)
    m.add_argument("--outdir", required=True)
    m.add_argument("--out", required=True)
    m.set_defaults(fn=cmd_merge)
    mc = sub.add_parser("merge-checks")
    mc.add_argument("--job", required=True)
    mc.set_defaults(fn=cmd_merge_checks)
    vc = sub.add_parser("validate-checks")
    vc.add_argument("--job", required=True)
    vc.set_defaults(fn=cmd_validate_checks)
    rc = sub.add_parser("reconcile")
    rc.add_argument("--job", required=True)
    rc.set_defaults(fn=cmd_reconcile)
    sh = sub.add_parser("split-half")
    sh.add_argument("--job", required=True)
    sh.add_argument("--chunk", required=True, help="原 chunk 序号（如 0、3）")
    sh.add_argument("--module", default=None)
    sh.set_defaults(fn=cmd_split_half)
    jp = sub.add_parser("join-parts")
    jp.add_argument("--parts", required=True, nargs="+", help="两个 part 的输出文件路径")
    jp.add_argument("--out", required=True)
    jp.set_defaults(fn=cmd_join_parts)
    ca = sub.add_parser("ckpt-append")
    ca.add_argument("--file", required=True, help="ckpt jsonl 路径")
    ca.add_argument("--entry", required=True, help="JSON object {id,issues}")
    ca.set_defaults(fn=cmd_ckpt_append)
    cf = sub.add_parser("ckpt-finalize")    # 全部段判完后调1次，去重+排序+转成正式 JSON 数组
    cf.add_argument("--jsonl", required=True)
    cf.add_argument("--out", required=True)
    cf.set_defaults(fn=cmd_ckpt_finalize)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
