# LQE Agent Skill

Language Quality Evaluation pipeline for AI-generated ZH→EN translations (燕云十六声 / WWM).

---

## Directory Structure

```
lqe-agent-skill/
├── scripts/
│   ├── lqe_engine.py    # Shared constants (weights, severities, categories)
│   ├── lqe_calc.py      # Score calculator
│   └── lqe_io.py        # All I/O subcommands
├── input/               # Source translation Excel files
├── jobs/
│   └── <file_stem>/     # One folder per translation job
│       ├── state.json         # Job state (segments, history, paths)
│       ├── sg.txt             # Style guide full text
│       ├── terms.json         # Terminology table
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

```bash
SCRIPTS=~/.claude/skills/lqe-agent-skill/scripts
```

---

## Workflow

### 1. Initialize

```bash
python "$SCRIPTS/lqe_io.py" read \
  --input "input/<file>.xlsx" \
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
| Color tag `#G/C/Y…#E` count mismatch | Markup | Major |
| Variable `{}` / `%s` missing or extra | Markup | Major |
| `\n` count mismatch | Markup | Major |
| Length > 1.5× source (non-CJK source only) | Length | Major |
| 4+ digit number without thousands separator | Locale convention | Minor |
| Term in source but translation absent from target | Terminology | Major |

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
| Other | 1.0 | |

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
