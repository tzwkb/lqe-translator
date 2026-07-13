"""TDD tests for the TM ingest feature (tm_index.py).

Run:  python scripts/tm_index_test.py
Builds tiny .sdltm fixtures in a temp dir; nothing written into the repo.
"""
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import tm_index  # RED until tm_index.py exists

PASS, FAIL = [], []
TMP = Path(tempfile.mkdtemp(prefix="tm_tests_"))


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f"  ✗ {name}  {detail}")


def seg(*values, culture="zh-CN"):
    inner = "".join(f"<Text><Value>{v}</Value></Text>" for v in values)
    return f'<Segment><Elements>{inner}</Elements><CultureName>{culture}</CultureName></Segment>'


def make_sdltm(path, units):
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE translation_units(source_segment TEXT, target_segment TEXT)")
    con.executemany(
        "INSERT INTO translation_units(source_segment, target_segment) VALUES(?,?)", units)
    con.commit()
    con.close()


# ── loader: extract Value text, unescape entities, ignore Tag, concat values ──
def test_loader():
    fx = TMP / "a.sdltm"
    make_sdltm(fx, [
        (seg("即将开始"), seg("Starting Soon", culture="en-US")),
        (seg("A &amp; B"), seg("X", culture="en-US")),
        ('<Segment><Elements><Text><Value>点</Value></Text>'
         '<Tag><x>1</x></Tag><Text><Value>击</Value></Text></Elements></Segment>',
         seg("Click", culture="en-US")),
    ])
    units = list(tm_index.iter_units_sdltm(fx))
    check("loader basic pair", ("即将开始", "Starting Soon") in units, units)
    check("loader entity unescape", ("A & B", "X") in units, units)
    check("loader multi-value concat + tag ignored", ("点击", "Click") in units, units)


# ── norm: strip + collapse internal whitespace + NFC ──────────────────────────
def test_norm():
    check("norm strip+collapse", tm_index.norm("  a   b ") == "a b")
    check("norm nfc combining", tm_index.norm("é") == "é")  # e+◌́ → é
    check("norm none-safe", tm_index.norm(None) == "")


# ── build_index: {norm_src: [norm_tgt...]}, 1:n variant set, dedup ────────────
def test_build_index():
    fx = TMP / "b.sdltm"
    make_sdltm(fx, [
        (seg("即将开始"), seg("Starting Soon", culture="en-US")),
        (seg("天"), seg("day(s)", culture="en-US")),
        (seg("天"), seg("d", culture="en-US")),
        (seg("天"), seg("day(s)", culture="en-US")),  # dup → deduped
    ])
    idx = tm_index.build_index([fx])
    check("index key→target", idx.get("即将开始") == ["Starting Soon"], idx)
    check("index 1:n variant set", set(idx.get("天", [])) == {"day(s)", "d"}, idx)
    check("index dedups targets", len(idx.get("天", [])) == 2, idx)


# ── match_protected: protect iff src hits AND tgt ∈ target set ───────────
def test_match_protected():
    idx = {"即将开始": ["Starting Soon"], "天": ["day(s)", "d"]}
    segs = [
        {"id": 0, "source": "即将开始", "target": "Starting Soon"},   # lock
        {"id": 1, "source": "即将开始", "target": "Begin Now"},        # tgt differs
        {"id": 2, "source": "天", "target": "d"},                                  # variant set → lock
        {"id": 3, "source": "未知", "target": "x"},                            # src absent
        {"id": 4, "source": " 即将开始 ", "target": " Starting Soon "},  # norm → lock
    ]
    protected = set(tm_index.match_protected(segs, idx))
    check("protect exact src+tgt", 0 in protected)
    check("no protect when tgt differs", 1 not in protected)
    check("protect via variant set", 2 in protected)
    check("no protect when src absent", 3 not in protected)
    check("protect after normalization", 4 in protected)


def run(*argv):
    return subprocess.run([sys.executable, str(SCRIPTS / "tm_index.py"), *argv],
                          capture_output=True, text=True)


def test_cli_build_and_match():
    fx = TMP / "cli.sdltm"
    make_sdltm(fx, [
        (seg("即将开始"), seg("Starting Soon", culture="en-US")),
        (seg("天"), seg("d", culture="en-US")),
    ])
    idxp = TMP / "idx.json"
    r = run("build", "--libraries", str(fx), "--out", str(idxp))
    check("cli build rc", r.returncode == 0, r.stderr[-200:])
    check("cli build wrote index", idxp.exists(), "no index produced")
    if idxp.exists():
        idx = json.loads(idxp.read_text(encoding="utf-8"))
        check("cli build content", idx.get("即将开始") == ["Starting Soon"], idx)
    statep = TMP / "state.json"
    statep.write_text(json.dumps({"segments": [
        {"id": 0, "source": "即将开始", "target": "Starting Soon"},
        {"id": 1, "source": "即将开始", "target": "Begin Now"},
        {"id": 2, "source": "天", "target": "d"},
    ]}, ensure_ascii=False), encoding="utf-8")
    protected_path = TMP / "protected.json"
    r = run("tm-match", "--state", str(statep), "--index", str(idxp), "--out-protected", str(protected_path))
    check("cli tm-match rc", r.returncode == 0, r.stderr[-200:])
    check("cli tm-match wrote protected", protected_path.exists(), "no protected file")
    if protected_path.exists():
        protected = json.loads(protected_path.read_text(encoding="utf-8"))
        check("cli protected_ids", protected.get("protected_ids") == [0, 2], protected)


def run_lqe(*argv):
    return subprocess.run([sys.executable, str(SCRIPTS / "lqe_io.py"), *argv],
                          capture_output=True, text=True)


def test_integration():
    """xlsx → lqe_io read → rag build → tm-match → lqe_io apply-fixes:
    a locked (exact source+target) segment must survive uncorrected; an edited
    one (source in TM, target changed) must NOT lock and gets corrected."""
    import openpyxl
    inp = TMP / "tm_in.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["原文", "译文"])
    ws.append(["点击开始", "Click Start"])    # 0 exact → lock
    ws.append(["退出游戏", "Exit Game"])       # 1 src in TM, tgt edited → no lock
    ws.append(["保存进度", "Save Progress"])   # 2 not in TM
    wb.save(inp)
    tm = TMP / "tm.sdltm"
    make_sdltm(tm, [
        (seg("点击开始"), seg("Click Start", culture="en-US")),
        (seg("退出游戏"), seg("Quit Game", culture="en-US")),
    ])
    job = TMP / "jr"
    r = run_lqe("read", "--input", str(inp), "--source-col", "原文", "--target-col", "译文",
                "--target-lang", "en", "--out", str(job / "state.json"))
    check("intg read rc", r.returncode == 0, r.stderr[-200:])
    r = run("build", "--libraries", str(tm), "--out", str(job / "tm_index.json"))
    check("intg build rc", r.returncode == 0, r.stderr[-200:])
    r = run("tm-match", "--state", str(job / "state.json"), "--index", str(job / "tm_index.json"),
            "--out-protected", str(job / "tm_protected.json"))
    check("intg tm-match rc", r.returncode == 0, r.stderr[-200:])
    protected = json.loads((job / "tm_protected.json").read_text(encoding="utf-8"))
    check("intg protects only exact match", protected.get("protected_ids") == [0], protected)
    errors = [
        {"id": 0, "errors": [{"category": "Mistranslation", "severity": "Major", "comment": "x"}],
         "corrected": "SHOULD BE SKIPPED"},
        {"id": 1, "errors": [{"category": "Mistranslation", "severity": "Major", "comment": "x"}],
         "corrected": "Quit Game"},
        {"id": 2, "errors": [], "corrected": None},
    ]
    (job / "errors.json").write_text(json.dumps(errors, ensure_ascii=False), encoding="utf-8")
    r = run_lqe("apply-fixes", "--state", str(job / "state.json"), "--errors", str(job / "errors.json"),
                "--protected-file", str(job / "tm_protected.json"))
    check("intg apply-fixes rc", r.returncode == 0, r.stderr[-200:])
    st = json.loads((job / "state.json").read_text(encoding="utf-8"))
    segs = {s["id"]: s for s in st["segments"]}
    check("intg protected seg not corrected",
          segs[0].get("corrected") is None and segs[0].get("protected") is True, segs[0])
    check("intg non-protected seg corrected", segs[1].get("corrected") == "Quit Game", segs[1])


def run_all():
    for t in (test_loader, test_norm, test_build_index, test_match_protected,
              test_cli_build_and_match, test_integration):
        t()
    total = len(PASS) + len(FAIL)
    print(f"{len(PASS)}/{total} passed" + (f"  FAILED: {FAIL}" if FAIL else "  — all green"))
    shutil.rmtree(TMP, ignore_errors=True)
    return not FAIL


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
