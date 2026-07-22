# LQE Row Font Autofit Design

## Goal

Generate complete LQE workbooks when a wrapped report row exceeds Excel/WPS's 409-point row-height limit at the default 11-point font.

## Design

- Keep the existing Unicode-aware wrapped-line calculation.
- Try row font sizes 11, 10, and 9 points with proportional line heights 16.5, 15, and 13.5 points.
- Select the largest font whose calculated row height is at most 409 points.
- Apply the smaller font only to the overflowing data row in `LQA Scorecard` or `LQE Results`.
- Preserve all cell text, explicit line breaks, rich-text differences, columns, issue counts, scoring, and protected-segment behavior.
- If a row still cannot fit at 9 points, span the logical record across the minimum number of vertically merged worksheet rows. Each physical row remains at or below 409 points.

## Validation

- A 30-line row must render at 9 points and no more than 409 points high.
- Ordinary rows must remain 11 points.
- A 36-line row must span two physical rows without changing its cell text.
- The full LQE test suite and the production `王浩宇batch2` finalization must pass.
