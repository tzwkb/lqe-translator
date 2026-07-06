# LQE Translator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Agent Skill](https://img.shields.io/badge/Agent%20Skill-Codex-blue.svg)](SKILL.md)
[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)

English | [中文](README_ZH.md)


**Agent Skill** — Language Quality Evaluation pipeline for game-localization translations: ZH source to EN/TH live profiles, deterministic pre-checks, multi-lens AI evaluation, scorecard profiles, and Excel reports.

> **Project managers should start with [PM_GUIDE.html](PM_GUIDE.html)** for the operational guide: how to start a job, what questions to expect, and what deliverables come back.

---

## Directory Structure

```
lqe-translator/
├── scripts/
│   ├── lqe_engine.py    # Shared constants (weights, severities, categories)
│   ├── lqe_calc.py      # Score calculator (N4 repeat dedup)
│   ├── lqe_io.py        # All I/O subcommands
│   ├── lqe_checks.py    # Deterministic pre-check engine (23 builtin checks)
│   ├── lqe_chunk.py     # Multi-lens fan-out (split/merge-lenses/validate-lenses/reconcile/merge)
│   ├── finalize_job.sh  # Multi-lens one-shot finalize (single|iterate)
│   ├── lqe_batch.py     # Output-budget batching + resumable runs (plan/merge)
│   └── gen_*.py         # docs/ xlsx report generators
├── target_languages/<code>/ # Target-language attribute layer (linguistic facts; en/th/zh)
│   ├── attributes.json  # script/word_delim/sentence_terminator/numerals/wordcount_basis
│   └── eval_notes.md    # Language-level AI evaluation notes (copied into jobs)
├── projects/<game>/     # Client layer
│   ├── <lang>/          # Language track: profile.json + checks.json + adjudications.md
│   │                    #   + terms_*.json + sg_* + sources/ + inputs/
│   └── common/          # Game-level shared reference (language-agnostic)
├── docs/                # Analysis & report documents
│   └── lenses/          # Multi-lens specs (_common + T/A/G/R)
├── jobs/
│   └── <file_stem>/     # One folder per translation job
│       ├── state.json         # Job state (segments, history, paths)
│       ├── sg.txt             # Style guide full text
│       ├── terms.json         # Terminology table
│       ├── lang_notes.md      # Target-language eval notes (from target_languages/)
│       ├── errors.json        # Current iteration errors (AI output)
│       ├── errors_precheck.json   # Auto-detected issues (first iteration)
│       ├── errors_iter{N}.json    # Archived errors per FAIL iteration
│       ├── *_lqe_iter{N}.xlsx     # Report for each FAIL iteration
│       └── *_lqe.xlsx             # Final PASS report
└── SKILL.md             # Agent workflow instructions
```

---

## Setup

```bash
pip install openpyxl requests python-docx -q
```

Regression suite (all 23 builtin checks, profiles, batch/feedback smoke):
```bash
python scripts/run_tests.py
```

```bash
SCRIPTS=~/.claude/skills/lqe-translator/scripts
```

---

## Workflow

### 1. Initialize

Project profile (preferred — one flag pulls SG/terms/checks/adjudications/language attrs):
```bash
python "$SCRIPTS/lqe_io.py" read \
  --input "<file>.xlsx" --project <game>/<lang> \
  --source-col "<col>" --target-col "<col>" \
  --out "jobs/<file_stem>/state.json"
```

Standalone:
```bash
python "$SCRIPTS/lqe_io.py" read \
  --input "<file>.xlsx" \
  --source-col "<col>" \
  --target-col "<col>" \
  --style-guide "<sg.docx>" \
  --terminology "<terms.xlsx>" \
  --out "jobs/<file_stem>/state.json"
```

Creates `jobs/<file_stem>/` with `state.json`, `sg.txt`, `terms.json`.

### 2. Pre-check (first iteration only)

```bash
python "$SCRIPTS/lqe_io.py" pre-check \
  --state "jobs/<stem>/state.json" \
  --out "jobs/<stem>/errors.json"
```

Auto-detects deterministic errors:

| Check | Category | Severity |
|-------|----------|----------|
| Chinese characters in target | Untranslated | Major |
| Em dash `—` | Punctuation | Minor |
| Color tag `#G/C/Y…#E` pair count mismatch (source↔target) | Markup | Major |
| Variable `{}` / `%s` missing or extra | Markup | Major |
| Positional placeholder `%s/%d` order changed **[R1]** | Markup | Major |
| `\n` count mismatch | Markup | Major |
| Source number missing/changed in target (e.g. 100→1000) **[R6]** | Mistranslation | Major |
| Target exceeds `max-length` column **[R3]** | Length | Major |
| Length > 1.5× source (fallback when no max-length, non-CJK only) | Length | Major |
| 4+ digit number without thousands separator | Locale convention | Minor |
| Leading/trailing whitespace, double space, full-width punctuation **[R5]** | Punctuation | Minor |
| Term in source but translation absent from target | Terminology | Major |

`max-length` column auto-detected from headers (`maxlen` / `max_length` / `char_limit` / `限长` / `字符上限` …). R6 fires only when the source contains Arabic digits.

### 3. AI Evaluation

Read `errors.json` (pre-check baseline) and the style guide at `sg.txt`. Add judgment-based errors, provide `corrected` text for all error segments. Write back to `errors.json`.

Format:
```json
[
  {"id": 0, "errors": [{"category": "Mistranslation", "severity": "Major", "comment": "..."}], "corrected": "Fixed text"},
  {"id": 1, "errors": [], "corrected": null}
]
```

> **Note:** `Terminology`, `Untranslated`, `Markup`, `Length` severities are **always Major** — enforced automatically by scripts regardless of what is written.

### 4. Calculate Score

```bash
python "$SCRIPTS/lqe_calc.py" \
  --state "jobs/<stem>/state.json" \
  --errors "jobs/<stem>/errors.json" \
  --threshold 98
```

Output: `SCORE=XX.XX STATUS=PASS/FAIL ERRORS=N WORDCOUNT=N`

### 5a. FAIL → Apply Fixes

```bash
python "$SCRIPTS/lqe_io.py" apply-fixes \
  --state "jobs/<stem>/state.json" \
  --errors "jobs/<stem>/errors.json" \
  --score <score> --threshold 98
```

- Archives errors → `errors_iter{N}.json`
- Applies corrections to state
- Generates `*_lqe_iter{N}.xlsx`

→ Go back to step 3.

### 5b. PASS → Write Final Report

```bash
python "$SCRIPTS/lqe_io.py" write \
  --state "jobs/<stem>/state.json" \
  --errors "jobs/<stem>/errors.json" \
  --score <score> --threshold 98
```

Generates `*_lqe.xlsx` with full iteration history.

---

## Large Files — Multi-Lens Fan-Out

For jobs with many segments (≳300), Step 3 runs as parallel subagents split across **4 narrow lenses** — recall is guaranteed by structure, not by instruction. Lens specs live in `docs/lenses/` (`_common.md` + `T/A/G/R.md`).

| Lens | Owns | Segments |
|------|------|----------|
| **T** terminology | Terminology, Inconsistency, Company style + pre-check triage | all (spine) |
| **A** accuracy | Mistranslation, Omission, Addition, Untranslated | all |
| **G** grammar | Grammar, Spelling, semantic Punctuation | desc |
| **R** register | Audience appropriateness, Culture specific reference, Unidiomatic | desc |

```bash
# 1. split: dedup (source,target) + longest-match term coverage + kind tagging
python "$SCRIPTS/lqe_chunk.py" split --state state.json --errors errors.json \
  --terms terms.json --outdir chunks --size 200
# 2. one subagent per chunk × lens → chunk_NN.<L>.json  (T/A all segs; G/R desc segs)
# 3. union lenses → chunk_NN.out.json  (auto-normalizes flat-schema lens files)
python "$SCRIPTS/lqe_chunk.py" merge-lenses   --outdir chunks
# 4. structural gate: missing id / bad category / T-spine gap → non-zero exit
python "$SCRIPTS/lqe_chunk.py" validate-lenses --outdir chunks
# 5. category ownership: A-owned errors kept only if lens A confirms (archives reconcile_dropped.json)
python "$SCRIPTS/lqe_chunk.py" reconcile      --outdir chunks
# 6. broadcast dedup groups to every id → errors.json
python "$SCRIPTS/lqe_chunk.py" merge --state state.json --errors errors_precheck.json \
  --outdir chunks --out errors.json
```

One-shot (steps 3–6 + calc + report + export; idempotent, runs once all T spines exist):
```bash
bash "$SCRIPTS/finalize_job.sh" <job_stem> <nchunks> [single|iterate]
```
`single` = first-round report only (no apply-fixes); `iterate` (default) = apply-fixes loop while FAIL.

---

## Scoring Formula

```
K  = Σ severity_points per category   (Neutral=0, Minor=1, Major=5, Critical=10)
L  = weight × K per category
score = max((1 - ΣL / wordcount) × 100, 0)
threshold = 98
```

Wordcount is locked at initialization and does not change across iterations.

---

## Error Categories

| Category | Weight | Notes |
|----------|--------|-------|
| Terminology | 1.5 | Always Major |
| Mistranslation | 1.5 | |
| Omission | 1.5 | |
| Addition | 1.5 | |
| Untranslated | 1.5 | Always Major |
| Grammar | 1.5 | |
| Inconsistency | 1.5 | |
| Company style | 1.5 | |
| Unidiomatic | 1.5 | |
| Markup | 1.5 | Always Major |
| Culture specific reference | 1.5 | |
| Punctuation | 1.0 | |
| Spelling | 1.0 | |
| Locale convention | 1.0 | |
| Length | 1.0 | Always Major; not checked for CJK sources |
| Audience appropriateness | 1.5 | Accurate but unfit for target audience/register/world |
| Other | 1.0 | |

> Parent dimensions align to MQM-Core / ISO 5060:2024 (Terminology, Accuracy, Linguistic Conventions, Style, Locale Conventions, Audience Appropriateness, Design and Markup, + Other). `lqe_calc.py --critical-gate` enables the industry Critical auto-fail rule; `--severity-scale mqm` switches to the 0/1/5/25 exponential scale.

---

## Auxiliary Commands

**Term lookup** (before evaluation):
```bash
python "$SCRIPTS/lqe_io.py" lookup-terms \
  --state "jobs/<stem>/state.json" [--ids "0,3,7"]
```

**AIPE integration** (alternative to `read`):
```bash
python "$SCRIPTS/lqe_io.py" from-aipe \
  --aipe-csv "<export.csv>" --aipe-url "http://localhost:8000" \
  --out "jobs/<stem>/state.json"
```

**Batch orchestration** (large files; resumable):
```bash
python "$SCRIPTS/lqe_batch.py" plan  --job "jobs/<stem>" [--output-budget 24000]
python "$SCRIPTS/lqe_batch.py" merge --job "jobs/<stem>"
```
