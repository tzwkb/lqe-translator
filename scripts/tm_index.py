"""TM ingest for LQE.

Parse a translation memory → exact-match index → segment ids marked as protected.
Pluggable loaders (one function per format, picked by file extension); only
`.sdltm` is implemented. All local: exact normalized-string match, no
embeddings / no external API — source text never leaves the machine.
"""
import html
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

_VALUE = re.compile(r"<Value>(.*?)</Value>", re.S)


def _segment_text(xml):
    """Concatenate all <Value> text in an SDLTM segment XML, unescaping entities.
    Inline <Tag> elements carry no <Value>, so they are ignored."""
    if not xml:
        return ""
    return "".join(html.unescape(v) for v in _VALUE.findall(xml))


def iter_units_sdltm(path):
    """Yield (source_text, target_text) per translation unit in an .sdltm (SQLite)."""
    con = sqlite3.connect(str(path))
    try:
        for src, tgt in con.execute(
                "SELECT source_segment, target_segment FROM translation_units"):
            yield _segment_text(src), _segment_text(tgt)
    finally:
        con.close()


# extension → loader; add a format = add one function + one entry here
LOADERS = {".sdltm": iter_units_sdltm}


def norm(s):
    """Strip, collapse internal whitespace, Unicode NFC. None-safe."""
    return unicodedata.normalize("NFC", re.sub(r"\s+", " ", (s or "").strip()))


def build_index(libraries):
    """Build {norm(source): [norm(target), ...]} from TM files. Targets deduped;
    a source with several distinct targets keeps all (acceptable-variant set)."""
    index = {}
    for lib in libraries:
        loader = LOADERS[Path(lib).suffix.lower()]
        for src, tgt in loader(lib):
            ns = norm(src)
            if not ns:
                continue
            nt = norm(tgt)
            bucket = index.setdefault(ns, [])
            if nt not in bucket:
                bucket.append(nt)
    return index


def match_protected(segments, index):
    """Return ids of segments whose source exactly matches the index AND whose
    target equals one of that source's approved targets (= confirmed 100% match)."""
    protected = []
    for seg in segments:
        targets = index.get(norm(seg.get("source", "")))
        if targets and norm(seg.get("target", "")) in targets:
            protected.append(seg["id"])
    return protected


# ── CLI ───────────────────────────────────────────────────────────────────────

def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_build(args):
    index = build_index(args.libraries)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    print(f"[tm_index] {len(index)} source keys → {args.out}")


def cmd_tm_match(args):
    state = _read_json(args.state)
    index = _read_json(args.index)
    protected = match_protected(state["segments"], index)
    out = Path(args.out_protected)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"protected_ids": protected}, ensure_ascii=False), encoding="utf-8")
    print(f"[tm_index] 已保护 {len(protected)}/{len(state['segments'])} 段 → {args.out_protected}")


def main():
    import argparse
    ap = argparse.ArgumentParser(prog="tm_index", description="本地生成 TM 精确匹配索引并标记已保护段")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="parse TM file(s) → exact-match index json")
    b.add_argument("--libraries", nargs="+", required=True, help="TM files (.sdltm)")
    b.add_argument("--out", required=True, help="output index json path")

    m = sub.add_parser("tm-match", help="用 state.json 和索引生成已保护段 id JSON")
    m.add_argument("--state", required=True)
    m.add_argument("--index", required=True)
    m.add_argument("--out-protected", dest="out_protected", required=True)

    args = ap.parse_args()
    {"build": cmd_build, "tm-match": cmd_tm_match}[args.cmd](args)


if __name__ == "__main__":
    main()
