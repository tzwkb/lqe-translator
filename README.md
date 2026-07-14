# LQE Translator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Agent Skill](https://img.shields.io/badge/Agent%20Skill-Codex-blue.svg)](SKILL.md)
[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)

English | [中文](README_ZH.md)

Agent skill for game-localization LQE: deterministic pre-checks, focused AI check modules, validated local edits, scoring, and Excel deliverables.

> Project managers can use the standalone [PM guide](PM_GUIDE.html).

## What the workflow guarantees

- Project context is loaded from `profile.json`, `confirmed_rules.md`, the style guide, and target-language notes; standard mode also loads terminology.
- Standard mode requires terminology, accuracy, grammar, and naturalness. No-terminology mode requires `precheck_review`, accuracy, grammar, and naturalness; the optional proper-name module is standard-mode only.
- Models report `issues` and safe local `edit` operations. Python validates edits and builds the internal full-text result.
- `confirmed: true` authorizes a unique terminology edit; `protected: true` means the content must not be changed.
- Protected segments are neither changed nor scored.
- SDLXLIFF 1.2 can be read from one file or a recursively scanned directory without an intermediate workbook.
- Standard deliverables are `<job>_lqe.xlsx` plus a format-specific corrected file: CSV/TSV keeps the source extension; XLSX and SDLXLIFF use `.xlsx`.

## Directory structure

```text
lqe-translator/
├── scripts/
│   ├── lqe_io.py           # Read, pre-check, protect, report, and export
│   ├── lqe_chunk.py        # Split, validate, merge, and reconcile module results
│   ├── lqe_corrections.py  # Validate local edits and build full-text results
│   ├── lqe_calc.py         # Calculate the LQE score
│   └── finalize_job.sh     # Validate through export in one command
├── docs/check_modules/
│   ├── common.md
│   ├── terminology.md
│   ├── precheck_review.md
│   ├── accuracy.md
│   ├── grammar.md
│   ├── naturalness.md
│   ├── proper_names.md
│   └── term_audit.md
├── target_languages/<code>/
│   ├── attributes.json
│   └── eval_notes.md
├── projects/<game>/<source>-<target>/
│   ├── profile.json
│   ├── checks.json
│   ├── confirmed_rules.md
│   ├── terms_*.json
│   └── sg*.md / sg*.txt
└── jobs/<job>/
    ├── state.json
    ├── scope.json
    ├── source_manifest.json       # SDLXLIFF jobs
    ├── tm_candidates.json         # SDLXLIFF jobs
    ├── confirmed_rules.md
    ├── errors_precheck.json
    ├── errors.json
    ├── chunks/
    ├── <job>_lqe.xlsx
    └── <job>_corrected.<csv|tsv|xlsx>
```

## Setup

```bash
pip install openpyxl requests python-docx -q
SCRIPTS=~/.codex/skills/lqe-translator/scripts
```

Run the regression suite from the skill root:

```bash
python3 scripts/run_tests.py
```

## Workflow

### 1. Initialize a job

Project profiles are preferred because one option loads language settings, checks, confirmed rules, terminology, and the style guide.

```bash
JOB="jobs/<job>"
python3 "$SCRIPTS/lqe_io.py" read \
  --project "<game>/<source>-<target>" \
  --input "<file>.xlsx" \
  --source-col "<source column>" \
  --target-col "<target column>" \
  --out "$JOB/state.json"
```

The profile must declare `language_pair`, `source_lang`, and `target_lang`. Run checks only after reading the project background, `confirmed_rules.md`, the style guide, and language notes.

When the request explicitly excludes terminology and proper-name checks, add `--no-terminology` to `read`. It overrides profile terminology and is mutually exclusive with an explicit `--terminology <file>`:

```bash
python3 "$SCRIPTS/lqe_io.py" read \
  --project "<game>/<source>-<target>" \
  --input "<file>.xlsx" \
  --source-col "<source column>" \
  --target-col "<target column>" \
  --no-terminology \
  --out "$JOB/state.json"
```

The resolved mode is stored in `state.check_scope` and copied to `$JOB/scope.json`. No-terminology mode disables terminology, proper-name, and term-audit work; it does not disable file-wide consistency, Markup, or numeric checks.

For SDLXLIFF, pass one `.sdlxliff` file or a directory. `--input-format` accepts `auto`, `tabular`, or `sdlxliff`; a single file and a directory containing only SDLXLIFF files are auto-detected, while a mixed directory requires the explicit format. SDLXLIFF input reads source and target segments directly, so it does not use `--source-col` or `--target-col`:

```bash
python3 "$SCRIPTS/lqe_io.py" read \
  --project "<game>/<source>-<target>" \
  --input "<file-or-directory>" \
  --input-format sdlxliff \
  --out "$JOB/state.json"
```

The first release supports XLIFF 1.2 with the SDL namespace. XLIFF 2.0 is rejected. Unknown vendor extensions are preserved and recorded when segment boundaries remain unambiguous; an extension that makes source, target, or `mid` pairing ambiguous causes the import to fail. Content type and exclusion behavior comes only from explicit profile rules, never from CC, FF, filenames, or directory names.

The following visible contract defines both resolved scopes:

<pre data-lqe-scope-contract>
{
  "mode_flag": "--no-terminology",
  "standard": {
    "required": ["terminology", "accuracy", "grammar", "naturalness"],
    "optional": ["proper_names"]
  },
  "no-terminology": {
    "required": ["precheck_review", "accuracy", "grammar", "naturalness"],
    "optional": [],
    "disabled": ["terminology", "proper_names", "term_audit"]
  },
  "scope_artifact": {
    "path": "scope.json",
    "state_field": "state.check_scope",
    "relation": "same resolved scope"
  },
  "kept_checks": ["file-wide consistency", "Markup", "numeric checks"]
}
</pre>

### 2. Mark protected content

Terminology entries use explicit flags in standard mode; no-terminology mode ignores them. Explicit segment protection, including verified TM matches, remains available in both modes.

```json
{"source":"Source term","target":"Approved rendering","confirmed":true,"protected":false}
```

- Missing flags default to `false`.
- Do not infer `confirmed` from a status label.
- `protected_term_statuses` may map user-confirmed status values to `protected: true`.

When the input supplies exact TM-match evidence, the agent records explicit segment ids and then runs:

```bash
python3 "$SCRIPTS/lqe_io.py" protect-segments \
  --state "$JOB/state.json" \
  --protected-file "$JOB/tm_protected.agent_decision.json" \
  --reason TM_100_MATCH
```

The script never guesses match columns or values.

For SDLXLIFF, segments marked locked are always protected with reason `SOURCE_LOCKED`. By default, only segments satisfying all three conditions—`origin=tm`, `percent=100`, and `text-match=SourceAndTarget`—are written to `tm_candidates.json`; candidates are not protected automatically. Review them and pass that file to `protect-segments`, set profile policy `protect-exact-source-and-target`, or use `--protect-exact-tm` for an explicit strict decision. A plain 100% value is insufficient. If locked and exact-TM evidence coexist, `SOURCE_LOCKED` remains the effective reason and both evidence records are retained.

An optional profile section defines auditable SDLXLIFF rules:

```json
{
  "sdlxliff": {
    "tm_protection": "candidate-only",
    "content_type_rules": [
      {"id": "dialog", "glob": "**/dialog*.sdlxliff", "content_type": "Dialogue"}
    ],
    "exclude_rules": [
      {"id": "rejected", "field": "confirmation", "equals": "Rejected", "reason": "Client excluded"}
    ]
  }
}
```

### 3. Run the deterministic pre-check

```bash
python3 "$SCRIPTS/lqe_io.py" pre-check \
  --state "$JOB/state.json" \
  --out "$JOB/errors_precheck.json"
```

Checks include untranslated or empty targets, variables, tags, line breaks, numbers, length, whitespace, punctuation, repeated words, case, source-target consistency, and project-specific rules. Standard mode also runs terminology and terminology-dependent proper-name checks. No-terminology mode skips those checks while keeping all non-terminology pre-checks for contextual review.

### 4. Split and run check modules

```bash
python3 "$SCRIPTS/lqe_chunk.py" split \
  --state "$JOB/state.json" \
  --errors "$JOB/errors_precheck.json" \
  --outdir "$JOB/chunks" \
  --size 100
```

`split` reads terminology through the state in standard mode. `--terms <file>` is an optional standard-mode override and is rejected in no-terminology mode.

For every `chunk_NN.json`, produce the files selected by `state.check_scope`:

```text
# Standard mode
chunk_NN.terminology.json
chunk_NN.accuracy.json
chunk_NN.grammar.json
chunk_NN.naturalness.json

# No-terminology mode
chunk_NN.precheck_review.json
chunk_NN.accuracy.json
chunk_NN.grammar.json
chunk_NN.naturalness.json
```

Each module reads `docs/check_modules/common.md`, its own specification, and the job context. It must cover every assigned id, including rows with no findings.

`precheck_review` confirms or removes non-terminology pre-check findings in the Markup, Length, Locale convention, Company style, Inconsistency, and Other categories. It must not create Terminology issues, `TERM REVIEW:` evidence, or `confirmed_term` edits.

The only model-facing contract is:

```json
[
  {
    "id": 0,
    "issues": [
      {
        "category": "Grammar",
        "severity": "Minor",
        "comment": "The verb form does not agree with the subject.",
        "needs_confirmation": false,
        "edit": {
          "from": "are",
          "to": "is",
          "start": 4,
          "end": 7,
          "evidence": null
        }
      }
    ]
  }
]
```

Use `needs_confirmation: true` and `edit: null` for a new name, missing terminology, multiple reasonable options, or a rewrite. A terminology or proper-name edit also requires one unique `confirmed: true` candidate and `confirmed_term` evidence.

### 5. Validate, merge, score, and export

```bash
python3 "$SCRIPTS/lqe_chunk.py" validate-checks --job "$JOB"
python3 "$SCRIPTS/lqe_chunk.py" merge-checks --job "$JOB"
python3 "$SCRIPTS/lqe_chunk.py" reconcile --job "$JOB"
python3 "$SCRIPTS/lqe_chunk.py" merge \
  --state "$JOB/state.json" \
  --errors "$JOB/errors_precheck.json" \
  --outdir "$JOB/chunks" \
  --out "$JOB/errors.json"

python3 "$SCRIPTS/lqe_calc.py" \
  --state "$JOB/state.json" \
  --errors "$JOB/errors.json" \
  --threshold 98
```

For a first-round review, explicitly use `single`:

```bash
bash "$SCRIPTS/finalize_job.sh" "$JOB" <chunk-count> single
```

Choose `iterate` only when the user has explicitly requested automatic iteration.

### 6. Write the standard deliverables

```bash
python3 "$SCRIPTS/lqe_io.py" write \
  --state "$JOB/state.json" \
  --errors "$JOB/errors.json" \
  --score <score> \
  --threshold 98

python3 "$SCRIPTS/lqe_io.py" export \
  --state "$JOB/state.json" \
  --errors "$JOB/errors.json"
```

Every input produces `<job>_lqe.xlsx` with the score, issues, suggested text, review handling, and history. The corrected output depends on the input format:

- CSV/TSV inputs produce `<job>_corrected.csv` or `<job>_corrected.tsv` and preserve rows, columns, and the source extension.
- XLSX input produces `<job>_corrected.xlsx` and preserves the workbook, worksheets, blank rows, column order, and formatting.
- SDLXLIFF produces a new fixed five-column `<job>_corrected.xlsx`.

User-facing reports label rows as suggested change, needs human confirmation, keep original, or protected. The word `corrected` is reserved for internal data and the standard output filename.

For SDLXLIFF, `LQE Results` always uses these 11 columns: `来源文件`, `TU ID`, `SDL Segment ID`, `原文`, `原译`, `建议译文`, `处理方式`, `错误详情`, `LQE_Iter`, `Protected`, `Protection Evidence`. `source_manifest.json` stores input SHA-256 hashes, declared languages, extension namespaces, rule matches, exclusions, and locked/TM evidence. The new corrected workbook uses five columns: `来源文件`, `TU ID`, `SDL Segment ID`, `原文`, `译文`.

The first release does not write back to SDLXLIFF XML. `export` creates `<job>_corrected.xlsx` and leaves every source XML file unchanged.

## Scoring

```text
K_per_category = Σ severity_points
L_per_category = weight × K
score = max((1 - ΣL / fixed_wordcount) × 100, 0)
```

Default severity points are Neutral 0, Minor 1, Major 5, and Critical 10. The default threshold is 98. Terminology, Untranslated, Markup, and Length are forced to Major. Protected segments are skipped.

## Multi-sheet workbooks

Create one child job per sheet, then aggregate after every sheet has passed the required checks:

```bash
python3 "$SCRIPTS/aggregate_sheets.py" \
  --job <job> \
  --sheets <sheet-a>,<sheet-b> \
  --threshold 98
```

The parent job preserves worksheet order, blank rows, formulas, styles, and merged cells while replacing only the target cells selected by validated edits.

This aggregation command is for tabular workbooks only; an SDLXLIFF directory is one multi-file job, not a multi-sheet workbook.

## Verification

```bash
python3 -m unittest -v tests.test_correction_builder
python3 -m unittest -v tests.test_corrected_ownership
python3 -m unittest -v tests.test_no_terminology_mode
python3 -m unittest -v tests.test_sdlxliff_input
python3 -m unittest -v tests.test_documented_contract
python3 -m unittest -v tests.test_plain_language
python3 scripts/run_tests.py
```
