# LQE Translator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Agent Skill](https://img.shields.io/badge/Agent%20Skill-Codex-blue.svg)](SKILL.md)
[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)

English | [中文](README_ZH.md)

Agent skill for game-localization LQE: deterministic pre-checks, focused AI check modules, validated local edits, scoring, and Excel deliverables.

> The PM guide is maintained outside the runtime Skill in the Langlobal development docs.

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
│   ├── lqe_review.py       # Build compact review packets and publish sparse drafts
│   ├── lqe_suggestions.py  # Publish report-only full-sentence references
│   ├── lqe_corrections.py  # Validate local edits and build full-text results
│   ├── lqe_calc.py         # Calculate the LQE score
│   └── finalize_job.sh     # Validate through export in one command
├── references/
│   ├── suggestions.md
│   └── check_modules/
│       ├── common.md
│       ├── terminology.md
│       ├── precheck_review.md
│       ├── accuracy.md
│       ├── grammar.md
│       ├── naturalness.md
│       ├── proper_names.md
│       └── term_audit.md
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
    ├── review_packets/
    ├── reference_suggestions.json
    ├── <job>_lqe.xlsx
    └── <job>_corrected.<csv|tsv|xlsx>
```

## Setup

```bash
pip install "openpyxl>=3.1" regex requests python-docx -q
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

Initialization stages and validates every asset before publication, rejects input/output/resource aliases (including symlinks and hardlinks), and publishes `state.json` last. Failure leaves no formal `state.json`, `scope.json`, `terms.json`, or partial SDL asset set.

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

- Every new-job term or sense must contain boolean `confirmed` and `protected`; either missing field fails before formal job artifacts are published.
- A canonical CSV/XLSX/JSON record that already contains both boolean fields may retain `status` as audit metadata and does not require `profile.term_status_map`. If either boolean is missing, status values require an explicit mapping; do not infer confirmation.
- `protected_term_statuses` may only supplement protection and is not a confirmation decision. When present, it must be an array of non-empty strings.
- `Denied` is always excluded case-insensitively and must not be mapped.

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

python3 "$SCRIPTS/lqe_review.py" prepare --job "$JOB"
python3 "$SCRIPTS/lqe_review.py" auto-publish --job "$JOB"
```

`split` reads terminology through the state in standard mode. `--terms <file>` is an optional standard-mode override and is rejected in no-terminology mode. Split inputs are fingerprinted; when the state, current target, scope, pre-check, terms, or split settings change, stale chunk artifacts are archived and old module outputs cannot be reused.

`prepare` creates generation-bound, module-specific `review_packets`, `batch_plan.json`, and `cost_report.json`. Non-terminology modules no longer receive terminology or pre-check fields they do not use. Protected segments and inapplicable `precheck_review` rows are deterministically filled with empty results. `auto-publish` handles only packets that require no AI review.

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

Assign bounded workers from `batch_plan.json`. One worker handles at most four packets and no more than 25,000 source-plus-target characters or 100,000 packet bytes; an oversized packet runs alone. Every new batch starts a new worker and reloads the module specification and job context.

The model writes a compact draft: `reviewed_ids` exactly copies the packet, while `findings` contains only ids with issues. Publish it with `lqe_review.py publish --job "$JOB" --chunk <NN> --module <module> --input <draft.json>`. The publisher restores formal full-id coverage and validates ownership, pre-check references, and generation binding under the existing contract.

`precheck_review` confirms or removes non-terminology pre-check findings in the Markup, Length, Locale convention, Company style, Inconsistency, and Other categories. It must not create Terminology issues, `TERM REVIEW:` evidence, or `confirmed_term` edits.

The compact draft contract is:

```json
{
  "schema": "lqe.compact-module-draft",
  "version": 1,
  "module": "grammar",
  "chunk_id": 0,
  "packet_digest": "<packet.packet_digest>",
  "reviewed_ids": [0, 1, 2],
  "findings": [
    {
      "id": 1,
      "issues": [
        {
          "category": "Grammar",
          "severity": "Minor",
          "comment": "The verb form does not agree with the subject.",
          "needs_confirmation": false,
          "edit": {
            "from": "are",
            "to": "is",
            "evidence": null
          }
        }
      ]
    }
  ]
}
```

Use `needs_confirmation: true` and `edit: null` for a new name, missing terminology, multiple reasonable options, or a rewrite. A terminology or proper-name edit also requires one unique `confirmed: true` candidate and `confirmed_term` evidence.

Machine-generated Terminology issues also carry read-only `term_source` and `expected_targets`; models do not need to emit or rewrite them, and the publisher preserves them through `precheck_ref`.

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
  --errors "$JOB/errors.json"
```

`merge` re-derives the merged issues and provenance from the current bound module outputs, verifies both the content digest and an independent local publication receipt for formal module entries, rejects a forged intermediate merged file, and atomically publishes `errors.json` with `errors.contract.json`. Model drafts cannot self-declare AI review/edit status. Calc, write, apply, export, and aggregation hold a generation lease and reject missing provenance or a missing, tampered, or stale contract. Jobs created by the current reader also reject state-only verification when `chunks/` is missing.

For a first-round review, explicitly use `single`:

```bash
bash "$SCRIPTS/finalize_job.sh" "$JOB" <chunk-count> single
```

Choose `iterate` only when the user has explicitly requested automatic iteration. PASS alone creates `.finalized`; FAIL+single writes review artifacts without changing the current target or finalizing. FAIL+iterate advances `current_target`/iteration, sets `pending_recheck=true`, and returns `PENDING-RECHECK` only when at least one re-verified safe local edit was applied. With zero applicable edits, it writes the round report, exports the verified error overlay with `export --errors`, returns `REVIEW-REQUIRED`, removes `.iteration_pending`, and does not advance the iteration. The next round must rerun pre-check, split, and all modules.

### 6. Write the standard deliverables

```bash
python3 "$SCRIPTS/lqe_io.py" write \
  --state "$JOB/state.json" \
  --errors "$JOB/errors.json" \
  --score <score>

python3 "$SCRIPTS/lqe_io.py" export \
  --state "$JOB/state.json" \
  --errors "$JOB/errors.json"
```

Every input produces `<job>_lqe.xlsx` with the score, issues, suggested text, review handling, and history. The corrected output depends on the input format:

`write --score` is a consistency input. `write` recomputes the score from state policy and errors, warns on disagreement, and uses the recomputed result.

- CSV/TSV inputs produce `<job>_corrected.csv` or `<job>_corrected.tsv` and preserve rows, columns, and the source extension.
- XLSX input produces `<job>_corrected.xlsx` and preserves the workbook, worksheets, blank rows, column order, and formatting.
- SDLXLIFF produces a new fixed five-column `<job>_corrected.xlsx`.

Reports have three visible worksheets: `说明·导读`, `LQA Scorecard`, and `LQE Results`; `_LQE_CONTRACT` remains very hidden. The guide is first and is the default opening sheet, with a three-step reading flow, Scorecard guidance, definitions for all ten review columns, status and decision guidance, and a delivery checklist. The Scorecard shows the verdict, score, compact category summary, and all per-issue review rows without hidden rows or columns.

The Scorecard issue area and `LQE Results` share ten review columns: `Segment ID`, `原文`, `原译`, `AI/建议译文`, `建议状态`, `错误类别`, `严重度`, `问题说明`, `审校结论`, and `审校终稿或备注`. The Scorecard combines parent and sub-category and omits file name, iteration, processing, and AI provenance columns; those audit fields remain in the hidden Results area. The Results reviewer view uses one visible row per segment; extra per-issue audit rows and clean segments are hidden. Status values are `可直接采用`, `建议待确认`, `部分修正，仍需确认`, `未生成建议，需人工处理`, and `已保护`.

Terminology detail exports must read `term_source` and `expected_targets` from each issue, or the hidden `术语原文（结构化）` and `术语库译文（结构化）` Results columns. Do not reverse-parse terms from `comment` with quote-delimited regexes: apostrophes and punctuation are data. Legacy artifacts can be read with `lqe_terms.terminology_issue_fields()`.

Rich-text diffs use red strikethrough for removed/replaced original text and red font for inserted/replaced suggested text. Safe local edits can enter the corrected workflow. Full-sentence entries in the separate `reference_suggestions.json` artifact are report-only and always marked `建议待确认`. Corrected files do not receive diff styling.

In verified internal results, `corrected: ""` is a valid deletion of the whole target; only `corrected: null` means no suggested change. Write, apply, export, and aggregation preserve that distinction.

Tabular and SDLXLIFF reports use the same ten-column reviewer view. Source file, TU ID, SDL Segment ID, processing, per-issue provenance, protection evidence, and `LQE_Iter` remain in the hidden audit area; `LQE_Iter` is always last. `source_manifest.json` stores input SHA-256 hashes, declared languages, extension namespaces, rule matches, exclusions, and locked/TM evidence. The new corrected workbook uses five columns: `来源文件`, `TU ID`, `SDL Segment ID`, `原文`, `译文`.

The first release does not write back to SDLXLIFF XML. `export` creates `<job>_corrected.xlsx` and leaves every source XML file unchanged.

## Scoring

```text
K_per_category = Σ severity_points
L_per_category = weight × K
score = max((1 - ΣL / fixed_wordcount) × 100, 0)
```

`state.scoring_policy` is the default for calc, write, reports, iteration, and aggregation; CLI flags are explicit overrides only. The policy contains threshold, scorecard profile, LISA/MQM severity scale, Critical gate, and repeat dedup. Repeated annotations are cleared and rebuilt on every score. Default severity points are Neutral 0, Minor 1, Major 5, and Critical 10; the default threshold is 98. Protected segments are skipped.

## Multi-sheet workbooks

The default delivery is separate: create one child job and one standard
`<child>_lqe.xlsx` report per selected sheet, then stop after the child
deliverables are complete. Do not create a parent aggregate report or copy
multiple child Results/Scorecards into one workbook unless the user explicitly
asks for a combined report, cross-sheet summary, or restored source-workbook
delivery.

Only for an explicit aggregation request, run:

```bash
python3 "$SCRIPTS/aggregate_sheets.py" \
  --job <job> \
  --sheets <sheet-a>,<sheet-b>
```

For explicit aggregation, the parent job preserves worksheet order, blank rows, formulas, styles, and merged cells while replacing only validated/current targets. Aggregation revalidates every child against its current state, `errors.contract.json`, and verified chunk generation, including chunk terminology context. Each hidden `_LQE_CONTRACT` binds state/errors, visible `LQE Results`, and its per-issue provenance layout; the aggregate copies both child Results and Scorecard history. Before publication, aggregation reacquires every child lease in stable order. Missing, corrupt, stale, or unbound results/reports, stale chunk evidence, or source drift fail without replacing existing parent outputs. Child policies are inherited; incompatible non-threshold policies fail closed. An explicit `--threshold` overrides only the threshold, and any child FAIL makes the aggregate FAIL.

This aggregation command is for tabular workbooks only; an SDLXLIFF directory is one multi-file job, not a multi-sheet workbook.

## Verification

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 scripts/run_tests.py
```
