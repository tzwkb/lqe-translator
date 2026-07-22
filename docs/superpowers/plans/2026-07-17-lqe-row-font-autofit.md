# LQE Row Font Autofit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fit exceptionally tall report rows by reducing only those rows to the largest readable font that stays within Excel/WPS's 409-point limit.

**Architecture:** Add a private row-fit helper beside the existing wrap calculator. Report builders use its returned height and font size; existing content and workbook structure remain unchanged.

**Tech Stack:** Python 3, openpyxl, unittest

## Global Constraints

- Try 11pt, 10pt, then 9pt; never shrink below 9pt.
- Preserve all report text and explicit line breaks.
- Span the logical record across vertically merged worksheet rows when 9pt still cannot fit.
- Do not alter scoring or LQE issue data.

---

### Task 1: Add deterministic row font fitting

**Files:**
- Modify: `scripts/lqe_io.py`
- Test: `tests/test_excel_diff_highlighting.py`

**Interfaces:**
- Consumes: `_wrapped_line_count(value, column_width) -> int`
- Produces: `_fit_wrapped_row(cells, minimum=15.75, context="wrapped row") -> tuple[float, float]`

- [ ] **Step 1: Write failing tests**

Add coverage proving a 30-line report row succeeds at 9pt, normal rows remain 11pt, and a 36-line row spans two physical rows at the 9pt floor.

- [ ] **Step 2: Verify the new fit test fails**

Run: `python3 -m unittest -v tests.test_excel_diff_highlighting.RichDiffUnitTests.test_fit_wrapped_row_reduces_font_only_when_needed`

Expected: FAIL because `_fit_wrapped_row` does not exist.

- [ ] **Step 3: Implement the helper and apply it to both report sheets**

Calculate maximum wrapped lines once, try `(11, 16.5)`, `(10, 15)`, `(9, 13.5)`, and return the first height at or below 409. At 9pt overflow, calculate the minimum row span, merge each logical cell vertically, and divide total height across the physical rows.

- [ ] **Step 4: Run targeted and full tests**

Run: `python3 -m unittest -v tests.test_excel_diff_highlighting`

Run: `python3 scripts/run_tests.py`

Expected: PASS.

- [ ] **Step 5: Regenerate and inspect the production report**

Run `finalize_job.sh` for `/Users/spellbook/Documents/LQE 3/jobs/王浩宇batch2` in `single` mode, then verify workbook existence, sheet names, maximum row height, row 921 font size, formulas, and corrected export.
