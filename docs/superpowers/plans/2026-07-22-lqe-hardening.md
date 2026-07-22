# LQE Translator Hardening Implementation Plan

> **For agentic workers:** Execute task-by-task with RED-GREEN-REFACTOR and verify each task before starting the next.

**Goal:** Align the installed LQE skill implementation with its safety, terminology, iteration, and scoring contracts.

**Architecture:** Introduce small shared helpers while preserving the current CLI and report formats. State is backward-compatible; `state.json` is the initialization commit marker and PASS is the only finalized workflow state.

**Tech Stack:** Python 3 standard library, openpyxl, unittest, Bash.

## Global Constraints

- Never modify source inputs or historical outputs.
- Never infer terminology confirmation or protection.
- Validate model-produced issues and edits before mutation.
- Preserve old-state readability.
- This installed directory is not a Git repository; commit steps are not applicable.

---

### Task 1: Common issue validation

**Files:** `tests/test_no_terminology_mode.py`, `scripts/lqe_engine.py`, `scripts/lqe_chunk.py`

- [ ] Add standard-mode tests for invalid category, severity, comment, and module ownership.
- [ ] Run the focused tests and confirm the existing implementation fails.
- [ ] Add a common issue validator and enforce ownership for all modes.
- [ ] Run the focused tests and existing no-terminology suite.

### Task 2: Input path safety and publication

**Files:** `tests/test_tabular_read_transaction.py`, `scripts/lqe_paths.py`, `scripts/lqe_io.py`

- [ ] Add tests for direct, normalized, symlink, and hardlink aliases plus rollback.
- [ ] Run them and confirm source overwrite/partial-publication failures.
- [ ] Add path guards and a staged replacement transaction with state published last.
- [ ] Run the focused transaction and SDL publication suites.

### Task 3: Canonical terminology contract

**Files:** `tests/test_terminology_read_contract.py`, `scripts/lqe_terms.py`, `scripts/lqe_io.py`, `scripts/mastertb_to_terms.py`

- [ ] Add fail-closed, status-map, Denied, canonical JSON, and protection-only tests.
- [ ] Run them and confirm current bypasses.
- [ ] Normalize all read paths through a shared terminology contract.
- [ ] Run terminology converter and read suites.

### Task 4: Canonical scoring policy

**Files:** `tests/test_scoring_policy.py`, `scripts/lqe_scoring.py`, `scripts/lqe_calc.py`, `scripts/lqe_engine.py`, `scripts/lqe_io.py`, `scripts/aggregate_sheets.py`

- [ ] Add stale-repeat, state-policy, CLI-override, critical-gate, and compatibility tests.
- [ ] Run them and confirm current divergence.
- [ ] Add policy resolution and pure scoring; clear/rebuild repeat annotations every run.
- [ ] Make downstream commands inherit state policy unless explicitly overridden.
- [ ] Run scoring and report tests.

### Task 5: Real iteration state machine

**Files:** `tests/test_iteration_state.py`, `scripts/lqe_engine.py`, `scripts/lqe_checks.py`, `scripts/lqe_chunk.py`, `scripts/lqe_corrections.py`, `scripts/lqe_io.py`, `scripts/finalize_job.sh`, `scripts/aggregate_sheets.py`

- [ ] Add current-target, forged-correction, stale-chunk, pending-recheck, and finalized-state tests.
- [ ] Run them and confirm current false-finalization behavior.
- [ ] Route all working translation reads through `current_target`.
- [ ] Re-verify edits in `apply-fixes` and add iteration fingerprints.
- [ ] Implement PASS-only finalization and pending-recheck behavior.
- [ ] Run iteration, correction, SDL, and aggregation suites.

### Task 6: Regression runner and documentation

**Files:** `scripts/run_tests.py`, `tests/test_documented_contract.py`, `SKILL.md`, `README.md`, `README_ZH.md`, `projects/README.md`

- [ ] Add runner-completeness tests and confirm the missing suite is detected.
- [ ] Include every `tests/test_*.py` module in the custom runner.
- [ ] Update visible terminology, publication, iteration, and scoring contracts.
- [ ] Run documented-contract and plain-language suites.

### Task 7: Full validation and forward test

- [ ] Run `python3 -m unittest discover -s tests -v`.
- [ ] Run `python3 scripts/run_tests.py`.
- [ ] Run `python3 -m compileall -q scripts tests` and `bash -n scripts/finalize_job.sh`.
- [ ] Run the skill creator `quick_validate.py` against the skill directory.
- [ ] Forward-test initialization and iterate decisions with fresh subagents using only the skill and raw fixtures.

### Task 8: Trusted AI provenance and grouped report rows

**Files:** `scripts/lqe_provenance.py`, `scripts/lqe_corrections.py`, `scripts/lqe_chunk.py`, `scripts/lqe_io.py`, `scripts/lqe_report_contract.py`, `scripts/aggregate_sheets.py`, `scripts/mastertb_prep.py`, report/provenance tests and user documentation.

- [x] Strip model-declared provenance and derive trusted review/edit evidence from bound module outputs.
- [x] Require explicit provenance in current results and preserve it through calc, write, apply, export, and aggregate verification.
- [x] Rebuild final merged content from current module envelopes and reject forged intermediate provenance.
- [x] Bind formal module entries by digest and an independent local publication receipt, bind the full physical Scorecard layout, and describe the local-evidence/identity-attestation boundary accurately.
- [x] Track deduplicated review reuse with the representative segment id.
- [x] Render each issue on its own contiguous segment row with issue-level handling and explicit AI status/source columns.
- [x] Add the same audit state to Scorecard history; bind semantic Results layout and visible Scorecard details in report contract v3.
- [x] Preserve merged long rows and copy child Results plus Scorecard history into aggregate reports.
- [x] Document the 16-column SDLXLIFF report contract and add end-to-end adversarial regressions.
