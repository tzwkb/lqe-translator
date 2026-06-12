"""
LQE I/O utilities.

Subcommands:
  read          Excel → state.json（独立使用）
  from-aipe     AIPE CSV + 术语/SG API → state.json
  pre-check     确定性错误自动检测（标点/Markup/术语/长度等）
  apply-fixes   errors.json 的 corrected 写回 state.json
  write         state.json + errors.json → *_lqe.xlsx
  ingest-corpus 修正译文回流 AIPE 语料库（接口待确认，暂为 stub）
"""
import argparse
import csv
import io
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter

from lqe_engine import (
    read_json,
    CATEGORY_ORDER as _ALL_CATS, CATEGORY_PARENT as _PARENT,
    VALID_CATEGORIES as _VALID_CATEGORIES, VALID_SEVERITIES as _VALID_SEVERITIES,
    apply_severity, load_terms as _load_terms, load_style_guide as _load_sg,
    raw_points, weighted_points,
)


# ── read ──────────────────────────────────────────────────────────────────────

_SRC_KEYS = {"source", "zh", "src", "原文", "中文_cn", "中文", "chinese", "chinese_prc", "zh_cn", "zh-cn", "简中", "中文简体", "source text"}
_TGT_KEYS = {"target", "en", "tgt", "译文", "en_us", "english", "翻译", "英文", "thai", "th", "泰语", "泰文", "target text"}
_ZW_TABLE = {ord(c): None for c in "​‌‍﻿"}


def _clean_terms(items: list) -> list:
    out = []
    for t in items:
        s = str(t.get("source", "")).translate(_ZW_TABLE).strip()
        g = str(t.get("target", "")).translate(_ZW_TABLE).strip()
        if s and g:
            item = {"source": s, "target": g}
            if t.get("status"):
                item["status"] = str(t["status"]).strip()
            out.append(item)
    return out
_MAXLEN_KEYS = {"maxlen", "max_len", "max length", "maxlength", "max_length",
                "char_limit", "charlimit", "limit", "width", "ui_max",
                "限长", "字符上限", "长度上限", "字数上限"}


def _parse_maxlen(val) -> int | None:
    if val is None or str(val).strip() == "":
        return None
    try:
        n = int(float(str(val).strip()))
        return n if n > 0 else None
    except ValueError:
        return None


def _pick_col(keys: list, candidates: set) -> str | None:
    for k in keys:
        if k and k.strip().lower() in candidates:
            return k
    return None


def _load_terminology(path: str) -> list:
    p = Path(path)
    if not p.exists():
        print(f"[warn] terminology file not found: {path}", file=sys.stderr)
        return []
    suffix = p.suffix.lower()

    if suffix == ".json":
        data = read_json(p)
        return _clean_terms(data if isinstance(data, list) else data.get("items", []))

    if suffix in (".csv", ".tsv"):
        delim = "\t" if suffix == ".tsv" else ","
        raw = p.read_bytes().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(raw), delimiter=delim)
        rows = list(reader)
        if not rows:
            return []
        keys = [k for k in rows[0].keys() if k is not None]
        src_key = _pick_col(keys, _SRC_KEYS) or keys[0]
        tgt_key = _pick_col(keys, _TGT_KEYS) or (keys[1] if len(keys) > 1 else keys[0])
        return _clean_terms([{"source": r.get(src_key, ""), "target": r.get(tgt_key, "")} for r in rows if r.get(src_key)])

    if suffix in (".xlsx", ".xls"):
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.active
            raw_headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
            keys = [str(h).strip() if h is not None else None for h in raw_headers]
            src_key = _pick_col([k for k in keys if k], _SRC_KEYS) or (keys[0] if keys else None)
            tgt_key = _pick_col([k for k in keys if k], _TGT_KEYS) or (keys[1] if len(keys) > 1 else None)
            if not src_key or not tgt_key:
                print(f"[warn] cannot detect source/target columns in {path}, headers={keys}", file=sys.stderr)
                return []
            si = keys.index(src_key)
            ti = keys.index(tgt_key)
            result = []
            for row in ws.iter_rows(min_row=2, values_only=True):
                src_val = row[si] if si < len(row) else None
                tgt_val = row[ti] if ti < len(row) else None
                if src_val:
                    result.append({"source": str(src_val), "target": str(tgt_val or "")})
        finally:
            wb.close()
        return _clean_terms(result)

    print(f"[warn] unsupported terminology format: {suffix}", file=sys.stderr)
    return []


def _load_project(name_or_path: str) -> dict:
    p = Path(name_or_path)
    if "/" not in str(name_or_path) and not p.suffix:
        p = Path("projects") / name_or_path
    if p.is_dir():
        p = p / "profile.json"
    if not p.exists():
        print(f"[ERROR] project profile not found: {p}", file=sys.stderr)
        sys.exit(1)
    prof = read_json(p)
    prof["_dir"] = str(p.parent.resolve())
    return prof


def _project_path(prof: dict, val: str) -> str:
    if not val:
        return ""
    q = Path(val)
    return str(q if q.is_absolute() else Path(prof["_dir"]) / q)


# 语言层：languages/<lang>.json（skill 根，锚定脚本位置而非 CWD）。
# 仅放语言学事实型默认（不可能被项目 SG 推翻的：分词方式、句号体系、数词映射）；
# 风格取向（em_dash/省略号样式等）一律留项目 checks.json。
# 合并顺序：内置默认 < 语言层 < 项目 checks.json < CLI 显式参数。
_LANG_DIR = Path(__file__).resolve().parent.parent / "languages"


def _target_lang(state_or_pair) -> str:
    if isinstance(state_or_pair, dict):
        lang = state_or_pair.get("target_lang", "")
        pair = state_or_pair.get("language_pair", "")
    else:
        lang, pair = "", state_or_pair or ""
    if not lang and pair and "-" in pair:
        lang = pair.rsplit("-", 1)[-1]
    return lang.strip().lower()


def _load_lang(lang: str) -> dict:
    if not lang:
        return {}
    p = _LANG_DIR / f"{lang}.json"
    return read_json(p) if p.exists() else {}


def _load_style_guide(path: str) -> str:
    p = Path(path)
    if not p.exists():
        print(f"[warn] style-guide file not found: {path}", file=sys.stderr)
        return ""
    suffix = p.suffix.lower()
    if suffix == ".docx":
        import docx
        doc = docx.Document(str(p))
        lines = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            style = para.style.name
            if style.startswith("Heading 1"):
                lines.append(f"\n# {text}")
            elif style.startswith("Heading 2"):
                lines.append(f"\n## {text}")
            elif style.startswith("Heading 3"):
                lines.append(f"\n### {text}")
            else:
                lines.append(text)
        return "\n".join(lines)
    if suffix in (".xlsx", ".xlsm"):
        wb = openpyxl.load_workbook(str(p), data_only=True)
        out = []
        for ws in wb.worksheets:
            rows = []
            for r in ws.iter_rows(values_only=True):
                cells = ["" if c is None else str(c).strip() for c in r]
                if any(cells):
                    rows.append(cells)
            if len(rows) < 2:
                continue
            header, data = rows[0], rows[1:]
            out.append(f"\n# {ws.title}")
            category = ""
            for r in data:
                title, body = "", []
                for i, v in enumerate(r):
                    h = header[i] if i < len(header) else ""
                    if i == 0 and not h:
                        if v:
                            category = v
                        continue
                    if not v:
                        continue
                    if not title:
                        title = v
                    else:
                        body.append(f"[{h}] {v}" if h else v)
                if not title and not body:
                    continue
                out.append(f"## {category} — {title}" if category else f"## {title}")
                out.extend(body)
        return "\n".join(out)
    return p.read_text(encoding="utf-8")


def cmd_read(args):
    prof = _load_project(args.project) if getattr(args, "project", None) else None
    if prof:
        if not args.style_guide and prof.get("style_guide"):
            args.style_guide = _project_path(prof, prof["style_guide"])
        if not args.terminology and prof.get("terminology"):
            args.terminology = _project_path(prof, prof["terminology"])
        print(f"[lqe_io] project: {prof.get('name', '?')} ({prof.get('language_pair', '?')})")

    wb = openpyxl.load_workbook(args.input)
    ws = wb.active

    no_header = getattr(args, "no_header", False)

    if no_header:
        # 列参数为整数索引（0-based）
        try:
            si = int(args.source_col)
            ti = int(args.target_col)
        except ValueError:
            print("[ERROR] --no-header mode requires integer column indices for --source-col and --target-col", file=sys.stderr)
            sys.exit(1)
        default_headers = ["Key", "Source", "Target", "Status", "Comment", "Scope", "File", "Reviewer Note"]
        headers = [default_headers[j] if j < len(default_headers) else f"col{j}" for j in range(ws.max_column)]
        start_row = 1
    else:
        headers = [cell.value for cell in ws[1]]
        for col in [args.source_col, args.target_col]:
            if col not in headers:
                print(f"[ERROR] Column '{col}' not found. Available: {headers}", file=sys.stderr)
                sys.exit(1)
        si = headers.index(args.source_col)
        ti = headers.index(args.target_col)
        start_row = 2

    # R3: 自动识别 max-length 列（UI 字段宽度上限），用于逐元素截断检查
    mi = None
    for idx, h in enumerate(headers):
        if h is not None and str(h).strip().lower() in _MAXLEN_KEYS:
            mi = idx
            break
    if mi is not None:
        print(f"[lqe_io] max-length column detected: '{headers[mi]}' (col {mi})")

    segments, rows_raw = [], []
    for i, row in enumerate(ws.iter_rows(min_row=start_row, values_only=True)):
        if any(c is not None for c in row):
            segments.append({
                "id": i,
                "source": str(row[si] if si < len(row) and row[si] is not None else ""),
                "target": str(row[ti] if ti < len(row) and row[ti] is not None else ""),
                "corrected": None,
                "content_type": None,
                "max_len": _parse_maxlen(row[mi]) if mi is not None and mi < len(row) else None,
                "iter": 0,
            })
            rows_raw.append(list(row))

    if not segments:
        print("[ERROR] No data rows found.", file=sys.stderr)
        sys.exit(1)

    out_path  = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    job_dir   = out_path.parent

    # ── Style Guide → 独立文本文件 ─────────────────────────────────────────
    sg_path = ""
    if args.style_guide:
        sg_text = _load_style_guide(args.style_guide)
        if sg_text:
            sg_file = job_dir / "sg.txt"
            sg_file.write_text(sg_text, encoding="utf-8")
            sg_path = str(sg_file)
            print(f"[lqe_io] style_guide: {len(sg_text)} chars → {sg_file}")

    # ── Terminology → 独立 JSON 文件 ──────────────────────────────────────
    terms_path = ""
    if args.terminology:
        terms = _load_terminology(args.terminology)
        lock_statuses = {str(s).lower() for s in (prof.get("lock_statuses") or [])} if prof else set()
        if terms and lock_statuses:
            n_locked = 0
            for t in terms:
                if str(t.get("status", "")).lower() in lock_statuses:
                    t["locked"] = True
                    n_locked += 1
            print(f"[lqe_io] locked terms: {n_locked} (lock_statuses: {sorted(lock_statuses)})")
        if terms:
            terms_file = job_dir / "terms.json"
            terms_file.write_text(json.dumps(terms, ensure_ascii=False, indent=2), encoding="utf-8")
            terms_path = str(terms_file)
            print(f"[lqe_io] terminology: {len(terms)} entries → {terms_file}")

    lang = (getattr(args, "target_lang", None) or "").strip().lower() \
        or _target_lang(prof.get("language_pair", "") if prof else "")
    lang_cfg = _load_lang(lang)
    if lang_cfg:
        print(f"[lqe_io] language defaults: languages/{lang}.json")

    basis = getattr(args, "wordcount_basis", None) \
        or (prof.get("wordcount_basis") if prof else None) \
        or lang_cfg.get("wordcount_basis") or "target-words"
    if basis == "source-chars":
        wordcount = sum(
            len(_RE_CJK.findall(s["source"])) + len(re.findall(r"[A-Za-z0-9]+", s["source"]))
            for s in segments
        )
    else:
        wordcount = sum(len(s["target"].split()) for s in segments)

    checks_path = adjud_path = ""
    if prof:
        cp = Path(_project_path(prof, prof.get("checks", "checks.json")))
        checks_path = str(cp) if cp.exists() else ""
        ap = Path(_project_path(prof, prof.get("adjudications", "adjudications.md")))
        adjud_path = str(ap) if ap.exists() else ""

    state = {
        "input_path": str(Path(args.input).resolve()),
        "source_col": args.source_col,
        "target_col": args.target_col,
        "headers": headers,
        "rows_raw": rows_raw,
        "aipe_url": None,
        "project": prof.get("name", "") if prof else "",
        "language_pair": prof.get("language_pair", "") if prof else "",
        "target_lang": lang,
        "checks_path": checks_path,
        "adjudications_path": adjud_path,
        "threshold": prof.get("threshold", 98) if prof else 98,
        "sg_path":    sg_path,
        "terms_path": terms_path,
        "terminology": [],
        "style_guide": "",
        "wordcount": wordcount,
        "wordcount_basis": basis,
        "iteration": 0,
        "segments": segments,
    }
    out_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[lqe_io] {len(segments)} segments → {args.out}  wordcount={state['wordcount']}")


# ── from-aipe ─────────────────────────────────────────────────────────────────

def cmd_from_aipe(args):
    import requests

    # 读取 AIPE 导出 CSV（BOM 安全）
    raw = Path(args.aipe_csv).read_bytes()
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    all_rows = list(reader)
    fieldnames = reader.fieldnames or []

    valid = [r for r in all_rows if r.get("status", "").strip().lower() != "error"]
    if not valid:
        print("[ERROR] No valid rows after filtering errors.", file=sys.stderr)
        sys.exit(1)

    def _row_maxlen(r):
        for k in ("max_length", "maxlen", "max_len", "char_limit", "limit"):
            if r.get(k):
                return _parse_maxlen(r.get(k))
        return None

    segments = [
        {
            "id": i,
            "source": r.get("source", ""),
            "target": r.get("translation", ""),
            "corrected": None,
            "content_type": r.get("content_type") or None,
            "max_len": _row_maxlen(r),
            "iter": 0,
        }
        for i, r in enumerate(valid)
    ]
    rows_raw = [[r.get(h, "") for h in fieldnames] for r in valid]

    # 拉术语表
    terminology = []
    try:
        resp = requests.get(
            f"{args.aipe_url.rstrip('/')}/api/v1/terminology",
            params={"limit": 1000}, timeout=10
        )
        if resp.ok:
            terminology = resp.json().get("items", [])
            print(f"[lqe_io] terminology: {len(terminology)} entries")
        else:
            print(f"[warn] terminology fetch {resp.status_code}", file=sys.stderr)
    except Exception as e:
        print(f"[warn] terminology fetch failed: {e}", file=sys.stderr)

    # 拉风格指南
    style_guide = ""
    try:
        resp = requests.get(
            f"{args.aipe_url.rstrip('/')}/api/v1/style-guide",
            params={"full": "true"}, timeout=10
        )
        if resp.ok:
            style_guide = resp.json().get("rules") or ""
            print(f"[lqe_io] style_guide: {len(style_guide)} chars")
        else:
            print(f"[warn] style-guide fetch {resp.status_code}", file=sys.stderr)
    except Exception as e:
        print(f"[warn] style-guide fetch failed: {e}", file=sys.stderr)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    job_dir  = out_path.parent

    sg_path = ""
    if style_guide:
        sg_file = job_dir / "sg.txt"
        sg_file.write_text(style_guide, encoding="utf-8")
        sg_path = str(sg_file)
    terms_path = ""
    if terminology:
        terms_file = job_dir / "terms.json"
        terms_file.write_text(json.dumps(terminology, ensure_ascii=False, indent=2), encoding="utf-8")
        terms_path = str(terms_file)

    state = {
        "input_path": str(Path(args.aipe_csv).resolve()),
        "source_col": "source",
        "target_col": "translation",
        "headers": list(fieldnames),
        "rows_raw": rows_raw,
        "aipe_url": args.aipe_url,
        "sg_path":    sg_path,
        "terms_path": terms_path,
        "terminology": [],
        "style_guide": "",
        "wordcount": sum(len(s["target"].split()) for s in segments),
        "iteration": 0,
        "segments": segments,
    }
    out_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    skipped = len(all_rows) - len(valid)
    print(f"[lqe_io] {len(segments)} segments (skipped {skipped} errors) → {args.out}  wordcount={state['wordcount']}")


# ── lookup-terms ──────────────────────────────────────────────────────────────

def cmd_lookup_terms(args):
    state = read_json(args.state)
    terms = _load_terms(state)
    if not terms:
        print("[lqe_io] no terminology available.", file=sys.stderr)
        return

    term_map = {t["source"].strip(): t["target"].strip() for t in terms if t.get("source")}

    segs = state["segments"]
    if args.ids:
        id_set = set(int(x) for x in args.ids.split(","))
        segs = [s for s in segs if s["id"] in id_set]

    # 逐段匹配，避免跨段拼接产生误命中
    hits: dict[str, dict] = {}  # term_source → {target, seg_ids}
    for seg in segs:
        src_text = seg["source"]
        for term_src, term_tgt in term_map.items():
            if term_src in src_text:
                if term_src not in hits:
                    hits[term_src] = {"target": term_tgt, "seg_ids": []}
                hits[term_src]["seg_ids"].append(seg["id"])

    if not hits:
        print("[lookup-terms] no terminology matches found.")
        return

    print(f"[lookup-terms] {len(hits)} matches:\n")
    for src, info in sorted(hits.items(), key=lambda x: -len(x[0])):
        seg_ids = info["seg_ids"]
        id_str = f"  (segs: {seg_ids})" if len(seg_ids) <= 5 else f"  ({len(seg_ids)} segs)"
        print(f"  {src} → {info['target']}{id_str}")


# ── apply-fixes ───────────────────────────────────────────────────────────────

def _locked_ids(args) -> set[int]:
    ids: set[int] = set()
    if getattr(args, "locked_ids", None):
        ids.update(int(x.strip()) for x in args.locked_ids.split(",") if x.strip())
    if getattr(args, "locked_file", None):
        data = read_json(args.locked_file)
        if isinstance(data, dict):
            data = data.get("locked_ids") or data.get("segments") or []
        for item in data:
            if isinstance(item, int):
                ids.add(item)
            elif isinstance(item, dict):
                sid = item.get("id", item.get("seg_id", item.get("segment_id")))
                if sid is not None:
                    ids.add(int(sid))
    return ids


def cmd_apply_fixes(args):
    state_path = Path(args.state)
    state = read_json(state_path)
    errors_data = read_json(args.errors)
    locked_ids = _locked_ids(args)

    seg_ids = {s["id"] for s in state["segments"]}
    issues = _validate_errors(errors_data, seg_ids)
    for msg in issues:
        print(f"[validate] {msg}")

    attempted = {e["id"]: e["corrected"] for e in errors_data if e.get("corrected")}
    corrections = {sid: text for sid, text in attempted.items() if sid not in locked_ids}
    skipped = [{"id": sid, "reason": "RAG_100_MATCH", "attempted": text} for sid, text in attempted.items() if sid in locked_ids]
    if not corrections and not skipped:
        print("[lqe_io] apply-fixes: no corrections found, state unchanged.")
        return

    cur_iter = state.get("iteration", 0)
    history = state.get("error_history", [])
    cur_entry = {
        "iteration": cur_iter,
        "score": float(args.score) if getattr(args, "score", None) else None,
        "errors": errors_data,
        "corrections_count": len(corrections),
        "locked_ids": sorted(locked_ids),
        "skipped_corrections": skipped,
    }
    history.append(cur_entry)
    state["error_history"] = history

    next_iter = cur_iter + 1
    for seg in state["segments"]:
        if seg["id"] in locked_ids:
            seg["locked"] = True
            seg["lock_reason"] = "RAG_100_MATCH"
            seg["corrected"] = None
            continue
        if seg["id"] in corrections:
            seg["corrected"] = corrections[seg["id"]]
            seg["iter"] = next_iter

    state["iteration"] = next_iter
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    archived = state_path.parent / f"errors_iter{cur_iter}.json"
    archived.write_text(json.dumps(errors_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[lqe_io] Applied {len(corrections)} corrections → iteration {next_iter}")
    print(f"[lqe_io] Errors archived → {archived}")

    src = Path(state["input_path"])
    iter_score = cur_entry.get("score") or 0.0
    threshold = getattr(args, "threshold", 98.0)
    iter_out = state_path.parent / (src.stem + f"_lqe_iter{cur_iter}.xlsx")
    _build_xlsx(state, [cur_entry], iter_score, threshold, iter_out)


# ── write ─────────────────────────────────────────────────────────────────────

_DARK_BLUE   = PatternFill("solid", fgColor="073763")
_LIGHT_BLUE  = PatternFill("solid", fgColor="CFE2F3")
_ORANGE      = PatternFill("solid", fgColor="FCE5CD")
_RED         = PatternFill("solid", fgColor="CC0000")
_GREEN       = PatternFill("solid", fgColor="006600")
_GREEN_LIGHT = PatternFill("solid", fgColor="D9EAD3")
_WHITE_FONT = Font(color="FFFFFF")
_BOLD       = Font(bold=True)
_CENTER     = Alignment(horizontal="center", vertical="center", wrap_text=True)
_LEFT_TOP   = Alignment(horizontal="left", vertical="top", wrap_text=True)
_LEFT_MID   = Alignment(horizontal="left", vertical="center")

def _validate_errors(errors_data: list, seg_ids: set) -> list[str]:
    issues = []
    for entry in errors_data:
        sid = entry.get("id")
        if sid not in seg_ids:
            issues.append(f"[seg {sid}] 未知 segment id")
            continue
        errs = entry.get("errors", [])
        if errs and entry.get("corrected") is None:
            issues.append(f"[seg {sid}] 有 {len(errs)} 条错误但 corrected=null")
        for e in errs:
            cat = e.get("category", "")
            sev = e.get("severity", "")
            if cat not in _VALID_CATEGORIES:
                issues.append(f"[seg {sid}] 非法 category: '{cat}'")
            if sev not in _VALID_SEVERITIES:
                issues.append(f"[seg {sid}] 非法 severity: '{sev}'")
            new_sev = apply_severity(cat, sev)
            if new_sev != sev:
                issues.append(f"[seg {sid}] {cat} severity {sev}→{new_sev} (auto-corrected)")
                e["severity"] = new_sev
    return issues


def _s(cell, fill=None, font=None, align=None):
    if fill:  cell.fill  = fill
    if font:  cell.font  = font
    if align: cell.alignment = align


def _build_xlsx(state, history, score, threshold, out_path):
    segments = state["segments"]
    seg_map = {s["id"]: s for s in segments}
    cat_counts: dict[str, dict[str, int]] = {
        cat: {"Neutral": 0, "Minor": 0, "Major": 0, "Critical": 0}
        for cat in _ALL_CATS
    }
    detail_rows: list[dict] = []
    all_locked_ids = set()
    for entry in history:
        all_locked_ids.update(entry.get("locked_ids", []))
    for seg in segments:
        if seg.get("locked"):
            all_locked_ids.add(seg["id"])
    max_iter = max((entry["iteration"] for entry in history), default=0)

    for entry in history:
        fixed = entry["iteration"] < max_iter
        for e_seg in entry["errors"]:
            seg = seg_map.get(e_seg["id"])
            if not seg:
                continue
            corrected = e_seg.get("corrected") or seg.get("corrected") or seg["target"]
            for e in e_seg.get("errors", []):
                cat = e.get("category", "Other")
                sev = apply_severity(cat, e.get("severity", "Minor"))
                if cat in cat_counts:
                    cat_counts[cat][sev] = cat_counts[cat].get(sev, 0) + 1
                detail_rows.append({
                    "filename": Path(state["input_path"]).stem,
                    "seg_id":   seg["id"],
                    "source":   seg["source"],
                    "original": seg["target"],
                    "corrected": corrected,
                    "parent":   _PARENT.get(cat, "Other"),
                    "category": cat,
                    "severity": sev,
                    "iteration": f"Iter {entry['iteration']}",
                    "comment":  e.get("comment", ""),
                    "fixed":    fixed,
                })

    total_counts = {"Neutral": 0, "Minor": 0, "Major": 0, "Critical": 0}
    for c in cat_counts.values():
        for sev, n in c.items():
            total_counts[sev] += n
    total_raw      = sum(raw_points(c) for c in cat_counts.values())
    total_weighted = sum(weighted_points(cat, c) for cat, c in cat_counts.items())

    wb  = openpyxl.Workbook()
    ws  = wb.active
    ws.title = "LQA Scorecard"
    status   = "PASS" if score >= threshold else "FAIL"

    def _db_row(row, height=14.25):
        ws.row_dimensions[row].height = height
        for col in range(1, 11):
            _s(ws.cell(row=row, column=col), fill=_DARK_BLUE, font=_WHITE_FONT)

    for r in [1, 2, 3]:
        ws.row_dimensions[r].height = 23.25
        _db_row(r, height=23.25)
    ws.merge_cells("A1:J3")
    c = ws["A1"]
    c.value = "LQA Scorecard"
    c.font  = Font(color="FFFFFF", size=16, bold=True)
    c.alignment = _CENTER

    info = [
        ("File", Path(state["input_path"]).name, "Wordcount", state.get("wordcount", 0)),
        ("Source language", "Chinese (Simplified)", "Target language", "English"),
        ("Total iterations", len(history), "Threshold", threshold),
        ("Date", date.today().isoformat(), "", ""),
    ]
    for ri, (l1, v1, l2, v2) in enumerate(info, start=4):
        _db_row(ri, height=15.0)
        ws.cell(row=ri, column=1, value=l1)
        ws.merge_cells(f"B{ri}:D{ri}")
        c = ws.cell(row=ri, column=2, value=v1)
        c.fill = _DARK_BLUE; c.font = Font(color="FFFFFF")
        ws.cell(row=ri, column=5, value=l2)
        ws.merge_cells(f"F{ri}:H{ri}")
        c = ws.cell(row=ri, column=6, value=v2)
        c.fill = _DARK_BLUE; c.font = Font(color="FFFFFF")

    ws.row_dimensions[8].height = 6

    _db_row(9)
    ws.merge_cells("A9:J9")
    c = ws["A9"]
    c.value = "LQA results"
    c.alignment = _LEFT_MID

    for row, height in [(10, 34.0), (11, 34.0), (12, 34.0)]:
        ws.row_dimensions[row].height = height

    for row, label, val, val_fill, val_font in [
        (10, "Status",      status,          _RED if status == "FAIL" else _GREEN,
                                             Font(color="FFFFFF", bold=True)),
        (11, "Final score", round(score, 4), _ORANGE, Font(bold=True)),
        (12, "Threshold",   threshold,       _ORANGE, Font(bold=True)),
    ]:
        c = ws.cell(row=row, column=1, value=label)
        _s(c, fill=_LIGHT_BLUE, align=_CENTER)
        c = ws.cell(row=row, column=2, value=val)
        _s(c, fill=val_fill, font=val_font, align=_CENTER)

    ws.merge_cells("C10:J12")
    c = ws["C10"]
    c.value = "Overall feedback"
    _s(c, fill=_LIGHT_BLUE, align=_CENTER)

    cur_row = 13
    if len(history) > 1:
        ws.row_dimensions[cur_row].height = 6
        cur_row += 1
        _db_row(cur_row)
        ws.merge_cells(f"A{cur_row}:J{cur_row}")
        c = ws.cell(row=cur_row, column=1, value="Iteration log")
        c.alignment = _LEFT_MID
        cur_row += 1
        for col, hdr in [(1,"Iteration"),(2,"Score"),(3,"Errors found"),(4,"Corrections applied")]:
            c = ws.cell(row=cur_row, column=col, value=hdr)
            _s(c, fill=_LIGHT_BLUE, align=_CENTER, font=_BOLD)
        ws.row_dimensions[cur_row].height = 14.25
        cur_row += 1
        for entry in history:
            s  = entry.get("score")
            ec = sum(len(e.get("errors", [])) for e in entry["errors"])
            for col, val in [
                (1, f"Iter {entry['iteration']}"),
                (2, round(s, 2) if s is not None else ""),
                (3, ec),
                (4, entry.get("corrections_count", 0)),
            ]:
                c = ws.cell(row=cur_row, column=col, value=val)
                _s(c, fill=_ORANGE, align=_CENTER)
            ws.row_dimensions[cur_row].height = 14.25
            cur_row += 1

    ws.row_dimensions[cur_row].height = 6
    cur_row += 1

    _db_row(cur_row)
    ws.merge_cells(f"A{cur_row}:L{cur_row}")
    c = ws.cell(row=cur_row, column=1, value="Error summary")
    c.alignment = _LEFT_MID
    cur_row += 1

    ws.row_dimensions[cur_row].height = 15.0
    ws.merge_cells(f"A{cur_row}:A{cur_row+1}")
    ws.merge_cells(f"B{cur_row}:B{cur_row+1}")
    ws.merge_cells(f"C{cur_row}:J{cur_row}")
    ws.merge_cells(f"K{cur_row}:L{cur_row}")
    for col, val in [(1,"Error category"),(2,"Weight"),(3,"Error severity"),(11,"Penalty points")]:
        c = ws.cell(row=cur_row, column=col, value=val)
        _s(c, font=_BOLD, align=_CENTER)
    cur_row += 1

    ws.row_dimensions[cur_row].height = 14.25
    for col, val in enumerate(
        ["Neutral","Neutral – repeated","Minor","Minor – repeated",
         "Major","Major – repeated","Critical","Critical – repeated","Raw","Weighted"], start=3):
        c = ws.cell(row=cur_row, column=col, value=val)
        _s(c, fill=_LIGHT_BLUE, align=_CENTER)
    cur_row += 1

    ws.row_dimensions[cur_row].height = 14.25
    for col, val in [
        (1,"TOTAL"),(2,None),
        (3,total_counts.get("Neutral",0)),(4,0),
        (5,total_counts.get("Minor",0)),  (6,0),
        (7,total_counts.get("Major",0)),  (8,0),
        (9,total_counts.get("Critical",0)),(10,0),
        (11,total_raw),(12,round(total_weighted,2)),
    ]:
        c = ws.cell(row=cur_row, column=col, value=val)
        _s(c, fill=_ORANGE, align=_CENTER)
    cur_row += 1

    for cat in _ALL_CATS:
        counts = cat_counts[cat]
        r = raw_points(counts)
        w = weighted_points(cat, counts)
        ws.row_dimensions[cur_row].height = 14.25
        for col, val in [
            (1,cat),(2,weighted_points(cat, {"Minor": 1})),
            (3,counts.get("Neutral",0)),(4,0),
            (5,counts.get("Minor",0)),  (6,0),
            (7,counts.get("Major",0)),  (8,0),
            (9,counts.get("Critical",0)),(10,0),
            (11,r),(12,round(w,2)),
        ]:
            c = ws.cell(row=cur_row, column=col, value=val)
            _s(c, align=_CENTER)
        cur_row += 1

    ws.row_dimensions[cur_row].height = 6
    cur_row += 1

    ws.row_dimensions[cur_row].height = 14.25
    for col, hdr in enumerate(
        ["File name","Segment #","Source text","Original target translation",
         "Corrected target translation","Error category","Error sub-category",
         "Error severity","Iteration","Reviewer's comment","Fixed","RAG Protected","RAG Evidence"], start=1):
        c = ws.cell(row=cur_row, column=col, value=hdr)
        _s(c, fill=_DARK_BLUE, font=_WHITE_FONT, align=_CENTER)
    cur_row += 1

    for dr in detail_rows:
        ws.row_dimensions[cur_row].height = 15.75
        row_fill = _GREEN_LIGHT if dr["fixed"] else None
        for col, val in [
            (1, dr["filename"]), (2, dr["seg_id"]),
            (3, dr["source"]),   (4, dr["original"]),
            (5, dr["corrected"]),(6, dr["parent"]),
            (7, dr["category"]), (8, dr["severity"]),
            (9, dr["iteration"]),(10, dr["comment"]),
            (11, "✓" if dr["fixed"] else "—"),
            (12, "Yes" if dr["seg_id"] in all_locked_ids else "No"),
            (13, "RAG_100_MATCH" if dr["seg_id"] in all_locked_ids else ""),
        ]:
            c = ws.cell(row=cur_row, column=col, value=val)
            _s(c, fill=row_fill, align=_LEFT_TOP if col not in (2, 8, 9, 11) else _CENTER)
        cur_row += 1

    for col_ltr, width in [
        ("A",22),("B",8),("C",35),("D",45),("E",45),
        ("F",14),("G",22),("H",10),("I",10),("J",45),
        ("K",12),("L",12),
    ]:
        ws.column_dimensions[col_ltr].width = width

    ws2 = wb.create_sheet("LQE Results")

    def _fmt_errors(errs):
        return "\n".join(
            f"[{e.get('category','?')} · {e.get('severity','?')}] {e.get('comment','')}"
            for e in errs
        )

    _WRAP_TOP = Alignment(wrap_text=True, vertical="top")

    current_seg_errors = {
        e["id"]: e.get("errors", [])
        for e in history[-1].get("errors", [])
    } if history else {}
    current_entries = {e["id"]: e for e in history[-1].get("errors", [])} if history else {}
    is_final_report = "_lqe_iter" not in out_path.name
    translation_col = "Final Translation" if is_final_report else "Suggested Correction"

    ws2_headers = state["headers"] + [translation_col, "LQE_Error_Detail", "LQE_Status", "LQE_Iter", "RAG Protected", "RAG Evidence"]
    for ci, h in enumerate(ws2_headers, start=1):
        c = ws2.cell(row=1, column=ci, value=h)
        _s(c, fill=_DARK_BLUE, font=_WHITE_FONT, align=_CENTER)
    ws2.row_dimensions[1].height = 15.0

    for ri, (raw_row, seg) in enumerate(zip(state["rows_raw"], segments), start=2):
        errs = current_seg_errors.get(seg["id"], [])
        has_error = bool(errs)
        row_fill = _ORANGE if has_error else _GREEN_LIGHT if seg.get("corrected") else None
        row_data = list(raw_row) + [
            (seg.get("corrected") or "") if is_final_report else (current_entries.get(seg["id"], {}).get("corrected") or ""),
            _fmt_errors(errs),
            "Error" if has_error else ("Fixed" if seg.get("corrected") else "OK"),
            seg.get("iter", 0),
            "Yes" if seg["id"] in all_locked_ids else "No",
            "RAG_100_MATCH" if seg["id"] in all_locked_ids else "",
        ]
        for ci, val in enumerate(row_data, start=1):
            c = ws2.cell(row=ri, column=ci, value=val)
            c.alignment = _WRAP_TOP
            if row_fill:
                c.fill = row_fill
        ws2.row_dimensions[ri].height = max(15.0, min(80.0, 15.0 + 13.0 * max(0, len(errs) - 1)))

    n_orig = len(state["headers"])
    for ci in range(1, n_orig + 1):
        ws2.column_dimensions[get_column_letter(ci)].width = 20
    for ci, w in enumerate([35, 45, 10, 8, 12, 18], start=n_orig + 1):
        ws2.column_dimensions[get_column_letter(ci)].width = w

    wb.save(str(out_path))
    print(f"[lqe_io] Output → {out_path}")


def cmd_write(args):
    state_path = Path(args.state)
    state = read_json(state_path)
    final_errors_data = read_json(args.errors)
    score = float(args.score)

    final_entry = {
        "iteration": state.get("iteration", 0),
        "score": score,
        "errors": final_errors_data,
        "corrections_count": 0,
    }

    history = state.get("error_history", [])
    final_iter = state.get("iteration", 0)
    if not history or history[-1].get("iteration") != final_iter:
        history.append(final_entry)
        state["error_history"] = history
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    src = Path(state["input_path"])
    out_path = state_path.parent / (src.stem + "_lqe.xlsx")
    _build_xlsx(state, history, score, args.threshold, out_path)


# ── pre-check ────────────────────────────────────────────────────────────────

_RE_CJK      = re.compile(r'[一-鿿]')
_RE_DASH     = re.compile(r'—')
_RE_NUM      = re.compile(r'(?<!\d)(\d{4,})(?!\d)')
_RE_COLOR    = {c: re.compile(rf'#{c}[^#]*?#E') for c in 'GCY'}  # count-only, content translatable
_RE_VARS     = [re.compile(r'\{[^}]*\}'), re.compile(r'%[sd]')]   # exact match
# R1: 位置占位符顺序（无索引 %s/%d 顺序敏感；命名/带索引占位符允许重排）
# 注：颜色标签的开闭配对不做独立计数——`#` 在部分项目兼作叙述标记（#Enter/#Camera），
# `#E/#C/#G/#Y` 会误匹配英文词首；颜色标签数量异常由下方整对 `#X...#E` 源译比对负责。
_RE_POS_PH   = re.compile(r'%(?![0-9]+\$)[sd]')
# R6: 数值一致性（提取阿拉伯数字 token，归一去千位分隔符）
_RE_NUMTOK   = re.compile(r'\d[\d,]*(?:\.\d+)?')
# R3 回退门控/长度比对前剥离标记（标签会稀释 CJK 占比、虚增长度）
_RE_MARKUP   = re.compile(r'<[^>]*>|\{[^}]*\}|%[sd]')
# R5: 译文中不应出现的全角/CJK 标点与全角空格（适用 EN/TH 等非 CJK 目标语言；
# CJK 目标语言如 ja 在语言层关闭 fullwidth_punct）
_FORBIDDEN_FW = '，。！？；：、（）【】《》「」『』“”‘’　'


def _norm_nums(text: str):
    return Counter(m.group(0).replace(',', '') for m in _RE_NUMTOK.finditer(text))


def _load_checks(state: dict):
    toggles, custom = {}, []

    def _absorb(cfg: dict, label: str):
        toggles.update(cfg.get("builtin", {}))
        for c in cfg.get("custom", []):
            try:
                custom.append((re.compile(c["pattern"]), c))
            except (re.error, KeyError) as e:
                print(f"[warn] bad custom check {c.get('id', '?')} in {label}: {e}", file=sys.stderr)

    lang = _target_lang(state)
    lang_cfg = _load_lang(lang)
    if lang_cfg:
        _absorb(lang_cfg, f"languages/{lang}.json")
        print(f"[pre-check] language layer: languages/{lang}.json")

    p = state.get("checks_path", "")
    if p and Path(p).exists():
        _absorb(read_json(p), "project checks.json")  # 项目层后合并，覆盖语言层同名开关
        print(f"[pre-check] checks profile: {len(toggles)} toggles, {len(custom)} custom rules")
    return toggles, custom


def cmd_pre_check(args):
    state_path = Path(args.state)
    state = read_json(state_path)
    segments = state["segments"]

    terms = _load_terms(state)
    term_map = {
        t["source"].strip(): (t["target"].strip().lower(), t.get("status", ""), bool(t.get("locked")))
        for t in terms
        if t.get("source") and t.get("target")
        and len(t["source"].strip()) >= (2 if _RE_CJK.search(t["source"]) else 3)
    }

    toggles, custom = _load_checks(state)
    on = lambda key: toggles.get(key, True)

    results = []
    total = 0

    for seg in segments:
        src = seg["source"]
        tgt = seg.get("corrected") or seg["target"]
        errs = []

        tgt_has_cjk = bool(_RE_CJK.search(tgt))
        src_cjk     = len(_RE_CJK.findall(src))

        # R7: 空译文（仅报一条，跳过其余检查避免堆叠噪音）
        if on("empty_target") and src.strip() and not tgt.strip():
            results.append({"id": seg["id"], "errors": [
                {"category": "Untranslated", "severity": "Major",
                 "comment": "Target is empty"}], "corrected": None})
            total += 1
            continue

        if on("untranslated_cjk") and tgt_has_cjk and src.strip():
            errs.append({"category": "Untranslated", "severity": "Major",
                         "comment": "Target contains Chinese characters"})

        if on("em_dash") and _RE_DASH.search(tgt):
            errs.append({"category": "Punctuation", "severity": "Minor",
                         "comment": "Em dash '—' found; use ' - '"})

        for c, pat in (_RE_COLOR.items() if on("color_tags") else ()):
            sc, tc = len(pat.findall(src)), len(pat.findall(tgt))
            if sc != tc:
                errs.append({"category": "Markup", "severity": "Major",
                             "comment": f"#{c}...#E count: source={sc}, target={tc}"})

        for pat in (_RE_VARS if on("variables") else ()):
            s_hits, t_hits = set(pat.findall(src)), set(pat.findall(tgt))
            for m in s_hits - t_hits:
                errs.append({"category": "Markup", "severity": "Major",
                             "comment": f"Missing variable: {m!r}"})
            for m in t_hits - s_hits:
                errs.append({"category": "Markup", "severity": "Major",
                             "comment": f"Extra variable: {m!r}"})

        src_nl, tgt_nl = src.count(r'\n'), tgt.count(r'\n')
        if on("newline_count") and src_nl != tgt_nl:
            errs.append({"category": "Markup", "severity": "Major",
                         "comment": f"\\n count: source={src_nl}, target={tgt_nl}"})

        max_len = seg.get("max_len") if on("length") else None
        if max_len:
            # R3: 有真实 UI 字段宽度上限 → 硬截断检查（优先于 1.5× 启发式）
            if len(tgt) > max_len:
                errs.append({"category": "Length", "severity": "Major",
                             "comment": f"Target {len(tgt)} chars exceeds max-length {max_len}"})
        elif on("length"):
            src_plain = _RE_MARKUP.sub('', src)
            tgt_plain = _RE_MARKUP.sub('', tgt)
            if len(_RE_CJK.findall(src_plain)) <= len(src_plain) * 0.3:
                src_len = len(src_plain.replace(" ", ""))
                tgt_len = len(tgt_plain.replace(" ", ""))
                if src_len > 0 and tgt_len > src_len * 1.5:
                    errs.append({"category": "Length", "severity": "Major",
                                 "comment": f"Target {tgt_len} chars > 1.5× source {src_len} (markup stripped)"})

        for m in (_RE_NUM.finditer(tgt) if on("locale_numbers") else ()):
            num = int(m.group(1))
            if not (1900 <= num <= 2099):
                errs.append({"category": "Locale convention", "severity": "Minor",
                             "comment": f"{m.group(1)} → {num:,} (thousands separator)"})
                break

        tgt_lower = tgt.lower()
        if on("terminology"):
            hit_srcs = [ts for ts in term_map if ts in src]
            for term_src in hit_srcs:
                term_tgt, term_status, term_locked = term_map[term_src]
                # 复合术语优先：更长词条命中且其译法已在译文中 → 跳过被包含的子词条
                covered = any(other != term_src and term_src in other
                              and term_map[other][0] in tgt_lower for other in hit_srcs)
                if covered:
                    continue
                if term_tgt not in tgt_lower:
                    note = f" [TB:{term_status}]" if term_status else ""
                    if term_locked:
                        note += " [LOCKED]"
                    errs.append({"category": "Terminology", "severity": "Major",
                                 "comment": f"'{term_src}' → expected '{term_tgt}'{note}"})

        # R1: 无索引位置占位符 %s/%d 顺序（数量相同但顺序错位 → 参数错位）
        src_pos, tgt_pos = _RE_POS_PH.findall(src), _RE_POS_PH.findall(tgt)
        if on("pos_placeholder") and sorted(src_pos) == sorted(tgt_pos) and src_pos != tgt_pos:
            errs.append({"category": "Markup", "severity": "Major",
                         "comment": f"Positional placeholder order changed: {src_pos} → {tgt_pos}"})

        # R6: 数值一致性（仅当源含阿拉伯数字；漏译/改值是游戏 Critical 级隐患）
        if on("numbers_consistency") and _RE_NUMTOK.search(src):
            missing = _norm_nums(src) - _norm_nums(tgt)
            if missing:
                miss = ", ".join(sorted(missing.elements()))
                errs.append({"category": "Mistranslation", "severity": "Major",
                             "comment": f"Source number(s) missing/changed in target: {miss}"})

        # R5: 空白规范化 + EN 译文全角标点
        if on("whitespace") and tgt.strip() and tgt != tgt.strip():
            errs.append({"category": "Punctuation", "severity": "Minor",
                         "comment": "Leading/trailing whitespace in target"})
        if on("whitespace") and '  ' in tgt.strip():
            errs.append({"category": "Punctuation", "severity": "Minor",
                         "comment": "Double space in target"})
        fw = sorted({ch for ch in tgt if ch in _FORBIDDEN_FW}) if on("fullwidth_punct") else []
        if fw:
            errs.append({"category": "Punctuation", "severity": "Minor",
                         "comment": f"Full-width punctuation in target: {''.join(fw)}"})

        for pat, c in custom:
            where = c.get("where", "target")
            hay = src if where == "source" else (src + "\n" + tgt if where == "both" else tgt)
            m = pat.search(hay)
            if m:
                errs.append({"category": c.get("category", "Company style"),
                             "severity": c.get("severity", "Minor"),
                             "comment": f"{c.get('comment', c.get('id', 'custom check'))} [match: {m.group(0)[:30]}]"})

        total += len(errs)
        results.append({"id": seg["id"], "errors": errs, "corrected": None})

    out = Path(args.out) if args.out else state_path.parent / "errors_precheck.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    dist = Counter(e["category"] for r in results for e in r["errors"])
    flagged = sum(1 for r in results if r["errors"])
    print(f"[pre-check] {total} issues / {flagged} segments → {out}")
    for cat, n in dist.most_common():
        print(f"  {n:>4}x  {cat}")


# ── export ───────────────────────────────────────────────────────────────────

def cmd_export(args):
    state_path = Path(args.state)
    state = read_json(state_path)
    segments = state["segments"]
    seg_map = {s["id"]: s for s in segments}

    no_header = isinstance(state.get("source_col"), int) or (
        isinstance(state.get("source_col"), str) and state["source_col"].isdigit()
    )
    try:
        ti = int(state["target_col"])
    except (ValueError, TypeError):
        headers = state.get("headers", [])
        ti = headers.index(state["target_col"]) if state["target_col"] in headers else None
        if ti is None:
            print(f"[export] cannot locate target column '{state['target_col']}'", file=sys.stderr)
            sys.exit(1)

    src_path = Path(state["input_path"])
    wb = openpyxl.load_workbook(str(src_path))
    ws = wb.active

    start_row = 1 if no_header else 2
    for i, row_cells in enumerate(ws.iter_rows(min_row=start_row)):
        seg = seg_map.get(i)
        if seg is None:
            continue
        final_text = seg["target"] if seg.get("locked") else (seg.get("corrected") or seg["target"])
        if ti < len(row_cells):
            row_cells[ti].value = final_text

    out_path = state_path.parent / (src_path.stem + "_corrected.xlsx")
    wb.save(str(out_path))
    corrected_count = sum(1 for s in segments if s.get("corrected"))
    print(f"[export] {corrected_count} corrections applied → {out_path}")


# ── ingest-corpus (stub) ──────────────────────────────────────────────────────

def cmd_ingest_corpus(args):
    # TODO: 接口格式待确认（JSON 直传 vs 文件上传）
    print("[lqe_io] ingest-corpus: AIPE RAG ingest interface TBD, skipping.")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("read")
    r.add_argument("--input", required=True)
    r.add_argument("--project", default=None, help="项目档案：projects/<名>/profile.json 或目录/文件路径；提供 SG/术语/词数基准/checks/adjudications 默认值，显式参数优先")
    r.add_argument("--source-col", required=True, dest="source_col", help="列名或列索引（0-based，配合 --no-header）")
    r.add_argument("--target-col", required=True, dest="target_col", help="列名或列索引（0-based，配合 --no-header）")
    r.add_argument("--no-header", action="store_true", dest="no_header", help="文件无表头行，source-col/target-col 为整数索引")
    r.add_argument("--terminology", default=None, help="术语表文件路径（.csv/.tsv/.json/.xlsx）")
    r.add_argument("--style-guide", default=None, dest="style_guide", help="风格指南文件路径（.txt/.md/.docx/.xlsx）")
    r.add_argument("--target-lang", default=None, dest="target_lang",
                   help="目标语言代码（en/th 等）；挂载 languages/<lang>.json 语言层默认。方式 C 自动从 profile language_pair 解析，无需传")
    r.add_argument("--wordcount-basis", default=None, choices=["target-words", "source-chars"],
                   dest="wordcount_basis",
                   help="词数基准：target-words=译文空格分词（EN 等）；source-chars=源文 CJK 字符数+拉丁词数（泰语等无空格译文用）")
    r.add_argument("--out", default="lqe_state.json")

    fa = sub.add_parser("from-aipe")
    fa.add_argument("--aipe-csv", required=True, dest="aipe_csv")
    fa.add_argument("--aipe-url", required=True, dest="aipe_url")
    fa.add_argument("--out", default="lqe_state.json")

    af = sub.add_parser("apply-fixes")
    af.add_argument("--state",     required=True)
    af.add_argument("--errors",    required=True)
    af.add_argument("--score",     default=None, help="本轮分数（来自 lqe_calc.py 输出）")
    af.add_argument("--threshold", type=float, default=98.0)
    af.add_argument("--locked-ids", default=None, help="逗号分隔的 RAG/TM 100%% match segment ids")
    af.add_argument("--locked-file", default=None, help="RAG/TM 100%% match locked ids JSON 文件")

    w = sub.add_parser("write")
    w.add_argument("--state",     required=True)
    w.add_argument("--errors",    required=True)
    w.add_argument("--score",     required=True)
    w.add_argument("--threshold", type=float, default=98)

    pc = sub.add_parser("pre-check")
    pc.add_argument("--state", required=True)
    pc.add_argument("--out", default=None, help="输出路径（默认 {job_dir}/errors_precheck.json）")

    lt = sub.add_parser("lookup-terms")
    lt.add_argument("--state", required=True)
    lt.add_argument("--ids", default=None, help="逗号分隔的 seg id，不传则扫描全部段落")

    ex = sub.add_parser("export")
    ex.add_argument("--state", required=True)

    ic = sub.add_parser("ingest-corpus")
    ic.add_argument("--state",    required=True)
    ic.add_argument("--aipe-url", required=True, dest="aipe_url")

    args = p.parse_args()
    {
        "read":           cmd_read,
        "from-aipe":      cmd_from_aipe,
        "pre-check":      cmd_pre_check,
        "apply-fixes":    cmd_apply_fixes,
        "write":          cmd_write,
        "export":         cmd_export,
        "lookup-terms":   cmd_lookup_terms,
        "ingest-corpus":  cmd_ingest_corpus,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
