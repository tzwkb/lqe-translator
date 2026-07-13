#!/usr/bin/env python3
"""MasterTB self-review prep + audit pipeline for LQE.

A glossary/TB audited as the work product (its own target translations are the
thing under review, there is no external TB to diff against). Reproduces the
proven 2024-06 ROCO flow: header-offset clean, EN/category/gender/definition
context injection, a single atomic-term rubric run in TWO independent passes
(p1 U p2 high recall, per the "single judge under-reports ~3x" lesson), plus a
cross-term consistency index that the rubric is told NOT to judge locally.

Subcommands
  prep    raw TB xlsx -> clean_input.xlsx + context.json + consistency.json + missing_th.xlsx
  chunks  state.json + context.json + errors_precheck.json -> chunks/chunk_NN.json + _RUBRIC.md
  merge   chunks/chunk_NN.out.json (+ .p2.json) + consistency.json -> errors.json (standard schema)
  report  state.json + errors.json + context.json -> <label>_审校建议.xlsx

Column mapping is by header name (auto-locates the real header row containing
"术语 ZHCN"); the per-language TH block (TH / TH Comment / status) is resolved
POSITIONALLY because the status header repeats for every language.
"""
import argparse
import json
import re
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

import openpyxl

from lqe_corrections import build_results, normalize_check_entries

ZW = {0x200b: None, 0x200c: None, 0x200d: None, 0xfeff: None, 0x2060: None}
SRC_HDR = "术语 ZHCN"
STATUS_HDRS = {"术语状态 status", "status", "术语状态"}
CJK = re.compile(r"[一-鿿㐀-䶿]")
THAI = re.compile(r"[฀-๿]")

CTX_FIELDS = ("zhcn", "en", "definition", "category", "gender", "former",
              "th", "th_comment", "th_status", "scope")


def cl(v) -> str:
    return "" if v is None else str(v).translate(ZW).strip()


def find_header_row(rows):
    for i, r in enumerate(rows):
        if any(cl(c) == SRC_HDR for c in r):
            return i
    sys.exit(f"[err] header row containing {SRC_HDR!r} not found")


def col_map(hdr):
    def need(name):
        if name not in hdr:
            sys.exit(f"[err] column {name!r} not found; headers={hdr}")
        return hdr.index(name)
    m = {
        "src": need(SRC_HDR), "tgt": need("TH"), "en": need("EN"),
        "cat": need("术语类别 Category"), "scope": need("剧情范围"),
        "def": need("术语定义 Definition"), "gender": need("性別 Gender"),
        "former": need("曾用名"),
    }
    m["tgt_comment"] = m["tgt"] + 1
    m["tgt_status"] = next((j for j, c in enumerate(hdr)
                            if j > m["tgt"] and c.lower() in STATUS_HDRS), None)
    return m


def load_rows(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    return rows


# ---------------------------------------------------------------- prep
def cmd_prep(a):
    rows = load_rows(a.input)
    h = find_header_row(rows)
    hdr = [cl(c) for c in rows[h]]
    m = col_map(hdr)
    job = Path(a.job_dir)
    job.mkdir(parents=True, exist_ok=True)

    audit, missing = [], []          # audit = filled TH, in order
    scope_ff = ""                    # forward-fill 剧情范围 (merged section marker)
    for r in rows[h + 1:]:
        g = lambda i: (cl(r[i]) if i is not None and i < len(r) else "")
        src = g(m["src"])
        sc = g(m["scope"])
        if sc:
            scope_ff = sc
        if not src or src == SRC_HDR:
            continue
        rec = {
            "zhcn": src, "en": g(m["en"]), "definition": g(m["def"]),
            "category": g(m["cat"]), "gender": g(m["gender"]),
            "former": g(m["former"]), "th": g(m["tgt"]),
            "th_comment": g(m["tgt_comment"]), "th_status": g(m["tgt_status"]),
            "scope": scope_ff,
        }
        (audit if rec["th"] else missing).append(rec)

    # context.json keyed by sequential id == lqe_io.read row order on clean_input
    ctx = OrderedDict((str(i), {k: rec[k] for k in CTX_FIELDS})
                      for i, rec in enumerate(audit))
    (job / "context.json").write_text(
        json.dumps(ctx, ensure_ascii=False, indent=1), encoding="utf-8")

    # clean_input.xlsx: real header at row 1 + audit rows (src + TH only is
    # enough for read; full structure kept so export can restore the TB).
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([SRC_HDR, "TH"])
    for rec in audit:
        ws.append([rec["zhcn"], rec["th"]])
    wb.save(job / "clean_input.xlsx")

    # missing_th.xlsx (record only; excluded from audit)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["术语 ZHCN", "EN", "Category", "Definition", "th_status"])
    for rec in missing:
        ws.append([rec["zhcn"], rec["en"], rec["category"],
                   rec["definition"], rec["th_status"]])
    wb.save(job / "missing_th.xlsx")

    # consistency.json (cross-term; rubric is told NOT to judge this locally)
    by_src, by_th = defaultdict(list), defaultdict(list)
    noth, cjk = [], []
    for i, rec in enumerate(audit):
        by_src[rec["zhcn"]].append({"id": i, "th": rec["th"], "en": rec["en"]})
        by_th[rec["th"]].append({"id": i, "zhcn": rec["zhcn"]})
        if not THAI.search(rec["th"]):
            noth.append({"id": i, "zhcn": rec["zhcn"], "th": rec["th"]})
        if CJK.search(rec["th"]):
            cjk.append({"id": i, "zhcn": rec["zhcn"], "th": rec["th"]})
    inc_src = {s: v for s, v in by_src.items()
              if len({x["th"] for x in v}) > 1}
    multi = {t: v for t, v in by_th.items()
            if len({x["zhcn"] for x in v}) > 1}
    cons = {
        "summary": {
            "total_filled": len(audit), "total_missing_th": len(missing),
            "src_groups_inconsistent_th": len(inc_src),
            "th_groups_multiple_src": len(multi),
            "th_no_thai_char": len(noth), "th_contains_cjk": len(cjk),
        },
        "inconsistent_same_src": inc_src,
        "same_th_multi_src": multi,
        "th_no_thai_char": noth,
        "th_contains_cjk": cjk,
    }
    (job / "consistency.json").write_text(
        json.dumps(cons, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"[ok] audit(filled TH)={len(audit)}  missing TH={len(missing)}")
    print(f"     clean_input.xlsx / context.json / missing_th.xlsx / consistency.json -> {job}")
    print(f"     consistency: {cons['summary']}")


# ---------------------------------------------------------------- chunks
RUBRIC = """\
# 泰语术语表审校规则（中→泰 Master TB 自审）

你是泰语本地化 QA。审一个**术语表**（原子词条，非句子）的 TH 译文。先读 `../background.md`（题材/受众/语气）、`../lang_notes.md`（泰语关注点：RTGS 音译、声调符号、性别语尾、敬语层、佛历等）、`../adjudications.md`（客户裁决，优先于通用规则），并速览 `../sg.txt` 的音译/标点规范——题材与语域口吻一律以这些注入文件为准。

## 输入
chunk JSON 的 `terms[]`，每条字段：
- `zhcn` 中文术语 = **含义判定的唯一真源**
- `en` 英文译名 = **强参考**，专名音译的罗马化锚点（TH 应与 EN 读音对应）；EN 为空时仅以 ZHCN 判
- `definition` 定义 / `category` 类别 / `gender` 性别 = 释义与消歧上下文
- `former` 曾用名（一般忽略）/ `th_comment` 译注
- `th` = **待审的泰语译文**
- `auto_flags` = 确定性 pre-check 已标类别（确认或细化，别盲目重复；词内数字/标点类易假阳，判不成立就丢）

## 逐条判定（每个 term 都要过一遍）
1. **Mistranslation [Major]**：TH 含义 ≠ ZHCN。描述性词条核对语义。
2. **Omission / Addition [Major]**：多部件中文术语，TH 漏掉或多加有意义成分。
3. **Untranslated [Major]**：TH 照抄中文/残留中文；或该出泰文却留英文（例外：既定品牌名如 "Roco Kingdom" 可保留拉丁字母）。
4. **专名音译**（Named NPC / Creature / 地名等）：TH 应与目标读音一致，**以 EN 为罗马化锚点**。报错若 TH 读音明显不符 / 泰文元音辅音错 / 声调符号位置错 / 混用文字系统。遵 RTGS 或 TB 既定译名，避免邻近竞品官方译名污染。整名认不出=Major（归 Mistranslation；文化负载名→Culture specific reference）；单声调/元音小误=Minor。
5. **Grammar / Spelling [Minor，改义则 Major]**：泰文拼写错、声调符号缺/错、元音位置、sara/辅音错。
6. **Unidiomatic / Audience appropriateness**：语域是否合题材（见 background）——粗俗/成人词=Major；生硬/过度正式=Minor。
7. **Culture specific reference**：文化负载概念译错。
8. **Punctuation [Minor]**：按 sg.txt/lang_notes——禁连续同种 !!/??；省略号用三个英文点 `...` 不用 `…`。

## 不要报
- 可接受的风格变体、纯偏好；有意保留的拉丁品牌名；**跨词条一致性**（全局另算，本块别报同源异译）；EN/定义列本身（只审 TH）。
- ZHCN 与 EN 含义冲突时，**以 ZHCN 为准**判 TH。

## 严重度
Major=含义/品牌/功能/专名认不出/粗俗；Minor=表面（单声调符号、轻微拼写、标点、略生硬）。**Untranslated 永远 Major**。Major/Minor 拿不准 → 取 Major。

## 输出
只写**有问题**的词条（issues 非空），UTF-8 JSON 写到指定 out 文件：
```json
{"chunk": NN, "reviewed_first": F, "reviewed_last": L, "reviewed_count": N,
 "findings": [
   {"id": 123,
    "issues": [{"category": "Mistranslation", "severity": "Major",
                "comment": "中文'X' / EN'Y' / 泰译'Z'：说明问题",
                "needs_confirmation": false,
                "edit": {"from": "原 TH", "to": "修正 TH", "evidence": null}}]}
 ]}
```
- `comment` 用中文，引用 ZHCN/EN/TH 片段。确定修正时 `edit.from` 必须是当前完整 TH，`edit.to` 是修正后的完整 TH。
- 无把握时写 `needs_confirmation: true, edit: null`，不得输出整句 `corrected`。
- **覆盖**：`reviewed_first/last` = chunk 的 `id_first/id_last`，`reviewed_count` = chunk 的 `count`，逐条过完不可截断。
- 干净术语表应只有少量 findings——**重质不重量**，但真实的音译/正字/含义错必须抓出。
"""


_NAME_CATS = {"Named NPC", "Creature Species", "Settlement", "Wilderness",
              "Macro Region", "Administrative Region", "Urban Area", "Functional Area"}
_DESC_MARK = ("的", "们")  # descriptive-phrase markers


def _kind(category, zhcn):
    """name=专名(走 N 音译); desc=描述/词义(走 A/R)。Creature Individual 多为描述
    短语，按内容细分(含 的/们 或长度>6→desc)；存疑偏 desc(多一道 A/R 覆盖)。"""
    if category in _NAME_CATS:
        return "name"
    if category == "Creature Individual":
        return "desc" if (any(m in zhcn for m in _DESC_MARK) or len(zhcn) > 6) else "name"
    return "desc"


def cmd_chunks(a):
    job = Path(a.job_dir)
    state = json.loads((job / "state.json").read_text("utf-8"))
    ctx = json.loads((job / "context.json").read_text("utf-8"))
    segs = state["segments"]
    if len(segs) != len(ctx):
        sys.exit(f"[err] state segs {len(segs)} != context {len(ctx)}; re-run read on clean_input")
    # alignment guard: source/target must match context by id
    for s in segs:
        c = ctx[str(s["id"])]
        if c["zhcn"] != s["source"] or c["th"] != s["target"]:
            sys.exit(f"[err] id {s['id']} misaligned: state({s['source']!r}/{s['target']!r}) "
                     f"vs ctx({c['zhcn']!r}/{c['th']!r})")
    # auto_flags from pre-check
    flags = defaultdict(list)
    pc = job / "errors_precheck.json"
    if pc.exists():
        for e in json.loads(pc.read_text("utf-8")):
            cats = sorted({x["category"] for x in e.get("errors", [])})
            if cats:
                flags[e["id"]] = cats
    out = job / "chunks"
    out.mkdir(exist_ok=True)
    size = a.size
    n = (len(segs) + size - 1) // size
    for ci in range(n):
        block = segs[ci * size:(ci + 1) * size]
        terms = []
        for s in block:
            c = ctx[str(s["id"])]
            terms.append({
                "id": s["id"], "zhcn": c["zhcn"], "en": c["en"],
                "definition": c["definition"], "category": c["category"],
                "gender": c["gender"], "former": c["former"],
                "th": c["th"], "th_comment": c["th_comment"],
                "kind": _kind(c["category"], c["zhcn"]),
                "auto_flags": flags.get(s["id"], []),
            })
        doc = {"chunk": ci, "count": len(terms),
               "id_first": block[0]["id"], "id_last": block[-1]["id"],
               "terms": terms}
        (out / f"chunk_{ci:02d}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[ok] {n} chunks (size {size}, 含 kind 路由) -> {out}")
    print(f"     派 lens 按 kind 门控(N:name / A,R:desc / T,G:全部) -> chunk_NN.<L>.json")
    print(f"     再 lqe_chunk.py merge-lenses -> chunk_NN.out.json -> mastertb_prep merge")


# ---------------------------------------------------------------- merge
def _load_findings(path):
    if not path.exists():
        return {}
    doc = json.loads(path.read_text("utf-8"))
    entries = normalize_check_entries(doc.get("findings", []), label=str(path))
    return {entry["id"]: entry for entry in entries}


def _ekey(e):
    return (e.get("category", ""), e.get("severity", ""))


def cmd_merge(a):
    job = Path(a.job_dir)
    state = json.loads((job / "state.json").read_text("utf-8"))
    ids = [s["id"] for s in state["segments"]]
    out = job / "chunks"
    nchunks = sum(1 for p in out.glob("chunk_*.json")
                  if re.fullmatch(r"chunk_\d+\.json", p.name))  # base chunks only, exclude .out/.p2

    merged = {i: {"id": i, "issues": []} for i in ids}
    for ci in range(nchunks):
        p1 = _load_findings(out / f"chunk_{ci:02d}.out.json")
        p2 = _load_findings(out / f"chunk_{ci:02d}.p2.json")
        for sid in set(p1) | set(p2):
            f1, f2 = p1.get(sid), p2.get(sid)
            errs = OrderedDict()
            for f in (f1, f2):
                if not f:
                    continue
                for e in f.get("issues", []):
                    k = _ekey(e)
                    cand = dict(e)
                    if k not in errs or len(cand.get("comment", "")) > len(errs[k].get("comment", "")):
                        errs[k] = cand
            if sid in merged and errs:
                merged[sid]["issues"] = list(errs.values())

    # fold cross-term consistency (global; not judged locally by the rubric)
    cons_p = job / "consistency.json"
    folded = 0
    if cons_p.exists() and not a.no_consistency:
        cons = json.loads(cons_p.read_text("utf-8"))
        for src, members in cons.get("inconsistent_same_src", {}).items():
            variants = sorted({x["th"] for x in members})
            for x in members:
                sid = x["id"]
                if sid in merged and not any(e.get("category") == "Inconsistency"
                                             for e in merged[sid]["issues"]):
                    merged[sid]["issues"].append({
                        "category": "Inconsistency", "severity": "Minor",
                        "comment": f"[一致性] 同源 '{src}' 跨词条出现多种泰译 {variants}；需统一。",
                        "needs_confirmation": False,
                        "edit": None,
                    })
                    folded += 1

    checks = [merged[i] for i in ids]
    errors = build_results(state["segments"], checks)
    (job / "errors.json").write_text(
        json.dumps(errors, ensure_ascii=False, indent=1), encoding="utf-8")
    flagged = sum(1 for e in errors if e["errors"])
    nerr = sum(len(e["errors"]) for e in errors)
    print(f"[ok] merged lenses over {nchunks} chunks -> errors.json")
    print(f"     flagged segments={flagged}/{len(ids)}  total errors={nerr}  consistency folded={folded}")
    # --- recall gate (enforced): all APPLICABLE lens files present per chunk ---
    def _applicable(ci):
        cf = out / f"chunk_{ci:02d}.json"
        kinds = set()
        if cf.exists():
            kinds = {t.get("kind", "desc")
                     for t in json.loads(cf.read_text("utf-8")).get("terms", [])}
        req = {"T", "G"}
        if "name" in kinds:
            req.add("N")
        if "desc" in kinds:
            req |= {"A", "R"}
        return req
    incomplete = []
    for ci in range(nchunks):
        req = _applicable(ci)
        have = {L for L in req if (out / f"chunk_{ci:02d}.{L}.json").exists()}
        if have != req:
            incomplete.append({"chunk": ci, "missing": sorted(req - have)})
    degraded = bool(incomplete)
    status = {
        "n_chunks": nchunks,
        "lenses_complete": not degraded,
        "verdict_allowed": not degraded,
        "incomplete_chunks": incomplete,
        "note": ("缺适用 lens：低召回降级，calc 的 PASS/FAIL 不可信，补齐缺失 lens 重 merge"
                 if degraded else "各 chunk 适用 lens(N/A/G/R/T) 齐，可出裁决"),
    }
    (job / "recall_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    if degraded:
        bar = "!" * 64
        print("  " + bar)
        print(f"  ⚠ 降级运行：{len(incomplete)}/{nchunks} 块缺适用 lens(见 recall_status.json)。")
        print("  ⚠ 分数只是【临时下限】，禁作 PASS/FAIL 裁决。")
        print("  ⚠ 补齐缺失 lens 重 merge-lenses + merge；见 SKILL.md step 3「降级不出裁决」。")
        print("  " + bar)


# ---------------------------------------------------------------- report
SEV_ORDER = {"Critical": 0, "Major": 1, "Minor": 2, "Neutral": 3}


def cmd_report(a):
    job = Path(a.job_dir)
    state = json.loads((job / "state.json").read_text("utf-8"))
    errors = json.loads((job / "errors.json").read_text("utf-8"))
    ctx = json.loads((job / "context.json").read_text("utf-8"))
    emap = {e["id"]: e for e in errors}

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "审校建议"
    ws.append(["id", "剧情范围", "类别", "中文 ZHCN", "EN", "性别", "定义",
               "原泰译 TH", "建议译文", "错误类别", "严重度", "置信", "说明", "TH状态"])
    rows = []
    for e in errors:
        if not e["errors"]:
            continue
        c = ctx.get(str(e["id"]), {})
        worst = min(e["errors"], key=lambda x: SEV_ORDER.get(x.get("severity"), 9))
        rows.append((SEV_ORDER.get(worst.get("severity"), 9), e["id"], e, c))
    rows.sort(key=lambda t: (t[0], t[1]))
    for _, sid, e, c in rows:
        cats = " / ".join(x.get("category", "") for x in e["errors"])
        sevs = " / ".join(x.get("severity", "") for x in e["errors"])
        cons = " / ".join(x.get("confidence", "") for x in e["errors"])
        cmts = "\n".join(f"[{x.get('severity')}] {x.get('comment','')}" for x in e["errors"])
        ws.append([sid, c.get("scope", ""), c.get("category", ""), c.get("zhcn", ""),
                   c.get("en", ""), c.get("gender", ""), c.get("definition", ""),
                   c.get("th", ""), e.get("corrected") or "", cats, sevs, cons, cmts,
                   c.get("th_status", "")])
    # summary sheet — stamp recall gate first so the deliverable carries the verdict status
    sm = wb.create_sheet("汇总")
    rs_p = job / "recall_status.json"
    rs = json.loads(rs_p.read_text("utf-8")) if rs_p.exists() else {}
    if rs.get("verdict_allowed") is False:
        nbad = len(rs.get("incomplete_chunks", []))
        sm.append(["⚠ 召回状态", f"降级·{nbad}/{rs.get('n_chunks')} 块缺适用 lens"])
        sm.append(["⚠ 裁决", "临时下限·禁作 PASS/FAIL·补齐 lens 重跑（见 SKILL.md step3）"])
        sm.append([])
    cat_ct = Counter()
    sev_ct = Counter()
    for e in errors:
        for x in e["errors"]:
            cat_ct[x.get("category", "")] += 1
            sev_ct[x.get("severity", "")] += 1
    sm.append(["指标", "值"])
    sm.append(["审校词条总数", len(state["segments"])])
    sm.append(["有问题词条数", len(rows)])
    sm.append(["错误总数", sum(cat_ct.values())])
    sm.append([])
    sm.append(["严重度", "数量"])
    for k in ("Critical", "Major", "Minor", "Neutral"):
        if sev_ct.get(k):
            sm.append([k, sev_ct[k]])
    sm.append([])
    sm.append(["错误类别", "数量"])
    for k, v in cat_ct.most_common():
        sm.append([k, v])

    label = a.label or job.name
    outp = job / f"{label}_审校建议.xlsx"
    wb.save(outp)
    print(f"[ok] {len(rows)} flagged terms -> {outp}")


# ---------------------------------------------------------------- view
def cmd_view(a):
    """Compact per-chunk text views for inline judging when subagents are
    unavailable (rate/session limit). ~10x denser than raw chunk JSON so the
    main context can read all chunks without blowing the window. Single-judge
    inline is a LOW-RECALL floor, not a substitute for the lens 2-pass."""
    job = Path(a.job_dir)
    ctx = json.loads((job / "context.json").read_text("utf-8"))
    out = job / "chunks" / "views"
    out.mkdir(parents=True, exist_ok=True)

    def one(s, n=0):
        s = ("" if s is None else str(s)).replace("\n", " / ").strip()
        return s[:n] if n else s

    ids = sorted(int(k) for k in ctx)
    size = a.size
    n = (len(ids) + size - 1) // size
    for ci in range(n):
        block = ids[ci * size:(ci + 1) * size]
        lines = ["id\tcat\tg\tzhcn\ten\tdef\tth"]
        for i in block:
            c = ctx[str(i)]
            lines.append("\t".join([str(i), one(c["category"]), one(c["gender"]),
                one(c["zhcn"]), one(c["en"]), one(c["definition"], 60), one(c["th"])]))
        (out / f"chunk_{ci:02d}.view.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[ok] {n} compact views (size {size}) -> {out}")
    print("     inline 兜底: 逐块 Read view + _RUBRIC.md 判, 写回 chunk_NN.out.json")
    print("     ⚠ 单判=低召回下限, 非 lens 双遍替代; 额度恢复后须补遍, 降级运行不报 PASS/FAIL")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prep"); p.add_argument("--input", required=True); p.add_argument("--job-dir", required=True); p.set_defaults(fn=cmd_prep)
    p = sub.add_parser("chunks"); p.add_argument("--job-dir", required=True); p.add_argument("--size", type=int, default=300); p.set_defaults(fn=cmd_chunks)
    p = sub.add_parser("merge"); p.add_argument("--job-dir", required=True); p.add_argument("--no-consistency", action="store_true"); p.set_defaults(fn=cmd_merge)
    p = sub.add_parser("report"); p.add_argument("--job-dir", required=True); p.add_argument("--label", default=None); p.set_defaults(fn=cmd_report)
    p = sub.add_parser("view"); p.add_argument("--job-dir", required=True); p.add_argument("--size", type=int, default=300); p.set_defaults(fn=cmd_view)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
