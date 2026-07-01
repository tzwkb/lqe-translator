"""Self-contained regression suite for the LQE skill.

Run:  python scripts/run_tests.py
Covers: all 23 builtin pre-checks, language-attribute derivation, project
profiles (method C), custom count_match, N4 repeat dedup in calc, wordcount
chain + guard, and a smoke test for lqe_batch.
Fixtures are built in a temp dir; nothing is written into the repo.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import openpyxl

SCRIPTS = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="lqe_tests_"))
PASS, FAIL = [], []


def run(script, *argv, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *argv],
                          capture_output=True, text=True, cwd=cwd or TMP)


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f"  ✗ {name}  {detail}")


def make_xlsx(path, rows, headers=("原文", "译文")):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))
    wb.save(path)


def load_errs(path):
    return {r["id"]: [e["comment"] for e in r["errors"]] for r in json.loads(Path(path).read_text(encoding="utf-8"))}


def has(res, i, kw):
    return any(kw in c for c in res.get(i, []))


# ── T1: EN main fixture — N5-N9 / #3 / #7 / #10 / R5 ─────────────────────────
def t1():
    rows = [
        ('你好。', 'Hello'),                          # 0 N5 src-terminal missing
        ('你好', 'Hello.'),                           # 1 N5 tgt adds .
        ('开始！', 'Start!'),                         # 2 N5 ok
        ('你有三次机会。', 'You have chances.'),       # 3 N6 missing
        ('你有三次机会。', 'You have three chances.'), # 4 N6 ok word
        ('一起出发吧。', 'Let us set off together.'),  # 5 N6 no classifier
        ('第五章开启。', 'Chapter 5 unlocked.'),       # 6 N6 ordinal ok
        ('获得两个金币。', 'Got 2 coins.'),            # 7 N6 两 ok
        ('那只猫。', 'The the cat.'),                  # 8 N7 repeat
        ('我受够了。', 'I had had enough.'),           # 9 N7 whitelist
        ('苹果酱。', 'AppLe sauce.'),                  # 10 N8 mixed
        ('我的手机。', 'Check my iPhone.'),            # 11 N8 exempt
        ('对战模式。', 'PvP mode.'),                   # 12 N8 exempt
        ('（测试）完成。', '(test done.'),             # 13 N9 unbalanced
        ('没事。', "It's fine."),                      # 14 N9 apostrophe ok
        ('恢复生命值。', 'Restore hp.'),               # 15 #7 acronym case
        ('恢复生命值。', 'Restore HP.'),               # 16 #7 ok
        ('<b>你</b>好。', 'Hello there.'),             # 17 #3 angle tag lost
        ('等等…', 'Wait…'),                           # 18 #10 majority
        ('还有…', 'And…'),                            # 19 #10 majority
        ('走吧…', 'Go...'),                           # 20 #10 minority
        ('他说：「好」', 'He said 『fine』'),           # 21 R5 corner quotes
    ]
    make_xlsx(TMP / "en_main.xlsx", rows)
    (TMP / "tb.json").write_text(json.dumps(
        [{"source": "生命值", "target": "HP", "status": "Approved"}], ensure_ascii=False), encoding="utf-8")
    r = run("lqe_io.py", "read", "--input", str(TMP / "en_main.xlsx"),
            "--source-col", "原文", "--target-col", "译文", "--target-lang", "en",
            "--terminology", str(TMP / "tb.json"), "--out", str(TMP / "j1/state.json"))
    check("T1 read rc", r.returncode == 0, r.stderr[-200:])
    r = run("lqe_io.py", "pre-check", "--state", str(TMP / "j1/state.json"), "--out", str(TMP / "j1/pc.json"))
    check("T1 pre-check rc", r.returncode == 0, r.stderr[-200:])
    res = load_errs(TMP / "j1/pc.json")
    for name, cond in [
        ("N5 src-terminal", has(res, 0, "target does not")),
        ("N5 tgt adds", has(res, 1, "adds terminal")),
        ("N5 clean", not has(res, 2, "terminal")),
        ("N6 missing", has(res, 3, "三次")),
        ("N6 word ok", not has(res, 4, "Chinese numeral")),
        ("N6 no classifier", not has(res, 5, "Chinese numeral")),
        ("N6 ordinal ok", not has(res, 6, "Chinese numeral")),
        ("N6 两 ok", not has(res, 7, "Chinese numeral")),
        ("N7 repeat", has(res, 8, "Repeated word")),
        ("N7 whitelist", not has(res, 9, "Repeated word")),
        ("N8 mixed", has(res, 10, "Mixed case")),
        ("N8 iPhone", not has(res, 11, "Mixed case")),
        ("N8 PvP", not has(res, 12, "Mixed case")),
        ("N9 paren", has(res, 13, "Unbalanced")),
        ("N9 apostrophe", not has(res, 14, "Unbalanced") and not has(res, 14, "quote")),
        ("#7 hp", has(res, 15, "Acronym case")),
        ("#7 HP ok", not has(res, 16, "Acronym")),
        ("#3 tag", has(res, 17, "angle-bracket tag")),
        ("#10 minority", has(res, 20, "Ellipsis style")),
        ("#10 majority clean", not has(res, 18, "Ellipsis") and not has(res, 19, "Ellipsis")),
        ("R5 corner quotes", has(res, 21, "『")),
        ("N2 catches 3/4 divergence", has(res, 4, "Same source translated differently")),
    ]:
        check(f"T1 {name}", cond, str(res.get(0, ''))[:80])


# ── T2: N1 pinyin / N2 consistency / group-col ───────────────────────────────
def t2():
    rows = [
        ('前往张家口。', 'Go to Zhangjiakou.', ''),
        ('他叫青河。', 'His name is Qinghe.', ''),
        ('平安街到了。', "Ping'an Street ahead.", ''),
        ('坐出租车。', 'Take a Taxi today.', ''),
        ('改变战局。', 'Change the battle.', ''),
        ('点击开始', 'Click Start', ''),
        ('点击开始', 'Tap Begin', ''),
        ('这是一段超过二十个字符的长句子用于测试异源同译规则。', 'This long sentence is reused verbatim.', ''),
        ('另一段完全不同但同样超过二十字符的源文本内容在此。', 'This long sentence is reused verbatim.', ''),
        ('确定', 'OK', ''),
        ('好的', 'OK', ''),
        ('上联内容', 'First line', 'G1'),
    ]
    make_xlsx(TMP / "n1n2.xlsx", rows, headers=("原文", "译文", "组"))
    run("lqe_io.py", "read", "--input", str(TMP / "n1n2.xlsx"), "--source-col", "原文",
        "--target-col", "译文", "--group-col", "组", "--target-lang", "en",
        "--out", str(TMP / "j2/state.json"))
    run("lqe_io.py", "pre-check", "--state", str(TMP / "j2/state.json"), "--out", str(TMP / "j2/pc.json"))
    res = load_errs(TMP / "j2/pc.json")
    for name, cond in [
        ("N1 zh", has(res, 0, "pinyin residue: 'Zhangjiakou'")),
        ("N1 q", has(res, 1, "pinyin residue: 'Qinghe'")),
        ("N1 apostrophe", has(res, 2, "Ping'an")),
        ("N1 whitelist", not has(res, 3, "pinyin")),
        ("N1 ch-not-strong", not has(res, 4, "pinyin")),
        ("N2 base clean", not has(res, 5, "Same source")),
        ("N2 divergent", has(res, 6, "Same source translated differently")),
        ("N2 conv base clean", not has(res, 7, "reused")),
        ("N2 conv flagged", has(res, 8, "reused for different sources")),
        ("N2 short exempt", not has(res, 10, "reused")),
    ]:
        check(f"T2 {name}", cond)
    state = json.loads((TMP / "j2/state.json").read_text(encoding="utf-8"))
    check("T2 group stored", state["segments"][11].get("group") == "G1")


# ── T3: thai attribute derivation silences latin/sentence checks ─────────────
def t3():
    rows = [('你好。', 'สวัสดี'), ('那只猫。', 'แมว the the'), ('苹果。', 'AppLe แอปเปิ้ล')]
    make_xlsx(TMP / "th.xlsx", rows)
    r = run("lqe_io.py", "read", "--input", str(TMP / "th.xlsx"), "--source-col", "原文",
            "--target-col", "译文", "--target-lang", "th", "--out", str(TMP / "j3/state.json"))
    state = json.loads((TMP / "j3/state.json").read_text(encoding="utf-8"))
    check("T3 basis from lang attrs", state["wordcount_basis"] == "source-chars")
    check("T3 lang notes copied", bool(state["lang_notes_path"]) and "ครับ" in Path(state["lang_notes_path"]).read_text(encoding="utf-8"))
    r = run("lqe_io.py", "pre-check", "--state", str(TMP / "j3/state.json"), "--out", str(TMP / "j3/pc.json"))
    check("T3 derivation printed", "terminal_punct" in r.stdout and "word_repeat" in r.stdout)
    cs = [c for v in load_errs(TMP / "j3/pc.json").values() for c in v]
    check("T3 N5/N7/N8 silent", not any(k in c for c in cs for k in ("terminal", "Repeated word", "Mixed case")))
    # guard: explicit target-words on no-delim language warns
    r = run("lqe_io.py", "read", "--input", str(TMP / "th.xlsx"), "--source-col", "原文",
            "--target-col", "译文", "--target-lang", "th", "--wordcount-basis", "target-words",
            "--out", str(TMP / "j3b/state.json"))
    check("T3 word_delim guard", "no word delimiter" in r.stderr)


# ── T4: method C (project profiles) + wwm N3 custom ──────────────────────────
def t4():
    make_xlsx(TMP / "tiny.xlsx", [('他说：「你好」', 'เขาพูดว่า สวัสดี')])
    for proj, lang, basis in [("nrc/th", "th", "source-chars"), ("nrc/en", "en", "target-words"),
                              ("wwm/en", "en", "target-words")]:
        slug = proj.replace("/", "-")
        r = run("lqe_io.py", "read", "--input", str(TMP / "tiny.xlsx"), "--source-col", "原文",
                "--target-col", "译文", "--project", proj, "--out", str(TMP / f"j4-{slug}/state.json"))
        ok = r.returncode == 0
        check(f"T4 {proj} read", ok, r.stderr[-200:])
        if not ok:
            continue
        s = json.loads((TMP / f"j4-{slug}/state.json").read_text(encoding="utf-8"))
        check(f"T4 {proj} lang/basis", s["target_lang"] == lang and s["wordcount_basis"] == basis)
        check(f"T4 {proj} checks+adjud", bool(s["checks_path"]) and bool(s["adjudications_path"]))
    # wwm N3 roman numeral custom
    sp = TMP / "j4-wwm-en/state.json"
    s = json.loads(sp.read_text(encoding="utf-8"))
    s["segments"] = [{"id": 0, "source": "第二章。", "target": "Chapter II begins.",
                      "corrected": None, "max_len": None, "iter": 0}]
    sp.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    run("lqe_io.py", "pre-check", "--state", str(sp), "--out", str(TMP / "j4-n3.json"))
    check("T4 N3 roman numeral", has(load_errs(TMP / "j4-n3.json"), 0, "罗马数字"))


# ── T5: custom count_match ────────────────────────────────────────────────────
def t5():
    (TMP / "cm_checks.json").write_text(json.dumps({"builtin": {}, "custom": [
        {"id": "cm-probe", "type": "count_match", "pattern": "#P\\d+#",
         "category": "Markup", "severity": "Major", "comment": "tag #Pn# count"}]}), encoding="utf-8")
    state = {"wordcount": 10, "language_pair": "ZHCN-EN", "checks_path": str(TMP / "cm_checks.json"),
             "segments": [{"id": 0, "source": "按#P1#键和#P2#键。", "target": "Press #P1#.",
                           "corrected": None, "max_len": None, "iter": 0}]}
    (TMP / "cm_state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    run("lqe_io.py", "pre-check", "--state", str(TMP / "cm_state.json"), "--out", str(TMP / "cm_pc.json"))
    check("T5 count_match", has(load_errs(TMP / "cm_pc.json"), 0, "source=2, target=1"))


# ── T6: N4 repeat dedup in calc ───────────────────────────────────────────────
def t6():
    state = {"wordcount": 100, "segments": [
        {"id": i, "source": "重复句。", "target": "Dup sentence.", "corrected": None} for i in range(3)]}
    errors = [{"id": i, "errors": [{"category": "Mistranslation", "severity": "Major",
                                    "comment": "wrong"}], "corrected": None} for i in range(3)]
    (TMP / "n4_state.json").write_text(json.dumps(state), encoding="utf-8")
    (TMP / "n4_errors.json").write_text(json.dumps(errors), encoding="utf-8")
    r = run("lqe_calc.py", "--state", str(TMP / "n4_state.json"), "--errors", str(TMP / "n4_errors.json"))
    check("T6 score dedup", "SCORE=92.50" in r.stdout and "REPEATED=2" in r.stdout, r.stdout[:120])
    flags = [e.get("repeated", False) for x in json.loads((TMP / "n4_errors.json").read_text(encoding="utf-8"))
             for e in x["errors"]]
    check("T6 repeated written back", flags == [False, True, True], str(flags))
    r = run("lqe_calc.py", "--state", str(TMP / "n4_state.json"), "--errors", str(TMP / "n4_errors.json"),
            "--no-repeat-dedup")
    check("T6 dedup off", "REPEATED=0" in r.stdout and "SCORE=77.50" in r.stdout, r.stdout[:120])


# ── T7: lqe_batch plan/merge smoke ────────────────────────────────────────────
def t7():
    job = TMP / "j1"
    shutil.copy(job / "pc.json", job / "errors_precheck.json")
    r = run("lqe_batch.py", "plan", "--job", str(job), "--output-budget", "400")
    check("T7 plan rc", r.returncode == 0, r.stderr[-200:])
    check("T7 manifest", (job / "manifest.json").exists() and len(list((job / "batches").glob("batch_*.txt"))) >= 2)
    evals = job / "evals"
    evals.mkdir(exist_ok=True)
    (evals / "eval_00.json").write_text(json.dumps(
        [{"id": 0, "errors": [{"category": "Mistranslation", "severity": "Major", "comment": "test"}],
          "corrected": "Hello."}]), encoding="utf-8")
    r = run("lqe_batch.py", "merge", "--job", str(job))
    check("T7 merge rc+gap report", r.returncode == 0 and "MISSING" in r.stdout, r.stdout[-200:])
    merged = json.loads((job / "errors.json").read_text(encoding="utf-8"))
    check("T7 merge content", merged[0]["corrected"] == "Hello." and merged[1]["errors"] == [])


# ── T8: lqe_engine term_senses / group_terms ──────────────────────────────
def t8():
    sys.path.insert(0, str(SCRIPTS))
    from lqe_engine import term_senses, group_terms

    singleton = {"source": "马尔文", "target": "มาร์วิน", "status": "New"}
    check("T8 singleton term_senses",
          term_senses(singleton) == [{"target": "มาร์วิน", "status": "New"}])

    multi = {"source": "里奥", "senses": [
        {"target": "ลีโอ", "category": "Creature Individual"},
        {"target": "ไลเอล", "category": "Creature Species"},
    ]}
    check("T8 multi term_senses passthrough", term_senses(multi) == multi["senses"])

    grouped = group_terms([singleton, multi])
    check("T8 group_terms keys", set(grouped.keys()) == {"马尔文", "里奥"})
    check("T8 group_terms multi count", len(grouped["里奥"]) == 2)
    check("T8 group_terms singleton count", len(grouped["马尔文"]) == 1)


# ── T9: lqe_checks pre-check 多义术语命中 ─────────────────────────────────────
def t9():
    rows = [
        ('看到一只里奥。', 'Saw a ลีโอ.'),      # 0 命中 Individual 候选 -> 不报
        ('看到一只里奥。', 'Saw a ไลเอล.'),      # 1 命中 Species 候选 -> 不报
        ('看到一只里奥。', 'Saw a Rio.'),        # 2 两个候选都不匹配 -> 报错，列出两个候选
        ('马尔文来了。', 'มาร์วิน is here.'),    # 3 单义词条回归检查
    ]
    make_xlsx(TMP / "t9.xlsx", rows)
    (TMP / "t9_tb.json").write_text(json.dumps([
        {"source": "里奥", "senses": [
            {"target": "ลีโอ", "category": "Creature Individual"},
            {"target": "ไลเอล", "category": "Creature Species"},
        ]},
        {"source": "马尔文", "target": "มาร์วิน", "status": "New"},
    ], ensure_ascii=False), encoding="utf-8")
    r = run("lqe_io.py", "read", "--input", str(TMP / "t9.xlsx"),
            "--source-col", "原文", "--target-col", "译文", "--target-lang", "th",
            "--wordcount-basis", "source-chars",
            "--terminology", str(TMP / "t9_tb.json"), "--out", str(TMP / "j9/state.json"))
    check("T9 read rc", r.returncode == 0, r.stderr[-200:])
    r = run("lqe_io.py", "pre-check", "--state", str(TMP / "j9/state.json"), "--out", str(TMP / "j9/pc.json"))
    check("T9 pre-check rc", r.returncode == 0, r.stderr[-200:])
    res = load_errs(TMP / "j9/pc.json")
    check("T9 sense A no Terminology error", not has(res, 0, "里奥"))
    check("T9 sense B no Terminology error", not has(res, 1, "里奥"))
    check("T9 neither-sense reports both candidates", has(res, 2, "ลีโอ") and has(res, 2, "ไลเอล"))
    check("T9 singleton regression unaffected", not has(res, 3, "马尔文"))


# ── T10: lqe_chunk split 多义 term_hits ───────────────────────────────────────
def t10():
    job = TMP / "j10"
    job.mkdir(parents=True, exist_ok=True)
    state = {"segments": [
        {"id": 0, "source": "看到一只里奥。", "target": "Saw a ลีโอ."},
        {"id": 1, "source": "马尔文来了。", "target": "มาร์วิน is here."},
    ]}
    (job / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    (job / "errors_precheck.json").write_text(json.dumps(
        [{"id": 0, "errors": []}, {"id": 1, "errors": []}], ensure_ascii=False), encoding="utf-8")
    (job / "terms.json").write_text(json.dumps([
        {"source": "里奥", "senses": [
            {"target": "ลีโอ", "category": "Creature Individual"},
            {"target": "ไลเอล", "category": "Creature Species"},
        ]},
        {"source": "马尔文", "target": "มาร์วิน", "status": "New"},
    ], ensure_ascii=False), encoding="utf-8")
    outdir = job / "chunks"
    r = run("lqe_chunk.py", "split", "--state", str(job / "state.json"),
            "--errors", str(job / "errors_precheck.json"),
            "--terms", str(job / "terms.json"),
            "--outdir", str(outdir), "--size", "10")
    check("T10 split rc", r.returncode == 0, r.stderr[-300:])
    chunk = json.loads((outdir / "chunk_00.json").read_text(encoding="utf-8"))
    seg0 = next(s for s in chunk["segments"] if s["id"] == 0)
    seg1 = next(s for s in chunk["segments"] if s["id"] == 1)
    hit0 = next(h for h in seg0["term_hits"] if h["src"] == "里奥")
    check("T10 multi-sense th is list of 2", isinstance(hit0["th"], list) and len(hit0["th"]) == 2)
    check("T10 multi-sense categories present",
          {s.get("category") for s in hit0["th"]} == {"Creature Individual", "Creature Species"})
    hit1 = next(h for h in seg1["term_hits"] if h["src"] == "马尔文")
    check("T10 singleton th is list of 1",
          isinstance(hit1["th"], list) and len(hit1["th"]) == 1 and hit1["th"][0]["target"] == "มาร์วิน")


if __name__ == "__main__":
    for t in (t1, t2, t3, t4, t5, t6, t7, t8, t9, t10):
        t()
    rag = subprocess.run([sys.executable, str(SCRIPTS / "test_rag.py")], capture_output=True, text=True)
    check("RAG suite (test_rag.py)", rag.returncode == 0,
          (rag.stdout or rag.stderr).strip().splitlines()[-1] if (rag.stdout or rag.stderr) else "")
    total = len(PASS) + len(FAIL)
    print(f"\n{len(PASS)}/{total} passed" + (f"  FAILED: {FAIL}" if FAIL else "  — all green"))
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if FAIL else 0)
