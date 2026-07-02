# Legacy Scorecard Profile

This profile preserves the current `lqe-translator` scoring behavior.

It externalizes the previous in-code constants:

- Category order and MQM/ISO parent mapping
- Category weights
- LISA severity points
- Optional MQM severity points
- Forced severity rules

Use it explicitly with:

```bash
python scripts/lqe_calc.py --state jobs/foo/state.json --errors jobs/foo/errors.json --scorecard-profile legacy
```

Omitting `--scorecard-profile` currently defaults to `legacy`.
