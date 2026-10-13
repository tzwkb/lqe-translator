# Standalone LQE maintenance

- This repository is maintained independently from `AI Translation Tool Intergration`.
- Integration performance, token, cost, model-effort, combined-checker and acceptance-policy experiments must not be copied here merely to keep the two products aligned.
- Standalone behavior changes must serve an explicit standalone requirement and be validated for this module. Integration acceptance does not establish standalone acceptance.
- New standalone automatic jobs prioritize quality: strict historical-issue adjudication, separate specialist checker identities, and full intermediate re-review by default. Do not silently lower model reasoning effort or combine specialists to save cost.
- Main includes the quality-first standalone workflow developed on `codex/lqe-quality-first-20261014`: autonomous iteration, issue history and native safety checks are retained, and the integration-oriented cost defaults are reverted. Keep the development branch for traceability.
- The earlier `codex/lqe-shared-workflow-20261009` branch at `f5a623c7fead3148ec41ebf3dc64d70526f721df` and maintenance-only branch are preserved as unmerged history. Their integration-oriented defaults are not the quality-first policy.
- Do not update the globally installed skill as a side effect of integration work.
