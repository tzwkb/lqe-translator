# LQE Translator Hardening Design

## Goal

Make initialization, terminology, issue validation, iteration, scoring, and regression coverage match the contracts already documented by the skill without rewriting the report engine.

## Architecture

- Add focused helpers for path publication, terminology normalization, current-target state, and scoring policy.
- Keep existing CLI names and output formats. Old states remain readable through fallback defaults.
- Treat `state.json` as the final commit marker for tabular initialization.
- Treat AI issue files as untrusted input: validate schema, module ownership, scope, and edits before state mutation.

## Behavior

### Initialization

- Reject `--out` aliases of any input before writing job artifacts.
- Stage generated assets, `scope.json`, and `state.json`; publish state last and roll back on process-level failure.
- Preserve input bytes and existing job artifacts on failure.

### Terminology

- Canonical terms always contain explicit boolean `confirmed` and `protected` fields.
- Status-bearing canonical records that already contain both booleans do not require `profile.term_status_map`; their status is audit metadata. If either boolean is missing, status values require an explicit mapping, and protection-only settings do not count as a confirmation decision.
- `protected_term_statuses`, when supplied, is an array of non-empty strings.
- Exclude `Denied` case-insensitively before mapping and reject attempts to map it.
- Fail before publishing any job artifact when confirmation provenance is missing.

### Issue validation

- Validate issue object, category, severity, and non-empty comment in every mode.
- Enforce module-category ownership in every mode.
- Apply mode-specific terminology restrictions only after the common issue contract passes.

### Iteration

- Resolve the working translation through one `current_target(segment)` helper.
- `apply-fixes` re-verifies edits against the current target and never trusts a supplied `corrected` value by itself.
- `FAIL + iterate` applies verified edits, increments iteration, records `pending_recheck`, exports the current target, and does not create `.finalized`.
- Only PASS creates `.finalized`; old chunk artifacts cannot be reused for a different iteration or target fingerprint.

### Scoring

- Persist a resolved `scoring_policy` in state: threshold, profile, severity scale, critical gate, and repeat deduplication.
- CLI values override state only when explicitly supplied.
- Recompute repeated annotations from scratch on every scoring run.
- Use one pure scoring result for CLI status and downstream reporting defaults.

## Compatibility

- Old states fall back to top-level `threshold`, `legacy`, `lisa`, no critical gate, and repeat deduplication enabled.
- Existing canonical terminology JSON continues to load.
- Raw or ambiguous terminology intentionally fails closed.
- Existing `nrc/zh-en` terminology remains unmodified and will require an explicit status decision before initialization.

## Verification

- Add focused regression tests before every production change.
- Run targeted modules after each change, then unittest discovery, the custom runner, compile checks, shell syntax checks, skill validation, and independent forward tests.

## Bound artifact and report audit extension

- Current jobs bind split inputs, content-digested module entries plus independent local publication receipts, final results, and reports to one live generation. Final merge re-derives issues from formal module envelopes and rejects a modified intermediate merge.
- `review_provenance` separates finding origin, AI review module, directly reviewed segment, edit origin, and script-computed `ai_edited`. Model drafts cannot provide trusted provenance; current results require it on every issue.
- Deduplicated members retain the representative `reviewed_segment_id`, so reports display reuse instead of claiming direct review.
- `LQE Results` projects one logical row per issue in state/issue order, keeps each segment contiguous, and retains one row for a segment without issues. Processing is issue-specific; suggested text remains segment-level.
- Report contract v3 validates the audit headers and logical row projection, binds visible Results and Scorecard history, and aggregation copies both sheets including long-row merges.
- Legacy results without provenance remain readable but are labeled unknown rather than unreviewed.
- AI module provenance is locally content-bound workflow evidence, not a host/orchestrator identity signature. `ai_edited` means a validated edit was included in the suggested translation, not that it was written back to state.
