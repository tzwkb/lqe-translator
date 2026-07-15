# LQE Wrapped Row Height Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make wrapped long text fully visible in WPS/Excel on both LQE report sheets and rebuild the current report.

**Architecture:** Add one deterministic Unicode-aware row-height estimator to `lqe_io.py`, apply it to both report sheets using their real column widths, and verify it with a long-rich-text regression. Regenerate the existing job through the normal `write` command and validate the resulting workbook with artifact-tool.

**Tech Stack:** Python 3, `openpyxl`, `unittest`, bundled `@oai/artifact-tool` for final workbook inspection/rendering.

## Global Constraints

- Preserve report values, rich-text diff runs, scoring, issue counts, and no-terminology scope.
- Keep every generated row at or below `409` points; abort before saving if a row cannot fit instead of silently clipping it.
- Use width `45` for long-text columns in `LQE Results`.
- The skill directory is not a Git repository, so no commit step is possible.

---

### Task 1: Add a failing long-text regression

**Files:**
- Modify: `/Users/spellbook/.codex/skills/lqe-translator/tests/test_excel_diff_highlighting.py`
- Test: `/Users/spellbook/.codex/skills/lqe-translator/tests/test_excel_diff_highlighting.py`

**Interfaces:**
- Consumes: `lqe_io._build_xlsx(state, history, score, threshold, output)`
- Produces: `RichDiffReportTests.test_long_wrapped_text_rows_expand_on_both_report_sheets`

- [ ] Add a fixture containing a short segment and an eight-line long rich-diff segment with the same issue count.
- [ ] Assert both sheets keep wrapping, long-row height exceeds short-row height, long rows are at least `120` points, and all heights are at most `409`.
- [ ] Run `python3 -m unittest -v tests.test_excel_diff_highlighting.RichDiffReportTests.test_long_wrapped_text_rows_expand_on_both_report_sheets` and confirm failure because the old heights are `15.75` and `15.0`.

### Task 2: Implement deterministic sizing

**Files:**
- Modify: `/Users/spellbook/.codex/skills/lqe-translator/scripts/lqe_io.py`
- Test: `/Users/spellbook/.codex/skills/lqe-translator/tests/test_excel_diff_highlighting.py`

**Interfaces:**
- Produces: `_display_units(value) -> int`, `_wrapped_line_count(value, column_width) -> int`, and `_wrapped_row_height(cells, minimum=15.75) -> float`.
- `cells` is an iterable of `(value, column_width)` pairs.

- [ ] Import `math` and `unicodedata`.
- [ ] Implement Unicode display-unit counting, explicit-newline handling, whitespace-aware wrapping, overlong-token splitting, and the `409`-point ceiling.
- [ ] Measure extended grapheme clusters atomically, including emoji presentation, ZWJ, keycap, regional-indicator, modifier, and combining-character sequences.
- [ ] Define Scorecard widths before writing detail rows and replace the fixed `15.75` assignment with `_wrapped_row_height` over the row values.
- [ ] Define `LQE Results` widths before writing rows, set long-text columns to `45`, and replace the issue-count formula with `_wrapped_row_height` over `row_data`.
- [ ] Run the targeted regression and confirm it passes.
- [ ] Run `python3 -m unittest -v tests.test_excel_diff_highlighting` and confirm the whole module passes.

### Task 3: Rebuild and verify the current report

**Files:**
- Rewrite through normal generator: `/Users/spellbook/Documents/LQE 3/jobs/0714审校反馈_无术语_20260715/0714审校反馈_无术语_20260715_lqe.xlsx`

**Interfaces:**
- Consumes: existing `state.json`, `errors.json`, score `95.03`, threshold `98`.
- Produces: the corrected LQE workbook at the same job path.

- [ ] Run `lqe_io.py write` against the current job.
- [ ] Run `lqe_chunk.py validate-checks --job ...` and `python3 scripts/run_tests.py`.
- [ ] Inspect sheets, key ranges, long-row heights, widths, and formula errors with artifact-tool.
- [ ] Render every worksheet and focused long-text ranges, then visually confirm no clipping.
- [ ] Run `unzip -t` and confirm the XLSX package has no errors.

### Post-review hardening: emoji and hard-limit behavior

- [x] Add RED tests proving the old code miscounts emoji graphemes and silently caps over-limit rows.
- [x] Measure Unicode extended grapheme clusters atomically and count complete emoji sequences as two display units.
- [x] Replace the silent `409`-point cap with a contextual `ValueError` before workbook save.
- [x] Add an integration regression proving an over-limit report is rejected and no output file is created.
- [x] Make `cmd_write` build to staging before any persistent JSON/report mutation; cover byte-identical rollback and staging cleanup.
- [x] Cover the Results-only overflow call site with 25 hard error-detail lines.
- [x] Publish state, scrubbed errors, and workbook through a snapshot/identity-guarded rollback transaction.
- [x] Fault-inject state/workbook publication failures and verify every original byte and staging cleanup; verify the successful scrubbed publication path.
- [x] Verify in native WPS 12.1 that long unbroken ASCII/XML/UUID tokens wrap at character boundaries; verify that fixed over-limit content is clipped at the row-height ceiling.
