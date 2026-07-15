# LQE Wrapped Row Height Design

## Goal

Ensure long wrapped text is fully visible in both `LQA Scorecard` and `LQE Results` when an LQE report is opened in WPS or Excel, and regenerate the current `0714审校反馈` report with the same fix.

## Root Cause

- `LQA Scorecard` detail rows are forced to `15.75` points regardless of content.
- `LQE Results` rows are sized only from the number of issues and capped at `80` points.
- `LQE Results` gives original source/target columns width `20`, so long content can exceed Excel/WPS's maximum row height even after wrapping.
- `wrap_text=True` only enables wrapping; it does not calculate row height in an `openpyxl`-generated workbook.

## Considered Approaches

1. Leave row height unset and rely on WPS/Excel AutoFit. This is smallest, but viewer-dependent and unreliable for generated rich-text cells.
2. Compute row height deterministically from text and column width. This is the selected approach because it is stable across WPS, Excel, and headless rendering.
3. Keep fixed rows and only widen columns. This reduces clipping but cannot guarantee full visibility.

## Selected Design

Add private helpers in `scripts/lqe_io.py` that:

- convert plain or rich-text values to display text;
- split text into Unicode extended grapheme clusters so combining sequences and emoji are never divided during measurement;
- count Latin graphemes as one display unit, CJK/full-width graphemes and complete emoji sequences as two, combining marks and zero-width format characters as zero, and tabs as four;
- preserve explicit CR/LF line breaks and empty lines;
- estimate wrapped lines with whitespace-aware greedy wrapping and split overlong UUID/XML tokens by display width;
- compute `max(15.75, 2 + 16.5 * lines)`;
- raise a contextual error before saving if a row would exceed Excel/WPS's `409`-point row limit, rather than silently generating a clipped workbook.

The `write` command builds the workbook into a same-directory staging file before persisting `state.json`, scrubbed `errors.json`, or replacing an existing report. Publication snapshots all destinations and uses randomized same-directory staging; any mid-publication failure restores every destination whose published identity still matches this transaction. A layout or publication failure removes all staging and leaves the persistent artifacts byte-consistent.

For `LQA Scorecard`, calculate each detail row from all displayed values and their actual column widths instead of assigning `15.75`.

For `LQE Results`, assign widths before writing rows. Use width `45` for source text, original translation, suggested translation, error details, and protection evidence. Calculate each row from all displayed values and widths instead of using issue count or the `80`-point cap.

The report remains one-detail-row-per-error. This change does not alter LQE scoring, issue counts, rich-diff content, protection behavior, or terminology scope.

## Validation

- A regression fixture with long multi-line rich text must fail against the old fixed-height behavior.
- Both report sheets must keep `wrap_text=True`, give long rows more height than short rows, and remain at or below `409` points.
- Emoji, ZWJ, keycap, combining-character, CR/LF, long-token, and over-limit behavior must have direct regression coverage.
- The production `write` entry point must be failure-atomic for layout errors, including protected-error scrubbing and an existing report.
- Fault-injection regressions must cover state and workbook replacement failures, JSON staging cleanup, rollback byte identity, and the successful three-artifact publication path.
- The current report must be regenerated from its existing `state.json` and `errors.json` so rich-text diff formatting is preserved.
- Run the targeted regression, the full LQE test suite, `validate-checks`, artifact-tool formula scan, key-range inspection, and visual renders of all sheets plus focused long-text ranges.
- Perform a native WPS smoke test for long unbroken tokens and the fixed-height ceiling without touching the user workbook.

## Approval

The user approved repairing both the current report and the generator with “都修复吧” after the two-layer design was presented.
