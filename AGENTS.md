# Standalone LQE maintenance

- This repository is maintained independently from `AI Translation Tool Intergration`.
- Integration performance, token, cost, model-effort, combined-checker and acceptance-policy experiments must not be copied here merely to keep the two products aligned.
- Standalone behavior changes must serve an explicit standalone requirement and be validated for this module. Integration acceptance does not establish standalone acceptance.
- The `codex/lqe-independent-maintenance-20261013` branch starts from the existing `main` code at `6ab00122cce6428d2411372b40ceace96aa8b157` and adds maintenance guidance only.
- The earlier `codex/lqe-shared-workflow-20261009` branch at `f5a623c7fead3148ec41ebf3dc64d70526f721df` is preserved as unmerged development history. Its automatic-workflow and cost-related changes are not the standalone baseline.
- Do not update the globally installed skill as a side effect of integration work.
