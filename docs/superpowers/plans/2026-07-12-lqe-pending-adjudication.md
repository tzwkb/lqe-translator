# LQE Pending Adjudication Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent pending PM/TB correction candidates from being applied to corrected deliverables or automatic iterations while keeping the findings, score, and candidate suggestions in the LQE report.

**Architecture:** Add a segment-level `correction_status` field with a backwards-compatible default of `suggested`. Propagate the field through lens normalization and merges, render it in reports, and enforce a fail-closed gate in export and apply-fixes. Reuse the existing evaluation data to migrate the current job and regenerate only the two standard workbooks.

**Tech Stack:** Python 3.12, `unittest`, `openpyxl`, shell, existing LQE JSON/XLSX pipeline.

## Global Constraints

- Do not rerun the 829-segment T/A/G/R evaluation.
- Preserve the original input workbook and all source strings.
- Missing `correction_status` remains compatible and means `suggested`.
- `pending_adjudication` findings remain in the score and report but never alter target text in export or state in apply-fixes.
- Pending is segment-level and fail-closed: if a segment mixes ordinary and pending errors, the full segment remains unchanged until adjudication.
- Default delivery contains only `*_lqe.xlsx` and `*_corrected.xlsx`.
- Preserve existing installed-runtime changes that are not present in the source repository.
- Back up existing delivery files before replacing standard filenames.

---

### Task 1: Add failing regression coverage for pending corrections

**Files:**
- Create: `tests/test_pending_adjudication.py`
- Modify: `scripts/run_tests.py`

**Interfaces:**
- Consumes: `scripts/lqe_io.py` CLI and `scripts/lqe_chunk.py` CLI.
- Produces: regression tests for `correction_status="pending_adjudication"` behavior.

- [ ] **Step 1: Write the failing export and apply-fixes tests**

Create a temporary XLSX with two segments and an `errors.json` where segment 0 is pending and segment 1 is suggested. Assert:

```python
self.assertEqual(exported.cell(2, 2).value, "原译A")
self.assertEqual(exported.cell(2, 3).value, "待人工裁决")
self.assertEqual(exported.cell(3, 2).value, "建议B")
self.assertEqual(exported.cell(3, 3).value, "AI修正")
```

Run `apply-fixes` on the same fixture and assert segment 0 retains `corrected=None` while segment 1 receives `建议B`.

Include more than one error on segment 0 so the test proves a mixed segment is held as a whole rather than partially applied.

- [ ] **Step 2: Write the failing report test**

Run `write` and assert `LQE Results` retains the pending candidate in `Suggest translation`, sets `LQE_Status` to `Pending Adjudication`, and the matching Scorecard `Fixed` cell is `Pending`.

- [ ] **Step 3: Write the failing merge propagation test**

Build one chunk with a T entry marked pending and verify `merge-lenses` then `merge` preserve:

```python
{"id": 0, "correction_status": "pending_adjudication"}
```

Also verify a multi-lens entry with distinct candidates defaults to pending.

- [ ] **Step 4: Register the test in the self-contained suite**

Append a `t25()` wrapper in `scripts/run_tests.py` that invokes the new unittest file and records its return code/output without duplicating test logic.

- [ ] **Step 5: Run tests to verify RED**

Run:

```bash
python3 -m unittest -v tests/test_pending_adjudication.py
```

Expected: failures showing pending candidates are currently exported/applied and the status is not propagated.

- [ ] **Step 6: Commit RED tests**

```bash
git add tests/test_pending_adjudication.py scripts/run_tests.py
git commit -m "test: cover pending adjudication gate"
```

### Task 2: Implement the correction gate in I/O and reports

**Files:**
- Modify: `scripts/lqe_io.py`
- Modify: `scripts/aggregate_sheets.py`
- Test: `tests/test_pending_adjudication.py`

**Interfaces:**
- Consumes: entry-level `correction_status` values `suggested`, `pending_adjudication`, and `approved`.
- Produces: `_correction_status(entry) -> str`; gated report, export, and apply-fixes behavior.

- [ ] **Step 1: Add status validation and normalization**

Add:

```python
_CORRECTION_STATUSES = {"suggested", "pending_adjudication", "approved"}

def _correction_status(entry):
    return entry.get("correction_status") or "suggested"
```

Have `_validate_errors` report unknown values.

- [ ] **Step 2: Gate apply-fixes**

Build `attempted` only from non-pending entries. Record pending candidates in `skipped_corrections` with reason `PENDING_ADJUDICATION`; do not increment their segment iteration or write `state.segments[].corrected`.

- [ ] **Step 3: Render pending state in both report sheets**

Carry `correction_status` into Scorecard detail rows. Use `Pending` in the Scorecard `Fixed` column and `Pending Adjudication` in `LQE Results.LQE_Status`, while retaining the candidate in `Suggest translation`. Add one guide row explaining that pending suggestions must not be applied.

When `cmd_write` is rerun for the same iteration, replace `error_history[-1]` with the new `final_entry` instead of silently retaining the old entry. Add a regression assertion that a same-iteration rewrite exposes the newly migrated pending status.

- [ ] **Step 4: Gate XLSX/CSV export**

When overlaying `errors.json`, copy both `corrected` and `correction_status` to the in-memory segment. Change `_export_choice` so pending returns the original target and `("待人工裁决", "pending")`; add pending fill and a separate count to CSV/XLSX output summaries.

For iterative state, use the already-landed `seg.corrected` as the pending baseline and keep the new pending candidate separately in the report input. Preserve `approved` on state and export it as `人工批准`.

- [ ] **Step 5: Gate multi-Sheet aggregation**

Update `aggregate_sheets.py` so its `corr` map excludes `pending_adjudication`. Its suggested-correction count must use the same filtered map.

- [ ] **Step 6: Run focused tests to verify GREEN**

```bash
python3 -m unittest -v tests/test_pending_adjudication.py
```

Expected: all I/O/report tests pass; merge tests may remain failing until Task 3.

- [ ] **Step 7: Commit I/O implementation**

```bash
git add scripts/lqe_io.py scripts/aggregate_sheets.py
git commit -m "fix: gate pending adjudication corrections"
```

### Task 3: Propagate pending status through lens merges and document the schema

**Files:**
- Modify: `scripts/lqe_chunk.py`
- Modify: `docs/lenses/_common.md`
- Modify: `docs/lenses/T.md`
- Modify: `SKILL.md`
- Test: `tests/test_pending_adjudication.py`

**Interfaces:**
- Consumes: optional lens-entry `correction_status`.
- Produces: merged `errors.json` retaining the status; multi-candidate unresolved entries default to pending.

- [ ] **Step 1: Preserve status in `_norm_lens`**

Initialize each normalized entry with its status and promote the result to `pending_adjudication` if any duplicate/flat entry for the same id is pending.

- [ ] **Step 2: Propagate status through `merge-lenses` and `merge`**

Store per-lens statuses alongside candidates. For one candidate, retain its status. For multiple distinct candidates, set pending unless a later explicit integration has already replaced `corr_candidates` and set a non-pending status. Preserve `correction_status` and `corr_candidates` through final merge and dedup broadcast.

- [ ] **Step 3: Update agent-facing schema documentation**

Document the exact field and require T/N or any lens proposing an unresolved key name/TB replacement to emit:

```json
"correction_status": "pending_adjudication"
```

Clarify that comments are explanatory only and never control machine behavior.

- [ ] **Step 4: Run focused and full tests**

```bash
python3 -m unittest -v tests/test_pending_adjudication.py
python3 scripts/run_tests.py
```

Expected: focused tests pass. Full suite matches or improves the recorded baseline; the only allowed pre-existing failure is T22 missing the untracked NRC style-guide XLSX in the worktree.

- [ ] **Step 5: Commit merge and documentation changes**

```bash
git add scripts/lqe_chunk.py docs/lenses/_common.md docs/lenses/T.md SKILL.md
git commit -m "fix: propagate pending correction status"
```

### Task 4: Make standard finalization accept an explicit job directory

**Files:**
- Modify: `scripts/finalize_job.sh`
- Test: `tests/test_pending_adjudication.py`

**Interfaces:**
- Consumes: either legacy job name under `$SK/jobs` or an explicit directory containing `state.json`.
- Produces: one standard finalization path without hand-written command chains.

- [ ] **Step 1: Write the failing path-resolution test**

Assert that passing an absolute temporary job directory makes the script resolve that directory rather than `$SK/jobs/<argument>`.

- [ ] **Step 2: Verify RED**

```bash
python3 -m unittest -v tests.test_pending_adjudication.FinalizePathTests
```

Expected: failure because the current script always prefixes `$SK/jobs`.

- [ ] **Step 3: Implement compatible path resolution**

Use the argument directly when it is a directory containing `state.json`; otherwise retain legacy `$SK/jobs/<jobname>` behavior. Keep `.finalized` and output behavior unchanged.

- [ ] **Step 4: Verify GREEN and commit**

```bash
python3 -m unittest -v tests.test_pending_adjudication.FinalizePathTests
git add scripts/finalize_job.sh tests/test_pending_adjudication.py
git commit -m "fix: support explicit LQE job directories"
```

### Task 5: Deploy the fix, migrate the current job, and regenerate deliverables

**Files:**
- Modify: `/Users/spellbook/.codex/skills/lqe-translator/scripts/lqe_io.py`
- Modify: `/Users/spellbook/.codex/skills/lqe-translator/scripts/lqe_chunk.py`
- Modify: `/Users/spellbook/.codex/skills/lqe-translator/scripts/finalize_job.sh`
- Modify: `/Users/spellbook/.codex/skills/lqe-translator/docs/lenses/_common.md`
- Modify: `/Users/spellbook/.codex/skills/lqe-translator/docs/lenses/T.md`
- Modify: `/Users/spellbook/.codex/skills/lqe-translator/SKILL.md`
- Modify: `/Users/spellbook/Desktop/Langlobal/wecom-agent/jobs/LOC_FILE-20260420_P1阿珠SourceTarget0712/errors.json`
- Create: `/Users/spellbook/Desktop/Langlobal/wecom-agent/outputs/LOC_FILE-20260420_P1阿珠SourceTarget0712/superseded_20260712/`
- Replace after backup: the standard `_lqe.xlsx` and `_corrected.xlsx` in the output directory.

**Interfaces:**
- Consumes: the verified source-tree implementation and the current job's 76 legacy comments.
- Produces: installed runtime with the same behavior and two corrected standard deliverables.

- [ ] **Step 1: Synchronize only verified changed hunks to the installed skill**

Preserve the installed `cmd_write` error-history replacement behavior that differs from the source repository. Compare files after patching and inspect the remaining intended difference.

- [ ] **Step 2: Migrate the 76 current entries**

Create an auditable migration script in the job support directory that sets `correction_status="pending_adjudication"` only where an error comment contains the exact legacy marker `PM/TB adjudication`. Assert exactly 76 unique ids and 76 non-empty corrected candidates before writing.

- [ ] **Step 3: Back up old delivery files**

Copy the existing LQE report, corrected workbook, and extra adjudication workbook into `superseded_20260712/`; do not delete them.

- [ ] **Step 4: Regenerate the two standard files**

Run the installed `write` and `export --errors` using the existing score 96.45 and threshold 98. Copy only the regenerated `_lqe.xlsx` and `_corrected.xlsx` to the standard output directory.

- [ ] **Step 5: Verify exact output counts**

Using the bundled spreadsheet runtime, assert 143 `AI修正`, 76 `待人工裁决`, 610 `未改`; every pending row keeps the original target; every pending report row retains its candidate and shows `Pending Adjudication`.

### Task 6: Final verification and review

**Files:**
- Verify all files changed in Tasks 1-5.

**Interfaces:**
- Consumes: source branch, installed skill, migrated job, and regenerated workbooks.
- Produces: evidence-backed completion report and real before/after examples.

- [ ] **Step 1: Run fresh automated verification**

```bash
python3 -m unittest -v tests/test_pending_adjudication.py
python3 scripts/run_tests.py
git diff --check main...HEAD
```

- [ ] **Step 2: Verify workbook structure and visuals**

Import both regenerated workbooks with the bundled spreadsheet runtime, scan formula errors, compare source strings and sheet names, and render the report guide/results plus corrected top/bottom ranges.

- [ ] **Step 3: Independently review the complete branch diff**

Review requirements, backward compatibility, fail-closed behavior, and installed-runtime sync. Resolve all Critical/Important findings before completion.

- [ ] **Step 4: Report real examples**

Show one ordinary pending term, one multi-lens conflict, and one ordinary suggested correction with source, original target, old incorrect export, new safe export, status, and report behavior.
