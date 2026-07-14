"""
LQE I/O utilities.

Subcommands:
  read          Excel/CSV/TSV + project profile → state.json
  pre-check     确定性错误自动检测（标点/Markup/术语/长度等）
  protect-segments 把已确认的 TM/100% 匹配段标记为已保护
  apply-fixes   把程序生成的建议译文写回 state.json
  write         state.json + errors.json → *_lqe.xlsx
  ingest-corpus 建议译文回传 AIPE 语料库（接口尚未确定，暂不执行）
"""
import argparse
import csv
import io
import json
import re
import sys
from datetime import date
from pathlib import Path

import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter

from lqe_engine import (
    read_json, RE_CJK as _RE_CJK, _source_lang, _target_lang, _load_lang, _LANG_DIR, _SKILL_ROOT,
    CATEGORY_ORDER as _ALL_CATS, CATEGORY_PARENT as _PARENT,
    VALID_CATEGORIES as _VALID_CATEGORIES, VALID_SEVERITIES as _VALID_SEVERITIES,
    apply_severity, build_check_scope, load_terms as _load_terms, group_terms as _group_terms,
    raw_points, weighted_points,
    load_scorecard_profile, normalize_category_for_profile, scorecard_category_order,
    scorecard_category_parent, scorecard_category_weight,
)
from lqe_corrections import (
    CheckFormatError,
    build_results,
    normalize_check_entries,
    verify_results,
)


def _write_json_atomic(path: Path, value: object) -> None:
    staging = path.with_name(f".{path.name}.tmp")
    staging.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    staging.replace(path)


def _processing_label(entry: dict) -> str:
    errors = entry.get("errors") or []
    if any(error.get("protected") for error in errors):
        return "已保护，不修改"
    if any(error.get("needs_confirmation") for error in errors):
        return "需要人工确认"
    if entry.get("corrected") is not None:
        return "建议修改"
    if errors:
        return "仅提醒"
    return "无需修改"


# ── read ──────────────────────────────────────────────────────────────────────

_SRC_KEYS = {"source", "zh", "src", "原文", "中文_cn", "中文", "chinese", "chinese_prc", "zh_cn", "zh-cn", "简中", "中文简体", "source text"}
_TGT_KEYS = {"target", "en", "tgt", "译文", "en_us", "english", "翻译", "英文", "thai", "th", "泰语", "泰文", "target text"}
_ZW_TABLE = {ord(c): None for c in "​‌‍﻿"}


def _clean_term_sense(raw: dict) -> dict | None:
    target = str(raw.get("target", "")).translate(_ZW_TABLE).strip()
    if not target:
        return None
    sense = {"target": target}
    for key in ("status", "category", "definition"):
        value = raw.get(key)
        if value is not None and str(value).strip():
            sense[key] = str(value).strip()
    sense["confirmed"] = raw.get("confirmed") is True
    sense["protected"] = raw.get("protected") is True
    return sense


def _clean_terms(items: list) -> list:
    out = []
    for t in items:
        s = str(t.get("source", "")).translate(_ZW_TABLE).strip()
        if not s:
            continue
        if "senses" in t:
            senses = [
                clean
                for raw in t["senses"]
                if isinstance(raw, dict)
                for clean in [_clean_term_sense(raw)]
                if clean is not None
            ]
            if senses:
                out.append({"source": s, "senses": senses})
            continue
        sense = _clean_term_sense(t)
        if sense is not None:
            out.append({"source": s, **sense})
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


def _job_label(state_path) -> str:
    """输出文件名前缀：标注产物来自哪个任务。取 jobs/ 下的子路径用 _ 连接
    （如 jobs/LQE测试用/剧情/ → 'LQE测试用_剧情'），否则退回 job 目录名。
    避免多文件/多 sheet 拆分时所有 job 都叫 src_*，看不出来源。"""
    d = Path(state_path).resolve().parent
    parts = d.parts
    if "jobs" in parts:
        sub = parts[parts.index("jobs") + 1:]
        if sub:
            return "_".join(sub)
    return d.name


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
    # 项目名 = <game>/<track>（如 nrc/zh-th、wwm/zh-en），在 skill 根 projects/ 下解析（CWD 无关）；
    # 带后缀或绝对路径按字面处理（支持任意位置的 profile.json）。
    p = Path(name_or_path)
    if not p.suffix and not p.is_absolute():
        p = _SKILL_ROOT / "projects" / p
    if p.is_dir():
        p = p / "profile.json"
    if not p.exists():
        print(f"[ERROR] project profile not found: {p}", file=sys.stderr)
        sys.exit(1)
    prof = read_json(p)
    prof["_dir"] = str(p.parent.resolve())
    return prof


def _validate_project_profile(prof: dict):
    required = ("language_pair", "source_lang", "target_lang")
    missing = [k for k in required if not str(prof.get(k, "")).strip()]
    if missing:
        print("[ERROR] project profile must define language_pair, source_lang, and target_lang; "
              f"missing: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)


def _project_path(prof: dict, val: str) -> str:
    if not val:
        return ""
    q = Path(val)
    return str(q if q.is_absolute() else Path(prof["_dir"]) / q)


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


def _cell(row, idx):
    return row[idx] if idx is not None and idx < len(row) else None


def _text(v):
    return str(v).strip() if v is not None else ""


def _extract_text_type_marker(src, tgt=None, content_type=None):
    """AIPE CSV may contain text-type header rows; they are context, not segments."""
    s = _text(src)
    if not s:
        return None
    explicit = {"对话类文本", "游戏内侧页文本", "故事类文本"}
    if s in explicit:
        return s
    m = re.match(r"^(?:文本类型|文本类别)\s*[:：]\s*(.+)$", s)
    if m and m.group(1).strip():
        return m.group(1).strip()
    if s in {"文本类型", "文本类别"}:
        return _text(tgt) or _text(content_type) or s
    return None


def cmd_read(args):
    check_scope = build_check_scope(getattr(args, "no_terminology", False))
    prof = _load_project(args.project) if getattr(args, "project", None) else None
    if prof:
        _validate_project_profile(prof)
        if not args.style_guide and prof.get("style_guide"):
            args.style_guide = _project_path(prof, prof["style_guide"])
        if prof.get("terminology"):
            if not check_scope["terminology_enabled"]:
                print("[lqe_io] profile terminology overridden by --no-terminology")
            elif not args.terminology:
                args.terminology = _project_path(prof, prof["terminology"])
        print(f"[lqe_io] project: {prof.get('name', '?')} ({prof.get('language_pair', '?')})")

    no_header = getattr(args, "no_header", False)
    input_path = Path(args.input)
    suffix = input_path.suffix.lower()

    if suffix in (".csv", ".tsv"):
        delim = "\t" if suffix == ".tsv" else ","
        raw_rows = list(csv.reader(io.StringIO(input_path.read_bytes().decode("utf-8-sig")), delimiter=delim))
        if not raw_rows:
            print("[ERROR] No data rows found.", file=sys.stderr)
            sys.exit(1)
        width = max(len(r) for r in raw_rows)
        if no_header:
            default_headers = ["Key", "Source", "Target", "Status", "Comment", "Scope", "File", "Reviewer Note"]
            headers = [default_headers[j] if j < len(default_headers) else f"col{j}" for j in range(width)]
            data_rows = raw_rows
        else:
            headers = [str(h).strip() if h is not None else "" for h in raw_rows[0]]
            data_rows = raw_rows[1:]
    else:
        wb = openpyxl.load_workbook(args.input)
        ws = wb.active
        if no_header:
            default_headers = ["Key", "Source", "Target", "Status", "Comment", "Scope", "File", "Reviewer Note"]
            headers = [default_headers[j] if j < len(default_headers) else f"col{j}" for j in range(ws.max_column)]
            data_rows = list(ws.iter_rows(min_row=1, values_only=True))
        else:
            headers = [cell.value for cell in ws[1]]
            data_rows = list(ws.iter_rows(min_row=2, values_only=True))

    if no_header:
        # 列参数为整数索引（0-based）
        try:
            si = int(args.source_col)
            ti = int(args.target_col)
        except ValueError:
            print("[ERROR] --no-header mode requires integer column indices for --source-col and --target-col", file=sys.stderr)
            sys.exit(1)
    else:
        for col in [args.source_col, args.target_col]:
            if col not in headers:
                print(f"[ERROR] Column '{col}' not found. Available: {headers}", file=sys.stderr)
                sys.exit(1)
        si = headers.index(args.source_col)
        ti = headers.index(args.target_col)

    # R3: 自动识别 max-length 列（UI 字段宽度上限），用于逐元素截断检查
    mi = None
    for idx, h in enumerate(headers):
        if h is not None and str(h).strip().lower() in _MAXLEN_KEYS:
            mi = idx
            break
    if mi is not None:
        print(f"[lqe_io] max-length column detected: '{headers[mi]}' (col {mi})")

    gi = None
    if getattr(args, "group_col", None):
        g = args.group_col
        gi = int(g) if str(g).isdigit() else (headers.index(g) if g in headers else None)
        if gi is None:
            print(f"[warn] group column '{g}' not found; grouping disabled", file=sys.stderr)
        else:
            print(f"[lqe_io] group column: '{headers[gi]}' (col {gi})")

    ci = None
    for idx, h in enumerate(headers):
        if h is not None and str(h).strip().lower() in {"content_type", "text_type", "文本类型", "文本类别"}:
            ci = idx
            break

    segments, rows_raw, text_type_markers = [], [], []
    text_type_context = None
    for i, row in enumerate(data_rows):
        if any(_text(c) for c in row):
            src = _text(_cell(row, si))
            tgt = _text(_cell(row, ti))
            row_content_type = _text(_cell(row, ci)) if ci is not None else ""
            marker = _extract_text_type_marker(src, tgt, row_content_type)
            if marker:
                text_type_context = marker
                text_type_markers.append({
                    "row_index": i,
                    "source": src,
                    "target": tgt,
                    "content_type": row_content_type or None,
                })
                continue
            seg_id = len(segments)
            segments.append({
                "id": seg_id,
                "row_index": i,
                "source": src,
                "target": tgt,
                "corrected": None,
                "content_type": row_content_type or None,
                "text_type_context": text_type_context,
                "max_len": _parse_maxlen(row[mi]) if mi is not None and mi < len(row) else None,
                "group": (str(row[gi]).strip() if gi is not None and gi < len(row) and row[gi] is not None and str(row[gi]).strip() else None),
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

    # ── Terminology ───────────────────────────────────────────────────────
    # 优化：项目模式下源已是干净 JSON 且无保护标记 → terms_path 直接指向项目权威 TB，
    # 不在每个 job 里复制一份（项目 terms_*.json 由 mastertb_to_terms 产出、已清理）。
    # 需格式转换(xlsx/csv) 或要打 protected 标时，才落一份 job 副本。
    terms_path = ""
    if args.terminology:
        protected_statuses = {
            str(status).lower()
            for status in (prof.get("protected_term_statuses") or [])
        } if prof else set()
        src = Path(args.terminology)
        if prof and src.suffix.lower() == ".json" and not protected_statuses and src.exists():
            terms_path = str(src)
            print(f"[lqe_io] terminology: 引用项目 TB（不复制）→ {src}")
        else:
            terms = _load_terminology(args.terminology)
            if terms and protected_statuses:
                n_protected = 0
                for t in terms:
                    senses = t.get("senses", [t])
                    for sense in senses:
                        if str(sense.get("status", "")).lower() in protected_statuses:
                            sense["protected"] = True
                            n_protected += 1
                print(
                    f"[lqe_io] protected term senses: {n_protected} "
                    f"(protected_term_statuses: {sorted(protected_statuses)})"
                )
            if terms:
                terms_file = job_dir / "terms.json"
                terms_file.write_text(json.dumps(terms, ensure_ascii=False, indent=2), encoding="utf-8")
                terms_path = str(terms_file)
                print(f"[lqe_io] terminology: {len(terms)} entries → {terms_file}")

    source_lang = _source_lang({"source_lang": getattr(args, "source_lang", None)}) \
        or _source_lang(prof if prof else {})
    lang = _target_lang({"target_lang": getattr(args, "target_lang", None)}) \
        or _target_lang(prof if prof else {})
    lang_cfg = _load_lang(lang)
    if lang_cfg:
        print(f"[lqe_io] target language attributes: target_languages/{lang}/attributes.json")

    # 语言级检查说明（固定名 eval_notes.md，存在即挂载）会复制到任务目录；效力低于风格指南和确认规则
    lang_notes_path = ""
    if lang:
        np = _LANG_DIR / lang / "eval_notes.md"
        if np.exists():
            dst = job_dir / "lang_notes.md"
            dst.write_text(np.read_text(encoding="utf-8"), encoding="utf-8")
            lang_notes_path = str(dst)
            print(f"[lqe_io] language eval notes → {dst}")

    # 项目背景（游戏类型/受众/语气/语域基调）提供给各检查模块和单任务，校准自然度与口吻判断
    # 检查模块规范保持项目中立；具体背景来自 profile.background
    background_path = ""
    if prof and (prof.get("background") or "").strip():
        dst = job_dir / "background.md"
        dst.write_text("# 项目背景\n\n" + prof["background"].strip() + "\n", encoding="utf-8")
        background_path = str(dst)
        print(f"[lqe_io] project background → {dst}")

    basis = getattr(args, "wordcount_basis", None) \
        or (prof.get("wordcount_basis") if prof else None) \
        or lang_cfg.get("wordcount_basis") or "target-words"
    if lang_cfg.get("word_delim") == "none" and basis == "target-words":
        print("[warn] target language has no word delimiter — 'target-words' basis will "
              "undercount severely; use source-chars", file=sys.stderr)
    if basis == "source-chars":
        wordcount = sum(
            len(_RE_CJK.findall(s["source"])) + len(re.findall(r"[A-Za-z0-9]+", s["source"]))
            for s in segments
        )
    else:
        wordcount = sum(len(s["target"].split()) for s in segments)

    checks_path = confirmed_rules_path = ""
    if prof:
        cp = Path(_project_path(prof, prof.get("checks", "checks.json")))
        checks_path = str(cp) if cp.exists() else ""
        # confirmed rules = game 级共通 + 语言专有，拼成 job 内一份
        ap = Path(_project_path(prof, prof.get("confirmed_rules", "confirmed_rules.md")))
        common_ap = ap.parent.parent / "common" / "confirmed_rules_common.md"
        parts = []
        if common_ap.exists():
            parts.append(f"<!-- ===== 共通确认规则（游戏级）: {common_ap.name} ===== -->\n" + common_ap.read_text(encoding="utf-8"))
        if ap.exists():
            parts.append(f"<!-- ===== 语言专有确认规则: {ap} ===== -->\n" + ap.read_text(encoding="utf-8"))
        if parts:
            combined = Path(args.out).parent / "confirmed_rules.md"
            combined.parent.mkdir(parents=True, exist_ok=True)
            combined.write_text("\n\n".join(parts), encoding="utf-8")
            confirmed_rules_path = str(combined)
            print(f"[lqe_io] confirmed rules: {'共通+' if common_ap.exists() else ''}语言专有 → {combined}")

    state = {
        "input_path": str(Path(args.input).resolve()),
        "source_col": args.source_col,
        "target_col": args.target_col,
        "headers": headers,
        "rows_raw": rows_raw,
        "text_type_markers": text_type_markers,
        "aipe_url": None,
        "check_scope": check_scope,
        "project": prof.get("name", "") if prof else "",
        "language_pair": prof.get("language_pair", "") if prof else (
            f"{source_lang}-{lang}" if source_lang and lang else ""
        ),
        "source_lang": source_lang,
        "target_lang": lang,
        "lang_notes_path": lang_notes_path,
        "background_path": background_path,
        "checks_path": checks_path,
        "confirmed_rules_path": confirmed_rules_path,
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
    _write_json_atomic(job_dir / "scope.json", check_scope)
    _write_json_atomic(out_path, state)
    print(f"[lqe_io] {len(segments)} segments → {args.out}  wordcount={state['wordcount']}")

# ── lookup-terms ──────────────────────────────────────────────────────────────

def cmd_lookup_terms(args):
    state = read_json(args.state)
    terms = _load_terms(state)
    if not terms:
        print("[lqe_io] no terminology available.", file=sys.stderr)
        return

    term_map = _group_terms(terms)

    segs = state["segments"]
    if args.ids:
        id_set = set(int(x) for x in args.ids.split(","))
        segs = [s for s in segs if s["id"] in id_set]

    # 逐段匹配，避免跨段拼接产生误命中
    hits: dict[str, dict] = {}  # term_source → {senses, seg_ids}
    for seg in segs:
        src_text = seg["source"]
        for term_src, senses in term_map.items():
            if term_src in src_text:
                if term_src not in hits:
                    hits[term_src] = {"senses": senses, "seg_ids": []}
                hits[term_src]["seg_ids"].append(seg["id"])

    if not hits:
        print("[lookup-terms] no terminology matches found.")
        return

    print(f"[lookup-terms] {len(hits)} matches:\n")
    for src, info in sorted(hits.items(), key=lambda x: -len(x[0])):
        seg_ids = info["seg_ids"]
        id_str = f"  (segs: {seg_ids})" if len(seg_ids) <= 5 else f"  ({len(seg_ids)} segs)"
        tgt_str = " | ".join(s["target"] for s in info["senses"])
        print(f"  {src} → {tgt_str}{id_str}")


# ── apply-fixes ───────────────────────────────────────────────────────────────

def _protected_ids(args) -> set[int]:
    ids: set[int] = set()
    if getattr(args, "protected_ids", None):
        ids.update(int(x.strip()) for x in args.protected_ids.split(",") if x.strip())
    if getattr(args, "protected_file", None):
        data = read_json(args.protected_file)
        if isinstance(data, dict):
            data = data.get("protected_ids") or data.get("segments") or []
        for item in data:
            if isinstance(item, int):
                ids.add(item)
            elif isinstance(item, dict):
                sid = item.get("id", item.get("seg_id", item.get("segment_id")))
                if sid is not None:
                    ids.add(int(sid))
    return ids


def _state_protected_ids(state) -> set[int]:
    return {s["id"] for s in state.get("segments", []) if s.get("protected")}


def _scrub_protected_entries(errors_data: list, protected_ids: set[int]) -> int:
    changed = 0
    for entry in errors_data:
        if entry.get("id") in protected_ids:
            if entry.get("errors") or entry.get("corrected"):
                changed += len(entry.get("errors", [])) or 1
            entry["errors"] = []
            entry["corrected"] = None
    return changed


def cmd_protect_segments(args):
    state_path = Path(args.state)
    state = read_json(state_path)
    ids = _protected_ids(args)
    if not ids:
        print("[protect-segments] no ids supplied; state unchanged.")
        return

    seg_by_id = {s["id"]: s for s in state.get("segments", [])}
    valid = sorted(sid for sid in ids if sid in seg_by_id)
    unknown = sorted(sid for sid in ids if sid not in seg_by_id)
    for sid in valid:
        seg = seg_by_id[sid]
        seg["protected"] = True
        seg["protected_reason"] = args.reason
        seg["corrected"] = None

    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    out_path = Path(args.out) if args.out else state_path.parent / "tm_protected.json"
    payload = {
        "protected_ids": valid,
        "reason": args.reason,
        "source": "agent_decision",
    }
    if unknown:
        payload["unknown_ids"] = unknown
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[protect-segments] protected {len(valid)} segment(s) → {state_path}")
    print(f"[protect-segments] protected file → {out_path}")
    if unknown:
        print(f"[protect-segments] ignored unknown ids: {unknown[:20]}")


def cmd_build_results(args):
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    entries = normalize_check_entries(
        json.loads(Path(args.checks).read_text(encoding="utf-8")),
        label=args.checks,
    )
    segments = state["segments"]
    state_ids = {segment["id"] for segment in segments}
    check_ids = {entry["id"] for entry in entries}
    missing = sorted(state_ids - check_ids)
    extra = sorted(check_ids - state_ids)
    if missing or extra:
        sys.exit(
            f"[build-results] check ids must match state segment ids: "
            f"missing={missing} extra={extra}"
        )
    results = build_results(segments, entries)
    Path(args.out).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def cmd_apply_fixes(args):
    state_path = Path(args.state)
    state = read_json(state_path)
    errors_data = read_json(args.errors)
    protected_ids = _protected_ids(args) | _state_protected_ids(state)
    scrubbed = _scrub_protected_entries(errors_data, protected_ids)
    if scrubbed:
        Path(args.errors).write_text(json.dumps(errors_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[apply-fixes] scrubbed {scrubbed} protected-segment issue(s) from {args.errors}")
    scorecard_profile = load_scorecard_profile(getattr(args, "scorecard_profile", "legacy"))

    seg_ids = {s["id"] for s in state["segments"]}
    issues = _validate_errors(errors_data, seg_ids, scorecard_profile)
    for msg in issues:
        print(f"[validate] {msg}")

    attempted_entries = {
        e["id"]: e
        for e in errors_data
        if e.get("corrected")
        and not any(error.get("protected") for error in (e.get("errors") or []))
    }
    attempted = {sid: entry["corrected"] for sid, entry in attempted_entries.items()}
    corrections = {sid: text for sid, text in attempted.items() if sid not in protected_ids}
    protected_skipped = [
        {"id": sid, "reason": "TM_100_MATCH", "attempted": text}
        for sid, text in attempted.items()
        if sid in protected_ids
    ]
    skipped = protected_skipped
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
        "protected_ids": sorted(protected_ids),
        "skipped_corrections": skipped,
    }
    history.append(cur_entry)
    state["error_history"] = history

    next_iter = cur_iter + (1 if corrections or protected_skipped else 0)
    for seg in state["segments"]:
        if seg["id"] in protected_ids:
            seg["protected"] = True
            seg["protected_reason"] = "TM_100_MATCH"
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
    iter_out = state_path.parent / (_job_label(state_path) + f"_lqe_iter{cur_iter}.xlsx")
    _build_xlsx(state, [cur_entry], iter_score, threshold, iter_out, getattr(args, "scorecard_profile", "legacy"))


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


def _validate_errors(errors_data: list, seg_ids: set, scorecard_profile: dict | None = None) -> list[str]:
    issues = []
    valid_categories = set(scorecard_category_order(scorecard_profile))
    for entry in errors_data:
        sid = entry.get("id")
        if sid not in seg_ids:
            issues.append(f"[seg {sid}] 未知 segment id")
            continue
        errs = entry.get("errors", [])
        for e in errs:
            raw_cat = e.get("category", "")
            cat = normalize_category_for_profile(raw_cat, scorecard_profile)
            sev = e.get("severity", "")
            if cat not in valid_categories:
                issues.append(f"[seg {sid}] 非法 category: '{raw_cat}'")
            if sev not in _VALID_SEVERITIES:
                issues.append(f"[seg {sid}] 非法 severity: '{sev}'")
            new_sev = apply_severity(cat, sev, scorecard_profile)
            if new_sev != sev:
                issues.append(f"[seg {sid}] {cat} severity {sev}→{new_sev} (auto-corrected)")
                e["severity"] = new_sev
    return issues


def _s(cell, fill=None, font=None, align=None):
    if fill:  cell.fill  = fill
    if font:  cell.font  = font
    if align: cell.alignment = align


def _build_xlsx(state, history, score, threshold, out_path, scorecard_profile_id="legacy"):
    scorecard_profile = load_scorecard_profile(scorecard_profile_id)
    categories = scorecard_category_order(scorecard_profile)
    segments = state["segments"]
    seg_map = {s["id"]: s for s in segments}
    cat_counts: dict[str, dict[str, int]] = {
        cat: {"Neutral": 0, "Minor": 0, "Major": 0, "Critical": 0}
        for cat in categories
    }
    rep_counts: dict[str, dict[str, int]] = {
        cat: {"Neutral": 0, "Minor": 0, "Major": 0, "Critical": 0}
        for cat in categories
    }
    detail_rows: list[dict] = []
    all_protected_ids = set()
    for entry in history:
        all_protected_ids.update(entry.get("protected_ids", []))
    for seg in segments:
        if seg.get("protected"):
            all_protected_ids.add(seg["id"])
    max_iter = max((entry["iteration"] for entry in history), default=0)

    for entry in history:
        fixed = entry["iteration"] < max_iter
        for e_seg in entry["errors"]:
            seg = seg_map.get(e_seg["id"])
            if not seg:
                continue
            if seg["id"] in all_protected_ids:
                continue
            corrected = e_seg.get("corrected")
            processing = _processing_label(e_seg)
            for e in e_seg.get("errors", []):
                cat = normalize_category_for_profile(e.get("category", "Other"), scorecard_profile)
                sev = apply_severity(cat, e.get("severity", "Minor"), scorecard_profile)
                if e.get("repeated"):
                    if cat in rep_counts:
                        rep_counts[cat][sev] = rep_counts[cat].get(sev, 0) + 1
                elif cat in cat_counts:
                    cat_counts[cat][sev] = cat_counts[cat].get(sev, 0) + 1
                detail_rows.append({
                    "filename": Path(state["input_path"]).stem,
                    "seg_id":   seg["id"],
                    "source":   seg["source"],
                    "original": seg["target"],
                    "corrected": corrected,
                    "parent":   scorecard_category_parent(cat, scorecard_profile),
                    "category": cat,
                    "severity": sev,
                    "iteration": f"Iter {entry['iteration']}",
                    "comment":  ("[Repeated] " if e.get("repeated") else "") + e.get("comment", ""),
                    "fixed":    fixed,
                    "processing": processing,
                })

    total_counts = {"Neutral": 0, "Minor": 0, "Major": 0, "Critical": 0}
    total_rep    = {"Neutral": 0, "Minor": 0, "Major": 0, "Critical": 0}
    for c in cat_counts.values():
        for sev, n in c.items():
            total_counts[sev] += n
    for c in rep_counts.values():
        for sev, n in c.items():
            total_rep[sev] += n
    total_raw      = sum(raw_points(c, scorecard_profile) for c in cat_counts.values())
    total_weighted = sum(weighted_points(cat, c, scorecard_profile) for cat, c in cat_counts.items())

    wb  = openpyxl.Workbook()
    ws  = wb.active
    ws.title = "LQA Scorecard"
    status   = "PASS" if score >= threshold else "FAIL"

    # ── 导读 sheet（插最前）：说明后两个 sheet 的用处 + 建议使用思路 ──
    intro = wb.create_sheet("说明·导读", 0)
    _wrap = Alignment(wrap_text=True, vertical="top")
    for r in [
        ("LQE 质检报告 · 导读", "", "", ""),
        ("", "", "", ""),
        (f"本报告 3 个 sheet：本「说明·导读」+ 后两个正文。阈值 {threshold}；本次 {status}（{score:.2f} 分）。", "", "", ""),
        ("", "", "", ""),
        ("Sheet", "是什么", "给谁看", "怎么用"),
        ("LQA Scorecard（第 2 个）", "计分卡：过/不过 + 分数 + 错误(类别×严重度)分布 + 罚分", "PM / 客户", f"先看这里拿整体判定：是否达标(阈值 {threshold})、差在哪类"),
        ("LQE Results（第 3 个）", "逐段明细：原文 / 原译 / 建议译文 / 错误详情 / 处理方式", "审校 / 译员", "逐段审阅「建议译文」与「处理方式」，结合错误详情处理"),
        ("", "", "", ""),
        ("建议使用思路：", "", "", ""),
        ("1. PM 先看「LQA Scorecard」拿整体判定（分数 / 状态 / 错误分布）。", "", "", ""),
        ("2. 审校/译员到「LQE Results」，结合「建议译文」「处理方式」和「错误详情」逐段处理。", "", "", ""),
        ("3. 「建议译文」留空时保留原译；「处理方式」说明是否仅提醒或需要人工确认。", "", "", ""),
        ("4. 修正若要落地，按项目流程（如改在线 memoQ）。", "", "", ""),
        ("5. 已保护内容不修改；需要人工确认的问题由审校人员判断。", "", "", ""),
    ]:
        intro.append(r)
        for c in intro[intro.max_row]:
            c.alignment = _wrap
    intro["A1"].font = Font(bold=True, size=13, color="073763")
    for c in intro[5]:                       # 表头行
        c.fill = _DARK_BLUE; c.font = _WHITE_FONT
    intro["A9"].font = Font(bold=True)
    for col, w in zip("ABCD", [22, 50, 12, 46]):
        intro.column_dimensions[col].width = w
    wb.active = intro

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

    source_lang = state.get("source_lang") or "-"
    target_lang = state.get("target_lang") or "-"
    info = [
        ("File", Path(state["input_path"]).name, "Wordcount", state.get("wordcount", 0)),
        ("Source language", source_lang, "Target language", target_lang),
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
        (3,total_counts.get("Neutral",0)),(4,total_rep.get("Neutral",0)),
        (5,total_counts.get("Minor",0)),  (6,total_rep.get("Minor",0)),
        (7,total_counts.get("Major",0)),  (8,total_rep.get("Major",0)),
        (9,total_counts.get("Critical",0)),(10,total_rep.get("Critical",0)),
        (11,total_raw),(12,round(total_weighted,2)),
    ]:
        c = ws.cell(row=cur_row, column=col, value=val)
        _s(c, fill=_ORANGE, align=_CENTER)
    cur_row += 1

    for cat in categories:
        counts = cat_counts[cat]
        r = raw_points(counts, scorecard_profile)
        w = weighted_points(cat, counts, scorecard_profile)
        ws.row_dimensions[cur_row].height = 14.25
        rep = rep_counts[cat]
        for col, val in [
            (1,cat),(2,scorecard_category_weight(cat, scorecard_profile)),
            (3,counts.get("Neutral",0)),(4,rep.get("Neutral",0)),
            (5,counts.get("Minor",0)),  (6,rep.get("Minor",0)),
            (7,counts.get("Major",0)),  (8,rep.get("Major",0)),
            (9,counts.get("Critical",0)),(10,rep.get("Critical",0)),
            (11,r),(12,round(w,2)),
        ]:
            c = ws.cell(row=cur_row, column=col, value=val)
            _s(c, align=_CENTER)
        cur_row += 1

    ws.row_dimensions[cur_row].height = 6
    cur_row += 1

    ws.row_dimensions[cur_row].height = 14.25
    for col, hdr in enumerate(
        ["File name","Segment #","Source text","原译",
         "建议译文","Error category","Error sub-category",
         "Error severity","Iteration","Reviewer's comment","处理方式","TM Protected","TM Evidence"], start=1):
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
            (11, dr["processing"]),
            (12, "Yes" if dr["seg_id"] in all_protected_ids else "No"),
            (13, "TM_100_MATCH" if dr["seg_id"] in all_protected_ids else ""),
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

    current_entries = {e["id"]: e for e in history[-1].get("errors", [])} if history else {}
    report_headers = list(state["headers"])
    target_col = state.get("target_col", 1)
    try:
        target_index = int(target_col)
    except (ValueError, TypeError):
        target_index = report_headers.index(target_col) if target_col in report_headers else 1
    if 0 <= target_index < len(report_headers):
        report_headers[target_index] = "原译"

    ws2_headers = report_headers + ["建议译文", "处理方式", "错误详情", "LQE_Iter", "TM Protected", "TM Evidence"]
    for ci, h in enumerate(ws2_headers, start=1):
        c = ws2.cell(row=1, column=ci, value=h)
        _s(c, fill=_DARK_BLUE, font=_WHITE_FONT, align=_CENTER)
    ws2.row_dimensions[1].height = 15.0

    for ri, (raw_row, seg) in enumerate(zip(state["rows_raw"], segments), start=2):
        is_protected = seg["id"] in all_protected_ids
        current_entry = current_entries.get(seg["id"])
        entry = current_entry if current_entry is not None else {
            "errors": [],
            "corrected": seg.get("corrected"),
        }
        errs = [] if is_protected else entry.get("errors", [])
        has_error = bool(errs)
        if is_protected:
            processing_entry = {"errors": [{"protected": True}], "corrected": None}
        else:
            processing_entry = entry
        processing = _processing_label(processing_entry)
        corrected = entry.get("corrected")
        suggestion = "" if processing == "已保护，不修改" else (corrected or "")
        row_fill = _ORANGE if has_error else _GREEN_LIGHT if (is_protected or suggestion) else None
        row_data = list(raw_row) + [
            suggestion,
            processing,
            _fmt_errors(errs),
            seg.get("iter", 0),
            "Yes" if is_protected else "No",
            seg.get("protected_reason") or ("TM_100_MATCH" if is_protected else ""),
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
    for ci, w in enumerate([35, 45, 22, 8, 12, 18], start=n_orig + 1):
        ws2.column_dimensions[get_column_letter(ci)].width = w

    wb.save(str(out_path))
    print(f"[lqe_io] Output → {out_path}")


def cmd_write(args):
    state_path = Path(args.state)
    state = read_json(state_path)
    final_errors_data = read_json(args.errors)
    protected_ids = _state_protected_ids(state)
    scrubbed = _scrub_protected_entries(final_errors_data, protected_ids)
    if scrubbed:
        Path(args.errors).write_text(json.dumps(final_errors_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[write] scrubbed {scrubbed} protected-segment issue(s) from {args.errors}")
    score = float(args.score)

    final_entry = {
        "iteration": state.get("iteration", 0),
        "score": score,
        "errors": final_errors_data,
        "corrections_count": 0,
        "protected_ids": sorted(protected_ids),
    }

    history = state.get("error_history", [])
    final_iter = state.get("iteration", 0)
    skipped_corrections = [
        skipped
        for entry in history
        if entry.get("iteration") == final_iter
        for skipped in entry.get("skipped_corrections", [])
    ]
    if skipped_corrections:
        final_entry["skipped_corrections"] = skipped_corrections
    history = [
        entry for entry in history if entry.get("iteration") != final_iter
    ]
    history.append(final_entry)
    state["error_history"] = history
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    src = Path(state["input_path"])
    out_path = state_path.parent / (_job_label(state_path) + "_lqe.xlsx")
    _build_xlsx(state, history, score, args.threshold, out_path, args.scorecard_profile)


# ── pre-check（实现在 lqe_checks.py）─────────────────────────────────────────

def cmd_pre_check(args):
    from lqe_checks import run_pre_check
    run_pre_check(Path(args.state), Path(args.out) if args.out else None)


# ── export ───────────────────────────────────────────────────────────────────

def cmd_export(args):
    state_path = Path(args.state)
    state = read_json(state_path)
    segments = state["segments"]
    seg_map = {s["id"]: s for s in segments}
    result_entries = {
        segment["id"]: {
            "errors": [],
            "corrected": segment.get("corrected"),
        }
        for segment in segments
    }

    if getattr(args, "errors", None):
        try:
            overlay_entries = verify_results(
                segments,
                read_json(args.errors),
                str(args.errors),
            )
        except CheckFormatError as exc:
            sys.exit(f"[export] {exc}")
        for e in overlay_entries:
            seg = seg_map.get(e["id"])
            if seg is None:
                continue
            seg["corrected"] = e.get("corrected")
            result_entries[e["id"]] = e

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
    counts = {
        "建议修改": 0,
        "需要人工确认": 0,
        "保持原译": 0,
        "已保护": 0,
    }

    def export_kind(segment):
        if segment.get("protected"):
            return "已保护"
        label = _processing_label(result_entries[segment["id"]])
        if label == "已保护，不修改":
            return "已保护"
        if label in ("建议修改", "需要人工确认"):
            return label
        return "保持原译"

    def print_summary(out_path):
        print(
            f"[export] 建议修改 {counts['建议修改']} / "
            f"需要人工确认 {counts['需要人工确认']} / "
            f"保持原译 {counts['保持原译']} / "
            f"已保护 {counts['已保护']} → {out_path}"
        )

    if src_path.suffix.lower() in (".csv", ".tsv"):
        delim = "\t" if src_path.suffix.lower() == ".tsv" else ","
        raw_rows = list(csv.reader(io.StringIO(src_path.read_bytes().decode("utf-8-sig")), delimiter=delim))
        offset = 0 if no_header else 1
        for seg in segments:
            row_idx = offset + int(seg.get("row_index", seg.get("id", 0)))
            if row_idx < 0 or row_idx >= len(raw_rows):
                continue
            row = raw_rows[row_idx]
            kind = export_kind(seg)
            corrected = result_entries[seg["id"]].get("corrected")
            if kind != "已保护" and corrected and ti < len(row):
                row[ti] = corrected
            counts[kind] += 1
        out_path = state_path.parent / (_job_label(state_path) + "_corrected" + src_path.suffix.lower())
        enc = "utf-8-sig" if src_path.suffix.lower() == ".csv" else "utf-8"
        with out_path.open("w", newline="", encoding=enc) as f:
            csv.writer(f, delimiter=delim).writerows(raw_rows)
        print_summary(out_path)
        return

    wb = openpyxl.load_workbook(str(src_path))
    sheet_name = state.get("sheet_name")
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active

    start_row = 1 if no_header else 2
    for seg in segments:
        row_num = start_row + int(seg.get("row_index", seg.get("id", 0)))
        if row_num < start_row or row_num > ws.max_row:
            continue
        kind = export_kind(seg)
        corrected = result_entries[seg["id"]].get("corrected")
        if kind != "已保护" and corrected:
            ws.cell(row=row_num, column=ti + 1, value=corrected)
        counts[kind] += 1

    out_path = state_path.parent / (_job_label(state_path) + "_corrected.xlsx")
    wb.save(str(out_path))
    wb.close()
    print_summary(out_path)


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
    r.add_argument("--project", default=None, help="项目档案：projects/<名>/profile.json 或目录/文件路径；提供 SG/术语/词数基准/checks/confirmed_rules 默认值，显式参数优先")
    r.add_argument("--source-col", required=True, dest="source_col", help="列名或列索引（0-based，配合 --no-header）")
    r.add_argument("--target-col", required=True, dest="target_col", help="列名或列索引（0-based，配合 --no-header）")
    r.add_argument("--no-header", action="store_true", dest="no_header", help="文件无表头行，source-col/target-col 为整数索引")
    r.add_argument("--group-col", default=None, dest="group_col", help="成组文本（对联/题目）的组标识列名或索引；同组段落 Step 2 合并评估")
    terminology = r.add_mutually_exclusive_group()
    terminology.add_argument("--terminology", default=None, help="术语表文件路径（.csv/.tsv/.json/.xlsx）")
    terminology.add_argument("--no-terminology", action="store_true", dest="no_terminology",
                             help="禁用术语、专名和术语审计检查")
    r.add_argument("--style-guide", default=None, dest="style_guide", help="风格指南文件路径（.txt/.md/.docx/.xlsx）")
    r.add_argument("--target-lang", default=None, dest="target_lang",
                   help="目标语言代码（en/th/zh 等）；挂载 target_languages/<code>/ 目标语言属性。项目 profile 必须显式写 target_lang")
    r.add_argument("--source-lang", default=None, dest="source_lang",
                   help="源语言代码（zh/en 等）；项目 profile 必须显式写 source_lang，显式参数优先")
    r.add_argument("--wordcount-basis", default=None, choices=["target-words", "source-chars"],
                   dest="wordcount_basis",
                   help="词数基准：target-words=译文空格分词（EN 等）；source-chars=源文 CJK 字符数+拉丁词数（泰语等无空格译文用）")
    r.add_argument("--out", default="lqe_state.json")

    af = sub.add_parser("apply-fixes")
    af.add_argument("--state",     required=True)
    af.add_argument("--errors",    required=True)
    af.add_argument("--score",     default=None, help="本轮分数（来自 lqe_calc.py 输出）")
    af.add_argument("--threshold", type=float, default=98.0)
    af.add_argument("--scorecard-profile", default="legacy", dest="scorecard_profile",
                    help="评分卡 profile id/目录/profile.json 路径；默认 legacy（当前原有评分标准）")
    af.add_argument("--protected-ids", default=None, help="逗号分隔的 TM 100%% match segment ids")
    af.add_argument("--protected-file", default=None, help="TM 100%% match protected ids JSON 文件")

    ps = sub.add_parser("protect-segments")
    ps.add_argument("--state", required=True)
    ps.add_argument("--protected-ids", default=None, help="逗号分隔的已确认段 id")
    ps.add_argument("--protected-file", default=None, help="已确认段 id JSON 文件")
    ps.add_argument("--reason", default="TM_100_MATCH")
    ps.add_argument("--out", default=None, help="输出 protected ids JSON，默认 {job}/tm_protected.json")

    br = sub.add_parser("build-results")
    br.add_argument("--state", required=True)
    br.add_argument("--checks", required=True)
    br.add_argument("--out", required=True)

    w = sub.add_parser("write")
    w.add_argument("--state",     required=True)
    w.add_argument("--errors",    required=True)
    w.add_argument("--score",     required=True)
    w.add_argument("--threshold", type=float, default=98)
    w.add_argument("--scorecard-profile", default="legacy", dest="scorecard_profile",
                   help="评分卡 profile id/目录/profile.json 路径；默认 legacy（当前原有评分标准）")

    pc = sub.add_parser("pre-check")
    pc.add_argument("--state", required=True)
    pc.add_argument("--out", default=None, help="输出路径（默认 {job_dir}/errors_precheck.json）")

    lt = sub.add_parser("lookup-terms")
    lt.add_argument("--state", required=True)
    lt.add_argument("--ids", default=None, help="逗号分隔的 seg id，不传则扫描全部段落")

    ex = sub.add_parser("export")
    ex.add_argument("--state", required=True)
    ex.add_argument("--errors", default=None, help="可选 errors.json：state.corrected 为空时用其 corrected 填充建议修正（单轮 FAIL 导出用）")

    ic = sub.add_parser("ingest-corpus")
    ic.add_argument("--state",    required=True)
    ic.add_argument("--aipe-url", required=True, dest="aipe_url")

    args = p.parse_args()
    {
        "read":           cmd_read,
        "pre-check":      cmd_pre_check,
        "protect-segments": cmd_protect_segments,
        "build-results":  cmd_build_results,
        "apply-fixes":    cmd_apply_fixes,
        "write":          cmd_write,
        "export":         cmd_export,
        "lookup-terms":   cmd_lookup_terms,
        "ingest-corpus":  cmd_ingest_corpus,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
